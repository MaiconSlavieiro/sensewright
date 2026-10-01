"""Social layer (L6, v0.3 R5): sim<->sim dialogue channel.

Two agent-owned Sims get a real conversation. The layer picks disjoint pairs of
non-player Sims, builds a PairContext, and renders a short dialogue (template or
LLM). The resulting Dialogue carries two "speak" intents so the mod's GameLever
and the legacy /v1/autonomy/directives alias keep working.
"""

from __future__ import annotations

import ast
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .. import content_i18n
from ..llm import langguard
from .context_forge import PairContext
from .intents import DEFAULT_EXPIRES_AT
from .prompts import strip_thought

logger = logging.getLogger(__name__)

# When the current native interaction cannot be classified, fall back to this.
DEFAULT_CATEGORY = "casual"
DEFAULT_TONE = "casual"

# A native interaction name maps to a dialogue category so the interaction the
# Sims are actually doing shapes what they say. Tokens are matched in order, so
# specific tokens come before generic ones (``kiss`` before ``flirt`` before a
# generic ``chat``). Categories have their own deterministic fallback lines
# (``social.line.<category>.<n>``).
_INTERACTION_CATEGORIES = (
    ("woohoo", "intimate"),
    ("make_out", "intimate"),
    ("makeout", "intimate"),
    ("kiss", "intimate"),
    ("cuddle", "affectionate"),
    ("hug", "affectionate"),
    ("affection", "affectionate"),
    ("get_to_know", "intro"),
    ("gettoknow", "intro"),
    ("getknow", "intro"),
    ("introduce", "intro"),
    ("intro", "intro"),
    ("flirt", "flirty"),
    ("romance", "flirty"),
    ("romantic", "flirty"),
    ("joke", "funny"),
    ("funny", "funny"),
    ("comedy", "funny"),
    ("insult", "mean"),
    ("mock", "mean"),
    ("gossip", "mean"),
    ("argue", "tense"),
    ("fight", "tense"),
    ("yell", "tense"),
    ("anger", "tense"),
    ("chat", "friendly"),
    ("friendly", "friendly"),
)

# Tone used per category in the deterministic template and fallback topic.
_CATEGORY_TONES = {
    "intimate": "flirty",
    "affectionate": "warm",
    "flirty": "flirty",
    "funny": "funny",
    "intro": "friendly",
    "mean": "tense",
    "tense": "tense",
    "friendly": "friendly",
    "casual": "casual",
}

# Variant pool size for the rotated deterministic lines. Categories that ship
# fewer keys degrade to their 1/2 lines (never a missing key).
_MAX_VARIANTS = 4


def _hash_seed(seed: str | None) -> int:
    """Small stable hash for deterministic line rotation (no ``hash()`` salt)."""
    if not seed:
        return 0
    value = 0
    for char in str(seed):
        value = (value * 131 + ord(char)) & 0xFFFFFFFF
    return value


def _is_missing(value: str, key: str) -> bool:
    """``content_i18n.t`` returns the key itself when it is unknown."""
    return value == key


def _variant_count(lang: str, prefix: str) -> int:
    """Number of consecutive ``prefix.<n>`` lines available for ``lang``."""
    count = 0
    for index in range(1, _MAX_VARIANTS + 1):
        key = f"{prefix}.{index}"
        if _is_missing(content_i18n.t(lang, key), key):
            break
        count = index
    return count


def _object_token(label: str) -> str:
    """Map a localized object label to a data-driven token (``bed``/``bathtub``).

    The mapping lives in ``lexicon.json`` -> ``object_tokens`` (multiple language
    words per token), so a new language or object needs a data edit only.
    """
    data = content_i18n.lexicon().get("object_tokens")
    if not isinstance(data, dict):
        return ""
    text = str(label or "").lower()
    if not text:
        return ""
    for token, words in data.items():
        if not isinstance(words, list):
            continue
        for word in words:
            if str(word).lower() in text:
                return str(token)
    return ""


