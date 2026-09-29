"""Fallback in-memory memory store for when SQLite fails."""

from __future__ import annotations

import logging
import time
from typing import Any

from ..memory.base import HouseholdKey, MemKey

logger = logging.getLogger(__name__)


class FallbackMemory:
    """In-memory fallback when SQLite is unavailable."""

    def __init__(self):
        self._profiles: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._reflections: dict[str, list[dict[str, Any]]] = {}
        self._neighborhoods: dict[tuple[str, str], dict[str, Any]] = {}
        self._households: dict[tuple[str, str, int], dict[str, Any]] = {}
        self._counter = 0

    def _key_str(self, key: MemKey) -> str:
        return str(key)

    async def upsert_profile(self, key: MemKey, profile: dict[str, Any]) -> None:
        self._profiles[self._key_str(key)] = profile

    async def get_profile(self, key: MemKey) -> dict[str, Any] | None:
        return self._profiles.get(self._key_str(key))

    async def list_profiles(self, player_id: str, save_id: str) -> list[dict[str, Any]]:
        prefix = f"{player_id}:{save_id}:"
        result: list[dict[str, Any]] = []
        for composite, profile in self._profiles.items():
            if not composite.startswith(prefix):
                continue
            sim_id_text = composite[len(prefix):]
            sim_id = int(sim_id_text) if sim_id_text.lstrip("-").isdigit() else 0
            result.append({"sim_id": sim_id, "profile": profile})
        result.sort(key=lambda entry: entry["sim_id"])
        return result

    async def add_event(self, key: MemKey, event: dict[str, Any]) -> int:
        self._counter += 1
        k = self._key_str(key)
        if k not in self._events:
            self._events[k] = []
        event_copy = event.copy()
        event_copy["id"] = self._counter
        import time
        event_copy["created_at"] = time.time()
        self._events[k].append(event_copy)
        return self._counter

    async def recent_events(
        self,
        key: MemKey,
        limit: int = 50,
        *,
        now: float | None = None,
        preset: str | None = None,
        min_strength: float | None = None,
    ) -> list[dict[str, Any]]:
        k = self._key_str(key)
        events = [e for e in self._events.get(k, []) if not e.get("consolidated")]
        return list(reversed(events[-limit:]))

    async def unconsolidated_events(self, key: MemKey, limit: int = 100) -> list[dict[str, Any]]:
        k = self._key_str(key)
        events = [
            e
            for e in self._events.get(k, [])
            if str(e.get("type")) == "chat" and not e.get("consolidated")
        ]
        return events[:limit]

    async def mark_consolidated(
        self, key: MemKey, event_ids: list[int], summary_event_id: int | None = None
    ) -> int:
        ids = {int(i) for i in (event_ids or [])}
        changed = 0
        for event in self._events.get(self._key_str(key), []):
            if event.get("id") in ids and not event.get("consolidated"):
                event["consolidated"] = 1
                changed += 1
        return changed

    async def touch_events(self, key: MemKey, event_ids: list[int]) -> int:
        ids = {int(i) for i in (event_ids or [])}
        changed = 0
        for event in self._events.get(self._key_str(key), []):
            if event.get("id") in ids:
                event["strength"] = min(1.0, float(event.get("strength", 1.0)) * 1.1 + 0.05)
                event["last_accessed_at"] = time.time()
                changed += 1
        return changed

    async def prune_forgotten(self, retention_days: int, now: float | None = None) -> int:
        return 0

    async def search_events(self, key: MemKey, query: str, limit: int = 10) -> list[dict[str, Any]]:
        k = self._key_str(key)
        events = self._events.get(k, [])
        query_lower = query.lower()
        matches = [
            e for e in reversed(events)
            if query_lower in str(e.get("content", "")).lower()
        ]
        return matches[:limit]

    async def set_sim_background(self, key: MemKey, background: dict[str, Any]) -> None:
        profile = self._profiles.get(self._key_str(key), {})
        profile["background"] = background
        self._profiles[self._key_str(key)] = profile

    async def add_reflection(self, key: MemKey, reflection: dict[str, Any]) -> int:
        import time

        self._counter += 1
        entry = {"id": self._counter, "content": dict(reflection), "created_at": time.time()}
        self._reflections.setdefault(self._key_str(key), []).append(entry)
        return self._counter

    async def recent_reflections(self, key: MemKey, limit: int = 10) -> list[dict[str, Any]]:
        entries = self._reflections.get(self._key_str(key), [])
        return list(entries[-limit:])

    async def upsert_neighborhood(self, player_id: str, save_id: str, data: dict[str, Any]) -> None:
        self._neighborhoods[(player_id, save_id)] = data

    async def get_neighborhood(self, player_id: str, save_id: str) -> dict[str, Any] | None:
        return self._neighborhoods.get((player_id, save_id))

    async def upsert_household(self, key: HouseholdKey, data: dict[str, Any]) -> None:
        self._households[(key.player_id, key.save_id, key.household_id)] = data

    async def get_household(self, key: HouseholdKey) -> dict[str, Any] | None:
        return self._households.get((key.player_id, key.save_id, key.household_id))

    async def list_households(self, player_id: str, save_id: str) -> list[dict[str, Any]]:
        result = []
        for (pid, sid, household_id), data in self._households.items():
            if pid == player_id and sid == save_id:
                result.append({"household_id": household_id, "data": data})
        result.sort(key=lambda entry: entry["household_id"])
        return result

    async def reset(self, scope: str, key: MemKey | None) -> dict[str, int]:
        deleted = {
            "sims": 0,
            "events": 0,
            "relationships": 0,
            "reflections": 0,
            "directives": 0,
            "neighborhoods": 0,
            "households": 0,
        }
        if scope == "sim" and key:
            k = self._key_str(key)
            if k in self._profiles:
                del self._profiles[k]
                deleted["sims"] = 1
            if k in self._events:
                deleted["events"] = len(self._events[k])
                del self._events[k]
            if k in self._reflections:
                deleted["reflections"] = len(self._reflections[k])
                del self._reflections[k]
        elif scope == "save" and key:
            deleted["neighborhoods"] = 1 if (key.player_id, key.save_id) in self._neighborhoods else 0
            self._neighborhoods.pop((key.player_id, key.save_id), None)
            removed = [
                hk
                for hk in self._households
                if hk[0] == key.player_id and hk[1] == key.save_id
            ]
            for hk in removed:
                del self._households[hk]
            deleted["households"] = len(removed)
        elif scope == "all":
            deleted["sims"] = len(self._profiles)
            deleted["events"] = sum(len(v) for v in self._events.values())
            deleted["reflections"] = sum(len(v) for v in self._reflections.values())
            deleted["neighborhoods"] = len(self._neighborhoods)
            deleted["households"] = len(self._households)
            self._profiles.clear()
            self._events.clear()
            self._reflections.clear()
            self._neighborhoods.clear()
            self._households.clear()
        return deleted

    async def stats(self) -> dict[str, Any]:
        return {
            "sims": len(self._profiles),
            "events": sum(len(v) for v in self._events.values()),
            "relationships": 0,
            "reflections": sum(len(v) for v in self._reflections.values()),
            "directives": 0,
            "neighborhoods": len(self._neighborhoods),
            "households": len(self._households),
            "db_path": "memory (fallback)",
        }

    async def close(self) -> None:
        pass