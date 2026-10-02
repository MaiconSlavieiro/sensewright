"""SeatManager (F06 / REQ-SEAT-*).

Manages the finite pool of agent seats (default 12). Priority is strict:
active household > catalyst NPCs > intimate visitors > common visitors. A
visitor is never evicted while in an active ConversationSession, acting as a
catalyst, or within the minimum lease time (60 sim minutes). When a seat must be
freed, the evictee is the eligible visitor farthest from the active sim with no
social interaction (REQ-SEAT-03).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .presence import capabilities, presence_tier

#: Role priority (lower = higher priority). Lower value seats first.
ROLE_PRIORITY = {
    "household": 0,
    "catalyst": 1,
    "visitor_intimate": 2,
    "visitor_common": 3,
}

#: Presence tier ranking used within the same role.
TIER_RANK = {"full": 0, "reactive": 1, "off": 2}


def _distance(active_sim_id: Optional[int], sim: Dict[str, Any]) -> float:
    """Euclidean distance to the active sim from a census/delta entry."""
    if active_sim_id is None:
        return 0.0
    pos = sim.get("pos") or {}
    active_pos = sim.get("active_pos") or {}
    try:
        ax = float(active_pos.get("x", 0.0))
        az = float(active_pos.get("z", 0.0))
        x = float(pos.get("x", 0.0))
        z = float(pos.get("z", 0.0))
        return math.hypot(x - ax, z - az)
    except (TypeError, ValueError):
        return 0.0


class SeatManager:
    """Assigns and evicts agent seats from the current census."""

    def assign(
        self,
        sims: Dict[int, Dict[str, Any]],
        active_household_id: Optional[int],
        active_sim_id: Optional[int],
        catalyst_ids: List[int],
        active_conversation_ids: List[int],
        tick: int,
        max_seats: int,
        lease_min_sim_minutes: int,
        existing_seats: Optional[Dict[int, Dict[str, Any]]] = None,
    ) -> Dict[int, Dict[str, Any]]:
        """Return the new seat map (sim_id -> seat dict)."""
        existing = existing_seats or {}
        catalyst_set = set(int(c) for c in catalyst_ids)
        conversation_set = set(int(c) for c in active_conversation_ids)

        candidates: List[Dict[str, Any]] = []
        for sim_id, sim in sims.items():
            sim_id = int(sim_id)
            caps = capabilities(sim.get("species"), sim.get("age_stage"))
            if caps["excluded_from_seats"]:
                continue
            is_player = bool(sim.get("is_player", False))
            household_id = sim.get("household_id")
            in_household = household_id is not None and int(household_id) == int(active_household_id or -1)
            is_catalyst = sim_id in catalyst_set

            tier = presence_tier(
                is_player, in_household, is_catalyst,
                friendship=sim.get("friendship", 0.0),
                bond_types=sim.get("bond_types"),
            )
            if tier == "off":
                continue

            if is_player or in_household:
                role = "household"
            elif is_catalyst:
                role = "catalyst"
            elif tier == "full":
                role = "visitor_intimate"
            else:
                role = "visitor_common"

            candidates.append({
                "sim_id": sim_id,
                "role": role,
                "tier": tier,
                "priority": ROLE_PRIORITY[role],
                "tier_rank": TIER_RANK[tier],
                "distance": _distance(active_sim_id, sim),
            })

        candidates.sort(key=lambda c: (c["priority"], c["tier_rank"], c["distance"], c["sim_id"]))

        seats: Dict[int, Dict[str, Any]] = {}
        for cand in candidates:
            sim_id = cand["sim_id"]
            if sim_id in existing and self._protected(existing[sim_id], sim_id, catalyst_set, conversation_set, tick, lease_min_sim_minutes):
                seats[sim_id] = existing[sim_id]
                continue
            if len(seats) >= max_seats:
                break
            seats[sim_id] = {
                "sim_id": sim_id,
                "role": cand["role"],
                "tier": cand["tier"],
                "lease_expires_tick": tick + lease_min_sim_minutes,
            }
        return seats

    @staticmethod
    def _protected(
        seat: Dict[str, Any],
        sim_id: int,
        catalyst_set: set,
        conversation_set: set,
        tick: int,
        lease_min: int,
    ) -> bool:
        if sim_id in catalyst_set:
            return True
        if sim_id in conversation_set:
            return True
        return int(seat.get("lease_expires_tick", 0)) > int(tick)

    @staticmethod
    def snapshot(seats: Dict[int, Dict[str, Any]], max_seats: int) -> Dict[str, Any]:
        return {
            "seats": list(seats.values()),
            "pool": max(0, max_seats - len(seats)),
        }
