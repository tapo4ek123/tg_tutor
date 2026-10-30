from datetime import UTC, datetime

from aiogram import Bot
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from tutor.config import Settings
from tutor.engine import TutorEngine
from tutor.mcp_client import connect_tools
from tutor.telegram import build_dispatcher

from .fakes import FakeTutor
from .test_llm_telegram import TelegramSession


async def test_telegram_to_engine_to_real_mcp_to_sqlite(tmp_path):
    path = tmp_path / "e2e.db"
    session = TelegramSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    user = User(id=1, is_bot=False, first_name="Student")
    chat = Chat(id=1, type="private")
    counter = 0
    async with connect_tools(path) as tools:
        dispatcher = build_dispatcher(TutorEngine(tools, FakeTutor()), Settings())

        async def send(text):
            nonlocal counter
            counter += 1
            await dispatcher.feed_update(
                bot,
                Update(
                    update_id=counter,
                    message=Message(
                        message_id=counter,
                        date=datetime.now(UTC),
                        chat=chat,
                        from_user=user,
                        text=text,
                    ),
                ),
            )

        for text in ["/start", "Выучить Go", "Знаю Python", "30 3", "Без срока", "Не знаю"]:
            await send(text)
        button = session.sent[-1].reply_markup.inline_keyboard[0][0]
        assert button.callback_data.startswith("accept:")
        counter += 1
        await dispatcher.feed_update(
            bot,
            Update(
                update_id=counter,
                callback_query=CallbackQuery(
                    id="fixture",
                    from_user=user,
                    chat_instance="private",
                    data=button.callback_data,
                    message=Message(message_id=10, date=datetime.now(UTC), chat=chat, text="План"),
                ),
            ),
        )
        await send("/lesson")
        await send("Не знаю")
        assert "План скорректирован" in session.sent[-1].text
        await send("/remind 19:00 Europe/Moscow 1,3,5")
        assert (await tools.call("get_reminder", user_id=1))["enabled"] == 1
        await send("/snooze")
        assert "через час" in session.sent[-1].text
        await send("/remind off")
        assert not (await tools.call("get_reminder", user_id=1))["enabled"]
    async with connect_tools(path) as tools:
        assert len((await tools.call("get_learning_state", user_id=1))["state"]["attempts"]) == 1
    await bot.session.close()


async def test_telegram_budget_button_resume_and_skill_switch(tmp_path):
    from datetime import timedelta
    from decimal import Decimal

    from tutor.budget import BudgetLedger, units

    now = [datetime(2026, 10, 27, 20, 59, tzinfo=UTC)]
    budget = BudgetLedger(
        Settings(_env_file=None, budget_database_path=tmp_path / "budget.db"), lambda: now[0]
    )
    reservation = budget.reserve(units(Decimal(3)), "deepseek-flash")
    budget.settle(reservation, units(Decimal(3)))

    class BudgetedTutor(FakeTutor):
        async def generate(self, *args):
            hold = self.budget.reserve(100, "deepseek-flash")
            self.budget.settle(hold, 100)
            return await super().generate(*args)

    model = BudgetedTutor()
    model.budget = budget
    session = TelegramSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    user = User(id=1, is_bot=False, first_name="Student")
    chat = Chat(id=1, type="private")
    counter = 0
    async with connect_tools(tmp_path / "learning.db") as tools:
        dispatcher = build_dispatcher(TutorEngine(tools, model), Settings())

        async def feed(text=None, callback=None):
            nonlocal counter
            counter += 1
            message = Message(
                message_id=counter, date=datetime.now(UTC), chat=chat, from_user=user, text=text
            )
            update = (
                Update(update_id=counter, message=message)
                if callback is None
                else Update(
                    update_id=counter,
                    callback_query=CallbackQuery(
                        id=str(counter),
                        from_user=user,
                        chat_instance="private",
                        data=callback,
                        message=message,
                    ),
                )
            )
            await dispatcher.feed_update(bot, update)

        def button(prefix):
            return next(
                b
                for row in session.sent[-1].reply_markup.inline_keyboard
                for b in row
                if b.callback_data.startswith(prefix)
            )

        for text in ["Освоить Go", "Знаю Python", "30 3", "без срока"]:
            await feed(text)
        assert "Недостаточно суточного бюджета" in session.sent[-1].text
        assert button("budget_resume:").text == "Проверить лимит и продолжить"
        await feed(callback=button("budget_resume:").callback_data)
        assert model.calls == []
        now[0] += timedelta(minutes=2)
        await feed(callback=button("budget_resume:").callback_data)
        first = await tools.call("get_learning_state", user_id=1)
        assert first["state"]["stage"] == "diagnostic"
        assert first["state"]["pending_request"] is None
        await feed("/newskill Выучить испанский")
        await feed("/skills")
        await feed(callback=button(f"switch_{first['skill_id']}:").callback_data)
        assert "Навык выбран" in session.sent[-1].text
        assert "Освоить Go" in session.sent[-1].text
        assert (await tools.call("get_learning_state", user_id=1))["state"] == first["state"]
    await bot.session.close()
