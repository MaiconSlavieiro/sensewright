"""Tests for the v0.3 GameLever intent adapter and the agent roster (R3)."""

from __future__ import annotations

import pytest

from simssense_mod import god_ui, http_client, tool_executor


@pytest.fixture(autouse=True)
def _no_post(monkeypatch):
    """Never touch the network: results are posted best-effort."""
    monkeypatch.setattr(tool_executor, "post_json", lambda *a, **k: {"ok": True})


def _intent(**overrides):
    base = {
        "id": "i1",
        "sim_id": 1,
        "kind": "speak",
        "target_sim_id": None,
        "params": {"text": "Hello"},
        "reason": "",
        "expires_at": "next_sleep",
        "priority": 0,
        "source": "agent",
        "name": "",
        "args": {},
        "thought": "",
        "narration": "",
    }
    base.update(overrides)
    return base


def test_execute_intent_speak_without_target_surfaces_text():
    result = tool_executor.execute_intent(_intent(kind="speak"))

    assert result["ok"] is True
    assert result["text"] == "Hello"


def test_execute_intent_speak_with_target_falls_back_to_line(monkeypatch):
    # Outside the game the native social push is unavailable, so a targeted
    # speak intent must degrade to a surfaced line (never a silent no-op).
    def _no_native(_args):
        return {"ok": False, "error": "not_implemented"}

    monkeypatch.setattr(tool_executor, "tool_say_to", _no_native)

    result = tool_executor.execute_intent(
        _intent(kind="speak", target_sim_id=2, params={"message": "Hi you"})
    )

    assert result["ok"] is True
    assert result["text"] == "Hi you"
    assert result["native_error"] == "not_implemented"


def test_execute_intent_bias_falls_back_to_ack(monkeypatch):
    monkeypatch.setattr(
        tool_executor,
        "tool_queue_interaction",
        lambda _args: {"ok": False, "error": "not_implemented"},
    )

    result = tool_executor.execute_intent(_intent(kind="bias_interaction", sim_id=1))

    assert result["ok"] is True
    assert result["result"]["applied"] is False
    assert result["result"]["native_error"] == "not_implemented"


def test_execute_intent_ack_kinds_degrade_gracefully():
    for kind in ("prefer_target", "set_goal", "remember", "forget"):
        result = tool_executor.execute_intent(_intent(kind=kind))
        assert result["ok"] is True
        assert result["result"]["applied"] is False


def test_execute_intent_command_escape_hatch_delegates():
    result = tool_executor.execute_intent(
        _intent(kind="command", name="spontaneous_line", params={"text": "Hi there"})
    )

    assert result["ok"] is True
    assert result["text"] == "Hi there"


def test_execute_intent_unknown_command_is_reported():
    result = tool_executor.execute_intent(
        _intent(kind="command", name="does_not_exist", params={})
    )

    assert result["ok"] is False
    assert result["error"] == "unknown_tool"


def test_execute_intent_unknown_kind_without_command():
    result = tool_executor.execute_intent(_intent(kind="bogus", name=""))

    assert result["ok"] is False
    assert result["error"] == "unknown_intent"


def test_execute_intent_rejects_non_mapping():
    assert tool_executor.execute_intent("nope")["error"] == "bad_intent"


def test_intent_args_prefers_params_and_injects_sim_id():
    args = tool_executor._intent_args(_intent(params={"mood": "happy"}))

    assert args["sim_id"] == 1
    assert args["mood"] == "happy"


def test_format_roster_renders_agents():
    roster = {
        "seats": 2,
        "used": 2,
        "agents": [
            {"sim_id": 1, "tier": "household", "is_player": True, "impulse_frequency": None},
            {"sim_id": 2, "tier": "visitor", "is_player": False, "impulse_frequency": 0.4},
        ],
    }

    text = god_ui.format_roster(roster)

    assert "1 [household]" in text
    assert "*" in text
    assert "2 [visitor]" in text
    assert "0.4" in text


def test_format_roster_handles_empty():
    assert god_ui.format_roster({}) == ""
    assert god_ui.format_roster(None) == ""
