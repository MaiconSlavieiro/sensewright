"""Tests for sensewright_sidecar.save_vault module."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sensewright_sidecar.memory.sqlite_store import SqliteStore
from sensewright_sidecar.save_vault import SaveVault


class TestSaveVault:
    """Tests for SaveVault."""

    @pytest.fixture
    def vault(self, tmp_path):
        vault = SaveVault(tmp_path)
        yield vault
        vault.shutdown()

    def test_session_start_new_save_bootstrap_needed(self, vault):
        result = vault.session_start(save_id=1, world_sim_tick=100)
        assert result["bootstrap_needed"] is True
        assert result["restored_tick"] is None
        assert vault.active_save_id == 1
        assert vault.working_store() is not None

    def test_session_start_existing_save(self, vault):
        # First session: create and save
        vault.session_start(save_id=1, world_sim_tick=100)
        store = vault.working_store()
        store.add_memory(1, "thought", {"text": "test"}, "test", created_sim_tick=100)
        vault.save(save_id=1, previous_save_id=None, world_sim_tick=200)
        vault.shutdown()  # Close the working store

        # Second session: should restore from committed
        vault2 = SaveVault(vault._saves_dir.parent)
        result = vault2.session_start(save_id=1, world_sim_tick=300)
        assert result["bootstrap_needed"] is False
        assert result["restored_tick"] == 300
        vault2.shutdown()

    def test_session_start_discards_residual_working(self, vault):
        # Create a committed save
        vault.session_start(save_id=1, world_sim_tick=100)
        store = vault.working_store()
        store.add_memory(1, "thought", {"text": "committed"}, "committed", created_sim_tick=100)
        vault.save(save_id=1, previous_save_id=None, world_sim_tick=200)
        vault.shutdown()

        # Create a residual working db manually
        working_path = vault.working_path(1)
        residual_store = SqliteStore(working_path)
        residual_store.initialize()
        residual_store.add_memory(1, "thought", {"text": "residual"}, "residual", created_sim_tick=999)
        residual_store.close()

        # New session should discard residual
        vault2 = SaveVault(vault._saves_dir.parent)
        result = vault2.session_start(save_id=1, world_sim_tick=300)
        assert result["bootstrap_needed"] is False

        # The residual memory should be gone
        restored_store = vault2.working_store()
        memories = restored_store.recent_memories(1, limit=10, include_archived=True)
        texts = [m["content"]["text"] for m in memories]
        assert "residual" not in texts
        assert "committed" in texts
        vault2.shutdown()

    def test_add_memory_then_save_committed_exists(self, vault):
        vault.session_start(save_id=1, world_sim_tick=100)
        store = vault.working_store()
        store.add_memory(1, "thought", {"text": "session memory"}, "session memory", created_sim_tick=150)
        result = vault.save(save_id=1, previous_save_id=None, world_sim_tick=200)

        assert result["committed_tick"] == 200
        # Committed file should exist
        committed_path = vault.committed_path(1)
        assert Path(committed_path).exists()

        # Verify memory is in committed db
        committed_store = SqliteStore(committed_path)
        committed_store.initialize()
        memories = committed_store.recent_memories(1, limit=10)
        assert any(m["content"]["text"] == "session memory" for m in memories)
        committed_store.close()

    def test_session_start_again_discards_working(self, vault):
        # Session 1: add memory and save
        vault.session_start(save_id=1, world_sim_tick=100)
        store = vault.working_store()
        store.add_memory(1, "thought", {"text": "session1"}, "session1", created_sim_tick=150)
        vault.save(save_id=1, previous_save_id=None, world_sim_tick=200)

        # Session 2: add different memory, DON'T save
        vault.session_start(save_id=1, world_sim_tick=300)
        store2 = vault.working_store()
        store2.add_memory(1, "thought", {"text": "session2"}, "session2", created_sim_tick=350)
        vault.shutdown()  # Exit without saving

        # Session 3: should only have session1 memory
        vault3 = SaveVault(vault._saves_dir.parent)
        vault3.session_start(save_id=1, world_sim_tick=400)
        store3 = vault3.working_store()
        memories = store3.recent_memories(1, limit=10, include_archived=True)
        texts = [m["content"]["text"] for m in memories]
        assert "session1" in texts
        assert "session2" not in texts  # Uncommitted session discarded
        vault3.shutdown()

    def test_save_as_previous_save_id_differs(self, vault):
        # Save to slot 1
        vault.session_start(save_id=1, world_sim_tick=100)
        store = vault.working_store()
        store.add_memory(1, "thought", {"text": "slot1"}, "slot1", created_sim_tick=100)
        vault.save(save_id=1, previous_save_id=None, world_sim_tick=200)

        # Save As to slot 2
        vault.session_start(save_id=2, world_sim_tick=300)
        store2 = vault.working_store()
        store2.add_memory(2, "thought", {"text": "slot2"}, "slot2", created_sim_tick=300)
        vault.save(save_id=2, previous_save_id=1, world_sim_tick=400)

        # Slot 1 committed should still have slot1 memory
        committed1 = SqliteStore(vault.committed_path(1))
        committed1.initialize()
        mem1 = committed1.recent_memories(1, limit=10)
        assert any(m["content"]["text"] == "slot1" for m in mem1)
        committed1.close()

        # Slot 2 committed should have slot2 memory
        committed2 = SqliteStore(vault.committed_path(2))
        committed2.initialize()
        mem2 = committed2.recent_memories(2, limit=10)
        assert any(m["content"]["text"] == "slot2" for m in mem2)
        committed2.close()

    def test_rewind_when_game_tick_less_than_committed(self, vault):
        # Create committed save at tick 500
        vault.session_start(save_id=1, world_sim_tick=100)
        store = vault.working_store()
        store.add_memory(1, "thought", {"text": "at500"}, "at500", created_sim_tick=500)
        vault.save(save_id=1, previous_save_id=None, world_sim_tick=500)
        vault.shutdown()

        # Game loads older save at tick 300
        vault2 = SaveVault(vault._saves_dir)
        result = vault2.session_start(save_id=1, world_sim_tick=300)
        # Should have rewound
        assert vault2.working_store() is not None
        vault2.shutdown()

    def test_zone_transition_advances_tick(self, vault):
        vault.session_start(save_id=1, world_sim_tick=100)
        vault.zone_transition(save_id=1, world_sim_tick=200)
        assert vault.working_store().get_tick() == 200

    def test_zone_transition_creates_session_if_none(self, vault):
        result = vault.zone_transition(save_id=1, world_sim_tick=100)
        assert result["ok"] is True
        assert vault.active_save_id == 1
        assert vault.working_store() is not None

    def test_ring_buffer_rotation(self, vault):
        vault.session_start(save_id=1, world_sim_tick=100)
        store = vault.working_store()
        store.add_memory(1, "thought", {"text": "v1"}, "v1", created_sim_tick=100)
        vault.save(save_id=1, previous_save_id=None, world_sim_tick=200)  # rev1 created

        store.add_memory(1, "thought", {"text": "v2"}, "v2", created_sim_tick=300)
        vault.save(save_id=1, previous_save_id=None, world_sim_tick=400)  # rev1->rev2, new rev1

        store.add_memory(1, "thought", {"text": "v3"}, "v3", created_sim_tick=500)
        vault.save(save_id=1, previous_save_id=None, world_sim_tick=600)  # rev2 removed, rev1->rev2, new rev1

        # Check ring buffer files exist (only 2 slots: rev1 and rev2)
        assert Path(vault.rev_path(1, 1)).exists()  # Most recent committed (v3)
        assert Path(vault.rev_path(1, 2)).exists()  # Previous (v2)
        assert not Path(vault.rev_path(1, 3)).exists()  # rev3 doesn't exist (only 2 slots)

    def test_shutdown_closes_store(self, vault):
        vault.session_start(save_id=1, world_sim_tick=100)
        assert vault.working_store() is not None
        vault.shutdown()
        assert vault.working_store() is None
        assert vault.active_save_id is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])