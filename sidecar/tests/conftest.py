"""Pytest fixtures for sidecar tests."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from sims_sense_sidecar.auth import ensure_token
from sims_sense_sidecar.config import (
    AgentsConfig,
    GodConfig,
    LLMConfig,
    LoggingConfig,
    MemoryConfig,
    NetworkConfig,
    Settings,
    UiConfig,
)
from sims_sense_sidecar.server import create_app


@pytest.fixture
def tmp_home(tmp_path: Path) -> Path:
    """Temporary home directory for tests."""
    home = tmp_path / "sims_sense_home"
    home.mkdir(parents=True, exist_ok=True)
    (home / "data").mkdir(exist_ok=True)
    return home


@pytest.fixture
def settings(tmp_home: Path) -> Settings:
    """Settings instance with temporary home."""
    return Settings(
        home=tmp_home,
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
def token(settings: Settings) -> str:
    """Generate a token for the test settings."""
    return ensure_token(settings)


@pytest.fixture
def app(settings: Settings, token: str):
    """FastAPI app instance for testing."""
    return create_app(settings, token)


@pytest.fixture
async def client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def auth_headers(token: str) -> dict[str, str]:
    """Authorization headers with valid token."""
    return {"X-SimsSense-Token": token}