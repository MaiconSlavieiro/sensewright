"""ContextForge: build the per-Sim context once per "think" (v0.3 R3, §15.4).

Every cognition layer needs the same material: the Sim's profile, its recent
memories (which are ``touch``ed so recalling is remembering) and the cached world
context. ``ContextForge`` centralizes that so layers stay small. ``PairContext``
is the two-Sim variant used by the sim<->sim channel (L6, R5).
"""

from __future__ import annotations

from typing import Any


class ContextForge:
    """Assembles the profile + memories + world context for one Sim."""

    def __init__(self, memory: Any, settings: Any = None) -> None:
        self._memory = memory
        self._settings = settings

    async def build(self, job: Any, *, memories_limit: int = 10) -> dict[str, Any]:
        """Return ``{profile, memories, world, autonomy}`` for an impulse job.

        Never raises: a failing memory read yields an empty slice so an impulse
        can still run in native mode.
        """
        from ..memory.base import MemKey

        key = MemKey(job.player_id, job.save_id, int(job.sim_id))
        profile: dict[str, Any] = {}
        if self._memory is not None:
            try:
                profile = await self._memory.get_profile(key) or {}
            except Exception:
                profile = {}

        memories: list[Any] = []
        if self._memory is not None:
            try:
                memories = await self._memory.recent_events(key, limit=memories_limit)
            except Exception:
                memories = []
            ids = [event.get("id") for event in memories if event.get("id") is not None]
            if ids:
                try:
                    await self._memory.touch_events(key, ids)
                except Exception:
                    pass

        autonomy = str((profile or {}).get("autonomy") or "")

        return {
            "key": key,
            "profile": profile,
            "memories": memories,
            "world": {},
            "autonomy": autonomy,
        }


class PairContext:
    """Two-Sim context (both profiles + relationship + shared memories)."""

    def __init__(self, forge: ContextForge | None = None) -> None:
        self._forge = forge

    async def build(self, job_a: Any, job_b: Any, relationship: dict[str, Any] | None = None) -> dict[str, Any]:
        forge = self._forge or ContextForge(None)
        first = await forge.build(job_a)
        second = await forge.build(job_b)
        return {
            "a": first,
            "b": second,
            "relationship": dict(relationship or {}),
        }
