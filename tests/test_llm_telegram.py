from datetime import datetime

import httpx
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import Chat, Message, Update, User
from openai import AsyncOpenAI

from tutor.config import Settings
from tutor.engine import TutorEngine
from tutor.llm import DeepSeekTutor
from tutor.models import Diagnostic
from tutor.telegram import build_dispatcher, chunks

from .fakes import FakeTutor
from .test_engine import LocalTools


async def test_deepseek_responses_contract():
    import json

    seen = []
    urls = []

    def respond(request):
        urls.append(str(request.url))
        data = json.loads(request.content)
        seen.append(data)
        return httpx.Response(
            200,
            json={
                "id": "resp_fixture",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "deepseek-flash",
                "usage": {
                    "input_tokens": 100,
                    "input_tokens_details": {"cached_tokens": 0},
                    "output_tokens": 20,
                    "output_tokens_details": {"reasoning_tokens": 0},
                    "total_tokens": 120,
                },
                "output": [
                    {
                        "type": "message",
                        "id": "msg_fixture",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "annotations": [],
                                "text": json.dumps(
                                    {
                                        "introduction": "Проверим знания",
                                        "questions": ["Вопрос 1", "Вопрос 2"],
                                    }
                                ),
                            }
                        ],
                    }
                ],
            },
        )

    model = DeepSeekTutor(Settings(deepseek_api_key="test-key"))
    await model.client.close()
    model.client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://api.deepseek.com",
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    result = await model.generate("diagnostic", Diagnostic, {"goal": "Go"})
    assert len(result.questions) == 2
    assert urls == ["https://api.deepseek.com/responses"]
    assert seen[0]["model"] == "deepseek-flash"
    assert seen[0]["text"]["format"]["strict"] is True
    assert "store" not in seen[0]
    assert "service_tier" not in seen[0]
    await model.close()


def test_telegram_utf16_split():
    text = "😀" * 4000 + "abc"
    parts = chunks(text)
    assert "".join(parts) == text
    assert all(len(part.encode("utf-16-le")) // 2 <= 3800 for part in parts)


class TelegramSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):  # noqa: ASYNC109 - aiogram interface
        if isinstance(method, SendMessage):
            self.sent.append(method)
            return Message(
                message_id=len(self.sent),
                date=datetime.now(),
                chat=Chat(id=method.chat_id, type="private"),
                text=method.text,
            )
        return True

    async def stream_content(self, *args, **kwargs):
        yield b""


async def test_dispatcher_private_chat_and_access_control(tmp_path):
    session = TelegramSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    tools = LocalTools(tmp_path / "telegram.db")
    engine = TutorEngine(tools, FakeTutor())
    dispatcher = build_dispatcher(engine, Settings(allowed_user_ids="1"))

    async def feed(user_id, text, kind="private"):
        await dispatcher.feed_update(
            bot,
            Update(
                update_id=user_id,
                message=Message(
                    message_id=1,
                    date=datetime.now(),
                    chat=Chat(id=user_id, type=kind),
                    from_user=User(id=user_id, is_bot=False, first_name="Test"),
                    text=text,
                ),
            ),
        )

    await feed(2, "Хочу Go")
    assert "участникам тестирования" in session.sent[-1].text
    assert tools.store.load(2)["revision"] == 0
    await feed(1, "/start")
    assert "Какой навык" in session.sent[-1].text
    await feed(1, "Хочу освоить Go")
    assert tools.store.load(1)["state"]["stage"] == "experience"
    count = len(session.sent)
    await feed(1, "Текст из группы", "group")
    assert len(session.sent) == count
    await bot.session.close()
