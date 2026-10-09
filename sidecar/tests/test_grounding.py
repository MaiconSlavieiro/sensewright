"""Tests for the Dev Mode LLM grounding/merge contract (R-0..R-7).

Covers the sidecar half of ``docs/dev-mode-coauthor.md``:
- S1: rich ``sim.profile`` context (native truth + director theme + history).
- S3: neighborhood zeitgeist regeneration merges arc theme + chronicles + rumors.
- S4: 0-key fallbacks stay truthful (never invent/erase ground truth).
- S5: consolidated God dump endpoint contract.
"""
from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

from sensewright_sidecar import services
from sensewright_sidecar.config import get_config, reset_config
from sensewright_sidecar.fallbacks import render_fallback
from sensewright_sidecar.god.arcs import create_arc
from sensewright_sidecar.god.zeitgeist import run_zeitgeist
from sensewright_sidecar.i18n_engine import get_engine, reset_engine
from sensewright_sidecar.llm.context import ContextAssembler
from sensewright_sidecar.server import app
from sensewright_sidecar.state import get_state, reset_state


class _RecordingScheduler:
    """Records the context each purpose receives and returns a canned result."""

    def __init__(self, result=None):
        self.result = result or {
            "core_personality": "pirate", "current_demeanor": "restless",
            "speech_style": "salty", "backstory": "took to the sea",
        }
        self.contexts = {}
        self.jobs = []

    def run_purpose(self, purpose_id, context=None, lang="", trace_id=None, timeout=None):
        self.contexts[purpose_id] = context
        return types.SimpleNamespace(data=dict(self.result))

    def submit_bg(self, purpose_id, context=None, lang="", trace_id=None, dedup_key=None, callback=None):
        self.contexts[purpose_id] = context
        self.jobs.append(purpose_id)
        if callback is not None:
            callback(types.SimpleNamespace(data=dict(self.result)))

    def submit_async(self, purpose_id, context=None, lang="", trace_id=None, dedup_key=None, callback=None):
        self.submit_bg(purpose_id, context, lang, trace_id, dedup_key, callback)

    def status(self):
        return {"queue_depth": 0}


@pytest.fixture(autouse=True)
def reset_singletons():
    reset_state()
    reset_config()
    reset_engine()
    yield
    store = get_state().working_store()
    if store is not None:
        store.close()
    reset_state()
    reset_config()
    reset_engine()


def _state_with_store(scheduler=None):
    state = get_state()
    state.save_vault.session_start(1, 1000)
    state.scheduler = scheduler or _RecordingScheduler()
    return state


def _seed_sim(state, store, sim_id=1):
    state.update_census({sim_id: {
        "sim_id": sim_id, "name": "Alice", "species": "HUMAN",
        "age_stage": "YOUNGADULT", "gender": "F",
        "traits": ["Creative", "Bookworm"],
        "likes": ["Writing"], "dislikes": ["Fitness"],
    }})
    store.upsert_sim_profile(sim_id, {
        "name": "Alice", "core_personality": "guarded", "speech_style": "dry",
        "life_story": ["Born in Willow Creek", "Moved for a fresh start"],
        "traits": ["Creative", "Bookworm"],
    }, 1000)
    store.add_memory(sim_id, "legacy", {"text": "A defining loss"},
                     search_text="A defining loss", created_sim_tick=900)
    store.add_memory(sim_id, "thought", {"text": "A recent mood"},
                     search_text="A recent mood", created_sim_tick=1000)


