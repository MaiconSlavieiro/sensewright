"""Tests for the Phase 2/3 infrastructure (events, spawn_npc, beat-ended, world).

Covers the sidecar side of tasks 2.1 (mem.legacy), 2.4 (spawn_npc contract),
2.9 (god.beat-ended -> god.react -> advance_arc), 3.9 (mailbox/neighborhood)
and 3.4 (diary fetch).
"""
from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

from sensewright_sidecar import services
from sensewright_sidecar.agent.intents import normalize_intent
from sensewright_sidecar.config import reset_config
from sensewright_sidecar.fallbacks import render_fallback
from sensewright_sidecar.god.arcs import ARC_DONE, create_arc
from sensewright_sidecar.god.cast import run_cast
from sensewright_sidecar.god.react import apply_react
from sensewright_sidecar.purposes import get_purpose
from sensewright_sidecar.schemas import INTENT_KINDS
from sensewright_sidecar.server import app
from sensewright_sidecar.state import get_state, reset_state
from sensewright_sidecar.world.chronicle import append_chronicle
from sensewright_sidecar.world.rumors import create_rumor, save_rumors


class _FakeScheduler:
    """Scheduler whose submit_bg runs the callback immediately (deterministic)."""

    def __init__(self):
        self.jobs = []

    def submit_bg(self, purpose_id, context=None, lang="", trace_id=None,
                  dedup_key=None, callback=None):
        self.jobs.append(purpose_id)
        if callback is not None:
            callback(types.SimpleNamespace(data=render_fallback(purpose_id, lang, context or {})))

    def run_purpose(self, purpose_id, context=None, lang="", trace_id=None, timeout=None):
        return types.SimpleNamespace(data=render_fallback(purpose_id, lang, context or {}))

    def submit_async(self, purpose_id, context=None, lang="", trace_id=None,
                     dedup_key=None, callback=None):
        self.jobs.append(purpose_id)
        if callback is not None:
            callback(self.run_purpose(purpose_id, context, lang, trace_id))

    def purposes(self):
        return list(self.jobs)


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


@pytest.fixture
def client():
    return TestClient(app)


def _state_with_store():
    state = get_state()
    state.save_vault.session_start(1, 1000)
    state.scheduler = _FakeScheduler()
    return state


class TestSpawnNpcContract:
    def test_kind_registered(self):
        assert "spawn_npc" in INTENT_KINDS

    def test_normalize_spawn_npc(self):
        intent = normalize_intent({
            "sim_id": 5, "kind": "spawn_npc",
            "params": {"role": "catalyst", "objective": "arrive"},
        })
        assert intent["kind"] == "spawn_npc"
        assert intent["params"]["role"] == "catalyst"
        assert intent["expires_on"] == "ttl"

    def test_cast_reuses_compatible_townie(self):
        state = _state_with_store()
        state.update_census({
            1: {"sim_id": 1, "name": "Player", "is_player": True, "age_stage": "ADULT"},
            2: {"sim_id": 2, "name": "Townie", "is_player": False, "age_stage": "ADULT"},
        })
        result = run_cast(state, 1, {"title": "the arrival"}, 100, "en-US", target_sim_id=1)
        assert result["spawned"] is False
        assert result["cast"][0]["sim_id"] == 2

    def test_cast_falls_back_to_spawn_intent(self):
        state = _state_with_store()
        state.update_census({
            1: {"sim_id": 1, "name": "Player", "is_player": True, "age_stage": "ADULT"},
        })
        result = run_cast(state, 1, {"title": "the arrival"}, 100, "en-US", target_sim_id=1)
        assert result["spawned"] is True
        kinds = [i["kind"] for i in result["intents"]]
        assert kinds == ["spawn_npc"]


