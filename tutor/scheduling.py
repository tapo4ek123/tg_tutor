from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo


def next_occurrence(
    now: datetime, hour: int, minute: int, timezone: str, days: list[int]
) -> datetime:
    """Next wall-clock slot, respecting DST gaps/folds and ISO weekdays (1=Monday)."""
    zone = ZoneInfo(timezone)
    local = now.astimezone(zone)
    for offset in range(9):
        date = local.date() + timedelta(days=offset)
        if date.isoweekday() not in days:
            continue
        wall = datetime(date.year, date.month, date.day, hour, minute)
        # A nonexistent spring time moves forward to the first real minute.
        for shift in range(181):
            candidate = (wall + timedelta(minutes=shift)).replace(tzinfo=zone, fold=0)
            utc = candidate.astimezone(UTC)
            if utc.astimezone(zone).replace(tzinfo=None) != candidate.replace(tzinfo=None):
                continue
            if utc > now.astimezone(UTC):
                return utc
            break
    raise ValueError("Не удалось найти следующее время напоминания.")


def parse_schedule(text: str, default_timezone: str) -> tuple[int, int, str, list[int]]:
    parts = text.split()
    if not 1 <= len(parts) <= 3:
        raise ValueError("Формат: /remind 19:00 Europe/Moscow 1,3,5 (1=пн, 7=вс)")
    try:
        time = parts[0].split(":")
        if len(time) != 2:
            raise ValueError
        hour, minute = map(int, time)
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            raise ValueError
        timezone = parts[1] if len(parts) > 1 else default_timezone
        ZoneInfo(timezone)
        days = (
            sorted({int(day) for day in parts[2].split(",")})
            if len(parts) > 2
            else list(range(1, 8))
        )
        if not days or any(day not in range(1, 8) for day in days):
            raise ValueError
        return hour, minute, timezone, days
    except (ValueError, KeyError) as exc:
        raise ValueError(
            "Проверьте время, IANA timezone и дни 1–7. Пример: 19:00 Europe/Moscow 1,3,5"
        ) from exc