class TestProfileGroundingContext:
    def test_includes_native_truth_history_and_director_theme(self):
        state = _state_with_store()
        store = state.working_store()
        _seed_sim(state, store)
        state.active_arc = create_arc(
            "A looming rivalry",
            [{"title": "First contact", "god_whisper_hint": "trust no one"}],
            [], 1000,
        )

        ctx = services._profile_grounding_context(state, 1, 1000)

        assert ctx["traits"] == ["Creative", "Bookworm"]
        assert ctx["age_stage"] == "YOUNGADULT"
        assert ctx["profile"]["core_personality"] == "guarded"
        assert ctx["profile"]["life_story"] == ["Born in Willow Creek", "Moved for a fresh start"]
        assert ctx["memories"], "memory bundle must be present"
        assert ctx["legacy_memories"], "legacy memories must be surfaced"
        assert ctx["legacy_memories"][0]["content"]["text"] == "A defining loss"
        assert "family" in ctx and isinstance(ctx["family"], list)
        assert isinstance(ctx["zeitgeist"], dict)
        assert ctx["theme"] == "A looming rivalry"
        assert ctx["god_whisper_hint"] == "trust no one"

    def test_coauthor_text_is_threaded(self):
        state = _state_with_store()
        _seed_sim(state, state.working_store())
        ctx = services._profile_grounding_context(state, 1, 1000, coauthor_text="make her a pirate")
        assert ctx["coauthor_text"] == "make her a pirate"
        assert ctx["coauthor_block"] == "make her a pirate"


class TestBuildPayload:
    def test_profile_payload_carries_truth_theme_and_zeitgeist(self):
        state = _state_with_store()
        store = state.working_store()
        _seed_sim(state, store)
        state.active_arc = create_arc("A looming rivalry", [], [], 1000)
        ctx = services._profile_grounding_context(state, 1, 1000, coauthor_text="pirate")

        assembler = ContextAssembler(get_config())
        payload = assembler._build_payload("sim.profile", ctx, "bg")

        assert payload["profile"]["traits"] == ["Creative", "Bookworm"]
        assert payload["profile"]["age_stage"] == "YOUNGADULT"
        assert payload["profile"]["likes"] == ["Writing"]
        assert payload["theme"] == "A looming rivalry"
        assert payload["zeitgeist"] == ctx["zeitgeist"]
        assert payload["coauthor_block"] == "pirate"
        assert payload["relationships"] == []


class TestRenderPromptCoauthor:
    def test_system_template_expands_coauthor_block(self):
        engine = get_engine()
        text = engine.render_prompt(
            "sim.profile", "system", "en-US",
            {"coauthor_block": "PLAYER DIRECTS: make her a pirate"},
        )
        assert "PLAYER DIRECTS: make her a pirate" in text
        assert "MERGE" in text

    def test_missing_coauthor_block_does_not_break(self):
        engine = get_engine()
        text = engine.render_prompt("sim.profile", "system", "en-US", {})
        assert "{coauthor_block}" not in text


class TestHandleProfileCoauthor:
    def test_coauthor_merges_and_preserves_ground_truth(self):
        state = _state_with_store(_RecordingScheduler())
        store = state.working_store()
        _seed_sim(state, store)

        result = services.handle_profile({
            "sim_id": 1, "coauthor_text": "make her a pirate",
            "world_sim_tick": 1000, "lang": "en-US",
        })

        profile = result["profile"]
        assert profile["core_personality"] == "pirate"
        # R-2: native facts survive the LLM output.
        assert profile["traits"] == ["Creative", "Bookworm"]
        assert profile["age_stage"] == "YOUNGADULT"
        # R-3: history survives.
        assert profile["life_story"] == ["Born in Willow Creek", "Moved for a fresh start"]
        # R-1: the handler sent the grounded context with the player's direction.
        sent = state.scheduler.contexts["sim.profile"]
        assert sent["coauthor_block"] == "make her a pirate"
        assert sent["traits"] == ["Creative", "Bookworm"]
        saved = store.get_sim_profile(1)["profile"]
        assert saved["core_personality"] == "pirate"

    def test_pure_regeneration_is_grounded_in_theme(self):
        state = _state_with_store(_RecordingScheduler())
        store = state.working_store()
        _seed_sim(state, store)
        state.active_arc = create_arc("A looming rivalry", [{"god_whisper_hint": "trust no one"}], [], 1000)

        services.handle_profile({"sim_id": 1, "force_interactive": True,
                                 "world_sim_tick": 1000, "lang": "en-US"})

        sent = state.scheduler.contexts["sim.profile"]
        assert sent["theme"] == "A looming rivalry"
        assert sent["legacy_memories"]


