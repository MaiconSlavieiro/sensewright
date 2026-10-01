"""Tests for the evolution module."""

from __future__ import annotations

import pytest

from sensewright_sidecar.agent.evolution import (
    REFLECTION_SHAPE,
    fallback_reflection,
    normalize_reflection,
    propose_trait_swap,
    reflect,
    should_reflect,
)
from sensewright_sidecar.llm.base import LLMResponse


class FakeRegistry:
    """Registry that returns a valid JSON reflection."""

    def __init__(self, reflection_text: str = "Test reflection.", insights: list[str] | None = None):
        self._reflection_text = reflection_text
        self._insights = insights or ["insight 1", "insight 2"]
        self.provider = "fake"

    async def complete(self, messages: list[dict[str, str]], *, lang: str, temperature: float, max_tokens: int, purpose: str | None = None) -> LLMResponse:
        json_payload = {
            "reflection": self._reflection_text,
            "insights": self._insights,
            "personality": "Drifted personality.",
            "trait_add": "creative",
            "trait_remove": "lazy",
            "trait_reason": "Events show creative bursts.",
        }
        import json
        text = json.dumps(json_payload)
        return LLMResponse(text=text, provider=self.provider, model="fake-model", raw={})


class FailingRegistry:
    """Registry that always raises."""

    async def complete(self, messages: list[dict[str, str]], *, lang: str, temperature: float, max_tokens: int, purpose: str | None = None) -> LLMResponse:
        raise RuntimeError("LLM unavailable")


def test_reflection_shape_keys():
    assert set(REFLECTION_SHAPE.keys()) == {"text", "insights", "personality", "source", "generated_at"}


def test_normalize_reflection_coercion():
    raw = {
        "text": "  hello  ",
        "insights": ["a", "b"],
        "personality": "  test  ",
        "source": "llm",
        "generated_at": 123.0,
    }
    out = normalize_reflection(raw)
    assert out["text"] == "hello"
    assert out["insights"] == ["a", "b"]
    assert out["personality"] == "test"
    assert out["source"] == "llm"
    assert out["generated_at"] == 123.0

    # Missing/extra keys handled
    out2 = normalize_reflection({"text": "x", "extra": 1})
    assert out2["text"] == "x"
    assert out2["insights"] == []
    assert out2["personality"] == ""
    assert out2["source"] == "template"
    assert isinstance(out2["generated_at"], float)


def test_fallback_reflection_en_vs_ptbr():
    profile = {"name": "Alice", "personality": "Friendly and curious."}
    events = [
        {"type": "chat", "content": {"message": "Hello world"}},
        {"type": "skill", "content": {"action": "painting"}},
    ]

    en = fallback_reflection(profile, events, "en")
    pt = fallback_reflection(profile, events, "pt-BR")

    assert en["source"] == "template"
    assert pt["source"] == "template"
    assert "Alice" in en["text"]
    assert "Alice" in pt["text"]
    assert en["text"] != pt["text"]
    assert en["personality"] == "Friendly and curious."
    assert pt["personality"] == "Friendly and curious."
    assert isinstance(en["generated_at"], float)
    assert isinstance(pt["generated_at"], float)


def test_should_reflect_min_events_and_cooldown():
    profile = {"name": "Bob"}
    events = [{"type": "chat"}] * 7
    assert should_reflect(profile, events, min_events=8, last_reflection_ts=0, now=1000) is False

    events = [{"type": "chat"}] * 8
    assert should_reflect(profile, events, min_events=8, last_reflection_ts=0, now=1000) is True

    # Cooldown not elapsed
    assert should_reflect(profile, events, min_events=8, last_reflection_ts=950, now=1000, cooldown_seconds=100) is False
    # Cooldown elapsed
    assert should_reflect(profile, events, min_events=8, last_reflection_ts=800, now=1000, cooldown_seconds=100) is True


@pytest.mark.asyncio
async def test_reflect_uses_llm():
    profile = {"name": "Carol", "personality": "Base personality."}
    events = [
        {"type": "chat", "content": {"message": "I love art"}},
        {"type": "skill", "content": {"action": "painting"}},
    ] * 5  # 10 events

    result = await reflect(profile, events, "en", registry=FakeRegistry())

    assert result["provider"] == "fake"
    assert result["reflection"]["source"] == "llm"
    assert result["reflection"]["text"] == "Test reflection."
    assert result["reflection"]["insights"] == ["insight 1", "insight 2"]
    assert result["reflection"]["personality"] == "Drifted personality."
    assert result["trait_swap"]["add"] == "creative"
    assert result["trait_swap"]["remove"] == "lazy"
    assert result["trait_swap"]["reason"] == "Events show creative bursts."


@pytest.mark.asyncio
async def test_reflect_falls_back_on_error():
    profile = {"name": "Dave", "personality": "Base."}
    events = [{"type": "chat"}] * 10

    result = await reflect(profile, events, "en", registry=FailingRegistry())

    assert result["provider"] is None
    assert result["reflection"]["source"] == "template"
    assert result["trait_swap"]["add"] is None
    assert result["trait_swap"]["remove"] is None


def test_propose_trait_swap_refuses_unknown_removal():
    profile = {"name": "Eve"}
    reflection = {"trait_add": "creative", "trait_remove": "unknown_trait", "trait_reason": "test"}

    # Without known_traits, removal passes through
    out = propose_trait_swap(profile, reflection)
    assert out["add"] == "creative"
    assert out["remove"] == "unknown_trait"

    # With known_traits, unknown removal is blocked
    out2 = propose_trait_swap(profile, reflection, known_traits=["creative", "lazy"])
    assert out2["add"] == "creative"
    assert out2["remove"] is None
    assert "blocked" in out2["reason"].lower()

    # Known removal allowed
    reflection2 = {"trait_add": "creative", "trait_remove": "lazy", "trait_reason": "test"}
    out3 = propose_trait_swap(profile, reflection2, known_traits=["creative", "lazy"])
    assert out3["add"] == "creative"
    assert out3["remove"] == "lazy"