import asyncio
import json
import logging
import time
from collections import defaultdict, deque

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from aiogram.utils.chat_action import ChatActionSender
from pydantic import ValidationError

from tutor.config import Settings
from tutor.engine import PROFILE_CHOICES, Reply, TutorEngine
from tutor.llm import ModelError
from tutor.mcp_client import ToolError
from tutor.scheduling import parse_schedule

logger = logging.getLogger(__name__)
LABELS = {
    "accept": "Принять план",
    "lesson": "Занятие",
    "hint": "Подсказка",
    "progress": "Прогресс",
    "plan": "План",
    "reset_confirm": "Удалить выбранный навык",
    "skills": "Мои навыки",
    "newskill": "Добавить навык",
    "budget_resume": "Проверить лимит и продолжить",
    "home": "Главное меню",
    "continue": "Продолжить обучение",
    "back": "← Назад",
    "ask": "Задать вопрос",
    "cancel": "К заданию",
    "remind": "Напоминания",
    "remind_daily": "Каждый день в 19:00",
    "remind_weekdays": "По будням в 19:00",
    "remind_off": "Выключить напоминания",
    "snooze": "Напомнить через час",
}

MENU_ACTIONS = {
    "▶️ Продолжить": "/continue",
    "📚 Мои навыки": "/skills",
    "🗺 План": "/plan",
    "📈 Прогресс": "/progress",
    "➕ Новый навык": "/newskill",
    "⏰ Напоминания": "/remind",
    "🏠 Главное меню": "/menu",
    "ℹ️ Помощь": "/help",
    "⌨️ Скрыть меню": "/hide_menu",
}


def main_menu() -> ReplyKeyboardMarkup:
    labels = list(MENU_ACTIONS)
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=label) for label in labels[index : index + 2]]
            for index in range(0, len(labels), 2)
        ],
        resize_keyboard=True,
        is_persistent=False,
        input_field_placeholder="Ответ на текущий шаг или действие из меню",
    )


def chunks(text: str, limit: int = 3800) -> list[str]:
    """Telegram measures limits in UTF-16 code units, including emoji."""
    result, current, length = [], [], 0
    for char in text:
        size = 2 if ord(char) > 0xFFFF else 1
        if length + size > limit:
            result.append("".join(current))
            current, length = [], 0
        current.append(char)
        length += size
    if current:
        result.append("".join(current))
    return result or ["Готово."]


def keyboard(reply: Reply) -> InlineKeyboardMarkup | None:
    if not reply.actions:
        return None
    rows = []
    groups = {"hint": "help", "ask": "help", "skills": "nav", "home": "nav"}
    previous_group = None
    for action in reply.actions:
        button = InlineKeyboardButton(
            text=reply.action_labels.get(action, LABELS.get(action, action)),
            callback_data=f"{action}:{reply.revision}",
        )
        group = groups.get(action)
        if group and group == previous_group and len(rows[-1]) == 1:
            rows[-1].append(button)
        else:
            rows.append([button])
        previous_group = group
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def send_reply(bot: Bot, chat_id: int, reply: Reply) -> None:
    parts = chunks(reply.text)
    for index, text in enumerate(parts):
        await bot.send_message(
            chat_id,
            text,
            reply_markup=keyboard(reply) if index == len(parts) - 1 else None,
        )


