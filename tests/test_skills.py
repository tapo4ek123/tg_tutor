import sqlite3
from datetime import UTC, datetime

import pytest

from tutor.engine import TutorEngine
from tutor.mcp_client import connect_tools
from tutor.models import LearningState, Plan
from tutor.storage import ConflictError, Store

from .fakes import FakeTutor, lesson_fixture
from .test_engine import LocalTools, prepare


async def test_independent_skills_restore_pending_lesson_and_hints(tmp_path):
    tools = LocalTools(tmp_path / "skills.db")
    engine = TutorEngine(tools, FakeTutor())
    await prepare(engine)
    await engine.handle(1, "/lesson")
    await engine.handle(1, "/hint")
    first = tools.store.load(1)
    await engine.handle(1, "/newskill Выучить испанский")
    second = tools.store.load(1)
    assert second["skill_id"] != first["skill_id"]
    assert second["state"]["stage"] == "experience"
    assert not second["state"]["attempts"] and second["state"]["lesson"] is None
    assert len(tools.store.list_skills(1)["skills"]) == 2
    stale = await engine.handle(1, "/hint", first["revision"])
    assert "устарело" in stale.text
    assert tools.store.load(1) == second
    await engine.handle(1, f"/switch {first['skill_id']}")
    assert tools.store.load(1)["state"] == first["state"]
    await engine.handle(1, "if err != nil { return err }")
    assert tools.store.load(1)["state"]["module_index"] == 1
    await engine.handle(1, f"/switch {second['skill_id']}")
    assert tools.store.load(1)["state"] == second["state"]


async def test_ownership_and_reset_only_selected_skill(tmp_path):
    tools = LocalTools(tmp_path / "skills.db")
    engine = TutorEngine(tools, FakeTutor())
    await prepare(engine)
    first = tools.store.load(1)
    await engine.handle(1, "/newskill Разобраться с RL")
    tools.store.set_reminder(1, 1, 19, 0, "Europe/Moscow", [1], datetime.now(UTC))
    foreign = await engine.handle(2, f"/switch {first['skill_id']}")
    assert "не найден" in foreign.text
    assert tools.store.list_skills(2)["skills"] == []
    await engine.handle(1, "/reset_confirm", tools.store.load(1)["revision"])
    assert tools.store.load(1)["skill_id"] == first["skill_id"]
    assert tools.store.load(1)["state"] == first["state"]
    assert tools.store.reminder(1)["enabled"] == 1


async def test_migration_preserves_old_plan_and_lesson(tmp_path):
    path = tmp_path / "legacy.db"
    state = LearningState(
        goal="Освоить Go",
        stage="learning",
        lesson=lesson_fixture(),
        plan=await FakeTutor().generate("plan", Plan, {}),
        hints_used=1,
    )
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE learners(user_id INTEGER PRIMARY KEY, revision INTEGER, state TEXT)"
        )
        db.execute("INSERT INTO learners VALUES (1,7,?)", (state.model_dump_json(),))
    store = Store(path)
    assert store.load(1)["revision"] == 8
    assert store.load(1)["state"] == state.model_dump()
    assert len(Store(path).list_skills(1)["skills"]) == 1
    with pytest.raises(ConflictError):
        store.save(1, 7, state.model_dump())


async def test_skills_through_real_mcp_and_restart(tmp_path):
    path = tmp_path / "mcp-skills.db"
    async with connect_tools(path) as tools:
        engine = TutorEngine(tools, FakeTutor())
        await prepare(engine)
        first = await tools.call("get_learning_state", user_id=1)
        await engine.handle(1, "/newskill Подтянуть английский")
        assert len((await tools.call("list_skills", user_id=1))["skills"]) == 2
        assert (
            await tools.call("switch_skill", user_id=2, skill_id=first["skill_id"], revision=0)
        )["error"]
    async with connect_tools(path) as tools:
        catalog = await tools.call("list_skills", user_id=1)
        selected = await tools.call(
            "switch_skill", user_id=1, skill_id=first["skill_id"], revision=catalog["revision"]
        )
        assert selected["state"] == first["state"]


async def test_internal_rubric_is_hidden_from_student(tmp_path):
    tools = LocalTools(tmp_path / "hidden.db")
    engine = TutorEngine(tools, FakeTutor())
    await prepare(engine)
    plan = await engine.handle(1, "/plan")
    state = tools.store.load(1)["state"]
    for criterion in state["plan"]["modules"][0]["success_criteria"]:
        assert criterion not in plan.text
    lesson = await engine.handle(1, "/lesson")
    rubric = tools.store.load(1)["state"]["lesson"]["rubric"]
    grade = await engine.handle(1, "if err != nil { return err }")
    for criterion in rubric:
        assert criterion not in lesson.text
        assert criterion not in grade.text
    assert "2/2" not in grade.text


async def test_skill_catalog_pages_and_empty_draft_reuse(tmp_path):
    tools = LocalTools(tmp_path / "paging.db")
    engine = TutorEngine(tools, FakeTutor())
    await engine.handle(1, "/newskill")
    await engine.handle(1, "/newskill")
    assert len(tools.store.list_skills(1)["skills"]) == 1
    for i in range(12):
        await engine.handle(1, f"/newskill Навык номер {i}")
    page = await engine.handle(1, "/skills 2")
    assert "Страница 2/2" in page.text
    assert "skills_page_1" in page.actions
