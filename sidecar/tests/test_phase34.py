"""Tests for Phase 3 (profiles, chat budget) and Phase 4 (evolution) wiring."""

from __future__ import annotations

import tempfile
from pathlib import Path

import httpx
import pytest

from sensewright_sidecar.agent import graph
from sensewright_sidecar.config import (
    AgentsConfig,
    EvolutionConfig,
    LLMConfig,
    MemoryConfig,
    Settings,
)
from sensewright_sidecar.llm.budgeter import ChatBudgeter
from sensewright_sidecar.schemas import (
    EventIngestRequest,
    EventRecord,
    EvolveRequest,
    ProfileRequest,
    SimRef,
)

SIM = SimRef(player_id="local", save_id="save1", sim_id=10, household_id=5)


@pytest.fixture
async def agent_settings():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            home=Path(tmp),
            llm=LLMConfig(chain=[], providers={}, budget_per_sim_per_day=2),
            memory=MemoryConfig(provider="sqlite", embedding_provider="none"),
            agents=AgentsConfig(
                autonomy_default="semi",
                evolution=EvolutionConfig(enabled=True, min_events=2, cooldown_seconds=0.0),
            ),
            lang="en",
        )
        graph.configure(settings)
        yield settings
        try:
            await graph.shutdown()
        except Exception:
            pass


async def test_generate_profile_and_cache(agent_settings):
    req = ProfileRequest(sim=SIM, seed="nosy neighbor who envies my Sim", lang="en")

    first = await graph.generate_profile(req)
    assert first["ok"] is True
    assert first["cached"] is False
    assert first["profile"]["source"] == "template"
    assert first["profile"]["backstory"]

    second = await graph.generate_profile(req)
    assert second["cached"] is True
    assert second["profile"] == first["profile"]


async def test_evolve_reflects_and_drifts(agent_settings):
    events = [
        EventRecord(
            sim=SIM,
            type="chat",
            content={"message": f"event {i}"},
            importance=1.0,
        )
        for i in range(4)
    ]
    await graph.ingest_events(EventIngestRequest(events=events).events)

    result = await graph.evolve(EvolveRequest(sim=SIM, scope="sim", force=True))

    assert result["ok"] is True
    assert result["reflected"] == 1
    assert result["results"][0]["source"] == "template"


async def test_evolve_disabled(agent_settings):
    agent_settings.agents.evolution.enabled = False
    graph.configure(agent_settings)

    result = await graph.evolve(EvolveRequest(sim=SIM, scope="sim", force=True))
    assert result["ok"] is True
    assert result["reflected"] == 0
    assert result["message_key"] == "evolve.disabled"


async def test_evolve_save_scope(agent_settings):
    await graph.generate_profile(ProfileRequest(sim=SIM, seed="a curious neighbor", lang="en"))
    await graph.ingest_events(
        EventIngestRequest(
            events=[EventRecord(sim=SIM, type="chat", content={"message": "hi"})]
        ).events
    )

    result = await graph.evolve(EvolveRequest(sim=SIM, scope="save", force=True))
    assert result["ok"] is True
    assert result["reflected"] >= 1


async def test_chat_budget_blocks_when_exhausted(agent_settings, monkeypatch):
    graph._chat_budget = ChatBudgeter(per_sim_per_day=1)
    monkeypatch.setattr(graph, "_effective_registry", lambda: object())

    from sensewright_sidecar.schemas import ChatRequest

    first = await graph.handle_chat(ChatRequest(sim=SIM, message="hello", lang="en"))
    second = await graph.handle_chat(ChatRequest(sim=SIM, message="again", lang="en"))

    assert first.message_key != "error.budget_exhausted"
    assert second.message_key == "error.budget_exhausted"


def test_chat_budgeter_limits_and_reset():
    budgeter = ChatBudgeter(per_sim_per_day=2)

    assert budgeter.try_acquire("a") is True
    assert budgeter.try_acquire("a") is True
    assert budgeter.try_acquire("a") is False
    assert budgeter.try_acquire("b") is True
    assert budgeter.remaining("a") == 0
    assert budgeter.snapshot()["per_sim_per_day"] == 2

    budgeter.reset("a")
    assert budgeter.try_acquire("a") is True


def test_chat_budgeter_unlimited():
    budgeter = ChatBudgeter(per_sim_per_day=0)
    for _ in range(100):
        assert budgeter.try_acquire("a") is True
    assert budgeter.remaining("a") is None


class TestProfileEndpoints:
    async def test_profile_401_without_token(self, client: httpx.AsyncClient):
        payload = {"sim": SIM.model_dump(), "seed": "a neighbor", "lang": "en"}
        resp = await client.post("/v1/profile", json=payload)
        assert resp.status_code == 401

    async def test_evolve_401_without_token(self, client: httpx.AsyncClient):
        payload = {"sim": SIM.model_dump(), "scope": "sim", "lang": "en"}
        resp = await client.post("/v1/evolve", json=payload)
        assert resp.status_code == 401

    async def test_profile_200(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        payload = {"sim": SIM.model_dump(), "seed": "a neighbor", "lang": "en"}
        resp = await client.post("/v1/profile", json=payload, headers=auth_headers)
        assert resp.status_code == 200

    async def test_evolve_200(self, client: httpx.AsyncClient, auth_headers: dict[str, str]):
        payload = {"sim": SIM.model_dump(), "scope": "sim", "lang": "en"}
        resp = await client.post("/v1/evolve", json=payload, headers=auth_headers)
        assert resp.status_code == 200
