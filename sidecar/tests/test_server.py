"""Tests for the Sensewright sidecar HTTP server."""

from __future__ import annotations

import httpx
import pytest
from httpx import ASGITransport

from sensewright_sidecar.auth import ensure_token
from sensewright_sidecar.config import (
    AgentsConfig,
    GodConfig,
    LLMConfig,
    LoggingConfig,
    MemoryConfig,
    NetworkConfig,
    Settings,
    UiConfig,
)
from sensewright_sidecar.schemas import (
    AckResponse,
    ChatResponse,
    HealthResponse,
    StatusResponse,
    normalize_lang,
)
from sensewright_sidecar.server import create_app


@pytest.fixture
def test_settings(tmp_path) -> Settings:
    """Settings with a temporary home directory."""
    home = tmp_path / "test_home"
    home.mkdir(parents=True)
    (home / "data").mkdir(exist_ok=True)
    return Settings(
        home=home,
        config_path=None,
        ui=UiConfig(language="en"),
        network=NetworkConfig(host="127.0.0.1", port=8765),
        logging=LoggingConfig(level="DEBUG", file="data/sidecar.log", audit="data/audit.log"),
        llm=LLMConfig(),
        memory=MemoryConfig(),
        agents=AgentsConfig(),
        god=GodConfig(),
        lang="en",
    )


@pytest.fixture
def test_token(test_settings: Settings) -> str:
    return ensure_token(test_settings)


@pytest.fixture
def test_app(test_settings: Settings, test_token: str):
    return create_app(test_settings, test_token)


@pytest.fixture
async def test_client(test_app) -> httpx.AsyncClient:
    transport = ASGITransport(app=test_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers(test_token: str) -> dict[str, str]:
    return {"X-Sensewright-Token": test_token}


class TestHealthEndpoint:
    """Tests for GET /v1/health (no auth required)."""

    async def test_health_returns_200(self, test_client: httpx.AsyncClient):
        resp = await test_client.get("/v1/health")
        assert resp.status_code == 200

    async def test_health_response_shape(self, test_client: httpx.AsyncClient):
        resp = await test_client.get("/v1/health")
        data = resp.json()
        health = HealthResponse(**data)
        assert health.ok is True
        assert health.version == "0.1.0"
        assert health.uptime_s >= 0
        assert health.lang in ("en", "pt-BR")

    async def test_health_no_token_required(self, test_client: httpx.AsyncClient):
        # No headers at all
        resp = await test_client.get("/v1/health")
        assert resp.status_code == 200


class TestStatusEndpoint:
    """Tests for GET /v1/status (auth required)."""

    async def test_status_401_without_token(self, test_client: httpx.AsyncClient):
        resp = await test_client.get("/v1/status")
        assert resp.status_code == 401

    async def test_status_200_with_token(self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]):
        resp = await test_client.get("/v1/status", headers=auth_headers)
        assert resp.status_code == 200

    async def test_status_response_shape(self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]):
        resp = await test_client.get("/v1/status", headers=auth_headers)
        data = resp.json()
        status_resp = StatusResponse(**data)
        assert status_resp.ok is True
        assert status_resp.sidecar_version == "0.1.0"
        assert status_resp.uptime_s >= 0
        assert isinstance(status_resp.providers, list)
        assert isinstance(status_resp.chain_health, dict)
        assert isinstance(status_resp.autonomy, dict)
        assert isinstance(status_resp.memory, dict)
        assert isinstance(status_resp.god, dict)
        assert isinstance(status_resp.backgrounds, dict)


