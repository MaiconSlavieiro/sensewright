"""God Director — control leases & asymmetric arbitration (F13 / REQ-COORD-*)."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from ..constants import (
    LEASE_GOD_CATALYST_PUPPET, LEASE_PLAYER_MANUAL, LEASE_PRIORITY,
    LEASE_SANDBOX_OVERRIDE, LEASE_SOVEREIGN_AGENT,
)
from ..state import AppState


def player_lock(state: AppState, sim_id: int, seconds: float) -> None:
    """Apply the PLAYER_MANUAL lock for ``seconds`` wall-clock seconds."""
    state.player_lock_until[int(sim_id)] = time.time() + float(seconds)


def is_player_locked(state: AppState, sim_id: int) -> bool:
    return time.time() < state.player_lock_until.get(int(sim_id), 0.0)


def lease_for(state: AppState, sim_id: int) -> str:
    """Return the active control lease for a sim (highest priority wins)."""
    sim_id = int(sim_id)
    if is_player_locked(state, sim_id):
        return LEASE_PLAYER_MANUAL
    if sim_id in state.catalyst_leases:
        return LEASE_GOD_CATALYST_PUPPET
    return LEASE_SOVEREIGN_AGENT


def can_god_puppeteer(state: AppState, sim_id: int) -> bool:
    """The puppeteer may only control NPC catalysts, never sovereign agents."""
    return sim_id in state.catalyst_leases and not is_player_locked(state, sim_id)


def is_sovereign_agent(state: AppState, sim_id: int) -> bool:
    return lease_for(state, sim_id) in (LEASE_SOVEREIGN_AGENT,)


def set_catalyst_lease(state: AppState, sim_id: int, objective: str, tick: int) -> None:
    state.catalyst_leases[int(sim_id)] = {
        "objective": objective,
        "lease_expires_tick": int(tick) + 1440,
    }


def clear_catalyst_lease(state: AppState, sim_id: int) -> None:
    state.catalyst_leases.pop(int(sim_id), None)
