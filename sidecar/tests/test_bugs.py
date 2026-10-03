"""Regression tests for the bugs catalogued in docs/bugs.md.

BUG-01 — ``sim.social`` pair detection.
BUG-02 — stale duplicate active arcs.
BUG-03 — armed-beat liveness/timeout.
"""
from __future__ import annotations

import types

import pytest

from sensewright_sidecar.config import Config, reset_config
from sensewright_sidecar.constants import TICKS_PER_SIM_DAY
from sensewright_sidecar.god.arcs import create_arc, load_active_arc
from sensewright_sidecar.god.orchestrator import god_tick
from sensewright_sidecar.memory.sqlite_store import SqliteStore
from sensewright_sidecar.state import get_state, reset_state


@pytest.fixture(autouse=True)
def _reset():
    reset_state()
    reset_config()
    yield
    state = get_state()
    try:
        state.save_vault.shutdown()
    except Exception:  # noqa: BLE001
        pass
    reset_state()
    reset_config()


class _FakeScheduler:
    def __init__(self, result=None):
        self.result = result or {}
        self.jobs = []

    def submit_bg(self, purpose_id, context=None, lang="", trace_id=None, dedup_key=None, callback=None):
        self.jobs.append(purpose_id)

    def submit_async(self, purpose_id, context=None, lang="", trace_id=None, dedup_key=None, callback=None):
        self.jobs.append(purpose_id)

    def run_purpose(self, purpose_id, context=None, lang="", trace_id=None, timeout=None):
        return types.SimpleNamespace(data=self.result)

    def status(self):
        return {"queue_depth": 0}


# ── BUG-01 pair detection ────────────────────────────────────────────────
class TestConversationalPair:
    def test_explicit_flag_and_target_forms_pair(self):
        from sensewright_sidecar import services

        state = get_state()
        state.update_census({
            1: {"sim_id": 1, "is_conversing": True, "social_target_sim_id": 2,
                "room_id": 5, "pos": {"x": 0.0, "z": 0.0}},
            2: {"sim_id": 2, "room_id": 5, "pos": {"x": 1.0, "z": 0.0}},
        })
        pair = services._find_conversational_pair(state, None)
        assert pair is not None
        assert {pair[0]["sim_id"], pair[1]["sim_id"]} == {1, 2}

    def test_is_conversing_honors_flag(self):
        from sensewright_sidecar import services

        assert services._is_conversing({"is_conversing": True, "activity": "idle"}) is True
        assert services._is_conversing({"activity": "MixerInteraction"}) is False

    def test_proximity_fallback_for_unresolved_social_class(self):
        from sensewright_sidecar import services

        state = get_state()
        state.update_census({
            1: {"sim_id": 1, "activity": "MixerInteraction", "room_id": 5,
                "pos": {"x": 0.0, "z": 0.0}, "species": "HUMAN", "age_stage": "ADULT"},
            2: {"sim_id": 2, "activity": "GetToKnow", "room_id": 5,
                "pos": {"x": 1.0, "z": 0.0}, "species": "HUMAN", "age_stage": "ADULT"},
        })
        pair = services._find_conversational_pair(state, None)
        assert pair is not None

    def test_idle_sims_do_not_form_pair(self):
        from sensewright_sidecar import services

        state = get_state()
        state.update_census({
            1: {"sim_id": 1, "activity": "idle", "room_id": 5, "pos": {"x": 0.0, "z": 0.0}},
            2: {"sim_id": 2, "activity": "idle", "room_id": 5, "pos": {"x": 1.0, "z": 0.0}},
        })
        assert services._find_conversational_pair(state, None) is None

    def test_puppeteer_context_from_catalyst_lease(self):
        from sensewright_sidecar import services

        state = get_state()
        state.update_census({2: {"sim_id": 2, "name": "Catalyst"}})
        state.catalyst_leases = {2: {"objective": "confront the agent"}}
        ctx = services._puppeteer_context(
            state, {"sim_id": 1, "name": "Agent"}, {"sim_id": 2, "name": "Catalyst"},
        )
        assert ctx is not None
        assert ctx["objective"] == "confront the agent"
        assert ctx["agent_name"] == "Agent"


