"""Tests for the God agent zeitgeist service."""

from __future__ import annotations

from sensewright_sidecar.god.zeitgeist import (
    build_local_template,
    normalize_zeitgeist,
    suggest_zeitgeist,
    zeitgeist_to_prompt_block,
)
from sensewright_sidecar.llm.base import LLMResponse


class FakeRegistry:
    """Registry stub returning a canned LLM response."""

    def __init__(self, text: str = "A rewritten zeitgeist."):
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, messages, **kwargs) -> LLMResponse:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return LLMResponse(text=self.text, provider="fake", model="m", raw={})


class FailingRegistry:
    """Registry stub that always raises."""

    async def complete(self, messages, **kwargs) -> LLMResponse:
        raise RuntimeError("provider down")


def test_normalize_zeitgeist_filters_tags_and_clamps_influence():
    result = normalize_zeitgeist(
        {
            "mood_tags": ["drama", "bogus", "drama", "romance"],
            "free_text": "rainy week",
            "rewritten_text": "stories",
            "mood_influence": 5.0,
            "configured": True,
            "updated_at": 12.5,
        }
    )

    assert result["mood_tags"] == ["drama", "romance"]
    assert result["free_text"] == "rainy week"
    assert result["rewritten_text"] == "stories"
    assert result["mood_influence"] == 1.0
    assert result["configured"] is True
    assert result["updated_at"] == 12.5


def test_normalize_zeitgeist_clamps_below_zero_and_handles_garbage():
    result = normalize_zeitgeist(
        {
            "mood_tags": "drama, not-a-tag, caos",
            "free_text": None,
            "mood_influence": -3,
            "updated_at": "nope",
        }
    )

    assert result["mood_tags"] == ["drama", "caos"]
    assert result["free_text"] == ""
    assert result["mood_influence"] == 0.0
    assert result["updated_at"] is None
    assert result["configured"] is False


def test_build_local_template_is_deterministic():
    first = build_local_template(["drama", "romance"], "keep it grounded")
    second = build_local_template(["drama", "romance"], "keep it grounded")

    assert first == second
    assert "emotional conflict" in first
    assert "romantic entanglements" in first
    assert "grounded" in first.lower()


def test_zeitgeist_to_prompt_block_contains_pieces():
    block = zeitgeist_to_prompt_block(
        {"mood_tags": ["caos"], "free_text": "wild", "mood_influence": 0.9}
    )

    assert "Mood tags: caos" in block
    assert "Mood influence: 0.90" in block
    assert "Player notes: wild" in block


async def test_suggest_zeitgeist_uses_registry():
    registry = FakeRegistry(text="The neighborhood hums with drama.")

    result = await suggest_zeitgeist(
        {"sims": [{"full_name": "Bella Goth"}], "households": [{}]},
        ["drama", "nope"],
        "a storm is coming",
        "en",
        registry,
    )

    assert result["provider"] == "fake"
    assert result["suggested_text"] == "The neighborhood hums with drama."
    assert result["mood_tags"] == ["drama"]
    assert registry.calls


async def test_suggest_zeitgeist_without_registry_uses_template():
    result = await suggest_zeitgeist({}, ["romance"], "summer fling", "en", None)

    assert result["provider"] is None
    assert result["mood_tags"] == ["romance"]
    assert result["suggested_text"] == build_local_template(["romance"], "summer fling")


async def test_suggest_zeitgeist_falls_back_on_error():
    result = await suggest_zeitgeist({}, ["drama"], "notes", "pt-BR", FailingRegistry())

    assert result["provider"] is None
    assert result["suggested_text"] == build_local_template(["drama"], "notes")
