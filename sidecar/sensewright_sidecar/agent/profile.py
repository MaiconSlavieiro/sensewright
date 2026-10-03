"""Sim profile shape and normalization (F02 / REQ-PROF-01).

The canonical ``PROFILE_SHAPE`` separates immutable essence (``core_personality``)
from the current phase (``current_demeanor``). ``normalize_profile`` guarantees
every profile is valid, filling missing keys with safe defaults. Native data
(traits/likes/dislikes/age_stage/career) is ground truth and never overwritten
by the LLM (REQ-PROF-02).
"""
from __future__ import annotations

from typing import Any, Dict, List

from ..constants import LIFE_STORY_MAX_CHARS, LIFE_STORY_MAX_LINES

#: Canonical profile keys.
PROFILE_SHAPE_KEYS = (
    "name", "species", "age_stage", "backstory",
    "core_personality", "current_demeanor", "speech_style",
    "goals", "ambition", "secrets", "quirks", "traits", "likes", "dislikes",
    "life_story", "source", "generated_at_tick",
)

PROFILE_SOURCE_TEMPLATE = "template"
PROFILE_SOURCE_LLM = "llm"


def _list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    return []


def enforce_life_story(lines: Any) -> List[str]:
    """Clamp a life-story to the configured line/char budget (REQ-PSY-03).

    Keeps the most recent lines (the tail) and drops oldest lines until both
    the line cap and the character cap are respected.
    """
    if not isinstance(lines, list):
        return []
    cleaned = [str(line) for line in lines if isinstance(line, str) and line]
    if len(cleaned) > LIFE_STORY_MAX_LINES:
        cleaned = cleaned[-LIFE_STORY_MAX_LINES:]
    while cleaned and sum(len(line) for line in cleaned) > LIFE_STORY_MAX_CHARS:
        cleaned.pop(0)
    return cleaned


def normalize_profile(
    raw: Any,
    name: str = "",
    species: str = "HUMAN",
    age_stage: str = "YOUNGADULT",
    traits: Any = None,
    likes: Any = None,
    dislikes: Any = None,
    source: str = PROFILE_SOURCE_TEMPLATE,
    generated_at_tick: int = 0,
) -> Dict[str, Any]:
    """Return a valid profile dict, coercing ``raw`` and applying ground truth.

    Native ``traits``/``likes``/``dislikes``/``species``/``age_stage`` are taken
    from the explicit arguments (the game census) when provided, so the LLM can
    never contradict the ground truth.
    """
    if not isinstance(raw, dict):
        raw = {}

    profile: Dict[str, Any] = {
        "name": raw.get("name") or name,
        "species": species or raw.get("species", "HUMAN"),
        "age_stage": age_stage or raw.get("age_stage", "YOUNGADULT"),
        "backstory": raw.get("backstory", ""),
        "core_personality": raw.get("core_personality", ""),
        "current_demeanor": raw.get("current_demeanor", ""),
        "speech_style": raw.get("speech_style", ""),
        "goals": _list(raw.get("goals")),
        "ambition": raw.get("ambition", ""),
        "secrets": _list(raw.get("secrets")),
        "quirks": _list(raw.get("quirks")),
        "traits": _list(traits) if traits is not None else _list(raw.get("traits")),
        "likes": _list(likes) if likes is not None else _list(raw.get("likes")),
        "dislikes": _list(dislikes) if dislikes is not None else _list(raw.get("dislikes")),
        "life_story": enforce_life_story(raw.get("life_story")),
        "source": source,
        "generated_at_tick": int(generated_at_tick),
    }
    return profile


def template_profile(
    name: str,
    species: str = "HUMAN",
    age_stage: str = "YOUNGADULT",
    traits: Any = None,
    likes: Any = None,
    dislikes: Any = None,
    generated_at_tick: int = 0,
) -> Dict[str, Any]:
    """Build a deterministic 0-key fallback profile (``source="template"``)."""
    return normalize_profile(
        {},
        name=name, species=species, age_stage=age_stage,
        traits=traits, likes=likes, dislikes=dislikes,
        source=PROFILE_SOURCE_TEMPLATE, generated_at_tick=generated_at_tick,
    )