def build_dispatcher(engine: TutorEngine, settings: Settings) -> Dispatcher:
    router = Router()
    locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
    requests: dict[int, deque[float]] = defaultdict(deque)

    def allowed(user_id: int) -> bool:
        return not settings.allowed_ids or user_id in settings.allowed_ids

    async def process(bot: Bot, user_id: int, chat_id: int, text: str, revision=None):
        if not allowed(user_id):
            await bot.send_message(
                chat_id, "Этот учебный бот пока доступен только участникам тестирования."
            )
            return
        if locks[user_id].locked():
            await bot.send_message(chat_id, "Обрабатываю предыдущее сообщение. Дождитесь ответа.")
            return
        async with locks[user_id]:
            if text == "/hide_menu":
                await bot.send_message(
                    chat_id,
                    "Меню скрыто. Вернуть его можно командой /menu.",
                    reply_markup=ReplyKeyboardRemove(),
                )
                return
            if text in {"/start", "/menu", "/home"}:
                await bot.send_message(
                    chat_id,
                    "Меню доступно под полем ввода. «Продолжить» вернёт к текущему шагу обучения.",
                    reply_markup=main_menu(),
                )
            read_only = text.split(maxsplit=1)[0] in {
                "/start",
                "/help",
                "/plan",
                "/progress",
                "/remind",
                "/snooze",
                "/reset",
                "/reset_confirm",
                "/skills",
                "/newskill",
                "/switch",
                "/budget",
                "/budget_resume",
                "/menu",
                "/home",
                "/back",
                "/cancel",
                "/remind_daily",
                "/remind_weekdays",
                "/remind_off",
            }
            now = time.monotonic()
            queue = requests[user_id]
            while queue and queue[0] <= now - 3600:
                queue.popleft()
            if not read_only and len(queue) >= settings.max_requests_per_hour:
                await bot.send_message(
                    chat_id, "Лимит учебных запросов на час исчерпан. Попробуйте позже."
                )
                return
            if not read_only:
                queue.append(now)
            try:
                if text in {"/remind", "/remind_daily", "/remind_weekdays", "/remind_off"}:
                    if text != "/remind":
                        text = {
                            "/remind_daily": (
                                f"/remind 19:00 {settings.default_timezone} 1,2,3,4,5,6,7"
                            ),
                            "/remind_weekdays": (
                                f"/remind 19:00 {settings.default_timezone} 1,2,3,4,5"
                            ),
                            "/remind_off": "/remind off",
                        }[text]
                if text == "/remind":
                    schedule = await engine.tools.call("get_reminder", user_id=user_id)
                    if schedule and schedule["enabled"]:
                        weekdays = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
                        days = ", ".join(weekdays[d - 1] for d in json.loads(schedule["days"]))
                        message = (
                            f"Напоминания: {schedule['hour']:02}:{schedule['minute']:02} "
                            f"{schedule['timezone']}\nДни: {days}\n"
                        )
                    else:
                        message = "Напоминания выключены.\n"
                    snapshot = await engine.tools.call("get_learning_state", user_id=user_id)
                    await send_reply(
                        bot,
                        chat_id,
                        Reply(
                            message
                            + f"\nБыстрые варианты: часовой пояс {settings.default_timezone}.\n"
                            "Для своего времени: /remind 19:00 Europe/Moscow 1,3,5",
                            ["remind_daily", "remind_weekdays"]
                            + (["snooze", "remind_off"] if schedule.get("enabled") else [])
                            + ["home"],
                            snapshot["revision"],
                        ),
                    )
                    return
                if text.startswith("/remind "):
                    value = text.split(maxsplit=1)[1].strip()
                    if value.lower() == "off":
                        await engine.tools.call("disable_reminder", user_id=user_id)
                        message = "Напоминания отключены."
                    else:
                        hour, minute, zone, days = parse_schedule(value, settings.default_timezone)
                        await engine.tools.call(
                            "set_reminder",
                            user_id=user_id,
                            chat_id=chat_id,
                            schedule=value,
                            default_timezone=settings.default_timezone,
                        )
                        message = (
                            f"Буду напоминать в {hour:02}:{minute:02} ({zone}), "
                            f"дни: {','.join(map(str, days))}."
                        )
                    await send_reply(bot, chat_id, Reply(message, ["remind", "home"]))
                    return
                if text == "/snooze":
                    result = await engine.tools.call("snooze_reminder", user_id=user_id)
                    await send_reply(
                        bot,
                        chat_id,
                        Reply(
                            "Напомню через час."
                            if result["ok"]
                            else "Сначала включите напоминания кнопкой ниже.",
                            ["remind", "home"],
                        ),
                    )
                    return
                async with ChatActionSender.typing(bot=bot, chat_id=chat_id):
                    reply = await engine.handle(user_id, text, revision)
                await send_reply(bot, chat_id, reply)
            except ValidationError:
                await bot.send_message(
                    chat_id, "Ответ модели не прошёл проверку формата. Повторите действие."
                )
            except ValueError as exc:
                # Only local schedule/input validation is exposed; no provider errors.
                logger.warning("validation_error=%s", type(exc).__name__)
                await bot.send_message(
                    chat_id, "Проверьте формат команды. Пример: /remind 19:00 Europe/Moscow 1,3,5"
                )
            except ModelError as exc:
                await bot.send_message(chat_id, str(exc))
            except ToolError:
                await bot.send_message(
                    chat_id, "Хранилище временно недоступно. Повторите действие позже."
                )
            except Exception as exc:
                logger.error("request_failed=%s", type(exc).__name__)
                await bot.send_message(
                    chat_id,
                    "Не удалось завершить действие. Повторите его. "
                    "Если ответ уже сохранён, проверьте /progress.",
                )

    @router.message(F.chat.type == ChatType.PRIVATE)
    async def message_handler(message: Message, bot: Bot):
        if not message.from_user:
            return
        if not message.text:
            await message.answer(
                "В MVP принимаю текст. Код можно отправить текстом одним сообщением."
            )
            return
        text = message.text.strip()
        if not text:
            await message.answer("Отправьте текст или команду /help.")
            return
        # Deep links and command mentions must not become learning goals.
        if text.startswith("/start "):
            text = "/start"
        if text.startswith("/"):
            command, *rest = text.split(maxsplit=1)
            text = command.split("@")[0] + ((" " + rest[0]) if rest else "")
        text = MENU_ACTIONS.get(text, text)
        await process(bot, message.from_user.id, message.chat.id, text)

    @router.callback_query()
    async def callback_handler(callback: CallbackQuery, bot: Bot):
        await callback.answer()
        if (
            not isinstance(callback.message, Message)
            or callback.message.chat.type != ChatType.PRIVATE
        ):
            return
        try:
            action, revision = (callback.data or "").split(":")
            if action.startswith("switch_") and action[7:].isdigit():
                command = "/switch " + action[7:]
            elif action.startswith("skills_page_") and action[12:].isdigit():
                command = "/skills " + action[12:]
            elif action.startswith("choose_") and action[7:] in PROFILE_CHOICES:
                command = "/choose " + action[7:]
            elif action in LABELS:
                command = "/" + action
            else:
                return
            expected = int(revision)
        except ValueError:
            return
        # Remove old buttons immediately; version checks also reject duplicated callbacks.
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        # Navigation doesn't mutate learning; an old menu can safely open the current view.
        if action in {
            "home",
            "skills",
            "plan",
            "progress",
            "remind",
        } or action.startswith("skills_page_"):
            expected = None
        await process(bot, callback.from_user.id, callback.message.chat.id, command, expected)

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def set_commands(bot: Bot) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command=command, description=description)
            for command, description in [
                ("start", "Начать или продолжить"),
                ("menu", "Главное меню и навигация"),
                ("hide_menu", "Скрыть меню под полем ввода"),
                ("continue", "Продолжить с текущего шага"),
                ("skills", "Мои навыки и переключение"),
                ("newskill", "Добавить навык"),
                ("switch", "Выбрать навык по ID"),
                ("budget", "Общий суточный расход модели"),
                ("plan", "Учебный план"),
                ("lesson", "Получить занятие"),
                ("hint", "Подсказка"),
                ("ask", "Задать вопрос по теме"),
                ("progress", "Прогресс и ошибки"),
                ("remind", "Настроить напоминания"),
                ("snooze", "Напомнить через час"),
                ("reset", "Удалить выбранный навык"),
                ("help", "Все команды"),
            ]
        ]
    )
