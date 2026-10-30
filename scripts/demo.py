"""Offline smoke demo: real MCP and DB, deterministic fixture instead of paid API."""

import asyncio
import tempfile
from pathlib import Path

from tests.fakes import FakeTutor
from tutor.engine import TutorEngine
from tutor.mcp_client import connect_tools


async def main():
    print("OFFLINE DEMO: fixture-ответы, это НЕ результат DeepSeek V4.1 Flash. MCP настоящий.\n")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "demo.sqlite3"
        async with connect_tools(path) as tools:
            engine = TutorEngine(tools, FakeTutor())
            for text in [
                "/start",
                "Освоить Go и написать CLI",
                "Знаю Python",
                "30 3",
                "Через месяц",
                "Не знаю",
                "/accept",
                "/lesson",
                "Не знаю",
                "/progress",
                "/lesson",
                "if err != nil { return err }; затем используем результат",
                "/progress",
            ]:
                reply = await engine.handle(1, text)
                print(f"УЧЕНИК: {text}\nТЬЮТОР: {reply.text}\n")
        async with connect_tools(path) as tools:
            reply = await TutorEngine(tools, FakeTutor()).handle(1, "/progress")
            print("ПОСЛЕ ПЕРЕЗАПУСКА MCP:\n" + reply.text)


if __name__ == "__main__":
    asyncio.run(main())
