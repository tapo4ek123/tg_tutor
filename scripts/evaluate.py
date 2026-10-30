"""Offline checks and reproducible, append-only live model evaluation."""

import argparse
import asyncio
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from tests.fakes import lesson_fixture
from tutor.budget import BudgetLimitError
from tutor.config import Settings
from tutor.engine import grade_score
from tutor.llm import PROMPTS, SYSTEM, DeepSeekTutor
from tutor.models import Grade
from tutor.provider_errors import ModelError

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals/cases.json"


def offline() -> int:
    with tempfile.TemporaryDirectory() as folder:
        report = Path(folder) / "tests.xml"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", f"--junitxml={report}"],
            cwd=ROOT,
            check=False,
        )
        suites = ET.parse(report).getroot()
        cases = list(suites.iter("testcase"))
        failed = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
        output = {
            "kind": "offline_system_eval",
            "llm": "deterministic test double",
            "mcp": "real stdio subprocess in integration/e2e tests",
            "timestamp": datetime.now(UTC).isoformat(),
            "total": len(cases),
            "passed": len(cases) - len(failed),
            "failed": len(failed),
            "cases": [
                {
                    "name": c.get("name"),
                    "suite": c.get("classname"),
                    "seconds": float(c.get("time", "0")),
                }
                for c in cases
            ],
            "limitation": "Does not measure live model correctness or learning outcomes.",
        }
        (ROOT / "evals/system-results.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n"
        )
        return result.returncode


def describe_run(settings: Settings, limit: int, repeats: int) -> dict:
    """No client, credentials, network requests or budget reservations."""
    selected = json.loads(CASES.read_text())[:limit]
    return {
        "kind": "live_llm_eval",
        "provider": "DeepSeek",
        "model": settings.deepseek_model,
        "api_base_url": settings.deepseek_base_url,
        "api_format": "responses",
        "reasoning_effort": settings.deepseek_reasoning_effort,
        "case_count": len(selected),
        "repeats": repeats,
        "planned_total": len(selected) * repeats,
        "case_ids": [case["id"] for case in selected],
        "cases_sha256": hashlib.sha256(CASES.read_bytes()).hexdigest(),
        "prompt_sha256": hashlib.sha256((SYSTEM + "\n" + PROMPTS["grade"]).encode()).hexdigest(),
        "lesson_sha256": hashlib.sha256(lesson_fixture().model_dump_json().encode()).hexdigest(),
        "price_basis": "conservative DeepSeek peak rates, not an invoice",
        "daily_budget_usd": str(settings.daily_budget_usd),
        "report_directory": str(settings.eval_report_dir),
        "baselines": [
            str(p.relative_to(ROOT)) for p in sorted((ROOT / "evals/baselines").glob("*.json"))
        ],
    }


def metrics(rows: list[dict]) -> dict:
    valid = [row for row in rows if "score" in row]
    correct_decisions = sum((row["score"] >= 0.8) == (row["min"] >= 0.8) for row in valid)
    return {
        "attempted": len(rows),
        "valid_grades": len(valid),
        "errors": len(rows) - len(valid),
        "score_matches": sum(row["passed"] for row in rows),
        "correct_pass_decisions": correct_decisions,
        "false_accepts": sum(row["score"] >= 0.8 and row["max"] < 0.8 for row in valid),
        "false_rejects": sum(row["score"] < 0.8 and row["min"] >= 0.8 for row in valid),
    }


def save_report(path: Path, report: dict) -> None:
    # A checkpoint after every case survives interruption without exposing partial JSON.
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(path.name + ".tmp")
    staging.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    staging.replace(path)


