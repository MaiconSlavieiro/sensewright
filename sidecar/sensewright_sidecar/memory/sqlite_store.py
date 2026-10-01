"""SQLite memory store implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import threading
import time
from typing import Any

from ..config import Settings
from .base import HouseholdKey, MemKey, MemoryStore
from .decay import annotate, effective_strength, touch_strength
from .embeddings import build_embedding_provider, cosine_similarity

logger = logging.getLogger(__name__)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;

CREATE TABLE IF NOT EXISTS sims (
    player_id TEXT NOT NULL,
    save_id TEXT NOT NULL,
    sim_id INTEGER NOT NULL,
    profile_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (player_id, save_id, sim_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    save_id TEXT NOT NULL,
    sim_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    content_json TEXT NOT NULL,
    importance REAL DEFAULT 1.0,
    created_at REAL NOT NULL,
    embedding_json TEXT,
    strength REAL DEFAULT 1.0,
    last_accessed_at REAL,
    consolidated INTEGER DEFAULT 0,
    emotion TEXT,
    salience REAL
);

CREATE INDEX IF NOT EXISTS idx_events_sim_time
    ON events (player_id, save_id, sim_id, created_at DESC);

CREATE TABLE IF NOT EXISTS relationships (
    player_id TEXT NOT NULL,
    save_id TEXT NOT NULL,
    sim_id INTEGER NOT NULL,
    target_sim_id INTEGER NOT NULL,
    sentiment REAL DEFAULT 0.0,
    metadata_json TEXT DEFAULT '{}',
    updated_at REAL NOT NULL,
    PRIMARY KEY (player_id, save_id, sim_id, target_sim_id)
);

CREATE TABLE IF NOT EXISTS reflections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    save_id TEXT NOT NULL,
    sim_id INTEGER NOT NULL,
    content_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS directives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT NOT NULL,
    save_id TEXT NOT NULL,
    sim_id INTEGER NOT NULL,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT DEFAULT 'pending',
    created_at REAL NOT NULL,
    completed_at REAL
);

CREATE TABLE IF NOT EXISTS neighborhoods (
    player_id TEXT NOT NULL,
    save_id TEXT NOT NULL,
    data_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (player_id, save_id)
);

CREATE TABLE IF NOT EXISTS households (
    player_id TEXT NOT NULL,
    save_id TEXT NOT NULL,
    household_id INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (player_id, save_id, household_id)
);
"""


def _event_text(event: dict[str, Any]) -> str:
    """Best-effort text used to embed an event."""
    content = event.get("content")
    if isinstance(content, dict):
        for key in ("message", "text", "summary", "action", "topic", "reason"):
            value = content.get(key)
            if value:
                return str(value)
    event_type = str(event.get("type", "")).strip()
    return event_type or (str(content) if content else "")


# Canonical column lists. ``_BASE_EVENT_COLUMNS`` matches the original schema;
# ``_EVENT_COLUMNS`` extends it with the v0.2 M2 strength/forgetting fields.
# Semantic search appends ``embedding_json`` right after them (index 10).
_BASE_EVENT_COLUMNS = "id, type, content_json, importance, created_at"
_EXT_EVENT_COLUMNS = "strength, last_accessed_at, consolidated, emotion, salience"
_EVENT_COLUMNS = f"{_BASE_EVENT_COLUMNS}, {_EXT_EVENT_COLUMNS}"
_EMBEDDING_COLUMN_INDEX = 10


def _row_to_event(row: tuple) -> dict[str, Any]:
    """Build an event dict from an event row.

    Tolerates both the legacy 5-column shape and the extended v0.2 shape:
    ``id, type, content_json, importance, created_at[, strength, last_accessed_at,
    consolidated, emotion, salience]``.
    """
    event: dict[str, Any] = {
        "id": row[0],
        "type": row[1],
        "content": json.loads(row[2]) if row[2] else {},
        "importance": row[3],
        "created_at": row[4],
    }
    if len(row) > 5:
        event["strength"] = row[5]
        event["last_accessed_at"] = row[6]
        event["consolidated"] = row[7]
        event["emotion"] = row[8]
        event["salience"] = row[9]
    return event


