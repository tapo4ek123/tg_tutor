import asyncio
import logging
from contextlib import suppress

from aiogram import Bot

from tutor.config import Settings
from tutor.engine import TutorEngine
from tutor.llm import DeepSeekTutor
from tutor.mcp_client import connect_tools
from tutor.reminders import reminder_loop
from tutor.telegram import build_dispatcher, set_commands


async def run(settings: Settings) -> None:
    settings.validate_live()
    model = DeepSeekTutor(settings)
    try:
        async with Bot(settings.telegram_bot_token.get_secret_value()) as bot:
            async with connect_tools(settings.database_path) as tools:
                await set_commands(bot)
                # Polling and webhooks are mutually exclusive; never discard queued messages.
                await bot.delete_webhook(drop_pending_updates=False)
                dispatcher = build_dispatcher(TutorEngine(tools, model), settings)
                scheduler = asyncio.create_task(
                    reminder_loop(
                        bot,
                        tools,
                        settings.reminder_poll_seconds,
                        settings.heartbeat_path,
                    )
                )
                try:
                    await dispatcher.start_polling(
                        bot,
                        allowed_updates=dispatcher.resolve_used_update_types(),
                        close_bot_session=False,
                    )
                finally:
                    scheduler.cancel()
                    with suppress(asyncio.CancelledError):
                        await scheduler
    finally:
        await model.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    # Third-party HTTP debug logs may contain Telegram tokens in URLs.
    for name in ("httpx", "httpcore", "openai", "mcp.server.lowlevel.server"):
        logging.getLogger(name).setLevel(logging.WARNING)
    try:
        asyncio.run(run(Settings()))
    except (ValueError, KeyboardInterrupt) as exc:
        if isinstance(exc, ValueError):
            raise SystemExit(str(exc)) from None


if __name__ == "__main__":
    main()
