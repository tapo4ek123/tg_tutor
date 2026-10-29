import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)


class ToolError(RuntimeError):
    pass


class LearningTools:
    def __init__(self, session: ClientSession):
        self.session = session

    async def call(self, name: str, **arguments) -> dict:
        # Log tool names only: neither learner answers nor provider tokens.
        logger.info("mcp.tool=%s", name)
        result = await self.session.call_tool(name, arguments)
        if result.isError:
            raise ToolError(f"Инструмент {name} не смог выполнить действие.")
        for item in result.content:
            if item.type == "text":
                return json.loads(item.text)
        raise ToolError(f"Пустой ответ инструмента {name}.")


@asynccontextmanager
async def connect_tools(database_path: Path):
    # Strip API/bot credentials from the child: MCP only needs its DB path.
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "SYSTEMROOT", "TMPDIR", "LANG", "PYTHONPATH"}
    }
    env["DATABASE_PATH"] = str(await asyncio.to_thread(database_path.resolve))
    params = StdioServerParameters(command=sys.executable, args=["-m", "tutor.mcp_server"], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(
            read, write, read_timeout_seconds=timedelta(seconds=30)
        ) as session:
            await session.initialize()
            yield LearningTools(session)
