"""Tests for the God agent background generation service."""

from __future__ import annotations

import json

from sims_sense_sidecar.god.backgrounder import (
    BACKGROUND_SHAPE,
    fallback_household_background,
    fallback_sim_background,
    generate_household_background,
    generate_sim_background,
    is_stale,
)
from sims_sense_sidecar.llm.base import LLMResponse

SIM = {
    "sim_id": 1,
    "full_name": "Bella Goth",
    "age": "adult",
    "career": "Business",
    "traits": ["romantic", "ambitious"],
    "skills": {"charisma": 4},
    "relationships": [{"name": "Mortimer Goth", "relation": "spouse"}],
}
ZEITGEIST = {"mood_tags": ["drama", "romance"], "mood_influence": 0.5}


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
            "text": "Bella Goth hides a secret behind her polished career.",
            "summary": "Bella hides a secret.",
            "traits": ["romantic", "ambitious"],
        }
    )


def test_background_shape_keys():
    expected = {
        "text",
        "summary",
        "traits",
        "source",
        "mood_tags",
        "mood_influence",
        "generated_at",
        "stale",
    }
    assert set(BACKGROUND_SHAPE) == expected


async def test_generate_sim_background_uses_llm():
    registry = FakeRegistry(_llm_json())

    result = await generate_sim_background(SIM, ZEITGEIST, "add tension", "en", registry, 0.7)

    background = result["background"]
    assert result["provider"] == "fake"
    assert background["source"] == "llm"
    assert background["text"].startswith("Bella Goth hides a secret")
    assert background["traits"] == ["romantic", "ambitious"]
    assert background["mood_tags"] == ["drama", "romance"]
    assert set(background) == set(BACKGROUND_SHAPE)


async def test_generate_sim_background_falls_back_on_error():
    result = await generate_sim_background(SIM, ZEITGEIST, "", "en", FailingRegistry(), 0.5)

    background = result["background"]
    assert result["provider"] is None
    assert background["source"] == "template"
    assert "Bella Goth" in background["text"]
    assert set(background) == set(BACKGROUND_SHAPE)


async def test_generate_sim_background_without_registry():
    result = await generate_sim_background(SIM, ZEITGEIST, "", "pt-BR", None, 0.5)

    assert result["provider"] is None
    assert result["background"]["source"] == "template"


async def test_generate_sim_background_injects_mood_influence():
    low = FakeRegistry("ok")
    high = FakeRegistry("ok")

    await generate_sim_background(SIM, ZEITGEIST, "", "en", low, 0.0)
    await generate_sim_background(SIM, ZEITGEIST, "", "pt-BR", high, 1.0)

    low_prompt = low.calls[0]["messages"][-1]["content"]
    high_prompt = high.calls[0]["messages"][-1]["content"]
    assert "Mood influence 0.00/1.00" in low_prompt
    assert "Mood influence 1.00/1.00" in high_prompt
    assert "Write only in English" in low_prompt
    assert "Write only in Brazilian Portuguese" in high_prompt
    assert "Native traits: romantic, ambitious" in low_prompt


async def test_generate_household_background_uses_llm():
    registry = FakeRegistry(_llm_json())
    household = {"household_id": 1, "name": "Goth", "members": ["Bella", "Mortimer"], "funds": 5000}

    result = await generate_household_background(household, ZEITGEIST, "", "en", registry, 0.5)

    assert result["provider"] == "fake"
    assert result["background"]["source"] == "llm"
    assert set(result["background"]) == set(BACKGROUND_SHAPE)


async def test_generate_household_background_falls_back_on_error():
    household = {"household_id": 1, "name": "Goth", "members": ["Bella", "Mortimer"]}

    result = await generate_household_background(household, ZEITGEIST, "", "en", FailingRegistry(), 0.5)

    assert result["provider"] is None
    assert result["background"]["source"] == "template"
    assert "Goth" in result["background"]["text"]


def test_fallback_templates_differ_between_en_and_pt_br():
    en = fallback_sim_background({**SIM, "lang": "en"}, ["drama"], 0.5)
    pt = fallback_sim_background({**SIM, "lang": "pt-BR"}, ["drama"], 0.5)

    assert en["text"] != pt["text"]
    assert "Native traits" in en["text"]
    assert "Traços nativos" in pt["text"]


def test_fallback_household_templates_differ_between_en_and_pt_br():
    household = {"name": "Goth", "members": ["Bella", "Mortimer"], "funds": 1000}
    en = fallback_household_background({**household, "lang": "en"}, ["terror"], 0.8)
    pt = fallback_household_background({**household, "lang": "pt-BR"}, ["terror"], 0.8)

    assert en["text"] != pt["text"]
    assert en["mood_tags"] == ["terror"]
    assert set(en) == set(BACKGROUND_SHAPE)


def test_is_stale_logic():
    background = fallback_sim_background({"lang": "en", "full_name": "A"}, ["drama"], 0.5)

    assert is_stale(None, 0.5, ["drama"]) is True
    assert is_stale({}, 0.5, ["drama"]) is True
    assert is_stale(background, 0.5, ["drama"]) is False
    assert is_stale(background, 0.9, ["drama"]) is True
    assert is_stale(background, 0.5, ["romance"]) is True
    assert is_stale(background, 0.5, ["drama", "bogus"]) is False

    flagged = dict(background)
    flagged["stale"] = True
    assert is_stale(flagged, 0.5, ["drama"]) is True

    missing_influence = dict(background)
    del missing_influence["mood_influence"]
    assert is_stale(missing_influence, 0.5, ["drama"]) is True
