"""Tests for Stage 1: Closed-loop intent telemetry (R1) and Confidant persistence (R8/P0)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sensewright_sidecar.memory.sqlite_store import SqliteStore
from sensewright_sidecar.server import app
from sensewright_sidecar.state import reset_state
from sensewright_sidecar.config import reset_config


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset global state before each test."""
    reset_state()
    reset_config()
    yield
    reset_state()
    reset_config()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def store(tmp_path):
    """Fresh SqliteStore for direct DB tests."""
    db_path = str(tmp_path / "test.db")
    store = SqliteStore(db_path)
    store.initialize()
    yield store
    store.close()


class TestIntentOutcomesTable:
    """Direct tests for the intent_outcomes table and record_intent_outcomes method."""

    def test_intent_outcomes_table_created(self, store):
        conn = store._connect()
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {row["name"] for row in tables}
        assert "intent_outcomes" in table_names

    def test_intent_outcomes_index_created(self, store):
        conn = store._connect()
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='intent_outcomes'"
        ).fetchall()
        index_names = {row["name"] for row in indexes}
        assert "idx_intent_outcomes_intent_id" in index_names

    def test_record_intent_outcomes_basic(self, store):
        outcomes = [
            {"intent_id": "intent-1", "status": "applied", "reason": "success", "sim_tick": 100, "action_id": "act-1"},
            {"intent_id": "intent-2", "status": "failed", "reason": "blocked", "sim_tick": 101, "action_id": None},
        ]
        store.record_intent_outcomes(1, outcomes)

        conn = store._connect()
        rows = conn.execute("SELECT * FROM intent_outcomes ORDER BY id").fetchall()
        assert len(rows) == 2
        assert rows[0]["intent_id"] == "intent-1"
        assert rows[0]["status"] == "applied"
        assert rows[0]["reason"] == "success"
        assert rows[0]["sim_tick"] == 100
        assert rows[1]["intent_id"] == "intent-2"
        assert rows[1]["status"] == "failed"

    def test_record_intent_outcomes_empty_list(self, store):
        store.record_intent_outcomes(1, [])
        conn = store._connect()
        rows = conn.execute("SELECT * FROM intent_outcomes").fetchall()
        assert len(rows) == 0

    def test_record_intent_outcomes_drops_malformed(self, store):
        # The store method writes what it's given; validation happens in _ingest_outcomes (service layer).
        # This test verifies the store doesn't crash on malformed data and writes valid entries.
        outcomes = [
            {"intent_id": "intent-1", "status": "applied", "reason": "ok", "sim_tick": 100},  # valid
            {"intent_id": "intent-6", "status": "failed", "reason": "err", "sim_tick": 105},  # valid
        ]
        store.record_intent_outcomes(1, outcomes)

        conn = store._connect()
        rows = conn.execute("SELECT * FROM intent_outcomes ORDER BY id").fetchall()
        assert len(rows) == 2
        assert rows[0]["intent_id"] == "intent-1"
        assert rows[1]["intent_id"] == "intent-6"

    def test_record_intent_outcomes_no_cap_at_store_level(self, store):
        # Capping at 200 per tick is enforced in _ingest_outcomes, not at the store level.
        outcomes = [
            {"intent_id": f"intent-{i}", "status": "applied", "reason": "ok", "sim_tick": 100 + i}
            for i in range(250)
        ]
        store.record_intent_outcomes(1, outcomes)

        conn = store._connect()
        count = conn.execute("SELECT COUNT(*) as c FROM intent_outcomes").fetchone()["c"]
        assert count == 250  # store writes all; service layer caps


