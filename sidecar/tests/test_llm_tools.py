"""Tests for LLM function/tool-calling support (fully offline)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from sensewright_sidecar.config import LLMConfig, ProviderConfig, Settings
from sensewright_sidecar.llm.base import LLMError, LLMResponse
from sensewright_sidecar.llm.chain import ProviderChain
from sensewright_sidecar.llm.providers import PROVIDER_CLASSES
from sensewright_sidecar.llm.providers.gemini import GeminiProvider
from sensewright_sidecar.llm.providers.openai_compat import (
    OpenAICompatProvider,
    OpenCodeZenProvider,
)
from sensewright_sidecar.llm.registry import ProviderRegistry

OPENAI_BASE_URL = "https://api.openai.com/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com"

TOOL_SCHEMA: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get the weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
]


def make_openai_provider(handler) -> OpenAICompatProvider:
    """Build an OpenAI-compatible provider wired to a mock transport."""
    config = ProviderConfig(
        enabled=True,
        api_key="test-key",
        model="test-model",
        base_url=OPENAI_BASE_URL,
    )
    provider = OpenAICompatProvider(config)
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=OPENAI_BASE_URL,
    )
    return provider


def make_gemini_provider(handler) -> GeminiProvider:
    """Build a Gemini provider wired to a mock transport."""
    config = ProviderConfig(
        enabled=True,
        api_key="test-key",
        model="gemini-1.5-flash",
    )
    provider = GeminiProvider(config)
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=GEMINI_BASE_URL,
    )
    return provider


def openai_response(message: dict[str, Any]) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": message}]})


async def test_openai_parses_tool_calls_and_text():
    def handler(request: httpx.Request) -> httpx.Response:
        return openai_response(
            {
                "content": "Let me check",
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": json.dumps({"city": "Paris"}),
                        },
                    }
                ],
            }
        )

    provider = make_openai_provider(handler)
    response = await provider.complete(
        [{"role": "user", "content": "weather?"}],
        tools=TOOL_SCHEMA,
    )

    assert response.text == "Let me check"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.id == "call_abc"
    assert call.name == "get_weather"
    assert call.arguments == {"city": "Paris"}


async def test_openai_malformed_arguments_fall_back_to_raw():
    def handler(request: httpx.Request) -> httpx.Response:
        return openai_response(
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_bad",
                        "type": "function",
                        "function": {"name": "broken", "arguments": "not-json"},
                    }
                ],
            }
        )

    provider = make_openai_provider(handler)
    response = await provider.complete([{"role": "user", "content": "hi"}], tools=TOOL_SCHEMA)

    assert response.tool_calls[0].arguments == {"_raw": "not-json"}


async def test_openai_missing_id_generates_indexed_id():
    def handler(request: httpx.Request) -> httpx.Response:
        return openai_response(
            {
                "content": "",
                "tool_calls": [
                    {"type": "function", "function": {"name": "one", "arguments": "{}"}},
                    {"type": "function", "function": {"name": "two", "arguments": "{}"}},
                ],
            }
        )

    provider = make_openai_provider(handler)
    response = await provider.complete([{"role": "user", "content": "hi"}], tools=TOOL_SCHEMA)

    assert [call.id for call in response.tool_calls] == ["call_0", "call_1"]


async def test_openai_no_tools_produces_empty_tuple():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return openai_response({"content": "plain answer"})

    provider = make_openai_provider(handler)
    response = await provider.complete([{"role": "user", "content": "hi"}])

    assert response.tool_calls == ()
    assert response.text == "plain answer"
    assert "tools" not in captured["payload"]
    assert "tool_choice" not in captured["payload"]


async def test_openai_includes_tools_in_payload():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return openai_response({"content": "ok"})

    provider = make_openai_provider(handler)
    await provider.complete([{"role": "user", "content": "hi"}], tools=TOOL_SCHEMA)

    assert captured["payload"]["tools"] == TOOL_SCHEMA
    assert captured["payload"]["tool_choice"] == "auto"


async def test_gemini_parses_function_call_and_text():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {"text": "Checking now"},
                                {"functionCall": {"name": "get_weather", "args": {"city": "Rome"}}},
                            ]
                        }
                    }
                ]
            },
        )

    provider = make_gemini_provider(handler)
    response = await provider.complete(
        [{"role": "user", "content": "weather?"}],
        tools=TOOL_SCHEMA,
    )

    assert response.text == "Checking now"
    assert len(response.tool_calls) == 1
    call = response.tool_calls[0]
    assert call.id == "gemini_call_0"
    assert call.name == "get_weather"
    assert call.arguments == {"city": "Rome"}

    declarations = captured["payload"]["tools"][0]["functionDeclarations"]
    assert declarations == [
        {
            "name": "get_weather",
            "description": "Get the weather for a city",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        }
    ]


async def test_gemini_no_tools_produces_empty_tuple():
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"candidates": [{"content": {"parts": [{"text": "hello"}]}}]},
        )

    provider = make_gemini_provider(handler)
    response = await provider.complete([{"role": "user", "content": "hi"}])

    assert response.tool_calls == ()
    assert response.text == "hello"
    assert "tools" not in captured["payload"]


async def test_openai_falls_back_to_next_model_on_rate_limit():
    """A 429 on one model must try the provider's next model before giving up."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload["model"])
        if payload["model"] == "primary-model":
            return httpx.Response(429, json={"error": "rate limited"})
        return openai_response({"content": "from backup"})

    config = ProviderConfig(
        enabled=True,
        api_key="test-key",
        model="primary-model",
        models=["backup-model", "third-model"],
        base_url=OPENAI_BASE_URL,
    )
    provider = OpenAICompatProvider(config)
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=OPENAI_BASE_URL,
    )

    response = await provider.complete([{"role": "user", "content": "hi"}])

    assert response.model == "backup-model"
    assert response.text == "from backup"
    assert seen == ["primary-model", "backup-model"]


