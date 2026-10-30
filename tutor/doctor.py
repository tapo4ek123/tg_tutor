"""Check API access with a synthetic profile. Never send Telegram messages or read learner data."""

import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

from tutor.config import Settings
from tutor.llm import DeepSeekTutor, ModelError
from tutor.models import Diagnostic
from tutor.provider_errors import format_diagnostics


async def check(settings: Settings) -> int:
    env_path = await asyncio.to_thread(Path(".env").resolve)
    print(f"Файл настроек: {env_path}")
    url = urlsplit(settings.deepseek_base_url)
    print(f"API host: {url.hostname}")
    print(f"Модель: {settings.deepseek_model}")
    for key in ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL"):
        if key in os.environ:
            print(f"{key}: переменная окружения имеет приоритет над .env")
    if not settings.deepseek_api_key.get_secret_value():
        print("DEEPSEEK_API_KEY пустой. Заполните .env в указанной папке или переменную окружения.")
        return 1
    model = DeepSeekTutor(settings, timeout=20, max_retries=0)
    try:
        result = await model.generate(
            "diagnostic",
            Diagnostic,
            {
                "goal": "Освоить основы Go",
                "experience": "Знаю Python",
                "minutes_per_session": 30,
                "sessions_per_week": 3,
                "deadline": "без срока",
            },
        )
        print(f"OK: API доступен, диагностика получена ({len(result.questions)} вопроса).")
        return 0
    except ModelError as exc:
        print(str(exc))
        if exc.diagnostics:
            print(format_diagnostics(exc))
        return 1
    except Exception as exc:
        # The model layer already logged the complete error with credentials redacted.
        print(f"Некорректный ответ API или SDK: {type(exc).__name__}")
        return 1
    finally:
        await model.close()


def main() -> None:
    try:
        result = asyncio.run(check(Settings()))
    except ValueError:
        print("Некорректная конфигурация .env. Проверьте адрес API и параметры настроек.")
        result = 1
    raise SystemExit(result)


if __name__ == "__main__":
    main()
