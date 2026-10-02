"""Transactional Shadow DB synchronization with The Sims 4 save slots.

Implements F10 §13.2 and REQ-MEM-01..04. Each TS4 save slot maps to a family
of files under ``data/saves/``:

* ``slot_<save_id>.committed.db`` — the exact state of the last hard save.
* ``slot_<save_id>.working.db``  — the active session (all reads/writes).
* ``slot_<save_id>.rev1..rev3.db`` — ring buffer of the last 3 checkpoints.

Isolation is achieved with :meth:`sqlite3.Connection.backup` (a fast file-level
snapshot, < 5ms). Exiting without saving (or crashing) never corrupts or
advances history: ``.working.db`` is simply discarded on the next session.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Dict, Optional

from .memory.sqlite_store import SqliteStore
from .observability.logging import get_logger

logger = get_logger("save_vault")

RING_BUFFER_SLOTS = 3


def _copy_db(src: str, dst: str) -> None:
    """Snapshot ``src`` into ``dst`` using SQLite's online backup API."""
    src_conn = sqlite3.connect(src)
    try:
        dst_conn = sqlite3.connect(dst)
        try:
            with dst_conn:
                src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


class SaveVault:
    """Owns the working/committed database files for all save slots."""

    def __init__(self, data_dir: Path) -> None:
        self._saves_dir = Path(data_dir) / "saves"
        self._saves_dir.mkdir(parents=True, exist_ok=True)
        self._active_save_id: Optional[int] = None
        self._working_store: Optional[SqliteStore] = None

    # ── path helpers ─────────────────────────────────────────────────────
    def committed_path(self, save_id: int) -> str:
        return str(self._saves_dir / "slot_{}.committed.db".format(int(save_id)))

    def working_path(self, save_id: int) -> str:
        return str(self._saves_dir / "slot_{}.working.db".format(int(save_id)))

    def rev_path(self, save_id: int, n: int) -> str:
        return str(self._saves_dir / "slot_{}.rev{}.db".format(int(save_id), int(n)))

    # ── state ────────────────────────────────────────────────────────────
    @property
    def active_save_id(self) -> Optional[int]:
        return self._active_save_id

    def working_store(self) -> Optional[SqliteStore]:
        """The active session store, or None when no session is attached."""
        return self._working_store

    def _close_working(self) -> None:
        if self._working_store is not None:
            self._working_store.close()
        self._working_store = None
        self._active_save_id = None

    # ── lifecycle ────────────────────────────────────────────────────────
    def session_start(self, save_id: int, world_sim_tick: int) -> Dict[str, Optional[int]]:
        """Load (or create) a save slot, discarding any residual working db.

        Returns ``{"restored_tick": int|None, "bootstrap_needed": bool}``.
        """
        self._close_working()
        save_id = int(save_id)
        committed = self.committed_path(save_id)
        working = self.working_path(save_id)

        # 1. Discard residual working db (crash / exit-without-save).
        if os.path.exists(working):
            os.remove(working)
            logger.info("discarded residual working db for save %s", save_id)

        if os.path.exists(committed):
            # 2. Clone committed -> working.
            _copy_db(committed, working)
            committed_tick = self._peek_committed_tick(committed)
            if committed_tick is not None and world_sim_tick < committed_tick:
                # 4. Rewind: the game save is older than our history (rollback).
                logger.warning(
                    "rewind requested: game tick %s < committed tick %s",
                    world_sim_tick, committed_tick,
                )
                self._rewind_to_tick(save_id, world_sim_tick)
            bootstrap_needed = False
            restored_tick = world_sim_tick
        else:
            # 3. New save slot: fresh working db.
            store = SqliteStore(working)
            store.initialize()
            store.set_tick(world_sim_tick)
            store.set_committed_tick(world_sim_tick)
            store.close()
            bootstrap_needed = True
            restored_tick = None

        store = SqliteStore(working)
        store.initialize()
        store.set_tick(world_sim_tick)
        self._working_store = store
        self._active_save_id = save_id
        return {"restored_tick": restored_tick, "bootstrap_needed": bootstrap_needed}

    def zone_transition(self, save_id: int, world_sim_tick: int) -> Dict[str, bool]:
        """Keep the working db intact; only tick metadata advances."""
        save_id = int(save_id)
        if self._working_store is None or self._active_save_id != save_id:
            self.session_start(save_id, world_sim_tick)
        self._working_store.set_tick(world_sim_tick)
        return {"ok": True}

    def save(
        self,
        save_id: int,
        previous_save_id: Optional[int],
        world_sim_tick: int,
    ) -> Dict[str, int]:
        """Promote working -> committed, rotating the ring buffer.

        On "Save As" (previous_save_id != save_id) the old committed db is left
        untouched and a new pair is created for the new slot.
        """
        save_id = int(save_id)
        working = self.working_path(save_id)
        committed = self.committed_path(save_id)

        # Flush RAM buffers into working db (the active store already holds them;
        # ensure the metadata tick is current).
        if self._working_store is not None and self._active_save_id == save_id:
            self._working_store.set_tick(world_sim_tick)
            self._working_store.set_committed_tick(world_sim_tick)
            self._working_store.close()
        else:
            store = SqliteStore(working)
            store.initialize()
            store.set_tick(world_sim_tick)
            store.set_committed_tick(world_sim_tick)
            store.close()

        # If this is a fresh slot with no committed file, create a baseline copy.
        if not os.path.exists(committed):
            _copy_db(working, committed)
        else:
            # Rotate ring buffer: shift old revisions, snapshot current committed.
            self._rotate_ring_buffer(save_id, committed)
            _copy_db(working, committed)

        # Re-open the working store for the continuing session.
        store = SqliteStore(working)
        store.initialize()
        self._working_store = store
        self._active_save_id = save_id

        snapshot_rev = self._working_store.snapshot_revision()
        logger.info("committed save %s at tick %s (rev %s)", save_id, world_sim_tick, snapshot_rev)
        return {"committed_tick": world_sim_tick, "snapshot_rev": snapshot_rev.get("world_sim_tick", world_sim_tick)}

    def _rotate_ring_buffer(self, save_id: int, committed: str) -> None:
        """Shift the ring buffer: rev2->rev3, rev1->rev2, committed->rev1."""
        rev1, rev2, rev3 = (
            self.rev_path(save_id, 1), self.rev_path(save_id, 2), self.rev_path(save_id, 3)
        )
        if os.path.exists(rev3):
            os.remove(rev3)
        if os.path.exists(rev2):
            os.rename(rev2, rev3)
        if os.path.exists(rev1):
            os.rename(rev1, rev2)
        _copy_db(committed, rev1)

    def _peek_committed_tick(self, committed: str) -> Optional[int]:
        try:
            conn = sqlite3.connect(committed)
            try:
                row = conn.execute(
                    "SELECT value FROM metadata WHERE key = 'world_sim_tick'"
                ).fetchone()
                return int(row[0]) if row else None
            finally:
                conn.close()
        except sqlite3.Error:
            return None

    def _rewind_to_tick(self, save_id: int, world_sim_tick: int) -> None:
        """Restore the ring-buffer snapshot nearest to (and <=) the game tick.

        Falls back to deleting memories created after the target tick.
        """
        working = self.working_path(save_id)
        best: Optional[str] = None
        best_tick = -1
        for n in range(1, RING_BUFFER_SLOTS + 1):
            path = self.rev_path(save_id, n)
            if not os.path.exists(path):
                continue
            tick = self._peek_committed_tick(path)
            if tick is None:
                continue
            if best_tick < tick <= world_sim_tick:
                best, best_tick = path, tick
        if best is not None:
            _copy_db(best, working)
            logger.info("restored ring-buffer snapshot at tick %s", best_tick)
            return

        # Fallback: surgical rewind (delegated to the store, under its lock).
        store = SqliteStore(working)
        store.initialize()
        store.rewind_to_tick(world_sim_tick)
        store.close()
        logger.info("surgical rewind to tick %s", world_sim_tick)

    def shutdown(self) -> None:
        """Close the active store cleanly (called by the process watchdog)."""
        self._close_working()
