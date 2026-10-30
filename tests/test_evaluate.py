import asyncio
import hashlib
import json

import pytest

from scripts import evaluate
from tutor.budget import BudgetLimitError
from tutor.config import Settings
from tutor.models import CriterionScore, Grade
from tutor.provider_errors import ModelError


@pytest.fixture
def prepared_eval(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluate, "ROOT", tmp_path)
    monkeypatch.setattr(
        evaluate, "Settings", lambda: Settings(_env_file=None, deepseek_api_key="test-only")
    )
    instances = []

    class Model:
        def __init__(self, settings):
            self.closed = False
            self.calls = 0
            instances.append(self)

        async def generate(self, kind, schema, payload):
            self.calls += 1
            assert kind == "grade" and schema is Grade
            return Grade(
                criteria=[
                    CriterionScore(criterion=c, score=2, explanation="fixture")
                    for c in payload["lesson"]["rubric"]
                ],
                feedback="fixture",
                gaps=[],
            )

        async def close(self):
            self.closed = True

    monkeypatch.setattr(evaluate, "DeepSeekTutor", Model)
    return tmp_path, instances, Model


async def test_dry_run_has_frozen_hashes_and_no_model_or_output(prepared_eval, capsys):
    root, instances, _ = prepared_eval
    target = root / "unused.json"
    assert await evaluate.live(20, repeats=3, output=target, dry_run=True) == 0
    description = json.loads(capsys.readouterr().out)
    assert description["planned_total"] == 60
    assert description["model"] == "deepseek-flash"
    assert description["api_base_url"] == "https://api.deepseek.com"
    assert description["cases_sha256"] == hashlib.sha256(evaluate.CASES.read_bytes()).hexdigest()
    assert not instances and not target.exists()
    assert "test-only" not in json.dumps(description)


async def test_repeated_runs_save_separate_reports_with_metrics(prepared_eval):
    root, instances, _ = prepared_eval
    assert await evaluate.live(2, repeats=2) == 0
    first = list((root / "evals/runs").glob("*.json"))
    assert len(first) == 1
    report = json.loads(first[0].read_text())
    assert report["status"] == "completed"
    assert report["total"] == report["planned_total"] == report["passed"] == 4
    assert [r["repeat"] for r in report["cases"]] == [1, 1, 2, 2]
    assert report["metrics"]["false_accepts"] == report["metrics"]["false_rejects"] == 0
    assert instances[0].closed
    original = first[0].read_bytes()
    assert await evaluate.live(1) == 0
    assert len(list((root / "evals/runs").glob("*.json"))) == 2
    assert first[0].read_bytes() == original


async def test_existing_report_is_never_overwritten(prepared_eval):
    root, instances, _ = prepared_eval
    path = root / "baseline.json"
    path.write_text('"original report"')
    with pytest.raises(SystemExit, match="уже существует"):
        await evaluate.live(20, output=path)
    assert path.read_text() == '"original report"'
    assert not instances


@pytest.mark.parametrize("failure", ["budget", "authentication", "interrupted"])
async def test_stopped_eval_keeps_checkpoint_and_closes_model(prepared_eval, monkeypatch, failure):
    root, instances, model_type = prepared_eval

    async def fail(self, *args):
        self.calls += 1
        if failure == "budget":
            raise BudgetLimitError(
                {
                    "reset_at": "2026-10-31T00:00:00+03:00",
                    "spent_usd": "3",
                    "limit_usd": "3",
                    "reserved_usd": "0",
                    "timezone": "Europe/Moscow",
                }
            )
        if failure == "authentication":
            raise ModelError("invalid key", diagnostics={"category": "authentication"})
        raise asyncio.CancelledError

    monkeypatch.setattr(model_type, "generate", fail)
    path = root / "stopped.json"
    if failure == "interrupted":
        with pytest.raises(asyncio.CancelledError):
            await evaluate.live(20, output=path)
    else:
        assert await evaluate.live(20, output=path) == 1
    report = json.loads(path.read_text())
    assert (
        report["status"]
        == {
            "budget": "budget_limited",
            "authentication": "provider_blocked",
            "interrupted": "interrupted",
        }[failure]
    )
    assert report["total"] < report["planned_total"] == 20
    assert instances[0].calls == 1 and instances[0].closed
    assert "finished_at" in report


def test_pass_fail_metrics_separate_score_match_from_passing_lesson():
    result = evaluate.metrics(
        [
            {"score": 0.75, "min": 0.5, "max": 0.5, "passed": False},
            {"score": 1, "min": 1, "max": 1, "passed": True},
            {"passed": False, "error": "ModelError"},
        ]
    )
    assert result["score_matches"] == 1
    assert result["valid_grades"] == 2 and result["errors"] == 1
    assert result["correct_pass_decisions"] == 2
    assert result["false_accepts"] == 0