class TestZeitgeistGrounding:
    def test_regeneration_receives_theme_chronicles_and_rumors(self):
        state = _state_with_store(_RecordingScheduler(
            {"tags": ["tense"], "preset": "drama", "weather_preference": "rain"}))
        store = state.working_store()
        store.set_neighborhood(
            1,
            chronicles=[{"text": "The mayor resigned", "tick": 900}],
            rumors=[{"id": "r1", "text": "A secret affair", "known_by_sim_ids": [1]}],
            tick=900,
        )
        state.active_arc = create_arc("A looming rivalry", [], [], 1000)

        result = run_zeitgeist(state, 1, "", "en-US")

        sent = state.scheduler.contexts["god.zeitgeist"]
        assert sent["theme"] == "A looming rivalry"
        assert sent["chronicles"][0]["text"] == "The mayor resigned"
        assert sent["rumors"][0]["text"] == "A secret affair"
        assert result["tags"] == ["tense"]


class TestTruthfulFallbacks:
    def test_profile_fallback_preserves_persona_and_coauthor(self):
        fallback = render_fallback("sim.profile", "en-US", {
            "profile": {"core_personality": "guarded", "backstory": "quiet life"},
            "coauthor_text": "wants to sail",
            "traits": ["Creative"], "age_stage": "ADULT",
        })
        assert fallback["core_personality"] == "guarded"
        assert "wants to sail" in fallback["backstory"]
        assert fallback["traits"] == ["Creative"]
        assert fallback["age_stage"] == "ADULT"

    def test_zeitgeist_fallback_preserves_existing(self):
        fallback = render_fallback("god.zeitgeist", "en-US", {
            "zeitgeist": {"tags": ["tense"], "preset": "terror", "weather_preference": "rain"},
        })
        assert fallback == {"tags": ["tense"], "preset": "terror", "weather_preference": "rain"}


class TestGodDump:
    def test_dump_contract(self):
        state = _state_with_store()
        store = state.working_store()
        store.set_neighborhood(
            1,
            zeitgeist={"tags": ["tense"], "preset": "drama", "weather_preference": "rain"},
            chronicles=[{"text": "The mayor resigned", "tick": 900}],
            rumors=[{"id": "r1", "text": "A secret affair"}],
            tick=900,
        )
        state.active_arc = create_arc("A looming rivalry", [], [{"sim_id": 7, "name": "Bob"}], 1000)

        dump = services.handle_god_dump({"save_id": 1})

        assert dump["ok"] is True
        assert dump["zeitgeist"]["tags"] == ["tense"]
        assert dump["arc"]["theme"] == "A looming rivalry"
        assert dump["cast"][0]["name"] == "Bob"
        assert dump["chronicles"][0]["text"] == "The mayor resigned"
        assert dump["rumors"][0]["text"] == "A secret affair"


class TestDevRoutes:
    def test_god_dump_route(self):
        state = _state_with_store()
        store = state.working_store()
        store.set_neighborhood(
            1, zeitgeist={"tags": ["tense"]},
            chronicles=[{"text": "The mayor resigned", "tick": 900}], tick=900,
        )
        client = TestClient(app)
        response = client.get("/v1/god/dump?save_id=1")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["zeitgeist"]["tags"] == ["tense"]
        assert body["chronicles"][0]["text"] == "The mayor resigned"

    def test_profile_coauthor_route(self):
        state = _state_with_store(_RecordingScheduler())
        _seed_sim(state, state.working_store())
        client = TestClient(app)
        response = client.post("/v1/profile", json={
            "sim_id": 1, "coauthor_text": "make her a pirate",
            "world_sim_tick": 1000, "lang": "en-US",
        })
        assert response.status_code == 200
        profile = response.json()["profile"]
        assert profile["core_personality"] == "pirate"
        assert profile["traits"] == ["Creative", "Bookworm"]
