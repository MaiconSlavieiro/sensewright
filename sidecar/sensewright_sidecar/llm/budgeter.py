"""Per-Sim daily request budgeter for the real-time chat path (Phase 3).

Chat and background work use separate budgets: this one caps how many LLM
requests a single Sim may trigger per day, protecting the free tiers from a
runaway conversation. A limit of ``0`` means unlimited. The day boundary is
UTC to stay deterministic; the clock is injectable for tests.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


class ChatBudgeter:
    """Rolling daily quota, tracked per Sim."""

    def __init__(
        self,
        *,
        per_sim_per_day: int = 500,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._limit = max(0, int(per_sim_per_day))
        self._wall = wall_clock
        self._day = self._day_key()
        self._used: dict[str, int] = {}
        self._total = 0

    def _day_key(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._wall()))

    def _roll_day(self) -> None:
        today = self._day_key()
        if today != self._day:
            self._day = today
            self._used.clear()

    def try_acquire(self, sim_key: str) -> bool:
        """Consume one request slot for ``sim_key``; False when exhausted."""
        self._roll_day()
        if self._limit > 0 and self._used.get(sim_key, 0) >= self._limit:
            return False
        self._used[sim_key] = self._used.get(sim_key, 0) + 1
        self._total += 1
        return True

    def remaining(self, sim_key: str) -> int | None:
        """Remaining requests for a Sim today (None when unlimited)."""
        self._roll_day()
        if self._limit <= 0:
            return None
        return max(0, self._limit - self._used.get(sim_key, 0))

    def reset(self, sim_key: str | None = None) -> None:
        """Clear usage for one Sim, or everyone when ``sim_key`` is None."""
        if sim_key is None:
            self._used.clear()
        else:
            self._used.pop(sim_key, None)

    def snapshot(self) -> dict[str, Any]:
        self._roll_day()
        return {
            "per_sim_per_day": self._limit,
            "total_used": self._total,
            "sims": len(self._used),
            "day": self._day,
        }
