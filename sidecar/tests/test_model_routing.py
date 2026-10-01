"""v0.5 R2: hybrid routing (purpose) + dynamic free model pool + auto-swap."""

from __future__ import annotations

import pytest

from sensewright_sidecar.config import LLMConfig, ProviderConfig, Settings
from sensewright_sidecar.llm.providers.openai_compat import (
    OpenAICompatProvider,
    _is_free_model,
)
from sensewright_sidecar.llm.registry import ProviderRegistry


def _provider(models: list[str], **kwargs) -> OpenAICompatProvider:
    config = ProviderConfig(enabled=True, api_key="k", models=models, **kwargs)
    return OpenAICompatProvider(config)


def test_is_free_model_recognizes_both_markers():
    assert _is_free_model("z-ai/glm-4.5-air:free")
    assert _is_free_model("mimo-v2.6-flash-free")
    assert not _is_free_model("gpt-4o")


def test_short_task_prefers_fast_models():
    provider = _provider(
        [
            "nvidia/nemotron-3-ultra-550b-a55b:free",
            "nvidia/nemotron-3.5-lightning:free",
            "mimo-v2.6-flash-free",
        ]
    )
    ordered = provider._candidate_models("social")
    assert ordered[0] == "nvidia/nemotron-3.5-lightning:free"
    assert ordered[1] == "mimo-v2.6-flash-free"
    assert ordered[-1] == "nvidia/nemotron-3-ultra-550b-a55b:free"


def test_long_task_keeps_configured_order():
    models = ["heavy:free", "flash:free"]
    provider = _provider(models)
    assert provider._candidate_models("profile") == models


def test_task_models_override_wins():
    provider = _provider(["a:free", "b:free", "c:free"])
    provider.task_models = {"social": ["c:free"]}
    ordered = provider._candidate_models("social")
    assert ordered[0] == "c:free"


def test_discovered_free_models_are_used_for_swap():
    provider = _provider(["cooled:free"])
    provider.discovered_models = ["fresh:free"]

    provider._mark_model_failure("cooled:free")
    provider._mark_model_failure("cooled:free")  # threshold 2 -> cold
    assert "cooled:free" in provider.model_cooldowns()

    selected = provider._select_models("social")
    assert selected == ["fresh:free"]


def test_free_only_guard_drops_paid_discovered_models():
    provider = _provider(["free:free"], free_only=True)
    provider.discovered_models = ["paid-model", "other:free"]
    ordered = provider._candidate_models("summary")
    assert "paid-model" not in ordered
    assert "other:free" in ordered


@pytest.mark.asyncio
async def test_filter_free_models_per_provider():
    assert await ProviderRegistry._filter_free_models(
        "opencode", ["a-free", "b", "c-free"]
    ) == ["a-free", "c-free"]
    assert await ProviderRegistry._filter_free_models(
        "openrouter", ["x:free", "y", "z:free"]
    ) == ["x:free", "z:free"]


@pytest.mark.asyncio
async def test_refresh_populates_pool(monkeypatch):
    settings = Settings(
        llm=LLMConfig(
            chain=["opencode"],
            providers={"opencode": ProviderConfig(enabled=True, api_key="k", model="base-free")},
            model_refresh_minutes=30,
        )
    )
    registry = ProviderRegistry(settings)

    async def fake_discover(name, provider):
        return ["model-a-free", "model-b", "model-c-free"]

    monkeypatch.setattr(registry, "_discover_provider_models", fake_discover)
    found = await registry.refresh_models()
    assert found == 2
    provider = registry.chain.get_provider("opencode")
    assert provider.discovered_models == ["model-a-free", "model-c-free"]


def test_chain_status_exposes_pool_and_health():
    settings = Settings(
        llm=LLMConfig(
            chain=["opencode"],
            providers={"opencode": ProviderConfig(enabled=True, api_key="k", model="base-free")},
        )
    )
    registry = ProviderRegistry(settings)
    status = registry.status()
    assert status["chain"]["health"]["providers_total"] == 1
    assert "opencode" in status["chain"]["pool"]
