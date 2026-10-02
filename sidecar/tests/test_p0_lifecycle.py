"""Tests for the P0 narrative-core wiring.

Covers sleep-cycle edge detection (P07-P09 / P30), speech policy (F11), CHILD
hard-block (F12), life-story limits (REQ-PSY-03) and rumor creation/contagion
(F22 / P24). These are the "wiring and triggers" the status doc flags as
missing from the otherwise-tested foundation.
"""
from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

from sensewright_sidecar import services
from sensewright_sidecar.agent import build_impulse_context, enforce_life_story, sleep_transition
from sensewright_sidecar.agent.social import preflight
from sensewright_sidecar.agent.speech import record_speech, resolve_limits, speech_allowed
from sensewright_sidecar.config import reset_config
from sensewright_sidecar.fallbacks import render_fallback
from sensewright_sidecar.server import app
from sensewright_sidecar.state import get_state, reset_state
from sensewright_sidecar.world.rumors import get_rumors


@pytest.fixture(autouse=True)
def reset_singletons():
    reset_state()
    reset_config()
    yield
    store = get_state().working_store()
    if store is not None:
        store.close()
    reset_state()
    reset_config()


class _FakeScheduler:
    """Captures bg submissions and returns a canned/fallback result."""

    def __init__(self, result=None):
        self.jobs = []
        self.result = result

    def submit_bg(self, purpose_id, context=None, lang="", trace_id=None, dedup_key=None, callback=None):
        self.jobs.append({"purpose": purpose_id, "context": context, "dedup": dedup_key, "callback": callback})

    def run_purpose(self, purpose_id, context=None, lang="", trace_id=None, timeout=None):
        if self.result is None:
            return types.SimpleNamespace(data=render_fallback(purpose_id, lang, context or {}))
        return types.SimpleNamespace(data=self.result)

    def purposes(self):
        return [job["purpose"] for job in self.jobs]


def _state_with_store():
    state = get_state()
    state.save_vault.session_start(1, 1000)
    state.scheduler = _FakeScheduler()
    return state


class TestSleepTransition:
    def test_first_observation_is_not_an_edge(self):
        assert sleep_transition(None, True) is None
        assert sleep_transition(None, False) is None

    def test_edges(self):
        assert sleep_transition(False, True) == "sleep_start"
        assert sleep_transition(True, False) == "wake"

    def test_no_edge_when_unchanged(self):
        assert sleep_transition(True, True) is None
        assert sleep_transition(False, False) is None


class TestSpeechPolicy:
    def test_min_interval_blocks_fast_line(self):
        assert speech_allowed([100.0], 110.0, 12, 30.0) is False

    def test_interval_allows_after_cooldown(self):
        assert speech_allowed([100.0], 140.0, 12, 30.0) is True

    def test_rate_cap_blocks_burst(self):
        history = [0.0, 10.0, 20.0, 30.0, 40.0, 50.0]
        assert speech_allowed(history, 55.0, 6, 0.0) is False

    def test_record_prunes_old_entries(self):
        assert record_speech([0.0, 100.0], 150.0) == [100.0, 150.0]

    def test_resolve_limits_defaults(self):
        assert resolve_limits(None) == (12, 30.0)


class TestLifeStoryLimits:
    def test_line_cap_keeps_tail(self):
        lines = ["line-%d" % i for i in range(30)]
        out = enforce_life_story(lines)
        assert len(out) == 20
        assert out[-1] == "line-29"

    def test_char_cap(self):
        lines = ["x" * 500 for _ in range(10)]
        out = enforce_life_story(lines)
        assert sum(len(line) for line in out) <= 2000

    def test_non_list_is_empty(self):
        assert enforce_life_story(None) == []


