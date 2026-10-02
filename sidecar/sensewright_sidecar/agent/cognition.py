"""Hybrid cognition & native agenda (F07 / REQ-COG-*).

Builds the ``sim.cognition`` context from native schedule blocks, obligatory
tasks, wants and the dream urge, and folds the output into the sim profile's
``daily_plan`` + ``autonomy_biases`` (soft guidance of native autonomy).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_cognition_context(
    sim_id: int,
    sim_name: str,
    schedule_blocks: List[Dict[str, Any]],
    obligatory_tasks: List[Dict[str, Any]],
    native_wants: List[Dict[str, Any]],
    dream_urge: Optional[Dict[str, Any]],
    tick: int,
) -> Dict[str, Any]:
    """Assemble the context for the ``sim.cognition`` purpose."""
    return {
        "sim_id": sim_id,
        "sim_name": sim_name,
        "schedule_blocks": schedule_blocks or [],
        "obligatory_tasks": obligatory_tasks or [],
        "native_wants": native_wants or [],
        "dream_urge": dream_urge or {},
        "world_sim_tick": tick,
    }


def apply_cognition(
    profile: Dict[str, Any],
    cognition: Dict[str, Any],
) -> Dict[str, Any]:
    """Fold a cognition output into the profile (daily_plan + biases)."""
    profile = dict(profile)
    profile["daily_plan"] = cognition.get("blocks", {})
    profile["day_focus"] = cognition.get("day_focus", "")
    profile["attitude_toward_duty"] = cognition.get("attitude_toward_duty", "compliant")
    profile["autonomy_biases"] = cognition.get("autonomy_biases", [])
    return profile


def extract_autonomy_biases(cognition: Dict[str, Any]) -> List[str]:
    """Return the autonomy bias activity keys from a cognition output."""
    biases = cognition.get("autonomy_biases", [])
    if isinstance(biases, list):
        return [b for b in biases if isinstance(b, str)]
    return []
