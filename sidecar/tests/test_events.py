"""Tests for the event-ingestion and player-activity endpoints."""

from __future__ import annotations

import httpx

from sensewright_sidecar.schemas import AckResponse, EventIngestRequest


class TestEventsEndpoint:
    """Tests for POST /v1/events (auth required)."""

    async def test_events_401_without_token(self, client: httpx.AsyncClient):
        payload = {
            "events": [
                {
                    "sim": {"player_id": "local", "save_id": "save1", "sim_id": 1},
                    "type": "mood",
                    "content": {"mood": "happy"},
                }
            ]
        }
        resp = await client.post("/v1/events", json=payload)
        assert resp.status_code == 401

    async def test_events_200_with_two_events(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        payload = {
            "events": [
                {
                    "sim": {"player_id": "local", "save_id": "save1", "sim_id": 1},
                    "type": "mood",
                    "content": {"mood": "happy"},
                    "importance": 1.5,
                    "ts": 123.0,
                    "lang": "en",
                },
                {
                    "sim": {"player_id": "local", "save_id": "save1", "sim_id": 2},
                    "type": "interaction",
                    "content": {"target": "sim3"},
                },
            ]
        }
        resp = await client.post("/v1/events", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        ack = AckResponse(**data)
        assert ack.ok is True

    async def test_events_200_with_empty_list(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.post("/v1/events", json={"events": []}, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        ack = AckResponse(**data)
        assert ack.ok is True


class TestPlayerActivityEndpoint:
    """Tests for POST /v1/config/player-activity (auth required)."""

    async def test_player_activity_401_without_token(self, client: httpx.AsyncClient):
        payload = {"sim": {"player_id": "local", "save_id": "save1", "sim_id": 1}}
        resp = await client.post("/v1/config/player-activity", json=payload)
        assert resp.status_code == 401

    async def test_player_activity_200_with_token(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        payload = {"sim": {"player_id": "local", "save_id": "save1", "sim_id": 1}}
        resp = await client.post("/v1/config/player-activity", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        ack = AckResponse(**data)
        assert ack.ok is True


class TestEventIngestRequestSchema:
    """Tests for the wire payload model."""

    def test_accepts_documented_payload_shape(self):
        req = EventIngestRequest(
            events=[
                {
                    "sim": {"player_id": "local", "save_id": "save1", "sim_id": 1},
                    "type": "mood",
                    "content": {"mood": "happy"},
                    "importance": 2.0,
                    "ts": 42.0,
                    "lang": "pt-BR",
                }
            ]
        )
        assert len(req.events) == 1
        assert req.events[0].sim.sim_id == 1
        assert req.events[0].type == "mood"
        assert req.events[0].importance == 2.0
        assert req.events[0].lang == "pt-BR"

    def test_defaults(self):
        req = EventIngestRequest()
        assert req.events == []
        event = EventIngestRequest(events=[{"sim": {"sim_id": 7}, "type": "x"}]).events[0]
        assert event.content == {}
        assert event.importance == 1.0
        assert event.ts is None
        assert event.lang == "en"
