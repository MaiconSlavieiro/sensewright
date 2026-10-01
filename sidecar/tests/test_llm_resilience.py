"""v0.5 R1: provider resilience — empty content is a failure + per-model cooldown."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx
import pytest

from sensewright_sidecar.config import ProviderConfig
from sensewright_sidecar.llm.base import LLMError
from sensewright_sidecar.llm.providers.openai_compat import OpenAICompatProvider

BASE_URL = "https://api.test/v1"


def _provider(models: list[str], **kwargs: Any) -> OpenAICompatProvider:
    config = ProviderConfig(
        enabled=True,
        api_key="test-key",
        models=models,
        base_url=BASE_URL,
        **kwargs,
    )
    return OpenAICompatProvider(config)


def _transport(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=BASE_URL)


async def test_empty_content_falls_through_to_next_model():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == "empty":
            return httpx.Response(
                200, json={"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}]}
        )

    provider = _provider(["empty", "working"])
    provider._client = _transport(handler)

    response = await provider.complete([{"role": "user", "content": "hi"}])

    assert seen == ["empty", "working"]
    assert response.model == "working"
    assert response.text == "hello"


async def test_empty_content_raises_when_only_model():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": None}, "finish_reason": "stop"}]}
        )

    provider = _provider(["only"])
    provider._client = _transport(handler)

    with pytest.raises(LLMError) as exc:
        await provider.complete([{"role": "user", "content": "hi"}])

    assert "empty content" in str(exc.value)


async def test_model_cooldown_retires_a_failing_model():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        seen.append(model)
        if model == "bad":
            return httpx.Response(
                200, json={"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )

    provider = _provider(["bad", "good"], model_failure_threshold=1, model_cooldown_seconds=120)
    provider._client = _transport(handler)

    first = await provider.complete([{"role": "user", "content": "hi"}])
    assert first.model == "good"
    assert seen == ["bad", "good"]
    assert "bad" in provider.model_cooldowns()

    # The cooled model is skipped on the next call.
    seen.clear()
    second = await provider.complete([{"role": "user", "content": "hi"}])
    assert second.model == "good"
    assert seen == ["good"]


async def test_attempt_logging(caplog):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}
        )

    provider = _provider(["m1"])
    provider._client = _transport(handler)

    with caplog.at_level(logging.INFO, logger="sensewright_sidecar.llm.providers.openai_compat"):
        await provider.complete([{"role": "user", "content": "hi"}], purpose="social")

    messages = [record.getMessage() for record in caplog.records]
    assert any("llm.attempt" in message and "outcome=ok" in message for message in messages)
    assert any("purpose=social" in message for message in messages)


async def test_finish_reason_length_without_content_is_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}]},
        )

    provider = _provider(["len"])
    provider._client = _transport(handler)

    with pytest.raises(LLMError):
        await provider.complete([{"role": "user", "content": "hi"}])
