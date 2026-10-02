"""Tests for sensewright_sidecar.llm.chain (validation-driven failover)."""
from __future__ import annotations

from sensewright_sidecar.config import Config
from sensewright_sidecar.llm.base import ProviderResponse
from sensewright_sidecar.llm.chain import (
    INVALID_OUTPUT_COOLDOWN_SECONDS, ProviderChain,
)
from sensewright_sidecar.llm.scheduler import _extract_json


class _FakeProvider:
    """Returns reasoning prose for the 'bad' model, JSON for the 'good' one."""

    def __init__(self) -> None:
        self.calls = []

    def complete(self, messages, model, max_tokens=256, temperature=0.7, timeout=30.0):
        self.calls.append(model)
        text = (
            "The user provides a JSON with purpose sim.impulse... reasoning only"
            if model == "bad"
            else '{"thought": "ok", "intents": []}'
        )
        return ProviderResponse(text=text, prompt_tokens=1, completion_tokens=1,
                                total_tokens=2, model=model)


def _config(models):
    return Config({
        "llm": {
            "free_only": False,
            "providers": {
                "fake": {"enabled": True, "models": list(models), "rpm": 0, "rpd": 0, "tpm": 0},
            },
            "routes": {"default": {"provider": "fake", "model": models[0]}},
            "tiers": {},
        }
    })


def _only_json(response: ProviderResponse) -> bool:
    return bool(_extract_json(response.text))


def test_chain_skips_model_with_unusable_output():
    chain = ProviderChain(_config(["bad", "good"]))
    fake = _FakeProvider()
    chain._clients["fake"] = fake

    response, provider, model = chain.run(
        "sim.impulse", [{"role": "user", "content": "hi"}],
        max_tokens=50, temperature=0.0, timeout=5.0, validator=_only_json,
    )

    assert model == "good"
    assert provider == "fake"
    assert _extract_json(response.text)
    assert fake.calls == ["bad", "good"]

    # The unusable model is benched so we don't pay for it again.
    assert chain._invalid_cooling("fake", "bad") is True
    assert INVALID_OUTPUT_COOLDOWN_SECONDS > 0


def test_chain_returns_none_when_all_outputs_unusable():
    chain = ProviderChain(_config(["bad"]))
    chain._clients["fake"] = _FakeProvider()

    response, provider, model = chain.run(
        "sim.impulse", [{"role": "user", "content": "hi"}],
        max_tokens=50, temperature=0.0, timeout=5.0, validator=_only_json,
    )

    assert response is None
    assert provider is None
    assert model is None


def test_chain_without_validator_accepts_first_response():
    chain = ProviderChain(_config(["bad", "good"]))
    fake = _FakeProvider()
    chain._clients["fake"] = fake

    _, _, model = chain.run(
        "sim.impulse", [{"role": "user", "content": "hi"}],
        max_tokens=50, temperature=0.0, timeout=5.0,
    )

    assert model == "bad"
    assert fake.calls == ["bad"]
