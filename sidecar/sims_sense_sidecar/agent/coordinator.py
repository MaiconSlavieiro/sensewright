"""Single-writer arbitration between the Sim agent and the God agent (§14.5).

On a played Sim the Sim agent owns every action, mood and memory: the God must
never control it and may only reach it as broadcast knowledge. On an unplayed
Sim the God may act. ``Coordinator`` is a pure, dependency-free decision
function so the graph can call it with ``is_played`` taken from the census; it
holds no game state and produces no side effects. Denied directives are
reported (and logged) rather than silently dropped.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

WINNER_AGENT = "agent"
WINNER_GOD = "god"

REASON_ALLOWED = "allowed"
REASON_AGENT_OWNS_PLAYED = "agent_owns_played"
REASON_GOD_NEVER_CONTROLS_PLAYED = "god_never_controls_played"


class Coordinator:
    """Arbitrates who may write to a Sim (single-writer jurisdiction)."""

    def __init__(self) -> None:
        self._decisions = 0
        self._allowed = 0
        self._denied = 0
        self._by_source: dict[str, int] = {}
        self._last: dict[str, Any] | None = None

    def arbitrate(self, *, is_played: bool, source: str, tool_name: str = "") -> dict[str, Any]:
        """Decide whether a directive from ``source`` may be applied to a Sim.

        Returns ``{"allowed": bool, "winner": "agent"|"god", "reason": str}``.
        An agent directive is always allowed; a God directive is allowed only on
        an unplayed Sim (the agent owns played Sims).
        """
        src = (source or "").strip().lower() or WINNER_AGENT
        self._decisions += 1
        self._by_source[src] = self._by_source.get(src, 0) + 1

        if src == WINNER_AGENT:
            decision: dict[str, Any] = {
                "allowed": True,
                "winner": WINNER_AGENT,
                "reason": REASON_ALLOWED,
            }
        elif is_played:
            # A concrete control attempt is the sharper violation; a generic
            # God directive simply confirms the Sim is agent-owned.
            reason = REASON_GOD_NEVER_CONTROLS_PLAYED if tool_name else REASON_AGENT_OWNS_PLAYED
            decision = {"allowed": False, "winner": WINNER_AGENT, "reason": reason}
        else:
            decision = {"allowed": True, "winner": WINNER_GOD, "reason": REASON_ALLOWED}

        if decision["allowed"]:
            self._allowed += 1
        else:
            self._denied += 1
            logger.warning(
                "coordinator denied %s directive%s on played sim: %s",
                src,
                f" ({tool_name})" if tool_name else "",
                decision["reason"],
            )

        self._last = {
            "source": src,
            "is_played": is_played,
            "tool_name": tool_name,
            **decision,
        }
        return decision

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable view of arbitration counters."""
        return {
            "decisions": self._decisions,
            "allowed": self._allowed,
            "denied": self._denied,
            "by_source": dict(self._by_source),
            "last": dict(self._last) if self._last is not None else None,
        }
