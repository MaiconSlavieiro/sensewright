"""Presence policy and capability matrix (F12 / REQ-PRE-*).

Determines each sim's agency level (``full`` / ``reactive`` / ``off``) and its
capabilities by species + age stage. Purely data-driven — no game API calls.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..constants import (
    CHILD_HARD_BLOCKED_CATEGORIES, EXCLUDED_FROM_SEATS, FULL_PRESENCE_FRIENDSHIP,
    PRESENCE_FULL, PRESENCE_OFF, PRESENCE_REACTIVE, SENSORY_ONLY,
)

#: Bond links that count as "intimate" for presence promotion.
INTIMATE_BONDS = ("family", "friend", "romantic", "spouse", "partner")


def excluded_from_seats(species: Optional[str]) -> bool:
    """True for species excluded from the SeatManager entirely (BABY)."""
    return (species or "").upper() in EXCLUDED_FROM_SEATS


def sensory_only(species: Optional[str], age_stage: Optional[str]) -> bool:
    """True for sims that only produce instinctual thought + set_mood."""
    return (age_stage or "").upper() in SENSORY_ONLY or (species or "").upper() in SENSORY_ONLY


def hard_blocked_social(category: Optional[str], age_stage: Optional[str]) -> bool:
    """CHILD sims are hard-blocked from flirty/intimate social categories."""
    if (age_stage or "").upper() != "CHILD":
        return False
    return (category or "").lower() in CHILD_HARD_BLOCKED_CATEGORIES


def capabilities(species: Optional[str], age_stage: Optional[str]) -> Dict[str, bool]:
    """Return the capability flags for a sim."""
    sensory = sensory_only(species, age_stage)
    return {
        "can_speak": not sensory,
        "can_social": not sensory,
        "can_career": not sensory and (age_stage or "").upper() not in ("INFANT", "TODDLER", "CHILD"),
        "sensory_only": sensory,
        "excluded_from_seats": excluded_from_seats(species),
    }


def presence_tier(
    is_player: bool,
    in_active_household: bool,
    is_catalyst: bool,
    friendship: float = 0.0,
    bond_types: Optional[List[str]] = None,
    species: Optional[str] = None,
    age_stage: Optional[str] = None,
) -> str:
    """Classify a sim's presence tier.

    Priority: excluded/sensory-only (BABY, pets, INFANT/TODDLER) -> off; active
    household / player -> full; catalyst -> full; intimate visitor
    (friendship >= 20 on an intimate bond) -> full; else reactive.
    """
    if excluded_from_seats(species) or sensory_only(species, age_stage):
        return PRESENCE_OFF
    if is_player or in_active_household or is_catalyst:
        return PRESENCE_FULL
    bonds = [b or "" for b in (bond_types or [])]
    intimate = any(b.lower() in INTIMATE_BONDS for b in bonds)
    if intimate and float(friendship) >= FULL_PRESENCE_FRIENDSHIP:
        return PRESENCE_FULL
    return PRESENCE_REACTIVE
