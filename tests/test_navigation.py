from datetime import UTC, datetime

import pytest
from aiogram import Bot
from aiogram.types import (
    CallbackQuery,
    Chat,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
    User,
)

from tutor.config import Settings
from tutor.engine import TutorEngine
from tutor.mcp_client import connect_tools
from tutor.telegram import build_dispatcher

from .fakes import FakeTutor
from .test_engine import LocalTools, prepare
from .test_llm_telegram import TelegramSession


async def test_profile_shortcuts_back_and_stale_choices(tmp_path):
    tools, model = LocalTools(tmp_path / "navigation.db"), FakeTutor()
    engine = TutorEngine(tools, model)
    start = await engine.handle(1, "/start")
    assert "Шаг 1/4" in start.text
    assert "/switch ID" not in start.text
    experience = await engine.handle(1, "Освоить Go")
    assert "choose_experience_zero" in experience.actions
    await engine.handle(1, "/choose experience_zero", experience.revision)
    before_back = tools.store.load(1)
    back = await engine.handle(1, "/back", before_back["revision"])
    assert "Шаг 2/4" in back.text
    stale = await engine.handle(1, "/choose time_short", before_back["revision"])
    assert "устарело" in stale.text
    wrong_step = await engine.handle(1, "/choose deadline_none")
    assert "уже не относится" in wrong_step.text
    await engine.handle(1, "Знаю Python")
    await engine.handle(1, "/choose time_regular")
    reply = await engine.handle(1, "/choose deadline_none")
    state = tools.store.load(1)["state"]
    assert state["minutes_per_session"] == 30
    assert state["sessions_per_week"] == 3
    assert state["deadline"] == "без срока"
    assert state["experience"] == "Знаю Python"
    assert state["stage"] == "diagnostic"
    assert "Ответьте одним сообщением" in reply.text
    assert [kind for kind, _ in model.calls] == ["diagnostic"]


async def test_continue_restores_current_task_without_regenerating(tmp_path):
    tools, model = LocalTools(tmp_path / "navigation.db"), FakeTutor()
    engine = TutorEngine(tools, model)
    await prepare(engine)
    first = await engine.handle(1, "/continue")
    snapshot = tools.store.load(1)
    calls = len(model.calls)
    for text in ["/menu", "/plan", "/progress", "/skills", "/start", "/continue"]:
        reply = await engine.handle(1, text)
    assert snapshot["state"]["lesson"]["task"] in reply.text
    assert tools.store.load(1) == snapshot
    assert len(model.calls) == calls
    assert first.action_labels["lesson"] == "Вернуться к заданию"


async def test_question_mode_survives_restart_and_switch_and_does_not_grade(tmp_path):
    tools, model = LocalTools(tmp_path / "navigation.db"), FakeTutor()
    engine = TutorEngine(tools, model)
    await prepare(engine)
    await engine.handle(1, "/continue")
    await engine.handle(1, "/ask")
    first = tools.store.load(1)
    await engine.handle(1, "/newskill Выучить испанский")
    restarted = TutorEngine(LocalTools(tools.store.path), model)
    restored = await restarted.handle(1, f"/switch {first['skill_id']}")
    assert "Жду вопрос" in restored.text
    reply = await restarted.handle(1, "Что такое error?")
    state = tools.store.load(1)["state"]
    assert model.calls[-1][0] == "ask"
    assert not state["attempts"]
    assert state["hints_used"] == 1
    assert state["input_mode"] == "answer"
    assert "отправить ответ" in reply.text
    await restarted.handle(1, "if err != nil { return err }")
    assert model.calls[-1][0] == "grade"
    assert len(tools.store.load(1)["state"]["attempts"]) == 1


async def test_cancel_question_returns_to_answer_and_model_failure_keeps_mode(tmp_path):
    tools, model = LocalTools(tmp_path / "navigation.db"), FakeTutor()
    engine = TutorEngine(tools, model)
    await prepare(engine)
    await engine.handle(1, "/continue")
    await engine.handle(1, "/ask")
    before = tools.store.load(1)
    model.fail = True
    with pytest.raises(RuntimeError):
        await engine.handle(1, "Вопрос без slash-команды")
    assert tools.store.load(1) == before
    model.fail = False
    cancelled = await engine.handle(1, "/continue")
    state = tools.store.load(1)["state"]
    assert state["input_mode"] == "answer"
    assert not state["attempts"]
    assert state["hints_used"] == 0
    assert state["lesson"]["task"] in cancelled.text


