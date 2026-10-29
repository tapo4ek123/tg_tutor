from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from tutor.budget import BudgetLedger, BudgetLimitError, units
from tutor.config import Settings
from tutor.engine import TutorEngine

from .fakes import FakeTutor
from .test_engine import LocalTools


def ledger(tmp_path, clock=None):
    return BudgetLedger(Settings(_env_file=None, budget_database_path=tmp_path / "spend.db"), clock)


def test_cost_accounts_for_cache_writes_long_context_and_reasoning(tmp_path):
    budget = ledger(tmp_path)
    expected = (
        Decimal(500) * Decimal(".1")
        + Decimal(200) * Decimal(".01")
        + Decimal(300) * Decimal(".125")
        + Decimal(100) * Decimal(".5")
    ) / 1_000_000
    assert budget.cost(1000, 100, cached=200, written=300) == units(expected)
    assert budget.cost(300000, 100) == units(Decimal(".060075"))
    assert budget.cost(1000, 100, service_tier="priority") == 2 * budget.cost(1000, 100)


def test_shared_atomic_budget_prevents_parallel_overspend(tmp_path):
    budget = ledger(tmp_path)

    def reserve():
        try:
            return budget.reserve(units(Decimal(2)), "gpt-6-luna")
        except BudgetLimitError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: reserve(), range(2)))
    assert sum(i is not None for i in ids) == 1
    assert Decimal(budget.status()["reserved_usd"]) == 2
    with pytest.raises(BudgetLimitError):
        ledger(tmp_path).reserve(units(Decimal(2)), "gpt-6-luna")


def test_actual_cost_releases_unused_reserve_and_unknown_holds_it(tmp_path):
    budget = ledger(tmp_path)
    request = budget.reserve(units(Decimal(2)), "gpt-6-luna")
    budget.settle(request, units(Decimal(".25")))
    assert Decimal(budget.status()["remaining_usd"]) == Decimal("2.75")
    pending = budget.reserve(units(Decimal(2)), "gpt-6-luna")
    budget.settle(pending, None)
    assert Decimal(budget.status()["spent_usd"]) == Decimal("2.25")
    assert Decimal(budget.status()["estimated_usd"]) == 2


async def test_limit_resume_survives_restart_day_change_and_skill_switch(tmp_path):
    now = [datetime(2026, 10, 27, 20, 59, tzinfo=UTC)]
    budget = ledger(tmp_path, lambda: now[0])
    paid = budget.reserve(units(Decimal(3)), "gpt-6-luna")
    budget.settle(paid, units(Decimal(3)))

    class BudgetedFake(FakeTutor):
        def __init__(self):
            super().__init__()
            self.budget = budget

        async def generate(self, *args):
            reservation = self.budget.reserve(100, "gpt-6-luna")
            self.budget.settle(reservation, 100)
            return await super().generate(*args)

    tools = LocalTools(tmp_path / "learning.db")
    model = BudgetedFake()
    engine = TutorEngine(tools, model)
    for text in ["Освоить Go", "Знаю Python", "30 3"]:
        await engine.handle(1, text)
    stopped = await engine.handle(1, "без срока")
    first = tools.store.load(1)
    assert "budget_resume" in stopped.actions
    assert first["state"]["stage"] == "deadline"
    assert first["state"]["pending_request"] == "без срока"
    assert model.calls == []
    await engine.handle(1, "/newskill Выучить испанский")
    second = tools.store.load(1)
    stale = await engine.handle(1, "/budget_resume", stopped.revision)
    assert "устарело" in stale.text
    assert tools.store.load(1) == second
    await engine.handle(1, f"/switch {first['skill_id']}")
    now[0] += timedelta(minutes=2)
    restarted = TutorEngine(LocalTools(tools.store.path), BudgetedFake())
    reply = await restarted.handle(1, "/budget_resume")
    assert "Проверим" in reply.text
    result = tools.store.load(1)
    assert result["state"]["stage"] == "diagnostic"
    assert result["state"]["pending_request"] is None
    assert budget.status()["day"] == "2026-10-28"
