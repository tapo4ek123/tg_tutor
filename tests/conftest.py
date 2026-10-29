import pytest


@pytest.fixture(autouse=True)
def isolated_budget_database(tmp_path, monkeypatch):
    monkeypatch.setenv("BUDGET_DATABASE_PATH", str(tmp_path / "budget.sqlite3"))
