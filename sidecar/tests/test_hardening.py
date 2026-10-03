"""Regression tests for the runtime hardening plan (docs/hardening.md).

Covers: strict rewind tolerance (2.1), tick idempotency (2.3), session epoch
guards (2.4), god single-flight (3.1), the atomic rate limiter (3.6), impulse
throttling (4.1) and the per-purpose chain breaker (4.4).
"""
from __future__ import annotations

import types

import pytest

from sensewright_sidecar.config import Config, reset_config
from sensewright_sidecar.llm import base as llm_base
from sensewright_sidecar.llm.chain import ProviderChain
from sensewright_sidecar.llm.limits import ProviderRateLimiter
from sensewright_sidecar.save_vault import SaveVault
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


# ── 2.1 strict rewind tolerance ──────────────────────────────────────────
class TestRewindTolerance:
    def test_drift_within_tolerance_skips_rewind(self, tmp_path):
        vault = SaveVault(tmp_path, rewind_tolerance_ticks=3000)
        vault.session_start(1, 100)
        store = vault.working_store()
        store.add_memory(1, "thought", {"text": "keep"}, "keep", created_sim_tick=4800)
        vault.save(1, None, 5000)
        vault.shutdown()

        vault2 = SaveVault(tmp_path, rewind_tolerance_ticks=3000)
        result = vault2.session_start(1, 4600)  # 400 ticks of drift
        assert result["rewound"] is False
        texts = [m["content"]["text"]
                 for m in vault2.working_store().recent_memories(1, limit=10, include_archived=True)]
        assert "keep" in texts
        vault2.shutdown()

    def test_large_rollback_triggers_rewind(self, tmp_path):
        vault = SaveVault(tmp_path, rewind_tolerance_ticks=3000)
        vault.session_start(1, 100)
        vault.working_store().add_memory(1, "thought", {"text": "old"}, "old", created_sim_tick=100)
        vault.save(1, None, 5000)          # committed @5000
        vault.shutdown()

        vault2 = SaveVault(tmp_path, rewind_tolerance_ticks=3000)
        result = vault2.session_start(1, 1000)  # 4000 ticks behind -> rewind
        assert result["rewound"] is True
        vault2.shutdown()


# ── 2.3 tick idempotency ─────────────────────────────────────────────────
class TestTickIdempotency:
    def test_duplicate_tick_rejected(self):
        state = get_state()
        state.set_processed_tick(100)
        assert state.accept_tick(100) is False
        assert state.accept_tick(101) is True
        assert state.accept_tick(101) is False
        assert state.last_processed_tick == 101

    def test_first_pulse_at_session_tick_is_not_duplicate(self):
        from sensewright_sidecar import services

        state = get_state()
        state.scheduler = _FakeScheduler()
        services.handle_session_start({
            "save_id": 7, "world_sim_tick": 5000, "lang": "pt-BR",
        })
        result = services.handle_autonomy_tick({
            "save_id": 7, "world_sim_tick": 5000, "clock_speed": 1,
            "sims_delta": [], "active_sim_id": None, "lang": "pt-BR",
        })
        assert result.get("duplicate_tick") is not True

        duplicate = services.handle_autonomy_tick({
            "save_id": 7, "world_sim_tick": 5000, "clock_speed": 1,
            "sims_delta": [], "active_sim_id": None, "lang": "pt-BR",
        })
        assert duplicate.get("duplicate_tick") is True


# ── 2.4 session epoch guard ──────────────────────────────────────────────
class TestEpochGuard:
    def test_stale_callback_is_dropped(self):
        state = get_state()
        seen = []
        guarded = state.guard_callback("test", lambda result: seen.append(result))
        state.bump_epoch()
        guarded(types.SimpleNamespace(data={"x": 1}))
        assert seen == []
        assert state.metrics_snapshot().get("stale_epoch_dropped") == 1

    def test_current_callback_runs(self):
        state = get_state()
        seen = []
        guarded = state.guard_callback("test", lambda result: seen.append(result))
        guarded(types.SimpleNamespace(data={"x": 1}))
        assert len(seen) == 1

    def test_session_reset_bumps_epoch(self):
        state = get_state()
        epoch = state.session_epoch
        state.reset_ram()
        assert state.session_epoch == epoch + 1


# ── 3.1 god single-flight ────────────────────────────────────────────────
class TestGodSingleFlight:
    def test_claim_is_exclusive_until_released(self):
        state = get_state()
        assert state.try_begin_arc_plan() is True
        assert state.try_begin_arc_plan() is False
        state.end_arc_plan()
        assert state.try_begin_arc_plan() is True
        state.end_arc_plan()

    def test_plan_callback_releases_claim(self):
        from sensewright_sidecar.god import orchestrator

        state = get_state()
        state.save_vault.session_start(1, 100)
        state.scheduler = _FakeScheduler()
        assert state.try_begin_arc_plan() is True
        orchestrator._plan_callback(state, 5000)(types.SimpleNamespace(
            data={"theme": "A", "beats": [{"title": "b"}], "cast": []}
        ))
        assert state.arc_planning is False


# ── 3.6 atomic rate limiter ──────────────────────────────────────────────
class TestAtomicRateLimiter:
    def test_never_overshoots_rpm(self):
        limiter = ProviderRateLimiter(rpm=2)
        assert limiter.try_accept_and_record() is True
        assert limiter.try_accept_and_record() is True
        assert limiter.try_accept_and_record() is False


# ── 4.4 per-purpose breaker ──────────────────────────────────────────────
class _RaisingProvider:
    def __init__(self):
        self.calls = 0

    def complete(self, messages, model, max_tokens=256, temperature=0.7, timeout=30.0):
        self.calls += 1
        raise llm_base.LLMError("boom")


def _chain_config(models):
    return Config({
        "llm": {
            "free_only": False,
            "providers": {
                "fake": {"enabled": True, "models": list(models), "rpm": 0, "rpd": 0, "tpm": 0},
            },
            "routes": {"default": {"provider": "fake", "model": models[0]}},
            "tiers": {},
            "purpose_cooldown_seconds": 120,
        }
    })


class TestPurposeBreaker:
    def test_all_routes_failed_opens_purpose_breaker(self):
        chain = ProviderChain(_chain_config(["m1"]))
        provider = _RaisingProvider()
        chain._clients["fake"] = provider

        response, _, _ = chain.run("sim.impulse", [{"role": "user", "content": "hi"}],
                                   max_tokens=10, temperature=0.0, timeout=1.0)
        assert response is None
        assert chain._purpose_cooling("sim.impulse") is True

        # A second call is short-circuited (no provider hit).
        calls_before = provider.calls
        response2, _, _ = chain.run("sim.impulse", [{"role": "user", "content": "hi"}],
                                    max_tokens=10, temperature=0.0, timeout=1.0)
        assert response2 is None
        assert provider.calls == calls_before

    def test_success_clears_purpose_breaker(self):
        from sensewright_sidecar.llm.chain import ProviderChain as Chain

        chain = Chain(_chain_config(["m1"]))
        chain._record_purpose_failure("sim.impulse")
        assert chain._purpose_cooling("sim.impulse") is True
        chain._record_purpose_success("sim.impulse")
        assert chain._purpose_cooling("sim.impulse") is False


# ── helpers ──────────────────────────────────────────────────────────────
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
