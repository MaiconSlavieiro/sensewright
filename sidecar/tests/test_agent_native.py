"""Tests for agent graph in native (no LLM) mode."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sims_sense_sidecar.agent import graph
from sims_sense_sidecar.config import AgentsConfig, LLMConfig, MemoryConfig, Settings
from sims_sense_sidecar.schemas import ChatRequest, HeyRequest, SimRef


def make_test_settings_no_llm(tmp_path: Path) -> Settings:
    """Create a test Settings object with NO provider keys."""
    return Settings(
        home=tmp_path,
        data_dir=tmp_path / "data",
        llm=LLMConfig(
            chain=[],  # No providers in chain
            providers={},  # No provider configs
        ),
        memory=MemoryConfig(provider="sqlite", embedding_provider="none"),
        agents=AgentsConfig(autonomy_default="semi"),
        lang="en",
    )


@pytest.fixture
def temp_settings():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        settings = make_test_settings_no_llm(tmp_path)
        yield settings
        # Cleanup: shutdown the graph to close DB connections
        import asyncio
        try:
            asyncio.run(graph.shutdown())
        except Exception:
            pass


@pytest.mark.asyncio
async def test_handle_chat_returns_native_fallback(temp_settings):
    """Test handle_chat returns notify.no_llm_native when no providers configured."""
    graph.configure(temp_settings)

    req = ChatRequest(
        sim=SimRef(player_id="player1", save_id="save1", sim_id=123),
        message="Hello, how are you?",
        context={"mood": "happy", "needs": {"hunger": 50}},
        lang="en",
    )

    response = await graph.handle_chat(req)

    assert response.reply == ""
    assert response.provider is None
    assert response.model is None
    assert response.message_key == "notify.no_llm_native"
    assert response.message_args == {}


@pytest.mark.asyncio
async def test_handle_hey_returns_native_fallback(temp_settings):
    """Test handle_hey returns notify.no_llm_native when no providers configured."""
    graph.configure(temp_settings)

    req = HeyRequest(
        sim=SimRef(player_id="player1", save_id="save1", sim_id=123),
        context={"mood": "happy", "world_time": "10:00"},
        lang="en",
    )

    response = await graph.handle_hey(req)

    assert response.reply == ""
    assert response.provider is None
    assert response.model is None
    assert response.message_key == "notify.no_llm_native"
    assert response.message_args == {}


@pytest.mark.asyncio
async def test_handle_chat_with_pt_br_lang(temp_settings):
    """Test handle_chat respects pt-BR language."""
    graph.configure(temp_settings)

    req = ChatRequest(
        sim=SimRef(player_id="player1", save_id="save1", sim_id=123),
        message="Olá!",
        context={},
        lang="pt-BR",
    )

    response = await graph.handle_chat(req)

    assert response.message_key == "notify.no_llm_native"


@pytest.mark.asyncio
async def test_status_returns_dict(temp_settings):
    """Test status() returns a dict with expected keys."""
    graph.configure(temp_settings)

    status = graph.status()

    assert isinstance(status, dict)
    assert "lang" in status
    assert "autonomy_default" in status
    assert "providers" in status
    assert "memory" in status
    assert "god" in status


@pytest.mark.asyncio
async def test_reset_session_scope(temp_settings):
    """Test reset with session scope (no-op for persistent store)."""
    graph.configure(temp_settings)

    result = await graph.reset("session", None)

    assert result["ok"] is True
    assert "deleted" in result


@pytest.mark.asyncio
async def test_reset_sim_scope(temp_settings):
    """Test reset with sim scope."""
    graph.configure(temp_settings)

    sim = SimRef(player_id="player1", save_id="save1", sim_id=123)
    result = await graph.reset("sim", sim)

    assert result["ok"] is True
    assert "deleted" in result


@pytest.mark.asyncio
async def test_set_autonomy_valid(temp_settings):
    """Test set_autonomy with valid level."""
    graph.configure(temp_settings)

    sim = SimRef(player_id="player1", save_id="save1", sim_id=123)
    result = await graph.set_autonomy(sim, "full")

    assert result["ok"] is True
    assert result["autonomy"] == "full"


@pytest.mark.asyncio
async def test_set_autonomy_invalid(temp_settings):
    """Test set_autonomy with invalid level."""
    graph.configure(temp_settings)

    sim = SimRef(player_id="player1", save_id="save1", sim_id=123)
    result = await graph.set_autonomy(sim, "invalid_level")

    assert result["ok"] is False
    assert "error" in result


@pytest.mark.asyncio
async def test_set_lang_valid(temp_settings):
    """Test set_lang with valid language."""
    graph.configure(temp_settings)

    result = graph.set_lang("pt-BR")

    assert result["ok"] is True
    assert result["lang"] == "pt-BR"


@pytest.mark.asyncio
async def test_set_lang_invalid(temp_settings):
    """Test set_lang with invalid language - fr-FR normalizes to en which is supported."""
    graph.configure(temp_settings)

    # fr-FR normalizes to "en" (DEFAULT_LANG) which IS supported
    result = graph.set_lang("fr-FR")
    assert result["ok"] is True
    assert result["lang"] == "en"

    # Test with empty string - also normalizes to "en"
    result = graph.set_lang("")
    assert result["ok"] is True
    assert result["lang"] == "en"


@pytest.mark.asyncio
async def test_handle_tool_result(temp_settings):
    """Test handle_tool_result returns ok."""
    graph.configure(temp_settings)

    from sims_sense_sidecar.schemas import ToolResultRequest
    req = ToolResultRequest(tool_call_id="test-123", ok=True, result={"success": True})

    result = await graph.handle_tool_result(req)

    assert result["ok"] is True


@pytest.mark.asyncio
async def test_configure_idempotent(temp_settings):
    """Test configure can be called multiple times."""
    graph.configure(temp_settings)
    graph.configure(temp_settings)  # Should not raise

    status = graph.status()
    assert isinstance(status, dict)


@pytest.mark.asyncio
async def test_shutdown(temp_settings):
    """Test shutdown cleans up."""
    graph.configure(temp_settings)
    await graph.shutdown()

    # After shutdown, status should still work but show uninitialized
    status = graph.status()
    assert isinstance(status, dict)