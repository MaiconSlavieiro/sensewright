"""Tests for the P1 God Director + World Layer wiring (arcs, chronicle, diary)."""
from __future__ import annotations

import types

import pytest

from sensewright_sidecar import services
from sensewright_sidecar.config import reset_config
from sensewright_sidecar.constants import TICKS_PER_SIM_DAY
from sensewright_sidecar.fallbacks import render_fallback
from sensewright_sidecar.god import orchestrator
from sensewright_sidecar.state import get_state, reset_state
from sensewright_sidecar.world.chronicle import get_chronicles


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
    def __init__(self, result=None):
        self.result = result
        self.jobs = []

    def submit_bg(self, purpose_id, context=None, lang="", trace_id=None, dedup_key=None, callback=None):
        self.jobs.append(purpose_id)

    def run_purpose(self, purpose_id, context=None, lang="", trace_id=None, timeout=None):
        if self.result is None:
            return types.SimpleNamespace(data=render_fallback(purpose_id, lang, context or {}))
        return types.SimpleNamespace(data=self.result)

    def submit_async(self, purpose_id, context=None, lang="", trace_id=None, dedup_key=None, callback=None):
        self.jobs.append(purpose_id)
        if callback is not None:
            callback(self.run_purpose(purpose_id, context, lang, trace_id))

    def purposes(self):
        return list(self.jobs)


def _state_with_store():
    state = get_state()
    state.save_vault.session_start(1, 1000)
    state.scheduler = _FakeScheduler()
    return state


class TestGodPlan:
    def test_plan_callback_builds_and_persists_arc(self):
        state = _state_with_store()
        orchestrator._plan_callback(state, 5000)(types.SimpleNamespace(data={
            "theme": "drama",
            "beats": [{"title": "the arrival"}],
            "cast": [],
        }))
        assert state.active_arc is not None
        arcs = state.working_store().list_arcs(status="active")
        assert arcs and arcs[0]["theme"] == "drama"
        assert arcs[0]["beats"][0]["title"] == "the arrival"

    def test_plan_callback_ignores_empty_beats(self):
        state = _state_with_store()
        orchestrator._plan_callback(state, 5000)(types.SimpleNamespace(data={"beats": []}))
        assert state.active_arc is None

    def test_scene_callback_folds_draft_into_beat(self):
        state = _state_with_store()
        orchestrator._plan_callback(state, 5000)(types.SimpleNamespace(data={
            "theme": "drama", "beats": [{"title": "b1"}], "cast": [],
        }))
        arc = state.active_arc
        orchestrator._scene_callback(state, arc, 0)(types.SimpleNamespace(data={
            "scene_draft": "a tense dinner", "scene_subtext": "someone is lying",
        }))
        beat = arc["beats"][0]
        assert beat["scene_draft"] == "a tense dinner"
        assert beat["scene_subtext"] == "someone is lying"


class TestEndOfDay:
    def test_schedules_chronicle_and_diary_on_day_change(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "Alice"}})
        state.last_day_tick = 1
        scheduled = services._maybe_end_of_day(
            state, 1, TICKS_PER_SIM_DAY * 2, "pt-BR", None, 1,
        )
        purposes = state.scheduler.purposes()
        assert scheduled == 2
        assert "world.household.chronicle" in purposes
        assert "sim.diary" in purposes

    def test_noop_within_same_day(self):
        state = _state_with_store()
        state.last_day_tick = 5
        assert services._maybe_end_of_day(state, 1, TICKS_PER_SIM_DAY * 5 + 10, "pt-BR", None) == 0

    def test_chronicle_callback_persists(self):
        state = _state_with_store()
        services._chronicle_callback(state, 1, 3000)(types.SimpleNamespace(data={
            "chronicle": "Day one was quiet.",
        }))
        chronicles = get_chronicles(state.working_store(), 1)
        assert chronicles and chronicles[-1]["text"] == "Day one was quiet."

    def test_diary_callback_persists_memory(self):
        state = _state_with_store()
        services._diary_callback(state, 1, 3000)(types.SimpleNamespace(data={
            "entry": "Dear diary, today I met someone.",
        }))
        memories = state.working_store().recent_memories(1, limit=5)
        assert any(m["type"] == "diary" for m in memories)
