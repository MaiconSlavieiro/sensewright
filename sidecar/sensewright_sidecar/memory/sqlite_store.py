"""SQLite persistence with FTS5 (BM25) full-text memory search (REQ-MEM-05).

Implements the ``slot_<save_id>.db`` schema from F10 §13.1:

* ``metadata``      — save id, sim tick, last committed tick, schema version
* ``memories``      — raw + consolidated memories with importance/strength/decay
* ``memories_fts``  — virtual FTS5 table (external content) ranking via BM25
* ``relationships`` — friendship/romance + known traits/secrets + qualitative notes
* ``sims``          — sim profile JSON + background
* ``arcs``          — God Director narrative arcs and beats
* ``neighborhoods`` — zeitgeist, chronicles, rumors (world layer)

The store is bound to a single database file path. All writes go through a
process-level lock so the FastAPI thread pool can share one store safely.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any, Dict, Iterable, List, Optional, Tuple

SCHEMA_VERSION = 2

#: SQLite FTS5 is expected (bundled in CPython 3.12). If missing, fall back to
#: a LIKE-based scan (extremely unlikely).
_FTS_AVAILABLE = True

_MEMORY_COLUMNS = (
    "id", "sim_id", "type", "content", "search_text", "importance",
    "strength", "created_sim_tick", "last_accessed_sim_tick",
    "consolidated", "archived",
)

_SCHEMA_STATEMENTS: List[str] = [
    """
    CREATE TABLE IF NOT EXISTS metadata (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sim_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        content TEXT NOT NULL,
        search_text TEXT NOT NULL DEFAULT '',
        importance REAL NOT NULL DEFAULT 1.0,
        strength REAL NOT NULL DEFAULT 1.0,
        created_sim_tick INTEGER NOT NULL DEFAULT 0,
        last_accessed_sim_tick INTEGER NOT NULL DEFAULT 0,
        consolidated INTEGER NOT NULL DEFAULT 0,
        archived INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_memories_sim_tick
        ON memories (sim_id, created_sim_tick)
    """,
    """
    CREATE TABLE IF NOT EXISTS relationships (
        sim_id INTEGER NOT NULL,
        target_id INTEGER NOT NULL,
        friendship REAL NOT NULL DEFAULT 0,
        romance REAL NOT NULL DEFAULT 0,
        known_traits TEXT NOT NULL DEFAULT '[]',
        known_secrets TEXT NOT NULL DEFAULT '[]',
        dynamic_label TEXT NOT NULL DEFAULT '',
        qualitative_note TEXT NOT NULL DEFAULT '',
        updated_sim_tick INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (sim_id, target_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS sims (
        sim_id INTEGER PRIMARY KEY,
        profile TEXT NOT NULL DEFAULT '{}',
        background TEXT NOT NULL DEFAULT '',
        updated_sim_tick INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS arcs (
        id TEXT PRIMARY KEY,
        theme TEXT NOT NULL DEFAULT '',
        beats TEXT NOT NULL DEFAULT '[]',
        current_beat_idx INTEGER NOT NULL DEFAULT 0,
        cast TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'draft',
        created_sim_tick INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS neighborhoods (
        save_id INTEGER PRIMARY KEY,
        zeitgeist TEXT NOT NULL DEFAULT '{}',
        chronicles TEXT NOT NULL DEFAULT '[]',
        rumors TEXT NOT NULL DEFAULT '[]',
        updated_sim_tick INTEGER NOT NULL DEFAULT 0
    )
    """,
]

_FTS_STATEMENTS: List[str] = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
        search_text,
        content='memories',
        content_rowid='id',
        tokenize='unicode61'
    )
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, search_text) VALUES (new.id, new.search_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, search_text)
            VALUES ('delete', old.id, old.search_text);
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, search_text)
            VALUES ('delete', old.id, old.search_text);
        INSERT INTO memories_fts(rowid, search_text) VALUES (new.id, new.search_text);
    END
    """,
]


class SqliteStore:
    """Thread-safe facade over a single Sensewright SQLite database file."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None

    # ── connection management ────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            conn = sqlite3.connect(self._path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._conn = conn
        return self._conn

    def initialize(self) -> None:
        """Create tables, indexes and FTS triggers if absent."""
        with self._lock:
            conn = self._connect()
            with conn:
                for statement in _SCHEMA_STATEMENTS:
                    conn.execute(statement)
                try:
                    for statement in _FTS_STATEMENTS:
                        conn.execute(statement)
                except sqlite3.OperationalError:
                    # FTS5 unavailable: degrade gracefully to LIKE search.
                    global _FTS_AVAILABLE
                    _FTS_AVAILABLE = False
            self._set_meta("schema_version", str(SCHEMA_VERSION))

    def close(self) -> None:
        """Close the underlying connection safely (called on shutdown/watchdog)."""
        with self._lock:
            if self._conn is not None:
                try:
                    self._conn.close()
                finally:
                    self._conn = None

    # ── metadata ─────────────────────────────────────────────────────────
    def _set_meta(self, key: str, value: Any) -> None:
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            (key, str(value)),
        )
        conn.commit()

    def _get_meta(self, key: str, default: Any = None) -> Any:
        conn = self._connect()
        row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def get_tick(self) -> int:
        return int(self._get_meta("world_sim_tick", 0) or 0)

    def set_tick(self, tick: int) -> None:
        self._set_meta("world_sim_tick", int(tick))

    def get_committed_tick(self) -> int:
        return int(self._get_meta("last_committed_at", 0) or 0)

    def set_committed_tick(self, tick: int) -> None:
        self._set_meta("last_committed_at", int(tick))

    # ── memories ─────────────────────────────────────────────────────────
    def add_memory(
        self,
        sim_id: int,
        memory_type: str,
        content: Dict[str, Any],
        search_text: str = "",
        importance: float = 1.0,
        strength: float = 1.0,
        created_sim_tick: int = 0,
        consolidated: bool = False,
        archived: bool = False,
    ) -> int:
        """Insert a memory and return its id."""
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                """INSERT INTO memories
                   (sim_id, type, content, search_text, importance, strength,
                    created_sim_tick, last_accessed_sim_tick, consolidated, archived)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(sim_id), memory_type, json.dumps(content, ensure_ascii=False),
                    search_text, float(importance), float(strength),
                    int(created_sim_tick), int(created_sim_tick),
                    int(consolidated), int(archived),
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def get_memory(self, memory_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM memories WHERE id = ?", (int(memory_id),)).fetchone()
        return self._row_memory(row) if row else None

    def _row_memory(self, row: sqlite3.Row) -> Dict[str, Any]:
        result = dict(row)
        result["content"] = json.loads(result["content"]) if result.get("content") else {}
        return result

    def recent_memories(
        self, sim_id: int, limit: int = 20, include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """Most recent memories for a sim, newest first."""
        conn = self._connect()
        query = "SELECT * FROM memories WHERE sim_id = ?"
        params: List[Any] = [int(sim_id)]
        if not include_archived:
            query += " AND archived = 0"
        query += " ORDER BY created_sim_tick DESC LIMIT ?"
        params.append(int(limit))
        rows = conn.execute(query, params).fetchall()
        return [self._row_memory(r) for r in rows]

    def search_memories(
        self, sim_id: Optional[int], query: str, limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Full-text search over memories. BM25-ranked when FTS5 is available."""
        if not query.strip():
            return []
        with self._lock:
            conn = self._connect()
            if _FTS_AVAILABLE:
                where = ""
                params: List[Any] = []
                if sim_id is not None:
                    where = " AND m.sim_id = ?"
                    params.append(int(sim_id))
                sql = (
                    "SELECT m.*, bm25(memories_fts) AS rank "
                    "FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid "
                    "WHERE memories_fts MATCH ?" + where +
                    " ORDER BY rank LIMIT ?"
                )
                params = [query] + params + [int(limit)]
            else:
                like = "%" + query.replace("%", "").replace("_", "") + "%"
                where = "m.search_text LIKE ?"
                params = [like]
                if sim_id is not None:
                    where += " AND m.sim_id = ?"
                    params.append(int(sim_id))
                sql = "SELECT m.*, 0 AS rank FROM memories m WHERE " + where + " ORDER BY m.created_sim_tick DESC LIMIT ?"
                params.append(int(limit))
            try:
                rows = conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                rows = []
        return [self._row_memory(r) for r in rows]

    def decay_memories(self, sim_id: int, decayed_strength: Dict[int, float]) -> None:
        """Apply exponential decay to a batch of memory strengths."""
        with self._lock:
            conn = self._connect()
            with conn:
                for memory_id, new_strength in decayed_strength.items():
                    conn.execute(
                        "UPDATE memories SET strength = ? WHERE id = ?",
                        (float(new_strength), int(memory_id)),
                    )

    def archive_memories(self, memory_ids: Iterable[int]) -> None:
        """Mark memories as archived (they are kept, never hard-deleted)."""
        ids = [int(i) for i in memory_ids]
        if not ids:
            return
        with self._lock:
            conn = self._connect()
            with conn:
                conn.executemany(
                    "UPDATE memories SET archived = 1 WHERE id = ?", [(i,) for i in ids]
                )

    def prune_trivial_memories(self, before_sim_tick: int) -> int:
        """Hard-delete only trivial raw memories older than the retention window.

        Never deletes consolidated, compacted, diary or legacy memories.
        (REQ-MEM-06)
        """
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                """DELETE FROM memories
                   WHERE archived = 1 AND importance < 1.0
                     AND consolidated = 0 AND type NOT IN ('diary', 'legacy', 'compact', 'dream')
                     AND created_sim_tick < ?""",
                (int(before_sim_tick),),
            )
            conn.commit()
            return cursor.rowcount

    def mark_consolidated(self, memory_ids: Iterable[int], tick: int) -> None:
        ids = [int(i) for i in memory_ids]
        if not ids:
            return
        with self._lock:
            conn = self._connect()
            with conn:
                conn.executemany(
                    "UPDATE memories SET consolidated = 1, last_accessed_sim_tick = ? WHERE id = ?",
                    [(int(tick), i) for i in ids],
                )

    def count_consolidated(self, sim_id: int) -> int:
        conn = self._connect()
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM memories WHERE sim_id = ? AND consolidated = 1 AND archived = 0",
            (int(sim_id),),
        ).fetchone()
        return int(row["c"]) if row else 0

    # ── relationships ────────────────────────────────────────────────────
    def upsert_relationship(
        self,
        sim_id: int,
        target_id: int,
        friendship: Optional[float] = None,
        romance: Optional[float] = None,
        known_traits: Optional[List[str]] = None,
        known_secrets: Optional[List[str]] = None,
        dynamic_label: Optional[str] = None,
        qualitative_note: Optional[str] = None,
        updated_sim_tick: int = 0,
    ) -> None:
        existing = self.get_relationship(sim_id, target_id)
        with self._lock:
            conn = self._connect()
            new_friendship = friendship if friendship is not None else existing["friendship"]
            new_romance = romance if romance is not None else existing["romance"]
            merged_traits = existing["known_traits"] if known_traits is None else known_traits
            merged_secrets = existing["known_secrets"] if known_secrets is None else known_secrets
            new_label = dynamic_label if dynamic_label is not None else existing["dynamic_label"]
            new_note = qualitative_note if qualitative_note is not None else existing["qualitative_note"]
            conn.execute(
                """INSERT OR REPLACE INTO relationships
                   (sim_id, target_id, friendship, romance, known_traits, known_secrets,
                    dynamic_label, qualitative_note, updated_sim_tick)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    int(sim_id), int(target_id),
                    float(new_friendship), float(new_romance),
                    json.dumps(merged_traits, ensure_ascii=False),
                    json.dumps(merged_secrets, ensure_ascii=False),
                    new_label, new_note, int(updated_sim_tick),
                ),
            )
            conn.commit()

    def get_relationship(self, sim_id: int, target_id: int) -> Dict[str, Any]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM relationships WHERE sim_id = ? AND target_id = ?",
            (int(sim_id), int(target_id)),
        ).fetchone()
        if row is None:
            return {
                "sim_id": int(sim_id), "target_id": int(target_id),
                "friendship": 0.0, "romance": 0.0,
                "known_traits": [], "known_secrets": [],
                "dynamic_label": "", "qualitative_note": "", "updated_sim_tick": 0,
            }
        result = dict(row)
        result["known_traits"] = json.loads(result.get("known_traits") or "[]")
        result["known_secrets"] = json.loads(result.get("known_secrets") or "[]")
        return result

    def add_known_secret(self, sim_id: int, target_id: int, secret: str, tick: int) -> None:
        rel = self.get_relationship(sim_id, target_id)
        secrets = list(rel["known_secrets"])
        if secret not in secrets:
            secrets.append(secret)
        self.upsert_relationship(
            sim_id, target_id, known_secrets=secrets, updated_sim_tick=tick,
        )

    # ── sims ─────────────────────────────────────────────────────────────
    def upsert_sim_profile(self, sim_id: int, profile: Dict[str, Any], tick: int = 0) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                """INSERT OR REPLACE INTO sims (sim_id, profile, background, updated_sim_tick)
                   VALUES (?, ?, (SELECT background FROM sims WHERE sim_id = ?), ?)""",
                (int(sim_id), json.dumps(profile, ensure_ascii=False), int(sim_id), int(tick)),
            )
            conn.commit()

    def get_sim_profile(self, sim_id: int) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM sims WHERE sim_id = ?", (int(sim_id),)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["profile"] = json.loads(result.get("profile") or "{}")
        return result

    def set_sim_background(self, sim_id: int, background: str, tick: int = 0) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE sims SET background = ?, updated_sim_tick = ? WHERE sim_id = ?",
                (background, int(tick), int(sim_id)),
            )
            conn.commit()

    # ── arcs ─────────────────────────────────────────────────────────────
    def save_arc(self, arc: Dict[str, Any]) -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                """INSERT OR REPLACE INTO arcs
                   (id, theme, beats, current_beat_idx, cast, status, created_sim_tick)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    arc["id"], arc.get("theme", ""),
                    json.dumps(arc.get("beats", []), ensure_ascii=False),
                    int(arc.get("current_beat_idx", 0)),
                    json.dumps(arc.get("cast", []), ensure_ascii=False),
                    arc.get("status", "draft"),
                    int(arc.get("created_sim_tick", 0)),
                ),
            )
            conn.commit()

    def get_arc(self, arc_id: str) -> Optional[Dict[str, Any]]:
        conn = self._connect()
        row = conn.execute("SELECT * FROM arcs WHERE id = ?", (arc_id,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["beats"] = json.loads(result.get("beats") or "[]")
        result["cast"] = json.loads(result.get("cast") or "[]")
        return result

    def list_arcs(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        conn = self._connect()
        if status is None:
            rows = conn.execute("SELECT * FROM arcs ORDER BY created_sim_tick DESC").fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM arcs WHERE status = ? ORDER BY created_sim_tick DESC", (status,)
            ).fetchall()
        result = []
        for row in rows:
            arc = dict(row)
            arc["beats"] = json.loads(arc.get("beats") or "[]")
            arc["cast"] = json.loads(arc.get("cast") or "[]")
            result.append(arc)
        return result

    # ── neighborhoods ────────────────────────────────────────────────────
    def get_neighborhood(self, save_id: int) -> Dict[str, Any]:
        conn = self._connect()
        row = conn.execute(
            "SELECT * FROM neighborhoods WHERE save_id = ?", (int(save_id),)
        ).fetchone()
        if row is None:
            return {
                "save_id": int(save_id),
                "zeitgeist": {}, "chronicles": [], "rumors": [], "updated_sim_tick": 0,
            }
        result = dict(row)
        result["zeitgeist"] = json.loads(result.get("zeitgeist") or "{}")
        result["chronicles"] = json.loads(result.get("chronicles") or "[]")
        result["rumors"] = json.loads(result.get("rumors") or "[]")
        return result

    def set_neighborhood(
        self,
        save_id: int,
        zeitgeist: Optional[Dict[str, Any]] = None,
        chronicles: Optional[List[Any]] = None,
        rumors: Optional[List[Any]] = None,
        tick: int = 0,
    ) -> None:
        current = self.get_neighborhood(save_id)
        merged_zeitgeist = current["zeitgeist"] if zeitgeist is None else zeitgeist
        merged_chronicles = current["chronicles"] if chronicles is None else chronicles
        merged_rumors = current["rumors"] if rumors is None else rumors
        with self._lock:
            conn = self._connect()
            conn.execute(
                """INSERT OR REPLACE INTO neighborhoods
                   (save_id, zeitgeist, chronicles, rumors, updated_sim_tick)
                   VALUES (?, ?, ?, ?, ?)""",
                (
                    int(save_id),
                    json.dumps(merged_zeitgeist, ensure_ascii=False),
                    json.dumps(merged_chronicles, ensure_ascii=False),
                    json.dumps(merged_rumors, ensure_ascii=False),
                    int(tick),
                ),
            )
            conn.commit()

    # ── maintenance ──────────────────────────────────────────────────────
    def rewind_to_tick(self, tick: int) -> None:
        """Surgically roll back rows created/updated after ``tick`` (REQ-MEM-04).

        Deletes only raw memories created after the target tick and clamps the
        ``updated_sim_tick`` of sims/relationships. Consolidated, diary, legacy
        and compact memories are never touched by this surgical path.
        """
        tick = int(tick)
        with self._lock:
            conn = self._connect()
            with conn:
                conn.execute(
                    "DELETE FROM memories WHERE created_sim_tick > ?", (tick,)
                )
                conn.execute(
                    "UPDATE sims SET updated_sim_tick = ? WHERE updated_sim_tick > ?",
                    (tick, tick),
                )
                conn.execute(
                    "UPDATE relationships SET updated_sim_tick = ? WHERE updated_sim_tick > ?",
                    (tick, tick),
                )
        self.set_tick(tick)
        self.set_committed_tick(tick)

    def vacuum(self) -> None:
        """Reclaim space after a compaction (REQ-MEM-06 / A9)."""
        with self._lock:
            conn = self._connect()
            conn.execute("PRAGMA incremental_vacuum")
            conn.commit()

    def snapshot_revision(self) -> Dict[str, Any]:
        """Return a compact summary of the current database state."""
        return {
            "schema_version": SCHEMA_VERSION,
            "world_sim_tick": self.get_tick(),
            "last_committed_at": self.get_committed_tick(),
        }
