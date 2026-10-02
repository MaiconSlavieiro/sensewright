"""Personality system & psyche blocks (F08 / REQ-PSY-*).

Psyche blocks (trauma/belief) carry an intensity in [0, 1]. Salience is computed
from structured metadata (event category weight + emitted impact) — never from
language-dependent keyword search (REQ-PSY-01). Decay is exponential in SIM days
and prunes blocks below 0.05 (REQ-PSY-02).
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Tuple

from ..constants import (
    EVENT_CATEGORY_WEIGHTS, PSYCHE_PRUNE_THRESHOLD, PSYCHE_TRAIT_SWAP_DAYS,
    PSYCHE_TRAIT_SWAP_INTENSITY, SALIENCE_THRESHOLD,
)

#: Exponential decay rate per sim-day.
DECAY_LAMBDA = 0.05


def compute_salience(category: Optional[str], impact: float) -> float:
    """Salience = base weight of event_category + emitted impact (0..2)."""
    weight = EVENT_CATEGORY_WEIGHTS.get((category or "").lower(), 0.5)
    return weight + max(0.0, float(impact))


def is_salient(category: Optional[str], impact: float) -> bool:
    """True when an event generates/reinforces a psyche block."""
    return compute_salience(category, impact) >= SALIENCE_THRESHOLD


def decay_blocks(blocks: Dict[str, float], delta_sim_days: float) -> Dict[str, float]:
    """Apply exponential decay I(t) = I0 * e^(-lambda * delta_days) and prune."""
    factor = math.exp(-DECAY_LAMBDA * max(0.0, float(delta_sim_days)))
    result: Dict[str, float] = {}
    for key, intensity in blocks.items():
        value = float(intensity) * factor
        if value >= PSYCHE_PRUNE_THRESHOLD:
            result[key] = round(value, 4)
    return result


def reinforce_block(blocks: Dict[str, float], key: str, intensity: float) -> Dict[str, float]:
    """Create or strengthen a psyche block, clamped to [0, 1]."""
    result = dict(blocks)
    result[key] = min(1.0, max(0.0, result.get(key, 0.0) + float(intensity)))
    return result


def block_for_category(category: Optional[str]) -> str:
    """Map an event category to a canonical psyche block key."""
    cat = (category or "").lower()
    if cat in ("death",):
        return "grief"
    if cat in ("betrayal",):
        return "betrayal"
    if cat in ("fire",):
        return "trauma_fire"
    if cat in ("romance", "marriage"):
        return "romance"
    if cat in ("birth",):
        return "family"
    if cat in ("fight",):
        return "conflict"
    return "stress"


def propose_trait_swap(blocks: Dict[str, float], days_at_intensity: Dict[str, int]) -> List[str]:
    """Return block keys eligible for a core-trait swap proposal (REQ-EVO-03)."""
    proposals = []
    for key, intensity in blocks.items():
        if float(intensity) > PSYCHE_TRAIT_SWAP_INTENSITY and days_at_intensity.get(key, 0) >= PSYCHE_TRAIT_SWAP_DAYS:
            proposals.append(key)
    return proposals


def strongest_block(blocks: Dict[str, float]) -> Tuple[str, float]:
    """Return (key, intensity) of the strongest block, or ("", 0.0)."""
    if not blocks:
        return "", 0.0
    key = max(blocks, key=lambda k: float(blocks[k]))
    return key, float(blocks[key])
