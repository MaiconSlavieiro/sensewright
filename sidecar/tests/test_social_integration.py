"""Integration tests for the sim<->sim channel through Agency / graph (v0.3 R5)."""

from __future__ import annotations

from typing import Any

import pytest

from sensewright_sidecar.agent import graph
from sensewright_sidecar.agent.agency import Agency
from sensewright_sidecar.config import (
    AgentsConfig,
    InitiativeConfig,
    LayersConfig,
    Settings,
    SocialConfig,
)
from sensewright_sidecar.schemas import (
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


def tick(
    sims: list[tuple[int, str, bool]],
    *,
    sleeping: tuple[int, ...] = (),
    conversation: bool = True,
    locations: dict[int, str] | None = None,
) -> AutonomyTickRequest:
    ids = [sim_id for sim_id, _, _ in sims]
    states = []
    for index, (sim_id, autonomy, is_player) in enumerate(sims):
        partner = None
        if conversation:
            if index % 2 == 0 and index + 1 < len(ids):
                partner = ids[index + 1]
            elif index % 2 == 1:
                partner = ids[index - 1]
        states.append(
            AutonomySimState(
                sim_id=sim_id,
                autonomy=autonomy,
                is_player=is_player,
                sleeping=sim_id in sleeping,
                interaction_target_sim_id=partner,
                current_interaction="social_Chat" if partner else "",
                location=(locations or {}).get(sim_id, "10.0,10.0"),
            )
        )
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


async def test_open_session_continues_each_pulse_then_closes():
    """v0.4 P4: an open session advances every pulse (no inter-turn cooldown)."""
    clock = FakeClock()
    agency = Agency(make_settings(pair_cooldown=180.0), clock=clock)
    request = tick([(10, "semi", False), (11, "semi", False)])

    first = await agency.ingest_tick(request)
    assert len(first["social"]) == 1
    assert first["conversations"] == []

    # 30 s later the pair is still interacting: the session continues (the pair
    # cooldown only gates *starting* a session, not its turns) and closes at
    # max_turns=4 with a summary.
    clock.advance(30.0)
    second = await agency.ingest_tick(request)
    assert len(second["social"]) == 1
    assert len(second["conversations"]) == 1

    # After the inter-session cooldown a fresh session may start.
    clock.advance(200.0)
    third = await agency.ingest_tick(request)
    assert len(third["social"]) == 1


async def test_household_sims_may_pair():
    agency = Agency(make_settings(), clock=FakeClock())
    result = await agency.ingest_tick(tick([(10, "semi", True), (11, "full", True)]))
    # v0.3 R5 fix: household Sims are included (and preferred), so a dialogue forms.
    assert len(result["social"]) == 1
    assert result["social_intents"]


async def test_no_native_conversation_means_no_dialogue():
    """v0.3 R5 fix: two seated Sims that are NOT talking natively never converse."""
    agency = Agency(make_settings(), clock=FakeClock())
    result = await agency.ingest_tick(
        tick([(10, "semi", False), (11, "semi", False)], conversation=False)
    )
    assert result["social"] == []
    assert result["social_intents"] == []


async def test_far_apart_conversing_sims_do_not_converse():
    """A mutual native conversation still needs proximity (no telepathy)."""
    agency = Agency(make_settings(), clock=FakeClock())
    result = await agency.ingest_tick(
        tick(
            [(10, "semi", False), (11, "semi", False)],
            locations={10: "0.0,0.0", 11: "50.0,50.0"},
        )
    )
    assert result["social"] == []


async def test_same_room_required_for_dialogue():
    """v0.4 P6: Sims in different rooms never converse (no talking through walls)."""
    agency = Agency(make_settings(), clock=FakeClock())
    req = tick([(10, "semi", False), (11, "semi", False)])
    for state in req.sims:
        state.room_id = 1 if state.sim_id == 10 else 2
    result = await agency.ingest_tick(req)
    assert result["social"] == []


async def test_same_room_allows_dialogue():
    agency = Agency(make_settings(), clock=FakeClock())
    req = tick([(10, "semi", False), (11, "semi", False)])
    for state in req.sims:
        state.room_id = 7
    result = await agency.ingest_tick(req)
    assert len(result["social"]) == 1


async def test_queued_same_sim_keeps_session_open_without_farewell():
    """v0.4 P6: a queued interaction with the same Sim must not be a "goodbye"."""
    clock = FakeClock()
    agency = Agency(make_settings(pair_cooldown=180.0), clock=clock)
    opened = await agency.ingest_tick(tick([(10, "semi", False), (11, "semi", False)]))
    assert len(opened["social"]) == 1

    clock.advance(30.0)
    # The current interaction is momentarily gone, but the queue still continues
    # with the same Sim: the session continues (no leaving summary).
    req = tick([(10, "semi", False), (11, "semi", False)], conversation=False)
    req.sims[0].queued_interactions = [{"name": "social_Chat", "target_sim_id": 11}]
    result = await agency.ingest_tick(req)
    assert len(result["social"]) == 1
    assert all(not summary.get("leaving") for summary in result["conversations"])


async def test_queued_continuation_gated_when_disabled():
    clock = FakeClock()
    settings = Settings(
        agents=AgentsConfig(
            initiative=InitiativeConfig(max_impulses_per_tick=0),
            layers=LayersConfig(social=True),
            social=SocialConfig(pair_cooldown_seconds=180.0, keep_open_on_queued=False),
        )
    )
    agency = Agency(settings, clock=clock)
    await agency.ingest_tick(tick([(10, "semi", False), (11, "semi", False)]))
    clock.advance(30.0)
    req = tick([(10, "semi", False), (11, "semi", False)], conversation=False)
    req.sims[0].queued_interactions = [{"name": "social_Chat", "target_sim_id": 11}]
    result = await agency.ingest_tick(req)
    assert result["social"] == []
    assert len(result["conversations"]) == 1
    assert result["conversations"][0]["leaving"] is True


async def test_unilateral_player_initiated_interaction_forms_a_session():
    """v0.4 P4 live fix: A->B (player social) is enough to open a session."""
    agency = Agency(make_settings(), clock=FakeClock())
    req = tick([(10, "semi", False), (11, "semi", False)], conversation=False)
    req.sims[0].interaction_target_sim_id = 11
    req.sims[0].current_interaction = "social_Chat"
    result = await agency.ingest_tick(req)
    assert len(result["social"]) == 1
    assert {result["social"][0]["a"], result["social"][0]["b"]} == {10, 11}


async def test_player_interaction_seed_opens_a_session_without_pulse_targets():
    """A seed from the player hook starts a conversation even if the pulse has
    no interaction target (the common live case)."""
    clock = FakeClock()
    agency = Agency(make_settings(), clock=clock)
    req = tick([(10, "semi", False), (11, "semi", False)], conversation=False)

    agency.note_interaction_seed(
        "local", "save1", 10, 11, interaction="sim_Flirt", interaction_text="Flertar"
    )
    assert agency.interaction_seeds("local", "save1") == [(10, 11, "sim_Flirt", "Flertar")]

    result = await agency.ingest_tick(req)
    assert len(result["social"]) == 1
    assert {result["social"][0]["a"], result["social"][0]["b"]} == {10, 11}
    # The seed is consumed once the session starts.
    assert agency.interaction_seeds("local", "save1") == []


def test_interaction_seeds_expire():
    clock = FakeClock()
    agency = Agency(make_settings(), clock=clock)
    agency.note_interaction_seed("local", "save1", 10, 11, interaction="Chat")
    clock.advance(1000.0)
    assert agency.interaction_seeds("local", "save1") == []


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
