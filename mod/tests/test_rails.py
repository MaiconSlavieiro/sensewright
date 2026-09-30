"""
Tests for the mod-side DirectiveRails.
Fully offline; no game imports required.
Run with the system Python (3.10+).
"""

import os
import sys
import time

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest
from sensewright_mod.rails import (
    NEVER_TOOLS,
    DirectiveRails,
    RailDecision,
)


def test_never_tools_contract():
    assert NEVER_TOOLS == frozenset({
        "delete_save", "modify_money", "kill_sim", "spawn_npc_unbounded",
    })


def test_never_tools_excludes_non_registry_entries():
    # Review L9: "shell"/"http" are not real tools and were removed.
    assert "shell" not in NEVER_TOOLS
    assert "http" not in NEVER_TOOLS


def test_check_allows_normally():
    rails = DirectiveRails()
    decision = rails.check(1, "add_buff")

    assert isinstance(decision, RailDecision)
    assert decision.allowed is True
    assert decision.reason == ""
    assert decision.tool_name == "add_buff"
    assert decision.sim_id == 1


def test_check_denies_never_tool():
    rails = DirectiveRails()
    decision = rails.check(1, "kill_sim")

    assert decision.allowed is False
    assert decision.reason == "never_tool"


def test_player_priority_lock_blocks_then_expires():
    rails = DirectiveRails(player_lock_seconds=10.0)
    rails.record_player_activity(1)

    blocked = rails.check(1, "add_buff")
    assert blocked.allowed is False
    assert blocked.reason == "player_priority"

    # Simulate that the player activity is old (outside the lock window).
    rails.record_player_activity(1, ts=time.monotonic() - 100.0)
    allowed = rails.check(1, "add_buff")
    assert allowed.allowed is True
    assert allowed.reason == ""


def test_player_priority_is_per_sim():
    rails = DirectiveRails()
    rails.record_player_activity(1)

    assert rails.check(1, "add_buff").reason == "player_priority"
    assert rails.check(2, "add_buff").allowed is True


def test_rate_limited_after_max_per_minute():
    rails = DirectiveRails(max_per_minute=2)
    rails.note_executed(1, "add_buff")
    rails.note_executed(1, "add_buff")

    decision = rails.check(1, "add_buff")
    assert decision.allowed is False
    assert decision.reason == "rate_limited"


def test_rate_limit_window_trims_old_entries():
    rails = DirectiveRails(max_per_minute=1)
    rails.note_executed(1, "add_buff", ts=time.monotonic() - 120.0)

    decision = rails.check(1, "add_buff")
    assert decision.allowed is True


def test_reset_single_sim():
    rails = DirectiveRails()
    rails.note_executed(1, "add_buff")
    rails.note_executed(2, "add_buff")

    rails.reset(1)

    assert rails.check(1, "add_buff").allowed is True
    assert rails.check(2, "add_buff").allowed is True
    snapshot = rails.snapshot()
    assert "1" not in snapshot["sims"]
    assert "2" in snapshot["sims"]


def test_reset_all_sims():
    rails = DirectiveRails()
    rails.note_executed(1, "add_buff")
    rails.record_player_activity(2)

    rails.reset()

    assert rails.snapshot()["sims"] == {}


def test_snapshot_structure():
    rails = DirectiveRails(max_per_minute=7, player_lock_seconds=3.0)
    rails.note_executed(42, "add_buff")

    snapshot = rails.snapshot()

    assert snapshot["max_per_minute"] == 7
    assert snapshot["player_lock_seconds"] == 3.0
    assert snapshot["never_tools"] == sorted(NEVER_TOOLS)
    assert snapshot["sims"]["42"]["executed_in_window"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
