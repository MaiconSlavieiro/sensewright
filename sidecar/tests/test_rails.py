"""Tests for directive safety rails and new tool schemas."""

from __future__ import annotations

import time

from sims_sense_sidecar.tools.rails import (
    NEVER_TOOLS,
    DirectiveRails,
)
from sims_sense_sidecar.tools.registry import get_tool_schemas


class RecordingAudit:
    """Minimal audit double capturing record() calls."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def record(self, event: str, **fields: object) -> None:
        self.calls.append({"event": event, **fields})


def test_allowed_path() -> None:
    rails = DirectiveRails()
    decision = rails.check("sim:1", "queue_interaction")
    assert decision.allowed is True
    assert decision.reason == ""
    assert decision.tool_name == "queue_interaction"
    assert decision.sim_key == "sim:1"


def test_never_tool_denied() -> None:
    rails = DirectiveRails()
    for tool in NEVER_TOOLS:
        decision = rails.check("sim:1", tool)
        assert decision.allowed is False
        assert decision.reason == "never_tool"
        assert decision.tool_name == tool


def test_custom_never_tools_override() -> None:
    rails = DirectiveRails(never_tools={"nuke_world"})
    assert rails.check("sim:1", "nuke_world").reason == "never_tool"
    assert rails.check("sim:1", "delete_save").allowed is True


def test_player_priority_denied_with_ts_injection() -> None:
    rails = DirectiveRails(player_lock_seconds=10.0)
    now = time.monotonic()
    rails.record_player_activity("sim:1", ts=now - 2.0)
    decision = rails.check("sim:1", "queue_interaction")
    assert decision.allowed is False
    assert decision.reason == "player_priority"


def test_player_priority_expires() -> None:
    rails = DirectiveRails(player_lock_seconds=10.0)
    now = time.monotonic()
    rails.record_player_activity("sim:1", ts=now - 11.0)
    assert rails.check("sim:1", "queue_interaction").allowed is True


def test_rate_limited_after_max_per_minute() -> None:
    rails = DirectiveRails(max_per_minute=3)
    now = time.monotonic()
    for offset in range(3):
        rails.note_executed("sim:1", "queue_interaction", ts=now + offset * 0.001)
    decision = rails.check("sim:1", "queue_interaction")
    assert decision.allowed is False
    assert decision.reason == "rate_limited"


def test_rate_limit_is_per_sim() -> None:
    rails = DirectiveRails(max_per_minute=1)
    now = time.monotonic()
    rails.note_executed("sim:1", "queue_interaction", ts=now)
    assert rails.check("sim:1", "queue_interaction").allowed is False
    assert rails.check("sim:2", "queue_interaction").allowed is True


def test_window_expiry_allows_again() -> None:
    rails = DirectiveRails(max_per_minute=1)
    now = time.monotonic()
    rails.note_executed("sim:1", "queue_interaction", ts=now - 61.0)
    assert rails.check("sim:1", "queue_interaction").allowed is True


def test_note_executed_trims_stale_entries() -> None:
    rails = DirectiveRails(max_per_minute=2)
    now = time.monotonic()
    rails.note_executed("sim:1", "queue_interaction", ts=now - 120.0)
    rails.note_executed("sim:1", "queue_interaction", ts=now)
    state = rails.snapshot()["sims"]["sim:1"]
    assert state["executed_in_window"] == 1


def test_audit_record_called_for_each_check() -> None:
    audit = RecordingAudit()
    rails = DirectiveRails(max_per_minute=10, audit=audit)
    rails.check("sim:1", "queue_interaction")
    rails.check("sim:1", "delete_save")
    assert len(audit.calls) == 2
    assert audit.calls[0] == {
        "event": "tool_check",
        "sim": "sim:1",
        "tool": "queue_interaction",
        "allowed": True,
        "reason": "",
    }
    assert audit.calls[1]["reason"] == "never_tool"
    assert audit.calls[1]["allowed"] is False


def test_snapshot_shape() -> None:
    rails = DirectiveRails(max_per_minute=5, player_lock_seconds=7.5)
    now = time.monotonic()
    rails.record_player_activity("sim:1", ts=now)
    rails.note_executed("sim:1", "queue_interaction", ts=now)
    snap = rails.snapshot()
    assert snap["max_per_minute"] == 5
    assert snap["player_lock_seconds"] == 7.5
    assert snap["never_tools"] == sorted(NEVER_TOOLS)
    assert snap["sims"]["sim:1"]["executed_in_window"] == 1
    assert snap["sims"]["sim:1"]["last_player_activity"] == now


def test_reset_single_sim() -> None:
    rails = DirectiveRails()
    now = time.monotonic()
    rails.note_executed("sim:1", "queue_interaction", ts=now)
    rails.record_player_activity("sim:1", ts=now)
    rails.note_executed("sim:2", "queue_interaction", ts=now)
    rails.reset("sim:1")
    snap = rails.snapshot()
    assert "sim:1" not in snap["sims"]
    assert "sim:2" in snap["sims"]


def test_reset_all() -> None:
    rails = DirectiveRails()
    now = time.monotonic()
    rails.note_executed("sim:1", "queue_interaction", ts=now)
    rails.record_player_activity("sim:2", ts=now)
    rails.reset()
    assert rails.snapshot()["sims"] == {}


def test_add_buff_and_add_trait_schemas() -> None:
    semi = get_tool_schemas("semi")
    full = get_tool_schemas("full")
    observe = get_tool_schemas("observe")
    for name in ("add_buff", "add_trait"):
        assert name in semi
        assert name in full
        assert name not in observe


def test_new_schemas_required_params() -> None:
    for name, required in (
        ("add_buff", ["buff_name", "reason"]),
        ("add_trait", ["trait_name", "reason"]),
    ):
        schema = get_tool_schemas("full")[name]
        assert schema["type"] == "function"
        assert schema["function"]["name"] == name
        assert schema["function"]["parameters"]["required"] == required
