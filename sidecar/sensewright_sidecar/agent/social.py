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


def coerce_float(value: Any, default: float = 0.0) -> float:
    """Best-effort float coercion; returns ``default`` on anything non-numeric."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def relationship_value(state: Any, a_id: int, b_id: int, key: str) -> float:
    """Read a relationship track value for a pair, order-independent."""
    rel = state.relationships.get("{}:{}".format(a_id, b_id))
    if rel is None:
        rel = state.relationships.get("{}:{}".format(b_id, a_id))
    if rel is None:
        return 0.0
    return coerce_float(rel.get(key, 0.0), 0.0)


def are_family(state: Any, a_id: int, b_id: int) -> bool:
    """True when either sim lists the other in its census ``family_links``."""
    for sid, other in ((a_id, b_id), (b_id, a_id)):
        sim = state.get_census(sid)
        for link in (sim.get("family_links") or []):
            target = link.get("target_sim_id") if isinstance(link, dict) else link
            try:
                if int(target or 0) == other:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def relationship_tier(friendship: float, is_family: bool) -> str:
    if is_family:
        return "family"
    if friendship <= -15.0:
        return "rival"
    if friendship >= 65.0:
        return "close"
    if friendship >= 25.0:
        return "friend"
    if friendship >= 5.0:
        return "acquaintance"
    return "stranger"


def location_context(
    state: Any, sim: Dict[str, Any], other: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the location/setting context for a sim (or a pair)."""
    zone = getattr(state, "zone_context", None) or {}
    same_room = False
    if other is not None:
        same_room = (
            sim.get("room_id") not in (None, 0)
            and sim.get("room_id") == other.get("room_id")
        )
    is_outside = sim.get("is_outside")
    is_at_home = sim.get("is_at_home")
    return {
        "venue": zone.get("venue_type", ""),
        "is_residential": bool(zone.get("is_residential", False)),
        "is_outside": bool(is_outside) if is_outside is not None else None,
        "is_at_home": bool(is_at_home) if is_at_home is not None else None,
        "same_room": bool(same_room),
    }


def relationship_context(
    state: Any, sim_a: Dict[str, Any], sim_b: Dict[str, Any],
) -> Dict[str, Any]:
    a_id = int(sim_a.get("sim_id", 0))
    b_id = int(sim_b.get("sim_id", 0))
    baseline_friendship = relationship_value(state, a_id, b_id, "friendship")
    baseline_romance = relationship_value(state, a_id, b_id, "romance")
    is_family = are_family(state, a_id, b_id)

    # Native feedback: the Mod reports the fresh friendship/romance level after the
    # just-run interaction (social_friendship/social_romance on either side of the
    # pair). Use it as the "now" value and derive the delta vs the census baseline.
    current_friendship = _pair_fresh_value(sim_a, sim_b, "social_friendship", b_id)
    current_romance = _pair_fresh_value(sim_a, sim_b, "social_romance", b_id)
    if current_friendship is None:
        current_friendship = baseline_friendship
    if current_romance is None:
        current_romance = baseline_romance

    friendship = coerce_float(current_friendship, baseline_friendship)
    romance = coerce_float(current_romance, baseline_romance)
    friendship_delta = round(friendship - baseline_friendship, 2)
    romance_delta = round(romance - baseline_romance, 2)

    sentiments = []
    for sim, other_id in ((sim_a, b_id), (sim_b, a_id)):
        if int(sim.get("social_target_sim_id") or 0) == other_id:
            s_list = sim.get("social_sentiments")
            if s_list and isinstance(s_list, list):
                sentiments = [str(s) for s in s_list if s]
                break
    if not sentiments:
        rel = state.relationships.get("{}:{}".format(a_id, b_id)) or state.relationships.get("{}:{}".format(b_id, a_id))
        if rel and isinstance(rel, dict):
            s_list = rel.get("sentiments")
            if s_list and isinstance(s_list, list):
                sentiments = [str(s) for s in s_list if s]

    return {
        "friendship": friendship,
        "romance": romance,
        "friendship_delta": friendship_delta,
        "romance_delta": romance_delta,
        "tier": relationship_tier(friendship, is_family),
        "is_family": is_family,
        "sentiments": sentiments,
    }


def _pair_fresh_value(
    sim_a: Dict[str, Any], sim_b: Dict[str, Any], key: str, b_id: int,
) -> Optional[float]:
    """Read a fresh relationship value from the pair, matching the social target.

    Each side reports the value toward its own ``social_target_sim_id``; pick the
    side whose target is the other sim so the value reflects this exact pair.
    """
    for sim, other_id in ((sim_a, b_id), (sim_b, int(sim_a.get("sim_id", 0)))):
        if int(sim.get("social_target_sim_id") or 0) == int(other_id):
            value = sim.get(key)
            if value is not None:
                return coerce_float(value, 0.0)
    # Fall back to either side's value if the target is not resolved.
    for sim in (sim_a, sim_b):
        value = sim.get(key)
        if value is not None:
            return coerce_float(value, 0.0)
    return None


def action_context(sim: Dict[str, Any], other: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build the selected-action context (menu text) for a sim (or a pair)."""
    action: Dict[str, Any] = {
        "a_name": sim.get("name", ""),
        "a_current": sim.get("interaction_text") or sim.get("activity", ""),
        "a_queued": list(sim.get("queued_interaction_texts") or []),
    }
    if other is not None:
        action["b_name"] = other.get("name", "")
        action["b_current"] = other.get("interaction_text") or other.get("activity", "")
        action["b_queued"] = list(other.get("queued_interaction_texts") or [])
    return action


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
    location: Optional[Dict[str, Any]] = None,
    relationship: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the ``sim.social`` context, injecting rumor + puppeteer objective.

    Also carries the scene grounding the user requires for context-aware dialogue:
    ``location`` (venue / indoor-outdoor / home-away), ``relationship`` (friendship
    tier / family) and ``action`` (the selected interaction menu text each Sim is
    performing or has queued), so the tone reflects the setting and the specific
    action being taken. The actor's ``gender`` is carried through for grammatical
    inflection (BUG-17).
    """
    context: Dict[str, Any] = {
        "sim_id": int(sim_a.get("sim_id", 0)),
        "sim_name": sim_a.get("name", ""),
        "target_sim_id": int(sim_b.get("sim_id", 0)),
        "target_name": sim_b.get("name", ""),
        "world_sim_tick": tick,
    }
    if sim_a.get("gender"):
        context["gender"] = sim_a.get("gender")
    if rumor:
        context["rumor"] = rumor
    if puppeteer:
        context["puppeteer_objective"] = puppeteer.get("objective", "")
        context["catalyst_name"] = puppeteer.get("catalyst_name", "")
        context["agent_name"] = puppeteer.get("agent_name", "")
    if location:
        context["location"] = location
    if relationship:
        context["relationship"] = relationship
    context["action"] = {
        "a_name": sim_a.get("name", ""),
        "a_current": sim_a.get("interaction_text") or sim_a.get("activity", ""),
        "a_queued": list(sim_a.get("queued_interaction_texts") or []),
        "b_name": sim_b.get("name", ""),
        "b_current": sim_b.get("interaction_text") or sim_b.get("activity", ""),
        "b_queued": list(sim_b.get("queued_interaction_texts") or []),
    }
    return context


def has_rumor_to_spread(sim_id: int, rumor: Optional[Dict[str, Any]]) -> bool:
    """A sim can only comment on a rumor if they already know it (REQ-WLD-01)."""
    if not rumor:
        return False
    known = rumor.get("known_by_sim_ids", []) or []
    return int(sim_id) in [int(s) for s in known]
