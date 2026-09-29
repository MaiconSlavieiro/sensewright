"""
Tests for locale parity between en.json and pt-BR.json.
Run with system Python (3.10+).
"""

import sys
import os
import json

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest


def load_locale(locale: str) -> dict:
    """Load a locale file directly."""
    locale_path = os.path.join(mod_dir, "sensewright_mod", "locales", "{}.json".format(locale))
    with open(locale_path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_both_locales_exist():
    """Test that both locale files exist."""
    en_path = os.path.join(mod_dir, "sensewright_mod", "locales", "en.json")
    ptbr_path = os.path.join(mod_dir, "sensewright_mod", "locales", "pt-BR.json")

    assert os.path.exists(en_path), "en.json not found"
    assert os.path.exists(ptbr_path), "pt-BR.json not found"


def test_meta_structure():
    """Test that both locales have correct _meta structure."""
    en_data = load_locale("en")
    ptbr_data = load_locale("pt-BR")

    # Both must have _meta
    assert "_meta" in en_data
    assert "_meta" in ptbr_data

    # EN meta
    assert en_data["_meta"]["locale"] == "en"
    assert en_data["_meta"]["name"] == "English"
    assert "version" in en_data["_meta"]

    # PT-BR meta
    assert ptbr_data["_meta"]["locale"] == "pt-BR"
    assert ptbr_data["_meta"]["name"] == "Português (Brasil)"
    assert "version" in ptbr_data["_meta"]


def test_key_parity():
    """Test that both locales have identical key sets (excluding _meta)."""
    en_data = load_locale("en")
    ptbr_data = load_locale("pt-BR")

    en_keys = set(k for k in en_data.keys() if k != "_meta")
    ptbr_keys = set(k for k in ptbr_data.keys() if k != "_meta")

    # Both should have the same keys
    missing_in_ptbr = en_keys - ptbr_keys
    missing_in_en = ptbr_keys - en_keys

    assert not missing_in_ptbr, "Keys missing in pt-BR: {}".format(sorted(missing_in_ptbr))
    assert not missing_in_en, "Keys missing in en: {}".format(sorted(missing_in_en))


def test_required_keys_present():
    """Test that all canonical keys are present in both locales."""
    # Canonical keys from the spec
    required_keys = {
        "cmd.help.title",
        "cmd.help.body",
        "cmd.status.title",
        "cmd.status.body",
        "cmd.status.sidecar_down",
        "cmd.reset.done",
        "cmd.forget.done",
        "cmd.autonomy.set",
        "cmd.lang.set",
        "cmd.lang.invalid",
        "cmd.god.opening",
        "cmd.god.unavailable",
        "notify.sidecar_starting",
        "notify.sidecar_ready",
        "notify.sidecar_unreachable",
        "notify.no_llm_native",
        "error.brain_foggy",
        "error.rate_limited",
        "error.bad_request",
        "error.internal",
    }

    en_data = load_locale("en")
    ptbr_data = load_locale("pt-BR")

    en_keys = set(k for k in en_data.keys() if k != "_meta")
    ptbr_keys = set(k for k in ptbr_data.keys() if k != "_meta")

    missing_in_en = required_keys - en_keys
    missing_in_ptbr = required_keys - ptbr_keys

    assert not missing_in_en, "Required keys missing in en: {}".format(sorted(missing_in_en))
    assert not missing_in_ptbr, "Required keys missing in pt-BR: {}".format(sorted(missing_in_ptbr))


def test_no_empty_values():
    """Test that no locale has empty string values for required keys."""
    en_data = load_locale("en")
    ptbr_data = load_locale("pt-BR")

    for key, value in en_data.items():
        if key == "_meta":
            continue
        assert value != "", "Empty value in en for key: {}".format(key)

    for key, value in ptbr_data.items():
        if key == "_meta":
            continue
        assert value != "", "Empty value in pt-BR for key: {}".format(key)


def test_placeholders_consistency():
    """Test that placeholders in EN and PT-BR match for each key."""
    en_data = load_locale("en")
    ptbr_data = load_locale("pt-BR")

    import re
    placeholder_pattern = re.compile(r"\{(\w+)\}")

    for key in en_data:
        if key == "_meta":
            continue

        en_value = en_data[key]
        ptbr_value = ptbr_data.get(key, "")

        en_placeholders = set(placeholder_pattern.findall(en_value))
        ptbr_placeholders = set(placeholder_pattern.findall(ptbr_value))

        # Both should have the same placeholders
        assert en_placeholders == ptbr_placeholders, \
            "Placeholder mismatch for {}: en={}, pt-BR={}".format(
                key, en_placeholders, ptbr_placeholders
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])