async def live(
    limit: int, *, repeats: int = 1, output: Path | None = None, dry_run: bool = False
) -> int:
    settings = Settings()
    description = describe_run(settings, limit, repeats)
    if dry_run:
        print(json.dumps({**description, "status": "prepared"}, ensure_ascii=False, indent=2))
        return 0
    if not settings.deepseek_api_key.get_secret_value():
        raise SystemExit(
            "Для live Eval заполните DEEPSEEK_API_KEY в .env. Проверка набора: --dry-run"
        )
    started = datetime.now(UTC)
    slug = re.sub(r"[^a-zA-Z0-9_.-]", "_", settings.deepseek_model)
    report_dir = settings.eval_report_dir
    if not report_dir.is_absolute():
        report_dir = ROOT / report_dir
    path = output or report_dir / f"{slug}-{started:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}.json"
    path = path.resolve()
    if path.exists():
        raise SystemExit(f"Отчёт уже существует: {path}. Укажите новый --output.")
    report = {
        **description,
        "status": "running",
        "started_at": started.isoformat(),
        "timestamp": started.isoformat(),
        "passed": 0,
        "total": 0,
        "metrics": metrics([]),
        "cases": [],
        "limitation": "Fixed synthetic Go grading examples; not a study of learning efficacy.",
    }
    model = DeepSeekTutor(settings)
    rows = report["cases"]

    async def checkpoint() -> None:
        report.update(
            total=len(rows), passed=sum(row["passed"] for row in rows), metrics=metrics(rows)
        )
        await asyncio.to_thread(save_report, path, report)

    try:
        await checkpoint()
        print(
            f"Live Eval: {settings.deepseek_model}, {description['planned_total']} requests",
            flush=True,
        )
        for repeat in range(1, repeats + 1):
            for case in json.loads(CASES.read_text())[:limit]:
                row = {"id": case["id"], "repeat": repeat, "min": case["min"], "max": case["max"]}
                try:
                    grade = await model.generate(
                        "grade",
                        Grade,
                        {"lesson": lesson_fixture().model_dump(), "answer": case["answer"]},
                    )
                    score = grade_score(lesson_fixture(), grade)
                    row.update(
                        score=score,
                        passed=case["min"] <= score <= case["max"],
                        grade=grade.model_dump(),
                    )
                except BudgetLimitError:
                    row.update(passed=False, error="BudgetLimitError")
                    report["status"] = "budget_limited"
                except Exception as exc:
                    row.update(passed=False, error=type(exc).__name__)
                    if isinstance(exc, ModelError):
                        row["diagnostics"] = exc.diagnostics
                        if exc.diagnostics.get("category") in {
                            "authentication",
                            "permission",
                            "quota",
                            "not_found",
                            "request_format",
                        }:
                            report["status"] = "provider_blocked"
                rows.append(row)
                await checkpoint()
                print(
                    f"{repeat}/{repeats} {case['id']}: {'PASS' if row['passed'] else 'FAIL'}",
                    flush=True,
                )
                if report["status"] != "running":
                    break
            if report["status"] != "running":
                break
        if report["status"] == "running":
            report["status"] = "completed"
    except (asyncio.CancelledError, KeyboardInterrupt):
        report["status"] = "interrupted"
        raise
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        await asyncio.shield(checkpoint())
        await model.close()
    print(f"{report['passed']}/{report['total']} (planned {description['planned_total']}); {path}")
    return (
        0 if report["status"] == "completed" and report["passed"] == report["planned_total"] else 1
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Call the configured paid DeepSeek API")
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate the live Eval setup without API calls"
    )
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--repeat", type=int, default=1, help="Repeat the frozen dataset; default 1"
    )
    parser.add_argument(
        "--output", type=Path, help="New report path; existing files are never overwritten"
    )
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("--limit must be 1–20")
    if not 1 <= args.repeat <= 10:
        parser.error("--repeat must be 1–10")
    if not (args.live or args.dry_run) and (args.repeat != 1 or args.output is not None):
        parser.error("--repeat and --output require --live or --dry-run")
    raise SystemExit(
        asyncio.run(live(args.limit, repeats=args.repeat, output=args.output, dry_run=args.dry_run))
        if args.live or args.dry_run
        else offline()
    )


if __name__ == "__main__":
    main()
