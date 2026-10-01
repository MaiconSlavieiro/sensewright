"""v0.5 follow-up: GeminiProvider multi-model fallback, thinking budget, metering.

Google retired the 2.5-era models for new accounts and rejects
``thinkingBudget=0`` on 3.x with HTTP 400, so the provider now tries a model
list, counts every real request, treats empty content as a retryable failure and
only sends ``thinkingConfig`` when explicitly configured.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from sensewright_sidecar.config import ProviderConfig
from sensewright_sidecar.llm.base import LLMError
from sensewright_sidecar.llm.providers.gemini import GeminiProvider

BASE_URL = "https://generativelanguage.googleapis.com"


def _provider(models: list[str], **kwargs: Any) -> GeminiProvider:
    config = ProviderConfig(enabled=True, api_key="test-key", models=models, **kwargs)
    return GeminiProvider(config)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE_URL)


def _model_of(request: httpx.Request) -> str:
    return request.url.path.split("/models/")[1].split(":")[0]


def _ok(text: str = "ok") -> httpx.Response:
    return httpx.Response(
        200, json={"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}]}
    )


async def test_falls_through_retired_model():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = _model_of(request)
        seen.append(model)
        if model == "retired":
            return httpx.Response(404, json={"error": {"code": 404, "message": "no longer available"}})
        return _ok("hello")

    provider = _provider(["retired", "working"])
    provider._client = _client(handler)

    response = await provider.complete([{"role": "user", "content": "hi"}])

    assert seen == ["retired", "working"]
    assert response.model == "working"
    assert response.text == "hello"
    assert provider.requests_last_call == 2


async def test_empty_content_is_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": ""}]}, "finishReason": "MAX_TOKENS"}]}
        )

    provider = _provider(["only"])
    provider._client = _client(handler)

    with pytest.raises(LLMError) as exc:
        await provider.complete([{"role": "user", "content": "hi"}])

    assert "empty content" in str(exc.value)
    assert exc.value.retryable is True


async def test_tool_call_without_text_is_not_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"functionCall": {"name": "sit", "args": {}}}]},
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    provider = _provider(["m"])
    provider._client = _client(handler)

    response = await provider.complete([{"role": "user", "content": "hi"}])
    assert response.text == ""
    assert response.tool_calls[0].name == "sit"


async def test_thinking_budget_only_when_configured():
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payloads.append(json.loads(request.content))
        return _ok()

    provider = _provider(["m"])
    provider._client = _client(handler)
    await provider.complete([{"role": "user", "content": "hi"}])
    assert "thinkingConfig" not in payloads[-1]["generationConfig"]

    provider2 = _provider(["m"], thinking_budget=0)
    provider2._client = _client(handler)
    await provider2.complete([{"role": "user", "content": "hi"}])
    assert payloads[-1]["generationConfig"]["thinkingConfig"] == {"thinkingBudget": 0}


async def test_auth_error_aborts_provider():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(_model_of(request))
        return httpx.Response(403, json={"error": {"code": 403, "message": "API key not valid"}})

    provider = _provider(["a", "b"])
    provider._client = _client(handler)

    with pytest.raises(LLMError) as exc:
        await provider.complete([{"role": "user", "content": "hi"}])

    assert exc.value.retryable is False
    assert seen == ["a"]  # no point trying b with a bad key
