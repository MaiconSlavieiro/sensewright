"""Tests for v0.2 M1 dialogue consolidation."""

from __future__ import annotations

import json

from sims_sense_sidecar.llm.base import LLMResponse
from sims_sense_sidecar.memory.consolidation import (
    consolidate_turns,
    deterministic_consolidation,
)

TURNS = [
    {
        "type": "chat",
        "content": {"role": "user", "message": "Bella, I am so happy to see you! I love this town."},
    },
    {
        "type": "chat",
        "content": {
            "role": "assistant",
            "message": "I am happy too, and I am excited about the festival.",
        },
    },
    {"type": "chat", "content": {"role": "user", "message": "The festival in this town is wonderful."}},
]

PROFILE = {"name": "Bella Goth", "backstory": "mysterious"}

EXPECTED_KEYS = {
    "summary",
    "topics",
    "emotional_takeaways",
    "facts",
    "relationships_touched",
    "source",
}


class FakeRegistry:
    """Registry returning a canned consolidation JSON payload."""

    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, messages, **kwargs) -> LLMResponse:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return LLMResponse(text=self.text, provider="fake", model="m", raw={})


class FailingRegistry:
    """Registry that always raises."""

    async def complete(self, messages, **kwargs) -> LLMResponse:
        raise RuntimeError("provider down")


def test_deterministic_shape_and_content():
    out = deterministic_consolidation(TURNS, PROFILE, "en")

    assert set(out) == EXPECTED_KEYS
    assert out["source"] == "template"
    assert out["summary"]
    assert "town" in out["topics"]
    assert out["facts"] == ["Bella Goth took part in this conversation."]


def test_deterministic_emotional_takeaways_and_relationships():
    out = deterministic_consolidation(TURNS, PROFILE, "en")

    assert "felt joy" in out["emotional_takeaways"]
    assert "felt excitement" in out["emotional_takeaways"]
    assert "Bella" in out["relationships_touched"]


def test_deterministic_handles_empty_input():
    out = deterministic_consolidation([], {}, "en")

    assert set(out) == EXPECTED_KEYS
    assert out["summary"]
    assert out["topics"] == []
    assert out["facts"] == []
    assert out["relationships_touched"] == []
    assert out["source"] == "template"


def test_deterministic_accepts_string_content():
    turns = [{"type": "chat", "content": "just a raw string turn"}]
    out = deterministic_consolidation(turns, {}, "en")
    assert out["summary"] == "just a raw string turn"


async def test_consolidate_without_registry_matches_deterministic():
    out = await consolidate_turns(TURNS, PROFILE, None, "en")
    assert out == deterministic_consolidation(TURNS, PROFILE, "en")


async def test_consolidate_falls_back_when_registry_raises():
    out = await consolidate_turns(TURNS, PROFILE, FailingRegistry(), "en")
    fallback = deterministic_consolidation(TURNS, PROFILE, "en")
    assert out["source"] == "template"
    assert out["summary"] == fallback["summary"]


async def test_consolidate_falls_back_on_bad_json():
    out = await consolidate_turns(TURNS, PROFILE, FakeRegistry("not json at all"), "en")
    assert out["source"] == "template"


async def test_consolidate_uses_registry_json():
    payload = {
        "summary": "A joyful reunion downtown.",
        "topics": ["festival", "friendship"],
        "emotional_takeaways": ["felt joy"],
        "facts": ["Bella lives in town."],
        "relationships_touched": ["Bella"],
    }
    registry = FakeRegistry(json.dumps(payload))

    out = await consolidate_turns(TURNS, PROFILE, registry, "en")

    assert out["source"] == "fake"
    assert out["summary"] == "A joyful reunion downtown."
    assert out["topics"] == ["festival", "friendship"]
    assert out["facts"] == ["Bella lives in town."]
    assert registry.calls[0]["kwargs"]["lang"] == "en"


async def test_consolidate_normalizes_string_lists_from_llm():
    payload = {"summary": "x", "topics": "festival, friendship", "facts": None}
    out = await consolidate_turns(TURNS, PROFILE, FakeRegistry(json.dumps(payload)), "en")
    assert out["topics"] == ["festival", "friendship"]
    # Empty values keep the deterministic fallback instead of being wiped.
    assert out["facts"] == ["Bella Goth took part in this conversation."]
