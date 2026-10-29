from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from tutor.reminders import deliver_reminders

from .test_llm_telegram import TelegramSession


class ReminderTools:
    def __init__(self):
        self.calls = []
        self.stage = "learning"

    async def call(self, name, **args):
        self.calls.append((name, args))
        if name == "claim_due_reminders":
            return {"reminders": [{"user_id": 1, "chat_id": 1, "next_due": 10.0}]}
        if name == "list_skills":
            return {
                "revision": 3,
                "skills": [
                    {
                        "skill_id": 1,
                        "goal": "Go: ошибки",
                        "stage": self.stage,
                    }
                ],
            }
        return {"ok": True}


async def test_notification_delivery_and_completion():
    tools = ReminderTools()
    session = TelegramSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    await deliver_reminders(bot, tools)
    assert "Go: ошибки" in session.sent[0].text
    assert tools.calls[-1] == (
        "finish_reminder",
        {
            "user_id": 1,
            "scheduled_due": 10.0,
            "retry_seconds": 0,
        },
    )
    tools.stage = "done"
    await deliver_reminders(bot, tools)
    assert len(session.sent) == 1
    assert tools.calls[-1][0] == "disable_reminder"
    await bot.session.close()


async def test_blocked_user_disables_and_rate_limit_retries():
    class FailingSession(TelegramSession):
        failure = "blocked"

        async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109
            if isinstance(method, SendMessage):
                if self.failure == "blocked":
                    raise TelegramForbiddenError(method, "blocked")
                raise TelegramRetryAfter(method, "rate limit", retry_after=42)
            return True

    session = FailingSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    tools = ReminderTools()
    await deliver_reminders(bot, tools)
    assert tools.calls[-1][0] == "disable_reminder"
    session.failure = "rate_limit"
    await deliver_reminders(bot, tools)
    assert tools.calls[-1][1]["retry_seconds"] == 43
    await bot.session.close()
