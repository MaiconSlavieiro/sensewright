"""God agent orchestrator.

The orchestrator is the decision tier of the God agent (``PLANO.md`` §8.3 and
Phase 5c): on each tick it reads the world model, applies the configured dials
(preset, intervention frequency, intensity, autonomy/chaos degrees and the power
toggles), picks at most one eligible intervention from the preset deck and turns
it into a ``Directive``. When a LLM provider is available it also asks for a
short in-character narration; otherwise it falls back to the deterministic deck
description, so the tier works in native (0-key) mode too.

It never executes anything: the directive carries an optional ``tool_call`` the
mod executes and, for world/knowledge events the mod has no tool for yet, stays
as a broadcast event (``source=god``).
"""

from __future__ import annotations

import logging
import random
import time
from typing import Any
from uuid import uuid4

from ..config import GodConfig, Settings
from .interventions import Intervention, get_interventions_for_preset, get_preset
from .world_model import Directive, SimProfile, WorldState

logger = logging.getLogger(__name__)

# Shortest gap between two God interventions (seconds) and the slowest cadence
# (10 minutes) the frequency slider can reach, matching §14.2's "1-10 min" loop.
MIN_INTERVAL_SECONDS = 30.0
BASE_INTERVAL_SECONDS = 600.0

# Intervention types that get a boost as chaos rises.
CHAOTIC_TYPES = frozenset({"extreme_event", "spawn_npc"})

# Directive type -> power toggle key.
_POWER_FOR_TYPE = {
    "spawn_npc": "spawn_npc",
    "apply_trait": "apply_trait",
    "force_social": "force_social",
    "gossip": "gossip",
    "relationship_shift": "relationship_shift",
    "extreme_event": "extreme_events",
}

# Interventions that only make sense with at least one Sim around.
_NEEDS_SIMS = frozenset({"force_social", "gossip", "relationship_shift"})

_NARRATION_PROMPT = (
    "You are the unseen narrator of a Sims 4 neighborhood. In one short sentence "
    "({lang}), describe this story beat as it happens, staying consistent with the "
    "neighborhood mood. No lists, no quotes, no preamble.\n\n"
    "Beat: {description}\nPreset: {preset}"
)


