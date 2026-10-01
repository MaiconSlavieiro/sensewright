"""Tests for the built-in web panel (``/`` + ``/ui/*``)."""

from __future__ import annotations

import json

import httpx
from httpx import ASGITransport

from sensewright_sidecar.config import Settings
from sensewright_sidecar.god.controls import CONTROL_SPECS
from sensewright_sidecar.server import create_app


class TestIndex:
    async def test_index_serves_html(self, client: httpx.AsyncClient):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        assert "/ui/app.js" in resp.text

    async def test_index_404_when_disabled(self, settings: Settings, token: str):
        settings.ui.web_panel = False
        app = create_app(settings, token)
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/")
        assert resp.status_code == 404


class TestSession:
    async def test_session_discloses_token_to_loopback(self, client: httpx.AsyncClient, token: str):
        resp = await client.get("/ui/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["token"] == token
        assert data["lang"] in ("en", "pt-BR")
        assert isinstance(data["locales"], list) and data["locales"]

    async def test_session_hides_token_from_remote(self, settings: Settings, token: str):
        app = create_app(settings, token)
        transport = ASGITransport(app=app, client=("10.0.0.5", 1234))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/ui/session")
        assert resp.status_code == 200
        assert resp.json()["token"] is None

    async def test_session_404_when_disabled(self, settings: Settings, token: str):
        settings.ui.web_panel = False
        app = create_app(settings, token)
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/ui/session")
        assert resp.status_code == 404


class TestAssets:
    async def test_app_js(self, client: httpx.AsyncClient):
        resp = await client.get("/ui/app.js")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("application/javascript")

    async def test_style_css(self, client: httpx.AsyncClient):
        resp = await client.get("/ui/style.css")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/css")

    async def test_unknown_locale_404(self, client: httpx.AsyncClient):
        resp = await client.get("/ui/locales/fr.json")
        assert resp.status_code == 404


class TestLocales:
    async def test_locales_parity(self, client: httpx.AsyncClient):
        en = (await client.get("/ui/locales/en.json")).json()
        pt = (await client.get("/ui/locales/pt-BR.json")).json()
        assert set(en) == set(pt)

    async def test_every_control_key_is_localized(self, client: httpx.AsyncClient):
        en = (await client.get("/ui/locales/en.json")).json()
        pt = (await client.get("/ui/locales/pt-BR.json")).json()
        for spec in CONTROL_SPECS:
            keys = [spec.label_key, spec.description_key] + [o.label_key for o in spec.options]
            for key in keys:
                if not key:
                    continue
                assert key in en, f"missing en label for {spec.key}: {key}"
                assert key in pt, f"missing pt-BR label for {spec.key}: {key}"

    async def test_locale_is_valid_json(self, client: httpx.AsyncClient):
        resp = await client.get("/ui/locales/en.json")
        json.loads(resp.text)
