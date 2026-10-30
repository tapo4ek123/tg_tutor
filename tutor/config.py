from decimal import Decimal
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    telegram_bot_token: SecretStr = SecretStr("")
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_model: str = "deepseek-flash"
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_reasoning_effort: Literal["none", "low", "high", "max"] = "low"
    database_path: Path = Path("data/tutor.sqlite3")
    default_timezone: str = "Europe/Moscow"
    allowed_user_ids: str = ""
    max_requests_per_hour: int = Field(default=30, ge=1)
    reminder_poll_seconds: int = Field(default=30, ge=1)
    heartbeat_path: Path = Path("data/heartbeat")
    budget_database_path: Path = Path("data/budget.sqlite3")
    eval_report_dir: Path = Path("evals/runs")
    daily_budget_usd: Decimal = Field(default=Decimal("3"), gt=0)
    budget_timezone: str = "Europe/Moscow"
    llm_price_model: str = "deepseek-flash"
    llm_input_usd_per_million: Decimal = Field(default=Decimal("0.30"), ge=0)
    llm_cached_usd_per_million: Decimal = Field(default=Decimal("0.006"), ge=0)
    llm_output_usd_per_million: Decimal = Field(default=Decimal("1.20"), ge=0)
    llm_price_multiplier: Decimal = Field(default=Decimal("1"), gt=0)

    @field_validator("default_timezone", "budget_timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        ZoneInfo(value)
        return value

    @property
    def allowed_ids(self) -> set[int]:
        return {int(item.strip()) for item in self.allowed_user_ids.split(",") if item.strip()}

    def validate_live(self) -> None:
        if not self.telegram_bot_token.get_secret_value():
            raise ValueError("Заполните TELEGRAM_BOT_TOKEN в .env (токен от @BotFather).")
        if not self.deepseek_api_key.get_secret_value():
            raise ValueError("Заполните DEEPSEEK_API_KEY в .env.")
        _ = self.allowed_ids  # Validate before starting polling.
