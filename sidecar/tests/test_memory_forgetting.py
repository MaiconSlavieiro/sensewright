"""Tests for v0.2 M2 graded forgetting: decay, touch, pruning and filtering."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from sims_sense_sidecar.config import MemoryConfig, Settings
from sims_sense_sidecar.memory import build_memory_store
from sims_sense_sidecar.memory.base import MemKey
from sims_sense_sidecar.memory.decay import (
    DECAY_PRESETS,
    annotate,
    decay_lambda,
    decay_preset_or_default,
    dejavu_hint,
    effective_strength,
    is_forgotten,
    is_vivid,
    is_weak,
    touch_strength,
)

NOW = 1_000_000.0
HOUR = 3600.0
DAY = 86400.0


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        home=tmp_path,
        data_dir=tmp_path / "data",
        memory=MemoryConfig(provider="sqlite", embedding_provider="none"),
    )


@pytest.fixture
def temp_settings(tmp_path: Path) -> Settings:
    return make_settings(tmp_path)


# ── pure decay math ───────────────────────────────────────────────────


def test_decay_presets_ordering():
    assert DECAY_PRESETS["fast"] > DECAY_PRESETS["normal"] > DECAY_PRESETS["slow"]
    assert decay_lambda("fast") == DECAY_PRESETS["fast"]
    assert decay_preset_or_default("unknown") == DECAY_PRESETS["normal"]
    assert decay_preset_or_default(None) == DECAY_PRESETS["normal"]


def test_effective_strength_decays_monotonically():
    fresh = effective_strength(1.0, NOW, 1.0, NOW, "normal")
    hour = effective_strength(1.0, NOW - HOUR, 1.0, NOW, "normal")
    day = effective_strength(1.0, NOW - DAY, 1.0, NOW, "normal")
    assert fresh > hour > day
    assert 0.0 <= day <= 1.0


def test_fast_decays_more_than_slow():
    fast = effective_strength(1.0, NOW - DAY, 1.0, NOW, "fast")
    slow = effective_strength(1.0, NOW - DAY, 1.0, NOW, "slow")
    assert fast < slow


def test_importance_is_a_mild_lift():
    low = effective_strength(1.0, NOW, 0.0, NOW, "normal")
    mid = effective_strength(1.0, NOW, 1.0, NOW, "normal")
    high = effective_strength(1.0, NOW, 5.0, NOW, "normal")
    assert low < mid
    assert high >= mid
    assert high <= 1.0


def test_effective_strength_handles_none():
    assert effective_strength(None, None, None, NOW) > 0.0
    assert effective_strength("bad", "bad", "bad", NOW) > 0.0


def test_touch_strength_raises_and_caps():
    assert touch_strength(0.5) > 0.5
    assert touch_strength(1.0) == 1.0
    assert touch_strength(None) == 1.0
    assert touch_strength(0.0) == pytest.approx(0.05)


def test_strength_classifiers():
    assert is_vivid(0.9)
    assert not is_vivid(0.4)
    assert is_weak(0.3)
    assert not is_weak(0.1)
    assert not is_weak(0.9)
    assert is_forgotten(0.1)
    assert not is_forgotten(0.25)
    assert not is_forgotten(None)


def test_annotate_adds_strength_without_mutating():
    event = {"id": 1, "importance": 1.0, "last_accessed_at": NOW}
    out = annotate([event], NOW, "normal")
    assert isinstance(out[0]["strength"], float)
    assert "strength" not in event


def test_dejavu_hint_truncates():
    assert dejavu_hint("short", 60) == "short"
    hint = dejavu_hint("x" * 100, 10)
    assert hint.startswith("x" * 10)
    assert hint.endswith("…")
    assert dejavu_hint(None) == ""


# ── store behaviour ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_touch_events_boosts_strength(temp_settings):
    memory = build_memory_store(temp_settings)
    key = MemKey("player1", "save1", 1)
    other = MemKey("player1", "save1", 2)
    event_id = await memory.add_event(
        key, {"type": "chat", "content": {"message": "hi"}, "strength": 0.5}
    )
    await memory.add_event(other, {"type": "chat", "content": {"message": "yo"}, "strength": 0.5})

    changed = await memory.touch_events(key, [event_id])
    assert changed == 1
    stored = memory._execute("SELECT strength FROM events WHERE id=?", (event_id,)).fetchone()[0]
    assert stored > 0.5

    # Scoped by key: a wrong key touches nothing.
    assert await memory.touch_events(other, [event_id]) == 0

    await memory.close()


@pytest.mark.asyncio
async def test_forgotten_events_excluded_from_recent(temp_settings):
    memory = build_memory_store(temp_settings)
    key = MemKey("p", "s", 1)
    await memory.add_event(
        key, {"type": "chat", "content": {"message": "vivid"}, "importance": 1.0}
    )
    await memory.add_event(key, {"type": "chat", "content": {"message": "faded"}, "strength": 0.05})

    default = await memory.recent_events(key, limit=10)
    assert [event["content"]["message"] for event in default] == ["vivid"]

    override = await memory.recent_events(key, limit=10, min_strength=0.0)
    assert {event["content"]["message"] for event in override} == {"vivid", "faded"}

    await memory.close()


@pytest.mark.asyncio
async def test_consolidated_turns_excluded_from_context(temp_settings):
    memory = build_memory_store(temp_settings)
    key = MemKey("p", "s", 1)
    first = await memory.add_event(key, {"type": "chat", "content": {"message": "one"}})
    await memory.add_event(key, {"type": "chat", "content": {"message": "two"}})

    assert await memory.mark_consolidated(key, [first]) == 1

    events = await memory.recent_events(key, limit=10)
    assert [event["content"]["message"] for event in events] == ["two"]

    await memory.close()


@pytest.mark.asyncio
async def test_unconsolidated_round_trip(temp_settings):
    memory = build_memory_store(temp_settings)
    key = MemKey("p", "s", 1)
    await memory.add_event(key, {"type": "chat", "content": {"role": "user", "message": "hello"}})
    await memory.add_event(key, {"type": "action", "content": {"action": "sit"}})
    await memory.add_event(
        key, {"type": "chat", "content": {"role": "assistant", "message": "hi"}}
    )

    pending = await memory.unconsolidated_events(key, limit=10)
    assert [event["type"] for event in pending] == ["chat", "chat"]
    assert [event["content"]["message"] for event in pending] == ["hello", "hi"]
    assert all(isinstance(event["strength"], float) for event in pending)

    changed = await memory.mark_consolidated(key, [event["id"] for event in pending])
    assert changed == 2
    assert await memory.unconsolidated_events(key, limit=10) == []

    await memory.close()


@pytest.mark.asyncio
async def test_prune_forgotten_deletes_only_old_and_weak(temp_settings):
    memory = build_memory_store(temp_settings)
    key = MemKey("p", "s", 1)
    now = time.time()
    old_dead = await memory.add_event(
        key, {"type": "chat", "content": {"message": "old dead"}, "strength": 0.05}
    )
    old_alive = await memory.add_event(
        key, {"type": "chat", "content": {"message": "old alive"}, "strength": 1.0}
    )
    recent_dead = await memory.add_event(
        key, {"type": "chat", "content": {"message": "recent dead"}, "strength": 0.05}
    )

    old_ts = now - 2 * DAY
    memory._execute("UPDATE events SET created_at=? WHERE id=?", (old_ts, old_dead))
    memory._execute("UPDATE events SET created_at=? WHERE id=?", (old_ts, old_alive))

    assert await memory.prune_forgotten(retention_days=1, now=now) == 1

    remaining = {
        event["id"]
        for event in await memory.recent_events(key, limit=10, min_strength=0.0)
    }
    assert old_dead not in remaining
    assert old_alive in remaining
    assert recent_dead in remaining

    await memory.close()


@pytest.mark.asyncio
async def test_stats_reports_consolidated_and_forgotten(temp_settings):
    memory = build_memory_store(temp_settings)
    key = MemKey("p", "s", 1)
    first = await memory.add_event(
        key, {"type": "chat", "content": {"message": "a"}, "importance": 1.0}
    )
    await memory.add_event(key, {"type": "chat", "content": {"message": "b"}, "strength": 0.05})
    await memory.mark_consolidated(key, [first])

    stats = await memory.stats()
    assert stats["events"] == 2
    assert stats["consolidated"] == 1
    assert stats["forgotten"] == 1
    assert "db_path" in stats

    await memory.close()


@pytest.mark.asyncio
async def test_search_excludes_forgotten_and_archived(temp_settings):
    memory = build_memory_store(temp_settings)
    key = MemKey("p", "s", 1)
    strong = await memory.add_event(
        key, {"type": "chat", "content": {"message": "I love pizza"}, "importance": 1.0}
    )
    await memory.add_event(
        key, {"type": "chat", "content": {"message": "pizza is faded"}, "strength": 0.05}
    )
    archived = await memory.add_event(
        key, {"type": "chat", "content": {"message": "pizza archived"}, "importance": 1.0}
    )
    await memory.mark_consolidated(key, [archived])

    results = await memory.search_events(key, "pizza", limit=10)
    assert {event["id"] for event in results} == {strong}

    await memory.close()


@pytest.mark.asyncio
async def test_search_ranks_vivid_before_faded(temp_settings):
    memory = build_memory_store(temp_settings)
    key = MemKey("p", "s", 1)
    await memory.add_event(
        key, {"type": "chat", "content": {"message": "cake"}, "strength": 0.3}
    )
    vivid = await memory.add_event(
        key, {"type": "chat", "content": {"message": "cake"}, "strength": 1.0}
    )

    results = await memory.search_events(key, "cake", limit=10)
    assert results[0]["id"] == vivid

    await memory.close()


@pytest.mark.asyncio
async def test_migration_adds_columns_to_legacy_db(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "memory.sqlite3"

    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player_id TEXT NOT NULL,
            save_id TEXT NOT NULL,
            sim_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            content_json TEXT NOT NULL,
            importance REAL DEFAULT 1.0,
            created_at REAL NOT NULL,
            embedding_json TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO events (player_id, save_id, sim_id, type, content_json, importance, created_at)
        VALUES ('p', 's', 1, 'chat', '{"message": "legacy"}', 1.0, ?)
        """,
        (time.time(),),
    )
    conn.commit()
    conn.close()

    memory = build_memory_store(make_settings(tmp_path))
    columns = {
        row[1] for row in memory._execute("PRAGMA table_info(events)").fetchall()
    }
    assert {"strength", "last_accessed_at", "consolidated", "emotion", "salience"} <= columns

    events = await memory.recent_events(MemKey("p", "s", 1), limit=10)
    assert [event["content"]["message"] for event in events] == ["legacy"]

    await memory.close()
