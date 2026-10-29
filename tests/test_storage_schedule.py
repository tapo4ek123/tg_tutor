from datetime import UTC, datetime, timedelta

import pytest

from tutor.scheduling import next_occurrence, parse_schedule
from tutor.storage import ConflictError, Store


def test_optimistic_lock_and_reset(tmp_path):
    store = Store(tmp_path / "test.db")
    snapshot = store.load(1)
    store.save(1, 0, snapshot["state"])
    with pytest.raises(ConflictError):
        store.save(1, 0, snapshot["state"])
    store.reset(1)
    with pytest.raises(ConflictError):
        store.save(1, 1, snapshot["state"])


def test_moscow_schedule():
    now = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)  # Tuesday 18:00 Moscow
    assert next_occurrence(now, 19, 0, "Europe/Moscow", [1, 3, 5]) == datetime(
        2026, 10, 28, 16, tzinfo=UTC
    )


def test_dst_spring_gap():
    now = datetime(2026, 3, 28, 20, tzinfo=UTC)
    due = next_occurrence(now, 2, 30, "Europe/Berlin", [7])
    assert due == datetime(2026, 3, 29, 1, tzinfo=UTC)  # nonexistent 02:30 -> 03:00


@pytest.mark.parametrize(
    "text",
    [
        "25:00",
        "12:60",
        "12",
        "19:00 Nope",
        "19:00 UTC 0",
        "19:00 UTC 8",
        "19:00 UTC x",
        "19:00 UTC 1 extra",
    ],
)
def test_invalid_schedule(text):
    with pytest.raises(ValueError):
        parse_schedule(text, "Europe/Moscow")


def test_claim_retry_snooze_and_disable(tmp_path):
    store = Store(tmp_path / "test.db")
    now = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)
    store.set_reminder(1, 1, 18, 1, "Europe/Moscow", list(range(1, 8)), now)
    due = now + timedelta(minutes=1)
    rows = store.claim_due(due)
    assert len(rows) == 1
    assert store.claim_due(due) == []
    store.finish_reminder(1, rows[0]["next_due"], due, retry=60)
    assert store.claim_due(due + timedelta(seconds=59)) == []
    assert len(store.claim_due(due + timedelta(seconds=60))) == 1
    store.snooze(1, due)
    # An old delivery cannot overwrite a schedule changed by snooze.
    assert not store.finish_reminder(1, rows[0]["next_due"], due)["ok"]
    assert store.reminder(1)["next_due"] == (due + timedelta(hours=1)).timestamp()
    store.disable_reminder(1)
    assert store.claim_due(due + timedelta(hours=1)) == []


def test_outage_skips_old_notification(tmp_path):
    store = Store(tmp_path / "test.db")
    now = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)
    store.set_reminder(1, 1, 18, 1, "Europe/Moscow", list(range(1, 8)), now)
    assert store.claim_due(now + timedelta(days=1, hours=3)) == []
    assert store.reminder(1)["next_due"] > (now + timedelta(days=1, hours=3)).timestamp()