def _annotate_and_filter(
    events: list[dict[str, Any]],
    now: float,
    preset: str,
    min_strength: float | None,
) -> list[dict[str, Any]]:
    """Annotate events with effective strength and drop those below the floor."""
    annotated = annotate(events, now, preset)
    if min_strength is None:
        return annotated
    return [event for event in annotated if float(event.get("strength") or 0.0) >= min_strength]


def _lexical_score(event: dict[str, Any], now: float) -> float:
    """Rank key for lexical hits: ``importance * strength * recency``."""
    importance = float(event.get("importance") or 0.0)
    strength = float(event.get("strength") or 0.0)
    try:
        age_hours = max(0.0, now - float(event.get("created_at") or now)) / 3600.0
    except (TypeError, ValueError):
        age_hours = 0.0
    return importance * strength * (1.0 / (1.0 + age_hours))


def _int_ids(event_ids: Any) -> list[int]:
    """Best-effort coercion of an id collection to ints (bad values ignored)."""
    ids: list[int] = []
    for value in event_ids or []:
        try:
            ids.append(int(value))
        except (TypeError, ValueError):
            continue
    return ids


class SQLiteMemory:
    """SQLite-backed memory store with async wrappers over sync sqlite3."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db_path = settings.data_dir / "memory.sqlite3"
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._embeddings = build_embedding_provider(settings)
        self._init_db()

    def _init_db(self) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,  # autocommit
            )
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
            self._conn.executescript(SCHEMA)
            self._migrate()
            logger.info(f"Memory database initialized at {self.db_path}")

    def _migrate(self) -> None:
        """Additive migrations for databases created by older versions."""
        if self._conn is None:
            return
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(events)").fetchall()}
        if "embedding_json" not in columns:
            self._conn.execute("ALTER TABLE events ADD COLUMN embedding_json TEXT")
            logger.info("Migrated events table: added embedding_json column")
        # v0.2 M2: graded forgetting columns. Additive so existing DBs keep working.
        new_columns = {
            "strength": "REAL DEFAULT 1.0",
            "last_accessed_at": "REAL",
            "consolidated": "INTEGER DEFAULT 0",
            "emotion": "TEXT",
            "salience": "REAL",
        }
        for name, declaration in new_columns.items():
            if name not in columns:
                self._conn.execute(f"ALTER TABLE events ADD COLUMN {name} {declaration}")
                logger.info(f"Migrated events table: added {name} column")

    def _get_conn(self) -> sqlite3.Connection:
        with self._lock:
            if self._conn is None:
                self._init_db()
            return self._conn

    def _execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self._get_conn()
        with self._lock:
            return conn.execute(query, params)

    def _execute_many(self, query: str, params_list: list[tuple]) -> None:
        conn = self._get_conn()
        with self._lock:
            conn.executemany(query, params_list)

    async def upsert_profile(self, key: MemKey, profile: dict[str, Any]) -> None:
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO sims (player_id, save_id, sim_id, profile_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(player_id, save_id, sim_id) DO UPDATE SET
                profile_json=excluded.profile_json,
                updated_at=excluded.updated_at
            """,
            (key.player_id, key.save_id, key.sim_id, json.dumps(profile), time.time()),
        )

    async def get_profile(self, key: MemKey) -> dict[str, Any] | None:
        def _get() -> dict[str, Any] | None:
            cur = self._execute(
                "SELECT profile_json FROM sims WHERE player_id=? AND save_id=? AND sim_id=?",
                (key.player_id, key.save_id, key.sim_id),
            )
            row = cur.fetchone()
            if row:
                return json.loads(row[0])
            return None

        return await asyncio.to_thread(_get)

    async def list_profiles(self, player_id: str, save_id: str) -> list[dict[str, Any]]:
        def _list() -> list[dict[str, Any]]:
            cur = self._execute(
                "SELECT sim_id, profile_json FROM sims WHERE player_id=? AND save_id=? ORDER BY sim_id",
                (player_id, save_id),
            )
            result = []
            for row in cur.fetchall():
                try:
                    profile = json.loads(row[1])
                except (ValueError, TypeError):
                    profile = {}
                result.append({"sim_id": row[0], "profile": profile})
            return result

        return await asyncio.to_thread(_list)

    async def upsert_relationship(
        self,
        key: MemKey,
        target_sim_id: int,
        sentiment: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Create or update a Sim's stored relationship edge (census-driven).

        ``sentiment`` prefers the friendship/romance progression when the mod
        supplied it, falling back to the generic relationship depth.
        """
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO relationships
                (player_id, save_id, sim_id, target_sim_id, sentiment, metadata_json, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, save_id, sim_id, target_sim_id) DO UPDATE SET
                sentiment=excluded.sentiment,
                metadata_json=excluded.metadata_json,
                updated_at=excluded.updated_at
            """,
            (
                key.player_id,
                key.save_id,
                key.sim_id,
                int(target_sim_id),
                float(sentiment),
                json.dumps(metadata or {}),
                time.time(),
            ),
        )

    async def add_event(self, key: MemKey, event: dict[str, Any]) -> int:
        embedding = None
        text = _event_text(event)
        if text:
            try:
                vector = await self._embeddings.embed_one(text)
                embedding = vector or None
            except Exception as e:
                logger.debug(f"Embedding failed for event: {e}")

        def _add() -> int:
            created_at = time.time()
            cur = self._execute(
                """
                INSERT INTO events
                    (player_id, save_id, sim_id, type, content_json, importance, created_at,
                     embedding_json, strength, last_accessed_at, consolidated, emotion, salience)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key.player_id,
                    key.save_id,
                    key.sim_id,
                    event.get("type", "chat"),
                    json.dumps(event.get("content", {})),
                    event.get("importance", 1.0),
                    created_at,
                    json.dumps(embedding) if embedding else None,
                    event.get("strength", 1.0),
                    created_at,
                    int(event.get("consolidated", 0) or 0),
                    event.get("emotion"),
                    event.get("salience"),
                ),
            )
            return cur.lastrowid

        return await asyncio.to_thread(_add)

    async def recent_events(
        self,
        key: MemKey,
        limit: int = 50,
        *,
        now: float | None = None,
        preset: str | None = None,
        min_strength: float | None = None,
    ) -> list[dict[str, Any]]:
        def _recent() -> list[dict[str, Any]]:
            reference = time.time() if now is None else now
            decay_preset = preset or self.settings.memory.decay_preset
            floor = (
                min_strength
                if min_strength is not None
                else self.settings.memory.forget_threshold
            )
            # Use rowid for stable ordering (always increasing)
            cur = self._execute(
                f"""
                SELECT {_EVENT_COLUMNS}
                FROM events
                WHERE player_id=? AND save_id=? AND sim_id=?
                  AND consolidated=0
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (key.player_id, key.save_id, key.sim_id, limit),
            )
            rows = cur.fetchall()
            # Return in chronological order (oldest first) for conversation context
            rows = list(reversed(rows))
            events = [_row_to_event(row) for row in rows]
            return _annotate_and_filter(events, reference, decay_preset, floor)

        return await asyncio.to_thread(_recent)

    async def search_events(self, key: MemKey, query: str, limit: int = 10) -> list[dict[str, Any]]:
        now = time.time()
        preset = self.settings.memory.decay_preset
        floor = self.settings.memory.forget_threshold
        if query:
            try:
                vector = await self._embeddings.embed_one(query)
            except Exception:
                vector = []
            if vector:
                results = await asyncio.to_thread(
                    self._semantic_search, key, vector, limit, now, preset, floor
                )
                if results:
                    return results
        return await asyncio.to_thread(self._lexical_search, key, query, limit, now, preset, floor)

    def _lexical_search(
        self,
        key: MemKey,
        query: str,
        limit: int,
        now: float,
        preset: str,
        min_strength: float | None,
    ) -> list[dict[str, Any]]:
        like_query = f"%{query}%"
        cur = self._execute(
            f"""
            SELECT {_EVENT_COLUMNS}
            FROM events
            WHERE player_id=? AND save_id=? AND sim_id=?
              AND consolidated=0
              AND content_json LIKE ?
            LIMIT 500
            """,
            (key.player_id, key.save_id, key.sim_id, like_query),
        )
        events = _annotate_and_filter(
            [_row_to_event(row) for row in cur.fetchall()], now, preset, min_strength
        )
        events.sort(key=lambda event: _lexical_score(event, now), reverse=True)
        return events[:limit]

    def _semantic_search(
        self,
        key: MemKey,
        query_vector: list[float],
        limit: int,
        now: float,
        preset: str,
        min_strength: float | None,
    ) -> list[dict[str, Any]]:
        cur = self._execute(
            f"""
            SELECT {_EVENT_COLUMNS}, embedding_json
            FROM events
            WHERE player_id=? AND save_id=? AND sim_id=?
              AND consolidated=0
              AND embedding_json IS NOT NULL
            ORDER BY rowid DESC
            LIMIT 500
            """,
            (key.player_id, key.save_id, key.sim_id),
        )
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in cur.fetchall():
            try:
                vector = json.loads(row[_EMBEDDING_COLUMN_INDEX])
            except (ValueError, TypeError):
                continue
            event = _row_to_event(row)
            strength = effective_strength(
                event.get("strength"),
                event.get("last_accessed_at"),
                event.get("importance"),
                now,
                preset,
            )
            if min_strength is not None and strength < min_strength:
                continue
            event["strength"] = strength
            scored.append((cosine_similarity(query_vector, vector) * strength, event))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [event for score, event in scored[:limit] if score > 0.0]

    # v0.2 M1/M2: consolidation, touch and pruning

    async def unconsolidated_events(self, key: MemKey, limit: int = 100) -> list[dict[str, Any]]:
        def _get() -> list[dict[str, Any]]:
            reference = time.time()
            decay_preset = self.settings.memory.decay_preset
            cur = self._execute(
                f"""
                SELECT {_EVENT_COLUMNS}
                FROM events
                WHERE player_id=? AND save_id=? AND sim_id=?
                  AND consolidated=0 AND type='chat'
                ORDER BY rowid ASC
                LIMIT ?
                """,
                (key.player_id, key.save_id, key.sim_id, limit),
            )
            events = [_row_to_event(row) for row in cur.fetchall()]
            return annotate(events, reference, decay_preset)

        return await asyncio.to_thread(_get)

    async def mark_consolidated(
        self, key: MemKey, event_ids: list[int], summary_event_id: int | None = None
    ) -> int:
        ids = _int_ids(event_ids)
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)

        def _mark() -> int:
            cur = self._execute(
                f"""
                UPDATE events SET consolidated=1
                WHERE player_id=? AND save_id=? AND sim_id=?
                  AND id IN ({placeholders})
                """,
                (key.player_id, key.save_id, key.sim_id, *ids),
            )
            return cur.rowcount

        return await asyncio.to_thread(_mark)

    async def touch_events(self, key: MemKey, event_ids: list[int]) -> int:
        ids = _int_ids(event_ids)
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)

        def _touch() -> int:
            reference = time.time()
            cur = self._execute(
                f"""
                SELECT id, strength FROM events
                WHERE player_id=? AND save_id=? AND sim_id=?
                  AND id IN ({placeholders})
                """,
                (key.player_id, key.save_id, key.sim_id, *ids),
            )
            changed = 0
            for event_id, strength in cur.fetchall():
                result = self._execute(
                    """
                    UPDATE events SET last_accessed_at=?, strength=?
                    WHERE id=? AND player_id=? AND save_id=? AND sim_id=?
                    """,
                    (
                        reference,
                        touch_strength(strength),
                        event_id,
                        key.player_id,
                        key.save_id,
                        key.sim_id,
                    ),
                )
                changed += result.rowcount
            return changed

        return await asyncio.to_thread(_touch)

    async def prune_forgotten(self, retention_days: int, now: float | None = None) -> int:
        def _prune() -> int:
            reference = time.time() if now is None else now
            try:
                cutoff = reference - max(0.0, float(retention_days)) * 86400
            except (TypeError, ValueError):
                cutoff = reference - 180 * 86400
            decay_preset = self.settings.memory.decay_preset
            threshold = self.settings.memory.forget_threshold
            cur = self._execute(
                f"SELECT {_EVENT_COLUMNS} FROM events WHERE created_at < ?",
                (cutoff,),
            )
            doomed: list[int] = []
            for row in cur.fetchall():
                event = _row_to_event(row)
                strength = effective_strength(
                    event.get("strength"),
                    event.get("last_accessed_at"),
                    event.get("importance"),
                    reference,
                    decay_preset,
                )
                if strength < threshold:
                    doomed.append(event["id"])
            if not doomed:
                return 0
            placeholders = ",".join("?" for _ in doomed)
            result = self._execute(
                f"DELETE FROM events WHERE id IN ({placeholders})", tuple(doomed)
            )
            return result.rowcount

        return await asyncio.to_thread(_prune)

    async def set_sim_background(self, key: MemKey, background: dict[str, Any]) -> None:
        """Merge a God-written background into the Sim's stored profile."""
        profile = await self.get_profile(key) or {}
        profile["background"] = background
        await self.upsert_profile(key, profile)

    async def add_reflection(self, key: MemKey, reflection: dict[str, Any]) -> int:
        def _add() -> int:
            cur = self._execute(
                """
                INSERT INTO reflections (player_id, save_id, sim_id, content_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key.player_id, key.save_id, key.sim_id, json.dumps(reflection), time.time()),
            )
            return cur.lastrowid

        return await asyncio.to_thread(_add)

    async def recent_reflections(self, key: MemKey, limit: int = 10) -> list[dict[str, Any]]:
        def _recent() -> list[dict[str, Any]]:
            cur = self._execute(
                """
                SELECT id, content_json, created_at
                FROM reflections
                WHERE player_id=? AND save_id=? AND sim_id=?
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (key.player_id, key.save_id, key.sim_id, limit),
            )
            rows = list(reversed(cur.fetchall()))
            return [
                {"id": row[0], "content": json.loads(row[1]), "created_at": row[2]}
                for row in rows
            ]

        return await asyncio.to_thread(_recent)

    async def upsert_neighborhood(self, player_id: str, save_id: str, data: dict[str, Any]) -> None:
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO neighborhoods (player_id, save_id, data_json, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(player_id, save_id) DO UPDATE SET
                data_json=excluded.data_json,
                updated_at=excluded.updated_at
            """,
            (player_id, save_id, json.dumps(data), time.time()),
        )

    async def get_neighborhood(self, player_id: str, save_id: str) -> dict[str, Any] | None:
        def _get() -> dict[str, Any] | None:
            cur = self._execute(
                "SELECT data_json FROM neighborhoods WHERE player_id=? AND save_id=?",
                (player_id, save_id),
            )
            row = cur.fetchone()
            return json.loads(row[0]) if row else None

        return await asyncio.to_thread(_get)

    async def upsert_household(self, key: HouseholdKey, data: dict[str, Any]) -> None:
        await asyncio.to_thread(
            self._execute,
            """
            INSERT INTO households (player_id, save_id, household_id, data_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(player_id, save_id, household_id) DO UPDATE SET
                data_json=excluded.data_json,
                updated_at=excluded.updated_at
            """,
            (key.player_id, key.save_id, key.household_id, json.dumps(data), time.time()),
        )

    async def get_household(self, key: HouseholdKey) -> dict[str, Any] | None:
        def _get() -> dict[str, Any] | None:
            cur = self._execute(
                """
                SELECT data_json FROM households
                WHERE player_id=? AND save_id=? AND household_id=?
                """,
                (key.player_id, key.save_id, key.household_id),
            )
            row = cur.fetchone()
            return json.loads(row[0]) if row else None

        return await asyncio.to_thread(_get)

    async def list_households(self, player_id: str, save_id: str) -> list[dict[str, Any]]:
        def _list() -> list[dict[str, Any]]:
            cur = self._execute(
                """
                SELECT household_id, data_json, updated_at FROM households
                WHERE player_id=? AND save_id=?
                ORDER BY household_id
                """,
                (player_id, save_id),
            )
            result = []
            for row in cur.fetchall():
                entry = {"household_id": row[0], "updated_at": row[2]}
                try:
                    entry["data"] = json.loads(row[1])
                except (ValueError, TypeError):
                    entry["data"] = {}
                result.append(entry)
            return result

        return await asyncio.to_thread(_list)

    async def reset(self, scope: str, key: MemKey | None) -> dict[str, int]:
        """Clear memory by scope.

        Scopes:
        - session: not applicable for persistent store, no-op
        - sim: clear all data for the given sim
        - save: clear all data for the given save (requires key with player_id, save_id)
        - all: clear everything
        """
        deleted = {
            "sims": 0,
            "events": 0,
            "relationships": 0,
            "reflections": 0,
            "directives": 0,
            "neighborhoods": 0,
            "households": 0,
        }

        if scope == "session":
            return deleted

        if scope == "sim" and key:
            tables = ["sims", "events", "relationships", "reflections", "directives"]
            for table in tables:
                cur = await asyncio.to_thread(
                    self._execute,
                    f"DELETE FROM {table} WHERE player_id=? AND save_id=? AND sim_id=?",
                    (key.player_id, key.save_id, key.sim_id),
                )
                deleted[table] = cur.rowcount
            return deleted

        if scope == "save" and key:
            tables = ["sims", "events", "relationships", "reflections", "directives"]
            for table in tables:
                cur = await asyncio.to_thread(
                    self._execute,
                    f"DELETE FROM {table} WHERE player_id=? AND save_id=?",
                    (key.player_id, key.save_id),
                )
                deleted[table] = cur.rowcount
            for table in ("neighborhoods", "households"):
                cur = await asyncio.to_thread(
                    self._execute,
                    f"DELETE FROM {table} WHERE player_id=? AND save_id=?",
                    (key.player_id, key.save_id),
                )
                deleted[table] = cur.rowcount
            return deleted

        if scope == "all":
            tables = [
                "sims",
                "events",
                "relationships",
                "reflections",
                "directives",
                "neighborhoods",
                "households",
            ]
            for table in tables:
                cur = await asyncio.to_thread(self._execute, f"DELETE FROM {table}")
                deleted[table] = cur.rowcount
            return deleted

        return deleted

    async def stats(self) -> dict[str, Any]:
        def _stats() -> dict[str, Any]:
            cur = self._execute("SELECT COUNT(*) FROM sims")
            sims_count = cur.fetchone()[0]
            cur = self._execute("SELECT COUNT(*) FROM events")
            events_count = cur.fetchone()[0]
            cur = self._execute("SELECT COUNT(*) FROM relationships")
            rels_count = cur.fetchone()[0]
            cur = self._execute("SELECT COUNT(*) FROM reflections")
            refl_count = cur.fetchone()[0]
            cur = self._execute("SELECT COUNT(*) FROM directives")
            dir_count = cur.fetchone()[0]
            cur = self._execute("SELECT COUNT(*) FROM neighborhoods")
            neighborhoods_count = cur.fetchone()[0]
            cur = self._execute("SELECT COUNT(*) FROM households")
            households_count = cur.fetchone()[0]
            cur = self._execute("SELECT COUNT(*) FROM events WHERE consolidated=1")
            consolidated_count = cur.fetchone()[0]
            forgotten_count = self._count_forgotten()
            return {
                "sims": sims_count,
                "events": events_count,
                "relationships": rels_count,
                "reflections": refl_count,
                "directives": dir_count,
                "neighborhoods": neighborhoods_count,
                "households": households_count,
                "consolidated": consolidated_count,
                "forgotten": forgotten_count,
                "db_path": str(self.db_path),
            }

        return await asyncio.to_thread(_stats)

    def _count_forgotten(self) -> int:
        """Count events whose effective strength is below the forget threshold."""
        now = time.time()
        preset = self.settings.memory.decay_preset
        threshold = self.settings.memory.forget_threshold
        cur = self._execute(f"SELECT {_EVENT_COLUMNS} FROM events")
        forgotten = 0
        for row in cur.fetchall():
            event = _row_to_event(row)
            strength = effective_strength(
                event.get("strength"),
                event.get("last_accessed_at"),
                event.get("importance"),
                now,
                preset,
            )
            if strength < threshold:
                forgotten += 1
        return forgotten

    def close_sync(self) -> None:
        """Close the SQLite connection synchronously (best-effort).

        Safe to call outside an event loop. Used when the store is replaced by
        ``graph.configure`` (so the DB file handle is released and the old
        connection does not outlive its settings). The async :meth:`close` also
        awaits the embedding provider.
        """
        with self._lock:
            if self._conn:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None
                logger.info("Memory database closed")

    async def close(self) -> None:
        close_embeddings = getattr(self._embeddings, "close", None)
        if callable(close_embeddings):
            try:
                await close_embeddings()
            except Exception:
                pass
        self.close_sync()


def build_memory_store(settings: Settings) -> MemoryStore:
    """Factory function to build a memory store from settings."""
    provider = settings.memory.provider.lower()
    if provider == "sqlite":
        return SQLiteMemory(settings)
    raise ValueError(f"Unknown memory provider: {provider}")