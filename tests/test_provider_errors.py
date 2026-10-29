import json
import logging
from datetime import UTC, datetime

import httpx
import pytest
from aiogram import Bot
from aiogram.types import Chat, Message, Update, User
from openai import APIConnectionError, APITimeoutError, AsyncOpenAI

from tutor.config import Settings
from tutor.engine import TutorEngine
from tutor.llm import ModelError, OpenAITutor
from tutor.models import Diagnostic
from tutor.provider_errors import provider_failure
from tutor.telegram import build_dispatcher

from .test_engine import LocalTools
from .test_llm_telegram import TelegramSession


async def mocked_model(status, body, key="test-secret-key"):
    model = OpenAITutor(Settings(openai_api_key=key))
    await model.client.close()
    model.client = AsyncOpenAI(
        api_key=key,
        max_retries=0,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body))
        ),
    )
    return model


@pytest.mark.parametrize(
    ("status", "code", "category", "expected"),
    [
        (401, "invalid_api_key", "authentication", "API-ключ"),
        (403, "permission_denied", "permission", "запретил доступ"),
        (403, "unsupported_country_region_territory", "permission", "региона"),
        (403, "model_access_denied", "permission", "выбранной модели"),
        (404, "model_not_found", "not_found", "не нашёл выбранную модель"),
        (404, "not_found", "not_found", "OPENAI_BASE_URL"),
        (400, "unsupported_parameter", "request_format", "формат запроса"),
        (429, "insufficient_quota", "quota", "квота"),
        (429, "rate_limit_exceeded", "rate_limit", "частоту"),
        (503, "unavailable", "provider_unavailable", "Сбой на стороне"),
    ],
)
async def test_sdk_failures_have_actionable_messages(status, code, category, expected):
    model = await mocked_model(status, {"error": {"code": code, "message": code}})
    try:
        with pytest.raises(ModelError) as error:
            await model.generate("diagnostic", Diagnostic, {"goal": "Go"})
        assert expected in str(error.value)
        assert error.value.diagnostics["http_status"] == status
        assert error.value.diagnostics["category"] == category
    finally:
        await model.close()


async def test_permission_denied_keeps_deadline_stage_and_reports_403(tmp_path, caplog):
    secret = "private-gateway-key"
    model = await mocked_model(
        403,
        {
            "error": {
                "code": "permission_denied",
                "message": f"Access denied for Bearer {secret} at https://gateway.invalid/?key={secret}",
            }
        },
        key=secret,
    )
    tools = LocalTools(tmp_path / "errors.db")
    state = tools.store.load(1)["state"]
    state.update(stage="deadline", goal="Выучить Go", experience="Знаю Python")
    tools.store.save(1, 0, state)
    before = tools.store.load(1)
    session = TelegramSession()
    bot = Bot("123456:TEST_TOKEN", session=session)
    dispatcher = build_dispatcher(TutorEngine(tools, model), Settings(allowed_user_ids="1"))
    try:
        with caplog.at_level(logging.WARNING):
            await dispatcher.feed_update(
                bot,
                Update(
                    update_id=1,
                    message=Message(
                        message_id=1,
                        date=datetime.now(UTC),
                        chat=Chat(id=1, type="private"),
                        from_user=User(id=1, is_bot=False, first_name="Test"),
                        text="без срока",
                    ),
                ),
            )
        assert "HTTP 403" in session.sent[-1].text
        assert "запретил доступ" in session.sent[-1].text
        assert "Не удалось завершить действие" not in session.sent[-1].text
        assert tools.store.load(1) == before
        assert "category=permission" in caplog.text
        assert secret not in caplog.text
        assert "gateway.invalid" not in caplog.text
        with pytest.raises(ModelError) as error:
            await model.generate("diagnostic", Diagnostic, {"goal": "Go"})
        details = json.dumps(error.value.diagnostics)
        assert secret not in details
        assert "gateway.invalid" not in details
    finally:
        await bot.session.close()
        await model.close()


@pytest.mark.parametrize(
    "error_type,category", [(APITimeoutError, "timeout"), (APIConnectionError, "connection")]
)
def test_transport_failure_messages(error_type, category):
    error = error_type(request=httpx.Request("POST", "https://example.invalid/responses"))
    translated = provider_failure(error, api_key="secret")
    assert translated.diagnostics["category"] == category
    assert "example.invalid" not in str(translated)


async def test_full_provider_error_logged_without_truncation_or_credentials(caplog):
    secret = "private-log-test-key"
    marker = "PROVIDER_ERROR_END"
    body = {
        "error": {
            "code": "permission_denied",
            "message": "Long explanation: " + "detail " * 600 + marker,
            "details": {"credential": secret, "upstream": "policy blocked model access"},
        }
    }
    model = await mocked_model(403, body, key=secret)
    try:
        with caplog.at_level(logging.ERROR), pytest.raises(ModelError) as error:
            await model.generate("diagnostic", Diagnostic, {"goal": "PRIVATE_LEARNER_INPUT"})
        record = next(r for r in caplog.records if "llm_failed" in r.getMessage())
        message = record.getMessage()
        assert error.value.diagnostics["id"] in message
        assert "http_status=403" in message
        assert '"operation": "diagnostic"' in message
        assert '"model": "gpt-6-luna"' in message
        assert marker in message and "policy blocked model access" in message
        assert "Traceback (most recent call last)" in message
        assert "PermissionDeniedError" in message
        assert secret not in message
        assert "PRIVATE_LEARNER_INPUT" not in message
        # A normal formatter must not append an unredacted original exception.
        assert record.exc_info is None
    finally:
        await model.close()


async def test_non_json_provider_response_and_request_id_logged(caplog):
    secret = "test-error-secret"
    model = await mocked_model(502, {}, key=secret)
    await model.client.close()
    model.client = AsyncOpenAI(
        api_key=secret,
        max_retries=0,
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    502,
                    text=f"<html>upstream unavailable {'detail ' * 500} END_HTML {secret}</html>",
                    headers={"x-request-id": "req-test-upstream"},
                )
            )
        ),
    )
    try:
        with caplog.at_level(logging.ERROR), pytest.raises(ModelError):
            await model.generate("diagnostic", Diagnostic, {"goal": "Go"})
        assert "request_id=req-test-upstream" in caplog.text
        assert "END_HTML" in caplog.text
        assert "<html>upstream unavailable" in caplog.text
        assert "InternalServerError" in caplog.text
        assert secret not in caplog.text
    finally:
        await model.close()


def test_transport_traceback_includes_redacted_chained_cause(caplog):
    secret = "transport-private-key"
    request = httpx.Request("POST", f"https://example.invalid/?key={secret}")
    with caplog.at_level(logging.ERROR):
        try:
            try:
                raise httpx.ReadTimeout(f"Socket timed out with {secret}", request=request)
            except httpx.ReadTimeout as cause:
                raise APITimeoutError(request=request) from cause
        except APITimeoutError as exc:
            provider_failure(exc, api_key=secret)
    assert "ReadTimeout: Socket timed out with [REDACTED]" in caplog.text
    assert "APITimeoutError" in caplog.text
    assert "direct cause" in caplog.text
    assert secret not in caplog.text
