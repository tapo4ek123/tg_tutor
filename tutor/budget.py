"""Shared daily spend ledger. Integer nano-USD, atomic reservations, no prompt storage."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, time, timedelta
from decimal import ROUND_CEILING, Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

from tutor.config import Settings
from tutor.provider_errors import ModelError

SCALE = Decimal(1_000_000_000)


def units(usd: Decimal) -> int:
    return int((usd * SCALE).to_integral_value(rounding=ROUND_CEILING))


def dollars(value: int) -> str:
    return format(Decimal(value) / SCALE, ".9f")


class BudgetLimitError(ModelError):
    def __init__(self, snapshot: dict):
        self.snapshot = snapshot
        reset = datetime.fromisoformat(snapshot["reset_at"]).strftime("%d.%m %H:%M")
        super().__init__(
            f"Недостаточно суточного бюджета для следующего запроса.\n"
            f"Расход: ${Decimal(snapshot['spent_usd']):.4f} "
            f"из ${Decimal(snapshot['limit_usd']):.2f}.\n"
            f"Ожидающие запросы: ${Decimal(snapshot['reserved_usd']):.4f}.\n"
            f"Обновление лимита: {reset} ({snapshot['timezone']}).\n"
            "Текущий шаг сохранён. Нажмите «Проверить лимит и продолжить»."
        )


class BudgetLedger:
    def __init__(self, settings: Settings, clock=None):
        self.settings = settings
        self.path = settings.budget_database_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.zone = ZoneInfo(settings.budget_timezone)
        self.limit = units(settings.daily_budget_usd)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("""CREATE TABLE IF NOT EXISTS model_spend (
                id TEXT PRIMARY KEY, day TEXT NOT NULL, model TEXT NOT NULL,
                reserved INTEGER NOT NULL, billed INTEGER,
                status TEXT NOT NULL DEFAULT 'reserved', usage TEXT
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS model_spend_day ON model_spend(day)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _status(self, db) -> dict:
        local = self.clock().astimezone(self.zone)
        row = db.execute(
            "SELECT COALESCE(SUM(CASE WHEN status='reserved' THEN reserved ELSE 0 END),0) AS held, "
            "COALESCE(SUM(CASE WHEN status IN ('actual','estimated') "
            "THEN billed ELSE 0 END),0) AS spent, "
            "COALESCE(SUM(CASE WHEN status='estimated' THEN billed ELSE 0 END),0) AS estimated "
            "FROM model_spend WHERE day=?",
            (local.date().isoformat(),),
        ).fetchone()
        reset = datetime.combine(local.date() + timedelta(days=1), time.min, self.zone)
        return {
            "day": local.date().isoformat(),
            "timezone": self.settings.budget_timezone,
            "reset_at": reset.isoformat(),
            "limit_usd": dollars(self.limit),
            "spent_usd": dollars(row["spent"]),
            "reserved_usd": dollars(row["held"]),
            "estimated_usd": dollars(row["estimated"]),
            "remaining_usd": dollars(max(0, self.limit - row["spent"] - row["held"])),
        }

    def status(self) -> dict:
        with self.connect() as db:
            return self._status(db)

    def reserve(self, maximum_units: int, model: str) -> str:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            status = self._status(db)
            if maximum_units > units(Decimal(status["remaining_usd"])):
                raise BudgetLimitError(status)
            reservation = uuid4().hex
            db.execute(
                "INSERT INTO model_spend(id,day,model,reserved) VALUES (?,?,?,?)",
                (
                    reservation,
                    status["day"],
                    model,
                    maximum_units,
                ),
            )
            return reservation

    def settle(self, reservation: str, cost: int | None, usage: dict | None = None):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM model_spend WHERE id=?", (reservation,)).fetchone()
            if not row or row["status"] != "reserved":
                return
            # An uncertain/cancelled request keeps its entire reserve charged conservatively.
            db.execute(
                "UPDATE model_spend SET billed=?,status=?,usage=? WHERE id=?",
                (
                    row["reserved"] if cost is None else cost,
                    "estimated" if cost is None else "actual",
                    json.dumps(usage) if usage is not None else None,
                    reservation,
                ),
            )

    def cost(self, input_tokens: int, output_tokens: int, cached: int = 0) -> int:
        """Token-based ceiling using Flash peak prices; reasoning is already in output."""
        if min(input_tokens, output_tokens, cached) < 0 or cached > input_tokens:
            raise ValueError("Invalid token usage")
        s = self.settings
        return units(
            (
                (input_tokens - cached) * s.llm_input_usd_per_million
                + cached * s.llm_cached_usd_per_million
                + output_tokens * s.llm_output_usd_per_million
            )
            * s.llm_price_multiplier
            / Decimal(1_000_000)
        )

    def maximum_cost(self, request: dict) -> int:
        # Text-only UTF-8 bound plus framing; assume no cache hits and peak prices.
        token_bound = len(json.dumps(request, ensure_ascii=False).encode("utf-8")) + 8192
        s = self.settings
        return units(
            (
                token_bound * max(s.llm_input_usd_per_million, s.llm_cached_usd_per_million)
                + request["max_output_tokens"] * s.llm_output_usd_per_million
            )
            * s.llm_price_multiplier
            / Decimal(1_000_000)
        )
