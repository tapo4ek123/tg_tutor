import time

from tutor.config import Settings


def main() -> None:
    settings = Settings()
    heartbeat = settings.heartbeat_path
    max_age = max(180, settings.reminder_poll_seconds * 4)
    healthy = heartbeat.exists() and time.time() - heartbeat.stat().st_mtime < max_age
    raise SystemExit(0 if healthy else 1)


if __name__ == "__main__":
    main()
