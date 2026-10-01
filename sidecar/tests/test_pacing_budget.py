"""v0.5 R3: turn pacing + shared budget with a social reserve + backpressure."""

from __future__ import annotations

from sensewright_sidecar.agent.agency import Agency
from sensewright_sidecar.agent.conversations import ConversationManager
from sensewright_sidecar.config import LLMConfig, ProviderConfig, Settings
from sensewright_sidecar.god.budgeter import BackgroundBudgeter
from sensewright_sidecar.llm.chain import ProviderChain


def test_budget_reserve_keeps_slice_for_social():
    clock = [1000.0]
    budgeter = BackgroundBudgeter(
        per_minute=10,
        daily=0,
        reserve_fraction=0.4,
        monotonic=lambda: clock[0],
        wall_clock=lambda: clock[0],
    )
    # Idle (no reserve) may use only 60% of the window (6).
    assert all(budgeter.try_acquire() for _ in range(6))
    assert budgeter.try_acquire() is False
    # Social may spend the reserved slice.
    assert all(budgeter.try_acquire(allow_reserve=True) for _ in range(4))
    assert budgeter.try_acquire(allow_reserve=True) is False
    assert budgeter.snapshot()["reserve_fraction"] == 0.4


def test_turn_pacing_interval_and_change():
    clock = [100.0]
    manager = ConversationManager(clock=lambda: clock[0])
    manager.turn_min_interval = 25.0

    # A brand-new pair may speak.
    assert manager.should_turn(1, 2, "chat|") == (True, "new")

    class _Dlg:
        a = 1
        b = 2
        lines = ({"speaker": "a", "text": "hi", "tone": "friendly"},)
        topic = "x"

    # Record the turn; the same signature one second later is too soon.
    manager.record(_Dlg(), signature="chat|")
    clock[0] += 1.0
    allowed, reason = manager.should_turn(1, 2, "chat|")
    assert allowed is False and reason == "interval"

    # A changed interaction/queue allows an immediate turn.
    assert manager.should_turn(1, 2, "flirt|") == (True, "changed")

    # After the interval the same signature allows a turn again.
    clock[0] += 30.0
    assert manager.should_turn(1, 2, "flirt|")[0] is True


def test_pair_signature_tracks_interaction_and_queue():
    a = {"sim_id": 1, "current_interaction": "social_Chat",
         "queued_interactions": [{"name": "social_Flirt"}]}
    b = {"sim_id": 2, "current_interaction": "", "queued_interactions": []}
    sig = Agency._pair_signature(a, b)
    assert "social_Chat" in sig
    assert "social_Flirt" in sig
    # A change in the queue changes the signature (and thus allows a turn).
    b["queued_interactions"] = [{"name": "social_Hug"}]
    assert Agency._pair_signature(a, b) != sig


def test_chain_backpressure_factor():
    settings = Settings(
        llm=LLMConfig(
            chain=["openai", "openai_compat"],
            providers={
                "openai": ProviderConfig(enabled=True, api_key="k", model="m:free"),
                "openai_compat": ProviderConfig(enabled=True, api_key="k", model="m2:free"),
            },
        )
    )
    chain = ProviderChain(settings)
    assert chain.backpressure_factor() == 1.0

    # Cool one of two providers -> half pressure.
    chain._providers[0]._cold_until = float("inf")
    assert chain.backpressure_factor() == 0.5

    # Cool both -> no idle impulses.
    chain._providers[1]._cold_until = float("inf")
    assert chain.backpressure_factor() == 0.0
