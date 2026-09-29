"""
Directive safety rails for the SimsSense mod.

Mirror of the sidecar rails (never-tools, player-priority lock, rate limiting),
reimplemented for the game's embedded Python 3.7 (stdlib only). No game imports
are used, so this module imports and tests outside The Sims 4.

Reason codes: "never_tool", "player_priority", "rate_limited", or "" when allowed.
"""


import time

# Tools that must never be dispatched by the agent.
NEVER_TOOLS = frozenset({
    "delete_save",
    "modify_money",
    "kill_sim",
    "spawn_npc_unbounded",
})

DEFAULT_MAX_PER_MINUTE = 10
DEFAULT_PLAYER_LOCK_SECONDS = 10.0

_WINDOW_SECONDS = 60.0


class RailDecision(object):
    """Outcome of a rails check. Attributes: allowed, reason, tool_name, sim_id."""

    def __init__(self, allowed, reason="", tool_name="", sim_id=0):
        self.allowed = allowed
        self.reason = reason
        self.tool_name = tool_name
        self.sim_id = sim_id

    def __repr__(self):
        return (
            "RailDecision(allowed={!r}, reason={!r}, tool_name={!r}, sim_id={!r})"
            .format(self.allowed, self.reason, self.tool_name, self.sim_id)
        )


class DirectiveRails(object):
    """Evaluates whether a directive is safe to execute for a given Sim."""

    def __init__(self, max_per_minute=DEFAULT_MAX_PER_MINUTE, player_lock_seconds=DEFAULT_PLAYER_LOCK_SECONDS):
        self._max_per_minute = max_per_minute
        self._player_lock_seconds = player_lock_seconds
        self._never_tools = NEVER_TOOLS
        self._executed = {}
        self._last_activity = {}

    def check(self, sim_id, tool_name):
        """Decide whether ``tool_name`` may run for ``sim_id`` right now."""
        now = time.monotonic()
        return self._decide(sim_id, tool_name, now)

    def _decide(self, sim_id, tool_name, now):
        if tool_name in self._never_tools:
            return RailDecision(False, "never_tool", tool_name, sim_id)

        last_activity = self._last_activity.get(sim_id)
        if last_activity is not None and (now - last_activity) < self._player_lock_seconds:
            return RailDecision(False, "player_priority", tool_name, sim_id)

        if self._count_in_window(sim_id, now) >= self._max_per_minute:
            return RailDecision(False, "rate_limited", tool_name, sim_id)

        return RailDecision(True, "", tool_name, sim_id)

    def record_player_activity(self, sim_id, ts=None):
        """Mark the player as recently active for ``sim_id``."""
        self._last_activity[sim_id] = time.monotonic() if ts is None else ts

    def note_executed(self, sim_id, tool_name, ts=None):
        """Record that a directive was executed and trim stale entries."""
        now = time.monotonic() if ts is None else ts
        entries = self._executed.setdefault(sim_id, [])
        entries.append(now)
        cutoff = now - _WINDOW_SECONDS
        self._executed[sim_id] = [entry for entry in entries if entry > cutoff]

    def reset(self, sim_id=None):
        """Clear tracked state for one Sim, or all Sims when ``sim_id`` is None."""
        if sim_id is None:
            self._executed.clear()
            self._last_activity.clear()
        else:
            self._executed.pop(sim_id, None)
            self._last_activity.pop(sim_id, None)

    def snapshot(self):
        """Return a JSON-serializable view of the rails state."""
        now = time.monotonic()
        sim_ids = set(self._executed) | set(self._last_activity)
        sims = {}
        for sim_id in sim_ids:
            sims[str(sim_id)] = {
                "executed_in_window": self._count_in_window(sim_id, now),
                "last_player_activity": self._last_activity.get(sim_id),
            }
        return {
            "max_per_minute": self._max_per_minute,
            "player_lock_seconds": self._player_lock_seconds,
            "never_tools": sorted(self._never_tools),
            "sims": sims,
        }

    def _count_in_window(self, sim_id, now):
        cutoff = now - _WINDOW_SECONDS
        return sum(1 for entry in self._executed.get(sim_id, []) if entry > cutoff)
