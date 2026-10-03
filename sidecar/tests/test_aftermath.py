"""Tests for sensewright_sidecar.world.aftermath module."""
from __future__ import annotations

import pytest

from sensewright_sidecar.world.aftermath import (
    build_aftermath_context,
    merge_zeitgeist,
    parse_aftermath,
)


class TestBuildAftermathContext:
    """Tests for build_aftermath_context."""

    def test_builds_expected_shape(self):
        sim = {"sim_id": 42, "name": "Alice"}
        ctx = build_aftermath_context(sim, "death", 0.8, 0.6, 1000)

        assert ctx == {
            "sim_id": 42,
            "sim_name": "Alice",
            "event_category": "death",
            "impact": 0.8,
            "salience": 0.6,
            "world_sim_tick": 1000,
        }

    def test_coerces_types(self):
        sim = {"sim_id": "99", "name": 123}
        ctx = build_aftermath_context(sim, "promotion", "1.5", "0.3", "500")

        assert ctx["sim_id"] == 99
        assert ctx["sim_name"] == "123"
        assert ctx["event_category"] == "promotion"
        assert ctx["impact"] == 1.5
        assert ctx["salience"] == 0.3
        assert ctx["world_sim_tick"] == 500

    def test_handles_missing_sim_fields(self):
        sim = {}
        ctx = build_aftermath_context(sim, "breakup", 0.5, 0.5, 100)

        assert ctx["sim_id"] == 0
        assert ctx["sim_name"] == ""
        assert ctx["event_category"] == "breakup"
        assert ctx["impact"] == 0.5
        assert ctx["salience"] == 0.5
        assert ctx["world_sim_tick"] == 100

    def test_handles_none_sim(self):
        ctx = build_aftermath_context(None, "death", 0.1, 0.2, 10)  # type: ignore[arg-type]

        assert ctx["sim_id"] == 0
        assert ctx["sim_name"] == ""
        assert ctx["event_category"] == "death"
        assert ctx["impact"] == 0.1
        assert ctx["salience"] == 0.2
        assert ctx["world_sim_tick"] == 10

    def test_handles_none_category_impact_salience_tick(self):
        sim = {"sim_id": 1, "name": "Bob"}
        ctx = build_aftermath_context(sim, None, None, None, None)  # type: ignore[arg-type]

        assert ctx["sim_id"] == 1
        assert ctx["sim_name"] == "Bob"
        assert ctx["event_category"] == ""
        assert ctx["impact"] == 0.0
        assert ctx["salience"] == 0.0
        assert ctx["world_sim_tick"] == 0


class TestMergeZeitgeist:
    """Tests for merge_zeitgeist."""

    def test_union_tags_case_insensitive_order_preserving(self):
        existing = {"tags": ["Tense", "Romantic"], "preset": "drama", "weather_preference": "sunny"}
        shift = {"tags": ["tense", "MYSTERIOUS", "romantic", "New"]}

        result = merge_zeitgeist(existing, shift)

        # Order: existing first (Tense, Romantic), then shift new ones (MYSTERIOUS, New)
        # Case-insensitive dedup: "tense" and "romantic" already seen
        assert result["tags"] == ["Tense", "Romantic", "MYSTERIOUS", "New"]

    def test_caps_tags_at_12(self):
        existing = {"tags": [f"tag{i}" for i in range(10)], "preset": "drama", "weather_preference": "sunny"}
        shift = {"tags": [f"shift{i}" for i in range(5)]}  # 5 new, would make 15

        result = merge_zeitgeist(existing, shift)

        assert len(result["tags"]) == 12
        # First 10 from existing, first 2 from shift
        assert result["tags"][:10] == [f"tag{i}" for i in range(10)]
        assert result["tags"][10:] == ["shift0", "shift1"]

    def test_preset_overwritten_when_shift_provides_non_empty(self):
        existing = {"tags": [], "preset": "drama", "weather_preference": "sunny"}
        shift = {"preset": "comedy"}

        result = merge_zeitgeist(existing, shift)

        assert result["preset"] == "comedy"

    def test_preset_not_overwritten_when_shift_empty_or_missing(self):
        existing = {"tags": [], "preset": "drama", "weather_preference": "sunny"}

        # Empty string
        result = merge_zeitgeist(existing, {"preset": ""})
        assert result["preset"] == "drama"

        # Missing key
        result = merge_zeitgeist(existing, {})
        assert result["preset"] == "drama"

        # None value
        result = merge_zeitgeist(existing, {"preset": None})  # type: ignore[dict-item]
        assert result["preset"] == "drama"

    def test_weather_preference_overwritten_when_shift_provides_non_empty(self):
        existing = {"tags": [], "preset": "drama", "weather_preference": "sunny"}
        shift = {"weather_preference": "storm"}

        result = merge_zeitgeist(existing, shift)

        assert result["weather_preference"] == "storm"

    def test_weather_preference_not_overwritten_when_shift_empty_or_missing(self):
        existing = {"tags": [], "preset": "drama", "weather_preference": "sunny"}

        result = merge_zeitgeist(existing, {"weather_preference": ""})
        assert result["weather_preference"] == "sunny"

        result = merge_zeitgeist(existing, {})
        assert result["weather_preference"] == "sunny"

    def test_returns_new_dict_no_mutation(self):
        existing = {"tags": ["Tense"], "preset": "drama", "weather_preference": "sunny"}
        shift = {"tags": ["New"], "preset": "comedy", "weather_preference": "rain"}

        result = merge_zeitgeist(existing, shift)

        assert result is not existing
        assert result["tags"] is not existing["tags"]
        assert existing["tags"] == ["Tense"]
        assert existing["preset"] == "drama"
        assert existing["weather_preference"] == "sunny"
        assert shift["tags"] == ["New"]

    def test_handles_invalid_existing_gracefully(self):
        # existing is not a dict
        result = merge_zeitgeist("not a dict", {"tags": ["New"], "preset": "comedy"})  # type: ignore[arg-type]

        assert result["tags"] == ["New"]
        assert result["preset"] == "comedy"
        assert result["weather_preference"] == "sunny"

    def test_handles_invalid_shift_gracefully(self):
        existing = {"tags": ["Existing"], "preset": "drama", "weather_preference": "sunny"}

        # shift is not a dict
        result = merge_zeitgeist(existing, "not a dict")  # type: ignore[arg-type]

        assert result["tags"] == ["Existing"]
        assert result["preset"] == "drama"
        assert result["weather_preference"] == "sunny"

    def test_handles_none_inputs(self):
        result = merge_zeitgeist(None, None)  # type: ignore[arg-type]

        assert result == {"tags": [], "preset": "drama", "weather_preference": "sunny"}

    def test_non_string_tags_are_filtered(self):
        existing = {"tags": ["Valid", 123, None, "AlsoValid"], "preset": "drama", "weather_preference": "sunny"}
        shift = {"tags": ["New", 456, "Another"]}

        result = merge_zeitgeist(existing, shift)

        assert result["tags"] == ["Valid", "AlsoValid", "New", "Another"]


