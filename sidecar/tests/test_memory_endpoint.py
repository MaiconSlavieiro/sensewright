"""Endpoint tests for POST /v1/memory/consolidate (manual pie-menu action)."""

from __future__ import annotations

import httpx
import pytest

from sensewright_sidecar.agent import graph
from sensewright_sidecar.memory.base import MemKey


@pytest.fixture
def configured_graph(settings):
    """Configure the module-level graph (ASGITransport skips the lifespan)."""
    import asyncio

    graph.configure(settings)
    yield settings
    try:
        asyncio.run(graph.shutdown())
    except Exception:
        pass


class TestMemoryConsolidateEndpoint:
    async def test_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.post("/v1/memory/consolidate", json={"sim": {"sim_id": 10}})
        assert resp.status_code == 401

    async def test_reports_none_when_no_turns(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], configured_graph
    ):
        payload = {"sim": {"player_id": "local", "save_id": "s1", "sim_id": 10}, "lang": "en"}
        resp = await client.post("/v1/memory/consolidate", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["consolidated"] == 0
        assert body["message_key"] == "notify.consolidate.none"

    async def test_consolidates_pending_turns(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], configured_graph
    ):
        key = MemKey("local", "s1", 10)
        await graph._memory.add_event(key, {"type": "chat", "content": {"message": "oi"}})
        await graph._memory.add_event(key, {"type": "chat", "content": {"message": "tudo bem?"}})

        payload = {"sim": {"player_id": "local", "save_id": "s1", "sim_id": 10}, "lang": "en"}
        resp = await client.post("/v1/memory/consolidate", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["consolidated"] == 2
        assert body["message_key"] == "notify.consolidate.done"

    async def test_queue_true_enqueues_without_blocking(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], configured_graph
    ):
        # A running background scheduler gives the player action a top-priority lane.
        await graph.start_backgrounds()
        await graph.stop_backgrounds()

        payload = {
            "sim": {"player_id": "local", "save_id": "s1", "sim_id": 10},
            "queue": True,
            "lang": "en",
        }
        resp = await client.post("/v1/memory/consolidate", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["queued"] is True
        assert body["message_key"] == "notify.consolidate.queued"
