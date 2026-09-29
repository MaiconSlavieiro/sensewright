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

from ..schemas import normalize_lang

logger = logging.getLogger(__name__)

_MAX_SUMMARY_CHARS = 280
_MAX_TRANSCRIPT_CHARS = 4000
_MAX_TOKENS = 500
_TOP_TOPICS = 5
_TOP_RELATIONSHIPS = 5

_LANG_NAMES: dict[str, str] = {
    "en": "English",
    "pt-BR": "Brazilian Portuguese",
}

_EMPTY_SUMMARY: dict[str, str] = {
    "en": "No dialogue to consolidate.",
    "pt-BR": "Nenhum diálogo para consolidar.",
}

_STOPWORDS = frozenset(
    {
        # English
        "about", "after", "again", "against", "being", "could", "did", "does", "doing",
        "down", "each", "from", "going", "have", "having", "here", "into", "just", "know",
        "like", "maybe", "more", "most", "much", "must", "need", "only", "other", "over",
        "really", "should", "some", "such", "than", "that", "their", "them", "then",
        "there", "these", "they", "thing", "think", "this", "those", "very", "want",
        "well", "were", "what", "when", "where", "which", "while", "will", "with",
        "would", "yeah", "your", "you", "the", "and", "but", "for", "not", "are", "was",
        "can", "get", "got", "her", "his", "she", "him", "its", "our", "out",
        "who", "why", "how", "all", "any", "too", "also", "okay", "hello",
        # Português
        "você", "voce", "para", "pra", "muito", "bem", "também", "tambem", "só", "so",
        "já", "ja", "aqui", "ali", "isso", "isto", "aquilo", "tudo", "nada", "algo",
        "porque", "então", "entao", "como", "quando", "onde", "quem", "qual", "mas",
        "uma", "uns", "umas", "dos", "das", "nos", "nas", "pelo", "pela", "nós",
        "eles", "elas", "meu", "minha", "seu", "sua", "nosso", "nossa", "está", "esta",
        "estou", "tem", "tenho", "ter", "vai", "vou", "não", "nao", "sim", "obrigado",
        "obrigada",
    }
)

_EMOTION_WORDS: dict[str, str] = {
    "happy": "joy",
    "happiness": "joy",
    "feliz": "joy",
    "alegre": "joy",
    "joy": "joy",
    "love": "affection",
    "loved": "affection",
    "amor": "affection",
    "angry": "anger",
    "anger": "anger",
    "mad": "anger",
    "raiva": "anger",
    "sad": "sadness",
    "sadness": "sadness",
    "triste": "sadness",
    "afraid": "fear",
    "scared": "fear",
    "fear": "fear",
    "medo": "fear",
    "excited": "excitement",
    "animado": "excitement",
    "anxious": "anxiety",
    "ansioso": "anxiety",
    "worried": "anxiety",
    "tired": "exhaustion",
    "cansado": "exhaustion",
    "lonely": "loneliness",
    "sozinho": "loneliness",
    "proud": "pride",
    "orgulhoso": "pride",
    "embarrassed": "embarrassment",
    "envergonhado": "embarrassment",
    "grateful": "gratitude",
    "grato": "gratitude",
}

_WORD_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ']+")
_PROPER_NOUN_RE = re.compile(r"\b([A-Z][a-zà-öø-ÿ]{2,})\b")

_NAME_EXCLUDE = frozenset(
    {
        "The", "And", "But", "You", "She", "He", "They", "We", "It", "That", "This",
        "What", "When", "Where", "Why", "How", "Yes", "Not", "Oh", "Well", "Okay",
        "Hello", "Hey", "Thanks", "Thank", "Please", "Sim", "Sims",
        # Português
        "Olá", "Ola", "Oi", "Você", "Voce", "Ele", "Ela", "Nós", "Nos", "Eles", "Elas",
        "Não", "Nao", "Mas", "Que", "Como", "Quando", "Onde", "Porque", "Então",
        "Entao",
    }
)


def deterministic_consolidation(
    turns: list[dict[str, Any]], profile: dict[str, Any], lang: str = "en"
) -> dict:
    """Extractive consolidation requiring no LLM. Never raises."""
    target = normalize_lang(lang)
    messages = _messages(turns)
    transcript = " ".join(messages)

    summary = _truncate(transcript, _MAX_SUMMARY_CHARS)
    if not summary:
        summary = _EMPTY_SUMMARY.get(target, _EMPTY_SUMMARY["en"])

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


def _messages(turns: list[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for turn in turns or []:
        if not isinstance(turn, dict):
            continue
        content = turn.get("content")
        message: Any = None
        if isinstance(content, dict):
            for key in ("message", "text", "summary"):
                if content.get(key):
                    message = content[key]
                    break
        elif isinstance(content, str):
            message = content
        if message is None:
            message = turn.get("message") or turn.get("text")
        text = str(message).strip() if message is not None else ""
        if text:
            messages.append(text)
    return messages


def _topics(transcript: str) -> list[str]:
    counts = Counter(_significant_words(transcript))
    return [word for word, _ in counts.most_common(_TOP_TOPICS)]


def _significant_words(text: str) -> list[str]:
    return [
        word
        for word in _WORD_RE.findall(text.lower())
        if len(word) >= 4 and word not in _STOPWORDS
    ]


def _emotions(transcript: str, lang: str) -> list[str]:
    found: list[str] = []
    for word in _WORD_RE.findall(transcript.lower()):
        label = _EMOTION_WORDS.get(word)
        if label and label not in found:
            found.append(label)
    prefix = "senti" if lang == "pt-BR" else "felt"
    return [f"{prefix} {label}" for label in found]


def _facts(profile: dict[str, Any], lang: str) -> list[str]:
    data = profile if isinstance(profile, dict) else {}
    name = str(data.get("name") or data.get("full_name") or "").strip()
    if not name:
        return []
    if lang == "pt-BR":
        return [f"{name} participou desta conversa."]
    return [f"{name} took part in this conversation."]


def _relationships(transcript: str) -> list[str]:
    names: list[str] = []
    for match in _PROPER_NOUN_RE.findall(transcript):
        if match in _NAME_EXCLUDE or match.lower() in _STOPWORDS:
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
    transcript = "\n".join(_messages(turns))[:_MAX_TRANSCRIPT_CHARS]

    system = (
        "You consolidate a Sim's dialogue into a single durable memory. "
        'Return ONLY a JSON object with keys: "summary" (string), "topics" '
        '(array of short strings), "emotional_takeaways" (array), "facts" (array) '
        'and "relationships_touched" (array of names).'
    )
    user = (
        f"Sim: {name}\n"
        f"Write in {_LANG_NAMES.get(lang, 'English')}.\n"
        f"Dialogue transcript:\n{transcript}"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
