"""Directive safety rails: never-tools, player-priority lock, rate limiting, audit."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

NEVER_TOOLS: frozenset[str] = frozenset(
    {"delete_save", "modify_money", "kill_sim", "shell", "http", "spawn_npc_unbounded"}
)
DEFAULT_MAX_PER_MINUTE = 10
DEFAULT_PLAYER_LOCK_SECONDS = 10.0

_WINDOW_SECONDS = 60.0


@dataclass
class RailDecision:
    allowed: bool
    reason: str = ""
    tool_name: str = ""
    sim_key: str = ""


class DirectiveRails:
    """Evaluates whether a directive is safe to execute for a given Sim."""

    def __init__(
        self,
        *,
        max_per_minute: int = DEFAULT_MAX_PER_MINUTE,
        player_lock_seconds: float = DEFAULT_PLAYER_LOCK_SECONDS,
        never_tools: frozenset[str] | set[str] | None = None,
        audit: Any | None = None,
    ) -> None:
        self._max_per_minute = max_per_minute
        self._player_lock_seconds = player_lock_seconds
        self._never_tools = frozenset(never_tools) if never_tools is not None else NEVER_TOOLS
        self._audit = audit
        self._executed: dict[str, list[float]] = {}
        self._last_activity: dict[str, float] = {}

    def check(self, sim_key: str, tool_name: str) -> RailDecision:
        """Decide whether ``tool_name`` may run for ``sim_key`` right now."""
        now = time.monotonic()
        decision = self._decide(sim_key, tool_name, now)

        record = getattr(self._audit, "record", None)
        if callable(record):
            record(
                "tool_check",
                sim=sim_key,
                tool=tool_name,
                allowed=decision.allowed,
                reason=decision.reason,
            )

        return decision

    def _decide(self, sim_key: str, tool_name: str, now: float) -> RailDecision:
        if tool_name in self._never_tools:
            return RailDecision(
                allowed=False,
                reason="never_tool",
                tool_name=tool_name,
                sim_key=sim_key,
            )

        last_activity = self._last_activity.get(sim_key)
        if last_activity is not None and (now - last_activity) < self._player_lock_seconds:
            return RailDecision(
                allowed=False,
                reason="player_priority",
                tool_name=tool_name,
                sim_key=sim_key,
            )

        if self._count_in_window(sim_key, now) >= self._max_per_minute:
            return RailDecision(
                allowed=False,
                reason="rate_limited",
                tool_name=tool_name,
                sim_key=sim_key,
            )

        return RailDecision(allowed=True, reason="", tool_name=tool_name, sim_key=sim_key)

    def record_player_activity(self, sim_key: str, ts: float | None = None) -> None:
        """Mark the player as recently active for ``sim_key``."""
        self._last_activity[sim_key] = time.monotonic() if ts is None else ts

    def note_executed(self, sim_key: str, tool_name: str, ts: float | None = None) -> None:
        """Record that a directive was executed and trim stale entries."""
        now = time.monotonic() if ts is None else ts
        entries = self._executed.setdefault(sim_key, [])
        entries.append(now)
        cutoff = now - _WINDOW_SECONDS
        self._executed[sim_key] = [entry for entry in entries if entry > cutoff]

    def reset(self, sim_key: str | None = None) -> None:
        """Clear tracked state for one Sim, or all Sims when ``sim_key`` is None."""
        if sim_key is None:
            self._executed.clear()
            self._last_activity.clear()
        else:
            self._executed.pop(sim_key, None)
            self._last_activity.pop(sim_key, None)

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the rails state."""
        now = time.monotonic()
        sim_keys = set(self._executed) | set(self._last_activity)
        sims: dict[str, dict[str, Any]] = {}
        for key in sim_keys:
            sims[key] = {
                "executed_in_window": self._count_in_window(key, now),
                "last_player_activity": self._last_activity.get(key),
            }
        return {
            "max_per_minute": self._max_per_minute,
            "player_lock_seconds": self._player_lock_seconds,
            "never_tools": sorted(self._never_tools),
            "sims": sims,
        }

    def _count_in_window(self, sim_key: str, now: float) -> int:
        cutoff = now - _WINDOW_SECONDS
        return sum(1 for entry in self._executed.get(sim_key, []) if entry > cutoff)
