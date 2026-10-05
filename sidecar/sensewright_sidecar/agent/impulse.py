"""Initiative / impulse and reaction (F03 / REQ-IMP-*).

The idle impulse only produces internal thought + at most one non-verbal intent
and never speaks. The reaction (salience >= 1.5) may emit a ``speak`` intent at
the causer. A survival & punctuality guard forbids physical actions when a basic
need is critical or work/school starts within 45 in-game minutes.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..constants import SIM_MINUTES_PER_DAY, TICKS_PER_SIM_MINUTE

#: Need threshold considered critical (mood/need delta < -70).
CRITICAL_NEED_THRESHOLD = -70.0
#: Minutes before work/school within which physical actions are forbidden.
DUTY_GUARD_MINUTES = 45


def _minute_of_day(tick: int) -> float:
    """Best-effort in-game minute-of-day from a world tick.

    Assumes ``world_sim_tick`` starts at midnight and advances
    ``TICKS_PER_SIM_MINUTE`` per sim-minute. This is the basis for matching the
    Mod's ``start_hour`` schedule shape (S-H05); validate in-game if the origin
    differs.
    """
    try:
        return float((int(tick) // TICKS_PER_SIM_MINUTE) % SIM_MINUTES_PER_DAY)
    except (TypeError, ValueError):
        return 0.0


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
    """True if work/school starts within DUTY_GUARD_MINUTES of ``tick``.

    Accepts the Mod's real schedule shape (``start_hour``/``start_minute_of_day``,
    converted via minute-of-day) as well as the legacy ``start_tick`` raw-minute
    shape used by older payloads/tests (S-H05).
    """
    for block in schedule_blocks or []:
        if not isinstance(block, dict):
            continue

        start_mod = block.get("start_minute_of_day")
        if start_mod is None and block.get("start_hour") is not None:
            try:
                start_mod = float(block.get("start_hour")) * 60.0
            except (TypeError, ValueError):
                start_mod = None
        if start_mod is not None:
            try:
                delta = (float(start_mod) - _minute_of_day(tick)) % SIM_MINUTES_PER_DAY
            except (TypeError, ValueError):
                continue
            if 0 < delta <= DUTY_GUARD_MINUTES:
                return True
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
