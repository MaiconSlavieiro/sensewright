"""Regression tests for the previously-known code gaps.

Covers the ``gap-*`` items from ``docs/feature-review.json``:
inert layer/roster toggles, ignored ``dejavu_chance``, un-wired retention
pruning, missing immediate extreme absorption, un-enforced intent
``expires_at``, missing intent schemas and the absent zone-load census diff.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from sensewright_sidecar.agent import graph
from sensewright_sidecar.agent.context_forge import ContextForge
from sensewright_sidecar.agent.intents import IntentBus
from sensewright_sidecar.agent.nodes import AgentNodes
from sensewright_sidecar.config import (
    AgentsConfig,
    LayersConfig,
    LLMConfig,
    MemoryConfig,
    Settings,
)
from sensewright_sidecar.memory.base import MemKey
from sensewright_sidecar.schemas import (
    CensusHousehold,
    CensusRequest,
    CensusSim,
    ChatRequest,
    EventRecord,
    SimRef,
)
from sensewright_sidecar.tools.schemas import (
    INTENT_KINDS,
    get_all_intent_schemas,
    get_intent_schemas,
)


class FakeMemory:
    """Minimal in-memory stand-in for the MemoryStore protocol."""

    def __init__(self, events: list[dict] | None = None) -> None:
        self.events = list(events or [])
        self.profiles: dict[str, dict] = {}
        self.touched: list[int] = []
        self.prune_calls: list[tuple[int, float | None]] = []
        self.prune_result = 0

    async def get_profile(self, key: MemKey) -> dict | None:
        return self.profiles.get(str(key))

    async def upsert_profile(self, key: MemKey, profile: dict) -> None:
        self.profiles[str(key)] = profile

    async def add_event(self, key: MemKey, event: dict) -> int:
        self.events.append({"key": str(key), **event})
        return len(self.events)

    async def recent_events(
        self, key: MemKey, limit: int = 50, *, min_strength: float | None = None
    ) -> list[dict]:
        if min_strength is None:
            return [e for e in self.events if float(e.get("strength", 1.0)) >= 0.2][:limit]
        return list(self.events)[:limit]

    async def touch_events(self, key: MemKey, ids: list[int]) -> int:
        self.touched.extend(int(i) for i in ids)
        return len(ids)

    async def prune_forgotten(self, retention_days: int, now: float | None = None) -> int:
        self.prune_calls.append((retention_days, now))
        return self.prune_result


@pytest.fixture
def graph_settings():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            home=Path(tmp),
            llm=LLMConfig(chain=[], providers={}),
            memory=MemoryConfig(provider="sqlite", embedding_provider="none"),
            agents=AgentsConfig(),
            lang="en",
        )
        graph.configure(settings)
        yield settings
        import asyncio

        try:
            asyncio.run(graph.shutdown())
        except Exception:
            pass


# ─── gap-dejavu: dejavu_chance is read from config ────────────────────


async def test_dejavu_uses_configured_chance():
    weak = [
        {
            "id": 1,
            "type": "chat",
            "content": {"message": "an old forgotten thing"},
            "strength": 0.05,
        }
    ]
    req = ChatRequest(sim=SimRef(player_id="p", save_id="s", sim_id=1), message="hi")

    always = AgentNodes(registry=None, memory=FakeMemory(weak), dejavu_chance=1.0)
    recall = await always.recall_node(req)
    assert any(event["type"] == "dejavu" for event in recall["recent_events"])

    never = AgentNodes(registry=None, memory=FakeMemory(weak), dejavu_chance=0.0)
    recall_off = await never.recall_node(req)
    assert not any(event["type"] == "dejavu" for event in recall_off["recent_events"])


# ─── gap-layers: memory layer toggle gates recall ─────────────────────


async def test_memory_layer_toggle_gates_context():
    memory = FakeMemory(
        events=[{"id": 1, "type": "chat", "content": {"message": "remembered"}, "strength": 1.0}]
    )
    job = SimpleNamespace(player_id="p", save_id="s", sim_id=1)

    on = Settings(agents=AgentsConfig(layers=LayersConfig(memory=True)))
    ctx_on = await ContextForge(memory, on).build(job)
    assert ctx_on["memories"]

    off = Settings(agents=AgentsConfig(layers=LayersConfig(memory=False)))
    ctx_off = await ContextForge(memory, off).build(job)
    assert ctx_off["memories"] == []


# ─── gap-layers: runtime.expose_roster gates the roster ───────────────


async def test_expose_roster_toggle_gates_roster(graph_settings):
    graph_settings.runtime.expose_roster = True
    graph.assign_seat("s1", "local", seats=3)
    visible = graph.seats_roster("s1")
    assert visible["agents"] == []  # no Sims synced yet, but the surface is exposed
    assert "exposed" not in visible

    graph_settings.runtime.expose_roster = False
    hidden = graph.seats_roster("s1")
    assert hidden["exposed"] is False
    assert hidden["agents"] == []
    assert hidden["used"] == 0


# ─── gap-prune: retention pruning is wired and throttled ──────────────


async def test_maybe_prune_memory_is_wired_and_throttled(graph_settings, monkeypatch):
    memory = FakeMemory()
    memory.prune_result = 2
    monkeypatch.setattr(graph, "_memory", memory)
    monkeypatch.setattr(graph, "_last_prune_at", 0.0)

    assert await graph.maybe_prune_memory(force=True, now=1000.0) == 2
    assert memory.prune_calls[0][0] == graph_settings.memory.retention_days

    # Throttled: within the interval the DB is not touched again.
    assert await graph.maybe_prune_memory(now=1001.0) == 0
    assert len(memory.prune_calls) == 1

    later = 1000.0 + graph._PRUNE_INTERVAL_SECONDS + 1
    assert await graph.maybe_prune_memory(now=later) == 2
    assert len(memory.prune_calls) == 2


# ─── gap-absorb: extreme events are absorbed immediately ──────────────


async def test_extreme_event_absorbed_immediately(graph_settings):
    sim = SimRef(player_id="local", save_id="xsave", sim_id=1, household_id=1)
    await graph.ingest_events(
        [
            EventRecord(
                sim=sim,
                type="death",
                content={"message": "a loved one died"},
                importance=1.0,
            )
        ]
    )

    profile = await graph._memory.get_profile(MemKey("local", "xsave", 1))
    assert profile is not None
    assert profile.get("psyche", {}).get("traumas")


async def test_ordinary_event_is_not_absorbed_immediately(graph_settings):
    sim = SimRef(player_id="local", save_id="osave", sim_id=2, household_id=1)
    await graph.ingest_events(
        [EventRecord(sim=sim, type="chat", content={"message": "hello there"}, importance=1.0)]
    )

    profile = await graph._memory.get_profile(MemKey("local", "osave", 2))
    assert not (profile or {}).get("psyche", {}).get("traumas")


# ─── gap-expires: intent expires_at is enforced ───────────────────────


def test_intent_bus_expires_numeric_deadline():
    bus = IntentBus()
    bus.store("p", "s", {"id": "dead", "sim_id": 1, "kind": "speak", "expires_at": 100.0})
    bus.store("p", "s", {"id": "alive", "sim_id": 1, "kind": "speak", "expires_at": 10**12})

    pulled = bus.pull("p", "s", now=500.0)
    assert [intent["id"] for intent in pulled] == ["alive"]
    assert bus.snapshot()["expired"] == 1


def test_intent_bus_expires_on_next_sleep():
    bus = IntentBus()
    bus.store("p", "s", {"id": "x", "sim_id": 2, "kind": "speak"})  # default next_sleep
    assert [i["id"] for i in bus.pull("p", "s")] == ["x"]

    bus.store("p", "s", {"id": "y", "sim_id": 2, "kind": "speak"})
    bus.note_sleep("p", "s", 2, ts=10**18)
    assert bus.pull("p", "s", now=10**18) == []
    assert bus.snapshot()["expired"] == 1


def test_intent_bus_next_sleep_leaves_other_sims_alone():
    bus = IntentBus()
    bus.store("p", "s", {"id": "a", "sim_id": 1, "kind": "speak"})
    bus.store("p", "s", {"id": "b", "sim_id": 2, "kind": "speak"})
    bus.note_sleep("p", "s", 1, ts=10**18)

    remaining = bus.pull("p", "s", now=10**18)
    assert [i["id"] for i in remaining] == ["b"]


# ─── gap-intent-schemas: intent schemas exist ─────────────────────────


def test_intent_schemas_cover_all_kinds():
    schemas = get_intent_schemas()
    assert set(schemas) == set(INTENT_KINDS)
    for kind, schema in schemas.items():
        assert schema["type"] == "function"
        assert schema["function"]["name"] == kind
        assert schema["function"]["parameters"]["type"] == "object"

    assert len(get_all_intent_schemas()) == len(INTENT_KINDS)
    assert get_intent_schemas(["speak", "bogus"]) == {"speak": schemas["speak"]}


# ─── gap-census-diff: zone-load diff ──────────────────────────────────


def test_diff_census_same_scope_tracks_additions():
    previous = {
        "scope": "active_zone",
        "sims": [{"sim_id": 1}],
        "households": [{"household_id": 5}],
    }
    diff = graph._diff_census(
        previous,
        "active_zone",
        [{"sim_id": 1}, {"sim_id": 2}],
        [{"household_id": 5}, {"household_id": 6}],
    )
    assert diff["sims_added"] == [2]
    assert diff["sims_removed"] == []
    assert diff["households_added"] == [6]
    assert diff["households_removed"] == []


def test_diff_census_ignores_removals_across_scopes():
    previous = {
        "scope": "full_save",
        "sims": [{"sim_id": 1}, {"sim_id": 2}],
        "households": [],
    }
    diff = graph._diff_census(previous, "active_zone", [{"sim_id": 1}], [])
    assert diff["sims_added"] == []
    assert diff["sims_removed"] == []


def test_diff_census_first_snapshot_has_no_removals():
    diff = graph._diff_census(None, "active_zone", [{"sim_id": 1}], [{"household_id": 5}])
    assert diff["sims_added"] == [1]
    assert diff["sims_removed"] == []


async def test_ingest_census_reports_diff(graph_settings):
    sim = SimRef(player_id="local", save_id="diffsave", sim_id=10, household_id=5)
    await graph.ingest_census(
        CensusRequest(
            sim=sim,
            scope="active_zone",
            sims=[CensusSim(sim_id=10, full_name="Ana", household_id=5, is_player=True)],
            households=[CensusHousehold(household_id=5, name="Silva", members=[10])],
        )
    )

    result = await graph.ingest_census(
        CensusRequest(
            sim=sim,
            scope="active_zone",
            sims=[
                CensusSim(sim_id=10, full_name="Ana", household_id=5, is_player=True),
                CensusSim(sim_id=11, full_name="Beto", household_id=6),
            ],
            households=[
                CensusHousehold(household_id=5, name="Silva", members=[10]),
                CensusHousehold(household_id=6, name="Souza", members=[11]),
            ],
        )
    )

    assert result["diff"]["sims_added"] == [11]
    assert result["diff"]["households_added"] == [6]