# ── BUG-02 stale arcs ────────────────────────────────────────────────────
class TestStaleArcs:
    def test_deactivate_stale_arcs_keeps_one(self, tmp_path):
        store = SqliteStore(str(tmp_path / "w.db")); store.initialize()
        first = create_arc("same theme", [{"title": "b"}], [], 100)
        second = create_arc("same theme", [{"title": "b"}], [], 200)
        store.save_arc(first)
        store.save_arc(second)
        assert len(store.list_arcs(status="active")) == 2

        removed = store.deactivate_stale_arcs(second["id"])
        assert removed == 1
        actives = store.list_arcs(status="active")
        assert len(actives) == 1
        assert actives[0]["id"] == second["id"]

    def test_load_active_arc_self_heals(self, tmp_path):
        store = SqliteStore(str(tmp_path / "w.db")); store.initialize()
        store.save_arc(create_arc("a", [{"title": "b"}], [], 100))
        newest = create_arc("b", [{"title": "b"}], [], 300)
        store.save_arc(newest)

        kept = load_active_arc(store)
        assert kept["id"] == newest["id"]
        assert len(store.list_arcs(status="active")) == 1

    def test_session_start_cleans_duplicates(self, tmp_path, monkeypatch):
        from sensewright_sidecar import services

        state = get_state()
        store = SqliteStore(str(tmp_path / "w.db")); store.initialize()
        older = create_arc("older", [{"title": "b"}], [], 100)
        newest = create_arc("newest", [{"title": "b"}], [], 200)
        store.save_arc(older)
        store.save_arc(newest)

        monkeypatch.setattr(state, "working_store", lambda: store)
        monkeypatch.setattr(
            state.save_vault, "session_start",
            lambda save_id, tick: {"bootstrap_needed": False, "restored_tick": None, "rewound": False},
        )
        state.scheduler = _FakeScheduler()

        services.handle_session_start({"save_id": 1, "world_sim_tick": 5000, "lang": "pt-BR"})

        actives = store.list_arcs(status="active")
        assert len(actives) == 1
        assert actives[0]["id"] == newest["id"]
        assert state.active_arc["id"] == newest["id"]


# ── BUG-03 beat liveness ─────────────────────────────────────────────────
class TestBeatTimeout:
    def _state_with_arc(self, tmp_path, monkeypatch, armed_tick):
        state = get_state()
        store = SqliteStore(str(tmp_path / "w.db")); store.initialize()
        arc = create_arc("theme", [{"title": "beat1"}, {"title": "beat2"}], [], 0)
        arc["beats"][0]["armed"] = True
        arc["beats"][0]["beat_armed_tick"] = armed_tick
        store.save_arc(arc)
        state.active_arc = arc
        monkeypatch.setattr(state, "working_store", lambda: store)
        state.config = Config({"god": {"beat_timeout_sim_days": 1, "intervention_frequency": 0.0}})
        state.scheduler = _FakeScheduler()
        return state

    def test_stalled_beat_advances(self, tmp_path, monkeypatch):
        state = self._state_with_arc(tmp_path, monkeypatch, armed_tick=0)
        result = god_tick(state, 1, TICKS_PER_SIM_DAY + 10, "en-US")
        assert result["active_arc"]["current_beat_idx"] == 1
        assert state.metrics_snapshot().get("god_beat_timeouts") == 1

    def test_fresh_beat_does_not_advance(self, tmp_path, monkeypatch):
        state = self._state_with_arc(tmp_path, monkeypatch, armed_tick=0)
        result = god_tick(state, 1, 100, "en-US")
        assert result["active_arc"]["current_beat_idx"] == 0
        assert state.metrics_snapshot().get("god_beat_timeouts") is None

    def test_timeout_disabled_does_not_advance(self, tmp_path, monkeypatch):
        state = self._state_with_arc(tmp_path, monkeypatch, armed_tick=0)
        state.config = Config({"god": {"beat_timeout_sim_days": 0, "intervention_frequency": 0.0}})
        result = god_tick(state, 1, TICKS_PER_SIM_DAY * 5, "en-US")
        assert result["active_arc"]["current_beat_idx"] == 0


# ── BUG-01 follow-up: reaction intents must carry the causer's sim_id ──────
class TestReactionSimId:
    def test_reaction_speak_intent_gets_causer_sim_id(self):
        from sensewright_sidecar import services

        state = get_state()
        callback = services._reaction_callback(state, 7, "death", 1000)
        callback(types.SimpleNamespace(data={
            "intents": [{"kind": "speak", "params": {"text": "they are gone"}}],
        }))

        intents = state.drain_intents()
        assert len(intents) == 1
        assert intents[0]["kind"] == "speak"
        assert intents[0]["sim_id"] == 7

    def test_reaction_ignores_non_dict_intents(self):
        from sensewright_sidecar import services

        state = get_state()
        callback = services._reaction_callback(state, 7, "death", 1000)
        callback(types.SimpleNamespace(data={"intents": ["not-a-dict", None]}))

        assert state.drain_intents() == []
