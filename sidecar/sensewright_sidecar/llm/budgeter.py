"""Per-sim game budget bookkeeping (pacing) with asymmetric refund support.

The "game budget" is a per-sim token spend cap that governs pacing of autonomous
purposes. It is distinct from provider rate limits. On a timeout or network
failure after dispatch, the game budget is refunded (the player is not penalized)
but the provider rate limit is NOT (REQ-SCHED-02).
"""
from __future__ import annotations

import threading
from typing import Dict


class GameBudgeter:
    """Tracks per-sim token spend and supports refunds."""

    def __init__(self, default_cap: int = 10000) -> None:
        self._lock = threading.Lock()
        self._spend: Dict[int, int] = {}
        self._cap = default_cap

    def spend(self, sim_id: int, tokens: int) -> None:
        with self._lock:
            self._spend[int(sim_id)] = self._spend.get(int(sim_id), 0) + max(0, int(tokens))

    def refund(self, sim_id: int, tokens: int) -> None:
        with self._lock:
            current = self._spend.get(int(sim_id), 0)
            self._spend[int(sim_id)] = max(0, current - max(0, int(tokens)))

    def spent(self, sim_id: int) -> int:
        with self._lock:
            return self._spend.get(int(sim_id), 0)

    def reset(self, sim_id: int) -> None:
        with self._lock:
            self._spend.pop(int(sim_id), None)

    def snapshot(self) -> Dict[int, int]:
        with self._lock:
            return dict(self._spend)
