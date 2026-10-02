"""Social layer & asymmetric dialogue (F04 / REQ-SOC-*).

Pre-flight gate (before any LLM call): both sims must be eligible in the
capability matrix, share a room, be within 4.0m, within the hearing radius of the
active sim, and within the speech policy (lines/minute, interval). Symmetric
(Agent<->Agent) vs asymmetric (Sovereign<->Puppet NPC) dialogue is driven by the
``puppeteer_objective`` context.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..constants import SOCIAL_MAX_DISTANCE_M, SPEECH_DEFAULTS
from .presence import capabilities, hard_blocked_social


def preflight(
    sim_a: Dict[str, Any],
    sim_b: Dict[str, Any],
    active_sim_id: Optional[int],
    hearing_radius: float = SPEECH_DEFAULTS["hearing_radius_m"],
    category: Optional[str] = None,
) -> Dict[str, bool]:
    """Run the F04 pre-flight gate; returns a dict of per-check booleans.

    When ``category`` is known (e.g. from a puppeteer objective), the CHILD
    hard-block (flirty/intimate) is enforced here (F12 / REQ-PRE-02).
    """
    result = {
        "capable_a": capabilities(sim_a.get("species"), sim_a.get("age_stage"))["can_social"],
        "capable_b": capabilities(sim_b.get("species"), sim_b.get("age_stage"))["can_social"],
        "same_room": sim_a.get("room_id") is not None and sim_a.get("room_id") == sim_b.get("room_id"),
        "within_distance": _within_distance(sim_a, sim_b, SOCIAL_MAX_DISTANCE_M),
        "within_hearing": _within_hearing(sim_a, sim_b, active_sim_id, hearing_radius),
        "category_ok": not (
            hard_blocked_social(category, sim_a.get("age_stage"))
            or hard_blocked_social(category, sim_b.get("age_stage"))
        ),
    }
    result["ok"] = all(result.values())
    return result


def _within_distance(sim_a: Dict[str, Any], sim_b: Dict[str, Any], max_distance: float) -> bool:
    pos_a = sim_a.get("pos") or {}
    pos_b = sim_b.get("pos") or {}
    try:
        ax, az = float(pos_a.get("x", 0.0)), float(pos_a.get("z", 0.0))
        bx, bz = float(pos_b.get("x", 0.0)), float(pos_b.get("z", 0.0))
        return ((ax - bx) ** 2 + (az - bz) ** 2) ** 0.5 <= max_distance
    except (TypeError, ValueError):
        return True


def _within_hearing(sim_a: Dict[str, Any], sim_b: Dict[str, Any], active_sim_id: Optional[int], hearing_radius: float) -> bool:
    if active_sim_id is None:
        return True
    # A sim must be within hearing of the active sim.
    if int(sim_a.get("sim_id", 0)) == int(active_sim_id) or int(sim_b.get("sim_id", 0)) == int(active_sim_id):
        return True
    active_pos = _active_position(sim_a, sim_b, active_sim_id)
    if active_pos is None:
        return True
    for sim in (sim_a, sim_b):
        pos = sim.get("pos") or {}
        try:
            ax, az = float(active_pos.get("x", 0.0)), float(active_pos.get("z", 0.0))
            x, z = float(pos.get("x", 0.0)), float(pos.get("z", 0.0))
            if ((ax - x) ** 2 + (az - z) ** 2) ** 0.5 <= hearing_radius:
                return True
        except (TypeError, ValueError):
            continue
    return False


def _active_position(sim_a: Dict[str, Any], sim_b: Dict[str, Any], active_sim_id: int) -> Optional[Dict[str, Any]]:
    for sim in (sim_a, sim_b):
        if int(sim.get("sim_id", 0)) == int(active_sim_id):
            return sim.get("pos")
    return None


def build_social_context(
    sim_a: Dict[str, Any],
    sim_b: Dict[str, Any],
    tick: int,
    rumor: Optional[Dict[str, Any]] = None,
    puppeteer: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the ``sim.social`` context, injecting rumor + puppeteer objective."""
    context: Dict[str, Any] = {
        "sim_id": int(sim_a.get("sim_id", 0)),
        "sim_name": sim_a.get("name", ""),
        "target_sim_id": int(sim_b.get("sim_id", 0)),
        "target_name": sim_b.get("name", ""),
        "world_sim_tick": tick,
    }
    if rumor:
        context["rumor"] = rumor
    if puppeteer:
        context["puppeteer_objective"] = puppeteer.get("objective", "")
        context["catalyst_name"] = puppeteer.get("catalyst_name", "")
        context["agent_name"] = puppeteer.get("agent_name", "")
    return context


def has_rumor_to_spread(sim_id: int, rumor: Optional[Dict[str, Any]]) -> bool:
    """A sim can only comment on a rumor if they already know it (REQ-WLD-01)."""
    if not rumor:
        return False
    known = rumor.get("known_by_sim_ids", []) or []
    return int(sim_id) in [int(s) for s in known]
