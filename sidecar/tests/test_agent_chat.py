"""Tests for sensewright_sidecar.agent.chat module."""
from __future__ import annotations

import pytest

from sensewright_sidecar.agent.chat import (
    trust_level,
    trust_delta,
    is_deferred,
    extract_thought,
    strip_thought,
    build_chat_context,
    family_relation_label,
)
from sensewright_sidecar.agent.chat import TRUST_ACQUAINTANCE, TRUST_CONFIDANT


class TestTrustLevel:
    """Tests for trust_level."""

    def test_acquaintance(self):
        assert trust_level(0) == 1
        assert trust_level(24) == 1
        assert trust_level(25) == 2  # Boundary

    def test_confidant(self):
        assert trust_level(25) == 2
        assert trust_level(64) == 2
        assert trust_level(65) == 3  # Boundary

    def test_advisor_soulmate(self):
        assert trust_level(65) == 3
        assert trust_level(100) == 3

    def test_float_input(self):
        assert trust_level(25.0) == 2
        assert trust_level(64.9) == 2
        assert trust_level(65.0) == 3


class TestTrustDelta:
    """Tests for trust_delta."""

    def test_positive_sentiment(self):
        assert trust_delta(1.0) == 1.0
        assert trust_delta(2.0) == 2.0

    def test_negative_sentiment(self):
        assert trust_delta(-1.0) == -1.0
        assert trust_delta(-2.0) == -2.0

    def test_clamped_at_2(self):
        assert trust_delta(5.0) == 2.0
        assert trust_delta(-5.0) == -2.0

    def test_invalid_input_returns_zero(self):
        assert trust_delta("invalid") == 0.0
        assert trust_delta(None) == 0.0


class TestIsDeferred:
    """Tests for is_deferred."""

    def test_phone_sms_sleeping_deferred(self):
        sim = {"is_sleeping": True}
        assert is_deferred(sim, "phone_sms") is True

    def test_phone_sms_off_lot_deferred(self):
        sim = {"is_off_lot_duty": True}
        assert is_deferred(sim, "phone_sms") is True

    def test_phone_sms_awake_on_lot_not_deferred(self):
        sim = {"is_sleeping": False, "is_off_lot_duty": False}
        assert is_deferred(sim, "phone_sms") is False

    def test_pc_chat_never_deferred(self):
        sim = {"is_sleeping": True, "is_off_lot_duty": True}
        assert is_deferred(sim, "pc_chat") is False

    def test_pc_email_never_deferred(self):
        sim = {"is_sleeping": True, "is_off_lot_duty": True}
        assert is_deferred(sim, "pc_email") is False

    def test_missing_keys_defaults_false(self):
        sim = {}
        assert is_deferred(sim, "phone_sms") is False


class TestExtractThought:
    """Tests for extract_thought."""

    def test_extracts_thought_content(self):
        text = "Hello [thought]I am thinking[/thought] world"
        assert extract_thought(text) == "I am thinking"

    def test_multiple_thoughts_returns_first(self):
        text = "[thought]First[/thought] and [thought]Second[/thought]"
        assert extract_thought(text) == "First"

    def test_unclosed_thought_returns_rest(self):
        text = "Hello [thought]unclosed thought"
        assert extract_thought(text) == "unclosed thought"

    def test_no_thought_returns_empty(self):
        text = "Hello world"
        assert extract_thought(text) == ""

    def test_empty_string(self):
        assert extract_thought("") == ""

    def test_nested_tags_not_handled(self):
        # Not a real use case, but verify behavior
        text = "[thought]outer [thought]inner[/thought] outer[/thought]"
        # Finds first [thought], then first [/thought] after it
        assert extract_thought(text) == "outer [thought]inner"


class TestStripThought:
    """Tests for strip_thought."""

    def test_removes_thought_block(self):
        text = "Hello [thought]thinking[/thought] world"
        assert strip_thought(text) == "Hello  world"

    def test_removes_multiple_thought_blocks(self):
        text = "[thought]1[/thought] middle [thought]2[/thought] end"
        # strip() removes leading/trailing whitespace
        assert strip_thought(text) == "middle  end"

    def test_unclosed_thought_removes_from_start(self):
        text = "Hello [thought]unclosed"
        # strip() removes trailing whitespace
        assert strip_thought(text) == "Hello"

    def test_no_thought_returns_original(self):
        text = "Hello world"
        assert strip_thought(text) == "Hello world"

    def test_strips_whitespace(self):
        text = "  [thought]x[/thought]  "
        assert strip_thought(text) == ""

    def test_only_thought_returns_empty(self):
        text = "[thought]only[/thought]"
        assert strip_thought(text) == ""


