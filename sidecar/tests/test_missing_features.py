"""Tests for the P1/P4 feature wiring (docs/status.md gaps closed 2026-10-03)."""
from __future__ import annotations

import os
import types

import pytest

from sensewright_sidecar import services
from sensewright_sidecar.config import reset_config
from sensewright_sidecar.fallbacks import render_fallback
from sensewright_sidecar.constants import PRESENCE_OFF
from sensewright_sidecar.god.arcs import create_arc
from sensewright_sidecar.god.orchestrator import god_tick
from sensewright_sidecar.state import get_state, reset_state


class _FakeScheduler:
    def __init__(self):
        self.jobs = []

    def submit_bg(self, purpose_id, context=None, lang="", trace_id=None,
                  dedup_key=None, callback=None):
        self.jobs.append(purpose_id)
        if callback is not None:
            callback(types.SimpleNamespace(data=render_fallback(purpose_id, lang, context or {})))

    def submit_async(self, purpose_id, context=None, lang="", trace_id=None,
                     dedup_key=None, callback=None):
        self.jobs.append(purpose_id)
        if callback is not None:
            callback(types.SimpleNamespace(data=render_fallback(purpose_id, lang, context or {})))

    def run_purpose(self, purpose_id, context=None, lang="", trace_id=None, timeout=None):
        return types.SimpleNamespace(data=render_fallback(purpose_id, lang, context or {}))

    def status(self):
        return {"queue_depth": 0}

    def purposes(self):
        return list(self.jobs)


@pytest.fixture(autouse=True)
def _reset():
    reset_state()
    reset_config()
    yield
    store = get_state().working_store()
    if store is not None:
        store.close()
    reset_state()
    reset_config()


def _state_with_store():
    state = get_state()
    state.save_vault.session_start(1, 1000)
    state.scheduler = _FakeScheduler()
    return state


class TestConversationSessions:
    def test_pair_open_then_close_fires_job(self):
        state = _state_with_store()
        state.update_census({
            1: {"sim_id": 1, "is_conversing": True, "social_target_sim_id": 2,
                "room_id": 1, "pos": {"x": 0.0, "z": 0.0}},
            2: {"sim_id": 2, "room_id": 1, "pos": {"x": 1.0, "z": 0.0}},
        })
        result = services.handle_autonomy_tick({
            "save_id": 1, "world_sim_tick": 1000, "clock_speed": 1,
            "sims_delta": [], "lang": "en-US",
        })
        assert len(state.conversations) == 1
        assert len(result["social_sessions"]) == 1

        state.update_census({
            1: {"sim_id": 1, "is_conversing": False, "activity": "idle"},
            2: {"sim_id": 2, "activity": "idle"},
        })
        state.set_processed_tick(1000)
        services.handle_autonomy_tick({
            "save_id": 1, "world_sim_tick": 1001, "clock_speed": 1,
            "sims_delta": [], "lang": "en-US",
        })
        assert state.conversations == {}
        assert "sim.social.close" in state.scheduler.purposes()


class TestAftermath:
    def test_high_salience_event_schedules_aftermath(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "A"}})
        result = services.handle_event({
            "sim_id": 1, "event_category": "death", "impact": 2.0,
            "world_sim_tick": 100, "lang": "en-US",
        })
        assert "world.aftermath" in result["triggered_jobs"]

    def test_low_salience_event_skips_aftermath(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "A"}})
        result = services.handle_event({
            "sim_id": 1, "event_category": "mundane", "impact": 0.0,
            "world_sim_tick": 100, "lang": "en-US",
        })
        assert "world.aftermath" not in result["triggered_jobs"]


class TestOps:
    def test_recap_scheduled_and_stored(self):
        state = get_state()
        state.scheduler = _FakeScheduler()
        result = services.handle_session_start({
            "save_id": 1, "world_sim_tick": 1000, "lang": "en-US",
        })
        assert result["ok"] is True
        assert "ops.recap" in state.scheduler.purposes()
        assert services.handle_recap_get()["recap"]["tick"] == 1000

    def test_panel_summary_shape(self):
        _state_with_store()
        summary = services.handle_panel_summary()["summary"]
        assert "line1" in summary and "line2" in summary and "\n" in summary["text"]


class TestAspiration:
    def test_aspiration_persisted(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "A"}})
        result = services.handle_aspiration({
            "sim_id": 1, "world_sim_tick": 100, "lang": "en-US",
        })
        assert "ambition" in result
        profile = (state.working_store().get_sim_profile(1) or {}).get("profile") or {}
        assert "ambition" in profile


class TestProfilePersistence:
    def test_posted_profile_saved(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "A"}})
        result = services.handle_profile({
            "sim_id": 1, "world_sim_tick": 100, "lang": "en-US",
            "profile": {"goals": ["sleep"], "ambition": "be rich"},
        })
        assert result["profile"]["ambition"] == "be rich"
        saved = (state.working_store().get_sim_profile(1) or {}).get("profile") or {}
        assert saved["ambition"] == "be rich"


class TestPanic:
    def test_panic_pauses_freezes_and_resumes(self):
        state = _state_with_store()
        state.enqueue_intents([{"sim_id": 1, "kind": "speak", "params": {}}])
        result = services.handle_config_panic({})
        assert result["paused"] is True
        assert result["drained_intents"] == 1
        frozen = services.handle_autonomy_tick({
            "save_id": 1, "world_sim_tick": 500, "clock_speed": 1, "sims_delta": [],
        })
        assert frozen.get("paused") is True
        services.handle_config_resume({})
        assert state.paused is False


