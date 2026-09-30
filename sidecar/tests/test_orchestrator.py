"""Unit tests for the God orchestrator and world model (Phase 5c)."""

from __future__ import annotations

import random

from sensewright_sidecar.config import GodConfig
from sensewright_sidecar.god.interventions import Intervention
from sensewright_sidecar.god.orchestrator import MAX_DIRECTIVE_HISTORY, GodOrchestrator
from sensewright_sidecar.god.world_model import Directive, SimProfile, WorldState


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _world() -> WorldState:
    return WorldState(
        sims={
            "1": SimProfile(sim_id="1", name="Ana", is_player=True, relationships={"2": 40.0}),
            "2": SimProfile(sim_id="2", name="Beto", relationships={"1": 40.0}),
        },
        household_funds=20000,
    )


def _orchestrator(**overrides) -> GodOrchestrator:
    values = {
        "enabled": True,
        "preset": "novela",
        "intervention_frequency": 1.0,
        "intensity": 0.6,
        "autonomy_degree": 0.0,
        "chaos_degree": 0.0,
        "base_interval_seconds": 600.0,
    }
    values.update(overrides)
    return GodOrchestrator(GodConfig(**values), rng=random.Random(1), clock=FakeClock())


async def test_disabled_emits_nothing():
    orch = _orchestrator(enabled=False)
    assert await orch.maybe_intervene(_world()) == []


async def test_frequency_zero_emits_nothing():
    orch = _orchestrator(intervention_frequency=0.0)
    assert await orch.maybe_intervene(_world()) == []


async def test_first_tick_intervenes_then_respects_gap():
    clock = FakeClock()
    orch = GodOrchestrator(
        GodConfig(enabled=True, preset="novela", intervention_frequency=1.0, intensity=0.6),
        rng=random.Random(1),
        clock=clock,
    )

    first = await orch.maybe_intervene(_world())
    assert len(first) == 1
    assert first[0].narration

    # frequency 1.0 + autonomy 0.5 => gap = 600 * 0 * 0.75, floored at 30 s.
    clock.advance(10)
    assert await orch.maybe_intervene(_world()) == []

    clock.advance(40)
    assert len(await orch.maybe_intervene(_world())) == 1


async def test_power_toggle_gates_interventions():
    # Only temporary/personality traits may fire; everything else is off.
    orch = _orchestrator(
        intensity=0.8,
        powers={
            "spawn_npc": False,
            "apply_trait": True,
            "force_social": False,
            "gossip": False,
            "relationship_shift": False,
        },
    )
    directives = await orch.maybe_intervene(_world())
    assert len(directives) == 1
    assert directives[0].type == "apply_trait"


async def test_no_target_for_sim_dependent_intervention():
    orch = _orchestrator(
        intensity=0.8,
        powers={
            "spawn_npc": False,
            "apply_trait": False,
            "force_social": True,
            "gossip": False,
            "relationship_shift": False,
        },
    )
    empty = WorldState()
    assert await orch.maybe_intervene(empty) == []


async def test_apply_trait_maps_permanent_vs_temporary():
    orch = _orchestrator()
    target = SimProfile(sim_id="7")

    permanent = Intervention(
        id="p", name="P", description="d", type="apply_trait",
        payload_template={"trait": "careful", "duration": "permanent"},
    )
    tool_call = orch._map_tool_call(permanent, target, permanent.payload_template)
    assert tool_call["name"] == "add_trait"
    assert tool_call["args"]["trait_name"] == "careful"

    temporary = Intervention(
        id="t", name="T", description="d", type="apply_trait",
        payload_template={"trait": "spooked", "duration": "night"},
    )
    tool_call = orch._map_tool_call(temporary, target, temporary.payload_template)
    assert tool_call["name"] == "add_buff"
    assert tool_call["args"]["buff_name"] == "spooked"


