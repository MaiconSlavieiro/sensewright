"""Tests for sensewright_sidecar.agent.impulse module."""
from __future__ import annotations

import pytest

from sensewright_sidecar.agent.impulse import (
    has_critical_need,
    duty_imminent,
    physical_actions_allowed,
    build_impulse_context,
    build_reaction_context,
)
from sensewright_sidecar.agent.impulse import CRITICAL_NEED_THRESHOLD, DUTY_GUARD_MINUTES


class TestHasCriticalNeed:
    """Tests for has_critical_need."""

    def test_critical_need_detected(self):
        needs = {"hunger": -80, "energy": -50}
        assert has_critical_need(needs) is True

    def test_no_critical_need(self):
        needs = {"hunger": -50, "energy": -30}
        assert has_critical_need(needs) is False

    def test_exact_threshold_not_critical(self):
        needs = {"hunger": -70}  # Exactly at threshold
        assert has_critical_need(needs) is False

    def test_below_threshold_critical(self):
        needs = {"hunger": -71}
        assert has_critical_need(needs) is True

    def test_empty_needs(self):
        assert has_critical_need({}) is False

    def test_none_needs(self):
        assert has_critical_need(None) is False

    def test_non_dict_needs(self):
        assert has_critical_need("not a dict") is False

    def test_invalid_values_ignored(self):
        needs = {"hunger": "invalid", "energy": -80}
        assert has_critical_need(needs) is True


class TestDutyImminent:
    """Tests for duty_imminent."""

    def test_duty_within_guard_minutes(self):
        schedule = [{"start_tick": 145}]  # 45 minutes from tick 100
        assert duty_imminent(schedule, 100) is True

    def test_duty_at_guard_boundary(self):
        schedule = [{"start_tick": 145}]  # Exactly 45 minutes
        assert duty_imminent(schedule, 100) is True

    def test_duty_outside_guard_minutes(self):
        schedule = [{"start_tick": 146}]  # 46 minutes
        assert duty_imminent(schedule, 100) is False

    def test_duty_in_past(self):
        schedule = [{"start_tick": 50}]  # Already started
        assert duty_imminent(schedule, 100) is False

    def test_no_schedule_blocks(self):
        assert duty_imminent([], 100) is False
        assert duty_imminent(None, 100) is False

    def test_invalid_block_ignored(self):
        schedule = [{"start_tick": "invalid"}, {"start_tick": 145}]
        assert duty_imminent(schedule, 100) is True

    def test_missing_start_tick_ignored(self):
        schedule = [{"other": 145}, {"start_tick": 145}]
        assert duty_imminent(schedule, 100) is True


class TestPhysicalActionsAllowed:
    """Tests for physical_actions_allowed."""

    def test_allowed_when_no_critical_need_no_duty(self):
        needs = {"hunger": -50}
        schedule = [{"start_tick": 200}]
        assert physical_actions_allowed(needs, schedule, 100) is True

    def test_forbidden_when_critical_need(self):
        needs = {"hunger": -80}
        schedule = []
        assert physical_actions_allowed(needs, schedule, 100) is False

    def test_forbidden_when_duty_imminent(self):
        needs = {"hunger": -50}
        schedule = [{"start_tick": 145}]
        assert physical_actions_allowed(needs, schedule, 100) is False

    def test_forbidden_when_both(self):
        needs = {"hunger": -80}
        schedule = [{"start_tick": 145}]
        assert physical_actions_allowed(needs, schedule, 100) is False


class TestBuildImpulseContext:
    """Tests for build_impulse_context."""

    def test_returns_expected_keys(self):
        ctx = build_impulse_context(
            sim_id=1,
            sim_name="Test",
            tier="full",
            mood="happy",
            activity="idle",
            needs={"hunger": -10},
            is_off_lot_duty=False,
            is_sleeping=False,
            tick=100,
        )
        expected_keys = {
            "sim_id", "sim_name", "tier", "mood", "activity",
            "current_needs", "is_off_lot_duty", "is_sleeping",
            "physical_actions_allowed", "world_sim_tick"
        }
        assert set(ctx.keys()) == expected_keys

    def test_physical_actions_allowed_computed(self):
        ctx = build_impulse_context(
            sim_id=1, sim_name="Test", tier="full", mood="happy",
            activity="idle", needs={"hunger": -80},  # Critical need
            is_off_lot_duty=False, is_sleeping=False, tick=100
        )
        assert ctx["physical_actions_allowed"] is False

    def test_all_values_passed_through(self):
        ctx = build_impulse_context(
            sim_id=42, sim_name="Bob", tier="reactive", mood="sad",
            activity="reading", needs={"energy": -20},
            is_off_lot_duty=True, is_sleeping=True, tick=500
        )
        assert ctx["sim_id"] == 42
        assert ctx["sim_name"] == "Bob"
        assert ctx["tier"] == "reactive"
        assert ctx["mood"] == "sad"
        assert ctx["activity"] == "reading"
        assert ctx["current_needs"] == {"energy": -20}
        assert ctx["is_off_lot_duty"] is True
        assert ctx["is_sleeping"] is True
        assert ctx["world_sim_tick"] == 500


class TestBuildReactionContext:
    """Tests for build_reaction_context."""

    def test_returns_expected_keys(self):
        ctx = build_reaction_context(
            sim_id=1, sim_name="Test", target_sim_id=2, target_name="Target",
            event_category="death", impact=1.0, salience=3.5, tick=100
        )
        expected_keys = {
            "sim_id", "sim_name", "target_sim_id", "target_name",
            "event_category", "impact", "salience", "world_sim_tick"
        }
        assert set(ctx.keys()) == expected_keys

    def test_none_target_sim_id(self):
        ctx = build_reaction_context(
            sim_id=1, sim_name="Test", target_sim_id=None, target_name="",
            event_category="fire", impact=0.5, salience=2.5, tick=100
        )
        assert ctx["target_sim_id"] is None

    def test_all_values_passed_through(self):
        ctx = build_reaction_context(
            sim_id=5, sim_name="Alice", target_sim_id=6, target_name="Bob",
            event_category="betrayal", impact=2.0, salience=4.2, tick=999
        )
        assert ctx["sim_id"] == 5
        assert ctx["sim_name"] == "Alice"
        assert ctx["target_sim_id"] == 6
        assert ctx["target_name"] == "Bob"
        assert ctx["event_category"] == "betrayal"
        assert ctx["impact"] == 2.0
        assert ctx["salience"] == 4.2
        assert ctx["world_sim_tick"] == 999


if __name__ == "__main__":
    pytest.main([__file__, "-v"])