class TestProviderConfig:
    def test_provider_config_updates_in_place(self):
        state = _state_with_store()
        result = services.handle_provider_config({
            "provider": "openrouter", "enabled": True,
            "api_key": "sk-test", "models": ["m"],
        })
        assert result["ok"] is True
        assert result["api_key_set"] is True
        assert state.config.provider("openrouter")["api_key"] == "sk-test"


class TestArcRead:
    def test_get_arc_and_cast(self):
        state = _state_with_store()
        arc = create_arc("theme", [{"title": "b"}], [{"sim_id": 9, "role": "catalyst"}], 1)
        state.active_arc = arc
        assert services.handle_get_arc()["arc"]["id"] == arc["id"]
        assert services.handle_get_cast()["cast"][0]["sim_id"] == 9


class TestPresenceOff:
    def test_sensory_only_and_excluded_are_off(self):
        from sensewright_sidecar.agent.presence import presence_tier

        assert presence_tier(False, True, False, species="DOG", age_stage="ADULT") == PRESENCE_OFF
        assert presence_tier(False, False, False, species="HUMAN", age_stage="INFANT") == PRESENCE_OFF
        assert presence_tier(False, False, False, species="HUMAN", age_stage="ADULT") != PRESENCE_OFF


class TestLeaseExpiration:
    def test_expired_lease_is_cleared(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "A"}})
        state.catalyst_leases = {1: {"objective": "x", "lease_expires_tick": 100}}
        god_tick(state, 1, 5000, "en-US")
        assert 1 not in state.catalyst_leases


class TestSeatsEnrichment:
    """Seats endpoint must carry sim identity/profile/background (Web Studio fix)."""

    def test_seats_carry_name_profile_background(self):
        state = _state_with_store()
        store = state.working_store()
        state.update_census({
            1: {"sim_id": 1, "name": "Alice", "household_id": 10},
            2: {"sim_id": 2, "name": "Bob", "household_id": 10},
        })
        store.upsert_sim_profile(1, {"name": "Alice", "core_personality": "gregarious"}, 1000)
        store.set_sim_background(1, "A retired chef.", 1000)
        state.relationships = {"1:2": {"friendship": 30.0, "romance": 0.0}}
        state.set_seats({
            1: {"sim_id": 1, "role": "household", "tier": "full", "lease_expires_tick": 2000},
        })

        result = services.handle_seats_get()
        assert result["pool"] >= 0
        seat = result["seats"][0]
        assert seat["name"] == "Alice"
        assert seat["profile"]["core_personality"] == "gregarious"
        assert seat["background"] == "A retired chef."
        assert seat["relationships"][0]["target_name"] == "Bob"


class TestCompileAddon:
    def test_compile_addon_writes_package(self, tmp_path, monkeypatch):
        state = _state_with_store()
        monkeypatch.setattr(state, "data_dir", tmp_path)
        result = services.handle_compile_addon({
            "locale": "en-US", "locale_byte": 0,
            "strings": {"stbl.diary.title": "Diary"},
        })
        assert result["ok"] is True
        assert result["strings"] == 1
        assert os.path.exists(result["path"])


class TestPanicRead:
    """GET /v1/config/panic must expose the real switch state (Web Studio fix)."""

    def test_panic_state_readable(self):
        _state_with_store()
        assert services.handle_config_panic_state()["paused"] is False
        services.handle_config_panic({})
        assert services.handle_config_panic_state()["paused"] is True
        services.handle_config_resume({})
        assert services.handle_config_panic_state()["paused"] is False


class TestRelationshipReviewCadence:
    """The per-sim-day cadence advances only after the job's callback lands."""

    def _deferred_scheduler(self, captured):
        class _Deferred:
            def submit_bg(self, purpose_id, context=None, lang="", trace_id=None,
                          dedup_key=None, callback=None):
                captured["purpose"] = purpose_id
                captured["callback"] = callback
        return _Deferred()

    def _seed(self, state):
        state.update_census({
            1: {"sim_id": 1, "name": "A", "household_id": 1},
            2: {"sim_id": 2, "name": "B", "household_id": 1},
        })
        state.relationships = {"1:2": {"friendship": 40.0, "romance": 0.0}}

    def test_tick_advances_only_after_callback(self):
        state = _state_with_store()
        self._seed(state)
        captured = {}
        state.scheduler = self._deferred_scheduler(captured)

        scheduled = services._maybe_relationship_review(
            state, tick=5000, lang="en-US", trace_id="t", active_sim_id=1)
        assert scheduled == 1
        assert captured["purpose"] == "mem.relationship.review"
        # In flight: cadence must NOT have advanced yet.
        assert 1 not in state.last_relationship_review_tick
        # Callback lands -> cadence advances.
        captured["callback"](types.SimpleNamespace(data={"qualitative_note": "close"}))
        assert state.last_relationship_review_tick[1] == 5000

    def test_stale_epoch_callback_does_not_advance(self):
        state = _state_with_store()
        self._seed(state)
        captured = {}
        state.scheduler = self._deferred_scheduler(captured)

        services._maybe_relationship_review(
            state, tick=5000, lang="en-US", trace_id="t", active_sim_id=1)
        # A session reset/rewind bumps the epoch, dropping the in-flight result.
        state.bump_epoch()
        captured["callback"](types.SimpleNamespace(data={"qualitative_note": "close"}))
        assert 1 not in state.last_relationship_review_tick

