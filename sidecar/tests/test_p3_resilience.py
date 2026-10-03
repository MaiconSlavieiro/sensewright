"""Tests for the P3 resilience/config hardening (LLM cooldown, budget, compact)."""
from __future__ import annotations

import types

import pytest
from fastapi.testclient import TestClient

from sensewright_sidecar import services
from sensewright_sidecar.config import Config, reset_config
from sensewright_sidecar.fallbacks import render_fallback
from sensewright_sidecar.llm.budgeter import GameBudgeter
from sensewright_sidecar.llm.chain import ProviderChain
from sensewright_sidecar.memory.sqlite_store import SqliteStore
from sensewright_sidecar.server import app
from sensewright_sidecar.state import get_state, reset_state


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


def _config(models):
    return Config({
        "llm": {
            "free_only": False,
            "providers": {"fake": {"enabled": True, "models": list(models),
                                   "rpm": 0, "rpd": 0, "tpm": 0}},
            "routes": {"default": {"provider": "fake", "model": models[0]}},
            "tiers": {},
        }
    })


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


class TestModelCooldown:
    def test_two_failures_cool_the_model(self):
        chain = ProviderChain(_config(["m1"]))
        assert chain._model_cooling("fake", "m1") is False
        chain._record_failure("fake", "m1")
        chain._record_failure("fake", "m1")
        assert chain._model_cooling("fake", "m1") is True

    def test_success_clears_model_cooldown(self):
        chain = ProviderChain(_config(["m1"]))
        chain._record_failure("fake", "m1")
        chain._record_success("fake", "m1")
        assert chain._model_cooling("fake", "m1") is False


class TestGameBudget:
    def test_refund_never_goes_negative(self):
        budgeter = GameBudgeter()
        budgeter.spend(1, 100)
        budgeter.refund(1, 500)
        assert budgeter.spent(1) == 0

    def test_spend_accumulates(self):
        budgeter = GameBudgeter()
        budgeter.spend(1, 100)
        budgeter.spend(1, 50)
        assert budgeter.spent(1) == 150


class TestCompaction:
    def test_consolidated_ids_are_fifo(self, tmp_path):
        store = SqliteStore(str(tmp_path / "t.db"))
        store.initialize()
        ids = [
            store.add_memory(1, "consolidated", {"text": str(i)}, search_text=str(i),
                             created_sim_tick=i, consolidated=True)
            for i in range(25)
        ]
        assert store.consolidated_memory_ids(1, 15) == ids[:15]
        store.close()

    def test_maybe_compact_archives_and_vacuums(self):
        state = get_state()
        state.save_vault.session_start(1, 1000)
        state.scheduler = _FakeScheduler(result={"compact": "a summary of old days"})
        store = state.working_store()
        for i in range(20):
            store.add_memory(1, "consolidated", {"text": str(i)}, search_text=str(i),
                             created_sim_tick=i, consolidated=True)
        assert services._maybe_compact(state, 1, 2000, "pt-BR") is True
        assert store.count_consolidated(1) == 5
        types_found = [m["type"] for m in store.recent_memories(1, limit=10)]
        assert "compact" in types_found

    def test_maybe_compact_is_noop_below_threshold(self):
        state = get_state()
        state.save_vault.session_start(1, 1000)
        state.scheduler = _FakeScheduler(result={"compact": "x"})
        store = state.working_store()
        for i in range(5):
            store.add_memory(1, "consolidated", {"text": str(i)}, search_text=str(i),
                             created_sim_tick=i, consolidated=True)
        assert services._maybe_compact(state, 1, 2000, "pt-BR") is False


class TestInstalledPacks:
    def test_census_stores_and_status_exposes_packs(self):
        client = TestClient(app)
        client.post("/v1/lifecycle/session-start", json={
            "save_id": 1, "world_sim_tick": 100, "lang": "pt-BR",
        })
        client.post("/v1/census", json={
            "sims": [{"sim_id": 1, "name": "A"}],
            "installed_packs": ["EP01", "GP05"],
            "world_sim_tick": 100,
        })
        status = client.get("/v1/status").json()
        assert status["installed_packs"] == ["EP01", "GP05"]
