"""Agent-seat pool (inhabitation layer L2, PLANO.md §15.4).

v0.3 R2 replaces "every Sim can act" with a configurable pool of ``agent_seats``.
Seats are handed out by priority: the active household first, then instanced
visitors. A seat is *runtime only* and is rebuilt from the census/zone pulse; a
Sim that leaves the lot frees its seat, but its memory persists (the memory
layer never depends on seat occupancy). The God covers Sims without a seat.

The manager holds no game state and performs no I/O: the graph feeds it census
and pulse snapshots, so it is deterministic and trivially testable.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

DEFAULT_SEATS = 12

TIER_HOUSEHOLD = "household"
TIER_VISITOR = "visitor"


@dataclass
class Seat:
    """A Sim currently occupying an agent seat."""

    sim_id: int
    tier: str = TIER_VISITOR
    household_id: int | None = None
    is_player: bool = False
    since: float = field(default=0.0)
    impulse_frequency: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "sim_id": self.sim_id,
            "tier": self.tier,
            "household_id": self.household_id,
            "is_player": self.is_player,
            "since": self.since,
            "impulse_frequency": self.impulse_frequency,
        }


def _as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class SeatManager:
    """Assigns and frees seats by priority, keyed by ``(player_id, save_id)``."""

    def __init__(
        self,
        seats: int = DEFAULT_SEATS,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._pool = max(1, int(seats))
        self._seats: dict[tuple[str, str], dict[int, Seat]] = {}
        self._present: dict[tuple[str, str], set[int]] = {}
        self._released = 0

    # ── configuration ─────────────────────────────────────────────────
    def configure(self, seats: int) -> None:
        """Resize the pool. Existing seats beyond the new size are dropped."""
        self._pool = max(1, int(seats))
        for key, bucket in list(self._seats.items()):
            if len(bucket) > self._pool:
                keep = sorted(bucket)[: self._pool]
                self._seats[key] = {sid: bucket[sid] for sid in keep}

    @property
    def pool(self) -> int:
        return self._pool

    # ── assignment ────────────────────────────────────────────────────
    def sync(
        self,
        player_id: str,
        save_id: str,
        sims: list[dict[str, Any]] | None,
        *,
        active_sim_id: int | None = None,
    ) -> dict[str, Any]:
        """Reconcile the seat pool against a zone/census snapshot.

        ``sims`` is a list of dicts with at least ``sim_id`` and optionally
        ``household_id``/``is_player``. Sims absent from the snapshot lose their
        seat (eviction on lot exit). Returns a small report.
        """
        key = (player_id, save_id)
        rows = [s for s in (sims or []) if _as_int(s.get("sim_id")) is not None]

        player_household = self._resolve_player_household(rows, active_sim_id)

        household: list[dict[str, Any]] = []
        visitors: list[dict[str, Any]] = []
        for row in rows:
            if player_household is not None and _as_int(row.get("household_id")) == player_household:
                household.append(row)
            else:
                visitors.append(row)
        household.sort(key=lambda r: _as_int(r.get("sim_id"), 0) or 0)
        visitors.sort(key=lambda r: _as_int(r.get("sim_id"), 0) or 0)
        household_ids = {_as_int(row.get("sim_id")) for row in household}

        current = self._seats.get(key, {})
        now = self._clock()
        assigned: dict[int, Seat] = {}
        for row in (household + visitors)[: self._pool]:
            sid = _as_int(row.get("sim_id"))
            if sid is None:
                continue
            existing = current.get(sid)
            assigned[sid] = Seat(
                sim_id=sid,
                tier=TIER_HOUSEHOLD if sid in household_ids else TIER_VISITOR,
                household_id=_as_int(row.get("household_id")),
                is_player=bool(row.get("is_player")),
                since=existing.since if existing is not None else now,
                impulse_frequency=existing.impulse_frequency if existing is not None else None,
            )

        evicted = sorted(sid for sid in current if sid not in assigned)
        self._seats[key] = assigned
        self._present[key] = {
            sid for sid in (_as_int(row.get("sim_id")) for row in rows) if sid is not None
        }
        self._released += len(evicted)
        return {
            "seats": self._pool,
            "used": len(assigned),
            "evicted": evicted,
            "household": len(household),
            "visitors": len(visitors),
        }

    @staticmethod
    def _resolve_player_household(
        rows: list[dict[str, Any]], active_sim_id: int | None
    ) -> int | None:
        if active_sim_id is not None:
            for row in rows:
                if _as_int(row.get("sim_id")) == _as_int(active_sim_id):
                    hh = _as_int(row.get("household_id"))
                    if hh is not None:
                        return hh
        for row in rows:
            if row.get("is_player"):
                return _as_int(row.get("household_id"))
        return None

    # ── queries / mutations ───────────────────────────────────────────
    def seats_for(self, player_id: str, save_id: str) -> list[dict[str, Any]]:
        bucket = self._seats.get((player_id, save_id), {})
        return [bucket[sid].to_dict() for sid in sorted(bucket)]

    def occupies(self, player_id: str, save_id: str, sim_id: int) -> bool:
        return _as_int(sim_id) in self._seats.get((player_id, save_id), {})

    def free(self, player_id: str, save_id: str, sim_id: int) -> bool:
        bucket = self._seats.get((player_id, save_id))
        if not bucket:
            return False
        if _as_int(sim_id) in bucket:
            del bucket[_as_int(sim_id)]
            self._released += 1
            return True
        return False

    def set_impulse_frequency(
        self, player_id: str, save_id: str, sim_id: int, frequency: float | None
    ) -> bool:
        seat = self._seats.get((player_id, save_id), {}).get(_as_int(sim_id))
        if seat is None:
            return False
        seat.impulse_frequency = None if frequency is None else max(0.0, min(1.0, float(frequency)))
        return True

    def frequency_for(self, player_id: str, save_id: str, sim_id: int) -> float | None:
        seat = self._seats.get((player_id, save_id), {}).get(_as_int(sim_id))
        return None if seat is None else seat.impulse_frequency

    def roster(self, player_id: str, save_id: str) -> dict[str, Any]:
        agents = self.seats_for(player_id, save_id)
        return {
            "seats": self._pool,
            "used": len(agents),
            "agents": agents,
        }

    def clear(self, player_id: str | None = None, save_id: str | None = None) -> None:
        if player_id is None or save_id is None:
            self._seats.clear()
            self._present.clear()
            return
        key = (player_id, save_id)
        self._seats.pop(key, None)
        self._present.pop(key, None)

    def snapshot(self) -> dict[str, Any]:
        used = sum(len(bucket) for bucket in self._seats.values())
        by_tier: dict[str, int] = {}
        for bucket in self._seats.values():
            for seat in bucket.values():
                by_tier[seat.tier] = by_tier.get(seat.tier, 0) + 1
        return {
            "pool": self._pool,
            "used": used,
            "saves": len(self._seats),
            "by_tier": by_tier,
            "released": self._released,
            # Active (player_id, save_id) pairs so a UI can discover the current
            # save without guessing.
            "active": [
                {"player_id": player_id, "save_id": save_id, "used": len(bucket)}
                for (player_id, save_id), bucket in sorted(self._seats.items())
                if bucket
            ],
        }
