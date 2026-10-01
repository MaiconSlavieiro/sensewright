"""Intent model + bus (v0.3 R3, PLANO.md §15.4/§15.5).

The v0.2 command palette becomes an **intent bus**: an agent emits *intents*
(``bias_interaction``, ``set_mood``, ``approach`` …) that the mod's ``GameLever``
adapter translates into native levers or, failing that, a gated candidate in the
interaction queue. A minimal, gated direct command remains as an escape hatch.

For wire/back-compat each stored intent still carries the legacy directive keys
(``name``/``args``/``thought``/``narration``); the mod can choose to use
``kind`` first and fall back to the command. This keeps the existing
``/v1/autonomy/directives`` alias working while ``/v1/autonomy/intents`` exposes
the richer shape.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import uuid4

# Valid intent kinds (PLANO.md §15.5) plus the transitional ``command`` escape hatch.
INTENT_KINDS = (
    "bias_interaction",
    "prefer_target",
    "set_mood",
    "set_goal",
    "approach",
    "speak",
    "remember",
    "forget",
    "command",
)

# Tool name -> intent kind. Unlisted tools fall back to the ``command`` escape hatch.
TOOL_TO_INTENT = {
    "spontaneous_line": "speak",
    "say_to": "speak",
    "socialize": "speak",
    "set_mood": "set_mood",
    "add_buff": "set_mood",
    "approach": "approach",
    "move_to": "approach",
    "queue_interaction": "bias_interaction",
    "act_out": "bias_interaction",
    "add_trait": "set_goal",
}

# Default intent lifetime; "next_sleep" means the bias drops after sleep cognition.
DEFAULT_EXPIRES_AT = "next_sleep"


def _as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def intent_from_directive(
    sim_id: int,
    raw: dict[str, Any],
    *,
    priority: int = 0,
    source: str = "agent",
) -> dict[str, Any] | None:
    """Convert a legacy directive (tool call) into an intent, keeping its keys."""
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or "").strip()
    if not name:
        return None
    args = raw.get("args")
    if not isinstance(args, dict):
        args = {}

    kind = TOOL_TO_INTENT.get(name, "command")
    target = _as_int(args.get("target_sim_id"))
    reason = str(raw.get("narration") or raw.get("thought") or args.get("reason") or "")

    return {
        "id": str(raw.get("id") or uuid4().hex),
        "sim_id": _as_int(raw.get("sim_id", sim_id), sim_id) or sim_id,
        "kind": kind,
        "target_sim_id": target,
        "params": dict(args),
        "reason": reason,
        "expires_at": raw.get("expires_at") or DEFAULT_EXPIRES_AT,
        "priority": _as_int(raw.get("priority", priority), priority) or 0,
        "source": str(raw.get("source") or source),
        # Legacy/directive-compatible fields (kept for the escape hatch + alias).
        "name": name,
        "args": dict(args),
        "thought": str(raw.get("thought") or ""),
        "narration": str(raw.get("narration") or ""),
    }


def normalize_intent(raw: dict[str, Any], *, default_sim_id: int = 0) -> dict[str, Any] | None:
    """Coerce an arbitrary intent mapping into the canonical shape."""
    if not isinstance(raw, dict):
        return None
    sim_id = _as_int(raw.get("sim_id", default_sim_id), default_sim_id) or default_sim_id
    kind = str(raw.get("kind") or "").strip()
    if not kind:
        return None
    if kind not in INTENT_KINDS:
        kind = "command"
    params = raw.get("params")
    if not isinstance(params, dict):
        params = {}
    name = str(raw.get("name") or "")
    args = raw.get("args")
    if not isinstance(args, dict):
        args = {}
    # A command intent may only carry its tool via the legacy keys.
    if kind == "command" and not name and not args:
        return None
    return {
        "id": str(raw.get("id") or uuid4().hex),
        "sim_id": sim_id,
        "kind": kind,
        "target_sim_id": _as_int(raw.get("target_sim_id", params.get("target_sim_id"))),
        "params": dict(params),
        "reason": str(raw.get("reason") or ""),
        "expires_at": raw.get("expires_at") or DEFAULT_EXPIRES_AT,
        "priority": _as_int(raw.get("priority"), 0) or 0,
        "source": str(raw.get("source") or "agent"),
        "name": name,
        "args": dict(args),
        "thought": str(raw.get("thought") or ""),
        "narration": str(raw.get("narration") or ""),
    }


class IntentBus:
    """Pending-intent store keyed by ``(player_id, save_id)``.

    Intents are appended (not deduplicated) and drained by ``pull`` in FIFO
    order, optionally filtered by Sim and bounded by ``limit``.
    """

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], list[dict[str, Any]]] = {}
        # Last sleep-consolidation wall-clock per Sim; "next_sleep" intents stored
        # before it are considered expired (v0.3 R3 lifecycle enforcement).
        self._sleep_at: dict[tuple[str, str, int], float] = {}
        self._stored = 0
        self._pulled = 0
        self._expired = 0

    def store(self, player_id: str, save_id: str, intent: dict[str, Any]) -> None:
        # Copy so the caller's mapping is never mutated, and stamp the lifecycle
        # clock used to expire "next_sleep" intents.
        stored = dict(intent)
        stored.setdefault("expires_at", DEFAULT_EXPIRES_AT)
        stored.setdefault("stored_at", time.time())
        self._pending.setdefault((player_id, save_id), []).append(stored)
        self._stored += 1

    def note_sleep(self, player_id: str, save_id: str, sim_id: int, ts: float | None = None) -> None:
        """Mark that a Sim slept: invalidates its pending ``next_sleep`` intents."""
        try:
            key = (player_id, save_id, int(sim_id))
        except (TypeError, ValueError):
            return
        self._sleep_at[key] = time.time() if ts is None else float(ts)

    def extend(self, player_id: str, save_id: str, intents: list[dict[str, Any]]) -> int:
        count = 0
        for intent in intents:
            if isinstance(intent, dict):
                self.store(player_id, save_id, intent)
                count += 1
        return count

    def pull(
        self,
        player_id: str,
        save_id: str,
        *,
        sim_id: int | None = None,
        limit: int = 20,
        now: float | None = None,
    ) -> list[dict[str, Any]]:
        key = (player_id, save_id)
        bucket = self._pending.get(key)
        if not bucket:
            return []
        limit = max(0, int(limit))
        reference = time.time() if now is None else float(now)

        taken: list[dict[str, Any]] = []
        remaining: list[dict[str, Any]] = []
        for intent in bucket:
            if self._is_expired(player_id, save_id, intent, reference):
                self._expired += 1
                continue
            if len(taken) >= limit:
                remaining.append(intent)
                continue
            if sim_id is not None and intent.get("sim_id") != int(sim_id):
                remaining.append(intent)
                continue
            taken.append(intent)

        if remaining:
            self._pending[key] = remaining
        else:
            self._pending.pop(key, None)
        self._pulled += len(taken)
        return taken

    def _is_expired(
        self, player_id: str, save_id: str, intent: dict[str, Any], now: float
    ) -> bool:
        """Evaluate an intent's ``expires_at`` lifecycle (v0.3 R3).

        A numeric value is an absolute wall-clock deadline. ``"next_sleep"``
        expires once the owning Sim has slept since the intent was stored.
        Unknown values never expire.
        """
        expires = intent.get("expires_at")
        if isinstance(expires, (int, float)) and not isinstance(expires, bool):
            try:
                return float(expires) <= now
            except (TypeError, ValueError):
                return False
        if isinstance(expires, str) and expires.strip().lower() == "next_sleep":
            try:
                sim_id = int(intent.get("sim_id", 0))
            except (TypeError, ValueError):
                return False
            sleep_at = self._sleep_at.get((player_id, save_id, sim_id))
            if sleep_at is None:
                return False
            try:
                stored = float(intent.get("stored_at", 0.0))
            except (TypeError, ValueError):
                return False
            return stored < float(sleep_at)
        return False

    def pending_count(self, player_id: str | None = None, save_id: str | None = None) -> int:
        if player_id is not None and save_id is not None:
            return len(self._pending.get((player_id, save_id), []))
        return sum(len(bucket) for bucket in self._pending.values())

    def clear(self, player_id: str | None = None, save_id: str | None = None) -> None:
        if player_id is None or save_id is None:
            self._pending.clear()
            self._sleep_at.clear()
            return
        self._pending.pop((player_id, save_id), None)

    def snapshot(self) -> dict[str, Any]:
        by_kind: dict[str, int] = {}
        for bucket in self._pending.values():
            for intent in bucket:
                kind = str(intent.get("kind") or "command")
                by_kind[kind] = by_kind.get(kind, 0) + 1
        return {
            "pending": self.pending_count(),
            "by_kind": by_kind,
            "stored": self._stored,
            "pulled": self._pulled,
            "expired": self._expired,
        }
