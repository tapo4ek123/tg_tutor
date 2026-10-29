"""System evaluation is offline; --live explicitly calls the configured paid LLM."""

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

from tests.fakes import lesson_fixture
from tutor.config import Settings
from tutor.engine import grade_score
from tutor.llm import OpenAITutor
from tutor.models import Grade

ROOT = Path(__file__).resolve().parents[1]


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
            "limitation": "Does not measure GPT-6 Luna correctness or learning outcomes.",
        }
        (ROOT / "evals/system-results.json").write_text(
            json.dumps(output, ensure_ascii=False, indent=2) + "\n"
        )
        return result.returncode


async def live(limit: int) -> int:
    settings = Settings()
    if not settings.openai_api_key.get_secret_value():
        raise SystemExit(
            "Для live Eval заполните OPENAI_API_KEY в .env. Offline: python -m scripts.evaluate"
        )
    model = OpenAITutor(settings)
    lesson = lesson_fixture()
    cases = json.loads((ROOT / "evals/cases.json").read_text())[:limit]
    rows = []
    try:
        for case in cases:
            try:
                grade = await model.generate(
                    "grade",
                    Grade,
                    {
                        "lesson": lesson.model_dump(),
                        "answer": case["answer"],
                    },
                )
                score = grade_score(lesson, grade)
                rows.append(
                    {
                        "id": case["id"],
                        "score": score,
                        "min": case["min"],
                        "max": case["max"],
                        "passed": case["min"] <= score <= case["max"],
                        "grade": grade.model_dump(),
                    }
                )
            except Exception as exc:
                rows.append({"id": case["id"], "passed": False, "error": type(exc).__name__})
            print(f"{case['id']}: {'PASS' if rows[-1]['passed'] else 'FAIL'}", flush=True)
    finally:
        await model.close()
    passed = sum(row["passed"] for row in rows)
    output = {
        "kind": "live_llm_eval",
        "model": settings.openai_model,
        "reasoning_effort": settings.openai_reasoning_effort,
        "timestamp": datetime.now(UTC).isoformat(),
        "passed": passed,
        "total": len(rows),
        "cases": rows,
        "limitation": "20 hand-labelled Go grading examples, not a learning efficacy study.",
    }
    (ROOT / "evals/live-results.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    )
    print(f"{passed}/{len(rows)}; evals/live-results.json")
    return 0 if passed == len(rows) else 1


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Call the paid API")
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if not 1 <= args.limit <= 20:
        parser.error("--limit must be 1–20")
    raise SystemExit(asyncio.run(live(args.limit)) if args.live else offline())


if __name__ == "__main__":
    main()
