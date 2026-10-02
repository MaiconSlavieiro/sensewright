"""Tests for sensewright_sidecar.world.rumors module."""
from __future__ import annotations

import pytest

from sensewright_sidecar.world.rumors import (
    create_rumor,
    can_comment,
    spread,
    rumors_known_by,
)
from sensewright_sidecar.memory.sqlite_store import SqliteStore
from sensewright_sidecar.world.rumors import get_rumors, save_rumors


class TestCreateRumor:
    """Tests for create_rumor."""

    def test_creates_rumor_with_expected_fields(self):
        rumor = create_rumor("Test rumor", ["tag1", "tag2"], 1, 100)
        assert "id" in rumor
        assert len(rumor["id"]) == 12
        assert rumor["text"] == "Test rumor"
        assert rumor["tags"] == ["tag1", "tag2"]
        assert rumor["known_by_sim_ids"] == [1]
        assert rumor["created_sim_tick"] == 100
        assert rumor["source_sim_id"] == 1

    def test_empty_tags(self):
        rumor = create_rumor("Test", [], 1, 100)
        assert rumor["tags"] == []

    def test_none_tags(self):
        rumor = create_rumor("Test", None, 1, 100)
        assert rumor["tags"] == []


class TestCanComment:
    """Tests for can_comment."""

    def test_sim_in_known_by_can_comment(self):
        rumor = {"known_by_sim_ids": [1, 2, 3]}
        assert can_comment(rumor, 1) is True
        assert can_comment(rumor, 2) is True

    def test_sim_not_in_known_by_cannot_comment(self):
        rumor = {"known_by_sim_ids": [1, 2]}
        assert can_comment(rumor, 3) is False

    def test_empty_known_by(self):
        rumor = {"known_by_sim_ids": []}
        assert can_comment(rumor, 1) is False

    def test_none_known_by(self):
        rumor = {"known_by_sim_ids": None}
        assert can_comment(rumor, 1) is False

    def test_string_ids_coerced(self):
        rumor = {"known_by_sim_ids": ["1", "2"]}
        assert can_comment(rumor, 1) is True


class TestSpread:
    """Tests for spread."""

    def test_adds_sim_to_known_by(self):
        rumor = {"known_by_sim_ids": [1]}
        rumor = spread(rumor, 2)
        assert rumor["known_by_sim_ids"] == [1, 2]

    def test_does_not_duplicate(self):
        rumor = {"known_by_sim_ids": [1, 2]}
        rumor = spread(rumor, 1)
        assert rumor["known_by_sim_ids"] == [1, 2]

    def test_returns_new_dict(self):
        rumor = {"known_by_sim_ids": [1]}
        new_rumor = spread(rumor, 2)
        assert new_rumor is not rumor
        assert rumor["known_by_sim_ids"] == [1]  # Original unchanged

    def test_empty_known_by(self):
        rumor = {"known_by_sim_ids": []}
        rumor = spread(rumor, 1)
        assert rumor["known_by_sim_ids"] == [1]


class TestRumorsKnownBy:
    """Tests for rumors_known_by."""

    def test_filters_rumors(self):
        rumors = [
            {"id": "r1", "known_by_sim_ids": [1]},
            {"id": "r2", "known_by_sim_ids": [2]},
            {"id": "r3", "known_by_sim_ids": [1, 2]},
        ]
        known = rumors_known_by(rumors, 1)
        assert len(known) == 2
        assert all(1 in r["known_by_sim_ids"] for r in known)

    def test_empty_list(self):
        assert rumors_known_by([], 1) == []


class TestRumorsPersistence:
    """Tests for rumor persistence via SqliteStore."""

    @pytest.fixture
    def store(self, tmp_path):
        db_path = str(tmp_path / "test.db")
        store = SqliteStore(db_path)
        store.initialize()
        yield store
        store.close()

    def test_get_rumors_empty(self, store):
        rumors = get_rumors(store, 1)
        assert rumors == []

    def test_save_and_get_rumors(self, store):
        rumors = [
            {"id": "r1", "text": "Rumor 1", "known_by_sim_ids": [1]},
            {"id": "r2", "text": "Rumor 2", "known_by_sim_ids": [2]},
        ]
        save_rumors(store, 1, rumors, 100)
        retrieved = get_rumors(store, 1)
        assert len(retrieved) == 2
        assert retrieved[0]["id"] == "r1"
        assert retrieved[1]["id"] == "r2"

    def test_save_rumors_updates_existing(self, store):
        rumors = [{"id": "r1", "text": "Original", "known_by_sim_ids": [1]}]
        save_rumors(store, 1, rumors, 100)

        rumors[0]["text"] = "Updated"
        save_rumors(store, 1, rumors, 200)

        retrieved = get_rumors(store, 1)
        assert retrieved[0]["text"] == "Updated"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])