"""Generative-Agents style evolution for Sim profiles.

Compresses recent events into a reflection, drifts the personality description,
and optionally proposes a trait swap. All public functions degrade gracefully
to deterministic templates when no LLM provider is available.
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any

from .. import content_i18n
from ..schemas import normalize_lang

logger = logging.getLogger(__name__)

# Canonical shape of a generated reflection. All generators return exactly
# these keys so the mod and the memory store can rely on a stable contract.
REFLECTION_SHAPE: dict[str, Any] = {
    "text": "",
    "insights": [],
    "personality": "",
    "source": "template",
    "generated_at": 0.0,
}


def _extract_json_object(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _summarize_events(events: list[dict], lang: str) -> tuple[str, list[str]]:
    """Extract dominant themes and build a short summary from events."""
    if not events:
        return "", []
    target = normalize_lang(lang)

    themes: dict[str, int] = {}
    for ev in events:
        ev_type = str(ev.get("type") or "").strip()
        content = ev.get("content") or {}
        if isinstance(content, dict):
            for key in ("message", "action", "topic"):
                val = content.get(key)
                if val:
                    themes[str(val).strip().lower()] = themes.get(str(val).strip().lower(), 0) + 1
        if ev_type:
            themes[ev_type.lower()] = themes.get(ev_type.lower(), 0) + 1

    sorted_themes = sorted(themes.items(), key=lambda x: x[1], reverse=True)
    top_themes = [t for t, _ in sorted_themes[:3]]

    if top_themes:
        summary = content_i18n.t(
            target, "reflection.themes", themes=", ".join(top_themes)
        )
    else:
        summary = content_i18n.t(target, "reflection.no_themes")

    return summary, top_themes


def normalize_reflection(raw: dict) -> dict:
    """Coerce a raw dict into exactly REFLECTION_SHAPE. Never raises."""
    data = _as_dict(raw)
    text = str(data.get("text") or "").strip()
    insights = _string_list(data.get("insights"))
    personality = str(data.get("personality") or "").strip()
    source = str(data.get("source") or "template").strip() or "template"
    try:
        generated_at = float(data.get("generated_at") or 0.0)
    except (TypeError, ValueError):
        generated_at = time.time()
    if not generated_at or not isinstance(generated_at, (int, float)) or math.isnan(generated_at):
        generated_at = time.time()

    return {
        "text": text,
        "insights": insights,
        "personality": personality,
        "source": source,
        "generated_at": generated_at,
    }


def fallback_reflection(profile: dict, events: list[dict], lang: str) -> dict:
    """Deterministic reflection summary in the requested language.

    Builds 1-3 sentences referencing the Sim name and dominant themes.
    Leaves ``personality`` as the profile's existing personality.
    """
    data = _as_dict(profile)
    target_lang = normalize_lang(lang)
    name = str(data.get("name") or data.get("full_name") or "This Sim").strip() or "This Sim"
    current_personality = str(data.get("personality") or "").strip()

    summary, themes = _summarize_events(events, target_lang)

    parts = [content_i18n.t(target_lang, "reflection.intro", name=name)]
    if summary:
        parts.append(summary)
    if themes:
        parts.append(
            content_i18n.t(target_lang, "reflection.focuses", themes=", ".join(themes))
        )
    text = " ".join(parts)

    return {
        "text": text,
        "insights": themes,
        "personality": current_personality,
        "source": "template",
        "generated_at": time.time(),
    }


def should_reflect(
    profile: dict,
    events: list[dict],
    *,
    min_events: int = 8,
    last_reflection_ts: float = 0.0,
    now: float | None = None,
    cooldown_seconds: float = 900.0,
) -> bool:
    """Return True when a reflection should be triggered.

    Conditions: at least ``min_events`` events AND cooldown elapsed since
    ``last_reflection_ts``.
    """
    if len(events) < min_events:
        return False
    current = now if now is not None else time.time()
    return (current - last_reflection_ts) >= cooldown_seconds


async def reflect(
    profile: dict,
    events: list[dict],
    lang: str,
    registry: Any = None,
) -> dict:
    """Generate a reflection, falling back to a deterministic template.

    Returns ``{"reflection": <REFLECTION_SHAPE>, "trait_swap": {...}, "provider": str|None}``.
    Never raises.
    """
    data = _as_dict(profile)
    target_lang = normalize_lang(lang)

    fallback = fallback_reflection({**data, "lang": target_lang}, events, target_lang)

    if registry is None:
        return {
            "reflection": fallback,
            "trait_swap": {"add": None, "remove": None, "reason": ""},
            "provider": None,
        }

    try:
        name = str(data.get("name") or data.get("full_name") or "the Sim").strip()
        current_personality = str(data.get("personality") or "").strip()
        summary, themes = _summarize_events(events, target_lang)

        system = (
            "You are the narrative director for a Sims 4 save. You write "
            "reflections that compress a Sim's recent experiences into insights "
            "and a drifted personality description."
        )
        user = (
            f"Sim: {name}\n"
            f"Current personality: {current_personality or 'none'}\n"
            f"Recent events summary: {summary}\n"
            f"Dominant themes: {', '.join(themes) or 'none'}\n\n"
            "Instructions:\n"
            f"- Write a 2-4 sentence reflection for {name}.\n"
            f"- Write only in {content_i18n.language_name(target_lang)}.\n"
            "- Extract 2-4 concise insights as an array.\n"
            "- Drift the personality description slightly based on the events.\n"
            "- Optionally propose ONE trait to add and ONE to remove (or null).\n"
            '- Return ONLY a JSON object with keys "reflection" (string), '
            '"insights" (array of strings), "personality" (string), '
            '"trait_add" (string|null), "trait_remove" (string|null), '
            '"trait_reason" (string).'
        )
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        response = await registry.complete(
            messages,
            lang=target_lang,
            temperature=0.7,
            max_tokens=500,
        )

        raw_text = getattr(response, "text", "")
        parsed = _extract_json_object(raw_text)

        if parsed is None:
            logger.warning("reflection: failed to parse JSON from LLM response")
            return {
                "reflection": fallback,
                "trait_swap": {"add": None, "remove": None, "reason": ""},
                "provider": None,
            }

        reflection_text = str(parsed.get("reflection") or "").strip()
        insights = _string_list(parsed.get("insights"))
        personality = str(parsed.get("personality") or "").strip()
        trait_add = parsed.get("trait_add")
        trait_remove = parsed.get("trait_remove")
        trait_reason = str(parsed.get("trait_reason") or "").strip()

        if not reflection_text:
            logger.warning("reflection: empty reflection text from LLM")
            return {
                "reflection": fallback,
                "trait_swap": {"add": None, "remove": None, "reason": ""},
                "provider": None,
            }

        reflection = {
            "text": reflection_text,
            "insights": insights,
            "personality": personality or current_personality,
            "source": "llm",
            "generated_at": time.time(),
        }

        trait_swap = {
            "add": str(trait_add).strip() if trait_add else None,
            "remove": str(trait_remove).strip() if trait_remove else None,
            "reason": trait_reason,
        }

        return {
            "reflection": reflection,
            "trait_swap": trait_swap,
            "provider": getattr(response, "provider", None),
        }

    except Exception as exc:
        logger.warning("reflection generation failed: %s", exc)
        return {
            "reflection": fallback,
            "trait_swap": {"add": None, "remove": None, "reason": ""},
            "provider": None,
        }


def propose_trait_swap(
    profile: dict,
    reflection: dict,
    *,
    known_traits: list[str] | None = None,
) -> dict:
    """Deterministic fallback for trait swap proposals.

    Returns ``{"add": str|None, "remove": str|None, "reason": str}``.
    If the reflection carries add/remove, echo them (validated against
    ``known_traits`` for removal). Never proposes removing an unknown trait.
    """
    data = _as_dict(reflection)
    trait_add = data.get("trait_add")
    trait_remove = data.get("trait_remove")
    trait_reason = str(data.get("trait_reason") or "").strip()

    add = str(trait_add).strip() if trait_add else None
    remove = str(trait_remove).strip() if trait_remove else None

    if known_traits is not None and remove and remove not in known_traits:
        remove = None
        if trait_reason:
            trait_reason += " (removal blocked: trait not in known_traits)"

    return {"add": add, "remove": remove, "reason": trait_reason}