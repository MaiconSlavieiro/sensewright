"""Social layer (L6, v0.3 R5): sim<->sim dialogue channel.

Two agent-owned Sims get a real conversation. The layer picks disjoint pairs of
non-player Sims, builds a PairContext, and renders a short dialogue (template or
LLM). The resulting Dialogue carries two "speak" intents so the mod's GameLever
and the legacy /v1/autonomy/directives alias keep working.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from .context_forge import PairContext
from .intents import DEFAULT_EXPIRES_AT

logger = logging.getLogger(__name__)

# Deterministic fallback lines, per language (en is the source of truth). The
# LLM path writes in ``lang``; the template keeps native mode in-character too.
_TEMPLATE_LINES = {
    "en": (
        "Hey {b}! It's good to see you.",
        "Hey {a}! I've been meaning to catch up.",
    ),
    "pt-BR": (
        "Oi {b}! Que bom te ver.",
        "Oi {a}! Eu estava querendo te encontrar.",
    ),
}


def _template_lines(lang: str) -> tuple[str, str]:
    return _TEMPLATE_LINES.get(lang) or _TEMPLATE_LINES["en"]


DEFAULT_MAX_PAIRS = 1
DEFAULT_PAIR_COOLDOWN_SECONDS = 180.0
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
    t = text.strip()
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
) -> Dialogue:
    """Deterministic fallback dialogue (native mode or LLM failure)."""
    name_a = str((profile_a or {}).get("name") or f"Sim {a_id}")
    name_b = str((profile_b or {}).get("name") or f"Sim {b_id}")

    rel_type = (relationship or {}).get("type") if relationship else None
    rel_level = (relationship or {}).get("level") if relationship else None

    # Simple topic based on relationship
    if rel_type == "romantic":
        topic = "a quiet moment together"
    elif rel_type == "family":
        topic = "family matters"
    elif rel_type == "friend":
        topic = "catching up"
    elif rel_level is not None and rel_level < 0:
        topic = "a tense exchange"
    else:
        topic = "small talk"

    # Two lines, alternating (the spoken words only; the caller attributes them).
    first, second = _template_lines(lang)
    lines = [
        {"speaker": "a", "text": first.format(a=name_a, b=name_b), "tone": "friendly"},
        {"speaker": "b", "text": second.format(a=name_a, b=name_b), "tone": "friendly"},
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
) -> Dialogue:
    """Render a dialogue via LLM or template fallback."""
    if registry is None:
        return template_dialogue(profile_a, profile_b, relationship, a_id, b_id, lang=lang)

    name_a = str((profile_a or {}).get("name") or f"Sim {a_id}")
    name_b = str((profile_b or {}).get("name") or f"Sim {b_id}")

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

    system = (
        f"You are writing a brief dialogue between two Sims in The Sims 4. "
        f"Reply in {lang} with STRICT JSON only."
    )
    user = (
        f"Sim A: {name_a}. Personality: {personality_a or 'neutral'}.\n"
        f"Sim B: {name_b}. Personality: {personality_b or 'neutral'}.\n"
        f"{rel_desc}\n\n"
        f"Write a short, natural dialogue (1-2 lines) as JSON:\n"
        f'{{"topic": "...", "lines": [{{"speaker": "a", "text": "...", "tone": "..."}}, '
        f'{{"speaker": "b", "text": "...", "tone": "..."}}]}}\n'
        f"Rules: max {DIALOGUE_MAX_LINES} lines, alternating speakers, "
        f"each line non-empty, tone is one word (friendly, flirty, tense, casual, warm). "
        f"No meta commentary. No markdown fences."
    )

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    try:
        response = await registry.complete(messages, lang=lang, max_tokens=max_tokens)
    except Exception as exc:
        logger.warning("social dialogue LLM call failed, using template: %s", exc)
        return template_dialogue(profile_a, profile_b, relationship, a_id, b_id, lang=lang)

    raw = str(getattr(response, "text", "") or "").strip()
    # Strip markdown fences
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()

    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return template_dialogue(profile_a, profile_b, relationship, a_id, b_id, lang=lang)

    if not isinstance(data, dict):
        return template_dialogue(profile_a, profile_b, relationship, a_id, b_id, lang=lang)

    topic = str(data.get("topic") or "").strip()
    raw_lines = data.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        return template_dialogue(profile_a, profile_b, relationship, a_id, b_id, lang=lang)

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
        tone = str(item.get("tone") or "friendly").strip() or "friendly"
        lines.append({"speaker": speaker, "text": text, "tone": tone})
        if len(lines) >= DIALOGUE_MAX_LINES:
            break

    if not lines:
        return template_dialogue(profile_a, profile_b, relationship, a_id, b_id, lang=lang)

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
        self.line_max_tokens = 200
        if settings is not None:
            self.configure(settings)

    def configure(self, settings: Any) -> None:
        """Read settings.agents.layers.social (enable) and settings.agents.social (max_pairs_per_tick, pair_cooldown_seconds) defensively."""
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
        except Exception:
            self.max_pairs = DEFAULT_MAX_PAIRS
            self.pair_cooldown = DEFAULT_PAIR_COOLDOWN_SECONDS
            self.line_max_tokens = 200

        # Ensure sensible bounds
        self.max_pairs = max(1, self.max_pairs)
        self.pair_cooldown = max(0.0, self.pair_cooldown)
        self.line_max_tokens = max(1, self.line_max_tokens)

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
        # Filter out player Sims (PLANO §15.8 R5: two agent-owned Sims)
        non_player = [s for s in eligible if not s.get("is_player")]
        if len(non_player) < 2:
            return []

        # Sort for determinism, then shuffle with rng
        non_player.sort(key=lambda s: int(s.get("sim_id", 0)))
        if self._rng is not None:
            try:
                self._rng.shuffle(non_player)
            except Exception:
                pass

        now_ts = now if now is not None else self._clock()
        pairs: list[tuple[dict, dict]] = []
        used: set[int] = set()

        for i in range(len(non_player)):
            if len(pairs) >= self.max_pairs:
                break
            a = non_player[i]
            a_id = int(a.get("sim_id", 0))
            if a_id in used:
                continue
            for j in range(i + 1, len(non_player)):
                if len(pairs) >= self.max_pairs:
                    break
                b = non_player[j]
                b_id = int(b.get("sim_id", 0))
                if b_id in used:
                    continue
                pair_key = frozenset({a_id, b_id})
                last = self._last_pair_at.get(pair_key, 0.0)
                if now_ts - last < self.pair_cooldown:
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

        dialogue = await render_dialogue(
            profile_a,
            profile_b,
            relationship,
            self._registry,
            lang,
            a_id,
            b_id,
            max_tokens=self.line_max_tokens,
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
            "pairs_seen": len(self._last_pair_at),
        }