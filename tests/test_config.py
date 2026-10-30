from decimal import Decimal

import pytest
from pydantic import ValidationError

from tutor.config import Settings
from tutor.llm import DeepSeekTutor


def test_official_deepseek_defaults_do_not_reuse_openai_key(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "old-provider-key")
    settings = Settings(_env_file=None)
    assert not settings.deepseek_api_key.get_secret_value()
    assert settings.deepseek_model == settings.llm_price_model == "deepseek-flash"
    assert settings.deepseek_base_url == "https://api.deepseek.com"
    assert settings.llm_input_usd_per_million == Decimal(".30")
    assert settings.llm_cached_usd_per_million == Decimal(".006")
    assert settings.llm_output_usd_per_million == Decimal("1.20")


def test_reasoning_effort_and_price_model_are_checked_before_requests():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, deepseek_reasoning_effort="unsupported")
    with pytest.raises(ValueError, match="LLM_PRICE_MODEL"):
        DeepSeekTutor(Settings(_env_file=None, deepseek_model="another-model"))
