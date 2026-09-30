"""Per-provider request rate limiting (RPM/RPD).

The provider chain consults one of these before it exposes a provider to the
fallback order, so a free tier that is about to hit its cap is skipped in favor
of the next provider/model instead of burning a 429. A limit of ``0`` (or
``None`` at the config layer) disables that dimension.

The clock sources are injectable so the behaviour is deterministic under test.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from typing import Any


class ProviderRateLimiter:
    """Sliding-window (per-minute) + daily quota meter for one provider."""

    def __init__(
        self,
        *,
        rpm: int = 0,
        rpd: int = 0,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._rpm = max(0, int(rpm or 0))
        self._rpd = max(0, int(rpd or 0))
        self._monotonic = monotonic
        self._wall = wall_clock
        self._window: deque[float] = deque()
        self._day = self._day_key()
        self._day_used = 0
        self._total_used = 0

    @property
    def enabled(self) -> bool:
        """True when at least one dimension is capped."""
        return self._rpm > 0 or self._rpd > 0

    def _day_key(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self._wall()))

    def _prune(self, now: float) -> None:
        cutoff = now - 60.0
        while self._window and self._window[0] <= cutoff:
            self._window.popleft()

    def _roll_day(self) -> None:
        today = self._day_key()
        if today != self._day:
            self._day = today
            self._day_used = 0

    def try_acquire(self) -> bool:
        """Consume one slot; return False when any active limit is reached."""
        if not self.enabled:
            self._total_used += 1
            return True

        now = self._monotonic()
        self._prune(now)
        self._roll_day()

        if self._rpm > 0 and len(self._window) >= self._rpm:
            return False
        if self._rpd > 0 and self._day_used >= self._rpd:
            return False

        self._window.append(now)
        self._day_used += 1
        self._total_used += 1
        return True

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the current limiter usage."""
        now = self._monotonic()
        self._prune(now)
        self._roll_day()
        return {
            "rpm": self._rpm,
            "rpd": self._rpd,
            "minute_used": len(self._window),
            "day_used": self._day_used,
            "day_remaining": None if self._rpd <= 0 else max(0, self._rpd - self._day_used),
            "total_used": self._total_used,
        }

    def reset(self) -> None:
        """Clear all tracked usage (used on a full reset)."""
        self._window.clear()
        self._day_used = 0
        self._total_used = 0
        self._day = self._day_key()
