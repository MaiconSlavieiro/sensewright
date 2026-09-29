"""God agent world model.

The world model is the read-only picture of the neighborhood the God agent
reasons over: who lives there, how they relate, and the coarse world context
(time of day, lot type, funds). It is built from the census the mod pushes on
zone load (``POST /v1/census``) and from memory. It never holds psyches or
secrets - only the public, native state (see ``PLANO.md`` §8 and §14.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# Mood tags that, when present, contribute to the aggregate tension signal.
_NEGATIVE_MOODS = frozenset(
    {
        "angry",
        "enraged",
        "furious",
        "irritated",
        "frustrated",
        "stressed",
        "tense",
        "embarrassed",
        "uncomfortable",
        "sad",
    }
)


@dataclass
class SimProfile:
    """Lightweight Sim profile for the world model (public state only)."""

    sim_id: str
    name: str = ""
    traits: list[str] = field(default_factory=list)
    mood: str = "neutral"
    location: str = ""
    relationships: dict[str, float] = field(default_factory=dict)  # target_sim_id -> sentiment
    is_player: bool = False

    @classmethod
    def from_census_sim(cls, data: dict[str, Any]) -> SimProfile:
        """Build a profile from one ``CensusSim`` payload (``model_dump``)."""
        relationships: dict[str, float] = {}
        for rel in data.get("relationships") or []:
            if not isinstance(rel, dict):
                continue
            target = rel.get("target_id", rel.get("target_sim_id", rel.get("sim_id")))
            if target is None:
                continue
            relationships[str(target)] = _as_float(rel.get("depth", rel.get("value", 0.0)))

        return cls(
            sim_id=str(data.get("sim_id", "")),
            name=str(data.get("full_name") or ""),
            traits=[str(trait) for trait in data.get("traits") or []],
            mood=str(data.get("mood") or "neutral"),
            location=str(data.get("location") or ""),
            relationships=relationships,
            is_player=bool(data.get("is_player", False)),
        )


@dataclass
class WorldState:
    """Snapshot of the world for the God agent."""

    sims: dict[str, SimProfile] = field(default_factory=dict)
    active_events: list[dict[str, Any]] = field(default_factory=list)
    time_of_day: str = "unknown"
    lot_type: str = "residential"
    household_funds: int = 0

    @classmethod
    def from_census(
        cls,
        census: dict[str, Any] | None,
        *,
        time_of_day: str = "unknown",
        lot_type: str = "residential",
    ) -> WorldState:
        """Build a world snapshot from the cached census payload."""
        state = cls(time_of_day=time_of_day or "unknown", lot_type=lot_type or "residential")
        if not isinstance(census, dict):
            return state

        for sim_data in census.get("sims") or []:
            if not isinstance(sim_data, dict):
                continue
            profile = SimProfile.from_census_sim(sim_data)
            if profile.sim_id:
                state.sims[profile.sim_id] = profile

        funds = 0
        for household in census.get("households") or []:
            if not isinstance(household, dict):
                continue
            try:
                funds += int(household.get("funds", 0) or 0)
            except (TypeError, ValueError):
                continue
        state.household_funds = funds
        return state

    def sims_list(self) -> list[SimProfile]:
        """Return the Sims as a stable (id-ordered) list."""
        return [self.sims[key] for key in sorted(self.sims, key=_sort_key)]

    def candidates(self, *, include_players: bool = False) -> list[SimProfile]:
        """Return eligible targets, preferring unplayed Sims (never the player first)."""
        sims = self.sims_list()
        if include_players:
            return sims
        unplayed = [sim for sim in sims if not sim.is_player]
        return unplayed or sims

    def played_ids(self) -> set[str]:
        """Return the ids of Sims controlled by a player (never God-owned)."""
        return {sim_id for sim_id, sim in self.sims.items() if sim.is_player}


def _sort_key(sim_id: str) -> tuple[int, object]:
    text = str(sim_id)
    if text.lstrip("-").isdigit():
        return (0, int(text))
    return (1, text)


@dataclass
class Directive:
    """A directive issued by the God agent.

    ``tool_call`` is the executable payload (a mod tool call) when the
    intervention maps to a game action; ``None`` means it is a broadcast
    world/knowledge event the Sim agents react to (``source=god``).
    """

    id: str
    type: str  # spawn_npc, apply_trait, force_social, gossip, relationship_shift, extreme_event
    target_sim: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    status: str = "pending"  # pending, executing, done, failed
    created_at: float = 0.0
    narration: str = ""
    tool_call: dict[str, Any] | None = None


def _empty_aggregates() -> dict[str, Any]:
    """Zeroed defaults matching the ``NeighborhoodAggregates`` wire model."""
    return {
        "population": 0,
        "household_count": 0,
        "households": {},
        "mood_distribution": {},
        "mood": "neutral",
        "tension": 0.0,
        "funds": 0,
    }


def aggregates(census: dict[str, Any] | None) -> dict[str, Any]:
    """Return the public neighborhood aggregates the God may read (``§14.5``).

    Built **only from public census values** - population, mood tags, relationship
    depths and household funds - never from psyches or secrets. The shape matches
    ``schemas.NeighborhoodAggregates``. Malformed or missing input yields the
    zeroed defaults; this function never raises.
    """
    result = _empty_aggregates()
    if not isinstance(census, dict):
        return result

    sims = [sim for sim in census.get("sims") or [] if isinstance(sim, dict)]
    households = [h for h in census.get("households") or [] if isinstance(h, dict)]
    result["population"] = len(sims)

    mood_distribution: dict[str, int] = {}
    negative_depths: list[float] = []
    negative_moods = 0
    for sim in sims:
        mood = str(sim.get("mood") or "neutral").strip().lower() or "neutral"
        mood_distribution[mood] = mood_distribution.get(mood, 0) + 1
        if mood in _NEGATIVE_MOODS:
            negative_moods += 1
        for rel in sim.get("relationships") or []:
            if not isinstance(rel, dict):
                continue
            depth = _as_float(rel.get("depth", rel.get("value", 0.0)))
            if depth < 0.0:
                negative_depths.append(min(1.0, abs(depth) / 100.0))
    result["mood_distribution"] = mood_distribution
    if mood_distribution:
        result["mood"] = min(mood_distribution, key=lambda tag: (-mood_distribution[tag], tag))

    households_map: dict[str, int] = {}
    funds = 0
    for household in households:
        household_id = household.get("household_id")
        name = str(household.get("name") or "").strip()
        if name:
            key = name
        elif household_id is not None:
            key = str(household_id)
        else:
            key = ""
        members = household.get("members") or []
        member_count = len(members) if isinstance(members, list) else 0
        if key:
            households_map[key] = member_count
        funds += _as_int(household.get("funds", 0))
    result["household_count"] = len(households)
    result["households"] = households_map
    result["funds"] = funds

    tension = 0.0
    if negative_depths:
        tension += 0.5 * (sum(negative_depths) / len(negative_depths))
    if sims:
        tension += 0.5 * (negative_moods / len(sims))
    result["tension"] = round(min(1.0, max(0.0, tension)), 4)
    return result
