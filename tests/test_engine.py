import pytest

from tutor.engine import TutorEngine
from tutor.llm import ModelError
from tutor.models import LearningState
from tutor.storage import Store

from .fakes import FakeTutor


class LocalTools:
    """Fast business-logic tests; real protocol is tested separately."""

    def __init__(self, path):
        self.store = Store(path)

    async def call(self, name, **args):
        match name:
            case "get_learning_state":
                return self.store.load(**args)
            case "save_learning_state":
                return self.store.save(**args)
            case "reset_learning_state":
                return self.store.reset(**args)
            case "search_materials":
                return {"materials": []}
            case "list_skills":
                return self.store.list_skills(**args)
            case "create_skill":
                return self.store.create_skill(**args)
            case "switch_skill":
                return self.store.switch_skill(**args)
            case _:
                raise AssertionError(name)


async def prepare(engine, user=1):
    for text in ["Хочу освоить Go и написать CLI", "Знаю Python", "30 3", "Через месяц", "Не знаю"]:
        await engine.handle(user, text)
    await engine.handle(user, "/accept")


@pytest.fixture
def setup(tmp_path):
    tools, model = LocalTools(tmp_path / "test.db"), FakeTutor()
    return TutorEngine(tools, model), tools, model


async def test_complete_learning_cycle(setup):
    engine, tools, model = setup
    await prepare(engine)
    for _ in range(3):
        await engine.handle(1, "/lesson")
        await engine.handle(1, "if err != nil { return err }; используем результат")
    state = LearningState.model_validate(tools.store.load(1)["state"])
    assert state.stage == "done"
    assert state.module_index == 3
    assert len(state.attempts) == 3
    assert model.calls[-2][1]["final"] is True


async def test_wrong_answer_adds_targeted_practice(setup):
    engine, tools, model = setup
    await prepare(engine)
    await engine.handle(1, "/lesson")
    reply = await engine.handle(1, "Не знаю")
    assert "План скорректирован" in reply.text
    state = tools.store.load(1)["state"]
    assert state["module_index"] == 0
    assert state["adaptations"]
    await engine.handle(1, "/lesson")
    assert model.calls[-1][1]["focus"]
    assert "Повторная практика" in tools.store.load(1)["state"]["lesson"]["task"]


async def test_final_work_requires_no_help(setup):
    engine, tools, _ = setup
    await prepare(engine)
    for _ in range(2):
        await engine.handle(1, "/lesson")
        await engine.handle(1, "if err != nil { return err }")
    await engine.handle(1, "/lesson")
    await engine.handle(1, "/hint")
    await engine.handle(1, "if err != nil { return err }")
    state = tools.store.load(1)["state"]
    assert state["stage"] == "learning"
    assert state["module_index"] == 2
    assert state["attempts"][-1]["score"] == 1
    assert not state["attempts"][-1]["passed"]


async def test_bad_grading_and_provider_failure_preserve_state(setup):
    engine, tools, model = setup
    await prepare(engine)
    await engine.handle(1, "/lesson")
    before = tools.store.load(1)
    model.bad_rubric = True
    with pytest.raises(ModelError):
        await engine.handle(1, "if err != nil { return err }")
    assert tools.store.load(1) == before
    model.bad_rubric = False
    model.fail = True
    with pytest.raises(RuntimeError):
        await engine.handle(1, "ответ")
    assert tools.store.load(1) == before


async def test_user_isolation_and_restart(setup):
    engine, tools, _ = setup
    await prepare(engine)
    assert tools.store.load(2)["state"]["goal"] == ""
    new_engine = TutorEngine(LocalTools(tools.store.path), FakeTutor())
    reply = await new_engine.handle(1, "/plan")
    assert "CLI" in reply.text


async def test_stale_callback_does_not_mutate(setup):
    engine, tools, _ = setup
    await prepare(engine)
    revision = tools.store.load(1)["revision"]
    await engine.handle(1, "/lesson", revision)
    before = tools.store.load(1)
    reply = await engine.handle(1, "/lesson", revision)
    assert "устарело" in reply.text
    assert tools.store.load(1) == before


@pytest.mark.parametrize("budget", ["0 3", "121 1", "30 0", "30 8", "abc", "30", "30 -1"])
async def test_invalid_budget(setup, budget):
    engine, tools, _ = setup
    await engine.handle(1, "Учить Go")
    await engine.handle(1, "Знаю Python")
    await engine.handle(1, budget)
    assert tools.store.load(1)["state"]["stage"] == "budget"


async def test_reset_requires_confirmation(setup):
    engine, tools, _ = setup
    await prepare(engine)
    before = tools.store.load(1)
    await engine.handle(1, "/reset")
    await engine.handle(1, "/reset_confirm")
    assert tools.store.load(1) == before
    await engine.handle(1, "/reset_confirm", before["revision"])
    assert tools.store.load(1)["state"]["goal"] == ""


async def test_help_does_not_expose_reference_answer(setup):
    engine, tools, _ = setup
    await prepare(engine)
    reply = await engine.handle(1, "/lesson")
    assert tools.store.load(1)["state"]["lesson"]["reference_answer"] not in reply.text
    await engine.handle(1, "/ask Что такое error?")
    assert tools.store.load(1)["state"]["hints_used"] == 1
