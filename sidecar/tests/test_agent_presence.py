"""Tests for sensewright_sidecar.agent.presence module."""
from __future__ import annotations

import pytest

from sensewright_sidecar.agent.presence import (
    excluded_from_seats,
    sensory_only,
    hard_blocked_social,
    capabilities,
    presence_tier,
)
from sensewright_sidecar.constants import (
    EXCLUDED_FROM_SEATS,
    SENSORY_ONLY,
    CHILD_HARD_BLOCKED_CATEGORIES,
    PRESENCE_FULL,
    PRESENCE_REACTIVE,
    FULL_PRESENCE_FRIENDSHIP,
)
from sensewright_sidecar.agent.presence import INTIMATE_BONDS


class TestExcludedFromSeats:
    """Tests for excluded_from_seats."""

    def test_baby_excluded(self):
        assert excluded_from_seats("BABY") is True
        assert excluded_from_seats("baby") is True

    def test_other_species_not_excluded(self):
        assert excluded_from_seats("HUMAN") is False
        assert excluded_from_seats("DOG") is False
        assert excluded_from_seats("CAT") is False
        assert excluded_from_seats(None) is False
        assert excluded_from_seats("") is False


class TestSensoryOnly:
    """Tests for sensory_only."""

    def test_infant_sensory_only(self):
        assert sensory_only("HUMAN", "INFANT") is True

    def test_toddler_sensory_only(self):
        assert sensory_only("HUMAN", "TODDLER") is True

    def test_dog_sensory_only(self):
        assert sensory_only("DOG", "ADULT") is True

    def test_cat_sensory_only(self):
        assert sensory_only("CAT", "ADULT") is True

    def test_horse_sensory_only(self):
        assert sensory_only("HORSE", "ADULT") is True

    def test_adult_human_not_sensory_only(self):
        assert sensory_only("HUMAN", "YOUNGADULT") is False
        assert sensory_only("HUMAN", "ADULT") is False
        assert sensory_only("HUMAN", "ELDER") is False

    def test_child_not_sensory_only(self):
        assert sensory_only("HUMAN", "CHILD") is False

    def test_teen_not_sensory_only(self):
        assert sensory_only("HUMAN", "TEEN") is False


class TestHardBlockedSocial:
    """Tests for hard_blocked_social."""

    def test_child_flirty_blocked(self):
        assert hard_blocked_social("flirty", "CHILD") is True

    def test_child_intimate_blocked(self):
        assert hard_blocked_social("intimate", "CHILD") is True

    def test_child_friendly_not_blocked(self):
        assert hard_blocked_social("friendly", "CHILD") is False

    def test_adult_flirty_not_blocked(self):
        assert hard_blocked_social("flirty", "ADULT") is False

    def test_teen_flirty_not_blocked(self):
        assert hard_blocked_social("flirty", "TEEN") is False

    def test_none_category_not_blocked(self):
        assert hard_blocked_social(None, "CHILD") is False

    def test_case_insensitive_category(self):
        assert hard_blocked_social("FLIRTY", "CHILD") is True
        assert hard_blocked_social("Flirty", "CHILD") is True


class TestCapabilities:
    """Tests for capabilities."""

    def test_sensory_only_sim(self):
        caps = capabilities("HUMAN", "INFANT")
        assert caps["can_speak"] is False
        assert caps["can_social"] is False
        assert caps["can_career"] is False
        assert caps["sensory_only"] is True
        assert caps["excluded_from_seats"] is False

    def test_child_can_speak_and_social(self):
        caps = capabilities("HUMAN", "CHILD")
        assert caps["can_speak"] is True
        assert caps["can_social"] is True
        assert caps["can_career"] is False  # Children can't have careers
        assert caps["sensory_only"] is False

    def test_adult_full_capabilities(self):
        caps = capabilities("HUMAN", "YOUNGADULT")
        assert caps["can_speak"] is True
        assert caps["can_social"] is True
        assert caps["can_career"] is True
        assert caps["sensory_only"] is False

    def test_baby_excluded_from_seats(self):
        caps = capabilities("BABY", "INFANT")
        assert caps["excluded_from_seats"] is True

    def test_dog_sensory_only(self):
        caps = capabilities("DOG", "ADULT")
        assert caps["can_speak"] is False
        assert caps["can_social"] is False
        assert caps["sensory_only"] is True


class TestPresenceTier:
    """Tests for presence_tier."""

    def test_player_is_full(self):
        assert presence_tier(is_player=True, in_active_household=False, is_catalyst=False) == PRESENCE_FULL

    def test_active_household_is_full(self):
        assert presence_tier(is_player=False, in_active_household=True, is_catalyst=False) == PRESENCE_FULL

    def test_catalyst_is_full(self):
        assert presence_tier(is_player=False, in_active_household=False, is_catalyst=True) == PRESENCE_FULL

    def test_intimate_visitor_high_friendship_is_full(self):
        assert presence_tier(
            is_player=False,
            in_active_household=False,
            is_catalyst=False,
            friendship=25.0,
            bond_types=["friend"]
        ) == PRESENCE_FULL

    def test_intimate_visitor_low_friendship_is_reactive(self):
        assert presence_tier(
            is_player=False,
            in_active_household=False,
            is_catalyst=False,
            friendship=10.0,
            bond_types=["friend"]
        ) == PRESENCE_REACTIVE

    def test_non_intimate_bond_is_reactive(self):
        assert presence_tier(
            is_player=False,
            in_active_household=False,
            is_catalyst=False,
            friendship=50.0,
            bond_types=["acquaintance"]
        ) == PRESENCE_REACTIVE

    def test_no_bonds_is_reactive(self):
        assert presence_tier(
            is_player=False,
            in_active_household=False,
            is_catalyst=False,
            friendship=50.0,
            bond_types=[]
        ) == PRESENCE_REACTIVE

    def test_friendship_threshold_boundary(self):
        # Exactly at threshold
        assert presence_tier(
            is_player=False,
            in_active_household=False,
            is_catalyst=False,
            friendship=FULL_PRESENCE_FRIENDSHIP,
            bond_types=["friend"]
        ) == PRESENCE_FULL

    def test_all_intimate_bond_types(self):
        for bond in INTIMATE_BONDS:
            tier = presence_tier(
                is_player=False,
                in_active_household=False,
                is_catalyst=False,
                friendship=25.0,
                bond_types=[bond]
            )
            assert tier == PRESENCE_FULL, f"Bond type {bond} should be intimate"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])