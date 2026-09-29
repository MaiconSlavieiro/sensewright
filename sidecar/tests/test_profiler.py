"""Tests for the agent profiler service."""

from __future__ import annotations

import json

from sensewright_sidecar.agent.profiler import (
    PROFILE_SHAPE,
    fallback_profile,
    generate_profile,
    normalize_profile,
)
from sensewright_sidecar.llm.base import LLMResponse

NATIVE = {
    "full_name": "Bella Goth",
    "age": "adult",
    "career": "Business",
    "traits": ["romantic", "ambitious"],
    "skills": {"charisma": 4},
}


class FakeRegistry:
    """Registry stub returning a canned LLM response."""

    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    async def complete(self, messages, **kwargs) -> LLMResponse:
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return LLMResponse(text=self.text, provider="fake", model="m", raw={})


class FailingRegistry:
    """Registry stub that always raises."""

    async def complete(self, messages, **kwargs) -> LLMResponse:
        raise RuntimeError("provider down")


def _llm_json() -> str:
    return json.dumps(
        {
            "name": "Bella Goth",
            "backstory": "Bella Goth hides a secret behind her polished career. She navigates high society with charm.",
            "personality": "Calculating yet warm, she plays the long game.",
            "speech_style": "Eloquent with a hint of mystery.",
            "goals": ["Uncover the town's mysteries", "Secure her family's legacy"],
            "secrets": ["Knows the truth about the missing sims"],
            "quirks": ["Collects vintage postcards", "Whispers to plants"],
            "traits": ["romantic", "ambitious"],
        }
    )


def test_profile_shape_keys():
    expected = {
        "name",
        "backstory",
        "personality",
        "speech_style",
        "goals",
        "secrets",
        "quirks",
        "traits",
        "source",
        "generated_at",
    }
    assert set(PROFILE_SHAPE) == expected


async def test_generate_profile_uses_llm():
    registry = FakeRegistry(_llm_json())

    result = await generate_profile("A mysterious sim with a hidden past.", "en", registry, hints="add tension", native=NATIVE)

    profile = result["profile"]
    assert result["provider"] == "fake"
    assert profile["source"] == "llm"
    assert profile["name"] == "Bella Goth"
    assert "secret" in profile["backstory"].lower()
    assert profile["traits"] == ["romantic", "ambitious"]
    assert isinstance(profile["goals"], list) and len(profile["goals"]) >= 1
    assert set(profile) == set(PROFILE_SHAPE)


async def test_generate_profile_falls_back_on_error():
    result = await generate_profile("A mysterious sim.", "en", FailingRegistry(), native=NATIVE)

    profile = result["profile"]
    assert result["provider"] is None
    assert profile["source"] == "template"
    assert "Bella Goth" in profile["name"]
    assert "romantic" in profile["traits"]
    assert set(profile) == set(PROFILE_SHAPE)


async def test_generate_profile_without_registry():
    result = await generate_profile("A mysterious sim.", "pt-BR", None, native=NATIVE)

    assert result["provider"] is None
    assert result["profile"]["source"] == "template"


def test_fallback_templates_differ_between_en_and_pt_br():
    en = fallback_profile("A mysterious sim.", "en", NATIVE)
    pt = fallback_profile("A mysterious sim.", "pt-BR", NATIVE)

    assert en["text"] != pt["text"] if "text" in en else en["backstory"] != pt["backstory"]
    assert "Seed" in en["backstory"]
    assert "Semente" in pt["backstory"]
    assert "Traits" in en["backstory"]
    assert "Traços" in pt["backstory"]
    assert en["name"] == "Bella Goth"
    assert pt["name"] == "Bella Goth"
    assert en["traits"] == ["romantic", "ambitious"]
    assert pt["traits"] == ["romantic", "ambitious"]


def test_normalize_profile_coerces_partial_messy_dict():
    messy = {
        "name": "  Test Sim  ",
        "backstory": "  A backstory.  ",
        "personality": 123,
        "speech_style": None,
        "goals": "goal one, goal two, ",
        "secrets": ["secret one", "", "secret two"],
        "quirks": "quirk one, quirk two",
        "traits": ["trait1", "trait2"],
        "source": "llm",
        "generated_at": "not-a-float",
        "extra_field": "should be ignored",
    }

    normalized = normalize_profile(messy)

    assert normalized["name"] == "Test Sim"
    assert normalized["backstory"] == "A backstory."
    assert normalized["personality"] == "123"
    assert normalized["speech_style"] == ""
    assert normalized["goals"] == ["goal one", "goal two"]
    assert normalized["secrets"] == ["secret one", "secret two"]
    assert normalized["quirks"] == ["quirk one", "quirk two"]
    assert normalized["traits"] == ["trait1", "trait2"]
    assert normalized["source"] == "llm"
    assert isinstance(normalized["generated_at"], float)
    assert "extra_field" not in normalized
    assert set(normalized) == set(PROFILE_SHAPE)


def test_normalize_profile_handles_empty_input():
    normalized = normalize_profile({})

    assert normalized["name"] == ""
    assert normalized["backstory"] == ""
    assert normalized["personality"] == ""
    assert normalized["speech_style"] == ""
    assert normalized["goals"] == []
    assert normalized["secrets"] == []
    assert normalized["quirks"] == []
    assert normalized["traits"] == []
    assert normalized["source"] == "template"
    assert isinstance(normalized["generated_at"], float)
    assert set(normalized) == set(PROFILE_SHAPE)