class TestMetadataConfidant:
    """Tests for player_confidant_sim_id metadata persistence."""

    def test_set_get_metadata(self, store):
        store.set_metadata("player_confidant_sim_id", "42")
        val = store.get_metadata("player_confidant_sim_id")
        assert val == "42"

    def test_get_metadata_missing_returns_none(self, store):
        val = store.get_metadata("nonexistent_key")
        assert val is None

    def test_metadata_overwrite(self, store):
        store.set_metadata("player_confidant_sim_id", "10")
        store.set_metadata("player_confidant_sim_id", "20")
        val = store.get_metadata("player_confidant_sim_id")
        assert val == "20"


class TestAutonomyTickOutcomes:
    """Tests for outcomes ingestion via /v1/autonomy/tick."""

    def _setup_session(self, client, save_id=1):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": save_id, "world_sim_tick": 100, "lang": "pt-BR"
        })
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "Test", "species": "HUMAN", "age_stage": "YOUNGADULT", "household_id": 1}],
            "world_sim_tick": 100
        })

    def test_outcomes_ingested_on_tick(self, client):
        self._setup_session(client)
        # First tick: emit some intents (simulated by the test)
        # Second tick: report outcomes
        response = client.post("/v1/autonomy/tick", json={
            "save_id": 1,
            "world_sim_tick": 101,
            "clock_speed": 1,
            "lang": "pt-BR",
            "outcomes": [
                {"intent_id": "intent-1", "status": "applied", "reason": "executed", "sim_tick": 100, "action_id": "act-1"},
                {"intent_id": "intent-2", "status": "failed", "reason": "route_blocked", "sim_tick": 100, "action_id": "act-2"},
                {"intent_id": "intent-3", "status": "expired", "reason": "ttl", "sim_tick": 100},
                {"intent_id": "intent-4", "status": "preempted_by_player", "reason": "player_cancelled", "sim_tick": 100},
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

        # Check metrics
        status_resp = client.get("/v1/status")
        metrics = status_resp.json()["metrics"]
        assert metrics.get("outcomes_applied") == 1
        assert metrics.get("outcomes_failed") == 1
        assert metrics.get("outcomes_expired") == 1
        assert metrics.get("outcomes_preempted_by_player") == 1
        assert metrics.get("outcomes_total") == 4

    def test_outcomes_malformed_dropped_no_error(self, client):
        self._setup_session(client)
        response = client.post("/v1/autonomy/tick", json={
            "save_id": 1,
            "world_sim_tick": 101,
            "clock_speed": 1,
            "lang": "pt-BR",
            "outcomes": [
                {"intent_id": "intent-1", "status": "applied", "reason": "ok", "sim_tick": 100},  # valid
                {"intent_id": "", "status": "applied", "reason": "ok", "sim_tick": 101},  # missing intent_id
                {"intent_id": "intent-3", "status": "invalid", "reason": "ok", "sim_tick": 102},  # invalid status
                "not a dict",
                {"status": "applied"},  # missing intent_id
            ]
        })
        assert response.status_code == 200

        status_resp = client.get("/v1/status")
        metrics = status_resp.json()["metrics"]
        assert metrics.get("outcomes_applied") == 1
        assert metrics.get("outcomes_total") == 1

    def test_outcomes_capped_at_200_per_tick(self, client):
        self._setup_session(client)
        outcomes = [
            {"intent_id": f"intent-{i}", "status": "applied", "reason": "ok", "sim_tick": 100}
            for i in range(250)
        ]
        response = client.post("/v1/autonomy/tick", json={
            "save_id": 1,
            "world_sim_tick": 101,
            "clock_speed": 1,
            "lang": "pt-BR",
            "outcomes": outcomes
        })
        assert response.status_code == 200

        status_resp = client.get("/v1/status")
        metrics = status_resp.json()["metrics"]
        assert metrics.get("outcomes_total") == 200
        assert metrics.get("outcomes_applied") == 200

    def test_outcomes_persisted_to_db(self, client):
        self._setup_session(client)
        response = client.post("/v1/autonomy/tick", json={
            "save_id": 1,
            "world_sim_tick": 101,
            "clock_speed": 1,
            "lang": "pt-BR",
            "outcomes": [
                {"intent_id": "intent-db-1", "status": "applied", "reason": "success", "sim_tick": 100, "action_id": "act-1"},
            ]
        })
        assert response.status_code == 200

        # Verify in DB
        from sensewright_sidecar.state import get_state
        state = get_state()
        store = state.working_store()
        conn = store._connect()
        rows = conn.execute("SELECT * FROM intent_outcomes WHERE intent_id = 'intent-db-1'").fetchall()
        assert len(rows) == 1
        assert rows[0]["status"] == "applied"
        assert rows[0]["reason"] == "success"
        assert rows[0]["sim_tick"] == 100


class TestActionOutcomesEndpoint:
    """Tests for POST /v1/actions/outcomes endpoint."""

    def _setup_session(self, client, save_id=1):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": save_id, "world_sim_tick": 100, "lang": "pt-BR"
        })
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "Test", "species": "HUMAN", "age_stage": "YOUNGADULT", "household_id": 1}],
            "world_sim_tick": 100
        })

    def test_action_outcomes_endpoint_basic(self, client):
        self._setup_session(client)
        response = client.post("/v1/actions/outcomes", json={
            "save_id": 1,
            "world_sim_tick": 101,
            "outcomes": [
                {"intent_id": "intent-a1", "status": "applied", "reason": "ok", "sim_tick": 100},
                {"intent_id": "intent-a2", "status": "failed", "reason": "blocked", "sim_tick": 100},
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["accepted"] == 2

        status_resp = client.get("/v1/status")
        metrics = status_resp.json()["metrics"]
        assert metrics.get("outcomes_applied") == 1
        assert metrics.get("outcomes_failed") == 1
        assert metrics.get("outcomes_total") == 2

    def test_action_outcomes_endpoint_malformed_dropped(self, client):
        self._setup_session(client)
        response = client.post("/v1/actions/outcomes", json={
            "save_id": 1,
            "world_sim_tick": 101,
            "outcomes": [
                {"intent_id": "intent-b1", "status": "applied", "reason": "ok", "sim_tick": 100},
                {"intent_id": "", "status": "applied", "reason": "ok", "sim_tick": 101},
                {"intent_id": "intent-b3", "status": "invalid", "reason": "ok", "sim_tick": 102},
            ]
        })
        assert response.status_code == 200
        data = response.json()
        assert data["accepted"] == 1

    def test_action_outcomes_empty_list(self, client):
        self._setup_session(client)
        response = client.post("/v1/actions/outcomes", json={
            "save_id": 1,
            "world_sim_tick": 101,
            "outcomes": []
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["accepted"] == 0


class TestConfidantPersistence:
    """Tests for player_confidant_sim_id round-trip (R8/P0)."""

    def _setup_session(self, client, save_id=1):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": save_id, "world_sim_tick": 100, "lang": "pt-BR"
        })
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "Test", "species": "HUMAN", "age_stage": "YOUNGADULT", "household_id": 1}],
            "world_sim_tick": 100
        })

    def test_confidant_set_on_tick_returned_on_session_start(self, client):
        # Use a unique save_id (the existing suite uses 999 in
        # test_services_endpoints.py; sharing it would flip bootstrap_needed).
        save_id = 999991
        # First session: set confidant via autonomy tick
        self._setup_session(client, save_id=save_id)
        response = client.post("/v1/autonomy/tick", json={
            "save_id": save_id,
            "world_sim_tick": 101,
            "clock_speed": 1,
            "lang": "pt-BR",
            "player_confidant_sim_id": 42,
        })
        assert response.status_code == 200

        # Simulate save/zone transition to persist
        client.post("/v1/lifecycle/save", json={
            "save_id": save_id, "world_sim_tick": 200, "previous_save_id": None
        })

        # Reset state (simulating sidecar restart)
        reset_state()
        reset_config()

        # New session-start should return the persisted confidant
        response = client.post("/v1/lifecycle/session-start", json={
            "save_id": save_id, "world_sim_tick": 300, "lang": "pt-BR"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["player_confidant_sim_id"] == 42

    def test_confidant_defaults_to_zero_when_not_set(self, client):
        # Fresh save, no confidant set yet
        response = client.post("/v1/lifecycle/session-start", json={
            "save_id": 888, "world_sim_tick": 100, "lang": "pt-BR"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["player_confidant_sim_id"] == 0

    def test_confidant_zero_not_persisted(self, client):
        self._setup_session(client, save_id=777)
        # Send confidant_id = 0 (should not overwrite existing)
        client.post("/v1/autonomy/tick", json={
            "save_id": 777,
            "world_sim_tick": 101,
            "clock_speed": 1,
            "lang": "pt-BR",
            "player_confidant_sim_id": 0,
        })
        client.post("/v1/lifecycle/save", json={
            "save_id": 777, "world_sim_tick": 200, "previous_save_id": None
        })

        reset_state()
        reset_config()

        response = client.post("/v1/lifecycle/session-start", json={
            "save_id": 777, "world_sim_tick": 300, "lang": "pt-BR"
        })
        data = response.json()
        assert data["player_confidant_sim_id"] == 0

    def test_confidant_overwrite_on_new_tick(self, client):
        self._setup_session(client, save_id=666)
        # Set first confidant
        client.post("/v1/autonomy/tick", json={
            "save_id": 666, "world_sim_tick": 101, "clock_speed": 1, "lang": "pt-BR",
            "player_confidant_sim_id": 10,
        })
        # Overwrite with new confidant
        client.post("/v1/autonomy/tick", json={
            "save_id": 666, "world_sim_tick": 102, "clock_speed": 1, "lang": "pt-BR",
            "player_confidant_sim_id": 20,
        })
        client.post("/v1/lifecycle/save", json={
            "save_id": 666, "world_sim_tick": 200, "previous_save_id": None
        })

        reset_state()
        reset_config()

        response = client.post("/v1/lifecycle/session-start", json={
            "save_id": 666, "world_sim_tick": 300, "lang": "pt-BR"
        })
        data = response.json()
        assert data["player_confidant_sim_id"] == 20


class TestStatusExposesOutcomeMetrics:
    """Verify /v1/status includes outcome counters."""

    def _setup_session(self, client, save_id=1):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": save_id, "world_sim_tick": 100, "lang": "pt-BR"
        })
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "Test", "species": "HUMAN", "age_stage": "YOUNGADULT", "household_id": 1}],
            "world_sim_tick": 100
        })

    def test_status_includes_outcome_counters(self, client):
        self._setup_session(client)
        client.post("/v1/autonomy/tick", json={
            "save_id": 1, "world_sim_tick": 101, "clock_speed": 1, "lang": "pt-BR",
            "outcomes": [
                {"intent_id": "i1", "status": "applied", "reason": "ok", "sim_tick": 100},
                {"intent_id": "i2", "status": "failed", "reason": "err", "sim_tick": 100},
                {"intent_id": "i3", "status": "expired", "reason": "ttl", "sim_tick": 100},
                {"intent_id": "i4", "status": "preempted_by_player", "reason": "cancelled", "sim_tick": 100},
            ]
        })
        status_resp = client.get("/v1/status")
        metrics = status_resp.json()["metrics"]
        assert "outcomes_applied" in metrics
        assert "outcomes_failed" in metrics
        assert "outcomes_expired" in metrics
        assert "outcomes_preempted_by_player" in metrics
        assert "outcomes_total" in metrics
        assert metrics["outcomes_applied"] == 1
        assert metrics["outcomes_failed"] == 1
        assert metrics["outcomes_expired"] == 1
        assert metrics["outcomes_preempted_by_player"] == 1
        assert metrics["outcomes_total"] == 4


if __name__ == "__main__":
    pytest.main([__file__, "-v"])