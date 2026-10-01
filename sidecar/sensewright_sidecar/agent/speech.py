"""SpeechPolicy: what vocal output exists and what may surface (v0.4 P1).

Before v0.4 the idle impulse could emit a "spoken" line, so the player saw
random monologues. SpeechPolicy classifies every vocal output and gates the
surfacing:

- ``inner_thought`` — private reasoning; recorded as a memory event, never shown.
- ``murmur`` — a discreet devaneio; occasional, only near the active Sim.
- ``directed`` — speech aimed at another Sim (conversation / reaction with target).
- ``reaction`` — a voiced reaction to a salient event.

It also enforces a per-Sim minimum interval between surfaced lines and a global
per-minute ceiling, so the player is never spammed.
"""

from __future__ import annotations

import logging
import random
import time
from collections import deque
from typing import Any

logger = logging.getLogger(__name__)

INNER_THOUGHT = "inner_thought"
MURMUR = "murmur"
DIRECTED = "directed"
REACTION = "reaction"

_KINDS = (INNER_THOUGHT, MURMUR, DIRECTED, REACTION)

_DEFAULT_MIN_INTERVAL = 30.0
_DEFAULT_MAX_PER_MINUTE = 12
_DEFAULT_AMBIENT_CHANCE = 0.08
_DEFAULT_MURMUR_COOLDOWN = 120.0
_DEFAULT_NOTIFY_THOUGHTS = True
_DEFAULT_HEARING_RADIUS = 20.0


class SpeechPolicy:
    """Cadence + surfacing rules shared by every speech surface."""

    def __init__(
        self,
        settings: Any = None,
        *,
        clock: Any = None,
        rng: Any = None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._rng = rng or random.Random()
        self.min_interval = _DEFAULT_MIN_INTERVAL
        self.max_per_minute = _DEFAULT_MAX_PER_MINUTE
        self.ambient_talk_chance = _DEFAULT_AMBIENT_CHANCE
        self.murmur_cooldown = _DEFAULT_MURMUR_COOLDOWN
        self.notify_thoughts = _DEFAULT_NOTIFY_THOUGHTS
        self.hearing_radius = _DEFAULT_HEARING_RADIUS
        self._last_line_at: dict[str, float] = {}
        self._last_murmur_at: dict[str, float] = {}
        self._window: deque[float] = deque()
        self._stats = {"surfaced": 0, "suppressed": 0, "thoughts": 0, "murmurs": 0}
        if settings is not None:
            self.configure(settings)

    def configure(self, settings: Any) -> None:
        """Read ``settings.agents.speech`` defensively."""
        try:
            speech = getattr(getattr(settings, "agents", None), "speech", None)
        except Exception:
            speech = None
        if speech is None:
            return
        self.min_interval = max(
            0.0, float(getattr(speech, "min_interval_between_lines", _DEFAULT_MIN_INTERVAL))
        )
        self.max_per_minute = max(
            1, int(getattr(speech, "max_lines_per_minute", _DEFAULT_MAX_PER_MINUTE))
        )
        self.ambient_talk_chance = min(
            1.0, max(0.0, float(getattr(speech, "ambient_talk_chance", _DEFAULT_AMBIENT_CHANCE)))
        )
        self.murmur_cooldown = max(
            0.0, float(getattr(speech, "murmur_cooldown_seconds", _DEFAULT_MURMUR_COOLDOWN))
        )
        self.notify_thoughts = bool(
            getattr(speech, "notify_thoughts", _DEFAULT_NOTIFY_THOUGHTS)
        )
        self.hearing_radius = max(
            0.0, float(getattr(speech, "hearing_radius", _DEFAULT_HEARING_RADIUS))
        )

    # ── classification ────────────────────────────────────────────────
    @staticmethod
    def classify(
        *,
        job_kind: str = "idle",
        has_target: bool = False,
        intent_kind: str = "",
    ) -> str:
        """Classify one vocal output from its context."""
        if not has_target:
            if job_kind == "reaction":
                return REACTION
            if intent_kind == "speak":
                # A "speak" with no target is an ambient murmur, not a monologue.
                return MURMUR
            return MURMUR
        if job_kind == "reaction":
            return REACTION
        if intent_kind == "speak":
            return DIRECTED
        return DIRECTED

    # ── surfacing ─────────────────────────────────────────────────────
    def within_hearing(self, distance: float | None) -> bool:
        """True when a line is close enough to the active Sim to be heard."""
        if self.hearing_radius <= 0.0:
            return True
        if distance is None:
            return True
        return distance <= self.hearing_radius

    def _within_rate(self, now: float) -> bool:
        cutoff = now - 60.0
        while self._window and self._window[0] < cutoff:
            self._window.popleft()
        return len(self._window) < self.max_per_minute

    def should_surface(
        self,
        sim_key: str,
        *,
        kind: str,
        distance: float | None = None,
        now: float | None = None,
    ) -> bool:
        """Decide whether one classified line reaches the player."""
        if kind == INNER_THOUGHT:
            self._stats["thoughts"] += 1
            # Thoughts are always internal; ``notify_thoughts`` only affects murmurs.
            self._stats["suppressed"] += 1
            return False
        if not self.within_hearing(distance):
            self._stats["suppressed"] += 1
            return False
        reference = self._clock() if now is None else float(now)
        if kind == MURMUR:
            self._stats["murmurs"] += 1
            if not self.notify_thoughts:
                self._stats["suppressed"] += 1
                return False
            last = self._last_murmur_at.get(sim_key)
            if last is not None and reference - last < self.murmur_cooldown:
                self._stats["suppressed"] += 1
                return False
            if self._rng.random() > self.ambient_talk_chance:
                self._stats["suppressed"] += 1
                return False
        last_line = self._last_line_at.get(sim_key)
        if last_line is not None and reference - last_line < self.min_interval:
            self._stats["suppressed"] += 1
            return False
        if not self._within_rate(reference):
            self._stats["suppressed"] += 1
            return False
        return True

    def note(self, sim_key: str, *, kind: str, now: float | None = None) -> None:
        """Record that a line surfaced (advances cadence windows)."""
        reference = self._clock() if now is None else float(now)
        self._last_line_at[sim_key] = reference
        if kind == MURMUR:
            self._last_murmur_at[sim_key] = reference
        self._window.append(reference)
        self._stats["surfaced"] += 1

    def log_line(
        self,
        *,
        sim_id: int,
        kind: str,
        surfaced: bool,
        lang: str,
        distance: float | None = None,
    ) -> None:
        """Emit the v0.4 validation line (gated by the caller's logger level)."""
        dist = "?" if distance is None else f"{distance:.1f}"
        logger.info(
            "[validate] speech: sim=%s kind=%s surfaced=%s lang=%s dist=%s",
            sim_id,
            kind,
            surfaced,
            lang,
            dist,
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "min_interval": self.min_interval,
            "max_per_minute": self.max_per_minute,
            "ambient_talk_chance": self.ambient_talk_chance,
            "notify_thoughts": self.notify_thoughts,
            "hearing_radius": self.hearing_radius,
            "surfaced": self._stats["surfaced"],
            "suppressed": self._stats["suppressed"],
            "thoughts": self._stats["thoughts"],
            "murmurs": self._stats["murmurs"],
        }
