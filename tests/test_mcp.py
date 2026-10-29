import pytest

from tutor.engine import TutorEngine
from tutor.mcp_client import ToolError, connect_tools

from .fakes import FakeTutor
from .test_engine import prepare


async def test_real_mcp_roundtrip_and_restart(tmp_path):
    path = tmp_path / "integration.sqlite3"
    async with connect_tools(path) as tools:
        names = {tool.name for tool in (await tools.session.list_tools()).tools}
        assert {"get_learning_state", "save_learning_state", "search_materials"} <= names
        engine = TutorEngine(tools, FakeTutor())
        await prepare(engine)
        await engine.handle(1, "/lesson")
        await engine.handle(1, "Не знаю")
        snapshot = await tools.call("get_learning_state", user_id=1)
        assert snapshot["state"]["adaptations"]
        assert (await tools.call("get_learning_state", user_id=2))["state"]["goal"] == ""
        with pytest.raises(ToolError):
            await tools.call("save_learning_state", user_id=1, revision=0, state=snapshot["state"])
        materials = await tools.call("search_materials", query="Хочу выучить Go")
        assert materials["materials"][0]["url"] == "https://go.dev/tour/"
        await tools.call(
            "set_reminder",
            user_id=1,
            chat_id=1,
            schedule="19:00 Europe/Moscow 1,3,5",
            default_timezone="UTC",
        )
    async with connect_tools(path) as tools:
        assert (await tools.call("get_learning_state", user_id=1)) == snapshot
        assert (await tools.call("get_reminder", user_id=1))["enabled"] == 1
        await tools.call("reset_learning_state", user_id=1)
        assert not await tools.call("get_reminder", user_id=1)
