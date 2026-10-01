"""Tests for v0.2 M1 dialogue consolidation."""

from __future__ import annotations

import json

from sensewright_sidecar.llm.base import LLMResponse
from sensewright_sidecar.memory.consolidation import (
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


# ─── all native event types reach the consolidation (fix) ────────────────


def test_messages_render_every_event_type():
    from sensewright_sidecar.memory.consolidation import _messages

    events = [
        {"type": "thought", "content": {"text": "wants a coffee"}},
        {"type": "social", "content": {"topic": "gardening", "with": "Mortimer",
                                       "lines": [{"text": "The roses bloomed!"}]}},
        {"type": "buff_add", "content": {"buff": "Happy"}},
        {"type": "relationship_change", "content": {"target": "Mortimer", "depth": 12.0}},
        {"type": "skill_level_up", "content": {"skill": "Gardening"}},
        {"type": "career_change", "content": {"career": "Chef"}},
        {"type": "trait_change", "content": {"trait": "Creative"}},
        {"type": "sim_death", "content": {"sim_id": 9}},
        {"type": "snapshot", "content": {"mood": "fine"}},  # skipped
    ]
    lines = _messages(events, "en")
    joined = " | ".join(lines)
    assert "wants a coffee" in joined
    assert "gardening" in joined and "The roses bloomed!" in joined
    assert "felt Happy" in joined
    assert "relationship with Mortimer" in joined
    assert "improved Gardening" in joined
    assert "career changed to Chef" in joined
    assert "trait changed: Creative" in joined
    assert "passed away" in joined
    assert "snapshot" not in joined and "fine" not in joined


def test_messages_prefer_player_choice_and_consequence():
    from sensewright_sidecar.memory.consolidation import _messages

    events = [
        {"type": "player_choice", "content": {"choice": "Defended the stranger",
                                              "consequence": "gained a friend"}},
    ]
    lines = _messages(events, "en")
    assert lines == ["Defended the stranger"]


def test_deterministic_consolidation_summarizes_day_events():
    events = [
        {"type": "thought", "content": {"text": "eager to start the day"}},
        {"type": "buff_add", "content": {"buff": "Energized"}},
        {"type": "social", "content": {"topic": "the festival", "with": "Mortimer",
                                       "lines": [{"text": "See you at the festival!"}]}},
    ]
    result = deterministic_consolidation(events, PROFILE, "en")
    assert "festival" in result["summary"].lower()
