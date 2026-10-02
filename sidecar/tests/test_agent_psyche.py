"""Tests for sensewright_sidecar.agent.psyche module."""
from __future__ import annotations

import pytest

from sensewright_sidecar.agent.psyche import (
    compute_salience,
    is_salient,
    decay_blocks,
    reinforce_block,
    block_for_category,
    propose_trait_swap,
    strongest_block,
)
from sensewright_sidecar.constants import (
    EVENT_CATEGORY_WEIGHTS,
    SALIENCE_THRESHOLD,
    PSYCHE_PRUNE_THRESHOLD,
    PSYCHE_TRAIT_SWAP_INTENSITY,
    PSYCHE_TRAIT_SWAP_DAYS,
)


class TestComputeSalience:
    """Tests for compute_salience."""

    def test_death_category(self):
        # death weight = 2.5, impact adds to it
        salience = compute_salience("death", 0.0)
        assert salience == 2.5

    def test_death_with_impact(self):
        salience = compute_salience("death", 1.0)
        assert salience == 3.5  # 2.5 + 1.0

    def test_betrayal_category(self):
        salience = compute_salience("betrayal", 0.0)
        assert salience == 2.2

    def test_fire_category(self):
        salience = compute_salience("fire", 0.0)
        assert salience == 2.0

    def test_romance_category(self):
        salience = compute_salience("romance", 0.0)
        assert salience == 1.6

    def test_mundane_category(self):
        salience = compute_salience("mundane", 0.0)
        assert salience == 0.5

    def test_unknown_category_defaults_to_0_5(self):
        salience = compute_salience("unknown_category", 0.0)
        assert salience == 0.5

    def test_none_category(self):
        salience = compute_salience(None, 0.0)
        assert salience == 0.5

    def test_impact_clamped_at_zero(self):
        salience = compute_salience("death", -5.0)
        assert salience == 2.5  # impact clamped to 0


class TestIsSalient:
    """Tests for is_salient."""

    def test_death_is_salient(self):
        assert is_salient("death", 0.0) is True

    def test_betrayal_is_salient(self):
        assert is_salient("betrayal", 0.0) is True

    def test_fire_is_salient(self):
        assert is_salient("fire", 0.0) is True

    def test_romance_is_salient(self):
        assert is_salient("romance", 0.0) is True

    def test_promotion_not_salient(self):
        # promotion weight = 1.4, threshold = 1.5
        assert is_salient("promotion", 0.0) is False

    def test_promotion_with_impact_salient(self):
        assert is_salient("promotion", 0.2) is True  # 1.4 + 0.2 = 1.6 >= 1.5

    def test_mundane_not_salient(self):
        assert is_salient("mundane", 0.0) is False

    def test_mundane_with_high_impact_salient(self):
        assert is_salient("mundane", 1.0) is True  # 0.5 + 1.0 = 1.5 >= 1.5


class TestDecayBlocks:
    """Tests for decay_blocks."""

    def test_exponential_decay(self):
        blocks = {"grief": 1.0, "stress": 0.5}
        # After 1 sim day with lambda=0.05: factor = e^(-0.05) ≈ 0.951
        decayed = decay_blocks(blocks, 1.0)
        assert decayed["grief"] < 1.0
        assert decayed["grief"] > 0.9
        assert decayed["stress"] < 0.5
        assert decayed["stress"] > 0.45

    def test_prune_below_threshold(self):
        blocks = {"weak": 0.04, "strong": 0.5}
        # After enough days, weak should be pruned (but strong survives)
        # factor = e^(-0.05 * 10) ≈ 0.606, so strong = 0.5 * 0.606 ≈ 0.303 > 0.05
        decayed = decay_blocks(blocks, 10.0)
        assert "weak" not in decayed
        assert "strong" in decayed

    def test_prune_threshold_exact(self):
        blocks = {"exact": PSYCHE_PRUNE_THRESHOLD}
        decayed = decay_blocks(blocks, 0.0)
        assert "exact" in decayed

    def test_negative_delta_days_treated_as_zero(self):
        blocks = {"test": 1.0}
        decayed = decay_blocks(blocks, -10.0)
        assert decayed["test"] == 1.0

    def test_rounds_to_4_decimal_places(self):
        blocks = {"test": 1.0}
        decayed = decay_blocks(blocks, 1.0)
        # Check rounding
        val = decayed["test"]
        assert val == round(val, 4)


class TestReinforceBlock:
    """Tests for reinforce_block."""

    def test_create_new_block(self):
        blocks = {}
        result = reinforce_block(blocks, "grief", 0.3)
        assert result["grief"] == 0.3

    def test_strengthen_existing_block(self):
        blocks = {"grief": 0.4}
        result = reinforce_block(blocks, "grief", 0.3)
        assert result["grief"] == 0.7

    def test_clamp_at_one(self):
        blocks = {"grief": 0.8}
        result = reinforce_block(blocks, "grief", 0.5)
        assert result["grief"] == 1.0

    def test_clamp_at_zero(self):
        blocks = {"grief": 0.2}
        result = reinforce_block(blocks, "grief", -0.5)
        assert result["grief"] == 0.0

    def test_original_dict_not_mutated(self):
        blocks = {"grief": 0.5}
        reinforce_block(blocks, "grief", 0.3)
        assert blocks["grief"] == 0.5  # Original unchanged


class TestBlockForCategory:
    """Tests for block_for_category."""

    def test_death_maps_to_grief(self):
        assert block_for_category("death") == "grief"

    def test_betrayal_maps_to_betrayal(self):
        assert block_for_category("betrayal") == "betrayal"

    def test_fire_maps_to_trauma_fire(self):
        assert block_for_category("fire") == "trauma_fire"

    def test_romance_maps_to_romance(self):
        assert block_for_category("romance") == "romance"

    def test_fight_maps_to_conflict(self):
        assert block_for_category("fight") == "conflict"

    def test_unknown_maps_to_stress(self):
        assert block_for_category("unknown") == "stress"
        assert block_for_category("promotion") == "stress"
        assert block_for_category(None) == "stress"

    def test_case_insensitive(self):
        assert block_for_category("DEATH") == "grief"
        assert block_for_category("Betrayal") == "betrayal"


class TestProposeTraitSwap:
    """Tests for propose_trait_swap."""

    def test_eligible_when_intensity_and_days_high(self):
        blocks = {"grief": 0.9}
        days = {"grief": 5}
        proposals = propose_trait_swap(blocks, days)
        assert "grief" in proposals

    def test_not_eligible_when_intensity_low(self):
        blocks = {"grief": 0.8}  # Below 0.85
        days = {"grief": 5}
        proposals = propose_trait_swap(blocks, days)
        assert "grief" not in proposals

    def test_not_eligible_when_days_low(self):
        blocks = {"grief": 0.9}
        days = {"grief": 2}  # Below 3
        proposals = propose_trait_swap(blocks, days)
        assert "grief" not in proposals

    def test_multiple_blocks(self):
        blocks = {"grief": 0.9, "stress": 0.5}
        days = {"grief": 5, "stress": 5}
        proposals = propose_trait_swap(blocks, days)
        assert proposals == ["grief"]


class TestStrongestBlock:
    """Tests for strongest_block."""

    def test_returns_strongest(self):
        blocks = {"grief": 0.7, "stress": 0.3, "romance": 0.5}
        key, intensity = strongest_block(blocks)
        assert key == "grief"
        assert intensity == 0.7

    def test_empty_returns_empty(self):
        key, intensity = strongest_block({})
        assert key == ""
        assert intensity == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])