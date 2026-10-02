"""Speech policy enforcement (F11 / REQ-SOC-*).

Paces spoken lines with two wall-clock guards from the speech policy: at most
``max_lines_per_minute`` lines per rolling minute and at least
``min_interval_between_lines_seconds`` between consecutive lines. The policy is
evaluated before scheduling a ``sim.social`` call and recorded when lines are
emitted, so a chatty model cannot flood the dialogue UI.
"""
from __future__ import annotations

from typing import Any, List, Tuple

from ..constants import SPEECH_DEFAULTS

#: Rolling window for the lines-per-minute guard.
RATE_WINDOW_SECONDS = 60.0


def resolve_limits(config: Any = None) -> Tuple[int, float]:
    """Return ``(max_lines_per_minute, min_interval_seconds)`` from config."""
    max_lines = int(SPEECH_DEFAULTS["max_lines_per_minute"])
    min_interval = float(SPEECH_DEFAULTS["min_interval_between_lines_seconds"])
    if config is not None:
        try:
            max_lines = int(config.gameplay("max_lines_per_minute", max_lines))
            min_interval = float(
                config.gameplay("min_interval_between_lines_seconds", min_interval)
            )
        except Exception:  # noqa: BLE001 - config must never break speech
            pass
    return max_lines, min_interval


def prune(history: List[float], now: float) -> List[float]:
    """Drop entries older than the rolling window, keeping order."""
    return [t for t in (history or []) if now - float(t) < RATE_WINDOW_SECONDS]


def speech_allowed(
    history: List[float],
    now: float,
    max_lines_per_minute: int,
    min_interval_seconds: float,
) -> bool:
    """Whether a new spoken line is allowed by the speech policy."""
    recent = prune(history, now)
    if len(recent) >= int(max_lines_per_minute):
        return False
    if recent and (now - max(recent)) < float(min_interval_seconds):
        return False
    return True


def record_speech(history: List[float], now: float) -> List[float]:
    """Return the history with a new spoken line stamped at ``now``."""
    recent = prune(history, now)
    recent.append(float(now))
    return recent
