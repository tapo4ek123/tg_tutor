"""Private stdio MCP server. Only stdout MCP frames; logging goes to stderr."""

from datetime import UTC, datetime

from mcp.server.fastmcp import FastMCP

from tutor.config import Settings
from tutor.materials import search_materials as find_materials
from tutor.models import LearningState
from tutor.scheduling import parse_schedule
from tutor.storage import Store


def build_server(store: Store) -> FastMCP:
    mcp = FastMCP("SkillPilot Learning")

    @mcp.tool()
    def get_learning_state(user_id: int) -> dict:
        """Read the selected skill's state and the learner's selection revision."""
        return store.load(user_id)

    @mcp.tool()
    def list_skills(user_id: int) -> dict:
        """List only this learner's skills, their progress and selected skill ID."""
        return store.list_skills(user_id)

    @mcp.tool()
    def create_skill(user_id: int, revision: int, goal: str = "") -> dict:
        """Add and select an independent skill without overwriting existing learning."""
        return store.create_skill(user_id, revision, goal)

    @mcp.tool()
    def switch_skill(user_id: int, skill_id: int, revision: int) -> dict:
        """Select an owned skill and invalidate buttons from the previous selection."""
        return store.switch_skill(user_id, skill_id, revision)

    @mcp.tool()
    def save_learning_state(user_id: int, revision: int, state: dict) -> dict:
        """Validate and atomically save state using optimistic concurrency."""
        LearningState.model_validate(state)
        return store.save(user_id, revision, state)

    @mcp.tool()
    def reset_learning_state(user_id: int, revision: int | None = None) -> dict:
        """Delete only the selected skill after confirmation; retain other skills."""
        return store.reset(user_id, revision)

    @mcp.tool()
    def search_materials(query: str) -> dict:
        """Search curated primary learning resources; return titles and source URLs."""
        return {"materials": find_materials(query)}

    @mcp.tool()
    def set_reminder(user_id: int, chat_id: int, schedule: str, default_timezone: str) -> dict:
        """Set HH:MM IANA_timezone weekdays(1-7) reminders in durable storage."""
        hour, minute, timezone, days = parse_schedule(schedule, default_timezone)
        return store.set_reminder(user_id, chat_id, hour, minute, timezone, days, datetime.now(UTC))

    @mcp.tool()
    def get_reminder(user_id: int) -> dict:
        """Read the learner's reminder schedule."""
        return store.reminder(user_id)

    @mcp.tool()
    def disable_reminder(user_id: int) -> dict:
        """Disable reminders for one learner."""
        return store.disable_reminder(user_id)

    @mcp.tool()
    def snooze_reminder(user_id: int) -> dict:
        """Move the next enabled reminder one hour ahead."""
        return store.snooze(user_id, datetime.now(UTC))

    @mcp.tool()
    def claim_due_reminders() -> dict:
        """Lease due reminders for the private scheduler, suppress stale notifications."""
        return {"reminders": store.claim_due(datetime.now(UTC))}

    @mcp.tool()
    def finish_reminder(user_id: int, scheduled_due: float, retry_seconds: int = 0) -> dict:
        """Acknowledge delivery or schedule retry; don't overwrite newer schedules."""
        return store.finish_reminder(user_id, scheduled_due, datetime.now(UTC), retry_seconds)

    return mcp


def main() -> None:
    build_server(Store(Settings().database_path)).run(transport="stdio")


if __name__ == "__main__":
    main()
