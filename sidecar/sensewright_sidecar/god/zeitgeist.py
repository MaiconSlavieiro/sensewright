"""Neighborhood zeitgeist: normalization, prompt rendering and suggestions.

The zeitgeist is the first layer of meaning the God agent uses: a small set of
mood tags, the player's free text, an optional LLM rewrite and an influence
thermometer that later colors backgrounds and moods.
"""

from __future__ import annotations

import logging
import math
from typing import Any

from .. import content_i18n
from ..schemas import MOOD_TAGS, normalize_lang

logger = logging.getLogger(__name__)

DEFAULT_MOOD_INFLUENCE = 0.5

# Short English glosses used by the deterministic local template.
_TAG_PHRASES: dict[str, str] = {
    "novela": "soap-opera twists and secrets",
    "sitcom": "light comedic misunderstandings",
    "drama": "grounded emotional conflict",
    "caos": "unpredictable chaos",
    "terror": "eerie, spooky tension",
    "romance": "romantic entanglements",
    "filme_adolescente": "teen-movie coming-of-age energy",
}


def clamp01(value: Any, default: float = DEFAULT_MOOD_INFLUENCE) -> float:
    """Coerce ``value`` to a finite float clamped to ``0..1``."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(0.0, min(1.0, number))


def clean_mood_tags(tags: Any) -> list[str]:
    """Return the valid ``MOOD_TAGS`` in order, dropping invalid/duplicate ones."""
    if isinstance(tags, str):
        candidates: list[Any] = [part.strip() for part in tags.split(",")]
    elif isinstance(tags, (list, tuple)):
        candidates = list(tags)
    else:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        tag = str(candidate).strip()
        if tag in MOOD_TAGS and tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def _coerce_text(value: Any) -> str:
    return "" if value is None else str(value)


def normalize_zeitgeist(raw: dict) -> dict:
    """Coerce a raw dict into the canonical zeitgeist shape.

    Never raises: unknown tags are dropped and ``mood_influence`` is clamped to
    the ``0..1`` range.
    """
    data = raw if isinstance(raw, dict) else {}

    updated_at = data.get("updated_at")
    if (
        isinstance(updated_at, bool)
        or not isinstance(updated_at, (int, float))
        or not math.isfinite(float(updated_at))
    ):
        updated_at = None

    return {
        "mood_tags": clean_mood_tags(data.get("mood_tags")),
        "free_text": _coerce_text(data.get("free_text")),
        "rewritten_text": _coerce_text(data.get("rewritten_text")),
        "mood_influence": clamp01(data.get("mood_influence")),
        "configured": bool(data.get("configured", False)),
        "updated_at": updated_at,
    }


def influence_phrase(mood_influence: float) -> str:
    """Describe how strongly the mood should color the writing (English)."""
    value = clamp01(mood_influence)
    if value <= 0.15:
        return "neutral and realistic"
    if value <= 0.4:
        return "lightly tinted"
    if value <= 0.7:
        return "clearly colored"
    return "strongly mood-driven"


def build_local_template(mood_tags: list[str], free_text: str) -> str:
    """Build a deterministic English baseline from tags + free text (no LLM)."""
    tags = clean_mood_tags(mood_tags)
    if tags:
        phrases = ", ".join(_TAG_PHRASES[tag] for tag in tags)
        parts = [f"The neighborhood mood leans toward {phrases}."]
    else:
        parts = ["The neighborhood mood is neutral and grounded in everyday life."]

    text = _coerce_text(free_text).strip()
    if text:
        parts.append(f"Player direction: {text}.")
    return " ".join(parts)


def zeitgeist_to_prompt_block(zeitgeist: dict) -> str:
    """Render the zeitgeist as a compact English block for other prompts."""
    data = normalize_zeitgeist(zeitgeist)
    tags = ", ".join(data["mood_tags"]) or "none"
    lines = [
        "Neighborhood zeitgeist:",
        f"- Mood tags: {tags}",
        (
            f"- Mood influence: {data['mood_influence']:.2f} "
            f"({influence_phrase(data['mood_influence'])})"
        ),
    ]
    if data["free_text"]:
        lines.append(f"- Player notes: {data['free_text']}")
    if data["rewritten_text"]:
        lines.append(f"- Rewritten zeitgeist: {data['rewritten_text']}")
    return "\n".join(lines)


def _describe_census(census: dict) -> str:
    """Summarize an optional census dict for the suggestion prompt."""
    if not isinstance(census, dict):
        return "No census data."

    lines: list[str] = []
    sims = census.get("sims")
    households = census.get("households")
    if isinstance(households, (list, tuple)):
        lines.append(f"Households: {len(households)}")
    if isinstance(sims, (list, tuple)):
        lines.append(f"Sims: {len(sims)}")
        names: list[str] = []
        for sim in sims[:12]:
            if isinstance(sim, dict):
                name = _coerce_text(sim.get("full_name")).strip()
                if name:
                    names.append(name)
        if names:
            lines.append("Notable sims: " + ", ".join(names))
    return "\n".join(lines) if lines else "No census data."


def _build_suggest_messages(
    census: dict, mood_tags: list[str], free_text: str, lang: str
) -> list[dict[str, str]]:
    system = (
        "You are the narrative director for a Sims 4 save. You write the "
        "neighborhood zeitgeist: a short mood guide that colors all future "
        "storytelling."
    )
    user = (
        f"Census:\n{_describe_census(census)}\n\n"
        f"Selected mood tags: {', '.join(mood_tags) or 'none'}\n"
        f"Player free text: {_coerce_text(free_text).strip() or 'none'}\n\n"
        "Instructions:\n"
        "- Rewrite the zeitgeist into 2-4 evocative sentences that fit the mood "
        "tags and the census.\n"
        f"- Write only in {content_i18n.language_name(lang)}.\n"
        "- Do not contradict the census facts (names, households, traits).\n"
        "- Output only the rewritten text, with no headings, quotes or JSON."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def suggest_zeitgeist(
    census: dict,
    mood_tags: list[str],
    free_text: str,
    lang: str,
    registry: Any,
) -> dict:
    """Suggest a rewritten zeitgeist text, falling back to a local template.

    Returns ``{"suggested_text": str, "mood_tags": list[str], "provider": str|None}``.
    If ``registry`` is ``None`` or the LLM call fails, the deterministic local
    template is returned with ``provider=None``. Never raises.
    """
    tags = clean_mood_tags(mood_tags)
    target_lang = normalize_lang(lang)
    fallback = build_local_template(tags, free_text)

    if registry is None:
        return {"suggested_text": fallback, "mood_tags": tags, "provider": None}

    try:
        messages = _build_suggest_messages(census, tags, free_text, target_lang)
        response = await registry.complete(
            messages,
            lang=target_lang,
            temperature=0.7,
            max_tokens=400,
            purpose="summary",
        )
        text = _coerce_text(getattr(response, "text", "")).strip()
        if not text:
            return {"suggested_text": fallback, "mood_tags": tags, "provider": None}
        return {
            "suggested_text": text,
            "mood_tags": tags,
            "provider": getattr(response, "provider", None),
        }
    except Exception as exc:
        logger.warning("zeitgeist suggestion failed: %s", exc)
        return {"suggested_text": fallback, "mood_tags": tags, "provider": None}
