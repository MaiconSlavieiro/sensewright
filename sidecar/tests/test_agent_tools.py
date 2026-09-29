"""Tests for agent tool-call gating, pending results, and event ingestion."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sims_sense_sidecar.agent import graph
from sims_sense_sidecar.agent.nodes import AgentNodes
from sims_sense_sidecar.config import AgentsConfig, LLMConfig, MemoryConfig, Settings
from sims_sense_sidecar.llm.base import LLMResponse, LLMToolCall
from sims_sense_sidecar.memory.base import MemKey
from sims_sense_sidecar.schemas import EventRecord, SimRef, ToolResultRequest
from sims_sense_sidecar.tools.rails import DirectiveRails


class FakeMemory:
    """Minimal in-memory stand-in for the MemoryStore protocol."""

    def __init__(self) -> None:
        self.events: list[dict] = []
        self.profiles: dict[str, dict] = {}

    async def get_profile(self, key: MemKey) -> dict | None:
        return self.profiles.get(str(key))

    async def upsert_profile(self, key: MemKey, profile: dict) -> None:
        self.profiles[str(key)] = profile

    async def add_event(self, key: MemKey, event: dict) -> int:
        self.events.append({"key": str(key), **event})
        return len(self.events)

    async def recent_events(self, key: MemKey, limit: int = 50) -> list[dict]:
        return []

    async def search_events(self, key: MemKey, query: str, limit: int = 10) -> list[dict]:
        return []

    async def reset(self, scope: str, key: MemKey | None) -> dict:
        return {}

    async def stats(self) -> dict:
        return {}

    async def close(self) -> None:
        return None


class FakeRegistry:
    """Registry that returns a canned LLMResponse and records the tools passed."""

    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.last_tools = "unset"

    async def complete(
        self,
        messages,
        *,
        lang=None,
        temperature=None,
        max_tokens=None,
        tools=None,
    ) -> LLMResponse:
        self.last_tools = tools
        return self.response


def make_nodes(
    response: LLMResponse | None = None,
    rails: DirectiveRails | None = None,
) -> tuple[AgentNodes, FakeMemory]:
    response = response or LLMResponse(
        text="",
        provider="fake",
        model="fake-1",
        raw={},
        tool_calls=(
            LLMToolCall(id="c1", name="add_buff", arguments={"buff_name": "happy"}),
        ),
    )
    memory = FakeMemory()
    nodes = AgentNodes(
        registry=FakeRegistry(response),
        memory=memory,
        default_autonomy="semi",
        default_lang="en",
        rails=rails,
    )
    return nodes, memory


def make_persist_result(nodes: AgentNodes, response: LLMResponse, sim_key: str) -> dict:
    state = nodes._get_state(sim_key)
    mem_key = nodes._mem_key_from_sim_key(sim_key)
    return {
        "state": state,
        "mem_key": mem_key,
        "llm_response": response,
        "lang": "en",
    }


async def test_format_response_returns_allowed_tool_calls_and_pending():
    nodes, _memory = make_nodes()
    sim_key = "local:save1:123"
    persist = make_persist_result(nodes, nodes.registry.response, sim_key)

    response = await nodes.format_response_node(persist)

    assert len(response.tool_calls) == 1
    assert response.tool_calls[0].name == "add_buff"
    assert response.tool_calls[0].args == {"buff_name": "happy"}
    state = persist["state"]
    assert len(state.pending_tool_calls) == 1
    assert state.pending_tool_calls[0]["id"] == "c1"


async def test_never_tool_is_denied_in_character():
    rails = DirectiveRails()
    response = LLMResponse(
        text="",
        provider="fake",
        model="fake-1",
        raw={},
        tool_calls=(LLMToolCall(id="c9", name="delete_save", arguments={}),),
    )
    nodes, memory = make_nodes(response=response, rails=rails)
    sim_key = "local:save1:123"
    persist = make_persist_result(nodes, response, sim_key)

    result = await nodes.format_response_node(persist)

    assert result.tool_calls == []
    assert result.message_key == "error.directive_denied"
    assert any(e["type"] == "directive_denied" for e in memory.events)
    assert persist["state"].pending_tool_calls == []


async def test_player_priority_lock_denies_directives():
    rails = DirectiveRails(player_lock_seconds=10.0)
    nodes, _memory = make_nodes(rails=rails)
    sim_key = "local:save1:123"
    rails.record_player_activity(sim_key)

    persist = make_persist_result(nodes, nodes.registry.response, sim_key)
    result = await nodes.format_response_node(persist)

    assert result.tool_calls == []
    assert result.message_key == "error.directive_denied"


async def test_rate_limit_denies_after_budget():
    rails = DirectiveRails(max_per_minute=1)
    nodes, _memory = make_nodes(rails=rails)
    sim_key = "local:save1:123"
    rails.note_executed(sim_key, "add_buff")

    persist = make_persist_result(nodes, nodes.registry.response, sim_key)
    result = await nodes.format_response_node(persist)

    assert result.tool_calls == []


async def test_handle_tool_result_resolves_and_records():
    nodes, memory = make_nodes()
    sim_key = "local:save1:123"
    state = nodes._get_state(sim_key)
    state.set_pending_tool_calls([{"id": "c1", "name": "add_buff", "args": {}, "status": "pending"}])

    result = await nodes.handle_tool_result(
        ToolResultRequest(tool_call_id="c1", ok=True, result={"ok": True})
    )

    assert result["resolved"] is True
    assert state.pending_tool_calls == []
    assert state.tool_results[0]["ok"] is True
    assert any(e["type"] == "tool_result" for e in memory.events)


async def test_handle_tool_result_unknown_id_is_tolerated():
    nodes, _memory = make_nodes()
    result = await nodes.handle_tool_result(
        ToolResultRequest(tool_call_id="nope", ok=False, error="boom")
    )
    assert result["ok"] is True
    assert result["resolved"] is False


async def test_llm_node_forwards_tool_schemas():
    nodes, _memory = make_nodes()
    prompt_result = {
        "messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "hi"}],
        "lang": "en",
        "tools": [{"type": "function", "function": {"name": "get_needs"}}],
    }

    result = await nodes.llm_node(prompt_result)

    assert result["error"] is None
    assert nodes.registry.last_tools == [{"type": "function", "function": {"name": "get_needs"}}]


@pytest.fixture
def graph_settings() -> Settings:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = Settings(
            home=tmp_path,
            llm=LLMConfig(chain=[], providers={}),
            memory=MemoryConfig(provider="sqlite", embedding_provider="none"),
            agents=AgentsConfig(autonomy_default="semi"),
            lang="en",
        )
        yield settings


async def test_graph_ingest_events_arms_player_lock(graph_settings: Settings):
    graph.configure(graph_settings)
    sim = SimRef(player_id="local", save_id="save1", sim_id=42)
    event = EventRecord(sim=sim, type="player_interaction", content={"action": "click"})

    result = await graph.ingest_events([event])

    assert result["ok"] is True
    assert result["ingested"] == 1
    rails_snapshot = graph.status()["rails"]
    assert "local:save1:42" in rails_snapshot["sims"]

    await graph.shutdown()


async def test_graph_record_player_activity(graph_settings: Settings):
    graph.configure(graph_settings)
    sim = SimRef(player_id="local", save_id="save1", sim_id=7)

    result = graph.record_player_activity(sim)

    assert result["ok"] is True
    assert "local:save1:7" in graph.status()["rails"]["sims"]

    await graph.shutdown()
