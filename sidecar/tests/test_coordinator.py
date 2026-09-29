"""Tests for the single-writer coordinator (§14.5)."""

from __future__ import annotations

from sims_sense_sidecar.agent.coordinator import (
    REASON_AGENT_OWNS_PLAYED,
    REASON_GOD_NEVER_CONTROLS_PLAYED,
    Coordinator,
)


def test_god_directive_on_played_sim_is_denied_agent_wins():
    coordinator = Coordinator()

    decision = coordinator.arbitrate(is_played=True, source="god", tool_name="set_mood")

    assert decision["allowed"] is False
    assert decision["winner"] == "agent"
    assert decision["reason"] == REASON_GOD_NEVER_CONTROLS_PLAYED


def test_god_directive_on_played_sim_without_tool_is_agent_owned():
    coordinator = Coordinator()

    decision = coordinator.arbitrate(is_played=True, source="god")

    assert decision["allowed"] is False
    assert decision["winner"] == "agent"
    assert decision["reason"] == REASON_AGENT_OWNS_PLAYED


def test_god_directive_on_unplayed_sim_is_allowed():
    coordinator = Coordinator()

    decision = coordinator.arbitrate(is_played=False, source="god", tool_name="add_trait")

    assert decision["allowed"] is True
    assert decision["winner"] == "god"
    assert decision["reason"] == "allowed"


def test_agent_directive_is_always_allowed():
    coordinator = Coordinator()

    played = coordinator.arbitrate(is_played=True, source="agent", tool_name="say_to")
    unplayed = coordinator.arbitrate(is_played=False, source="agent")

    assert played["allowed"] is True
    assert played["winner"] == "agent"
    assert unplayed["allowed"] is True
    assert unplayed["winner"] == "agent"


def test_snapshot_counts_decisions():
    coordinator = Coordinator()
    coordinator.arbitrate(is_played=True, source="god", tool_name="set_mood")
    coordinator.arbitrate(is_played=False, source="god")
    coordinator.arbitrate(is_played=True, source="agent")

    snap = coordinator.snapshot()

    assert snap["decisions"] == 3
    assert snap["denied"] == 1
    assert snap["allowed"] == 2
    assert snap["by_source"]["god"] == 2
    assert snap["last"]["winner"] == "agent"