class TestChatEndpoint:
    """Tests for POST /v1/chat (auth required)."""

    async def test_chat_401_without_token(self, test_client: httpx.AsyncClient):
        payload = {
            "sim": {"player_id": "local", "save_id": "save1", "sim_id": 1},
            "message": "hello",
            "context": {},
            "lang": "en",
        }
        resp = await test_client.post("/v1/chat", json=payload)
        assert resp.status_code == 401

    async def test_chat_200_with_token(self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]):
        payload = {
            "sim": {"player_id": "local", "save_id": "save1", "sim_id": 1},
            "message": "hello",
            "context": {},
            "lang": "en",
        }
        resp = await test_client.post("/v1/chat", json=payload, headers=auth_headers)
        assert resp.status_code == 200

    async def test_chat_returns_valid_chat_response_even_without_agent(
        self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        """Chat should return a valid ChatResponse with message_key even if agent module is missing."""
        payload = {
            "sim": {"player_id": "local", "save_id": "save1", "sim_id": 1},
            "message": "hello",
            "context": {},
            "lang": "en",
        }
        resp = await test_client.post("/v1/chat", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        chat_resp = ChatResponse(**data)
        # With no provider configured the agent returns a localized system
        # message (key) instead of an LLM reply; this is native mode, not a crash.
        assert chat_resp.message_key is not None
        assert chat_resp.provider is None


class TestHeyEndpoint:
    """Tests for POST /v1/hey (auth required)."""

    async def test_hey_401_without_token(self, test_client: httpx.AsyncClient):
        payload = {
            "sim": {"player_id": "local", "save_id": "save1", "sim_id": 1},
            "context": {},
            "lang": "en",
        }
        resp = await test_client.post("/v1/hey", json=payload)
        assert resp.status_code == 401

    async def test_hey_200_with_token(self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]):
        payload = {
            "sim": {"player_id": "local", "save_id": "save1", "sim_id": 1},
            "context": {},
            "lang": "en",
        }
        resp = await test_client.post("/v1/hey", json=payload, headers=auth_headers)
        assert resp.status_code == 200

    async def test_hey_returns_valid_chat_response(
        self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        payload = {
            "sim": {"player_id": "local", "save_id": "save1", "sim_id": 1},
            "context": {},
            "lang": "en",
        }
        resp = await test_client.post("/v1/hey", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        chat_resp = ChatResponse(**data)
        assert chat_resp.message_key is not None
        assert chat_resp.provider is None


class TestToolResultEndpoint:
    """Tests for POST /v1/tools/result (auth required)."""

    async def test_tool_result_401_without_token(self, test_client: httpx.AsyncClient):
        payload = {"tool_call_id": "abc", "ok": True, "result": "done"}
        resp = await test_client.post("/v1/tools/result", json=payload)
        assert resp.status_code == 401

    async def test_tool_result_200_returns_ok(self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]):
        payload = {"tool_call_id": "abc", "ok": True, "result": "done"}
        resp = await test_client.post("/v1/tools/result", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        ack = AckResponse(**data)
        assert ack.ok is True


class TestResetEndpoint:
    """Tests for POST /v1/reset (auth required)."""

    async def test_reset_401_without_token(self, test_client: httpx.AsyncClient):
        payload = {"scope": "session", "sim": None}
        resp = await test_client.post("/v1/reset", json=payload)
        assert resp.status_code == 401

    async def test_reset_200_with_token(self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]):
        payload = {"scope": "session", "sim": None}
        resp = await test_client.post("/v1/reset", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        ack = AckResponse(**data)
        assert ack.ok is True


class TestConfigAutonomyEndpoint:
    """Tests for POST /v1/config/autonomy (auth required)."""

    async def test_config_autonomy_401_without_token(self, test_client: httpx.AsyncClient):
        payload = {"sim": {"player_id": "local", "save_id": "save1", "sim_id": 1}, "level": "semi"}
        resp = await test_client.post("/v1/config/autonomy", json=payload)
        assert resp.status_code == 401

    async def test_config_autonomy_200_with_token(self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]):
        payload = {"sim": {"player_id": "local", "save_id": "save1", "sim_id": 1}, "level": "semi"}
        resp = await test_client.post("/v1/config/autonomy", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        ack = AckResponse(**data)
        assert ack.ok is True


class TestConfigLangEndpoint:
    """Tests for POST /v1/config/lang (auth required)."""

    async def test_config_lang_401_without_token(self, test_client: httpx.AsyncClient):
        payload = {"lang": "pt-BR"}
        resp = await test_client.post("/v1/config/lang", json=payload)
        assert resp.status_code == 401

    async def test_config_lang_200_with_token(self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]):
        payload = {"lang": "pt-BR"}
        resp = await test_client.post("/v1/config/lang", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        ack = AckResponse(**data)
        assert ack.ok is True


class TestConfigGodEndpoint:
    """Tests for POST /v1/config/god (auth required)."""

    async def test_config_god_401_without_token(self, test_client: httpx.AsyncClient):
        payload = {"preset": "novela", "enabled": True}
        resp = await test_client.post("/v1/config/god", json=payload)
        assert resp.status_code == 401

    async def test_config_god_200_with_token(self, test_client: httpx.AsyncClient, auth_headers: dict[str, str]):
        payload = {"preset": "novela", "enabled": True}
        resp = await test_client.post("/v1/config/god", json=payload, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        ack = AckResponse(**data)
        assert ack.ok is True


class TestNormalizeLang:
    """Tests for the normalize_lang helper."""

    def test_normalize_en_variants(self):
        assert normalize_lang("en") == "en"
        assert normalize_lang("EN") == "en"
        assert normalize_lang("en-US") == "en"
        assert normalize_lang("en-GB") == "en"

    def test_normalize_pt_br_variants(self):
        assert normalize_lang("pt-BR") == "pt-BR"
        assert normalize_lang("pt_br") == "pt-BR"
        assert normalize_lang("ptbr") == "pt-BR"
        assert normalize_lang("pt") == "pt-BR"

    def test_normalize_unknown_fallbacks_to_en(self):
        assert normalize_lang("fr") == "en"
        assert normalize_lang("es") == "en"
        assert normalize_lang("") == "en"
        assert normalize_lang(None) == "en"

def test_port_in_use_detects_a_bound_socket():
    import socket

    from sensewright_sidecar.__main__ import _port_in_use

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        assert _port_in_use("127.0.0.1", port) is True


def test_port_in_use_false_for_free_port():
    import socket

    from sensewright_sidecar.__main__ import _port_in_use

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    # Socket closed -> the port is free again.
    assert _port_in_use("127.0.0.1", port) is False
