"""Conversation sessions: multi-turn exchanges + closing summary (v0.4 P4/P4b).

The v0.3 social channel produced an isolated two-line exchange per pulse. v0.4
keeps a *session* per pair: successive renditions continue the same topic until
``max_turns`` lines are reached, then the session closes with a one-line summary
(narrator style). A session also closes early — with a "goodbye" summary — when
the two Sims stop their native conversation.

Rendering stays in ``social.render_dialogue``; this module is the stateful
bookkeeping around it and never talks to the game directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .. import content_i18n

logger = logging.getLogger(__name__)

# Tones that have a localized ``conversation.end.<tone>`` line; others fall back.
_TONES = ("casual", "friendly", "warm", "flirty", "funny", "tense")


@dataclass
class Session:
    """One multi-turn conversation between two Sims."""

    a: int
    b: int
    topic: str = ""
    tone: str = "friendly"
    lines: list[dict[str, Any]] = field(default_factory=list)
    turns: int = 0
    exchanges: int = 0
    a_name: str = ""
    b_name: str = ""
    interaction_text: str = ""
    started_at: float = 0.0
    last_at: float = 0.0
    # v0.5 R3: signature of the interaction/queue at the last turn, so a new
    # turn only happens when the pair's native action changed (or the interval
    # elapsed), never once per zone pulse.
    last_signature: str = ""

    @property
    def key(self) -> frozenset[int]:
        return frozenset({self.a, self.b})

    def to_dict(self) -> dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "topic": self.topic,
            "tone": self.tone,
            "lines": list(self.lines),
            "turns": self.turns,
            "exchanges": self.exchanges,
            "a_name": self.a_name,
            "b_name": self.b_name,
            "interaction_text": self.interaction_text,
        }


class ConversationManager:
    """Tracks conversation sessions across zone pulses."""

    def __init__(
        self,
        settings: Any = None,
        *,
        registry: Any = None,
        clock: Any = None,
    ) -> None:
        self._registry = registry
        self._clock = clock or (lambda: 0.0)
        self.enabled = True
        self.max_turns = 4
        self.max_tokens = 220
        self.summary_enabled = True
        self.leaving_summary = True
        self.idle_seconds = 300.0
        self.turn_min_interval = 25.0
        self._sessions: dict[frozenset[int], Session] = {}
        self._completed = 0
        self._summaries = 0
        if settings is not None:
            self.configure(settings)

    def configure(self, settings: Any) -> None:
        try:
            cfg = getattr(getattr(settings, "agents", None), "conversations", None)
        except Exception:
            cfg = None
        if cfg is None:
            return
        self.enabled = bool(getattr(cfg, "enabled", True))
        self.max_turns = max(2, int(getattr(cfg, "max_turns", 4) or 4))
        self.max_tokens = max(32, int(getattr(cfg, "max_tokens", 220) or 220))
        self.summary_enabled = bool(getattr(cfg, "summary_enabled", True))
        self.leaving_summary = bool(getattr(cfg, "leaving_summary", True))
        self.idle_seconds = max(0.0, float(getattr(cfg, "idle_seconds", 300.0) or 0.0))
        social_cfg = getattr(getattr(settings, "agents", None), "social", None)
        self.turn_min_interval = max(
            0.0, float(getattr(social_cfg, "turn_min_interval_seconds", 25.0) or 0.0)
        )

    def set_registry(self, registry: Any) -> None:
        self._registry = registry

    def is_active(self, a: int, b: int) -> bool:
        return frozenset({int(a), int(b)}) in self._sessions

    def turns_for(self, a: int, b: int) -> int:
        """Lines already spoken in the pair's open session (0 when none)."""
        session = self._sessions.get(frozenset({int(a), int(b)}))
        return int(session.turns) if session else 0

    def should_turn(
        self,
        a: int,
        b: int,
        signature: str,
        *,
        now: float | None = None,
    ) -> tuple[bool, str]:
        """Turn pacing (v0.5 R3): render only on change or after the interval.

        Returns ``(allowed, reason)`` where ``reason`` is ``new``/``changed``/
        ``interval`` when allowed and ``interval`` when the pulse arrived too
        soon for the same interaction/queue.
        """
        key = frozenset({int(a), int(b)})
        session = self._sessions.get(key)
        if session is None:
            return True, "new"
        if signature and signature != session.last_signature:
            return True, "changed"
        if self.turn_min_interval <= 0:
            return True, "interval"
        reference = self._clock() if now is None else float(now)
        if (reference - session.last_at) >= self.turn_min_interval:
            return True, "interval"
        return False, "interval"

    def record(
        self,
        dialogue: Any,
        *,
        a_name: str = "",
        b_name: str = "",
        interaction_text: str = "",
        signature: str = "",
        now: float | None = None,
    ) -> Session | None:
        """Append one rendered dialogue to its session; close it when full.

        Returns the closed ``Session`` (to summarize) or ``None`` when the
        session is still open. Never raises.
        """
        try:
            a = int(getattr(dialogue, "a", 0) or 0)
            b = int(getattr(dialogue, "b", 0) or 0)
        except (TypeError, ValueError):
            return None
        if a == b:
            return None
        reference = self._clock() if now is None else float(now)
        key = frozenset({a, b})
        session = self._sessions.get(key)
        if session is None:
            session = Session(a=a, b=b, started_at=reference)
            self._sessions[key] = session

        lines = list(getattr(dialogue, "lines", ()) or ())
        session.lines.extend(lines)
        session.turns += len(lines)
        session.exchanges += 1
        session.last_at = reference
        session.topic = str(getattr(dialogue, "topic", "") or session.topic or "")
        session.a_name = a_name or session.a_name
        session.b_name = b_name or session.b_name
        session.interaction_text = interaction_text or session.interaction_text
        session.last_signature = signature or session.last_signature
        if lines:
            session.tone = str(lines[-1].get("tone") or session.tone or "friendly")

        if session.turns >= self.max_turns:
            self._sessions.pop(key, None)
            self._completed += 1
            return session
        return None

    def sweep(
        self,
        active_pairs: set[frozenset[int]] | None,
        *,
        now: float | None = None,
    ) -> list[Session]:
        """Close sessions whose pair stopped conversing or went idle too long."""
        reference = self._clock() if now is None else float(now)
        active = active_pairs or set()
        closed: list[Session] = []
        for key, session in list(self._sessions.items()):
            idle = self.idle_seconds > 0 and (reference - session.last_at) > self.idle_seconds
            if key in active and not idle:
                continue
            reason = "idle" if idle else "left"
            self._sessions.pop(key, None)
            self._completed += 1
            logger.info(
                "conversation close reason=%s a=%s b=%s turns=%d",
                reason,
                session.a,
                session.b,
                session.turns,
            )
            closed.append(session)
        return closed

    def summary_line(self, session: Session, *, lang: str, leaving: bool = False) -> str:
        """Deterministic, localized summary of a closed session."""
        if leaving and self.leaving_summary:
            name = session.a_name or f"Sim {session.a}"
            other = session.b_name or f"Sim {session.b}"
            return content_i18n.t(lang, "conversation.leave", name=name, other=other)
        tone = session.tone if session.tone in _TONES else "casual"
        topic = session.topic or content_i18n.t(lang, "conversation.topic.default")
        a = session.a_name or f"Sim {session.a}"
        b = session.b_name or f"Sim {session.b}"
        return content_i18n.t(
            lang, f"conversation.end.{tone}", a=a, b=b, topic=topic
        )

    async def summarize(
        self,
        session: Session,
        *,
        lang: str,
        leaving: bool = False,
    ) -> str:
        """One cheap LLM summary with a deterministic localized fallback."""
        fallback = self.summary_line(session, lang=lang, leaving=leaving)
        if not self.summary_enabled or self._registry is None:
            return fallback
        spoken = [
            str(line.get("text") or "")
            for line in session.lines
            if isinstance(line, dict) and line.get("text")
        ]
        if not spoken:
            return fallback
        from ..llm import langguard
        from .prompts import strip_thought

        nickname = session.a_name or f"Sim {session.a}"
        other = session.b_name or f"Sim {session.b}"
        system = (
            "You summarize a short conversation between two Sims in The Sims 4. "
            + langguard.language_directive(lang)
            + " Reply with ONE short narrator sentence (max 20 words), no quotes, no names in ALL CAPS."
        )
        user = (
            f"{nickname} and {other} talked about {session.topic or 'small things'}. "
            f"Spoken lines: " + " | ".join(strip_thought(text) for text in spoken[:6])
        )
        try:
            response = await self._registry.complete(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                lang=lang,
                max_tokens=80,
                purpose="summary",
            )
        except Exception as exc:
            logger.warning("conversation summary LLM failed, using fallback: %s", exc)
            return fallback
        text = str(getattr(response, "text", "") or "").strip()
        if not text or langguard.is_wrong_lang(text, lang):
            return fallback
        self._summaries += 1
        return text

    def snapshot(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_turns": self.max_turns,
            "turn_min_interval_s": self.turn_min_interval,
            "active_sessions": len(self._sessions),
            "completed": self._completed,
            "summaries": self._summaries,
        }
