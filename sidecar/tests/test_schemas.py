"""Tests for sensewright_sidecar.schemas module."""
from __future__ import annotations

import pytest

from sensewright_sidecar.schemas import (
    sanitize_payload,
    generate_trace_id,
    normalize_lang,
    require_lang,
    require_str,
    require_int,
    require_float,
    require_bool,
    CHANNELS,
    INTENT_KINDS,
    INTENT_SOURCES,
    INTENT_EXPIRY_MODES,
)


class TestSanitizePayload:
    """Tests for sanitize_payload."""

    def test_primitives_pass_through(self):
        assert sanitize_payload(None) is None
        assert sanitize_payload("string") == "string"
        assert sanitize_payload(42) == 42
        assert sanitize_payload(3.14) == 3.14
        assert sanitize_payload(True) is True
        assert sanitize_payload(False) is False

    def test_nested_dict(self):
        input_data = {"a": 1, "b": {"c": "hello", "d": [1, 2, 3]}}
        result = sanitize_payload(input_data)
        assert result == input_data

    def test_nested_list(self):
        input_data = [1, "two", {"three": 3}, [4, 5]]
        result = sanitize_payload(input_data)
        assert result == input_data

    def test_bytes_decoded(self):
        result = sanitize_payload(b"hello")
        assert result == "hello"

    def test_bytes_with_errors(self):
        result = sanitize_payload(b"\xff\xfe")
        assert isinstance(result, str)

    def test_unknown_object_stringified(self):
        class CustomObj:
            def __str__(self):
                return "custom"
        result = sanitize_payload(CustomObj())
        assert result == "custom"

    def test_dict_keys_coerced_to_str(self):
        input_data = {1: "one", 2.5: "two"}
        result = sanitize_payload(input_data)
        assert result == {"1": "one", "2.5": "two"}

    def test_depth_cap(self):
        # Create deeply nested structure
        deep = {}
        current = deep
        for i in range(70):
            current["next"] = {}
            current = current["next"]
        result = sanitize_payload(deep)
        # At depth > 64, nested values become None
        # Traverse to depth 65
        current = result
        for i in range(65):
            if isinstance(current, dict) and "next" in current:
                current = current["next"]
            else:
                break
        # At depth 65, value should be None
        assert current is None

    def test_set_converted_to_list(self):
        result = sanitize_payload({1, 2, 3})
        assert isinstance(result, list)
        assert set(result) == {1, 2, 3}

    def test_tuple_converted_to_list(self):
        result = sanitize_payload((1, 2, 3))
        assert isinstance(result, list)
        assert result == [1, 2, 3]


class TestGenerateTraceId:
    """Tests for generate_trace_id."""

    def test_length_is_8(self):
        tid = generate_trace_id()
        assert len(tid) == 8

    def test_hex_characters(self):
        tid = generate_trace_id()
        assert all(c in "0123456789abcdef" for c in tid)

    def test_uniqueness(self):
        ids = {generate_trace_id() for _ in range(100)}
        assert len(ids) == 100  # Very high probability of uniqueness


class TestNormalizeLang:
    """Tests for normalize_lang (requires i18n engine)."""

    def test_empty_string_returns_default(self):
        # This will use the default locale from manifest
        result = normalize_lang("")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_none_returns_default(self):
        result = normalize_lang(None)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_valid_locale_code(self):
        # Test with a known locale from manifest
        result = normalize_lang("pt-BR")
        assert result == "pt-BR"

    def test_case_insensitive(self):
        result = normalize_lang("PT-BR")
        assert result == "pt-BR"

    def test_unknown_falls_back_to_default(self):
        result = normalize_lang("xx-YY")
        # Should return default locale, not the unknown code
        assert result != "xx-YY"


