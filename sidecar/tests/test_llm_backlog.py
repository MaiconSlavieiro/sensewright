"""v0.5 follow-up §7.12: A2-A6 LLM provider/chain/registry backlog fixes.

A1/A7-A10 are config-template changes covered by ``test_config_example_backlog``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from sensewright_sidecar.config import LLMConfig, ProviderConfig, Settings
from sensewright_sidecar.llm.base import AllProvidersFailed
from sensewright_sidecar.llm.chain import ProviderChain
from sensewright_sidecar.llm.limits import ProviderRateLimiter
from sensewright_sidecar.llm.providers import PROVIDER_CLASSES
from sensewright_sidecar.llm.providers.openai_compat import (
    OpenAICompatProvider,
    OpenCodeZenProvider,
)
from sensewright_sidecar.llm.registry import ProviderRegistry

BASE_URL = "https://api.test/v1"


# ── A2: rate limit counts every real request ──────────────────────────────


def test_rate_limiter_has_capacity_and_record():
    clock = [1000.0]
    limiter = ProviderRateLimiter(
        rpm=2,
        rpd=0,
        monotonic=lambda: clock[0],
        wall_clock=lambda: clock[0],
    )

    assert limiter.has_capacity() is True
    limiter.record(2)
    assert limiter.has_capacity() is False  # RPM exhausted, never consumed by record
    snap = limiter.snapshot()
    assert snap["minute_used"] == 2
    assert snap["total_used"] == 2

    clock[0] += 61.0
    assert limiter.has_capacity() is True


@pytest.mark.asyncio
async def test_chain_records_every_real_request():
    """One chain call that tries two models must meter two requests (A2)."""
    settings = Settings(
        llm=LLMConfig(
            chain=["openrouter"],
            providers={
                "openrouter": ProviderConfig(
                    enabled=True,
                    api_key="k",
                    models=["empty", "working"],
                    base_url=BASE_URL,
                    rpm=10,
                )
            },
        )
    )

    chain = ProviderChain(settings)
    provider = chain.get_provider("openrouter")
    assert isinstance(provider, OpenAICompatProvider)

    def handler(request: httpx.Request) -> httpx.Response:
        model = json.loads(request.content)["model"]
        if model == "empty":
            return httpx.Response(
                200, json={"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]}
            )
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}
        )

    provider._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=BASE_URL
    )

    response = await chain.complete([{"role": "user", "content": "hi"}], lang="en")
    assert response.model == "working"
    assert provider.requests_last_call == 2

    snap = chain.status()["limits"]["openrouter"]
    assert snap["minute_used"] == 2
    assert snap["day_used"] == 2


# ── A3: failure-triggered refresh is throttled ─────────────────────────────


@pytest.mark.asyncio
async def test_failure_refresh_is_throttled(monkeypatch):
    settings = Settings(
        llm=LLMConfig(
            chain=["openrouter"],
            providers={"openrouter": ProviderConfig(enabled=True, api_key="k", model="m:free")},
            refresh_on_failure_min_seconds=60.0,
        )
    )
    registry = ProviderRegistry(settings)

    refresh_calls = 0

    async def always_fail(*args: Any, **kwargs: Any):
        raise AllProvidersFailed("nope", ["openrouter"])

    async def fake_refresh(*, force: bool = False) -> int:
        nonlocal refresh_calls
        refresh_calls += 1
        return 0

    monkeypatch.setattr(registry.chain, "complete", always_fail)
    monkeypatch.setattr(registry, "refresh_models", fake_refresh)

    for _ in range(3):
        with pytest.raises(AllProvidersFailed):
            await registry.complete([{"role": "user", "content": "hi"}])

    assert refresh_calls == 1


# ── A4: per-provider discovery toggle ──────────────────────────────────────


@pytest.mark.asyncio
async def test_discovery_disabled_returns_no_models():
    settings = Settings(
        llm=LLMConfig(
            chain=["opencode"],
            providers={
                "opencode": ProviderConfig(
                    enabled=True, api_key="k", model="space-bunny-free", discover_models=False
                )
            },
        )
    )
    registry = ProviderRegistry(settings)
    provider = registry.chain.get_provider("opencode")
    assert await registry._discover_provider_models("opencode", provider) == []


@pytest.mark.asyncio
async def test_refresh_skips_discovery_disabled_provider(monkeypatch):
    settings = Settings(
        llm=LLMConfig(
            chain=["opencode"],
            providers={
                "opencode": ProviderConfig(
                    enabled=True, api_key="k", model="space-bunny-free", discover_models=False
                )
            },
        )
    )
    registry = ProviderRegistry(settings)

    async def fake_discover(name: str, provider: Any) -> list[str]:
        return ["should-not-be-used-free"]

    monkeypatch.setattr(registry, "_discover_provider_models", fake_discover)
    found = await registry.refresh_models()
    assert found == 0
    assert registry.chain.get_provider("opencode").discovered_models == []


# ── A5: generic config-driven openai_compat provider ───────────────────────


def test_chain_resolves_generic_provider_by_type():
    settings = Settings(
        llm=LLMConfig(
            chain=["groq"],
            providers={
                "groq": ProviderConfig(
                    enabled=True,
                    type="openai_compat",
                    api_key="k",
                    model="llama",
                    base_url="https://api.groq.com/openai/v1",
                )
            },
        )
    )
    chain = ProviderChain(settings)
    provider = chain.get_provider("groq")
    assert provider is not None
    assert type(provider) is OpenAICompatProvider  # not a name-specific subclass
    assert provider.name == "groq"  # keyed by the config block, not the class
    assert "groq" in chain.status()["limits"]
    assert chain.status()["providers"]["groq"]["name"] == "groq"
    assert PROVIDER_CLASSES["openai_compat"] is OpenAICompatProvider


# ── A6: local providers may omit the API key ───────────────────────────────


def test_provider_available_without_api_key_when_optional():
    config = ProviderConfig(
        enabled=True,
        type="openai_compat",
        api_key="",
        api_key_optional=True,
        model="granite4.1:8b",
        base_url="http://localhost:11434/v1",
    )
    provider = OpenAICompatProvider(config)
    assert provider.available is True

    client = provider._get_client()
    assert "Authorization" not in client.headers


def test_provider_unavailable_without_key_by_default():
    config = ProviderConfig(enabled=True, api_key="", base_url=BASE_URL)
    assert OpenAICompatProvider(config).available is False


# ── A1/A7/A8/A9/A10: config template ───────────────────────────────────────


def test_config_example_backlog():
    import tomllib

    root = Path(__file__).resolve().parents[2]
    with (root / "config.example.toml").open("rb") as fh:
        config = tomllib.load(fh)

    chain = config["llm"]["chain"]
    assert chain[-1] == "deepseek"  # A8: paid last resort
    assert "ollama" in chain  # A7
    assert config["llm"]["providers"]["openrouter"]["rpd"] == 1000  # A1
    assert config["llm"]["providers"]["opencode"]["discover_models"] is False  # A4
    ollama = config["llm"]["providers"]["ollama"]
    assert ollama["type"] == "openai_compat"  # A5
    assert ollama["api_key_optional"] is True  # A6
    assert "deepseek-flash" in config["llm"]["providers"]["deepseek"]["models"]  # A8
    assert config["llm"]["refresh_on_failure_min_seconds"] == 60.0  # A3
    # A10: reduced volume.
    assert config["agents"]["initiative"]["impulse_frequency"] <= 0.1
    assert config["god"]["backgrounds"]["daily_limit"] <= 60


def test_opencode_zen_remains_a_named_provider():
    assert PROVIDER_CLASSES["opencode"] is OpenCodeZenProvider
