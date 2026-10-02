"""Evolution, demeanor & native likes/dislikes (F09 / REQ-EVO-*).

``evo.reflect`` runs at most once per sleep cycle (or on the mirror reflection
interaction); it updates only ``current_demeanor``, never ``core_personality``
(REQ-EVO-01). ``evo.trait`` proposes native likes/dislikes and core-trait swaps.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .psyche import propose_trait_swap


def build_reflect_context(
    sim_id: int,
    sim_name: str,
    profile: Dict[str, Any],
    salient_events: int,
    tick: int,
) -> Dict[str, Any]:
    """Context for ``evo.reflect``."""
    return {
        "sim_id": sim_id,
        "sim_name": sim_name,
        "profile": profile,
        "salient_events": salient_events,
        "world_sim_tick": tick,
    }


def apply_reflection(profile: Dict[str, Any], reflection: Dict[str, Any]) -> Dict[str, Any]:
    """Fold a reflection into the profile, updating current_demeanor only."""
    profile = dict(profile)
    demeanor_drift = reflection.get("demeanor_drift")
    if isinstance(demeanor_drift, str) and demeanor_drift:
        profile["current_demeanor"] = demeanor_drift
    return profile


def build_trait_context(
    sim_id: int,
    sim_name: str,
    profile: Dict[str, Any],
    psyche_blocks: Dict[str, float],
    days_at_intensity: Dict[str, int],
    tick: int,
) -> Dict[str, Any]:
    """Context for ``evo.trait`` (likes/dislikes + trait swap proposal)."""
    return {
        "sim_id": sim_id,
        "sim_name": sim_name,
        "profile": profile,
        "psyche_blocks": psyche_blocks,
        "trait_swap_candidates": propose_trait_swap(psyche_blocks, days_at_intensity),
        "world_sim_tick": tick,
    }


def extract_preference_change(trait_output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return the preference_change dict (or None) from an evo.trait output."""
    change = trait_output.get("preference_change")
    if isinstance(change, dict):
        return change
    return None


def extract_trait_proposal(trait_output: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    proposal = trait_output.get("trait_proposal")
    if isinstance(proposal, dict):
        return proposal
    return None
