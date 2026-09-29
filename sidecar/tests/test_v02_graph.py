"""Integration tests for the v0.2 graph wiring (agency, aggregates, ticks)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sensewright_sidecar.agent import graph
from sensewright_sidecar.config import AgentsConfig, LLMConfig, MemoryConfig, Settings
from sensewright_sidecar.schemas import (
    AutonomySimState,
    AutonomyTickRequest,
    CensusHousehold,
    CensusRequest,
    CensusSim,
    EventRecord,
    SimRef,
    ZoneContext,
)

SIM = SimRef(player_id="local", save_id="save1", sim_id=10, household_id=5)
OTHER = SimRef(player_id="local", save_id="save1", sim_id=11, household_id=5)


@pytest.fixture
def v02_settings():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            home=Path(tmp),
            llm=LLMConfig(chain=[], providers={}),
            memory=MemoryConfig(provider="sqlite", embedding_provider="none"),
            agents=AgentsConfig(autonomy_default="semi"),
            lang="en",
        )
        graph.configure(settings)
        yield settings
        import asyncio

        try:
            asyncio.run(graph.shutdown())
        except Exception:
            pass


async def _seed_census() -> None:
    await graph.ingest_census(
        CensusRequest(
            sim=SIM,
            scope="active_zone",
            sims=[
                CensusSim(sim_id=10, full_name="Ana", mood="happy", is_player=True),
                CensusSim(sim_id=11, full_name="Beto", mood="tense"),
            ],
            households=[CensusHousehold(household_id=5, name="Silva", members=[10, 11], funds=20000)],
        )
    )


async def test_god_aggregates(v02_settings):
    await _seed_census()
    result = graph.god_aggregates("save1")
    assert result["ok"] is True
    assert result["save_id"] == "save1"
    assert result["neighborhood"]["population"] == 2
    assert result["neighborhood"]["household_count"] == 1
    assert result["neighborhood"]["funds"] == 20000


async def test_autonomy_tick_caches_world_and_detects_sleep(v02_settings):
    tick = await graph.ingest_autonomy_tick(
        AutonomyTickRequest(
            sim=SIM,
            zone=ZoneContext(time_of_day="night", lot_type="residential"),
            sims=[
                AutonomySimState(sim_id=10, full_name="Ana", autonomy="semi", is_player=True),
                AutonomySimState(sim_id=11, full_name="Beto", autonomy="full", sleeping=True),
            ],
        )
    )
    assert tick["ok"] is True
    assert tick["sleeping"] == [11]


async def test_reaction_round_trip(v02_settings):
    await graph.ingest_autonomy_tick(
        AutonomyTickRequest(
            sim=SIM,
            sims=[AutonomySimState(sim_id=11, full_name="Beto", autonomy="full")],
        )
    )
    await graph.ingest_events(
        [
            EventRecord(
                sim=OTHER,
                type="relationship_change",
                content={"target_id": 10, "depth": -40.0},
                importance=2.0,
            )
        ]
    )

    processed = await graph.process_agency_once()
    assert processed >= 1

    pulled = await graph.pull_directives("local", "save1")
    assert pulled["ok"] is True
    assert pulled["directives"], "expected a scheduled reaction directive"
    directive = pulled["directives"][0]
    assert directive["source"] == "agent"
    assert directive["sim_id"] == 11
    assert directive["name"]


async def test_pull_directives_filters_by_sim(v02_settings):
    await graph.ingest_autonomy_tick(
        AutonomyTickRequest(sim=SIM, sims=[AutonomySimState(sim_id=11, autonomy="full")])
    )
    await graph.ingest_events(
        [EventRecord(sim=OTHER, type="fire", content={}, importance=3.0)]
    )
    await graph.process_agency_once()

    assert await graph.pull_directives("local", "save1", sim_id=999) == {
        "ok": True,
        "directives": [],
    }
    assert (await graph.pull_directives("local", "save1", sim_id=11))["directives"]


def test_status_exposes_agency(v02_settings):
    status = graph.status()
    assert "agency" in status
    assert status["agency"]["level"] == "full"
    assert "coordinator" in status["agency"]
    assert "personality" in status
