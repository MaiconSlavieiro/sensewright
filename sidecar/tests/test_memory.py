"""Tests for memory store."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sensewright_sidecar.config import MemoryConfig, Settings
from sensewright_sidecar.memory import (
    NoneEmbeddings,
    build_embedding_provider,
    build_memory_store,
)
from sensewright_sidecar.memory.base import MemKey


def make_test_settings(tmp_path: Path) -> Settings:
    """Create a test Settings object with a temporary data directory."""
    return Settings(
        home=tmp_path,
        data_dir=tmp_path / "data",
        memory=MemoryConfig(provider="sqlite", embedding_provider="none"),
    )


@pytest.fixture
def temp_settings():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = make_test_settings(tmp_path)
        yield settings
        # Note: Individual tests should close the memory store if needed


@pytest.mark.asyncio
async def test_profile_upsert_and_get(temp_settings):
    """Test profile upsert and retrieval."""
    memory = build_memory_store(temp_settings)
    key = MemKey(player_id="player1", save_id="save1", sim_id=123)

    profile = {
        "name": "Test Sim",
        "backstory": "A test backstory",
        "personality": {"openness": 0.8, "conscientiousness": 0.6},
    }

    await memory.upsert_profile(key, profile)
    retrieved = await memory.get_profile(key)

    assert retrieved is not None
    assert retrieved["name"] == "Test Sim"
    assert retrieved["backstory"] == "A test backstory"
    assert retrieved["personality"]["openness"] == 0.8

    await memory.close()


@pytest.mark.asyncio
async def test_profile_update(temp_settings):
    """Test profile update overwrites previous."""
    memory = build_memory_store(temp_settings)
    key = MemKey(player_id="player1", save_id="save1", sim_id=123)

    await memory.upsert_profile(key, {"name": "Original", "version": 1})
    await memory.upsert_profile(key, {"name": "Updated", "version": 2})

    retrieved = await memory.get_profile(key)
    assert retrieved["name"] == "Updated"
    assert retrieved["version"] == 2

    await memory.close()


@pytest.mark.asyncio
async def test_add_and_recent_events(temp_settings):
    """Test adding events and retrieving recent ones."""
    memory = build_memory_store(temp_settings)
    key = MemKey(player_id="player1", save_id="save1", sim_id=123)

    await memory.add_event(key, {"type": "chat", "content": {"message": "Hello"}, "importance": 0.5})
    await memory.add_event(key, {"type": "chat", "content": {"message": "World"}, "importance": 0.7})
    await memory.add_event(key, {"type": "action", "content": {"action": "sleep"}, "importance": 0.3})

    events = await memory.recent_events(key, limit=10)

    assert len(events) == 3
    # Chronological order (oldest first)
    assert events[0]["content"]["message"] == "Hello"
    assert events[1]["content"]["message"] == "World"
    assert events[2]["content"]["action"] == "sleep"

    await memory.close()


@pytest.mark.asyncio
async def test_recent_events_limit(temp_settings):
    """Test recent events respects limit."""
    memory = build_memory_store(temp_settings)
    key = MemKey(player_id="player1", save_id="save1", sim_id=123)

    for i in range(15):
        await memory.add_event(key, {"type": "test", "content": {"index": i}, "importance": 0.5})

    events = await memory.recent_events(key, limit=5)
    assert len(events) == 5
    # Should get the 5 most recent (indices 10-14) in chronological order
    assert events[0]["content"]["index"] == 10
    assert events[4]["content"]["index"] == 14

    await memory.close()


@pytest.mark.asyncio
async def test_search_events_lexical(temp_settings):
    """Test lexical event search."""
    memory = build_memory_store(temp_settings)
    key = MemKey(player_id="player1", save_id="save1", sim_id=123)

    await memory.add_event(key, {"type": "chat", "content": {"message": "I love pizza"}, "importance": 0.5})
    await memory.add_event(key, {"type": "chat", "content": {"message": "Pizza is great"}, "importance": 0.5})
    await memory.add_event(key, {"type": "chat", "content": {"message": "I hate burgers"}, "importance": 0.5})

    results = await memory.search_events(key, "pizza", limit=10)
    assert len(results) == 2
    for r in results:
        assert "pizza" in str(r["content"]).lower()

    results = await memory.search_events(key, "burgers", limit=10)
    assert len(results) == 1
    assert "burgers" in str(results[0]["content"]).lower()

    await memory.close()


@pytest.mark.asyncio
async def test_reset_scope_sim(temp_settings):
    """Test reset with sim scope."""
    memory = build_memory_store(temp_settings)
    key = MemKey(player_id="player1", save_id="save1", sim_id=123)
    key2 = MemKey(player_id="player1", save_id="save1", sim_id=456)

    await memory.upsert_profile(key, {"name": "Sim1"})
    await memory.upsert_profile(key2, {"name": "Sim2"})
    await memory.add_event(key, {"type": "chat", "content": {"msg": "hi"}, "importance": 0.5})
    await memory.add_event(key2, {"type": "chat", "content": {"msg": "hello"}, "importance": 0.5})

    deleted = await memory.reset("sim", key)

    assert deleted["sims"] == 1
    assert deleted["events"] == 1

    # Sim1 should be gone
    assert await memory.get_profile(key) is None
    assert await memory.recent_events(key, limit=10) == []

    # Sim2 should remain
    assert await memory.get_profile(key2) is not None
    assert len(await memory.recent_events(key2, limit=10)) == 1

    await memory.close()


@pytest.mark.asyncio
async def test_reset_scope_save(temp_settings):
    """Test reset with save scope."""
    memory = build_memory_store(temp_settings)
    key1 = MemKey(player_id="player1", save_id="save1", sim_id=123)
    key2 = MemKey(player_id="player1", save_id="save1", sim_id=456)
    key3 = MemKey(player_id="player1", save_id="save2", sim_id=789)

    await memory.upsert_profile(key1, {"name": "Sim1"})
    await memory.upsert_profile(key2, {"name": "Sim2"})
    await memory.upsert_profile(key3, {"name": "Sim3"})

    deleted = await memory.reset("save", key1)

    assert deleted["sims"] == 2

    # save1 sims should be gone
    assert await memory.get_profile(key1) is None
    assert await memory.get_profile(key2) is None
    # save2 sim should remain
    assert await memory.get_profile(key3) is not None

    await memory.close()


@pytest.mark.asyncio
async def test_reset_scope_all(temp_settings):
    """Test reset with all scope."""
    memory = build_memory_store(temp_settings)
    key1 = MemKey(player_id="player1", save_id="save1", sim_id=123)
    key2 = MemKey(player_id="player2", save_id="save2", sim_id=456)

    await memory.upsert_profile(key1, {"name": "Sim1"})
    await memory.upsert_profile(key2, {"name": "Sim2"})
    await memory.add_event(key1, {"type": "chat", "content": {"msg": "hi"}, "importance": 0.5})
    await memory.add_event(key2, {"type": "chat", "content": {"msg": "hello"}, "importance": 0.5})

    deleted = await memory.reset("all", None)

    assert deleted["sims"] == 2
    assert deleted["events"] == 2

    assert await memory.get_profile(key1) is None
    assert await memory.get_profile(key2) is None

    await memory.close()


@pytest.mark.asyncio
async def test_stats(temp_settings):
    """Test stats method."""
    memory = build_memory_store(temp_settings)
    key = MemKey(player_id="player1", save_id="save1", sim_id=123)

    await memory.upsert_profile(key, {"name": "Test"})
    await memory.add_event(key, {"type": "chat", "content": {"msg": "hi"}, "importance": 0.5})
    await memory.add_event(key, {"type": "chat", "content": {"msg": "hello"}, "importance": 0.5})

    stats = await memory.stats()

    assert stats["sims"] == 1
    assert stats["events"] == 2
    assert "db_path" in stats

    await memory.close()


@pytest.mark.asyncio
async def test_none_embeddings():
    """Test NoneEmbeddings returns empty vectors."""
    embeddings = NoneEmbeddings()

    result = await embeddings.embed(["hello", "world"])
    assert result == [[], []]

    result = await embeddings.embed_one("hello")
    assert result == []


@pytest.mark.asyncio
async def test_build_embedding_provider_none():
    """Test build_embedding_provider returns NoneEmbeddings for 'none'."""
    settings = Settings(memory=MemoryConfig(embedding_provider="none"))
    provider = build_embedding_provider(settings)
    assert isinstance(provider, NoneEmbeddings)


@pytest.mark.asyncio
async def test_upsert_relationship_persists_and_updates(temp_settings):
    """Phase 2b: census relationship edges are actually persisted (upsert)."""
    memory = build_memory_store(temp_settings)
    key = MemKey(player_id="player1", save_id="save1", sim_id=123)

    await memory.upsert_relationship(
        key, 7, 30.0, {"target_name": "Bella", "track": "Friendship", "known_traits": ["trait_Cheerful"]}
    )
    await memory.upsert_relationship(key, 7, 45.0, {"target_name": "Bella", "track": "Friendship"})

    cur = memory._execute(
        "SELECT sentiment, metadata_json FROM relationships WHERE sim_id=? AND target_sim_id=?",
        (123, 7),
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == 45.0
    assert "Bella" in row[1]

    await memory.close()