async def test_openai_auth_error_does_not_try_other_models():
    """A 401 is provider-wide, so the remaining models are not attempted."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload["model"])
        return httpx.Response(401, json={"error": "bad key"})

    config = ProviderConfig(
        enabled=True,
        api_key="test-key",
        model="primary-model",
        models=["backup-model"],
        base_url=OPENAI_BASE_URL,
    )
    provider = OpenAICompatProvider(config)
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=OPENAI_BASE_URL,
    )

    with pytest.raises(LLMError) as exc_info:
        await provider.complete([{"role": "user", "content": "hi"}])

    assert seen == ["primary-model"]
    assert exc_info.value.status == 401


async def test_openai_forbidden_tries_next_model():
    """A 403 is model-level: the provider must still try its next model."""
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.append(payload["model"])
        if payload["model"] == "blocked-model":
            return httpx.Response(403, json={"error": "not allowed"})
        return openai_response({"content": "from allowed"})

    config = ProviderConfig(
        enabled=True,
        api_key="test-key",
        model="blocked-model",
        models=["allowed-model"],
        base_url=OPENAI_BASE_URL,
    )
    provider = OpenAICompatProvider(config)
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=OPENAI_BASE_URL,
    )

    response = await provider.complete([{"role": "user", "content": "hi"}])

    assert response.model == "allowed-model"
    assert seen == ["blocked-model", "allowed-model"]


def test_free_only_guard_drops_paid_models():
    paid = ProviderConfig(
        enabled=True,
        api_key="k",
        model="paid-model",
        models=["free-model:free", "other-paid"],
    )
    assert OpenAICompatProvider(paid)._candidate_models() == [
        "paid-model",
        "free-model:free",
        "other-paid",
    ]

    guarded = ProviderConfig(
        enabled=True,
        api_key="k",
        model="paid-model",
        models=["free-model:free", "other-paid"],
        free_only=True,
    )
    assert OpenAICompatProvider(guarded)._candidate_models() == ["free-model:free"]


async def test_free_only_with_no_free_models_fails_retryably():
    config = ProviderConfig(enabled=True, api_key="k", models=["paid-model"], free_only=True)
    provider = OpenAICompatProvider(config)

    with pytest.raises(LLMError) as exc_info:
        await provider.complete([{"role": "user", "content": "hi"}])

    assert exc_info.value.retryable is True


def test_opencode_zen_provider_defaults_and_registration():
    provider = OpenCodeZenProvider(
        ProviderConfig(enabled=True, api_key="zen-key", models=["space-bunny-free"])
    )

    assert provider.name == "opencode"
    assert provider.config.base_url == "https://opencode.ai/zen/v1"
    assert PROVIDER_CLASSES["opencode"] is OpenCodeZenProvider


class RecordingProvider:
    """Fake provider that records the tools it receives."""

    name = "recorder"

    def __init__(self) -> None:
        self.received_tools: list[dict[str, Any]] | None = None
        self._failure_count = 0
        self._cold_until = 0.0

    @property
    def available(self) -> bool:
        return True

    def _is_cold(self) -> bool:
        return False

    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMResponse:
        self.received_tools = tools
        return LLMResponse(text="ok", provider=self.name, model="test-model", raw={})

    def status(self) -> dict[str, Any]:
        return {"name": self.name, "available": self.available}


def make_settings() -> Settings:
    providers = {"recorder": ProviderConfig(enabled=True, api_key="key", model="model")}
    return Settings(
        llm=LLMConfig(chain=["recorder"], providers=providers),
    )


async def test_chain_forwards_tools_to_provider():
    settings = make_settings()
    with patch("sensewright_sidecar.llm.chain.PROVIDER_CLASSES", {}):
        chain = ProviderChain(settings)
        provider = RecordingProvider()
        chain._providers = [provider]
        chain._provider_map = {"recorder": provider}
        chain._chain_order = ["recorder"]

        response = await chain.complete(
            [{"role": "user", "content": "hi"}],
            lang="en",
            tools=TOOL_SCHEMA,
        )

    assert response.text == "ok"
    assert provider.received_tools == TOOL_SCHEMA


class RecordingChain:
    """Fake chain that records the kwargs it receives."""

    def __init__(self) -> None:
        self.received: dict[str, Any] | None = None

    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        self.received = kwargs
        return LLMResponse(text="ok", provider="recorder", model="m", raw={})


async def test_registry_forwards_tools_to_chain(settings: Settings):
    registry = ProviderRegistry(settings)
    recording = RecordingChain()
    registry.chain = recording  # type: ignore[assignment]

    await registry.complete(
        [{"role": "user", "content": "hi"}],
        tools=TOOL_SCHEMA,
    )

    assert recording.received is not None
    assert recording.received["tools"] == TOOL_SCHEMA


def _reasoning_provider(supports: bool, captured: dict) -> OpenAICompatProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        captured["json"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    config = ProviderConfig(
        enabled=True,
        api_key="test-key",
        model="test-model",
        base_url=OPENAI_BASE_URL,
        supports_reasoning=supports,
    )
    provider = OpenAICompatProvider(config)
    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=OPENAI_BASE_URL
    )
    return provider


async def test_openai_provider_forwards_reasoning_effort():
    captured: dict = {}
    provider = _reasoning_provider(True, captured)

    await provider.complete([{"role": "user", "content": "hi"}], reasoning_effort="minimal")

    assert captured["json"]["reasoning"]["effort"] == "minimal"


async def test_openai_provider_omits_reasoning_when_unsupported():
    captured: dict = {}
    provider = _reasoning_provider(False, captured)

    await provider.complete([{"role": "user", "content": "hi"}], reasoning_effort="high")

    assert "reasoning" not in captured["json"]


async def test_openai_provider_omits_reasoning_when_none():
    captured: dict = {}
    provider = _reasoning_provider(True, captured)

    await provider.complete([{"role": "user", "content": "hi"}], reasoning_effort=None)

    assert "reasoning" not in captured["json"]