def _clean_interaction_label(value: Any) -> str:
    """A safe localized interaction label (never a numeric id or hash)."""
    text = str(value or "").strip()
    if not text:
        return ""
    if text.isdigit():
        return ""
    if re.fullmatch(r"0x[0-9a-fA-F]+", text):
        return ""
    if len(text) > 80:
        return ""
    return text


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object from a model reply (v0.5 R4/R5).

    Strips a private ``[thought]`` block and markdown fences, tries a strict
    parse, then falls back to the first balanced ``{...}`` object embedded in
    surrounding prose. Returns ``None`` when nothing parses (never raises).
    """
    if not text:
        return None
    cleaned = strip_thought(str(text)).strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except (TypeError, ValueError):
        pass
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(cleaned[start : index + 1])
                except (TypeError, ValueError):
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def _normalize_speakers(
    lines: list[dict[str, Any]],
    name_a: str,
    name_b: str,
) -> list[dict[str, Any]]:
    """Map each line's speaker to the ``a``/``b`` slots the game expects.

    Models differ: Qwen3 emits ``"a"/"b"``, but granite/qwen2.5 emit the Sim
    *name* (``"Eric Lewis"``). This accepts ``a``/``b`` (case-insensitive),
    ``sim a``/``sim b`` and name matches, then falls back to alternating order
    so a two-line exchange always yields one ``a`` and one ``b`` (v0.5 R4).
    """
    name_a_l = str(name_a or "").strip().lower()
    name_b_l = str(name_b or "").strip().lower()
    out: list[dict[str, Any]] = []
    used: set[str] = set()
    for index, line in enumerate(lines):
        raw = str(line.get("speaker") or "").strip().lower()
        mapped: str | None = None
        if raw in ("a", "sim a", "sima", "sim_a"):
            mapped = "a"
        elif raw in ("b", "sim b", "simb", "sim_b"):
            mapped = "b"
        elif name_a_l and name_a_l in raw:
            mapped = "a"
        elif name_b_l and name_b_l in raw:
            mapped = "b"
        if mapped is None or mapped in used:
            mapped = "b" if "a" in used else "a"
        used.add(mapped)
        out.append({**line, "speaker": mapped})
        if len(used) >= 2 and index >= 1:
            break
    return out


# Category precedence for the data-driven multilingual tokens (lexicon.json ->
# ``interaction_tokens``); specific categories come before generic ones.
_CATEGORY_ORDER = (
    "intimate",
    "affectionate",
    "intro",
    "flirty",
    "funny",
    "mean",
    "tense",
    "friendly",
)


def _lexicon_interaction_tokens() -> dict[str, list[str]]:
    """Per-category multilingual action words (``lexicon.json``, data-driven)."""
    data = content_i18n.lexicon().get("interaction_tokens")
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for category, words in data.items():
        if isinstance(words, list):
            out[str(category)] = [str(word) for word in words]
    return out


def _classify_text(text: str) -> str | None:
    """Return the category for one interaction string, or ``None``.

    Stable English tuning tokens (``_INTERACTION_CATEGORIES``) are matched first;
    then the data-driven multilingual ``interaction_tokens`` from the lexicon, so
    a *localized* label (e.g. "Contar piada") classifies even when the raw
    interaction name is a generic base like ``sim_Chat``.
    """
    name = str(text or "").lower()
    if not name:
        return None
    for token, category in _INTERACTION_CATEGORIES:
        if token in name:
            return category
    tokens = _lexicon_interaction_tokens()
    for category in _CATEGORY_ORDER:
        for token in tokens.get(category, []):
            if token.lower() in name:
                return category
    return None


def classify_interaction(interaction: str, label: str = "") -> tuple[str, str]:
    """Map an interaction to a ``(category, tone)`` pair.

    The **localized label is tried first** (it is the most specific: "Contar
    piada" beats a generic raw ``sim_Chat``), then the raw interaction name.
    """
    candidates = []
    if label:
        candidates.append(label)
    candidates.append(interaction)
    for candidate in candidates:
        category = _classify_text(candidate)
        if category:
            return category, _CATEGORY_TONES.get(category, DEFAULT_TONE)
    return DEFAULT_CATEGORY, DEFAULT_TONE


def _dialogue_lines(
    lang: str,
    category: str,
    *,
    object_token: str = "",
    seed: str | None = None,
) -> tuple[str, str]:
    """Two alternating deterministic lines, rotated by ``seed`` (v0.5 R4).

    An ``intimate`` category with a known object uses that object's own lines
    (``social.line.intimate.<object>.<n>``) so a line fits the bed/bathtub/...;
    otherwise it degrades to the generic intimate/category/casual line pool.
    """
    prefix = ""
    if category == "intimate" and object_token:
        candidate = f"social.line.intimate.{object_token}"
        if _variant_count(lang, candidate) >= 2:
            prefix = candidate
    if not prefix:
        candidate = f"social.line.{category}"
        if _variant_count(lang, candidate) >= 2:
            prefix = candidate
        elif _variant_count(lang, "social.line.casual") >= 2:
            prefix = "social.line.casual"
        else:
            prefix = "social.line"

    count = max(2, _variant_count(lang, prefix))
    value = _hash_seed(seed)
    first = (value % count) + 1
    second = ((value // count) % count) + 1
    if second == first:
        second = (first % count) + 1
    return (
        content_i18n.t(lang, f"{prefix}.{first}"),
        content_i18n.t(lang, f"{prefix}.{second}"),
    )


def _location_xy(sim: dict[str, Any]) -> tuple[float, float] | None:
    """Parse a pulse ``location`` ("x,y") into floats, or None when absent."""
    location = (sim or {}).get("location")
    if not isinstance(location, str):
        return None
    parts = location.split(",")
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        return None


def _distance_between(a: dict[str, Any], b: dict[str, Any]) -> float | None:
    """Lot-space distance between two Sims, or None when a location is unknown."""
    pa = _location_xy(a)
    pb = _location_xy(b)
    if pa is None or pb is None:
        return None
    return ((pa[0] - pb[0]) ** 2 + (pa[1] - pb[1]) ** 2) ** 0.5


def _room_id_of(sim: dict[str, Any]) -> int | None:
    """The pulse room/block id of a Sim, or None when unknown (0 = outside)."""
    value = (sim or {}).get("room_id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _queued_targets_of(sim: dict[str, Any]) -> set[int]:
    """Sim ids this Sim has queued (next) interactions with."""
    targets: set[int] = set()
    for entry in (sim or {}).get("queued_interactions") or []:
        if not isinstance(entry, dict):
            continue
        value = entry.get("target_sim_id")
        if value is None:
            continue
        try:
            targets.add(int(value))
        except (TypeError, ValueError):
            continue
    return targets


def _topic_for(category: str, relationship: dict[str, Any] | None) -> str:
    """Deterministic topic: the interaction category first, then relationship."""
    if category == "flirty":
        return "a flirty exchange"
    if category == "intimate":
        return "an intimate moment"
    if category == "affectionate":
        return "a warm moment"
    if category == "funny":
        return "joking around"
    if category == "tense":
        return "a tense exchange"
    if category == "mean":
        return "a mean exchange"
    if category == "intro":
        return "getting to know each other"
    rel_type = (relationship or {}).get("type") if relationship else None
    rel_level = (relationship or {}).get("level") if relationship else None
    if rel_type == "romantic":
        return "a quiet moment together"
    if rel_type == "family":
        return "family matters"
    if rel_type == "friend":
        return "catching up"
    if rel_level is not None and rel_level < 0:
        return "a tense exchange"
    return "small talk"


def _clean_text(value: Any) -> str:
    """Coerce a profile/background value into plain text.

    Backgrounds used to arrive (and still do in legacy saves) as Python-repr or
    JSON dicts (``{'text': '...'}``) and even double-encoded
    (``"{'text': '{\\"text\\": ...}'}"``). This unwraps them so the LLM never
    sees a raw dict repr.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        for key in ("text", "summary", "background", "description"):
            if value.get(key):
                return _clean_text(value[key])
        return ""
    if isinstance(value, (list, tuple)):
        return " ".join(_clean_text(item) for item in value if item)
    text = str(value).strip()
    if not text:
        return ""
    if text.startswith("{") and text.endswith("}"):
        parsed: Any = None
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            try:
                parsed = ast.literal_eval(text)
            except (ValueError, SyntaxError):
                parsed = None
        if isinstance(parsed, dict):
            inner = _clean_text(parsed)
            if inner:
                return inner
    return text


def _memory_text(memory: Any) -> str:
    """Extract one readable line from a stored memory event.

    Events are shaped ``{"id", "type", "content": {...}, ...}`` (see
    ``memory/sqlite_store._row_to_event``); the text lives in ``content``. The
    old code read top-level ``summary``/``text``/``event`` keys, so no memory
    ever reached the prompt.
    """
    if not isinstance(memory, dict):
        return str(memory).strip() if memory else ""
    content = memory.get("content")
    if isinstance(content, dict):
        for key in ("text", "summary", "message"):
            if content.get(key):
                return str(content[key]).strip()
        topic = str(content.get("topic") or "").strip()
        lines = content.get("lines")
        spoken = ""
        if isinstance(lines, list) and lines and isinstance(lines[0], dict):
            spoken = str(lines[0].get("text") or "").strip()
        if topic and spoken:
            return f"{topic}: {spoken}"
        if topic or spoken:
            return topic or spoken
        for key in ("action", "reason"):
            if content.get(key):
                return str(content[key]).strip()
    for key in ("summary", "text", "event"):
        if memory.get(key):
            return str(memory[key]).strip()
    return ""


def _memory_partner_id(memory: Any) -> int | None:
    """The partner Sim id a memory event was about, or None."""
    if not isinstance(memory, dict):
        return None
    content = memory.get("content")
    if not isinstance(content, dict):
        return None
    value = content.get("with")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def sim_brief(
    entry: dict[str, Any] | None,
    other_name: str = "",
    partner_id: int | None = None,
) -> str:
    """One-line context for a Sim: background, personality, memories, partner.

    Memories about ``partner_id`` are surfaced separately ("what you remember
    about X") so the dialogue can reference shared history with the Sim it is
    talking to.
    """
    entry = entry or {}
    profile = entry.get("profile") or {}
    parts: list[str] = []
    background = _clean_text(profile.get("backstory")) or _clean_text(profile.get("background"))
    if background:
        parts.append(f"Background: {background}")
    personality = _clean_text(profile.get("personality")) or _clean_text(profile.get("speech_style"))
    if personality:
        parts.append(f"Personality: {personality}")

    memories = entry.get("memories") or []
    self_snippets: list[str] = []
    partner_snippets: list[str] = []
    for memory in memories[:12]:
        text = _memory_text(memory)
        if not text:
            continue
        if partner_id is not None and _memory_partner_id(memory) == partner_id:
            partner_snippets.append(text)
        else:
            self_snippets.append(text)
    if self_snippets:
        parts.append("Recent memories: " + "; ".join(self_snippets[:3]))
    if partner_snippets and other_name:
        parts.append(f"What you remember about {other_name}: " + "; ".join(partner_snippets[:3]))
    if other_name:
        parts.append(f"Talking with: {other_name}")
    return " | ".join(parts)


DEFAULT_MAX_PAIRS = 1
DEFAULT_PAIR_COOLDOWN_SECONDS = 180.0
DEFAULT_MAX_PAIR_DISTANCE = 4.0
DIALOGUE_MAX_LINES = 2

# Regex to strip meta references like "the user", "the player", etc.
_META_PATTERNS = [
    r"\bthe\s+user\b",
    r"\bthe\s+player\b",
    r"\byou\s+the\s+player\b",
    r"\bas\s+an\s+ai\b",
    r"\bas\s+a\s+language\s+model\b",
    r"\bi\s+am\s+an\s+ai\b",
    r"\bi\s+don't\s+have\b",
    r"\bi\s+cannot\b",
    r"\bi'm\s+sorry\b",
    r"\bhere\s+is\b",
    r"\bhere\s+are\b",
]
_META_RE = re.compile("|".join(_META_PATTERNS), re.IGNORECASE)


def clean_line(text: str) -> str:
    """Strip, drop empty/punctuation-only/meta lines; return cleaned text or empty string."""
    if not isinstance(text, str):
        return ""
    # A private thought must never be spoken to the other Sim.
    t = strip_thought(text).strip()
    # Remove surrounding quotes if the whole line is quoted
    if (t.startswith('"') and t.endswith('"')) or (t.startswith("'") and t.endswith("'")):
        t = t[1:-1].strip()
    # Drop if empty or only punctuation
    if not t or all(ch in ".,;:!?-—…()[]{}\"'" for ch in t):
        return ""
    # Drop meta commentary
    if _META_RE.search(t):
        return ""
    return t


@dataclass
class Dialogue:
    """A short dialogue between two Sims (max DIALOGUE_MAX_LINES lines)."""

    a: int
    b: int
    lines: list[dict[str, Any]] = field(default_factory=list)  # {"speaker": "a"|"b", "text": str, "tone": str}
    topic: str = ""
    source: str = "template"  # "template" | "llm"
    # v0.5 R5: provenance persisted with the social memory event.
    model: str = ""
    provider: str = ""
    object_label: str = ""
    interaction: str = ""

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation."""
        return {
            "a": self.a,
            "b": self.b,
            "lines": list(self.lines),
            "topic": self.topic,
            "source": self.source,
            "model": self.model,
            "provider": self.provider,
            "object": self.object_label,
            "interaction": self.interaction,
        }

    def intents(self) -> list[dict[str, Any]]:
        """Return exactly two "speak" intents (a->b, b->a) in intent.py shape."""
        intents: list[dict[str, Any]] = []
        for line in self.lines:
            speaker_key = line.get("speaker")
            if speaker_key not in ("a", "b"):
                continue
            speaker_id = self.a if speaker_key == "a" else self.b
            target_id = self.b if speaker_key == "a" else self.a
            text = str(line.get("text") or "").strip()
            tone = str(line.get("tone") or "friendly").strip() or "friendly"
            if not text:
                continue
            intent = {
                "id": uuid4().hex,
                "sim_id": speaker_id,
                "kind": "speak",
                "target_sim_id": target_id,
                # ``message`` lets the mod push a native ``say_to``; ``text`` is
                # the notification fallback when the native affordance fails.
                "params": {"text": text, "message": text, "tone": tone},
                "reason": self.topic,
                "expires_at": DEFAULT_EXPIRES_AT,
                "priority": 0,
                "source": "agent",
                # Legacy/directive-compatible fields (kept for the escape hatch + alias).
                "name": "say_to",
                "args": {"sim_id": speaker_id, "target_sim_id": target_id, "message": text, "tone": tone},
                "thought": "",
                "narration": "",
            }
            intents.append(intent)
        return intents


def template_dialogue(
    profile_a: dict[str, Any] | None,
    profile_b: dict[str, Any] | None,
    relationship: dict[str, Any] | None = None,
    a_id: int = 0,
    b_id: int = 0,
    lang: str = "en",
    name_a: str | None = None,
    name_b: str | None = None,
    interaction: str = "",
    interaction_text: str = "",
    object_label: str = "",
    seed: str | None = None,
) -> Dialogue:
    """Deterministic fallback dialogue (native mode or LLM failure).

    v0.5 R4: the category comes from the raw interaction; the lines rotate by
    ``seed`` (the pair) and, for ``intimate``, are chosen by the current object
    (``object_label``). ``interaction_text`` is the localized label used for the
    ``{interaction}`` placeholder (never a numeric/hash id).
    """
    name_a = str(name_a or (profile_a or {}).get("name") or f"Sim {a_id}")
    name_b = str(name_b or (profile_b or {}).get("name") or f"Sim {b_id}")

    interactive = _clean_interaction_label(interaction_text)
    category, tone = classify_interaction(interaction, interactive)
    topic = _topic_for(category, relationship)

    def _format(template: str) -> str:
        try:
            return template.format(
                a=name_a,
                b=name_b,
                interaction=interactive,
                object=object_label,
            )
        except Exception:
            return template

    # Two lines, alternating (the spoken words only; the caller attributes them).
    first, second = _dialogue_lines(
        lang, category, object_token=_object_token(object_label), seed=seed
    )
    lines = [
        {"speaker": "a", "text": _format(first), "tone": tone},
        {"speaker": "b", "text": _format(second), "tone": tone},
    ]

    return Dialogue(
        a=a_id,
        b=b_id,
        lines=lines,
        topic=topic,
        source="template",
        object_label=object_label,
        interaction=interactive or interaction,
    )


async def render_dialogue(
    profile_a: dict[str, Any] | None,
    profile_b: dict[str, Any] | None,
    relationship: dict[str, Any] | None,
    registry: Any,
    lang: str,
    a_id: int,
    b_id: int,
    max_tokens: int = 200,
    extra_a: str = "",
    extra_b: str = "",
    name_a: str | None = None,
    name_b: str | None = None,
    interaction: str = "",
    interaction_text: str = "",
    interaction_sequence: list[str] | None = None,
    continuing: bool = False,
    object_label: str = "",
    seed: str | None = None,
) -> Dialogue:
    """Render a dialogue via LLM or template fallback.

    ``name_a``/``name_b`` override the profile name (so a Sim with no generated
    profile still speaks under its real ``full_name`` instead of ``Sim <id>``).
    ``interaction`` is the raw native interaction (used for classification);
    ``interaction_text`` is its localized pie-menu display name (v0.4 P4c) and
    is what the model is told the pair is doing. ``interaction_sequence`` is the
    ordered list of queued/next interactions so the dialogue can flow with the
    action sequence (v0.4 P6); ``continuing`` tells the model the conversation is
    still ongoing, so it must not close with a farewell. ``object_label`` is the
    localized current object (v0.5 R4). Output is language-guarded (v0.4 P2): a
    wrong-language answer is retried once, then falls back to the deterministic
    localized template. Every fallback logs its reason (v0.5 R5).
    """
    label = _clean_interaction_label(interaction_text) or _clean_interaction_label(interaction)

    if registry is None:
        logger.info("social.fallback reason=registry_none a=%s b=%s", a_id, b_id)
        return template_dialogue(
            profile_a, profile_b, relationship, a_id, b_id, lang=lang,
            name_a=name_a, name_b=name_b, interaction=interaction,
            interaction_text=label, object_label=object_label, seed=seed,
        )

    name_a = str(name_a or (profile_a or {}).get("name") or f"Sim {a_id}")
    name_b = str(name_b or (profile_b or {}).get("name") or f"Sim {b_id}")

    personality_a = str((profile_a or {}).get("personality") or (profile_a or {}).get("speech_style") or "")
    personality_b = str((profile_b or {}).get("personality") or (profile_b or {}).get("speech_style") or "")

    rel_desc = ""
    if relationship:
        rel_type = relationship.get("type")
        rel_level = relationship.get("level")
        if rel_type:
            rel_desc = f"Relationship: {rel_type}"
            if rel_level is not None:
                rel_desc += f" (level {rel_level})"

    category, tone = classify_interaction(interaction, label)
    interaction_desc = ""
    if label:
        interaction_desc = (
            f"Native interaction: the two Sims are currently doing "
            f"'{label}' ({category} tone). The dialogue must match this "
            "interaction and its mood.\n"
        )
    if object_label:
        interaction_desc += f"Current object involved: {object_label}.\n"
    sequence = [str(name).strip() for name in (interaction_sequence or []) if str(name).strip()]
    if sequence:
        interaction_desc += (
            "Upcoming interactions already queued for these two Sims: "
            + ", ".join(sequence)
            + ". Let the lines flow with this sequence.\n"
        )
    if continuing:
        interaction_desc += (
            "The conversation is still ongoing: do NOT end with a farewell, "
            "goodbye or parting line. Keep it open for the next interaction.\n"
        )

    def _messages(reinforced: bool) -> list[dict[str, str]]:
        system = (
            "You write short, natural, in-character dialogue between two Sims in "
            f"The Sims 4. {langguard.language_directive(lang, reinforced=reinforced)} "
            "Reply with STRICT JSON only, no markdown fences, no meta commentary."
        )
        user = (
            f"Sim A: {name_a}. {extra_a or ('Personality: ' + (personality_a or 'neutral'))}\n"
            f"Sim B: {name_b}. {extra_b or ('Personality: ' + (personality_b or 'neutral'))}\n"
            f"{rel_desc}\n"
            f"{interaction_desc}\n"
            f"Write a short, natural dialogue (1-2 lines) as JSON:\n"
            f'{{"topic": "...", "lines": [{{"speaker": "a", "text": "...", "tone": "..."}}, '
            f'{{"speaker": "b", "text": "...", "tone": "..."}}]}}\n'
            f"Rules: max {DIALOGUE_MAX_LINES} lines, alternating speakers, "
            f"each line non-empty, tone is one word (friendly, flirty, tense, casual, warm). "
            f"Use the Sims' names, never numeric ids. No meta commentary. No markdown fences."
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _fallback(
        reason: str, *, provider: str = "", model: str = "", raw: str = ""
    ) -> Dialogue:
        logger.info(
            "social.fallback reason=%s provider=%s model=%s a=%s b=%s raw=%r",
            reason,
            provider or "-",
            model or "-",
            a_id,
            b_id,
            raw or "",
        )
        return template_dialogue(
            profile_a, profile_b, relationship, a_id, b_id, lang=lang,
            name_a=name_a, name_b=name_b, interaction=interaction,
            interaction_text=label, object_label=object_label, seed=seed,
        )

    last_provider = ""
    last_model = ""
    for attempt in range(2):
        try:
            response = await registry.complete(
                _messages(attempt > 0), lang=lang, max_tokens=max_tokens, purpose="social"
            )
        except Exception as exc:
            logger.warning("social dialogue LLM call failed, using template: %s", exc)
            return _fallback("exception", provider=last_provider, model=last_model)

        last_model = str(getattr(response, "model", "") or "")
        last_provider = str(getattr(response, "provider", "") or "")

        raw = str(getattr(response, "text", "") or "").strip()
        # v0.5 R4/R5: a reasoning/prose model may wrap the JSON (or leak a
        # ``[thought]`` block). Extract the first JSON object instead of failing
        # on strict ``json.loads``.
        data = _extract_json_object(raw)
        raw_snippet = " ".join(raw.split())[:160]

        candidate_lines: list[dict[str, Any]] = []
        topic = ""
        if isinstance(data, dict):
            topic = str(data.get("topic") or "").strip()
            raw_lines = data.get("lines")
            if isinstance(raw_lines, list):
                for item in raw_lines:
                    if not isinstance(item, dict):
                        continue
                    text = clean_line(str(item.get("text") or ""))
                    if not text:
                        continue
                    line_tone = str(item.get("tone") or tone).strip() or tone
                    candidate_lines.append(
                        {
                            "speaker": str(item.get("speaker") or ""),
                            "text": text,
                            "tone": line_tone,
                        }
                    )
                    if len(candidate_lines) >= DIALOGUE_MAX_LINES:
                        break
        # v0.5 R4: local models (granite/qwen2.5) label the speaker with the Sim
        # *name*, not "a"/"b". Normalize to the a/b slots the game expects.
        lines = _normalize_speakers(candidate_lines, name_a, name_b)

        if lines:
            spoken = " ".join(line["text"] for line in lines)
            if not langguard.is_wrong_lang(spoken, lang):
                if not topic:
                    topic = _topic_for(category, relationship)
                return Dialogue(
                    a=a_id,
                    b=b_id,
                    lines=lines,
                    topic=topic,
                    source="llm",
                    model=last_model,
                    provider=last_provider,
                    object_label=object_label,
                    interaction=label or interaction,
                )
            logger.info(
                "langguard rejected dialogue attempt %d (target=%s)", attempt + 1, lang
            )
            if attempt >= 1:
                return _fallback("langguard", provider=last_provider, model=last_model)
            continue
        if attempt >= 1:
            return _fallback(
                "empty" if not raw else "invalid_json",
                provider=last_provider,
                model=last_model,
                raw=raw_snippet,
            )

    return _fallback("exhausted", provider=last_provider, model=last_model)


class SocialLayer:
    """The sim<->sim dialogue layer (L6)."""

    name = "social"

    def __init__(
        self,
        settings: Any = None,
        *,
        registry: Any = None,
        rng: Any = None,
        clock: Any = None,
        max_pairs: int | None = None,
        pair_cooldown_seconds: float | None = None,
        require_conversation: bool | None = None,
        max_pair_distance: float | None = None,
        require_same_room: bool | None = None,
        keep_open_on_queued: bool | None = None,
    ) -> None:
        self._registry = registry
        self._rng = rng
        self._clock = clock or time.monotonic
        self._last_pair_at: dict[frozenset[int], float] = {}
        self.enabled = True
        self.max_pairs = max_pairs if max_pairs is not None else DEFAULT_MAX_PAIRS
        self.pair_cooldown = (
            pair_cooldown_seconds if pair_cooldown_seconds is not None else DEFAULT_PAIR_COOLDOWN_SECONDS
        )
        self.require_conversation = True if require_conversation is None else bool(require_conversation)
        self.max_pair_distance = (
            DEFAULT_MAX_PAIR_DISTANCE if max_pair_distance is None else float(max_pair_distance)
        )
        self.require_same_room = True if require_same_room is None else bool(require_same_room)
        self.keep_open_on_queued = True if keep_open_on_queued is None else bool(keep_open_on_queued)
        self.line_max_tokens = 200
        if settings is not None:
            self.configure(settings)
        # Explicit constructor args win over settings (targeted overrides/tests).
        if max_pairs is not None:
            self.max_pairs = int(max_pairs)
        if pair_cooldown_seconds is not None:
            self.pair_cooldown = float(pair_cooldown_seconds)
        if require_conversation is not None:
            self.require_conversation = bool(require_conversation)
        if max_pair_distance is not None:
            self.max_pair_distance = float(max_pair_distance)
        if require_same_room is not None:
            self.require_same_room = bool(require_same_room)
        if keep_open_on_queued is not None:
            self.keep_open_on_queued = bool(keep_open_on_queued)

    def configure(self, settings: Any) -> None:
        """Read settings.agents.layers.social (enable) and settings.agents.social
        (max_pairs_per_tick, pair_cooldown_seconds, require_conversation,
        max_pair_distance) defensively."""
        try:
            layers = getattr(getattr(settings, "agents", None), "layers", None)
            self.enabled = bool(getattr(layers, "social", True)) if layers is not None else True
        except Exception:
            self.enabled = True

        try:
            agents = getattr(settings, "agents", None)
            social_cfg = getattr(agents, "social", None) if agents is not None else None
            if social_cfg is not None:
                self.max_pairs = int(getattr(social_cfg, "max_pairs_per_tick", DEFAULT_MAX_PAIRS) or DEFAULT_MAX_PAIRS)
                self.pair_cooldown = float(getattr(social_cfg, "pair_cooldown_seconds", DEFAULT_PAIR_COOLDOWN_SECONDS) or DEFAULT_PAIR_COOLDOWN_SECONDS)
                self.line_max_tokens = int(getattr(social_cfg, "line_max_tokens", 200) or 200)
                self.require_conversation = bool(getattr(social_cfg, "require_conversation", True))
                self.max_pair_distance = float(
                    getattr(social_cfg, "max_pair_distance", DEFAULT_MAX_PAIR_DISTANCE)
                    or DEFAULT_MAX_PAIR_DISTANCE
                )
                self.require_same_room = bool(getattr(social_cfg, "require_same_room", True))
                self.keep_open_on_queued = bool(getattr(social_cfg, "keep_open_on_queued", True))
        except Exception:
            self.max_pairs = DEFAULT_MAX_PAIRS
            self.pair_cooldown = DEFAULT_PAIR_COOLDOWN_SECONDS
            self.line_max_tokens = 200
            self.require_conversation = True
            self.max_pair_distance = DEFAULT_MAX_PAIR_DISTANCE
            self.require_same_room = True
            self.keep_open_on_queued = True

        # Ensure sensible bounds
        self.max_pairs = max(1, self.max_pairs)
        self.pair_cooldown = max(0.0, self.pair_cooldown)
        self.line_max_tokens = max(1, self.line_max_tokens)
        self.max_pair_distance = max(0.0, float(self.max_pair_distance))

    def set_registry(self, registry: Any) -> None:
        self._registry = registry

    def eligible(self, sims: list[dict[str, Any]] | None, seated_ids: list[int] | None = None) -> list[dict]:
        """Return awake, autonomy != 'off', valid sim_id Sims. Deduplicate by sim_id.
        If seated_ids is non-empty, require membership."""
        if not sims:
            return []
        seated_set = set(seated_ids or [])
        seen: set[int] = set()
        out: list[dict] = []
        for sim in sims:
            try:
                sim_id = int(sim.get("sim_id"))
            except (TypeError, ValueError):
                continue
            if sim_id in seen:
                continue
            if sim.get("sleeping"):
                continue
            autonomy = str(sim.get("autonomy") or "").lower()
            if autonomy == "off":
                continue
            if seated_set and sim_id not in seated_set:
                continue
            seen.add(sim_id)
            out.append(sim)
        return out

    @staticmethod
    def _target_id_of(sim: dict[str, Any]) -> int | None:
        """The Sim id this Sim is currently in a native social interaction with."""
        value = (sim or {}).get("interaction_target_sim_id")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _rooms_ok(self, a: dict[str, Any], b: dict[str, Any]) -> bool:
        """True when the two Sims share a room (v0.4 P6).

        Pass-through when ``require_same_room`` is off, and when either room id
        is unknown (the distance gate still applies then). Outside is room ``0``
        for everyone, matching the engine's "the outdoors is one room".
        """
        if not self.require_same_room:
            return True
        room_a = _room_id_of(a)
        room_b = _room_id_of(b)
        if room_a is None or room_b is None:
            return True
        return room_a == room_b

    def filter_conversing(self, sims: list[dict[str, Any]] | None) -> list[dict]:
        """Keep only Sims in a *real* native conversation (v0.3 R5 fix).

        A Sim qualifies when it targets another Sim present in the pulse, that
        Sim targets it back, and the two are within ``max_pair_distance`` (when
        both locations are known). When ``require_conversation`` is off this is a
        pass-through. This is what stops agents from "talking telepathically"
        across the lot.
        """
        sims = list(sims or [])
        if not self.require_conversation:
            return sims

        by_id: dict[int, dict] = {}
        for sim in sims:
            try:
                by_id[int(sim.get("sim_id"))] = sim
            except (TypeError, ValueError):
                continue

        out: list[dict] = []
        for sim in sims:
            try:
                sim_id = int(sim.get("sim_id"))
            except (TypeError, ValueError):
                continue
            partner_id = self._target_id_of(sim)
            if partner_id is None or partner_id == sim_id:
                continue
            partner = by_id.get(partner_id)
            if partner is None or self._target_id_of(partner) != sim_id:
                continue
            if not self._rooms_ok(sim, partner):
                continue
            distance = _distance_between(sim, partner)
            if distance is not None and distance > self.max_pair_distance:
                continue
            out.append(sim)
        return out

    def pick_pairs(
        self,
        sims: list[dict[str, Any]] | None,
        seated_ids: list[int] | None = None,
        *,
        now: float | None = None,
    ) -> list[tuple[dict, dict]]:
        """Pick disjoint pairs of non-player Sims, honoring pair_cooldown.
        Returns at most self.max_pairs pairs. Deterministic but shuffled with self._rng."""
        eligible = self.eligible(sims, seated_ids)
        if len(eligible) < 2:
            return []

        # v0.3 R5 fix: prefer household Sims (and household<->guest pairs) so the
        # player's household is involved instead of two visiting passers-by.
        household = [s for s in eligible if s.get("is_player")]
        visitors = [s for s in eligible if not s.get("is_player")]
        for group in (household, visitors):
            group.sort(key=lambda s: int(s.get("sim_id", 0)))
            if self._rng is not None:
                try:
                    self._rng.shuffle(group)
                except Exception:
                    pass
        ordered = household + visitors

        now_ts = now if now is not None else self._clock()
        pairs: list[tuple[dict, dict]] = []
        used: set[int] = set()

        for i in range(len(ordered)):
            if len(pairs) >= self.max_pairs:
                break
            a = ordered[i]
            a_id = int(a.get("sim_id", 0))
            if a_id in used:
                continue
            for j in range(i + 1, len(ordered)):
                if len(pairs) >= self.max_pairs:
                    break
                b = ordered[j]
                b_id = int(b.get("sim_id", 0))
                if b_id in used:
                    continue
                pair_key = frozenset({a_id, b_id})
                if not self._rooms_ok(a, b):
                    continue
                # A pair that was never seen has no cooldown. Using ``0.0`` as
                # the default here was a bug: the clock (``time.monotonic``)
                # starts at boot, so on a freshly-booted machine the first-ever
                # pair was wrongly blocked until the uptime passed the cooldown.
                last = self._last_pair_at.get(pair_key)
                if last is not None and now_ts - last < self.pair_cooldown:
                    continue
                pairs.append((a, b))
                used.add(a_id)
                used.add(b_id)
                self._last_pair_at[pair_key] = now_ts
                break

        return pairs

    def pair_ready(self, key: frozenset[int], *, now: float | None = None) -> bool:
        """True when a pair's cooldown has elapsed (or it was never seen)."""
        last = self._last_pair_at.get(key)
        if last is None:
            return True
        reference = self._clock() if now is None else float(now)
        return (reference - last) >= self.pair_cooldown

    def note_pair(self, key: frozenset[int], *, now: float | None = None) -> None:
        """Record that a pair started (opens its session cooldown)."""
        reference = self._clock() if now is None else float(now)
        self._last_pair_at[key] = reference

    def candidate_pairs(
        self,
        sims: list[dict[str, Any]] | None,
        seated_ids: list[int] | None = None,
    ) -> list[tuple[dict, dict]]:
        """Pairs that are *actually* interacting (either direction), deduped.

        Unlike ``pick_pairs`` (which invents pairs of seated Sims), this returns
        the pairs the pulse shows genuinely interacting: ``A targets B`` is
        enough — the target need not target back, which is exactly how a
        player-initiated conversation looks in the pulse (v0.4 P4 live fix).
        Cooldown is left to the caller so an open session can continue without
        waiting for the inter-session pair cooldown.
        """
        eligible = self.eligible(sims, seated_ids)
        by_id: dict[int, dict] = {}
        for sim in eligible:
            try:
                by_id[int(sim.get("sim_id"))] = sim
            except (TypeError, ValueError):
                continue
        if len(by_id) < 2:
            return []

        ordered = sorted(
            by_id.values(),
            key=lambda s: (not s.get("is_player"), int(s.get("sim_id", 0))),
        )
        pairs: list[tuple[dict, dict]] = []
        used: set[int] = set()
        for sim in ordered:
            try:
                a = int(sim.get("sim_id"))
            except (TypeError, ValueError):
                continue
            if a in used:
                continue
            # The current target first, then any Sim the queue still continues
            # with (v0.4 P6). A queued partner keeps an open session alive even
            # when the running interaction is momentarily between affordances.
            partner_ids: list[int] = []
            current = self._target_id_of(sim)
            if current is not None:
                partner_ids.append(current)
            if self.keep_open_on_queued:
                for queued in sorted(_queued_targets_of(sim)):
                    if queued not in partner_ids:
                        partner_ids.append(queued)

            chosen: dict | None = None
            for b in partner_ids:
                if b == a or b in used:
                    continue
                other = by_id.get(b)
                if other is None:
                    continue
                if not self._rooms_ok(sim, other):
                    continue
                distance = _distance_between(sim, other)
                if distance is not None and distance > self.max_pair_distance:
                    continue
                chosen = other
                break
            if chosen is None:
                continue
            b_id = int(chosen.get("sim_id", 0))
            pairs.append((sim, chosen))
            used.add(a)
            used.add(b_id)
            if len(pairs) >= self.max_pairs:
                break
        return pairs

    async def _dialogue_for_pair(
        self,
        a: dict[str, Any],
        b: dict[str, Any],
        *,
        player_id: str,
        save_id: str,
        lang: str,
        forge: PairContext | None,
        use_llm: bool = True,
        variant: int = 0,
    ) -> Dialogue | None:
        """Render a dialogue for a specific pair (a, b).

        v0.5 R4: a sleeping Sim is never paired (defensive gate) so no dialogue
        is ever emitted during sleep. ``use_llm`` is False when the social budget
        is unavailable (v0.5 R3), forcing the deterministic template instead of
        dropping the interaction.
        """
        a_id = int(a.get("sim_id", 0))
        b_id = int(b.get("sim_id", 0))

        if a.get("sleeping") or b.get("sleeping"):
            logger.info("social skip reason=sleeping a=%s b=%s", a_id, b_id)
            return None

        # Build simple job objects for PairContext
        class _Job:
            def __init__(self, player_id: str, save_id: str, sim_id: int):
                self.player_id = player_id
                self.save_id = save_id
                self.sim_id = sim_id

        job_a = _Job(player_id, save_id, a_id)
        job_b = _Job(player_id, save_id, b_id)

        # Find relationship hint from a's relationships
        relationship = None
        rels = a.get("relationships")
        if isinstance(rels, list):
            for rel in rels:
                if isinstance(rel, dict) and int(rel.get("target_sim_id", 0)) == b_id:
                    relationship = dict(rel)
                    break

        # Use provided forge or create one
        pair_ctx = forge or PairContext(None)
        ctx = await pair_ctx.build(job_a, job_b, relationship)

        profile_a = ctx.get("a", {}).get("profile", {})
        profile_b = ctx.get("b", {}).get("profile", {})

        name_a = str((profile_a or {}).get("name") or a.get("full_name") or f"Sim {a_id}")
        name_b = str((profile_b or {}).get("name") or b.get("full_name") or f"Sim {b_id}")
        extra_a = sim_brief(ctx.get("a"), name_b, partner_id=b_id)
        extra_b = sim_brief(ctx.get("b"), name_a, partner_id=a_id)

        # The native interaction the pair is doing shapes the dialogue's content.
        # ``current_interaction`` is the stable raw name (classification);
        # ``current_interaction_text`` is the localized pie-menu label (v0.4 P4c).
        interaction = str(
            a.get("current_interaction") or b.get("current_interaction") or ""
        ).strip()
        interaction_text = str(
            a.get("current_interaction_text")
            or b.get("current_interaction_text")
            or ""
        ).strip()
        # v0.5 R4: the localized object involved (bed/bathtub/...) for intimate
        # interactions, so the fallback line matches where the pair is.
        object_label = str(
            a.get("current_object") or b.get("current_object") or ""
        ).strip()

        # v0.4 P6: the sequence of queued/next interactions, and whether the
        # pair is still engaged (current target or a queued interaction with the
        # same Sim), so the model can flow with the action sequence and avoid a
        # premature farewell.
        sequence: list[str] = []
        for source in (a, b):
            for entry in source.get("queued_interactions") or []:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("name") or "").strip()
                if name and name not in sequence:
                    sequence.append(name)
        continuing = (
            self._target_id_of(a) == b_id
            or self._target_id_of(b) == a_id
            or b_id in _queued_targets_of(a)
            or a_id in _queued_targets_of(b)
        )
        logger.info(
            "social context a=%s b=%s rooms=%s/%s same_room=%s interaction=%r "
            "object=%r sequence=%s continuing=%s use_llm=%s",
            a_id,
            b_id,
            a.get("room_id"),
            b.get("room_id"),
            self._rooms_ok(a, b),
            interaction_text or interaction,
            object_label,
            sequence,
            continuing,
            use_llm,
        )

        dialogue = await render_dialogue(
            profile_a,
            profile_b,
            relationship,
            self._registry if use_llm else None,
            lang,
            a_id,
            b_id,
            max_tokens=self.line_max_tokens,
            extra_a=extra_a,
            extra_b=extra_b,
            name_a=name_a,
            name_b=name_b,
            interaction=interaction,
            interaction_text=interaction_text,
            interaction_sequence=sequence,
            continuing=continuing,
            object_label=object_label,
            # The pair hash + turn index rotates the deterministic lines so a
            # template conversation does not repeat the same line (v0.5 R4).
            seed=f"{min(a_id, b_id)}-{max(a_id, b_id)}-{int(variant)}",
        )

        # v0.5 R5: one grep-able line per rendered dialogue.
        if dialogue is not None:
            logger.info(
                "social render a=%s b=%s source=%s provider=%s model=%s lines=%d "
                "object=%r interaction=%r",
                a_id,
                b_id,
                dialogue.source,
                dialogue.provider or "-",
                dialogue.model or "-",
                len(dialogue.lines),
                object_label,
                interaction_text or interaction,
            )

        # The pair time is recorded once, in ``pick_pairs`` (cooldown authority).
        return dialogue

    async def maybe_dialogue(
        self,
        *,
        player_id: str,
        save_id: str,
        sims: list[dict[str, Any]] | None,
        seated_ids: list[int] | None = None,
        lang: str = "en",
        forge: PairContext | None = None,
    ) -> Dialogue | None:
        """Pick one pair and render a dialogue."""
        pairs = self.pick_pairs(sims, seated_ids)
        if not pairs:
            return None
        a, b = pairs[0]
        return await self._dialogue_for_pair(a, b, player_id=player_id, save_id=save_id, lang=lang, forge=forge)

    async def plan(
        self,
        *,
        player_id: str,
        save_id: str,
        sims: list[dict[str, Any]] | None,
        seated_ids: list[int] | None = None,
        lang: str = "en",
        forge: PairContext | None = None,
    ) -> list[Dialogue]:
        """For each chosen pair render a dialogue; collect non-None dialogues; never raises."""
        dialogues: list[Dialogue] = []
        pairs = self.pick_pairs(sims, seated_ids)
        for a, b in pairs:
            try:
                dlg = await self._dialogue_for_pair(a, b, player_id=player_id, save_id=save_id, lang=lang, forge=forge)
                if dlg is not None:
                    dialogues.append(dlg)
            except Exception:
                # Never raise; continue with other pairs
                continue
        return dialogues

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_pairs": self.max_pairs,
            "pair_cooldown_s": self.pair_cooldown,
            "require_conversation": self.require_conversation,
            "max_pair_distance": self.max_pair_distance,
            "require_same_room": self.require_same_room,
            "keep_open_on_queued": self.keep_open_on_queued,
            "pairs_seen": len(self._last_pair_at),
        }