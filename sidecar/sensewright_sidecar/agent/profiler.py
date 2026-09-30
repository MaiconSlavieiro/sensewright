"""Agent profiler for generating Sim character profiles from a seed sentence.

Profiles are the second layer of meaning the agent stores per Sim. Native game
data (traits, age, career, skills) is always ground truth; the seed and hints
only color the writing. Every public coroutine degrades gracefully to a
deterministic template when no LLM provider is available.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .. import content_i18n
from ..schemas import normalize_lang

logger = logging.getLogger(__name__)

# Canonical shape of a generated profile. All generators return exactly
# these keys so the mod and the memory store can rely on a stable contract.
PROFILE_SHAPE: dict[str, Any] = {
    "name": "",
    "backstory": "",
    "personality": "",
    "speech_style": "",
    "goals": [],
    "secrets": [],
    "quirks": [],
    "traits": [],
    "source": "template",
    "generated_at": 0.0,
}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


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


def normalize_profile(raw: dict) -> dict:
    """Coerce any dict into exactly PROFILE_SHAPE keys. Never raises."""
    if not isinstance(raw, dict):
        raw = {}

    profile: dict[str, Any] = {}
    profile["name"] = str(raw.get("name") or "").strip()
    profile["backstory"] = str(raw.get("backstory") or "").strip()
    profile["personality"] = str(raw.get("personality") or "").strip()
    profile["speech_style"] = str(raw.get("speech_style") or "").strip()
    profile["goals"] = _string_list(raw.get("goals"))
    profile["secrets"] = _string_list(raw.get("secrets"))
    profile["quirks"] = _string_list(raw.get("quirks"))
    profile["traits"] = _string_list(raw.get("traits"))
    profile["source"] = str(raw.get("source") or "template").strip()
    try:
        profile["generated_at"] = float(raw.get("generated_at"))
    except (TypeError, ValueError):
        profile["generated_at"] = time.time()

    return profile


def fallback_profile(seed: str, lang: str, native: dict | None = None) -> dict:
    """Deterministic template profile in the requested language.

    ``native`` may contain ``full_name``/``name``, ``traits`` (list), ``age``,
    ``career``, ``skills``. Use native traits/name when present; incorporate the
    seed text. Text for every language comes from ``locales_content`` (no inline
    language strings).
    """
    data = native if isinstance(native, dict) else {}
    target_lang = normalize_lang(lang)

    name = str(data.get("full_name") or data.get("name") or "This Sim").strip() or "This Sim"
    age = str(data.get("age") or "").strip()
    career = str(data.get("career") or "").strip()
    traits = _string_list(data.get("traits"))
    skills = _string_list(data.get("skills"))
    seed_text = str(seed or "").strip()

    parts = [content_i18n.t(target_lang, "profile.head", name=name)]
    if age:
        parts.append(f"({age})")
    parts.append(content_i18n.t(target_lang, "profile.living"))
    if seed_text:
        parts.append(content_i18n.t(target_lang, "profile.seed", seed=seed_text))
    if traits:
        parts.append(content_i18n.t(target_lang, "profile.traits", traits=", ".join(traits)))
    else:
        parts.append(content_i18n.t(target_lang, "profile.no_traits"))
    if career:
        parts.append(content_i18n.t(target_lang, "profile.career", career=career))
    if skills:
        parts.append(content_i18n.t(target_lang, "profile.skills", skills=", ".join(skills)))
    backstory = " ".join(parts)
    personality = content_i18n.t(target_lang, "profile.personality")
    speech_style = content_i18n.t(target_lang, "profile.speech_style")
    goals = [
        content_i18n.t(target_lang, "profile.goal.1"),
        content_i18n.t(target_lang, "profile.goal.2"),
    ]
    secrets = [content_i18n.t(target_lang, "profile.secret.1")]
    quirks = [
        content_i18n.t(target_lang, "profile.quirk.1"),
        content_i18n.t(target_lang, "profile.quirk.2"),
    ]

    return {
        "name": name,
        "backstory": backstory,
        "personality": personality,
        "speech_style": speech_style,
        "goals": goals,
        "secrets": secrets,
        "quirks": quirks,
        "traits": traits,
        "source": "template",
        "generated_at": time.time(),
    }


def _build_profile_messages(
    seed: str,
    lang: str,
    hints: str,
    native: dict | None,
) -> list[dict[str, str]]:
    data = native if isinstance(native, dict) else {}
    target_lang = normalize_lang(lang)

    name = str(data.get("full_name") or data.get("name") or "the Sim").strip()
    age = str(data.get("age") or "unknown").strip()
    career = str(data.get("career") or "none").strip()
    traits = _string_list(data.get("traits"))
    skills = _string_list(data.get("skills"))

    native_facts = [
        f"Name: {name}",
        f"Age: {age}",
        f"Career: {career}",
        f"Native traits: {', '.join(traits) or 'none'}",
        f"Skills: {', '.join(skills) or 'none'}",
    ]

    system = (
        "You are the character designer for a Sims 4 save. You write profiles "
        "that fit the neighborhood. The native Sim data is ground truth: "
        "never contradict traits, age, career or skills."
    )
    user = (
        "Native Sim data (ground truth):\n" + "\n".join(native_facts) + "\n\n"
        f"Seed (one sentence): {str(seed or '').strip() or 'none'}\n"
        f"Hints: {str(hints or '').strip() or 'none'}\n\n"
        "Instructions:\n"
        f"- Write a profile for {name}.\n"
        f"- Write only in {content_i18n.language_name(target_lang)}.\n"
        "- Never contradict the native traits, age, career or skills.\n"
        '- Return ONLY a JSON object with keys: "name" (string), '
        '"backstory" (2-4 sentences), "personality" (string), '
        '"speech_style" (string), "goals" (array of short strings), '
        '"secrets" (array), "quirks" (array), "traits" (array of native trait strings).'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def generate_profile(
    seed: str,
    lang: str,
    registry: Any,
    *,
    hints: str = "",
    native: dict | None = None,
) -> dict:
    """Generate a Sim profile, falling back to a deterministic template.

    Returns ``{"profile": <PROFILE_SHAPE>, "provider": str|None}``.
    Never raises.
    """
    target_lang = normalize_lang(lang)

    fallback = fallback_profile(seed, target_lang, native)
    if registry is None:
        return {"profile": fallback, "provider": None}

    try:
        messages = _build_profile_messages(seed, target_lang, hints, native)
        response = await registry.complete(
            messages,
            lang=target_lang,
            temperature=0.9,
            max_tokens=600,
        )
        raw_text = getattr(response, "text", "")
        parsed = _extract_json_object(raw_text)
        if parsed is None:
            return {"profile": fallback, "provider": None}

        profile = normalize_profile(parsed)
        profile["source"] = "llm"
        profile["generated_at"] = time.time()
        return {"profile": profile, "provider": getattr(response, "provider", None)}
    except Exception as exc:
        logger.warning("profile generation failed: %s", exc)
        return {"profile": fallback, "provider": None}