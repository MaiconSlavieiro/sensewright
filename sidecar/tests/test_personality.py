"""Tests for the living personality module (P1)."""

from __future__ import annotations

import json

import pytest

from sensewright_sidecar.agent.personality import (
    absorb,
    absorb_events,
    decay_psyche,
    format_life,
    merge_block,
    normalize_psyche,
    salience,
    should_absorb,
)
from sensewright_sidecar.config import PersonalityConfig
from sensewright_sidecar.llm.base import LLMResponse

NOW = 10_000_000_000.0
DAY = 86400.0


class FakeRegistry:
    """Registry returning a canned absorption JSON payload."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls: list[dict] = []

    async def complete(self, messages, **kwargs) -> LLMResponse:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return LLMResponse(text=json.dumps(self.payload), provider="fake", model="m", raw={})


class FailingRegistry:
    """Registry that always raises."""

    async def complete(self, messages, **kwargs) -> LLMResponse:
        raise RuntimeError("provider down")


def _negative_event(name: str, event_id: str = "e1") -> dict:
    return {
        "id": event_id,
        "type": "buff",
        "importance": 2.0,
        "content": {"target": name, "buff_name": "death of a loved one"},
    }


# ─── salience ─────────────────────────────────────────────────────────
def test_salience_neutral_default():
    assert salience({"importance": 1.0}) == 1.0
    assert salience({}) == 1.0


def test_salience_multiplies_importance_and_emotion():
    anger = salience({"importance": 1.0, "content": {"emotion": "anger"}})
    death = salience({"importance": 1.0, "content": {"emotion": "death"}})
    scaled = salience({"importance": 2.0, "content": {"emotion": "anger"}})

    assert death > anger > 1.0
    assert scaled == pytest.approx(anger * 2.0)


def test_salience_reads_buff_names_and_takeaways():
    assert salience({"importance": 1.0, "content": {"buff_name": "sudden fear"}}) > 1.0
    assert salience({"importance": 1.0, "content": {"emotional_takeaways": ["loss"]}}) > 1.0
    assert salience({"importance": 1.0, "content": {"emotion": "love"}}) > 1.0


def test_salience_invalid_importance_is_neutral():
    assert salience({"importance": "not-a-number"}) == 1.0


def test_should_absorb_threshold():
    assert should_absorb(_negative_event("Bella"), 1.5) is True
    assert should_absorb({"importance": 1.0}, 1.5) is False
    assert should_absorb({"importance": 1.0}, "bad") is True


# ─── normalize_psyche ─────────────────────────────────────────────────
def test_normalize_psyche_empty_profile():
    out = normalize_psyche({})
    assert out["psyche"] == {"traumas": [], "baggage": [], "aversions": [], "attachments": []}
    assert out["life_story"] == ""


def test_normalize_psyche_malformed():
    profile = {
        "psyche": {
            "traumas": "not-a-list",
            "baggage": [{"belief": 123}, "junk", {}],
            "aversions": "dogs, spiders",
            "attachments": None,
        },
        "life_story": ["line 1", "line 2"],
    }
    out = normalize_psyche(profile)
    psyche = out["psyche"]
    assert psyche["traumas"] == []
    assert len(psyche["baggage"]) == 1
    assert psyche["baggage"][0]["belief"] == "123"
    assert 0.0 <= psyche["baggage"][0]["intensity"] <= 1.0
    assert psyche["aversions"] == ["dogs", "spiders"]
    assert psyche["attachments"] == []
    assert out["life_story"] == "line 1\nline 2"


def test_normalize_psyche_handles_non_dict():
    out = normalize_psyche(None)  # type: ignore[arg-type]
    assert out["psyche"]["traumas"] == []


def test_normalize_psyche_does_not_mutate_input():
    profile = {
        "psyche": {"traumas": [{"trigger": "x", "belief": "y", "intensity": 0.5}]},
        "life_story": "story",
    }
    before = json.dumps(profile, sort_keys=True)
    normalize_psyche(profile)
    assert json.dumps(profile, sort_keys=True) == before


# ─── merge_block ──────────────────────────────────────────────────────
def test_merge_block_reinforces_and_caps():
    blocks = [
        {"trigger": "a", "belief": "old", "intensity": 0.4},
        {"trigger": "b", "belief": "b", "intensity": 0.5},
    ]
    merged = merge_block(blocks, {"trigger": "a", "belief": "new", "intensity": 0.9}, max_items=5, key="trigger")

    assert len(merged) == 2
    reinforced = next(b for b in merged if b["trigger"] == "a")
    assert reinforced["intensity"] == 0.9
    assert reinforced["belief"] == "new"
    assert merged[0]["intensity"] >= merged[-1]["intensity"]

    capped = merge_block(merged, {"trigger": "c", "intensity": 0.1}, max_items=2, key="trigger")
    assert len(capped) == 2
    assert "c" not in {b["trigger"] for b in capped}


# ─── decay ────────────────────────────────────────────────────────────
def _trauma_profile(intensity: float, reference: float) -> dict:
    return {
        "psyche": {
            "traumas": [
                {
                    "trigger": "the fire",
                    "belief": "brace yourself",
                    "intensity": intensity,
                    "first_seen": reference,
                    "last_reinforced": reference,
                    "source_event_ids": [],
                }
            ],
            "baggage": [],
            "aversions": [],
            "attachments": [],
        }
    }


def test_reinforcement_prevents_decay():
    profile = _trauma_profile(0.9, NOW - 0.5 * DAY)
    out = decay_psyche(profile, NOW, "slow")
    assert out["psyche"]["traumas"][0]["intensity"] == 0.9


def test_non_reinforced_decays_and_drops_at_floor():
    decayed = decay_psyche(_trauma_profile(0.9, NOW - 20 * DAY), NOW, "slow")
    remaining = decayed["psyche"]["traumas"]
    assert len(remaining) == 1
    assert 0.0 < remaining[0]["intensity"] < 0.9

    dropped = decay_psyche(_trauma_profile(0.06, NOW - 300 * DAY), NOW, "slow")
    assert dropped["psyche"]["traumas"] == []


def test_decay_caps_sizes():
    profile = {
        "psyche": {
            "traumas": [
                {"trigger": f"t{i}", "belief": "b", "intensity": 0.05 + i * 0.1, "last_reinforced": NOW}
                for i in range(6)
            ],
            "baggage": [],
            "aversions": [],
            "attachments": [],
        }
    }
    out = decay_psyche(profile, NOW, "slow", max_traumas=3)
    assert len(out["psyche"]["traumas"]) == 3


# ─── deterministic absorption ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_deterministic_absorption_creates_trauma_and_life_story():
    events = [_negative_event("Bella", "e1")]
    out = await absorb_events({}, events, PersonalityConfig(salience_threshold=1.0))

    assert out["psyche_source"] == "template"
    assert len(out["psyche"]["traumas"]) == 1
    trauma = out["psyche"]["traumas"][0]
    assert trauma["trigger"] == "Bella"
    assert trauma["source_event_ids"] == ["e1"]
    assert out["life_story"]
    assert "Bella" in out["life_story"]


@pytest.mark.asyncio
async def test_absorption_caps_traumas_by_config():
    events = [
        _negative_event("Alice", "e1"),
        _negative_event("Bob", "e2"),
        _negative_event("Carol", "e3"),
    ]
    config = PersonalityConfig(salience_threshold=1.0, max_traumas=2)
    out = await absorb_events({}, events, config)
    assert len(out["psyche"]["traumas"]) == 2


@pytest.mark.asyncio
async def test_absorption_ignores_below_threshold_events():
    events = [{"id": "e1", "importance": 1.0, "content": {"message": "said hi"}}]
    out = await absorb_events({}, events, PersonalityConfig(salience_threshold=1.5))
    assert out["psyche"]["traumas"] == []
    assert out["life_story"] == ""


@pytest.mark.asyncio
async def test_absorption_disabled_is_noop():
    events = [_negative_event("Bella", "e1")]
    out = await absorb_events({}, events, PersonalityConfig(absorption_enabled=False))
    assert out["psyche"]["traumas"] == []
    assert out["life_story"] == ""


@pytest.mark.asyncio
async def test_absorb_events_falls_back_on_registry_error():
    events = [_negative_event("Bella", "e1")]
    config = PersonalityConfig(salience_threshold=1.0)
    out = await absorb_events({}, events, config, registry=FailingRegistry())

    assert out["psyche_source"] == "template"
    assert len(out["psyche"]["traumas"]) == 1


@pytest.mark.asyncio
async def test_absorb_events_uses_llm_and_merges_drift():
    profile = {"name": "Eve", "personality": {"openness": 0.5}}
    events = [_negative_event("Bella", "e1")]
    payload = {
        "life_story_line": "I watched the fire take everything.",
        "traumas": [{"trigger": "the fire", "belief": "avoid open flames", "intensity": 0.7}],
        "baggage": [],
        "aversions": ["fire"],
        "attachments": ["Bella"],
        "personality_drift": {"openness": 0.05},
    }
    config = PersonalityConfig(salience_threshold=1.0)
    out = await absorb_events(profile, events, config, registry=FakeRegistry(payload))

    assert out["psyche_source"] == "llm"
    assert out["life_story"] == "I watched the fire take everything."
    assert out["psyche"]["traumas"][0]["source_event_ids"] == ["e1"]
    assert out["psyche"]["aversions"] == ["fire"]
    assert out["psyche"]["attachments"] == ["Bella"]
    assert out["personality"]["openness"] == pytest.approx(0.55)


@pytest.mark.asyncio
async def test_personality_drift_skipped_when_personality_is_string():
    profile = {"name": "Eve", "personality": "friendly"}
    events = [_negative_event("Bella", "e1")]
    payload = {
        "life_story_line": "Something changed.",
        "traumas": [],
        "baggage": [],
        "aversions": [],
        "attachments": [],
        "personality_drift": {"openness": 0.1},
    }
    config = PersonalityConfig(salience_threshold=1.0)
    out = await absorb_events(profile, events, config, registry=FakeRegistry(payload))
    assert out["personality"] == "friendly"


@pytest.mark.asyncio
async def test_life_story_is_capped():
    profile = {"life_story": "\n".join(f"old line {i}" for i in range(40))}
    events = [_negative_event("Bella", "e1")]
    out = await absorb_events(profile, events, PersonalityConfig(salience_threshold=1.0))
    lines = [line for line in out["life_story"].splitlines() if line.strip()]
    assert len(lines) <= 20
    assert lines[-1].startswith("You lived through")


def test_absorb_single_event_references_event_id():
    event = {"id": "abc", "importance": 2.0, "content": {"target": "Bob", "buff_name": "betrayal"}}
    out = absorb({}, event)
    assert out["psyche"]["traumas"][0]["source_event_ids"] == ["abc"]


def test_absorb_single_event_below_threshold_is_noop():
    out = absorb({}, {"importance": 1.0, "content": {"message": "hi"}})
    assert out["psyche"]["traumas"] == []


# ─── format_life ──────────────────────────────────────────────────────
def test_format_life_contains_shaping_lines():
    profile = {
        "psyche": {
            "traumas": [
                {"trigger": "the fire", "belief": "avoid open flames", "intensity": 0.8},
            ],
            "baggage": [{"belief": "trust no one", "source": "the betrayal", "intensity": 0.6}],
            "aversions": ["dogs"],
            "attachments": ["Alice"],
        },
        "life_story": "I moved away.",
    }
    text = format_life(profile)
    assert "Because of what happened with the fire, you now avoid open flames." in text
    assert "You carry unresolved feelings about the betrayal: trust no one." in text
    assert "You avoid dogs." in text
    assert "You are attached to Alice." in text
    assert "Your life story: I moved away." in text


def test_format_life_empty_profile_returns_empty():
    assert format_life({}) == ""
    assert format_life(None) == ""  # type: ignore[arg-type]
