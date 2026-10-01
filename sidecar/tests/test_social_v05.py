"""v0.5 R4/R5: interaction+object templates, sleep gate and dialogue provenance."""

from __future__ import annotations

import pytest

from sensewright_sidecar.agent.social import (
    Dialogue,
    SocialLayer,
    _clean_interaction_label,
    _dialogue_lines,
    _extract_json_object,
    _normalize_speakers,
    classify_interaction,
    render_dialogue,
    template_dialogue,
)
from sensewright_sidecar.llm.base import LLMResponse


def test_classify_interaction_covers_v05_categories():
    assert classify_interaction("social_GetToKnow")[0] == "intro"
    assert classify_interaction("social_TellJoke")[0] == "funny"
    assert classify_interaction("social_Flirt")[0] == "flirty"
    assert classify_interaction("social_Woohoo")[0] == "intimate"
    assert classify_interaction("social_Kiss")[0] == "intimate"
    assert classify_interaction("social_Hug")[0] == "affectionate"
    assert classify_interaction("social_Insult")[0] == "mean"
    assert classify_interaction("social_Argue")[0] == "tense"
    assert classify_interaction("social_Chat")[0] == "friendly"
    assert classify_interaction("something_unknown")[0] == "casual"


def test_intimate_template_matches_the_object():
    dlg = template_dialogue(
        {}, {}, a_id=1, b_id=2, interaction="social_Woohoo", object_label="Bed"
    )
    joined = " ".join(line["text"].lower() for line in dlg.lines)
    assert "bed" in joined
    assert dlg.topic == "an intimate moment"
    assert all(line["tone"] == "flirty" for line in dlg.lines)

    # A non-intimate interaction ignores the object.
    dlg = template_dialogue(
        {}, {}, a_id=1, b_id=2, interaction="social_Chat", object_label="Bed"
    )
    joined = " ".join(line["text"].lower() for line in dlg.lines)
    assert "bed" not in joined


def test_localized_label_classifies_specific_interaction():
    # A generic raw base (sim_Chat) must not override the specific localized label.
    assert classify_interaction("sim_Chat", "Contar piada")[0] == "funny"
    assert classify_interaction("sim_Chat", "Contar uma piada engraçada")[0] == "funny"
    assert classify_interaction("sim_Chat", "Flertar")[0] == "flirty"
    assert classify_interaction("sim_Chat", "Bater papo")[0] == "friendly"
    assert classify_interaction("sim_Chat", "Brigar")[0] == "tense"
    # The raw tuning name is still used when the label is generic/absent.
    assert classify_interaction("social_TellJoke", "")[0] == "funny"


@pytest.mark.asyncio
async def test_generic_raw_with_localized_label_renders_funny_template():
    layer = SocialLayer()
    a = {
        "sim_id": 1,
        "sleeping": False,
        "autonomy": "full",
        "current_interaction": "sim_Chat",
        "current_interaction_text": "Contar piada",
    }
    b = {"sim_id": 2, "sleeping": False, "autonomy": "full"}
    dlg = await layer._dialogue_for_pair(
        a, b, player_id="p", save_id="s", lang="pt-BR", forge=None
    )
    assert dlg is not None
    assert dlg.source == "template"
    assert dlg.topic == "joking around"
    assert all(line["tone"] == "funny" for line in dlg.lines)


def test_extract_json_object_tolerates_prose_and_thoughts():
    assert _extract_json_object('{"topic": "x", "lines": []}') == {"topic": "x", "lines": []}
    assert _extract_json_object('Sure!\n{"topic": "x"} extra') == {"topic": "x"}
    assert _extract_json_object('[thought]secret[/thought] ```json\n{"topic": "x"}\n```') == {
        "topic": "x"
    }
    assert _extract_json_object("no json here") is None
    assert _extract_json_object("") is None


def test_interaction_label_guard_rejects_numeric_and_hash():
    assert _clean_interaction_label("Flertar") == "Flertar"
    assert _clean_interaction_label("12345") == ""
    assert _clean_interaction_label("0xDEADBEEF") == ""
    assert _clean_interaction_label("   ") == ""


@pytest.mark.asyncio
async def test_sleeping_pair_is_never_rendered():
    layer = SocialLayer()
    a = {"sim_id": 1, "sleeping": True, "autonomy": "full"}
    b = {"sim_id": 2, "sleeping": False, "autonomy": "full"}
    dlg = await layer._dialogue_for_pair(
        a, b, player_id="p", save_id="s", lang="en", forge=None
    )
    assert dlg is None


def test_dialogue_lines_rotate_with_the_seed():
    firsts = {_dialogue_lines("en", "casual", seed=f"1-2-{turn}")[0] for turn in range(4)}
    # A category with 4 variants must not always render the same leading line.
    assert len(firsts) >= 2


def test_normalize_speakers_accepts_names_and_slots():
    lines = [
        {"speaker": "Eric Lewis", "text": "a", "tone": "funny"},
        {"speaker": "Olivia Kim-Lewis", "text": "b", "tone": "funny"},
    ]
    out = _normalize_speakers(lines, "Eric Lewis", "Olivia Kim-Lewis")
    assert [line["speaker"] for line in out] == ["a", "b"]

    # Explicit slots win; a duplicate slot is reassigned.
    out = _normalize_speakers(
        [{"speaker": "b", "text": "x"}, {"speaker": "b", "text": "y"}], "A", "B"
    )
    assert [line["speaker"] for line in out] == ["b", "a"]

    # Unknown labels fall back to alternating order.
    out = _normalize_speakers([{"speaker": "?", "text": "x"}], "A", "B")
    assert [line["speaker"] for line in out] == ["a"]


class _NameRegistry:
    """Registry that returns dialogue whose speakers are Sim names."""

    def __init__(self, text: str):
        self._text = text

    async def complete(self, messages, **kwargs):
        return LLMResponse(text=self._text, provider="fake", model="m", raw={})


@pytest.mark.asyncio
async def test_render_dialogue_maps_name_speakers_to_slots():
    text = (
        '{"topic": "piadas", "lines": ['
        '{"speaker": "Eric Lewis", "text": "Sabe a piada do pao?", "tone": "funny"},'
        '{"speaker": "Olivia Kim-Lewis", "text": "Nao, pai!", "tone": "funny"}]}'
    )
    dlg = await render_dialogue(
        {}, {}, None, _NameRegistry(text), "pt-BR", 1, 2,
        name_a="Eric Lewis", name_b="Olivia Kim-Lewis",
    )
    assert dlg.source == "llm"
    assert [line["speaker"] for line in dlg.lines] == ["a", "b"]


def test_dialogue_provenance_is_serialized():
    dlg = Dialogue(
        a=1,
        b=2,
        lines=[{"speaker": "a", "text": "hi", "tone": "friendly"}],
        topic="x",
        source="llm",
        model="flash-free",
        provider="opencode",
        object_label="Bed",
        interaction="Flertar",
    )
    data = dlg.to_dict()
    assert data["source"] == "llm"
    assert data["model"] == "flash-free"
    assert data["provider"] == "opencode"
    assert data["object"] == "Bed"
    assert data["interaction"] == "Flertar"