async def test_telegram_navigation_entire_flow_with_buttons_and_real_mcp(tmp_path):
    session = TelegramSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    user, chat = User(id=1, is_bot=False, first_name="Student"), Chat(id=1, type="private")
    counter = 0
    model = FakeTutor()
    async with connect_tools(tmp_path / "navigation.db") as tools:
        dispatcher = build_dispatcher(TutorEngine(tools, model), Settings())

        async def feed(text=None, *, callback=None):
            nonlocal counter
            counter += 1
            message = Message(
                message_id=counter, date=datetime.now(UTC), chat=chat, from_user=user, text=text
            )
            await dispatcher.feed_update(
                bot,
                Update(update_id=counter, message=message)
                if callback is None
                else Update(
                    update_id=counter,
                    callback_query=CallbackQuery(
                        id=str(counter),
                        from_user=user,
                        chat_instance="private",
                        message=message,
                        data=callback,
                    ),
                ),
            )

        def button(action):
            return next(
                b.callback_data
                for row in session.sent[-1].reply_markup.inline_keyboard
                for b in row
                if b.callback_data.startswith(action + ":")
            )

        await feed("/start")
        menu = session.sent[0].reply_markup
        assert isinstance(menu, ReplyKeyboardMarkup) and not menu.is_persistent
        labels = [b.text for row in menu.keyboard for b in row]
        assert "▶️ Продолжить" in labels and "📚 Мои навыки" in labels
        await feed("⌨️ Скрыть меню")
        assert isinstance(session.sent[-1].reply_markup, ReplyKeyboardRemove)
        # Visibility isn't tied to an in-memory flag that resets on restart.
        dispatcher = build_dispatcher(TutorEngine(tools, model), Settings())
        hidden_since = len(session.sent)
        await feed("/progress")
        assert not any(
            isinstance(m.reply_markup, ReplyKeyboardMarkup) for m in session.sent[hidden_since:]
        )
        assert not model.calls
        await feed("/menu")
        assert isinstance(session.sent[-2].reply_markup, ReplyKeyboardMarkup)
        await feed("Освоить Go")
        await feed(callback=button("choose_experience_zero"))
        await feed(callback=button("choose_time_regular"))
        await feed(callback=button("choose_deadline_none"))
        await feed("Не знаю")
        old_home = button("home")
        await feed(callback=button("accept"))
        await feed(callback=button("lesson"))
        await feed(callback=button("ask"))
        await feed("Что значит error?")
        snapshot = await tools.call("get_learning_state", user_id=1)
        assert not snapshot["state"]["attempts"]
        assert model.calls[-1][0] == "ask"
        await feed("📈 Прогресс")
        assert "Пройдено этапов" in session.sent[-1].text
        # Old navigation opens today's screen; it doesn't replay an old learning action.
        await feed(callback=old_home)
        assert "Главное меню" in session.sent[-1].text
        assert "устарело" not in session.sent[-1].text
        old_newskill = button("newskill")
        await feed("▶️ Продолжить")
        assert snapshot["state"]["lesson"]["task"] in session.sent[-1].text
        await feed("if err != nil { return err }")
        assert "Следующее занятие" in [
            b.text for row in session.sent[-1].reply_markup.inline_keyboard for b in row
        ]
        before_schedule = await tools.call("get_learning_state", user_id=1)
        await feed("⏰ Напоминания")
        await feed(callback=button("remind_weekdays"))
        schedule = await tools.call("get_reminder", user_id=1)
        assert schedule["enabled"] and schedule["hour"] == 19
        assert schedule["days"] == "[1, 2, 3, 4, 5]"
        await feed(callback=button("remind"))
        await feed(callback=button("remind_off"))
        assert not (await tools.call("get_reminder", user_id=1))["enabled"]
        assert await tools.call("get_learning_state", user_id=1) == before_schedule
        await feed("➕ Новый навык")
        assert "Шаг 1/4" in session.sent[-1].text
        await feed("Выучить испанский")
        before_stale = await tools.call("get_learning_state", user_id=1)
        await feed(callback=old_newskill)
        assert "устарело" in session.sent[-1].text
        assert await tools.call("get_learning_state", user_id=1) == before_stale
        await feed("📚 Мои навыки")
        await feed(callback=button(f"switch_{snapshot['skill_id']}"))
        assert "Освоить Go" in session.sent[-1].text
        assert "Занятие 2 из 3" in session.sent[-1].text
    await bot.session.close()