class TestRequireLang:
    """Tests for require_lang."""

    def test_extracts_lang_from_payload(self):
        payload = {"lang": "pt-BR"}
        result = require_lang(payload)
        assert result == "pt-BR"

    def test_missing_lang_returns_default(self):
        payload = {}
        result = require_lang(payload)
        assert isinstance(result, str)
        assert len(result) > 0


class TestRequireStr:
    """Tests for require_str."""

    def test_returns_string(self):
        payload = {"key": "value"}
        assert require_str(payload, "key") == "value"

    def test_missing_returns_default(self):
        payload = {}
        assert require_str(payload, "missing", "default") == "default"

    def test_non_string_coerced_to_default(self):
        payload = {"key": 123}
        assert require_str(payload, "key", "default") == "default"

    def test_none_value_returns_default(self):
        payload = {"key": None}
        assert require_str(payload, "key", "default") == "default"


class TestRequireInt:
    """Tests for require_int."""

    def test_returns_int(self):
        payload = {"key": 42}
        assert require_int(payload, "key") == 42

    def test_coerces_float(self):
        payload = {"key": 3.14}
        assert require_int(payload, "key") == 3

    def test_coerces_string(self):
        payload = {"key": "100"}
        assert require_int(payload, "key") == 100

    def test_missing_returns_default(self):
        payload = {}
        assert require_int(payload, "missing", 99) == 99

    def test_invalid_returns_default(self):
        payload = {"key": "not_a_number"}
        assert require_int(payload, "key", 77) == 77

    def test_none_returns_default(self):
        payload = {"key": None}
        assert require_int(payload, "key", 55) == 55


class TestRequireFloat:
    """Tests for require_float."""

    def test_returns_float(self):
        payload = {"key": 3.14}
        assert require_float(payload, "key") == 3.14

    def test_coerces_int(self):
        payload = {"key": 42}
        assert require_float(payload, "key") == 42.0

    def test_coerces_string(self):
        payload = {"key": "2.5"}
        assert require_float(payload, "key") == 2.5

    def test_missing_returns_default(self):
        payload = {}
        assert require_float(payload, "missing", 1.5) == 1.5

    def test_invalid_returns_default(self):
        payload = {"key": "not_a_number"}
        assert require_float(payload, "key", 0.0) == 0.0


class TestRequireBool:
    """Tests for require_bool."""

    def test_returns_bool(self):
        payload = {"key": True}
        assert require_bool(payload, "key") is True

    def test_coerces_int(self):
        assert require_bool({"key": 1}, "key") is True
        assert require_bool({"key": 0}, "key") is False

    def test_coerces_float(self):
        assert require_bool({"key": 1.0}, "key") is True
        assert require_bool({"key": 0.0}, "key") is False

    def test_coerces_string_true(self):
        for val in ("true", "True", "TRUE", "1", "yes", "on"):
            assert require_bool({"key": val}, "key") is True

    def test_coerces_string_false(self):
        for val in ("false", "False", "FALSE", "0", "no", "off"):
            assert require_bool({"key": val}, "key") is False

    def test_missing_returns_default(self):
        payload = {}
        assert require_bool(payload, "missing", True) is True

    def test_invalid_string_returns_false(self):
        payload = {"key": "invalid"}
        assert require_bool(payload, "key", True) is False

    def test_none_returns_default(self):
        payload = {"key": None}
        assert require_bool(payload, "key", True) is True


class TestConstants:
    """Tests for exported constants."""

    def test_channels(self):
        assert CHANNELS == ("phone_sms", "pc_chat", "pc_email")

    def test_intent_kinds(self):
        expected = (
            "speak", "approach", "set_mood", "bias_interaction", "prefer_target",
            "set_goal", "remember", "forget", "command",
        )
        assert INTENT_KINDS == expected

    def test_intent_sources(self):
        assert INTENT_SOURCES == ("agent", "god", "puppeteer", "social")

    def test_intent_expiry_modes(self):
        assert INTENT_EXPIRY_MODES == ("ttl", "next_sleep", "zone_transition")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])