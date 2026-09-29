"""End-to-end tests for the God-agent graph functions (zeitgeist, census, backgrounds)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sensewright_sidecar.agent import graph
from sensewright_sidecar.config import AgentsConfig, GodConfig, LLMConfig, MemoryConfig, Settings
from sensewright_sidecar.schemas import (
    BackgroundRequest,
    CensusHousehold,
    CensusRequest,
    CensusSim,
    GodTickRequest,
    SimRef,
)


@pytest.fixture
def god_settings():
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


SIM = SimRef(player_id="local", save_id="save1", sim_id=10, household_id=5)


async def test_zeitgeist_unconfigured(god_settings):
    result = await graph.get_zeitgeist("save1")
    assert result["ok"] is True
    assert result["zeitgeist"]["configured"] is False
    assert result["zeitgeist"]["mood_tags"] == []


async def test_set_zeitgeist_persists_and_rewrites(god_settings):
    result = await graph.set_zeitgeist(SIM, ["caos", "terror", "nope"], "a haunted cul-de-sac", 0.8, "en")

    assert result["ok"] is True
    zg = result["zeitgeist"]
    assert zg["configured"] is True
    assert zg["mood_tags"] == ["caos", "terror"]
    assert zg["mood_influence"] == 0.8
    assert zg["rewritten_text"]  # local template fallback (no provider)

    fetched = await graph.get_zeitgeist("save1")
    assert fetched["zeitgeist"]["configured"] is True
    assert fetched["zeitgeist"]["mood_tags"] == ["caos", "terror"]


async def test_suggest_zeitgeist_returns_text(god_settings):
    result = await graph.suggest_zeitgeist(SIM, ["romance"], "", "pt-BR")
    assert result["ok"] is True
    assert result["suggested_text"]
    assert result["provider"] is None


async def test_ingest_census_and_controls(god_settings):
    req = CensusRequest(
        sim=SIM,
        scope="active_zone",
        sims=[
            CensusSim(
                sim_id=10,
                full_name="Ana",
                household_id=5,
                traits=["ambitious"],
                age="adult",
                career="Chef",
                skills={"cooking": 4},
                relationships=[{"target_id": 11, "depth": 30.0}],
                is_player=True,
            )
        ],
        households=[CensusHousehold(household_id=5, name="Silva", members=[10, 11], funds=20000)],
    )

    result = await graph.ingest_census(req)
    assert result["ok"] is True
    assert result["sims"] == 1
    assert result["households"] == 1
    # v0.3 R2: the census seeds the agent-seat pool.
    assert result["seats"]["used"] == 1
    assert result["seats"]["seats"] == 12

    controls = graph.god_controls()
    assert controls["ok"] is True
    assert any(c["key"] == "mood_influence" for c in controls["controls"])
    assert "autonomy_degree" in controls["values"]


async def test_generate_sim_background_cached(god_settings):
    req = BackgroundRequest(
        sim=SIM,
        scope="sim",
        census={"full_name": "Ana", "traits": ["ambitious"], "age": "adult", "lang": "en"},
        lang="en",
    )

    first = await graph.generate_background(req)
    assert first["ok"] is True
    assert first["cached"] is False
    assert first["background"]["source"] in ("template", "llm")
    assert first["background"]["text"]

    second = await graph.generate_background(req)
    assert second["ok"] is True
    assert second["cached"] is True
    assert second["background"]["text"] == first["background"]["text"]


async def test_generate_household_background(god_settings):
    req = BackgroundRequest(
        sim=SIM,
        scope="household",
        household_id=5,
        census={"name": "Silva", "members": ["Ana", "Beto"], "funds": 20000, "lang": "en"},
        lang="en",
    )

    result = await graph.generate_background(req)
    assert result["ok"] is True
    assert result["scope"] == "household"
    assert result["household_id"] == 5
    assert result["background"]["text"]


async def test_zeitgeist_change_marks_household_stale(god_settings):
    await graph.generate_background(
        BackgroundRequest(
            sim=SIM,
            scope="household",
            household_id=5,
            census={"name": "Silva", "members": ["Ana"], "lang": "en"},
            lang="en",
        )
    )
    await graph.set_zeitgeist(SIM, ["romance"], "", 0.9, "en")

    regenerated = await graph.generate_background(
        BackgroundRequest(sim=SIM, scope="household", household_id=5, lang="en")
    )
    assert regenerated["ok"] is True
    assert regenerated["cached"] is False


@pytest.fixture
def god_enabled_settings():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            home=Path(tmp),
            llm=LLMConfig(chain=[], providers={}),
            memory=MemoryConfig(provider="sqlite", embedding_provider="none"),
            agents=AgentsConfig(autonomy_default="semi"),
            god=GodConfig(
                enabled=True,
                preset="caos",
                intervention_frequency=1.0,
                intensity=0.9,
                autonomy_degree=1.0,
                chaos_degree=0.9,
            ),
            lang="en",
        )
        graph.configure(settings)
        yield settings
        import asyncio

        try:
            asyncio.run(graph.shutdown())
        except Exception:
            pass


async def test_god_tick_emits_a_directive(god_enabled_settings):
    await graph.ingest_census(
        CensusRequest(
            sim=SIM,
            scope="active_zone",
            sims=[
                CensusSim(sim_id=10, full_name="Ana", is_player=True),
                CensusSim(sim_id=11, full_name="Beto", relationships=[{"target_id": 10, "depth": 20.0}]),
            ],
            households=[CensusHousehold(household_id=5, name="Silva", members=[10, 11], funds=1000)],
        )
    )

    result = await graph.god_tick(GodTickRequest(sim=SIM, time_of_day="evening"))

    assert result["ok"] is True
    assert result["enabled"] is True
    assert result["preset"] == "caos"
    assert len(result["directives"]) == 1

    directive = result["directives"][0]
    assert directive["source"] == "god"
    assert directive["narration"]
    assert directive["id"].startswith("god-")

    # The cadence gate blocks a second intervention immediately after.
    assert (await graph.god_tick(GodTickRequest(sim=SIM)))["directives"] == []


async def test_god_tick_disabled_emits_nothing(god_settings):
    await graph.ingest_census(CensusRequest(sim=SIM, scope="active_zone", sims=[], households=[]))
    result = await graph.god_tick(GodTickRequest(sim=SIM))
    assert result["ok"] is True
    assert result["enabled"] is False
    assert result["directives"] == []
