"""Tests for sensewright_sidecar.memory.sqlite_store module."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sensewright_sidecar.memory.sqlite_store import SqliteStore, SCHEMA_VERSION


class TestSqliteStore:
    """Tests for SqliteStore."""

    @pytest.fixture
    def store(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = SqliteStore(db_path)
        store.initialize()
        yield store
        store.close()

    def test_schema_init(self, store):
        # Verify tables exist by querying metadata
        conn = store._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {row["name"] for row in tables}
        assert "metadata" in table_names
        assert "memories" in table_names
        assert "relationships" in table_names
        assert "sims" in table_names
        assert "arcs" in table_names
        assert "neighborhoods" in table_names
        # FTS table
        assert "memories_fts" in table_names

    def test_schema_version_set(self, store):
        conn = store._connect()
        row = conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        assert row is not None
        assert int(row["value"]) == SCHEMA_VERSION

    def test_add_memory_returns_id(self, store):
        memory_id = store.add_memory(
            sim_id=1,
            memory_type="thought",
            content={"text": "I am thinking"},
            search_text="I am thinking",
            importance=1.0,
            strength=1.0,
            created_sim_tick=100,
        )
        assert isinstance(memory_id, int)
        assert memory_id > 0

    def test_get_memory(self, store):
        memory_id = store.add_memory(
            sim_id=1,
            memory_type="thought",
            content={"text": "Test memory"},
            search_text="Test memory",
            created_sim_tick=100,
        )
        memory = store.get_memory(memory_id)
        assert memory is not None
        assert memory["id"] == memory_id
        assert memory["sim_id"] == 1
        assert memory["type"] == "thought"
        assert memory["content"] == {"text": "Test memory"}
        assert memory["search_text"] == "Test memory"

    def test_recent_memories_ordering(self, store):
        # Add memories with different ticks
        store.add_memory(1, "thought", {"text": "first"}, "first", created_sim_tick=100)
        store.add_memory(1, "thought", {"text": "second"}, "second", created_sim_tick=200)
        store.add_memory(1, "thought", {"text": "third"}, "third", created_sim_tick=300)

        recent = store.recent_memories(1, limit=10)
        assert len(recent) == 3
        # Newest first
        assert recent[0]["content"]["text"] == "third"
        assert recent[1]["content"]["text"] == "second"
        assert recent[2]["content"]["text"] == "first"

    def test_recent_memories_excludes_archived_by_default(self, store):
        store.add_memory(1, "thought", {"text": "active"}, "active", created_sim_tick=100)
        mid = store.add_memory(1, "thought", {"text": "archived"}, "archived", created_sim_tick=200, archived=True)

        recent = store.recent_memories(1, limit=10)
        assert len(recent) == 1
        assert recent[0]["content"]["text"] == "active"

        recent_with_archived = store.recent_memories(1, limit=10, include_archived=True)
        assert len(recent_with_archived) == 2

    def test_search_memories_fts5(self, store):
        store.add_memory(1, "thought", {"text": "friendly dog at the park"}, "friendly dog at the park", created_sim_tick=100)
        store.add_memory(1, "thought", {"text": "cat sleeping"}, "cat sleeping", created_sim_tick=200)

        results = store.search_memories(1, "dog", limit=10)
        assert len(results) == 1
        assert "dog" in results[0]["search_text"]

    def test_search_memories_empty_query(self, store):
        results = store.search_memories(1, "", limit=10)
        assert results == []

    def test_search_memories_no_sim_filter(self, store):
        store.add_memory(1, "thought", {"text": "dog"}, "dog", created_sim_tick=100)
        store.add_memory(2, "thought", {"text": "dog"}, "dog", created_sim_tick=200)

        results = store.search_memories(None, "dog", limit=10)
        assert len(results) == 2

    def test_upsert_sim_profile(self, store):
        profile = {"name": "Test Sim", "traits": ["creative"]}
        store.upsert_sim_profile(1, profile, tick=100)

        retrieved = store.get_sim_profile(1)
        assert retrieved is not None
        assert retrieved["profile"] == profile
        assert retrieved["sim_id"] == 1

    def test_get_sim_profile_nonexistent(self, store):
        result = store.get_sim_profile(999)
        assert result is None

    def test_upsert_relationship(self, store):
        store.upsert_relationship(
            sim_id=1,
            target_id=2,
            friendship=50.0,
            romance=10.0,
            known_traits=["cheerful"],
            known_secrets=["secret1"],
            dynamic_label="friend",
            qualitative_note="Good friend",
            updated_sim_tick=100,
        )

        rel = store.get_relationship(1, 2)
        assert rel["sim_id"] == 1
        assert rel["target_id"] == 2
        assert rel["friendship"] == 50.0
        assert rel["romance"] == 10.0
        assert rel["known_traits"] == ["cheerful"]
        assert rel["known_secrets"] == ["secret1"]
        assert rel["dynamic_label"] == "friend"
        assert rel["qualitative_note"] == "Good friend"

    def test_get_relationship_defaults(self, store):
        rel = store.get_relationship(1, 999)
        assert rel["sim_id"] == 1
        assert rel["target_id"] == 999
        assert rel["friendship"] == 0.0
        assert rel["romance"] == 0.0
        assert rel["known_traits"] == []
        assert rel["known_secrets"] == []
        assert rel["dynamic_label"] == ""
        assert rel["qualitative_note"] == ""

    def test_add_known_secret(self, store):
        store.upsert_relationship(1, 2, friendship=10.0, updated_sim_tick=100)
        store.add_known_secret(1, 2, "new secret", tick=200)

        rel = store.get_relationship(1, 2)
        assert "new secret" in rel["known_secrets"]

    def test_save_arc(self, store):
        arc = {
            "id": "arc1",
            "theme": "Romance",
            "beats": [{"id": "beat1", "description": "Meet"}],
            "current_beat_idx": 0,
            "cast": [1, 2],
            "status": "active",
            "created_sim_tick": 100,
        }
        store.save_arc(arc)

        retrieved = store.get_arc("arc1")
        assert retrieved is not None
        assert retrieved["id"] == "arc1"
        assert retrieved["theme"] == "Romance"
        assert retrieved["beats"] == [{"id": "beat1", "description": "Meet"}]
        assert retrieved["cast"] == [1, 2]

    def test_get_arc_nonexistent(self, store):
        result = store.get_arc("nonexistent")
        assert result is None

    def test_list_arcs(self, store):
        store.save_arc({"id": "arc1", "theme": "A", "beats": [], "current_beat_idx": 0, "cast": [], "status": "active", "created_sim_tick": 100})
        store.save_arc({"id": "arc2", "theme": "B", "beats": [], "current_beat_idx": 0, "cast": [], "status": "draft", "created_sim_tick": 200})

        all_arcs = store.list_arcs()
        assert len(all_arcs) == 2
        # Ordered by created_sim_tick DESC
        assert all_arcs[0]["id"] == "arc2"
        assert all_arcs[1]["id"] == "arc1"

        active_arcs = store.list_arcs(status="active")
        assert len(active_arcs) == 1
        assert active_arcs[0]["id"] == "arc1"

    def test_neighborhoods_get_default(self, store):
        nbh = store.get_neighborhood(1)
        assert nbh["save_id"] == 1
        assert nbh["zeitgeist"] == {}
        assert nbh["chronicles"] == []
        assert nbh["rumors"] == []

    def test_neighborhoods_set_get(self, store):
        store.set_neighborhood(
            1,
            zeitgeist={"tags": ["romantic"], "preset": "novela"},
            chronicles=[{"text": "Day 1", "tick": 100}],
            rumors=[{"id": "r1", "text": "Rumor"}],
            tick=100,
        )

        nbh = store.get_neighborhood(1)
        assert nbh["zeitgeist"] == {"tags": ["romantic"], "preset": "novela"}
        assert nbh["chronicles"] == [{"text": "Day 1", "tick": 100}]
        assert nbh["rumors"] == [{"id": "r1", "text": "Rumor"}]

    def test_archive_memories(self, store):
        id1 = store.add_memory(1, "thought", {"text": "mem1"}, "mem1", created_sim_tick=100)
        id2 = store.add_memory(1, "thought", {"text": "mem2"}, "mem2", created_sim_tick=200)

        store.archive_memories([id1, id2])

        recent = store.recent_memories(1, include_archived=True)
        assert all(m["archived"] == 1 for m in recent)

    def test_prune_trivial_memories_never_deletes_consolidated(self, store):
        # Add consolidated memory (should not be deleted)
        cons_id = store.add_memory(1, "consolidated", {"text": "consolidated"}, "consolidated", created_sim_tick=100, consolidated=True)
        # Add diary memory (should not be deleted)
        diary_id = store.add_memory(1, "diary", {"text": "diary"}, "diary", created_sim_tick=100)
        # Add legacy memory (should not be deleted)
        legacy_id = store.add_memory(1, "legacy", {"text": "legacy"}, "legacy", created_sim_tick=100)
        # Add trivial archived memory (should be deleted)
        trivial_id = store.add_memory(1, "thought", {"text": "trivial"}, "trivial", created_sim_tick=50, importance=0.5, archived=True)

        # Prune before tick 200
        deleted = store.prune_trivial_memories(200)

        # Only trivial should be deleted
        assert deleted == 1

        # Verify protected memories still exist
        assert store.get_memory(cons_id) is not None
        assert store.get_memory(diary_id) is not None
        assert store.get_memory(legacy_id) is not None
        assert store.get_memory(trivial_id) is None

    def test_prune_trivial_memories_protects_compact_and_dream(self, store):
        compact_id = store.add_memory(1, "compact", {"text": "compact"}, "compact", created_sim_tick=50, importance=0.5, archived=True)
        dream_id = store.add_memory(1, "dream", {"text": "dream"}, "dream", created_sim_tick=50, importance=0.5, archived=True)
        trivial_id = store.add_memory(1, "thought", {"text": "trivial"}, "trivial", created_sim_tick=50, importance=0.5, archived=True)

        deleted = store.prune_trivial_memories(200)
        assert deleted == 1  # Only trivial deleted

        assert store.get_memory(compact_id) is not None
        assert store.get_memory(dream_id) is not None
        assert store.get_memory(trivial_id) is None

    def test_mark_consolidated(self, store):
        id1 = store.add_memory(1, "thought", {"text": "mem1"}, "mem1", created_sim_tick=100)
        id2 = store.add_memory(1, "thought", {"text": "mem2"}, "mem2", created_sim_tick=200)

        store.mark_consolidated([id1, id2], tick=300)

        mem1 = store.get_memory(id1)
        mem2 = store.get_memory(id2)
        assert mem1["consolidated"] == 1
        assert mem2["consolidated"] == 1
        assert mem1["last_accessed_sim_tick"] == 300
        assert mem2["last_accessed_sim_tick"] == 300

    def test_count_consolidated(self, store):
        store.add_memory(1, "thought", {"text": "mem1"}, "mem1", created_sim_tick=100, consolidated=True)
        store.add_memory(1, "thought", {"text": "mem2"}, "mem2", created_sim_tick=200, consolidated=True)
        store.add_memory(1, "thought", {"text": "mem3"}, "mem3", created_sim_tick=300)  # not consolidated

        count = store.count_consolidated(1)
        assert count == 2

    def test_tick_management(self, store):
        store.set_tick(500)
        assert store.get_tick() == 500

        store.set_committed_tick(400)
        assert store.get_committed_tick() == 400

    def test_snapshot_revision(self, store):
        store.set_tick(100)
        store.set_committed_tick(50)
        snap = store.snapshot_revision()
        assert snap["schema_version"] == SCHEMA_VERSION
        assert snap["world_sim_tick"] == 100
        assert snap["last_committed_at"] == 50

    def test_vacuum(self, store):
        # Should not raise
        store.vacuum()

    def test_decay_memories(self, store):
        id1 = store.add_memory(1, "thought", {"text": "mem1"}, "mem1", created_sim_tick=100, strength=1.0)
        id2 = store.add_memory(1, "thought", {"text": "mem2"}, "mem2", created_sim_tick=200, strength=0.8)

        store.decay_memories(1, {id1: 0.5, id2: 0.4})

        mem1 = store.get_memory(id1)
        mem2 = store.get_memory(id2)
        assert mem1["strength"] == 0.5
        assert mem2["strength"] == 0.4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])