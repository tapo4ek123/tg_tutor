"""Public error messages and complete, credential-redacted server diagnostics."""

import json
import logging
import re
import traceback
from uuid import uuid4

from openai import APIConnectionError, APITimeoutError

logger = logging.getLogger(__name__)


class ModelError(RuntimeError):
    def __init__(self, message: str, *, diagnostics: dict | None = None):
        super().__init__(message)
        self.diagnostics = diagnostics or {}


def redact(value: str, secrets: tuple[str, ...] = (), *, limit: int | None = 1000) -> str:
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[REDACTED]")
    value = re.sub(r"(?i)Bearer\s+[^\s\"'<>]+", "Bearer [REDACTED]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED]", value)
    value = re.sub(r"\b\d{6,}:[A-Za-z0-9_-]{15,}", "[REDACTED]", value)
    value = re.sub(r"https?://[^\s\"'<>]+", "[URL]", value)
    return value[:limit] if limit is not None else value


def log_model_failure(
    exc: Exception,
    *,
    api_key: str,
    diagnostics: dict | None = None,
    context: dict | None = None,
    response=None,
) -> dict:
    """Format before logging: exc_info would bypass redaction in logging formatters."""
    details = dict(diagnostics or {})
    details.setdefault("id", uuid4().hex[:10])
    details.setdefault("category", "response_validation" if response is not None else "unexpected")
    details.setdefault("http_status", getattr(exc, "status_code", None))
    details.setdefault("exception", type(exc).__name__)
    http_response = getattr(exc, "response", None)
    request_id = getattr(exc, "request_id", None)
    if http_response is not None:
        request_id = request_id or http_response.headers.get("x-request-id")
        body = http_response.text
    elif response is not None:
        body = (
            response.model_dump_json(indent=2)
            if hasattr(response, "model_dump_json")
            else json.dumps(response, ensure_ascii=False, default=str)
        )
        request_id = getattr(response, "_request_id", None)
    else:
        body = json.dumps(getattr(exc, "body", None), ensure_ascii=False, default=str)
    trace = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    # No request payload or headers: the response and chained traceback are sufficient.
    message = (
        f"llm_failed id={details['id']} category={details['category']} "
        f"http_status={details['http_status']} exception={details['exception']} "
        f"request_id={request_id}\n"
        f"context={json.dumps(context or {}, ensure_ascii=False, default=str)}\n"
        f"provider_response:\n{body}\ntraceback:\n{trace}"
    )
    logger.error("%s", redact(message, (api_key,), limit=None))
    return details


def provider_failure(exc: Exception, *, api_key: str, context: dict | None = None) -> ModelError:
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    error = body.get("error", body) if isinstance(body, dict) else {}
    if not isinstance(error, dict):
        error = {"message": str(error)}
    code = str(error.get("code") or getattr(exc, "code", None) or "unknown")
    message = str(error.get("message") or "")
    hints = (code + " " + message).lower()
    if isinstance(exc, APITimeoutError):
        category = "timeout"
        text = "Провайдер модели не ответил вовремя. Повторите действие позже."
    elif isinstance(exc, APIConnectionError):
        category = "connection"
        text = (
            "Не удалось соединиться с провайдером модели. "
            "Проверьте сеть и DEEPSEEK_BASE_URL на сервере бота."
        )
    elif status == 401:
        category = "authentication"
        text = (
            "Провайдер отклонил API-ключ. Проверьте DEEPSEEK_API_KEY и соответствие "
            "ключа выбранному DEEPSEEK_BASE_URL. После изменения .env перезапустите бота."
        )
    elif status == 403:
        category = "permission"
        if any(word in hints for word in ("unsupported_country", "region", "territory")):
            text = "Провайдер запретил запрос из текущего региона сервера бота."
        elif "model" in hints:
            text = (
                "Провайдер запретил доступ к выбранной модели. "
                "Проверьте права API-ключа и доступность DEEPSEEK_MODEL у провайдера."
            )
        else:
            text = (
                "Провайдер модели запретил доступ. Проверьте права API-ключа, "
                "доступность модели и ограничения доступа у провайдера."
            )
        text += "\nПроверка на сервере: python -m tutor.doctor"
    elif status in (402, 429) and any(
        word in hints for word in ("quota", "billing", "credit", "balance")
    ):
        category = "quota"
        text = "У провайдера исчерпан баланс или квота API. Проверьте лимиты проекта и оплату."
    elif status == 429:
        category = "rate_limit"
        text = "Провайдер временно ограничил частоту запросов. Попробуйте позже."
    elif status == 404:
        category = "not_found"
        if "model" in hints:
            text = (
                "Провайдер не нашёл выбранную модель. Проверьте DEEPSEEK_MODEL и права API-ключа."
            )
        else:
            text = (
                "API вернул 404. Проверьте DEEPSEEK_BASE_URL: нужен базовый адрес API "
                "(для DeepSeek — https://api.deepseek.com), нужен endpoint /responses."
            )
    elif status in (400, 405, 422, 501):
        category = "request_format"
        text = (
            "Провайдер отклонил формат запроса. Проверьте поддержку Responses API, "
            "Structured Outputs и параметров выбранной модели. "
            "Подробности: python -m tutor.doctor"
        )
    elif status and status >= 500:
        category = "provider_unavailable"
        text = "Сбой на стороне провайдера модели. Попробуйте позже."
    else:
        category = "provider_response"
        text = "Провайдер вернул некорректный ответ. Проверка: python -m tutor.doctor"
    error_id = uuid4().hex[:10]
    diagnostics = {
        "id": error_id,
        "category": category,
        "exception": type(exc).__name__,
        "http_status": status,
        "provider_code": redact(code, (api_key,)),
        "provider_message": redact(message, (api_key,)),
    }
    log_model_failure(exc, api_key=api_key, diagnostics=diagnostics, context=context)
    suffix = f"HTTP {status}; " if status else ""
    return ModelError(text + f"\n({suffix}код диагностики: {error_id})", diagnostics=diagnostics)


def format_diagnostics(error: ModelError) -> str:
    """Compact CLI diagnostics; complete redacted errors are in the server log."""
    return json.dumps(error.diagnostics, ensure_ascii=False, indent=2)
