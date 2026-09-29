"""Endpoint tests for the v0.2 autonomy + aggregates routes."""

from __future__ import annotations

import httpx
import pytest

from sensewright_sidecar.schemas import (
    AggregatesResponse,
    AutonomyTickResponse,
    DirectivesResponse,
)


@pytest.fixture
def configured_graph(settings):
    """Configure the module-level agent graph for the endpoint tests.

    ``httpx.ASGITransport`` does not run the FastAPI lifespan, so the graph is
    configured explicitly here (and torn down after).
    """
    import asyncio

    from sensewright_sidecar.agent import graph

    graph.configure(settings)
    yield settings
    try:
        asyncio.run(graph.shutdown())
    except Exception:
        pass


class TestAutonomyTickEndpoint:
    async def test_tick_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.post("/v1/autonomy/tick", json={"sim": {"sim_id": 10}})
        assert resp.status_code == 401

    async def test_tick_200(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], configured_graph
    ):
        payload = {
            "sim": {"player_id": "local", "save_id": "save1", "sim_id": 10},
            "zone": {"time_of_day": "evening", "lot_type": "residential"},
            "sims": [
                {"sim_id": 11, "full_name": "Beto", "autonomy": "full", "sleeping": True}
            ],
            "lang": "en",
        }
        resp = await client.post("/v1/autonomy/tick", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        body = AutonomyTickResponse(**resp.json())
        assert body.ok is True
        assert body.sleeping == [11]

    async def test_tick_returns_social_dialogue(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], configured_graph
    ):
        payload = {
            "sim": {"player_id": "local", "save_id": "save9", "sim_id": 130},
            "zone": {"time_of_day": "day", "lot_type": "residential"},
            "sims": [
                {"sim_id": 130, "full_name": "Ana", "autonomy": "full"},
                {"sim_id": 131, "full_name": "Bia", "autonomy": "full"},
            ],
            "lang": "en",
        }
        resp = await client.post("/v1/autonomy/tick", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        body = AutonomyTickResponse(**resp.json())
        assert len(body.social) == 1
        assert len(body.social[0].lines) == 2
        assert body.social[0].source == "template"


class TestAutonomyDirectivesEndpoint:
    async def test_directives_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.get("/v1/autonomy/directives", params={"save_id": "save1"})
        assert resp.status_code == 401

    async def test_directives_200(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], configured_graph
    ):
        resp = await client.get(
            "/v1/autonomy/directives",
            params={"save_id": "save1", "player_id": "local"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = DirectivesResponse(**resp.json())
        assert body.ok is True
        assert isinstance(body.directives, list)


class TestGodAggregatesEndpoint:
    async def test_aggregates_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.get("/v1/god/aggregates", params={"save_id": "save1"})
        assert resp.status_code == 401

    async def test_aggregates_200(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.get(
            "/v1/god/aggregates",
            params={"save_id": "save1", "player_id": "local"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        body = AggregatesResponse(**resp.json())
        assert body.save_id == "save1"
        assert body.neighborhood.population >= 0
