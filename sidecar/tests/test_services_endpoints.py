"""Tests for Sensewright sidecar API endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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


class TestHealthEndpoints:
    """Tests for health and status endpoints."""

    def test_health(self, client):
        response = client.get("/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_status(self, client):
        response = client.get("/v1/status")
        assert response.status_code == 200
        data = response.json()
        assert "chain" in data
        assert "providers" in data
        assert "routes" in data
        assert "tiers" in data
        assert "queue" in data
        assert "active_save" in data


class TestLifecycleEndpoints:
    """Tests for lifecycle endpoints."""

    def test_attach(self, client):
        response = client.post("/v1/lifecycle/attach", json={"game_pid": 1234})
        assert response.status_code == 200
        assert response.json() == {"ok": True}

    def test_session_start_new_save(self, client):
        # Use a unique save_id to avoid conflicts with other tests
        response = client.post("/v1/lifecycle/session-start", json={
            "save_id": 999,
            "world_sim_tick": 100,
            "lang": "pt-BR"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["bootstrap_needed"] is True
        assert data["restored_tick"] is None

    def test_zone_transition(self, client):
        # First start a session
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR"
        })
        response = client.post("/v1/lifecycle/zone-transition", json={
            "save_id": 1, "world_sim_tick": 200
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "cleared_spatial_intents" in data

    def test_save(self, client):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR"
        })
        response = client.post("/v1/lifecycle/save", json={
            "save_id": 1, "world_sim_tick": 200, "previous_save_id": None
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["committed_tick"] == 200


class TestCensusAndAutonomy:
    """Tests for census and autonomy endpoints."""

    def test_census(self, client):
        response = client.post("/v1/census", json={
            "sims": [
                {"sim_id": 1, "name": "Test", "species": "HUMAN", "age_stage": "YOUNGADULT"}
            ],
            "world_sim_tick": 100
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["hydrated_count"] == 1

    def test_autonomy_tick_paused(self, client):
        # Start session first
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR"
        })
        # Census to populate sims
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "Test", "species": "HUMAN", "age_stage": "YOUNGADULT", "household_id": 1}],
            "world_sim_tick": 100
        })
        # Autonomy tick with clock_speed=0 (paused)
        response = client.post("/v1/autonomy/tick", json={
            "world_sim_tick": 100,
            "clock_speed": 0,
            "lang": "pt-BR"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["scheduled"] == 0
        assert data["intents"] == []
        assert data["social_sessions"] == []

    def test_autonomy_intents(self, client):
        response = client.get("/v1/autonomy/intents")
        assert response.status_code == 200
        data = response.json()
        assert "intents" in data
        assert isinstance(data["intents"], list)


class TestChatEndpoints:
    """Tests for chat endpoints."""

    def test_chat_fallback_response(self, client):
        # Start session and census
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR"
        })
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "Test", "species": "HUMAN", "age_stage": "YOUNGADULT", "friendship": 50.0}],
            "world_sim_tick": 100
        })
        response = client.post("/v1/chat", json={
            "sim_id": 1,
            "channel": "phone_sms",
            "message": "Hello",
            "player_name": "Player",
            "world_sim_tick": 100,
            "lang": "pt-BR"
        })
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert isinstance(data["response"], str)
        assert len(data["response"]) > 0  # Fallback should be non-empty
        assert "thought" in data
        assert "intents" in data
        assert "trust_delta" in data
        assert "deferred" in data

    def test_hey_alias(self, client):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR"
        })
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "Test", "species": "HUMAN", "age_stage": "YOUNGADULT", "friendship": 50.0}],
            "world_sim_tick": 100
        })
        response = client.post("/v1/hey", json={
            "sim_id": 1,
            "message": "Hello",
            "player_name": "Player",
            "world_sim_tick": 100,
            "lang": "pt-BR"
        })
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert len(data["response"]) > 0


class TestEventsEndpoint:
    """Tests for events endpoint."""

    def test_events_salience_computed(self, client):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR"
        })
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "Test", "species": "HUMAN", "age_stage": "YOUNGADULT"}],
            "world_sim_tick": 100
        })
        response = client.post("/v1/events", json={
            "sim_id": 1,
            "event_category": "death",
            "impact": 1.0,
            "world_sim_tick": 100,
            "lang": "pt-BR"
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert "salience" in data
        assert data["salience"] >= 1.5  # death weight 2.5 + impact 1.0 = 3.5
        assert "triggered_jobs" in data


class TestProfileEndpoint:
    """Tests for profile endpoint."""

    def test_profile_returns_dict(self, client):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR"
        })
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "Test", "species": "HUMAN", "age_stage": "YOUNGADULT", "traits": ["creative"]}],
            "world_sim_tick": 100
        })
        response = client.post("/v1/profile", json={
            "sim_id": 1,
            "world_sim_tick": 100,
            "lang": "pt-BR"
        })
        assert response.status_code == 200
        data = response.json()
        assert "profile" in data
        assert isinstance(data["profile"], dict)
        assert data["profile"]["name"] == "Test"


class TestGodEndpoints:
    """Tests for God Director endpoints."""

    def test_controls_get(self, client):
        response = client.get("/v1/god/controls")
        assert response.status_code == 200
        data = response.json()
        assert "controls" in data
        controls = data["controls"]
        assert isinstance(controls, list)
        # Check for expected control keys
        keys = {c["key"] for c in controls}
        assert "intensity" in keys
        assert "preset" in keys
        assert "director_mode" in keys

    def test_controls_post(self, client):
        response = client.post("/v1/god/controls", json={
            "key": "intensity",
            "value": 0.8
        })
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True

        # Verify it persisted
        response2 = client.get("/v1/god/controls")
        controls = {c["key"]: c["value"] for c in response2.json()["controls"]}
        assert controls["intensity"] == 0.8

    def test_god_tick(self, client):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR"
        })
        response = client.post("/v1/god/tick", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR"
        })
        assert response.status_code == 200
        data = response.json()
        assert "directives" in data

    def test_zeitgeist(self, client):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR"
        })
        response = client.post("/v1/god/zeitgeist", json={
            "save_id": 1, "zeitgeist_text": "A dark storm approaches", "lang": "pt-BR"
        })
        assert response.status_code == 200
        data = response.json()
        assert "tags" in data
        assert "preset" in data
        assert "weather_preference" in data


class TestAgencySeatsEndpoint:
    """Tests for agency/seats endpoints."""

    def test_seats_get(self, client):
        response = client.get("/v1/agency/seats")
        assert response.status_code == 200
        data = response.json()
        assert "seats" in data
        assert "pool" in data
        assert isinstance(data["seats"], list)
        assert isinstance(data["pool"], int)

    def test_seats_post(self, client):
        response = client.post("/v1/agency/seats", json={"seats": 8})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["seats"] == 8


class TestConfigLangEndpoint:
    """Tests for config/lang endpoint."""

    def test_config_lang(self, client):
        response = client.post("/v1/config/lang", json={"lang": "pt-BR"})
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["lang"] == "pt-BR"


class TestWebUIEndpoints:
    """Tests for Web UI endpoints."""

    def test_ui_manifest(self, client):
        response = client.get("/ui/manifest.json")
        assert response.status_code == 200
        data = response.json()
        assert "locales" in data
        assert "default_locale" in data

    def test_ui_locales(self, client):
        # Test with a known locale
        response = client.get("/ui/locales/pt-BR.json")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_ui_locales_unknown_resolves_to_default(self, client):
        # Unknown locale codes are resolved to default via manifest
        response = client.get("/ui/locales/xx-YY.json")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert len(data) > 0  # Returns default locale data


class TestPlayerActivityEndpoint:
    """Tests for player-activity endpoint."""

    def test_player_activity(self, client):
        response = client.post("/v1/config/player-activity", json={
            "idle": True, "clock_speed": 0
        })
        assert response.status_code == 200
        data = response.json()
        assert "deep_window_open" in data
        assert data["deep_window_open"] is True


class TestConversationalPairDetection:
    """The mod reports interaction class names, not semantic activities."""

    def _state_with(self, activities):
        from sensewright_sidecar.state import get_state
        state = get_state()
        state.update_census({
            i + 1: {"sim_id": i + 1, "activity": activity}
            for i, activity in enumerate(activities)
        })
        return state

    def test_matches_interaction_class_names(self):
        from sensewright_sidecar.services import _find_conversational_pair
        state = self._state_with(["SocialInteraction", "Chatting"])
        pair = _find_conversational_pair(state, 1)
        assert pair is not None
        assert {pair[0]["sim_id"], pair[1]["sim_id"]} == {1, 2}

    def test_busy_sim_is_not_conversing(self):
        from sensewright_sidecar.services import _find_conversational_pair
        state = self._state_with(["SocialInteraction", "Sleeping"])
        assert _find_conversational_pair(state, 1) is None

    def test_unrelated_activity_is_not_conversing(self):
        from sensewright_sidecar.services import _find_conversational_pair
        state = self._state_with(["Painting", "Gardening"])
        assert _find_conversational_pair(state, 1) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])