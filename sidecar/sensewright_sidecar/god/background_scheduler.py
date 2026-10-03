"""Background scheduler for the God Director (REQ-GOD-03 / plan task 1.3).

Implements priority ordering: PLAYER > HOUSEHOLD > ACTIVE > RELATED > OTHER.
"""
from __future__ import annotations

from typing import Any

PRIORITY_ORDER = ("PLAYER", "HOUSEHOLD", "ACTIVE", "RELATED", "OTHER")


def priority_class(state: Any, sim: dict, active_sim_id: int | None = None) -> str:
    """Return the priority class for a sim.

    Classification precedence: PLAYER, then ACTIVE (the selected sim itself),
    then HOUSEHOLD, RELATED, OTHER. The selected sim is classified as ACTIVE
    *before* the household check so it can never be mistaken for a household
    member via its own ``household_id``.

    The resulting classes are then ranked by :data:`PRIORITY_ORDER`
    (``PLAYER > HOUSEHOLD > ACTIVE > RELATED > OTHER``, REQ-GOD-03), so a
    household Agent still outranks the active sim during selection.

    - PLAYER: ``sim.get("is_player")`` is truthy
    - ACTIVE: ``sim_id`` matches ``active_sim_id`` (if provided)
    - HOUSEHOLD: shares a non-empty ``household_id`` with the active or a player sim
    - RELATED: ``family_links`` intersects player/active sim ids, or vice versa
    - OTHER: everything else
    """
    # PLAYER check
    if sim.get("is_player"):
        return "PLAYER"

    sim_id = int(sim.get("sim_id", 0))

    # ACTIVE check (before HOUSEHOLD so the selected sim is never "household").
    if active_sim_id is not None and sim_id == int(active_sim_id):
        return "ACTIVE"

    # Build sets of player/active sim ids and their household_ids
    player_sim_ids: set[int] = set()
    player_household_ids: set[int] = set()
    active_household_id: int | None = None

    # We need to scan the census to find player sims and the active sim's household
    # Use duck typing on state.census_items()
    try:
        census_items = state.census_items()
    except AttributeError:
        census_items = []

    for cid, cdata in census_items:
        cid = int(cid)
        if cdata.get("is_player"):
            player_sim_ids.add(cid)
            hh_id = cdata.get("household_id")
            if hh_id:
                player_household_ids.add(int(hh_id))
        if active_sim_id is not None and cid == int(active_sim_id):
            hh_id = cdata.get("household_id")
            if hh_id:
                active_household_id = int(hh_id)

    # HOUSEHOLD check: shares household with active sim OR any player sim
    sim_household_id = sim.get("household_id")
    if sim_household_id:
        sim_hh = int(sim_household_id)
        if (active_household_id is not None and sim_hh == active_household_id) or (
            sim_hh in player_household_ids
        ):
            return "HOUSEHOLD"

    # RELATED check: family_links intersection with player/active sim ids
    target_ids = player_sim_ids.copy()
    if active_sim_id is not None:
        target_ids.add(int(active_sim_id))

    sim_family_links = sim.get("family_links") or []
    sim_family_set = {int(x) for x in sim_family_links if x}
    if sim_family_set & target_ids:
        return "RELATED"

    # Also check if any player/active sim has this sim in their family_links
    for cid, cdata in census_items:
        cid = int(cid)
        if cid in target_ids:
            other_links = cdata.get("family_links") or []
            if sim_id in {int(x) for x in other_links if x}:
                return "RELATED"

    return "OTHER"


def select_targets(
    state: Any,
    active_sim_id: int | None = None,
    cap: int = 2,
    exclude_ids: set[int] | list[int] | None = None,
) -> list[dict]:
    """Select up to `cap` target sims from the census, ordered by priority.

    Args:
        state: Object exposing `census_items()` returning list of (sim_id, sim_dict).
        active_sim_id: The currently active sim id (for ACTIVE priority).
        cap: Maximum number of targets to return (default 2).
        exclude_ids: Set/list of sim_ids to exclude from selection.

    Returns:
        List of sim dicts, each containing at least `sim_id` and `priority`.
    """
    if exclude_ids is None:
        exclude_ids = set()
    else:
        exclude_ids = set(int(x) for x in exclude_ids)

    try:
        census_items = state.census_items()
    except AttributeError:
        return []

    candidates: list[tuple[int, dict, str]] = []  # (priority_index, sim_id, sim_dict)

    for sim_id, sim_data in census_items:
        sim_id = int(sim_id)

        # Skip excluded
        if sim_id in exclude_ids:
            continue

        # Skip sleeping
        if sim_data.get("is_sleeping"):
            continue

        # Skip off-lot duty
        if sim_data.get("is_off_lot_duty"):
            continue

        # Determine priority class
        pclass = priority_class(state, sim_data, active_sim_id)
        priority_idx = PRIORITY_ORDER.index(pclass)

        # Ensure sim_id is in the dict
        sim_dict = dict(sim_data)
        sim_dict["sim_id"] = sim_id
        sim_dict["priority"] = pclass

        candidates.append((priority_idx, sim_id, sim_dict))

    # Sort by priority index, then by sim_id for deterministic ordering
    candidates.sort(key=lambda x: (x[0], x[1]))

    # Return up to cap sim dicts
    return [c[2] for c in candidates[:cap]]