def _coerce_god_config(config: Any) -> GodConfig:
    """Accept ``Settings``, ``GodConfig``, a dict or ``None``."""
    if config is None:
        return GodConfig()
    if isinstance(config, GodConfig):
        return config
    if isinstance(config, Settings):
        return config.god
    if isinstance(config, dict):
        try:
            return GodConfig(**config)
        except Exception:
            return GodConfig()
    god = getattr(config, "god", None)
    if god is not None:
        return god
    return GodConfig()


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class GodOrchestrator:
    """Periodic decision loop that issues God directives from the deck."""

    def __init__(
        self,
        config: Any = None,
        *,
        registry: Any = None,
        rng: random.Random | None = None,
        clock: Any = None,
        lang: str = "en",
    ) -> None:
        self._registry = registry
        self._rng = rng or random.Random()
        self._clock = clock or time.monotonic
        self._lang = lang
        self._last_intervention_at: float | None = None
        self._last_by_intervention: dict[str, float] = {}
        self._directives: list[Directive] = []
        self.configure(config)

    # ─── configuration ────────────────────────────────────────────────

    def configure(self, config: Any, *, lang: str | None = None) -> GodOrchestrator:
        """(Re)apply the God dials."""
        cfg = _coerce_god_config(config)
        self.enabled = cfg.enabled
        self.preset = cfg.preset
        self.intervention_frequency = cfg.intervention_frequency
        self.intensity = cfg.intensity
        self.autonomy_degree = cfg.autonomy_degree
        self.chaos_degree = cfg.chaos_degree
        self.mood_influence = cfg.mood_influence
        self.base_interval_seconds = getattr(cfg, "base_interval_seconds", BASE_INTERVAL_SECONDS)

        # The preset fills any power the player did not set explicitly.
        preset = get_preset(self.preset) or {}
        powers = dict(preset.get("powers") or {})
        powers.update(cfg.powers or {})
        self.powers = powers

        if lang is not None:
            self._lang = lang
        return self

    def set_registry(self, registry: Any) -> None:
        """Attach (or clear) the LLM registry used for narration."""
        self._registry = registry

    def status(self) -> dict[str, Any]:
        """Return a JSON-serializable status snapshot."""
        preset = get_preset(self.preset) or {}
        return {
            "enabled": self.enabled,
            "preset": self.preset,
            "preset_name": preset.get("name", self.preset),
            "intervention_frequency": self.intervention_frequency,
            "intensity": self.intensity,
            "autonomy_degree": self.autonomy_degree,
            "chaos_degree": self.chaos_degree,
            "powers": dict(self.powers),
            "min_interval_s": round(self._min_interval(), 1),
            "pending_directives": len(self.get_pending_directives()),
            "last_intervention_at": self._last_intervention_at,
        }

    # ─── decision loop ────────────────────────────────────────────────

    async def maybe_intervene(
        self,
        world_state: WorldState,
        *,
        lang: str | None = None,
    ) -> list[Directive]:
        """Return zero or one new directive for this tick."""
        directive = self._select(world_state)
        if directive is None:
            return []

        target_lang = lang or self._lang
        if self._registry is not None:
            narration = await self._narrate(directive, target_lang)
            if narration:
                directive.narration = narration

        self._directives.append(directive)
        return [directive]

    def played_ids(self, world_state: WorldState) -> set[str]:
        """Return the ids of player-owned Sims (never God-controlled, ``§14.5``)."""
        return world_state.played_ids()

    def _select(self, world_state: WorldState) -> Directive | None:
        if not self.enabled or self.intervention_frequency <= 0.0:
            return None

        now = self._clock()
        if not self._due(now):
            return None

        played = self.played_ids(world_state)
        # Single-writer jurisdiction: when every Sim in the world is played there is
        # no unplayed target, so the God stays silent instead of touching a player.
        if world_state.sims and len(played) == len(world_state.sims):
            logger.debug("God scoping: no unplayed sims, skipping tick")
            return None

        candidates = self._eligible(world_state, now)
        if not candidates:
            return None

        intervention = self._weighted_choice(candidates)
        target = self._pick_target(world_state, intervention)
        if target is not None and target.sim_id in played:
            logger.debug(f"God scoping: skipping {intervention.id} on played sim {target.sim_id}")
            return None
        if intervention.type in _NEEDS_SIMS and target is None:
            return None

        directive = self._build_directive(intervention, target, now)
        self._last_intervention_at = now
        self._last_by_intervention[intervention.id] = now
        return directive

    def _due(self, now: float) -> bool:
        if self._last_intervention_at is None:
            return True
        return (now - self._last_intervention_at) >= self._min_interval()

    def _min_interval(self) -> float:
        freq = min(1.0, max(0.0, self.intervention_frequency))
        autonomy = min(1.0, max(0.0, self.autonomy_degree))
        gap = self.base_interval_seconds * (1.0 - freq) * (1.0 - 0.5 * autonomy)
        return max(MIN_INTERVAL_SECONDS, gap)

    def _eligible(self, world_state: WorldState, now: float) -> list[Intervention]:
        has_sims = bool(world_state.sims)
        eligible: list[Intervention] = []
        for intervention in get_interventions_for_preset(self.preset, self.intensity):
            if not self._power_allows(intervention.type):
                continue
            if intervention.type in _NEEDS_SIMS and not has_sims:
                continue
            last = self._last_by_intervention.get(intervention.id)
            if last is not None and (now - last) < intervention.cooldown_seconds:
                continue
            eligible.append(intervention)
        return eligible

    def _power_allows(self, intervention_type: str) -> bool:
        key = _POWER_FOR_TYPE.get(intervention_type)
        if key is None:
            return True
        return bool(self.powers.get(key, True))

    def _weight(self, intervention: Intervention) -> float:
        weight = max(0.0, intervention.weight)
        if self.chaos_degree >= 0.5 and intervention.type in CHAOTIC_TYPES:
            weight *= 1.0 + self.chaos_degree
        return weight

    def _weighted_choice(self, candidates: list[Intervention]) -> Intervention:
        weights = [self._weight(intervention) for intervention in candidates]
        total = sum(weights)
        if total <= 0.0:
            return candidates[0]
        roll = self._rng.random() * total
        upto = 0.0
        for intervention, weight in zip(candidates, weights):
            upto += weight
            if roll <= upto:
                return intervention
        return candidates[-1]

    # ─── target + directive building ──────────────────────────────────

    def _pick_target(self, world_state: WorldState, intervention: Intervention) -> SimProfile | None:
        # ``candidates()`` falls back to all Sims when none are unplayed; filter so a
        # played Sim can never be chosen for control (single-writer, ``§14.5``).
        pool = [sim for sim in world_state.candidates() if not sim.is_player]
        if not pool:
            return None
        if intervention.type in ("force_social", "gossip", "relationship_shift"):
            with_relationships = [sim for sim in pool if sim.relationships]
            if with_relationships:
                pool = with_relationships
        return self._rng.choice(pool)

    def _partner_for(self, sim: SimProfile) -> str | None:
        """Pick a partner Sim id from the target's relationships."""
        if not sim.relationships:
            return None
        return self._rng.choice(sorted(sim.relationships))

    def _build_directive(
        self,
        intervention: Intervention,
        target: SimProfile | None,
        now: float,
    ) -> Directive:
        payload = dict(intervention.payload_template or {})
        return Directive(
            id=f"god-{uuid4().hex[:8]}",
            type=intervention.type,
            target_sim=target.sim_id if target else None,
            payload=payload,
            priority=1,
            created_at=now,
            narration=intervention.description,
            tool_call=self._map_tool_call(intervention, target, payload),
        )

    def _map_tool_call(
        self,
        intervention: Intervention,
        target: SimProfile | None,
        payload: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Map an intervention to a mod tool call when the mod can execute it.

        Interventions with no game tool yet (spawn_npc, relationship_shift,
        extreme_event) stay as broadcast world events.
        """
        if target is None:
            return None
        sim_id = _as_int(target.sim_id)
        reason = intervention.description

        if intervention.type == "apply_trait":
            trait = str(payload.get("trait", "")).strip()
            if not trait:
                return None
            duration = str(payload.get("duration", "permanent")).lower()
            if duration in ("permanent", "long"):
                return {"name": "add_trait", "args": {"sim_id": sim_id, "trait_name": trait, "reason": reason}}
            return {"name": "add_buff", "args": {"sim_id": sim_id, "buff_name": trait, "reason": reason}}

        if intervention.type == "force_social":
            args: dict[str, Any] = {
                "sim_id": sim_id,
                "interaction_name": str(payload.get("interaction", "chat")),
                "reason": reason,
            }
            partner = self._partner_for(target)
            if partner is not None:
                args["target_sim_id"] = _as_int(partner)
            return {"name": "queue_interaction", "args": args}

        if intervention.type == "gossip":
            partner = self._partner_for(target)
            if partner is None:
                return None
            return {
                "name": "say_to",
                "args": {
                    "sim_id": sim_id,
                    "target_sim_id": _as_int(partner),
                    "message": str(payload.get("topic", "gossip")),
                    "tone": "serious",
                    "reason": reason,
                },
            }

        return None

    # ─── optional LLM narration ───────────────────────────────────────

    async def _narrate(self, directive: Directive, lang: str) -> str:
        registry = self._registry
        if registry is None:
            return ""
        try:
            messages = [
                {
                    "role": "system",
                    "content": _NARRATION_PROMPT.format(
                        lang=lang,
                        description=directive.narration,
                        preset=self.preset,
                    ),
                },
                {"role": "user", "content": directive.type},
            ]
            response = await registry.complete(messages, lang=lang, max_tokens=80)
            return (getattr(response, "text", "") or "").strip()
        except Exception as exc:
            logger.debug(f"God narration failed: {exc}")
            return ""

    # ─── directive bookkeeping ────────────────────────────────────────

    def add_directive(self, directive: Directive) -> None:
        """Add a directive to the queue."""
        self._directives.append(directive)

    def get_pending_directives(self) -> list[Directive]:
        """Get all pending directives."""
        return [directive for directive in self._directives if directive.status == "pending"]

    def mark_directive_done(self, directive_id: str, success: bool = True) -> bool:
        """Mark a directive as done or failed."""
        for directive in self._directives:
            if directive.id == directive_id:
                directive.status = "done" if success else "failed"
                return True
        return False