class TestBuildChatContext:
    """Tests for build_chat_context."""

    def test_returns_expected_keys(self):
        ctx = build_chat_context(
            sim_id=1, sim_name="Test", player_name="Player",
            channel="phone_sms", message="Hello", friendship=50.0,
            profile={"traits": ["creative"]}, memories=[], mood="happy",
            activity="idle", tick=100
        )
        expected_keys = {
            "sim_id", "sim_name", "player_name", "channel", "message",
            "friendship", "trust", "mood", "activity", "profile",
            "memories", "world_sim_tick", "history", "family"
        }
        assert set(ctx.keys()) == expected_keys

    def test_trust_level_computed(self):
        ctx = build_chat_context(
            sim_id=1, sim_name="Test", player_name="Player",
            channel="phone_sms", message="Hello", friendship=70.0,
            profile={}, memories=[], mood="happy", activity="idle", tick=100
        )
        assert ctx["trust"] == 3  # Advisor/Soulmate

    def test_all_values_passed_through(self):
        ctx = build_chat_context(
            sim_id=42, sim_name="Bob", player_name="Alice",
            channel="pc_chat", message="Hi there", friendship=30.0,
            profile={"backstory": "A tale"}, memories=[{"text": "mem1"}],
            mood="excited", activity="chatting", tick=500
        )
        assert ctx["sim_id"] == 42
        assert ctx["sim_name"] == "Bob"
        assert ctx["player_name"] == "Alice"
        assert ctx["channel"] == "pc_chat"
        assert ctx["message"] == "Hi there"
        assert ctx["friendship"] == 30.0
        assert ctx["trust"] == 2  # Confidant
        assert ctx["mood"] == "excited"
        assert ctx["activity"] == "chatting"
        assert ctx["profile"] == {"backstory": "A tale"}
        assert ctx["memories"] == [{"text": "mem1"}]
        assert ctx["world_sim_tick"] == 500

    def test_history_and_family_passed_through(self):
        ctx = build_chat_context(
            sim_id=42, sim_name="Bob", player_name="Alice",
            channel="phone_sms", message="Hi", friendship=10.0,
            profile={}, memories=[], mood="fine", activity="idle", tick=100,
            history=[{"role": "user", "content": "hello"},
                     {"role": "assistant", "content": "hi there"}],
            family=[{"name": "Carol", "relation": "sibling"}],
        )
        assert ctx["history"] == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        assert ctx["family"] == [{"name": "Carol", "relation": "sibling"}]

    def test_history_and_family_default_empty(self):
        ctx = build_chat_context(
            sim_id=42, sim_name="Bob", player_name="Alice",
            channel="phone_sms", message="Hi", friendship=10.0,
            profile={}, memories=[], mood="fine", activity="idle", tick=100
        )
        assert ctx["history"] == []
        assert ctx["family"] == []


class TestFamilyRelationLabel:
    """Tests for family_relation_label."""

    def test_raw_ea_bits(self):
        assert family_relation_label("FAMILY_BROTHER_SISTER") == "sibling"
        assert family_relation_label("FAMILY_PARENT") == "parent"
        assert family_relation_label("FAMILY_SON_DAUGHTER") == "child"
        assert family_relation_label("FAMILY_HUSBAND_WIFE") == "spouse"

    def test_clean_labels_pass_through(self):
        assert family_relation_label("sibling") == "sibling"
        assert family_relation_label("parent") == "parent"
        assert family_relation_label("aunt_uncle") == "aunt/uncle"
        assert family_relation_label("niece_nephew") == "niece/nephew"
        assert family_relation_label("step_sibling") == "step-sibling"

    def test_empty_and_none(self):
        assert family_relation_label("") == ""
        assert family_relation_label(None) == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])