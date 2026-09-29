"""Memory provider protocol and key types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class MemKey:
    """Composite key for memory scoping: (player_id, save_id, sim_id)."""

    player_id: str
    save_id: str
    sim_id: int

    def __str__(self) -> str:
        return f"{self.player_id}:{self.save_id}:{self.sim_id}"


@dataclass(frozen=True)
class HouseholdKey:
    """Key for household-scoped data: (player_id, save_id, household_id)."""

    player_id: str
    save_id: str
    household_id: int

    def __str__(self) -> str:
        return f"{self.player_id}:{self.save_id}:{self.household_id}"


@runtime_checkable
class MemoryStore(Protocol):
    """Protocol for memory backends."""

    async def upsert_profile(self, key: MemKey, profile: dict[str, Any]) -> None:
        """Create or update a Sim's profile."""
        ...

    async def get_profile(self, key: MemKey) -> dict[str, Any] | None:
        """Get a Sim's profile."""
        ...

    async def list_profiles(self, player_id: str, save_id: str) -> list[dict[str, Any]]:
        """List every Sim profile for a save (id + profile), for batch loops."""
        ...

    async def add_event(self, key: MemKey, event: dict[str, Any]) -> int:
        """Add a memory event. Returns event ID."""
        ...

    async def recent_events(
        self,
        key: MemKey,
        limit: int = 50,
        *,
        now: float | None = None,
        preset: str | None = None,
        min_strength: float | None = None,
    ) -> list[dict[str, Any]]:
        """Get recent events for a Sim (oldest first, forgotten/archived excluded)."""
        ...

    async def search_events(self, key: MemKey, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search events (lexical or semantic)."""
        ...

    # ── v0.2 M1/M2: consolidation, strength decay and touch ───────────

    async def unconsolidated_events(self, key: MemKey, limit: int = 100) -> list[dict[str, Any]]:
        """Return the raw chat turns not yet folded into a consolidated memory."""
        ...

    async def mark_consolidated(
        self, key: MemKey, event_ids: list[int], summary_event_id: int | None = None
    ) -> int:
        """Archive raw turns; returns how many rows were flagged."""
        ...

    async def touch_events(self, key: MemKey, event_ids: list[int]) -> int:
        """Reset ``last_accessed_at`` and boost ``strength`` on used memories."""
        ...

    async def prune_forgotten(self, retention_days: int, now: float | None = None) -> int:
        """Delete memories weaker than the forget threshold past retention."""
        ...

    async def set_sim_background(self, key: MemKey, background: dict[str, Any]) -> None:
        """Merge a God-written background into the Sim's stored profile."""
        ...

    async def add_reflection(self, key: MemKey, reflection: dict[str, Any]) -> int:
        """Store a reflection output; returns its id."""
        ...

    async def recent_reflections(self, key: MemKey, limit: int = 10) -> list[dict[str, Any]]:
        """Get the most recent reflections for a Sim (oldest first)."""
        ...

    async def upsert_neighborhood(self, player_id: str, save_id: str, data: dict[str, Any]) -> None:
        """Create or update the neighborhood (zeitgeist + per-save overrides)."""
        ...

    async def get_neighborhood(self, player_id: str, save_id: str) -> dict[str, Any] | None:
        """Return the neighborhood data dict, or None when not configured."""
        ...

    async def upsert_household(self, key: HouseholdKey, data: dict[str, Any]) -> None:
        """Create or update a household record (background, members, ...)."""
        ...

    async def get_household(self, key: HouseholdKey) -> dict[str, Any] | None:
        """Return a household data dict, or None."""
        ...

    async def list_households(self, player_id: str, save_id: str) -> list[dict[str, Any]]:
        """List every household record for a save."""
        ...

    async def reset(self, scope: str, key: MemKey | None) -> dict[str, int]:
        """Clear memory by scope. Returns counts of deleted rows."""
        ...

    async def stats(self) -> dict[str, Any]:
        """Return storage statistics."""
        ...

    async def close(self) -> None:
        """Close the store."""
        ...