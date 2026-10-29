import json
from decimal import Decimal

import httpx
import pytest
from openai import AsyncOpenAI

from tutor.budget import BudgetLimitError, units
from tutor.config import Settings
from tutor.llm import ModelError, OpenAITutor
from tutor.models import Diagnostic


async def model_with_response(body, *, simulate_timeout=False):
    called = []

    def respond(request):
        called.append(json.loads(request.content))
        if simulate_timeout:
            raise httpx.ReadTimeout("fixture", request=request)
        return httpx.Response(200, json=body)

    model = OpenAITutor(Settings(openai_api_key="test-only"))
    await model.client.close()
    model.client = AsyncOpenAI(
        api_key="test-only",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
    )
    return model, called


def response(*, content=None, usage=True, status="completed"):
    result = {
        "id": "resp_test",
        "object": "response",
        "created_at": 1,
        "status": status,
        "model": "gpt-6-luna",
        "service_tier": "default",
        "output": [
            {
                "type": "message",
                "id": "msg_test",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "annotations": [],
                        "text": content
                        or json.dumps(
                            {
                                "introduction": "Проверим знания",
                                "questions": ["Вопрос 1", "Вопрос 2"],
                            }
                        ),
                    }
                ],
            }
        ],
    }
    if usage:
        result["usage"] = {
            "input_tokens": 1000,
            "input_tokens_details": {"cached_tokens": 200, "cache_write_tokens": 300},
            "output_tokens": 100,
            "output_tokens_details": {"reasoning_tokens": 40},
            "total_tokens": 1100,
        }
    return result


async def test_actual_usage_charged_once_before_output_validation():
    model, calls = await model_with_response(response(content="not valid JSON"))
    try:
        with pytest.raises(ValueError):
            await model.generate("diagnostic", Diagnostic, {"goal": "Go"})
        assert len(calls) == 1
        assert calls[0]["service_tier"] == "default"
        # Hidden reasoning_tokens=40 is part of output_tokens=100; no double billing.
        expected = model.budget.cost(1000, 100, 200, 300)
        assert Decimal(model.budget.status()["spent_usd"]) == Decimal(expected) / 1_000_000_000
        assert Decimal(model.budget.status()["reserved_usd"]) == 0
    finally:
        await model.close()


async def test_budget_exhaustion_prevents_any_http_request():
    model, calls = await model_with_response(response())
    try:
        reserve = model.budget.reserve(units(Decimal(3)), model.model)
        model.budget.settle(reserve, units(Decimal(3)))
        with pytest.raises(BudgetLimitError):
            await model.generate("diagnostic", Diagnostic, {"goal": "Go"})
        assert calls == []
    finally:
        await model.close()


@pytest.mark.parametrize("missing_usage,simulate_timeout", [(True, False), (False, True)])
async def test_unknown_usage_conservatively_keeps_reserve(missing_usage, simulate_timeout):
    model, calls = await model_with_response(
        response(usage=not missing_usage), simulate_timeout=simulate_timeout
    )
    try:
        with pytest.raises(ModelError):
            await model.generate("diagnostic", Diagnostic, {"goal": "Go"})
        assert len(calls) == 1
        assert Decimal(model.budget.status()["estimated_usd"]) > 0
        assert Decimal(model.budget.status()["reserved_usd"]) == 0
    finally:
        await model.close()


@pytest.mark.parametrize("failure", ["invalid_json", "incomplete", "missing_usage"])
async def test_invalid_success_response_is_logged_in_full(failure, caplog):
    body = response(
        content="NOT_JSON_END" if failure == "invalid_json" else None,
        usage=failure != "missing_usage",
        status="incomplete" if failure == "incomplete" else "completed",
    )
    if failure == "incomplete":
        body["incomplete_details"] = {"reason": "max_output_tokens"}
    model, _ = await model_with_response(body)
    try:
        with pytest.raises((ModelError, ValueError)):
            await model.generate("diagnostic", Diagnostic, {"goal": "Go"})
        assert "phase" in caplog.text and "response_validation" in caplog.text
        assert '"id": "resp_test"' in caplog.text
        assert "Traceback (most recent call last)" in caplog.text
        if failure == "invalid_json":
            assert "NOT_JSON_END" in caplog.text
        elif failure == "incomplete":
            assert "max_output_tokens" in caplog.text
        else:
            assert "Provider omitted usage" in caplog.text
    finally:
        await model.close()