async def test_force_social_maps_queue_interaction_with_partner():
    orch = _orchestrator()
    target = SimProfile(sim_id="2", relationships={"1": 30.0})
    intervention = Intervention(
        id="f", name="F", description="argue", type="force_social",
        payload_template={"interaction": "argue"},
    )
    tool_call = orch._map_tool_call(intervention, target, intervention.payload_template)
    assert tool_call["name"] == "queue_interaction"
    assert tool_call["args"]["sim_id"] == 2
    assert tool_call["args"]["target_sim_id"] == 1


async def test_world_event_has_no_tool_call():
    orch = _orchestrator()
    target = SimProfile(sim_id="2")
    intervention = Intervention(
        id="e", name="E", description="fire", type="extreme_event",
        payload_template={"event": "fire"},
    )
    assert orch._map_tool_call(intervention, target, intervention.payload_template) is None


def test_world_state_from_census():
    census = {
        "sims": [
            {
                "sim_id": 10,
                "full_name": "Ana",
                "traits": ["ambitious"],
                "is_player": True,
                "relationships": [{"target_id": 11, "depth": 25.5}],
            },
            {"sim_id": 11, "full_name": "Beto"},
        ],
        "households": [{"household_id": 5, "funds": 15000}, {"household_id": 6, "funds": 5000}],
    }
    state = WorldState.from_census(census, time_of_day="evening", lot_type="residential")
    assert set(state.sims) == {"10", "11"}
    assert state.sims["10"].relationships == {"11": 25.5}
    assert state.sims["10"].is_player is True
    assert state.household_funds == 20000
    assert state.time_of_day == "evening"
    # Unplayed candidates are preferred (the player is excluded).
    assert [sim.sim_id for sim in state.candidates()] == ["11"]


async def test_llm_narration_overrides_description():
    class _Response:
        text = "A sudden storm of gossip sweeps the block."

    class _Registry:
        async def complete(self, messages, **kwargs):
            return _Response()

    orch = _orchestrator()
    orch.set_registry(_Registry())
    directives = await orch.maybe_intervene(_world())
    assert directives[0].narration == _Response.text


async def test_llm_narration_failure_keeps_description():
    class _Registry:
        async def complete(self, messages, **kwargs):
            raise RuntimeError("boom")

    orch = _orchestrator()
    orch.set_registry(_Registry())
    directives = await orch.maybe_intervene(_world())
    assert directives[0].narration


def test_chaos_degree_boosts_chaotic_types():
    orch = _orchestrator()
    intervention = Intervention(
        id="c", name="C", description="d", type="extreme_event", weight=1.0,
    )
    orch.chaos_degree = 0.1
    base = orch._weight(intervention)
    orch.chaos_degree = 0.9
    boosted = orch._weight(intervention)
    assert boosted > base


def test_status_reports_dials():
    orch = _orchestrator()
    status = orch.status()
    assert status["enabled"] is True
    assert status["preset"] == "novela"
    assert "powers" in status


async def test_issued_directive_is_not_pending():
    orch = _orchestrator()
    directives = await orch.maybe_intervene(_world())
    assert len(directives) == 1
    assert directives[0].status == "issued"
    assert orch.get_pending_directives() == []


async def test_status_reports_issued_and_history_size():
    orch = _orchestrator()
    await orch.maybe_intervene(_world())
    status = orch.status()
    assert status["issued_directives"] >= 1
    assert status["history_size"] == len(orch._directives)


async def test_directive_history_is_bounded():
    clock = FakeClock()
    orch = GodOrchestrator(
        GodConfig(
            enabled=True,
            preset="novela",
            intervention_frequency=1.0,
            intensity=0.6,
            base_interval_seconds=1.0,
        ),
        rng=random.Random(1),
        clock=clock,
    )
    for _ in range(MAX_DIRECTIVE_HISTORY + 25):
        await orch.maybe_intervene(_world())
        clock.advance(60)
    assert len(orch._directives) <= MAX_DIRECTIVE_HISTORY


async def test_drain_directives_marks_pending_done():
    orch = _orchestrator()
    pending = Directive(id="manual-1", type="extreme_event")
    orch.add_directive(pending)

    drained = orch.drain_directives()
    assert drained == [pending]
    assert pending.status == "done"
    assert orch.drain_directives() == []
