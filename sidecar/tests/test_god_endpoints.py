"""Tests for the God-agent endpoints (zeitgeist, controls, census, config)."""

from __future__ import annotations

import httpx

from sims_sense_sidecar.schemas import (
    AckResponse,
    BackgroundResponse,
    CensusResponse,
    ControlsResponse,
    GodTickResponse,
    ZeitgeistResponse,
    ZeitgeistSuggestResponse,
)

_SIM = {"player_id": "local", "save_id": "save1", "sim_id": 1}


def _zeitgeist_payload() -> dict:
    return {
        "sim": _SIM,
        "mood_tags": ["novela"],
        "free_text": "a rainy neighborhood",
        "mood_influence": 0.5,
        "lang": "en",
    }


class TestGodZeitgeistEndpoints:
    """Tests for GET/POST /v1/god/zeitgeist (auth required)."""

    async def test_get_zeitgeist_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.get("/v1/god/zeitgeist", params={"save_id": "save1"})
        assert resp.status_code == 401

    async def test_post_zeitgeist_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.post("/v1/god/zeitgeist", json=_zeitgeist_payload())
        assert resp.status_code == 401

    async def test_get_zeitgeist_200_defaults_unconfigured(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.get(
            "/v1/god/zeitgeist",
            params={"save_id": "save1"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        parsed = ZeitgeistResponse(**data)
        assert parsed.zeitgeist.configured is False

    async def test_post_zeitgeist_200(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.post(
            "/v1/god/zeitgeist",
            json=_zeitgeist_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 200
        ZeitgeistResponse(**resp.json())


class TestGodSuggestEndpoint:
    """Tests for POST /v1/god/zeitgeist/suggest (auth required)."""

    async def test_suggest_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.post("/v1/god/zeitgeist/suggest", json=_zeitgeist_payload())
        assert resp.status_code == 401

    async def test_suggest_200(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.post(
            "/v1/god/zeitgeist/suggest",
            json=_zeitgeist_payload(),
            headers=auth_headers,
        )
        assert resp.status_code == 200
        ZeitgeistSuggestResponse(**resp.json())


class TestGodBackgroundEndpoint:
    """Tests for POST /v1/god/background (auth required)."""

    async def test_background_401_without_token(self, client: httpx.AsyncClient):
        payload = {"sim": _SIM, "scope": "sim", "lang": "en"}
        resp = await client.post("/v1/god/background", json=payload)
        assert resp.status_code == 401

    async def test_background_200(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        payload = {"sim": _SIM, "scope": "sim", "lang": "en"}
        resp = await client.post(
            "/v1/god/background",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        BackgroundResponse(**resp.json())


class TestGodControlsEndpoint:
    """Tests for GET /v1/god/controls (auth required)."""

    async def test_controls_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.get("/v1/god/controls")
        assert resp.status_code == 401

    async def test_controls_200_with_fallback_registry(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.get(
            "/v1/god/controls",
            params={"include_advanced": "true"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        parsed = ControlsResponse(**resp.json())
        assert parsed.controls
        assert parsed.values


class TestGodCensusEndpoint:
    """Tests for POST /v1/census (auth required)."""

    async def test_census_401_without_token(self, client: httpx.AsyncClient):
        payload = {"sim": _SIM, "scope": "active_zone", "sims": [], "households": []}
        resp = await client.post("/v1/census", json=payload)
        assert resp.status_code == 401

    async def test_census_200(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        payload = {"sim": _SIM, "scope": "active_zone", "sims": [], "households": []}
        resp = await client.post(
            "/v1/census",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        CensusResponse(**resp.json())


class TestConfigGodValidation:
    """Tests for ControlSpec validation on POST /v1/config/god."""

    async def test_config_god_rejects_unknown_control(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        payload = {"settings": {"nope": 1}}
        resp = await client.post(
            "/v1/config/god",
            json=payload,
            headers=auth_headers,
        )
        assert resp.status_code == 200
        ack = AckResponse(**resp.json())
        assert ack.ok is False
        assert ack.detail


class TestGodTickEndpoint:
    """Tests for POST /v1/god/tick (auth required)."""

    async def test_tick_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.post("/v1/god/tick", json={"sim": _SIM, "lang": "en"})
        assert resp.status_code == 401

    async def test_tick_200_with_token(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.post(
            "/v1/god/tick",
            json={"sim": _SIM, "lang": "en"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        parsed = GodTickResponse(**resp.json())
        assert isinstance(parsed.directives, list)
