"""Initiative / impulse and reaction (F03 / REQ-IMP-*).

The idle impulse only produces internal thought + at most one non-verbal intent
and never speaks. The reaction (salience >= 1.5) may emit a ``speak`` intent at
the causer. A survival & punctuality guard forbids physical actions when a basic
need is critical or work/school starts within 45 in-game minutes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Need threshold considered critical (mood/need delta < -70).
CRITICAL_NEED_THRESHOLD = -70.0
#: Minutes before work/school within which physical actions are forbidden.
DUTY_GUARD_MINUTES = 45


def has_critical_need(needs: Any) -> bool:
    """True if any basic need is critically low."""
    if isinstance(needs, dict):
        for value in needs.values():
            try:
                if float(value) < CRITICAL_NEED_THRESHOLD:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def duty_imminent(schedule_blocks: Any, tick: int) -> bool:
    """True if work/school starts within DUTY_GUARD_MINUTES of ``tick``."""
    for block in schedule_blocks or []:
        if not isinstance(block, dict):
            continue
        start = block.get("start_tick")
        if start is None:
            continue
        try:
            delta = float(start) - float(tick)
            if 0 < delta <= DUTY_GUARD_MINUTES:
                return True
        except (TypeError, ValueError):
            continue
    return False


def physical_actions_allowed(
    needs: Any,
    schedule_blocks: Any,
    tick: int,
) -> bool:
    """The survival & punctuality guard (REQ-IMP-03)."""
    if has_critical_need(needs):
        return False
    if duty_imminent(schedule_blocks, tick):
        return False
    return True


def build_impulse_context(
    sim_id: int,
    sim_name: str,
    tier: str,
    mood: str,
    activity: str,
    needs: Any,
    is_off_lot_duty: bool,
    is_sleeping: bool,
    tick: int,
    schedule_blocks: Any = None,
) -> Dict[str, Any]:
    """Context for the ``sim.impulse`` purpose (idle).

    ``schedule_blocks`` (from the native census) feeds the survival &
    punctuality guard so the LLM is told when physical actions are forbidden
    (REQ-IMP-03).
    """
    return {
        "sim_id": sim_id,
        "sim_name": sim_name,
        "tier": tier,
        "mood": mood,
        "activity": activity,
        "current_needs": needs,
        "is_off_lot_duty": bool(is_off_lot_duty),
        "is_sleeping": bool(is_sleeping),
        "physical_actions_allowed": physical_actions_allowed(needs, schedule_blocks, tick),
        "world_sim_tick": tick,
    }


def build_reaction_context(
    sim_id: int,
    sim_name: str,
    target_sim_id: Optional[int],
    target_name: str,
    event_category: str,
    impact: float,
    salience: float,
    tick: int,
) -> Dict[str, Any]:
    """Context for the ``sim.reaction`` purpose."""
    return {
        "sim_id": sim_id,
        "sim_name": sim_name,
        "target_sim_id": target_sim_id,
        "target_name": target_name,
        "event_category": event_category,
        "impact": impact,
        "salience": salience,
        "world_sim_tick": tick,
    }
