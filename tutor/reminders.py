import asyncio
import logging
from pathlib import Path

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


async def deliver_reminders(bot: Bot, tools) -> None:
    claimed = await tools.call("claim_due_reminders")
    for reminder in claimed["reminders"]:
        user_id = reminder["user_id"]
        retry = 0
        try:
            catalog = await tools.call("list_skills", user_id=user_id)
            active = [s for s in catalog["skills"] if s["stage"] != "done"]
            if not active:
                await tools.call("disable_reminder", user_id=user_id)
                continue
            visible = active[:10]
            topics = "\n".join(f"• {(s['goal'] or 'Новый навык')[:100]}" for s in visible)
            await bot.send_message(
                reminder["chat_id"],
                f"Время небольшой практики! Выберите навык:\n{topics}\n"
                "Отложить на час: /snooze · Отключить: /remind off",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[
                        [
                            InlineKeyboardButton(
                                text=(skill["goal"] or "Новый навык")[:45],
                                callback_data=f"switch_{skill['skill_id']}:{catalog['revision']}",
                            )
                        ]
                        for skill in visible
                    ]
                    + [
                        [
                            InlineKeyboardButton(
                                text="Все навыки", callback_data=f"skills:{catalog['revision']}"
                            )
                        ]
                    ]
                ),
            )
            await asyncio.sleep(0.05)  # Respect Telegram broadcast rate limits.
        except TelegramForbiddenError:
            await tools.call("disable_reminder", user_id=user_id)
            continue
        except TelegramRetryAfter as exc:
            retry = exc.retry_after + 1
        except Exception as exc:
            logger.warning("reminder_delivery_failed=%s", type(exc).__name__)
            retry = 300
        await tools.call(
            "finish_reminder",
            user_id=user_id,
            scheduled_due=reminder["next_due"],
            retry_seconds=retry,
        )


async def reminder_loop(bot: Bot, tools, interval: int, heartbeat: Path) -> None:
    await asyncio.to_thread(heartbeat.parent.mkdir, parents=True, exist_ok=True)
    while True:
        try:
            await deliver_reminders(bot, tools)
            await asyncio.to_thread(heartbeat.touch)
        except Exception as exc:
            logger.error("scheduler_failed=%s", type(exc).__name__)
        await asyncio.sleep(interval)
