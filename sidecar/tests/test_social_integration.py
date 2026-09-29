"""Integration tests for the sim<->sim channel through Agency / graph (v0.3 R5)."""

from __future__ import annotations

from typing import Any

import pytest

from sims_sense_sidecar.agent import graph
from sims_sense_sidecar.agent.agency import Agency
from sims_sense_sidecar.config import (
    AgentsConfig,
    InitiativeConfig,
    LayersConfig,
    Settings,
    SocialConfig,
)
from sims_sense_sidecar.schemas import (
    AutonomySimState,
    AutonomyTickRequest,
    SimRef,
    ZoneContext,
)


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_settings(
    *, social_enabled: bool = True, pair_cooldown: float = 180.0
) -> Settings:
    return Settings(
        agents=AgentsConfig(
            initiative=InitiativeConfig(max_impulses_per_tick=0),
            layers=LayersConfig(social=social_enabled),
            social=SocialConfig(pair_cooldown_seconds=pair_cooldown),
        )
    )


def tick(sims: list[tuple[int, str, bool]], *, sleeping: tuple[int, ...] = ()) -> AutonomyTickRequest:
    states = [
        AutonomySimState(
            sim_id=sim_id,
            autonomy=autonomy,
            is_player=is_player,
            sleeping=sim_id in sleeping,
        )
        for sim_id, autonomy, is_player in sims
    ]
    return AutonomyTickRequest(
        sim=SimRef(player_id="local", save_id="save1", sim_id=sims[0][0]),
        zone=ZoneContext(time_of_day="evening", lot_type="residential"),
        sims=states,
        lang="en",
    )


async def test_two_non_player_sims_start_a_dialogue():
    agency = Agency(make_settings(), clock=FakeClock())

    result = await agency.ingest_tick(tick([(10, "semi", False), (11, "full", False)]))

    social = result["social"]
    assert len(social) == 1
    dialogue = social[0]
    assert {dialogue["a"], dialogue["b"]} == {10, 11}
    assert len(dialogue["lines"]) == 2
    assert dialogue["source"] == "template"

    intents = result["social_intents"]
    assert len(intents) == 2
    assert all(intent["kind"] == "speak" for intent in intents)
    assert all(intent["name"] == "say_to" for intent in intents)
    assert {intent["sim_id"] for intent in intents} == {10, 11}


async def test_pair_cooldown_blocks_a_repeat_pulse():
    clock = FakeClock()
    agency = Agency(make_settings(pair_cooldown=180.0), clock=clock)
    request = tick([(10, "semi", False), (11, "semi", False)])

    first = await agency.ingest_tick(request)
    assert len(first["social"]) == 1

    clock.advance(30.0)
    second = await agency.ingest_tick(request)
    assert second["social"] == []

    clock.advance(200.0)
    third = await agency.ingest_tick(request)
    assert len(third["social"]) == 1


async def test_player_sims_never_pair():
    agency = Agency(make_settings(), clock=FakeClock())
    result = await agency.ingest_tick(tick([(10, "semi", True), (11, "full", True)]))
    assert result["social"] == []
    assert result["social_intents"] == []


async def test_sleeping_and_off_sims_are_excluded():
    agency = Agency(make_settings(), clock=FakeClock())
    result = await agency.ingest_tick(
        tick([(10, "semi", False), (11, "semi", False)], sleeping=(11,))
    )
    assert result["social"] == []


async def test_social_layer_toggle_disables_dialogues():
    agency = Agency(make_settings(social_enabled=False), clock=FakeClock())
    result = await agency.ingest_tick(tick([(10, "semi", False), (11, "semi", False)]))
    assert result["social"] == []


async def test_store_intents_then_pull_drains():
    agency = Agency(make_settings(), clock=FakeClock())
    intent = {"id": "s1", "sim_id": 10, "kind": "speak", "name": "say_to", "args": {}}

    assert agency.store_intents("local", "save1", [intent]) == 1
    assert agency.pending_count("local", "save1") == 1

    pulled = agency.pull("local", "save1")
    assert [item["id"] for item in pulled] == ["s1"]
    assert agency.pending_count("local", "save1") == 0


async def test_snapshot_exposes_social():
    agency = Agency(make_settings(), clock=FakeClock())
    snap = agency.snapshot()
    assert "social" in snap
    assert snap["social"]["enabled"] is True
    assert snap["social"]["pair_cooldown_s"] == 180.0


class FakeMemory:
    def __init__(self) -> None:
        self.events: list[tuple[Any, dict[str, Any]]] = []

    async def add_event(self, key: Any, event: dict[str, Any]) -> None:
        self.events.append((key, event))


async def test_graph_store_social_gates_and_remembers(monkeypatch):
    agency = Agency(make_settings(), clock=FakeClock())
    memory = FakeMemory()
    monkeypatch.setattr(graph, "_rails", None)
    monkeypatch.setattr(graph, "_memory", memory)
    monkeypatch.setattr(graph, "_agency", agency)

    req = tick([(10, "semi", False), (11, "semi", False)])
    dialogue = {
        "a": 10,
        "b": 11,
        "topic": "small talk",
        "source": "template",
        "lines": [
            {"speaker": "a", "text": "hi", "tone": "friendly"},
            {"speaker": "b", "text": "hey", "tone": "friendly"},
        ],
    }
    intents = [
        {"id": "s1", "sim_id": 10, "kind": "speak", "name": "say_to", "args": {}},
        {"id": "s2", "sim_id": 11, "kind": "speak", "name": "say_to", "args": {}},
    ]

    await graph._store_social(req, {"social": [dialogue], "social_intents": intents})

    assert agency.pending_count("local", "save1") == 2
    assert len(memory.events) == 2
    assert all(event["type"] == "social" for _, event in memory.events)
    participants = {key.sim_id for key, _ in memory.events}
    assert participants == {10, 11}


@pytest.mark.parametrize("count", [0, 1])
async def test_graph_store_social_noop_without_dialogues(monkeypatch, count):
    agency = Agency(make_settings(), clock=FakeClock())
    monkeypatch.setattr(graph, "_rails", None)
    monkeypatch.setattr(graph, "_memory", FakeMemory())
    monkeypatch.setattr(graph, "_agency", agency)

    result = {"social": []} if count == 0 else {}
    await graph._store_social(tick([(10, "semi", False), (11, "semi", False)]), result)
    assert agency.pending_count("local", "save1") == 0
