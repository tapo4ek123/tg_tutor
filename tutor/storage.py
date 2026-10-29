import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from tutor.models import LearningState
from tutor.scheduling import next_occurrence


class ConflictError(RuntimeError):
    pass


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("BEGIN IMMEDIATE")
            db.execute("""
                CREATE TABLE IF NOT EXISTS skills (
                    skill_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    state TEXT NOT NULL
                )
            """)
            db.execute("CREATE INDEX IF NOT EXISTS skills_owner ON skills(user_id, skill_id)")
            columns = {row["name"] for row in db.execute("PRAGMA table_info(learners)")}
            if "state" in columns:
                # Transactional v1 migration: keep the exact snapshot, including pending work.
                legacy = db.execute("SELECT * FROM learners").fetchall()
                db.execute("ALTER TABLE learners RENAME TO learners_v1")
                self._create_learners(db)
                for row in legacy:
                    skill = db.execute(
                        "INSERT INTO skills(user_id, state) VALUES (?, ?)",
                        (row["user_id"], row["state"]),
                    ).lastrowid
                    db.execute(
                        "INSERT INTO learners VALUES (?, ?, ?)",
                        (row["user_id"], row["revision"] + 1, skill),
                    )
                db.execute("DROP TABLE learners_v1")
            else:
                self._create_learners(db)
            db.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    user_id INTEGER PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    hour INTEGER NOT NULL,
                    minute INTEGER NOT NULL,
                    timezone TEXT NOT NULL,
                    days TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    next_due REAL NOT NULL,
                    lease_until REAL NOT NULL DEFAULT 0
                )
            """)

    @staticmethod
    def _create_learners(db):
        db.execute("""
            CREATE TABLE IF NOT EXISTS learners (
                user_id INTEGER PRIMARY KEY,
                revision INTEGER NOT NULL,
                active_skill_id INTEGER
            )
        """)

    @staticmethod
    def _snapshot(db, user_id: int) -> dict:
        row = db.execute(
            "SELECT l.revision, l.active_skill_id, s.state FROM learners l "
            "LEFT JOIN skills s ON s.skill_id=l.active_skill_id AND s.user_id=l.user_id "
            "WHERE l.user_id=?",
            (user_id,),
        ).fetchone()
        return {
            "revision": row["revision"] if row else 0,
            "skill_id": row["active_skill_id"] if row else None,
            "state": json.loads(row["state"])
            if row and row["state"]
            else LearningState().model_dump(),
        }

    @staticmethod
    def _check_revision(db, user_id: int, revision: int | None):
        row = db.execute("SELECT revision FROM learners WHERE user_id=?", (user_id,)).fetchone()
        if revision is not None and (row["revision"] if row else 0) != revision:
            raise ConflictError("Состояние или выбранный навык уже изменились. Повторите действие.")

    @staticmethod
    def _select(db, user_id: int, skill_id: int | None):
        db.execute(
            "INSERT INTO learners VALUES (?, 1, ?) ON CONFLICT(user_id) DO UPDATE SET "
            "revision=learners.revision+1, active_skill_id=excluded.active_skill_id",
            (user_id, skill_id),
        )

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def load(self, user_id: int) -> dict:
        with self.connect() as db:
            return self._snapshot(db, user_id)

    def list_skills(self, user_id: int) -> dict:
        with self.connect() as db:
            snapshot = self._snapshot(db, user_id)
            rows = db.execute(
                "SELECT skill_id, state FROM skills WHERE user_id=? ORDER BY skill_id", (user_id,)
            ).fetchall()
        skills = []
        for row in rows:
            state = LearningState.model_validate_json(row["state"])
            skills.append(
                {
                    "skill_id": row["skill_id"],
                    "goal": state.goal,
                    "stage": state.stage,
                    "module_index": state.module_index,
                    "module_count": len(state.plan.modules) if state.plan else 0,
                    "attempt_count": len(state.attempts),
                }
            )
        return {
            "revision": snapshot["revision"],
            "active_skill_id": snapshot["skill_id"],
            "skills": skills,
        }

    def create_skill(self, user_id: int, revision: int, goal: str = "") -> dict:
        state = LearningState(goal=goal, stage="experience" if goal else "goal")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_revision(db, user_id, revision)
            snapshot = self._snapshot(db, user_id)
            # Reuse the selected empty draft instead of accumulating blank skills.
            if snapshot["skill_id"] and not snapshot["state"]["goal"]:
                skill = snapshot["skill_id"]
                db.execute(
                    "UPDATE skills SET state=? WHERE skill_id=? AND user_id=?",
                    (
                        state.model_dump_json(),
                        skill,
                        user_id,
                    ),
                )
            else:
                skill = db.execute(
                    "INSERT INTO skills(user_id, state) VALUES (?, ?)",
                    (
                        user_id,
                        state.model_dump_json(),
                    ),
                ).lastrowid
            self._select(db, user_id, skill)
            return self._snapshot(db, user_id)

    def switch_skill(self, user_id: int, skill_id: int, revision: int) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_revision(db, user_id, revision)
            owned = db.execute(
                "SELECT skill_id FROM skills WHERE user_id=? AND skill_id=?", (user_id, skill_id)
            ).fetchone()
            if not owned:
                return {"error": "skill_not_found"}
            if self._snapshot(db, user_id)["skill_id"] != skill_id:
                self._select(db, user_id, skill_id)
            return self._snapshot(db, user_id)

    def save(self, user_id: int, revision: int, state: dict) -> dict:
        validated = LearningState.model_validate(state)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_revision(db, user_id, revision)
            snapshot = self._snapshot(db, user_id)
            skill = snapshot["skill_id"]
            if skill is None:
                skill = db.execute(
                    "INSERT INTO skills(user_id, state) VALUES (?, ?)",
                    (
                        user_id,
                        validated.model_dump_json(),
                    ),
                ).lastrowid
            else:
                db.execute(
                    "UPDATE skills SET state=? WHERE skill_id=? AND user_id=?",
                    (
                        validated.model_dump_json(),
                        skill,
                        user_id,
                    ),
                )
            self._select(db, user_id, skill)
        return {"revision": revision + 1}

    def reset(self, user_id: int, revision: int | None = None) -> dict:
        # Delete only the selected skill; preserve all other learning tracks.
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._check_revision(db, user_id, revision)
            selected = self._snapshot(db, user_id)["skill_id"]
            db.execute("DELETE FROM skills WHERE user_id=? AND skill_id=?", (user_id, selected))
            remaining = db.execute(
                "SELECT skill_id, state FROM skills WHERE user_id=? ORDER BY skill_id", (user_id,)
            ).fetchall()
            next_skill = next(
                (r for r in remaining if json.loads(r["state"])["stage"] != "done"),
                remaining[0] if remaining else None,
            )
            self._select(db, user_id, next_skill["skill_id"] if next_skill else None)
            if not remaining:
                db.execute("DELETE FROM reminders WHERE user_id=?", (user_id,))
            return self._snapshot(db, user_id)

    def set_reminder(
        self,
        user_id: int,
        chat_id: int,
        hour: int,
        minute: int,
        timezone: str,
        days: list[int],
        now: datetime,
    ) -> dict:
        due = next_occurrence(now, hour, minute, timezone, days).timestamp()
        with self.connect() as db:
            db.execute(
                "INSERT INTO reminders(user_id, chat_id, hour, minute, timezone, days, next_due) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET "
                "chat_id=excluded.chat_id, hour=excluded.hour, minute=excluded.minute, "
                "timezone=excluded.timezone, days=excluded.days, enabled=1, "
                "next_due=excluded.next_due, lease_until=0",
                (user_id, chat_id, hour, minute, timezone, json.dumps(days), due),
            )
        return {"next_due": datetime.fromtimestamp(due, UTC).isoformat()}

    def reminder(self, user_id: int) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM reminders WHERE user_id=?", (user_id,)).fetchone()
        return dict(row) if row else {}

    def disable_reminder(self, user_id: int) -> dict:
        with self.connect() as db:
            db.execute("UPDATE reminders SET enabled=0, lease_until=0 WHERE user_id=?", (user_id,))
        return {"ok": True}

    def snooze(self, user_id: int, now: datetime) -> dict:
        with self.connect() as db:
            count = db.execute(
                "UPDATE reminders SET next_due=?, lease_until=0 WHERE user_id=? AND enabled=1",
                ((now + timedelta(hours=1)).timestamp(), user_id),
            ).rowcount
        return {"ok": bool(count)}

    def claim_due(self, now: datetime) -> list[dict]:
        stamp = now.timestamp()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                "SELECT * FROM reminders WHERE enabled=1 AND next_due<=? AND lease_until<=? "
                "ORDER BY next_due LIMIT 100",
                (stamp, stamp),
            ).fetchall()
            claimed = []
            for row in rows:
                if stamp - row["next_due"] > 7200:
                    # Do not spam old reminders after a long server outage.
                    due = next_occurrence(
                        now, row["hour"], row["minute"], row["timezone"], json.loads(row["days"])
                    ).timestamp()
                    db.execute(
                        "UPDATE reminders SET next_due=? WHERE user_id=?", (due, row["user_id"])
                    )
                    continue
                db.execute(
                    "UPDATE reminders SET lease_until=? WHERE user_id=?",
                    (stamp + 300, row["user_id"]),
                )
                claimed.append(dict(row))
        return claimed

    def finish_reminder(
        self, user_id: int, scheduled_due: float, now: datetime, retry: int = 0
    ) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT * FROM reminders WHERE user_id=?", (user_id,)).fetchone()
            if not row or not row["enabled"] or row["next_due"] != scheduled_due:
                return {"ok": False}  # Schedule was edited while delivery was running.
            due = (
                (now + timedelta(seconds=max(retry, 30))).timestamp()
                if retry
                else next_occurrence(
                    now, row["hour"], row["minute"], row["timezone"], json.loads(row["days"])
                ).timestamp()
            )
            db.execute(
                "UPDATE reminders SET next_due=?, lease_until=0 WHERE user_id=?", (due, user_id)
            )
        return {"ok": True}
