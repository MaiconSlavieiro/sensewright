"""Tests for the God agent background generation service."""

from __future__ import annotations

import json

from sensewright_sidecar.god.backgrounder import (
    BACKGROUND_SHAPE,
    fallback_household_background,
    fallback_sim_background,
    generate_household_background,
    generate_sim_background,
    is_stale,
)
from sensewright_sidecar.llm.base import LLMResponse

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
    assert "Write only in Português (Brasil)" in high_prompt
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


def test_fallback_sim_background_includes_kinship():
    sim = {
        **SIM,
        "lang": "en",
        "kinship": [{"relation": "mother", "target_id": 9, "name": "Candy Goth"}],
    }
    en = fallback_sim_background(sim, ["drama"], 0.5)
    assert "Family: mother: Candy Goth" in en["text"]

    pt = fallback_sim_background({**sim, "lang": "pt-BR"}, ["drama"], 0.5)
    assert "Família: mother: Candy Goth" in pt["text"]


async def test_llm_prompt_includes_native_kinship():
    registry = FakeRegistry(_llm_json())
    sim = {
        **SIM,
        "kinship": [{"relation": "father", "target_id": 9, "name": "Mortimer Goth"}],
    }

    await generate_sim_background(sim, ZEITGEIST, "", "en", registry, 0.5)

    prompt = registry.calls[0]["messages"][1]["content"]
    assert "Family (kinship): father: Mortimer Goth" in prompt


# ─── aspiration + relationship names (fix) ───────────────────────────────


def test_sim_facts_includes_aspiration_and_relationship_name():
    from sensewright_sidecar.god.backgrounder import _sim_facts

    facts = _sim_facts({
        "full_name": "Bella Goth",
        "aspiration": "Soulmate",
        "traits": ["romantic"],
        "relationships": [
            {"target_id": 2, "target_name": "Mortimer Goth", "depth": 80.0,
             "relation": "husband"},
        ],
        "kinship": [{"relation": "husband", "target_id": 2, "name": "Mortimer Goth"}],
    })
    assert "Aspiration: Soulmate" in facts
    assert "Mortimer Goth (husband)" in facts
    assert "target_id" not in facts  # never leak numeric ids


async def test_sim_prompt_requires_using_family_and_aspiration():
    registry = FakeRegistry(_llm_json())
    sim = {
        **SIM,
        "aspiration": "Soulmate",
        "relationships": [
            {"target_id": 2, "target_name": "Mortimer Goth", "depth": 80.0,
             "relation": "husband"},
        ],
    }

    await generate_sim_background(sim, ZEITGEIST, "", "en", registry, 0.5)

    system = registry.calls[0]["messages"][0]["content"]
    user = registry.calls[0]["messages"][1]["content"]
    assert "NOT describe them as lonely" in user
    assert "Aspiration: Soulmate" in user
    assert "aspiration" in system


def test_fallback_sim_background_includes_aspiration():
    result = fallback_sim_background(
        {"full_name": "Bella", "aspiration": "Soulmate", "lang": "en"}, [], 0.5
    )
    assert "Soulmate" in result["text"]


def test_native_view_merges_nested_profile_facts():
    from sensewright_sidecar.god.backgrounder import _native_view

    view = _native_view({
        "name": "Bella",
        "native": {"traits": ["romantic"], "aspiration": "Soulmate"},
    })
    assert view["aspiration"] == "Soulmate"
    assert view["traits"] == ["romantic"]
    assert view["name"] == "Bella"


# ─── native trait cleaning ────────────────────────────────────────────────


def test_clean_traits_drops_technical_and_prettifies():
    from sensewright_sidecar.god.backgrounder import clean_traits

    raw = [
        "trait_Cheerful",
        "trait_FamilyOriented",
        "trait_GenderFemale",
        "trait_GenderOptions_AttractedTo_NotMale",
        "trait_RelExpectations_OpenToChange_Yes",
        "trait_Species_Human",
        "S4CL_Main_Trait",
        "trait_WalkStyleDefault",
        "trait_youngAdult",
        "trait_SimPreference_Likes_Music_Blues",
        "trait_Umbrella_User",
        "trait_Materialistic",
        "trait_Cheerful",
    ]
    assert clean_traits(raw) == ["Cheerful", "Family Oriented", "Materialistic"]


def test_clean_traits_preserves_readable_names():
    from sensewright_sidecar.god.backgrounder import clean_traits

    assert clean_traits(["romantic", "ambitious"]) == ["romantic", "ambitious"]
    assert clean_traits(None) == []


def test_sim_facts_uses_clean_traits():
    from sensewright_sidecar.god.backgrounder import _sim_facts

    facts = _sim_facts({
        "full_name": "Bella",
        "traits": ["trait_Cheerful", "trait_GenderFemale", "trait_FamilyOriented"],
    })
    assert "Native traits: Cheerful, Family Oriented" in facts
    assert "GenderFemale" not in facts


async def test_generate_sim_background_native_traits_from_nested_profile():
    """A profile-shaped payload resolves native traits from its ``native`` block."""
    registry = FakeRegistry("Bella hides a secret.")
    profile = {
        "name": "Bella",
        "native": {"traits": ["trait_Romantic", "trait_GenderFemale"]},
    }

    result = await generate_sim_background(profile, ZEITGEIST, "", "en", registry, 0.5)

    assert result["background"]["traits"] == ["Romantic"]


# ─── truncated / invalid JSON responses ───────────────────────────────────


def test_background_from_response_salvages_truncated_json():
    """A truncated JSON answer yields the prose field, never the raw object."""
    from sensewright_sidecar.god.backgrounder import _background_from_response

    raw = '{\n  "text": "Bella hides a secret behind her polished career.'

    result = _background_from_response(raw, ["Romantic"], ["drama"], 0.5)

    assert result is not None
    assert result["text"].startswith("Bella hides a secret")
    assert '"text"' not in result["text"]


def test_background_from_response_rejects_lone_brace():
    from sensewright_sidecar.god.backgrounder import _background_from_response

    assert _background_from_response("{", ["Romantic"], [], 0.5) is None


def test_background_from_response_rejects_json_without_text():
    from sensewright_sidecar.god.backgrounder import _background_from_response

    assert _background_from_response('{"text":', [], [], 0.5) is None


async def test_generate_sim_background_falls_back_on_truncated_response():
    result = await generate_sim_background(SIM, ZEITGEIST, "", "en", FakeRegistry("{"), 0.5)

    assert result["provider"] is None
    assert result["background"]["source"] == "template"
    assert result["background"]["text"] != "{"