class TestChildHardBlock:
    @staticmethod
    def _sim(sim_id, age_stage):
        return {
            "sim_id": sim_id, "age_stage": age_stage, "species": "HUMAN",
            "room_id": 1, "pos": {"x": 0.0, "z": 0.0},
        }

    def test_flirty_blocked_for_child(self):
        result = preflight(self._sim(1, "CHILD"), self._sim(2, "ADULT"), None, category="flirty")
        assert result["category_ok"] is False
        assert result["ok"] is False

    def test_friendly_allowed_for_child(self):
        result = preflight(self._sim(1, "CHILD"), self._sim(2, "ADULT"), None, category="friendly")
        assert result["category_ok"] is True
        assert result["ok"] is True


class TestPhysicalGuard:
    def test_schedule_blocks_physical_actions(self):
        ctx = build_impulse_context(
            sim_id=1, sim_name="Bob", tier="full", mood="happy", activity="idle",
            needs={"hunger": -10}, is_off_lot_duty=False, is_sleeping=False,
            tick=100, schedule_blocks=[{"start_tick": 145}],
        )
        assert ctx["physical_actions_allowed"] is False


class TestSleepPipeline:
    def test_sleep_start_schedules_dream(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "Bob", "is_sleeping": False}})
        services._process_sleep_transitions(state, 1000, "pt-BR", None)  # learn state
        state.update_census({1: {"sim_id": 1, "name": "Bob", "is_sleeping": True}})
        services._process_sleep_transitions(state, 2000, "pt-BR", None)
        assert "sim.dream" in state.scheduler.purposes()

    def test_wake_schedules_reflect_and_sleep(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "Bob", "is_sleeping": True}})
        services._process_sleep_transitions(state, 1000, "pt-BR", None)
        state.salient_since_sleep[1] = True
        state.update_census({1: {"sim_id": 1, "name": "Bob", "is_sleeping": False}})
        services._process_sleep_transitions(state, 2000, "pt-BR", None)
        purposes = state.scheduler.purposes()
        assert "sim.sleep" in purposes
        assert "evo.reflect" in purposes
        assert state.last_reflect_tick[1] == 2000

    def test_dream_callback_stores_memory_and_chains_cognition(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "Bob"}})
        callback = services._dream_callback(state, 1, 2000, None, "pt-BR")
        callback(types.SimpleNamespace(data={
            "dream_narrative": "a strange garden",
            "archetype": "surreal",
            "dream_urge": {"goal": "explore", "weight": 0.4},
        }))
        assert "sim.cognition" in state.scheduler.purposes()
        memories = state.working_store().recent_memories(1, limit=5)
        assert any(m["type"] == "dream" for m in memories)


class TestEvolvePersistence:
    def test_handle_evolve_applies_and_persists_demeanor(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "Bob"}})
        state.working_store().upsert_sim_profile(
            1, {"name": "Bob", "core_personality": "kind", "current_demeanor": ""}, 0,
        )
        state.scheduler = _FakeScheduler(result={
            "reflection": "grew colder", "demeanor_drift": "bitter",
            "preference_change": None, "trait_proposal": None,
        })
        out = services.handle_evolve({"sim_id": 1, "lang": "pt-BR", "world_sim_tick": 2000})
        assert out["demeanor_drift"] == "bitter"
        profile = state.working_store().get_sim_profile(1)["profile"]
        assert profile["current_demeanor"] == "bitter"
        assert profile["core_personality"] == "kind"


class TestGossip:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_public_salient_event_creates_rumor_for_witnesses(self, client):
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR",
        })
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "Alice", "species": "HUMAN", "age_stage": "ADULT"}],
            "world_sim_tick": 100,
        })
        # Force deterministic fallbacks so the test never hits a provider.
        get_state().scheduler = _FakeScheduler()
        response = client.post("/v1/events", json={
            "sim_id": 1, "event_category": "death", "impact": 1.0,
            "witnesses": [2, 3], "world_sim_tick": 100, "lang": "pt-BR",
        })
        assert "world.gossip" in response.json()["triggered_jobs"]
        rumors = get_rumors(get_state().working_store(), 1)
        assert rumors
        known = rumors[-1]["known_by_sim_ids"]
        assert 1 in known and 2 in known and 3 in known
