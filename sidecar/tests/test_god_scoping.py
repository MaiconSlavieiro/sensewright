"""Unit tests for God scoping (v0.2 G1): aggregates and played-Sim jurisdiction."""

from __future__ import annotations

import random

import pytest

from sensewright_sidecar.config import GodConfig
from sensewright_sidecar.god.orchestrator import GodOrchestrator
from sensewright_sidecar.god.world_model import SimProfile, WorldState, aggregates


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _orchestrator(**overrides) -> GodOrchestrator:
    values = {
        "enabled": True,
        "preset": "novela",
        "intervention_frequency": 1.0,
        "intensity": 0.8,
        "autonomy_degree": 0.0,
        "chaos_degree": 0.0,
        "base_interval_seconds": 600.0,
    }
    values.update(overrides)
    return GodOrchestrator(GodConfig(**values), rng=random.Random(1), clock=FakeClock())


# ─── aggregates() ─────────────────────────────────────────────────────


def _census() -> dict:
    return {
        "sims": [
            {
                "sim_id": 1,
                "full_name": "Ana",
                "household_id": 5,
                "is_player": True,
                "mood": "Angry",
                "relationships": [{"target_id": 2, "depth": -80.0}],
            },
            {
                "sim_id": 2,
                "full_name": "Beto",
                "household_id": 5,
                "mood": "happy",
                "relationships": [{"target_id": 1, "depth": -20.0}],
            },
            {
                "sim_id": 3,
                "full_name": "Caio",
                "household_id": 6,
                "mood": "happy",
                "relationships": [],
            },
        ],
        "households": [
            {"household_id": 5, "name": "Silva", "members": [1, 2], "funds": 15000},
            {"household_id": 6, "name": "Souza", "members": [3], "funds": 5000},
        ],
    }


def test_aggregates_representative_census():
    result = aggregates(_census())

    assert result["population"] == 3
    assert result["household_count"] == 2
    assert result["households"] == {"Silva": 2, "Souza": 1}
    assert result["mood_distribution"] == {"angry": 1, "happy": 2}
    assert result["mood"] == "happy"
    # 0.5 * avg(0.8, 0.2) + 0.5 * (1/3 negative moods) == 0.4167
    assert result["tension"] == pytest.approx(0.4167, abs=1e-4)
    assert result["funds"] == 20000


def test_aggregates_none_and_malformed_are_zeroed():
    expected = {
        "population": 0,
        "household_count": 0,
        "households": {},
        "mood_distribution": {},
        "mood": "neutral",
        "tension": 0.0,
        "funds": 0,
    }
    assert aggregates(None) == expected
    assert aggregates([]) == expected  # type: ignore[arg-type]
    assert aggregates({"sims": "nope", "households": None}) == expected
    assert aggregates({"sims": [None, 3], "households": [{"funds": "bad"}]})["population"] == 0


def test_aggregates_household_key_falls_back_to_id():
    census = {"sims": [], "households": [{"household_id": 9, "members": [1, 2]}]}
    result = aggregates(census)
    assert result["households"] == {"9": 2}
    assert result["household_count"] == 1


def test_world_state_played_ids():
    state = WorldState(
        sims={
            "1": SimProfile(sim_id="1", is_player=True),
            "2": SimProfile(sim_id="2"),
            "3": SimProfile(sim_id="3", is_player=True),
        }
    )
    assert state.played_ids() == {"1", "3"}


# ─── orchestrator jurisdiction ────────────────────────────────────────


def _played_world() -> WorldState:
    return WorldState(
        sims={
            "1": SimProfile(sim_id="1", is_player=True),
            "2": SimProfile(sim_id="2", is_player=True),
        }
    )


def _mixed_world() -> WorldState:
    return WorldState(
        sims={
            "1": SimProfile(sim_id="1", is_player=True, relationships={"2": 30.0}),
            "2": SimProfile(sim_id="2", relationships={"1": 30.0}),
            "3": SimProfile(sim_id="3", is_player=True),
            "4": SimProfile(sim_id="4", relationships={"3": -40.0}),
        }
    )


async def test_only_played_sims_never_issue_directives():
    clock = FakeClock()
    orch = GodOrchestrator(
        GodConfig(enabled=True, preset="caos", intervention_frequency=1.0, intensity=1.0),
        rng=random.Random(1),
        clock=clock,
    )
    world = _played_world()
    assert orch.played_ids(world) == {"1", "2"}

    for _ in range(100):
        assert await orch.maybe_intervene(world) == []
        clock.advance(30)


async def test_mixed_census_target_is_never_a_played_sim():
    clock = FakeClock()
    orch = GodOrchestrator(
        GodConfig(enabled=True, preset="caos", intervention_frequency=1.0, intensity=1.0),
        rng=random.Random(7),
        clock=clock,
    )
    world = _mixed_world()
    played = world.played_ids()

    issued = 0
    for _ in range(300):
        directives = await orch.maybe_intervene(world)
        for directive in directives:
            assert directive.target_sim not in played
            issued += 1
        clock.advance(30)
    assert issued > 0


async def test_high_dials_never_target_played_sims():
    clock = FakeClock()
    orch = GodOrchestrator(
        GodConfig(
            enabled=True,
            preset="caos",
            intervention_frequency=1.0,
            intensity=1.0,
            autonomy_degree=1.0,
            chaos_degree=1.0,
        ),
        rng=random.Random(3),
        clock=clock,
    )
    world = _mixed_world()
    played = world.played_ids()

    for _ in range(500):
        for directive in await orch.maybe_intervene(world):
            assert directive.target_sim not in played
        clock.advance(30)
