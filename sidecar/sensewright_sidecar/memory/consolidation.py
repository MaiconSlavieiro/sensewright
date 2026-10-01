"""Dialogue consolidation: collapse raw chat turns into one memory (v0.2 M1).

The graph calls :func:`consolidate_turns` after a dialogue silence window. It
summarizes a set of ``chat`` events (with the Sim's profile) into a single
``consolidated_memory`` payload: summary, topics, emotional takeaways, facts and
relationships touched. It always returns a deterministic extractive result and
uses an LLM only as an optional enhancement (never required, never fatal).
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import Any

from .. import content_i18n
from ..schemas import normalize_lang

logger = logging.getLogger(__name__)

_MAX_SUMMARY_CHARS = 280
_MAX_TRANSCRIPT_CHARS = 4000
_MAX_TOKENS = 500
_TOP_TOPICS = 5
_TOP_RELATIONSHIPS = 5

def _stopwords() -> frozenset:
    """Stopword set from the lexical data (data-driven, no language strings here)."""
    words = content_i18n.lexicon().get("stopwords")
    return frozenset(str(word) for word in words) if isinstance(words, list) else frozenset()


def _emotion_words() -> dict[str, str]:
    """Emotion keyword -> canonical label map from the lexical data."""
    words = content_i18n.lexicon().get("emotion_words")
    if isinstance(words, dict):
        return {str(key): str(value) for key, value in words.items()}
    return {}


def _name_exclude() -> frozenset:
    """Proper-noun false positives to skip, from the lexical data."""
    names = content_i18n.lexicon().get("name_exclude")
    return frozenset(str(name) for name in names) if isinstance(names, list) else frozenset()


_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ']+")
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-zà-öø-ÿ]{2,})\b")


def deterministic_consolidation(
    turns: list[dict[str, Any]], profile: dict[str, Any], lang: str = "en"
) -> dict:
    """Extractive consolidation requiring no LLM. Never raises."""
    target = normalize_lang(lang)
    messages = _messages(turns, target)
    transcript = " ".join(messages)

    summary = _truncate(transcript, _MAX_SUMMARY_CHARS)
    if not summary:
        summary = content_i18n.t(target, "consolidation.empty_summary")

    return {
        "summary": summary,
        "topics": _topics(transcript),
        "emotional_takeaways": _emotions(transcript, target),
        "facts": _facts(profile, target),
        "relationships_touched": _relationships(transcript),
        "source": "template",
    }


async def consolidate_turns(
    turns: list[dict[str, Any]],
    profile: dict[str, Any],
    registry: Any = None,
    lang: str = "en",
) -> dict:
    """Consolidate dialogue, using ``registry`` when available.

    Returns the deterministic result on a missing registry or on ANY failure
    (bad JSON, network error, ...). Never raises.
    """
    target = normalize_lang(lang)
    fallback = deterministic_consolidation(turns, profile, target)
    if registry is None:
        return fallback

    try:
        messages = _build_messages(turns, profile, target)
        response = await registry.complete(messages, lang=target, max_tokens=_MAX_TOKENS)
        raw_text = getattr(response, "text", "") or ""
        parsed = _extract_json_object(raw_text)
        if not isinstance(parsed, dict):
            return fallback

        result = _normalize_consolidation(parsed, fallback)
        result["source"] = str(getattr(response, "provider", "") or "llm")
        return result
    except Exception as exc:
        logger.warning("dialogue consolidation failed: %s", exc)
        return fallback


def _content_of(event: dict[str, Any]) -> dict[str, Any]:
    content = event.get("content")
    if isinstance(content, dict):
        return content
    if isinstance(content, str) and content.strip():
        return {"text": content.strip()}
    return {}


# Purely mechanical samples that would drown the durable memory.
_SKIP_EVENT_TYPES = frozenset({"snapshot"})


def _event_line(event: dict[str, Any], lang: str) -> str:
    """Render one stored event of ANY native type as a readable line.

    The consolidation used to read only chat ``message``/``text``; thoughts,
    social exchanges, buffs, relationship changes and player choices were all
    dropped. This turns every captured event type into a line so the Sim's day is
    consolidated.
    """
    etype = str(event.get("type") or "").strip()
    if etype in _SKIP_EVENT_TYPES:
        return ""
    content = _content_of(event)

    # A player choice and its consequence, when the event carries one.
    for key in ("choice", "outcome", "consequence", "result"):
        value = content.get(key)
        if value:
            return str(value).strip()

    if etype == "social":
        topic = str(content.get("topic") or "").strip()
        with_value = content.get("with")
        lines = content.get("lines")
        spoken = ""
        if isinstance(lines, list) and lines and isinstance(lines[0], dict):
            spoken = str(lines[0].get("text") or "").strip()
        head = "talked"
        if with_value:
            head += f" with {with_value}"
        if topic:
            head += f" about {topic}"
        return f"{head}: {spoken}" if spoken else head

    if etype == "buff_add":
        buff = str(content.get("buff") or "").strip()
        return f"felt {buff}" if buff else "mood shifted"
    if etype == "buff_remove":
        buff = str(content.get("buff") or "").strip()
        return f"no longer felt {buff}" if buff else ""
    if etype == "relationship_change":
        target = str(content.get("target") or "").strip()
        depth = content.get("depth")
        line = f"relationship with {target}" if target else "relationship changed"
        if depth is not None:
            try:
                line += f" ({float(depth):+.0f})"
            except (TypeError, ValueError):
                pass
        return line
    if etype == "household_change":
        household_id = content.get("household_id")
        return "household changed{}".format(f" ({household_id})" if household_id else "")
    if etype == "skill_level_up":
        skill = content.get("skill") or content.get("name")
        return f"improved {skill}" if skill else "a skill improved"
    if etype == "career_change":
        career = content.get("career") or content.get("name")
        return f"career changed to {career}" if career else "career changed"
    if etype == "trait_change":
        trait = content.get("trait") or content.get("name")
        return f"trait changed: {trait}" if trait else "personality shifted"
    if etype == "sim_death":
        return "someone passed away"

    # Generic text fields (chat / thought / zone_load / ...).
    for key in ("text", "message", "summary"):
        value = content.get(key)
        if value:
            return str(value).strip()
    # Last resort: compact values only (never a raw dict repr / ids).
    return " ".join(str(value) for value in content.values() if value not in (None, ""))


def _messages(turns: list[dict[str, Any]], lang: str = "en") -> list[str]:
    lines: list[str] = []
    for turn in turns or []:
        if not isinstance(turn, dict):
            continue
        line = _event_line(turn, lang)
        if line:
            lines.append(line)
    return lines


def _topics(transcript: str) -> list[str]:
    counts = Counter(_significant_words(transcript))
    return [word for word, _ in counts.most_common(_TOP_TOPICS)]


def _significant_words(text: str) -> list[str]:
    stopwords = _stopwords()
    return [
        word
        for word in _WORD_RE.findall(text.lower())
        if len(word) >= 4 and word not in stopwords
    ]


def _emotions(transcript: str, lang: str) -> list[str]:
    emotion_words = _emotion_words()
    found: list[str] = []
    for word in _WORD_RE.findall(transcript.lower()):
        label = emotion_words.get(word)
        if label and label not in found:
            found.append(label)
    return [content_i18n.t(lang, "consolidation.felt", label=label) for label in found]


def _facts(profile: dict[str, Any], lang: str) -> list[str]:
    data = profile if isinstance(profile, dict) else {}
    name = str(data.get("name") or data.get("full_name") or "").strip()
    if not name:
        return []
    return [content_i18n.t(lang, "consolidation.fact", name=name)]


def _relationships(transcript: str) -> list[str]:
    name_exclude = _name_exclude()
    stopwords = _stopwords()
    names: list[str] = []
    for match in _PROPER_NOUN_RE.findall(transcript):
        if match in name_exclude or match.lower() in stopwords:
            continue
        if match not in names:
            names.append(match)
    return names[:_TOP_RELATIONSHIPS]


def _truncate(text: str, max_chars: int) -> str:
    raw = str(text or "").strip()
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars] + "…"


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


def _normalize_consolidation(raw: dict, fallback: dict) -> dict:
    result = dict(fallback)
    summary = str(raw.get("summary") or "").strip()
    if summary:
        result["summary"] = summary
    for key in ("topics", "emotional_takeaways", "facts", "relationships_touched"):
        values = _string_list(raw.get(key))
        if values:
            result[key] = values
    return result


def _build_messages(
    turns: list[dict[str, Any]], profile: dict[str, Any], lang: str
) -> list[dict[str, str]]:
    data = profile if isinstance(profile, dict) else {}
    name = str(data.get("name") or data.get("full_name") or "the Sim").strip() or "the Sim"
    transcript = "\n".join(_messages(turns, lang))[:_MAX_TRANSCRIPT_CHARS]

    system = (
        "You consolidate a Sim's day into a single durable memory for The Sims 4. "
        "The input is a chronological list of the Sim's events: thoughts, "
        "conversations, moods/buffs, relationship changes, skill/career/trait "
        "changes and player choices with their consequences. Distill what matters "
        "long term. "
        'Return ONLY a JSON object with keys: "summary" (string), "topics" '
        '(array of short strings), "emotional_takeaways" (array), "facts" (array) '
        'and "relationships_touched" (array of names).'
    )
    user = (
        f"Sim: {name}\n"
        f"Write in {content_i18n.language_name(lang)}.\n"
        f"The Sim's day (chronological events):\n{transcript}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