class TestParseAftermath:
    """Tests for parse_aftermath."""

    def test_parses_valid_data(self):
        data = {
            "summary": "A dramatic event occurred.",
            "intents": [{"type": "mourn", "target": "sim_1"}, {"type": "comfort", "target": "sim_2"}],
            "zeitgeist_shift": {"tags": ["tense", "sad"], "preset": "drama", "weather_preference": "rain"},
        }

        result = parse_aftermath(data)

        assert result["summary"] == "A dramatic event occurred."
        assert result["intents"] == [
            {"type": "mourn", "target": "sim_1"},
            {"type": "comfort", "target": "sim_2"},
        ]
        assert result["zeitgeist_shift"] == {
            "tags": ["tense", "sad"],
            "preset": "drama",
            "weather_preference": "rain",
        }

    def test_coerces_summary_to_string(self):
        data = {"summary": 123}
        result = parse_aftermath(data)
        assert result["summary"] == "123"

        data = {"summary": None}
        result = parse_aftermath(data)
        assert result["summary"] == ""

        data = {}
        result = parse_aftermath(data)
        assert result["summary"] == ""

    def test_drops_non_dict_intents(self):
        data = {
            "intents": [
                {"type": "valid"},
                "not a dict",
                123,
                None,
                {"type": "also_valid"},
                ["list"],
            ]
        }
        result = parse_aftermath(data)

        assert result["intents"] == [{"type": "valid"}, {"type": "also_valid"}]

    def test_handles_missing_intents(self):
        data = {}
        result = parse_aftermath(data)
        assert result["intents"] == []

        data = {"intents": None}
        result = parse_aftermath(data)
        assert result["intents"] == []

        data = {"intents": "not a list"}
        result = parse_aftermath(data)
        assert result["intents"] == []

    def test_coerces_zeitgeist_shift_tags_to_strings(self):
        data = {
            "zeitgeist_shift": {
                "tags": ["valid", 123, None, "also_valid"],
                "preset": "drama",
                "weather_preference": "sunny",
            }
        }
        result = parse_aftermath(data)

        assert result["zeitgeist_shift"]["tags"] == ["valid", "also_valid"]

    def test_coerces_zeitgeist_shift_preset_weather_to_strings(self):
        data = {
            "zeitgeist_shift": {
                "preset": 123,
                "weather_preference": None,
            }
        }
        result = parse_aftermath(data)

        assert result["zeitgeist_shift"]["preset"] == "123"
        assert result["zeitgeist_shift"]["weather_preference"] == ""

    def test_handles_missing_zeitgeist_shift(self):
        data = {}
        result = parse_aftermath(data)

        assert result["zeitgeist_shift"] == {"tags": [], "preset": "", "weather_preference": ""}

        data = {"zeitgeist_shift": None}
        result = parse_aftermath(data)
        assert result["zeitgeist_shift"] == {"tags": [], "preset": "", "weather_preference": ""}

        data = {"zeitgeist_shift": "not a dict"}
        result = parse_aftermath(data)
        assert result["zeitgeist_shift"] == {"tags": [], "preset": "", "weather_preference": ""}

    def test_handles_non_dict_input(self):
        result = parse_aftermath("not a dict")  # type: ignore[arg-type]

        assert result == {
            "summary": "",
            "intents": [],
            "zeitgeist_shift": {"tags": [], "preset": "", "weather_preference": ""},
        }

    def test_returns_new_dicts_no_mutation(self):
        data = {
            "summary": "Test",
            "intents": [{"type": "test"}],
            "zeitgeist_shift": {"tags": ["tag1"], "preset": "drama", "weather_preference": "sunny"},
        }
        original_intents = data["intents"]
        original_shift = data["zeitgeist_shift"]

        result = parse_aftermath(data)

        assert result["intents"] is not original_intents
        assert result["zeitgeist_shift"] is not original_shift
        # Original data unchanged
        assert data["intents"] == [{"type": "test"}]
        assert data["zeitgeist_shift"]["tags"] == ["tag1"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])