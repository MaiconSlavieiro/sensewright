"""Tests for the v0.3 SeatManager, IntentBus and the seats/intents endpoints."""

from __future__ import annotations

import httpx
import pytest

from sensewright_sidecar.agent.intents import (
    IntentBus,
    intent_from_directive,
    normalize_intent,
)
from sensewright_sidecar.agent.seats import SeatManager
from sensewright_sidecar.schemas import IntentResponse, RosterResponse

# ─── SeatManager ──────────────────────────────────────────────────────


def test_sync_assigns_household_before_visitors():
    mgr = SeatManager(seats=2)
    sims = [
        {"sim_id": 9, "household_id": 9, "is_player": False},
        {"sim_id": 1, "household_id": 5, "is_player": True},
        {"sim_id": 2, "household_id": 5, "is_player": False},
    ]

    report = mgr.sync("local", "s1", sims, active_sim_id=1)

    assert report["used"] == 2
    roster = mgr.roster("local", "s1")
    assert [a["sim_id"] for a in roster["agents"]] == [1, 2]
    assert all(a["tier"] == "household" for a in roster["agents"])
    assert mgr.occupies("local", "s1", 9) is False


def test_sync_evicts_sims_that_leave_the_lot():
    mgr = SeatManager(seats=4)
    mgr.sync("local", "s1", [
        {"sim_id": 1, "household_id": 5, "is_player": True},
        {"sim_id": 2, "household_id": 7, "is_player": False},
    ], active_sim_id=1)

    report = mgr.sync("local", "s1", [
        {"sim_id": 1, "household_id": 5, "is_player": True},
    ], active_sim_id=1)

    assert report["evicted"] == [2]
    assert mgr.occupies("local", "s1", 2) is False


def test_configure_resizes_and_trims():
    mgr = SeatManager(seats=3)
    mgr.sync("local", "s1", [
        {"sim_id": sid, "household_id": 5, "is_player": sid == 1}
        for sid in (1, 2, 3)
    ], active_sim_id=1)

    mgr.configure(1)

    assert mgr.pool == 1
    assert mgr.seats_for("local", "s1")[0]["sim_id"] == 1


def test_frequency_override_survives_resync_and_reports():
    mgr = SeatManager(seats=2)
    sims = [{"sim_id": 1, "household_id": 5, "is_player": True}]
    mgr.sync("local", "s1", sims, active_sim_id=1)

    assert mgr.set_impulse_frequency("local", "s1", 1, 0.7) is True
    mgr.sync("local", "s1", sims, active_sim_id=1)

    assert mgr.frequency_for("local", "s1", 1) == 0.7
    assert mgr.snapshot()["by_tier"]["household"] == 1


# ─── intent conversion + bus ──────────────────────────────────────────


def test_intent_from_directive_maps_kinds_and_keeps_legacy_keys():
    mood = intent_from_directive(7, {
        "id": "d1", "sim_id": 7, "name": "add_buff",
        "args": {"buff_name": "Happy"}, "thought": "t",
    })
    assert mood["kind"] == "set_mood"
    assert mood["params"] == {"buff_name": "Happy"}
    assert mood["name"] == "add_buff"  # escape-hatch key preserved
    assert mood["expires_at"] == "next_sleep"

    assert intent_from_directive(7, {"name": "say_to", "args": {}})["kind"] == "speak"
    assert (
        intent_from_directive(7, {"name": "queue_interaction", "args": {}})["kind"]
        == "bias_interaction"
    )
    assert intent_from_directive(7, {"name": "mystery", "args": {}})["kind"] == "command"


def test_normalize_intent_validates_shape():
    assert normalize_intent({}, default_sim_id=1) is None
    assert normalize_intent({"kind": "bogus", "name": "x"}, default_sim_id=1)["kind"] == "command"
    assert normalize_intent({"kind": "command"}, default_sim_id=1) is None
    normalized = normalize_intent(
        {"kind": "speak", "sim_id": 3, "params": {"text": "hi"}}, default_sim_id=1
    )
    assert normalized["sim_id"] == 3
    assert normalized["kind"] == "speak"


def test_intent_bus_store_pull_filter_and_clear():
    bus = IntentBus()
    bus.store("local", "s1", {"id": "a", "sim_id": 1, "kind": "speak"})
    bus.store("local", "s1", {"id": "b", "sim_id": 2, "kind": "set_mood"})

    first = bus.pull("local", "s1", limit=1)
    assert [i["id"] for i in first] == ["a"]
    assert bus.pending_count("local", "s1") == 1

    only_2 = bus.pull("local", "s1", sim_id=2)
    assert [i["id"] for i in only_2] == ["b"]
    assert bus.pending_count() == 0

    bus.store("local", "s1", {"id": "c", "sim_id": 1, "kind": "approach"})
    assert bus.snapshot()["by_kind"] == {"approach": 1}
    bus.clear("local", "s1")
    assert bus.pending_count() == 0


# ─── endpoints ────────────────────────────────────────────────────────


@pytest.fixture
def configured_graph(settings):
    import asyncio

    from sensewright_sidecar.agent import graph

    graph.configure(settings)
    yield settings
    try:
        asyncio.run(graph.shutdown())
    except Exception:
        pass


class TestSeatsEndpoint:
    async def test_seats_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.get("/v1/agency/seats", params={"save_id": "s1"})
        assert resp.status_code == 401

    async def test_seats_200_and_resize(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], configured_graph
    ):
        resp = await client.get(
            "/v1/agency/seats", params={"save_id": "s1"}, headers=auth_headers
        )
        assert resp.status_code == 200
        body = RosterResponse(**resp.json())
        assert body.ok is True
        assert body.seats == 12

        resp = await client.post(
            "/v1/agency/seats",
            json={"sim": {"save_id": "s1", "sim_id": 1}, "seats": 3},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert RosterResponse(**resp.json()).seats == 3


class TestIntentsEndpoint:
    async def test_intents_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.get("/v1/autonomy/intents", params={"save_id": "s1"})
        assert resp.status_code == 401

    async def test_intents_200(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], configured_graph
    ):
        resp = await client.get(
            "/v1/autonomy/intents",
            params={"save_id": "s1", "player_id": "local"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = IntentResponse(**resp.json())
        assert body.ok is True
        assert isinstance(body.intents, list)
