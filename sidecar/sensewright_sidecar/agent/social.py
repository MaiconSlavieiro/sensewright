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
from .context_forge import PairContext
from .intents import DEFAULT_EXPIRES_AT
from .prompts import strip_thought

logger = logging.getLogger(__name__)

# When the current native interaction cannot be classified, fall back to this.
DEFAULT_TONE = "friendly"

# A native interaction name maps to a dialogue ``(category, tone)`` so the
# interaction the Sims are actually doing shapes what they say (chat -> small
# talk, joke -> funny, flirt -> flirty, insult -> tense). Categories also have
# their own deterministic fallback lines (``social.line.<category>.<n>``).
_INTERACTION_CATEGORIES = (
    ("flirt", "flirty"),
    ("romance", "flirty"),
    ("kiss", "flirty"),
    ("joke", "funny"),
    ("funny", "funny"),
    ("comedy", "funny"),
    ("insult", "tense"),
    ("mean", "tense"),
    ("argue", "tense"),
    ("fight", "tense"),
    ("anger", "tense"),
)

# Deterministic fallback lines live in the ``social.line.<category>.<n>`` content
# keys (en is the source of truth). The LLM path writes in ``lang``; the template
# keeps native mode in-character too.
def classify_interaction(interaction: str) -> tuple[str, str]:
    """Map a native interaction name to a ``(category, tone)`` pair."""
    name = str(interaction or "").lower()
    for token, category in _INTERACTION_CATEGORIES:
        if token in name:
            tone = DEFAULT_TONE if category == "funny" else category
            return category, tone
    return "casual", DEFAULT_TONE