class TestLegacyEvent:
    def test_death_creates_legacy_memory(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "Alice"}})
        result = services.handle_event({
            "sim_id": 1, "event_category": "death", "impact": 1.0,
            "world_sim_tick": 100, "lang": "en-US", "target_sim_id": 2,
        })
        assert result["ok"] is True
        assert "mem.legacy" in result["triggered_jobs"]
        memories = state.working_store().recent_memories(1, limit=10)
        assert any(m["type"] == "legacy" for m in memories)

    def test_marriage_and_birth_categories_are_legacy(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "Alice"}})
        for category in ("marriage", "birth"):
            result = services.handle_event({
                "sim_id": 1, "event_category": category, "impact": 1.0,
                "world_sim_tick": 100 + len(category), "lang": "en-US",
            })
            assert "mem.legacy" in result["triggered_jobs"]

    def test_lifestory_appended(self):
        state = _state_with_store()
        state.update_census({1: {"sim_id": 1, "name": "Alice"}})
        services.handle_event({
            "sim_id": 1, "event_category": "birth", "impact": 1.0,
            "world_sim_tick": 100, "lang": "en-US",
        })
        profile = (state.working_store().get_sim_profile(1) or {}).get("profile") or {}
        assert profile.get("life_story")


class TestBeatEnded:
    def test_apply_react_inserts_next_beat_and_advances(self):
        arc = create_arc("drama", [{"title": "b1"}, {"title": "b2"}], [], 10)
        updated = apply_react(arc, {"outcome": "accept", "pivot": "twist",
                                    "next_beat": {"title": "b1.5"}})
        assert [b["title"] for b in updated["beats"]] == ["b1", "b1.5", "b2"]
        assert updated["current_beat_idx"] == 1
        assert updated["beats"][0]["resolved"] is True

    def test_apply_react_marks_done_on_last_beat(self):
        arc = create_arc("drama", [{"title": "only"}], [], 10)
        updated = apply_react(arc, {"outcome": "reject"})
        assert updated["status"] == ARC_DONE

    def test_beat_ended_handler_advances_arc(self):
        state = _state_with_store()
        state.active_arc = create_arc("drama", [{"title": "b1"}, {"title": "b2"}], [], 10)
        state.working_store().save_arc(state.active_arc)
        result = services.handle_beat_ended({
            "save_id": 1, "world_sim_tick": 200, "decision": "accept",
            "agent_sim_id": 1, "lang": "en-US",
        })
        assert result["ok"] is True
        assert state.active_arc["current_beat_idx"] == 1

    def test_beat_ended_endpoint(self, client):
        response = client.post("/v1/god/beat-ended", json={"save_id": 1})
        assert response.status_code == 200
        assert response.json()["ok"] is False  # no active arc, but the route exists


class TestWorldAndDiary:
    def test_neighborhood_returns_chronicles_and_rumors(self):
        state = _state_with_store()
        store = state.working_store()
        append_chronicle(store, 1, "A quiet day.", 100)
        rumor = create_rumor("Something happened", ["gossip"], 1, 100)
        save_rumors(store, 1, [rumor], 100)
        result = services.handle_neighborhood({"save_id": 1, "sim_id": 1})
        assert result["ok"] is True
        assert result["chronicles"][-1]["text"] == "A quiet day."
        assert result["rumors"][0]["text"] == "Something happened"

    def test_diary_get_returns_latest_entry(self):
        state = _state_with_store()
        store = state.working_store()
        store.add_memory(1, "diary", {"text": "Dear diary, today was odd."},
                         search_text="Dear diary, today was odd.", created_sim_tick=50)
        result = services.handle_diary_get({"sim_id": 1})
        assert result["entry"] == "Dear diary, today was odd."

    def test_endpoints_exist(self, client):
        assert client.get("/v1/world/neighborhood?save_id=1").status_code == 200
        assert client.post("/v1/memory/diary", json={"sim_id": 1}).status_code == 200


class TestGodPurposeRegistry:
    def test_god_react_purpose_present(self):
        purpose = get_purpose("god.react")
        assert purpose is not None
        assert purpose.fallback_key == "god.react"
