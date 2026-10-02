"""God Director — ``god.cast`` (P16): townie reuse and catalyst recruitment.

Casting prefers an existing, compatible townie already present in the census
(no new SimInfo is created). Only when no compatible townie exists does it emit
a ``spawn_npc`` intent, which the Mod fulfils through the native SituationManager
/ VisitSituation path (task 2.4 / 3.3).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..agent.intents import normalize_intent
from ..observability.logging import get_logger
from ..state import AppState

logger = get_logger("god.cast")

#: Age stages that can serve as a dramatic catalyst.
_ADULT_STAGES = ("TEEN", "YOUNGADULT", "ADULT", "ELDER")


def _cast_member(state: AppState, sim_id: int, role: str, objective: str, name: str) -> Dict[str, Any]:
    return {
        "sim_id": int(sim_id),
        "name": name,
        "role": role,
        "objective": objective,
        "spawned": False,
    }


def _already_cast(arc: Optional[Dict[str, Any]]) -> set:
    ids = set()
    for member in (arc or {}).get("cast", []) or []:
        if isinstance(member, dict) and member.get("sim_id"):
            ids.add(int(member["sim_id"]))
    return ids


def find_compatible_townie(
    state: AppState,
    target_sim_id: Optional[int] = None,
    arc: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Return the best non-player adult townie for a catalyst role, or None.

    Matching is deterministic: candidates must not be in the player household,
    must be an adult-ish age stage, and must not already be cast. A shared trait
    with the target raises the score; otherwise the first candidate wins.
    """
    target = state.get_census(int(target_sim_id)) if target_sim_id else {}
    target_traits = {str(t).lower() for t in (target.get("traits") or [])}
    cast_ids = _already_cast(arc)
    best = None
    best_score = -1.0
    for sim_id, sim in state.census_items():
        if sim.get("is_player"):
            continue
        if str(sim.get("age_stage", "")).upper() not in _ADULT_STAGES:
            continue
        if int(sim.get("sim_id", sim_id)) in cast_ids:
            continue
        traits = {str(t).lower() for t in (sim.get("traits") or [])}
        score = float(len(traits & target_traits))
        # Prefer sims already on the lot (they have a room).
        if sim.get("room_id"):
            score += 0.5
        if score > best_score:
            best_score = score
            best = sim
    return best


def _spawn_intent(role: str, objective: str, target_sim_id: Optional[int], tick: int, state: AppState) -> Dict[str, Any]:
    """Build the canonical ``spawn_npc`` intent consumed by the Mod (2.4)."""
    return normalize_intent(
        {
            "sim_id": int(target_sim_id or 0),
            "kind": "spawn_npc",
            "target_sim_id": int(target_sim_id) if target_sim_id else None,
            "params": {
                "role": role,
                "objective": objective,
                "spawn_tick": int(tick),
                "ring_doorbell": True,
                "approach_target": int(target_sim_id) if target_sim_id else 0,
            },
            "expires_on": "ttl",
            "source": "god",
        },
        default_source="god",
    )


def run_cast(
    state: AppState,
    save_id: int,
    beat: Dict[str, Any],
    tick: int,
    lang: str,
    target_sim_id: Optional[int] = None,
    arc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Resolve the beat's catalyst: reuse a townie or emit a ``spawn_npc`` intent.

    Returns ``{"cast": [NpcSheet], "intents": [Intent]}``. The caller persists the
    cast into the arc via ``save_arc``.
    """
    role = beat.get("catalyst_role") or beat.get("role") or "catalyst"
    objective = beat.get("title") or beat.get("scene_draft") or "Deliver the scene."
    candidate = find_compatible_townie(state, target_sim_id, arc)
    if candidate is not None:
        sim_id = int(candidate.get("sim_id", 0))
        sheet = _cast_member(state, sim_id, role, objective, candidate.get("name", ""))
        # An already-present townie still needs to be pulled toward the target.
        intents: List[Dict[str, Any]] = []
        if target_sim_id:
            intents.append(normalize_intent(
                {
                    "sim_id": sim_id,
                    "kind": "approach",
                    "target_sim_id": int(target_sim_id),
                    "params": {"objective": objective, "source": "god.cast"},
                    "source": "god",
                },
                default_source="god",
            ))
        logger.info("god.cast reused townie %s for beat %r", sim_id, objective)
        return {"cast": [sheet], "intents": intents, "spawned": False}

    intent = _spawn_intent(role, objective, target_sim_id, tick, state)
    sheet = {
        "sim_id": 0,
        "name": role,
        "role": role,
        "objective": objective,
        "spawned": True,
    }
    logger.info("god.cast no candidate -> spawn_npc (%s)", role)
    return {"cast": [sheet], "intents": [intent], "spawned": True}