def _dialogue_lines(lang: str, category: str) -> tuple[str, str]:
    return (
        content_i18n.t(lang, f"social.line.{category}.1"),
        content_i18n.t(lang, f"social.line.{category}.2"),
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


def _topic_for(category: str, relationship: dict[str, Any] | None) -> str:
    """Deterministic topic: the interaction category first, then relationship."""
    if category == "flirty":
        return "a flirty exchange"
    if category == "funny":
        return "joking around"
    if category == "tense":
        return "a tense exchange"
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

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable representation."""
        return {
            "a": self.a,
            "b": self.b,
            "lines": list(self.lines),
            "topic": self.topic,
            "source": self.source,
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
) -> Dialogue:
    """Deterministic fallback dialogue (native mode or LLM failure)."""
    name_a = str(name_a or (profile_a or {}).get("name") or f"Sim {a_id}")
    name_b = str(name_b or (profile_b or {}).get("name") or f"Sim {b_id}")

    category, tone = classify_interaction(interaction)
    topic = _topic_for(category, relationship)

    # Two lines, alternating (the spoken words only; the caller attributes them).
    first, second = _dialogue_lines(lang, category)
    lines = [
        {"speaker": "a", "text": first.format(a=name_a, b=name_b), "tone": tone},
        {"speaker": "b", "text": second.format(a=name_a, b=name_b), "tone": tone},
    ]

    return Dialogue(a=a_id, b=b_id, lines=lines, topic=topic, source="template")


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
) -> Dialogue:
    """Render a dialogue via LLM or template fallback.

    ``name_a``/``name_b`` override the profile name (so a Sim with no generated
    profile still speaks under its real ``full_name`` instead of ``Sim <id>``).
    ``interaction`` is the native interaction the pair is doing; it steers the
    dialogue's tone/topic.
    """
    if registry is None:
        return template_dialogue(
            profile_a, profile_b, relationship, a_id, b_id, lang=lang,
            name_a=name_a, name_b=name_b, interaction=interaction,
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

    category, tone = classify_interaction(interaction)
    interaction_desc = ""
    if interaction:
        interaction_desc = (
            f"Native interaction: the two Sims are currently doing "
            f"'{interaction}' ({category} tone). The dialogue must match this "
            "interaction and its mood.\n"
        )

    lang_name = content_i18n.language_name(lang)
    system = (
        "You write short, natural, in-character dialogue between two Sims in "
        f"The Sims 4. Write ALL spoken text in {lang_name} ({lang}). "
        "Reply with STRICT JSON only, no markdown fences, no meta commentary."
    )
    if content_i18n.normalize_lang(lang) != content_i18n.default_lang():
        system += (
            f" The dialogue must be entirely in {lang_name}; do NOT use English."
        )

    user = (
        f"Sim A: {name_a}. {extra_a or ('Personality: ' + (personality_a or 'neutral'))}\n"
        f"Sim B: {name_b}. {extra_b or ('Personality: ' + (personality_b or 'neutral'))}\n"
        f"{rel_desc}\n"
        f"{interaction_desc}\n"
        f"Write a short, natural dialogue (1-2 lines) in {lang_name} as JSON:\n"
        f'{{"topic": "...", "lines": [{{"speaker": "a", "text": "...", "tone": "..."}}, '
        f'{{"speaker": "b", "text": "...", "tone": "..."}}]}}\n'
        f"Rules: max {DIALOGUE_MAX_LINES} lines, alternating speakers, "
        f"each line non-empty, tone is one word (friendly, flirty, tense, casual, warm). "
        f"Use the Sims' names, never numeric ids. "
        f"Every line must be written in {lang_name}. "
        f"No meta commentary. No markdown fences."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    def _fallback() -> Dialogue:
        return template_dialogue(
            profile_a, profile_b, relationship, a_id, b_id, lang=lang,
            name_a=name_a, name_b=name_b, interaction=interaction,
        )

    try:
        response = await registry.complete(messages, lang=lang, max_tokens=max_tokens)
    except Exception as exc:
        logger.warning("social dialogue LLM call failed, using template: %s", exc)
        return _fallback()

    raw = str(getattr(response, "text", "") or "").strip()
    # Strip markdown fences
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return _fallback()

    if not isinstance(data, dict):
        return _fallback()

    topic = str(data.get("topic") or "").strip()
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        return _fallback()

    lines: list[dict[str, Any]] = []
    for item in raw_lines:
        if not isinstance(item, dict):
            continue
        speaker = str(item.get("speaker") or "").strip()
        if speaker not in ("a", "b"):
            continue
        text = clean_line(str(item.get("text") or ""))
        if not text:
            continue
        line_tone = str(item.get("tone") or tone).strip() or tone
        lines.append({"speaker": speaker, "text": text, "tone": line_tone})
        if len(lines) >= DIALOGUE_MAX_LINES:
            break

    if not lines:
        return _fallback()

    if not topic:
        topic = _topic_for(category, relationship)

    return Dialogue(a=a_id, b=b_id, lines=lines, topic=topic, source="llm")


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
        except Exception:
            self.max_pairs = DEFAULT_MAX_PAIRS
            self.pair_cooldown = DEFAULT_PAIR_COOLDOWN_SECONDS
            self.line_max_tokens = 200
            self.require_conversation = True
            self.max_pair_distance = DEFAULT_MAX_PAIR_DISTANCE

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

    async def _dialogue_for_pair(
        self,
        a: dict[str, Any],
        b: dict[str, Any],
        *,
        player_id: str,
        save_id: str,
        lang: str,
        forge: PairContext | None,
    ) -> Dialogue | None:
        """Render a dialogue for a specific pair (a, b)."""
        a_id = int(a.get("sim_id", 0))
        b_id = int(b.get("sim_id", 0))

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
        interaction = str(
            a.get("current_interaction") or b.get("current_interaction") or ""
        ).strip()

        dialogue = await render_dialogue(
            profile_a,
            profile_b,
            relationship,
            self._registry,
            lang,
            a_id,
            b_id,
            max_tokens=self.line_max_tokens,
            extra_a=extra_a,
            extra_b=extra_b,
            name_a=name_a,
            name_b=name_b,
            interaction=interaction,
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
            "pairs_seen": len(self._last_pair_at),
        }