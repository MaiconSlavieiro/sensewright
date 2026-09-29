"""
Tests for i18n module.
Run with system Python (3.10+).
"""

import sys
import os

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest
from simssense_mod import i18n


def test_load_both_locales():
    """Test that both locales can be loaded."""
    en_data = i18n._load_locale("en")
    ptbr_data = i18n._load_locale("pt-BR")

    assert isinstance(en_data, dict)
    assert isinstance(ptbr_data, dict)
    assert "_meta" in en_data
    assert "_meta" in ptbr_data
    assert en_data["_meta"]["locale"] == "en"
    assert ptbr_data["_meta"]["locale"] == "pt-BR"


def test_t_fallback_missing_key():
    """Test that missing keys fall back to EN, then return key itself."""
    # Set to EN
    i18n.set_locale("en")

    # Existing key
    result = i18n.t("cmd.help.title")
    assert result == "SimsSense commands"
    assert result != "cmd.help.title"

    # Missing key returns key itself
    result = i18n.t("nonexistent.key.12345")
    assert result == "nonexistent.key.12345"


def test_t_formatting():
    """Test string formatting with args."""
    i18n.set_locale("en")
    result = i18n.t("cmd.autonomy.set", level="full", sim_id=12345)
    assert "full" in result
    assert "12345" in result

    # Test with pt-BR
    i18n.set_locale("pt-BR")
    result = i18n.t("cmd.autonomy.set", level="full", sim_id=12345)
    assert "full" in result
    assert "12345" in result


def test_detect_game_language_outside_game():
    """Test that detect_game_language returns 'en' outside the game."""
    result = i18n.detect_game_language()
    assert result == "en"


def test_normalize_locale():
    """Test locale normalization."""
    assert i18n._normalize_locale("en") == "en"
    assert i18n._normalize_locale("en-US") == "en"
    assert i18n._normalize_locale("pt_BR") == "pt-BR"
    assert i18n._normalize_locale("pt-BR") == "pt-BR"
    assert i18n._normalize_locale("pt") == "pt-BR"
    assert i18n._normalize_locale("fr") == "en"  # Unsupported -> en
    assert i18n._normalize_locale("") == "en"
    # Enum reprs from services.get_locale()
    assert i18n._normalize_locale("Locale.PORTUGUESE_BRAZIL") == "pt-BR"
    assert i18n._normalize_locale("Language.BrazilianPortuguese") == "pt-BR"
    assert i18n._normalize_locale("Language.ENGLISH") == "en"


def test_init_locale_sets_current(monkeypatch):
    assert i18n.init_locale("pt-BR") == "pt-BR"
    assert i18n.current_locale() == "pt-BR"

    assert i18n.init_locale("en") == "en"
    assert i18n.current_locale() == "en"


def test_detect_game_language_from_services(monkeypatch):
    import sys
    import types

    class FakeLocale:
        def __init__(self, name):
            self.name = name

    fake_services = types.SimpleNamespace(get_locale=lambda: FakeLocale("PORTUGUESE_BRAZIL"))
    monkeypatch.setitem(sys.modules, "services", fake_services)
    assert i18n.detect_game_language() == "pt-BR"

    fake_services_en = types.SimpleNamespace(get_locale=lambda: FakeLocale("ENGLISH"))
    monkeypatch.setitem(sys.modules, "services", fake_services_en)
    assert i18n.detect_game_language() == "en"


def test_resolve_locale():
    """Test locale resolution order."""
    # Explicit override
    assert i18n.resolve_locale("pt-BR") == "pt-BR"
    assert i18n.resolve_locale("en") == "en"

    # Auto -> detect_game_language (which returns en outside game)
    assert i18n.resolve_locale("auto") == "en"


def test_current_locale():
    """Test current_locale getter/setter."""
    i18n.set_locale("pt-BR")
    assert i18n.current_locale() == "pt-BR"

    i18n.set_locale("en")
    assert i18n.current_locale() == "en"


def test_ensure_locale_retries_until_game_ready(monkeypatch):
    """auto mode must keep retrying while services are down, then lock once."""
    import sys
    import types

    monkeypatch.setattr(i18n, "_locale_override", None)
    monkeypatch.setattr(i18n, "_auto_detected", False)
    monkeypatch.setattr(i18n, "_current_locale", "en")

    # Services not up yet: no locale answered -> stays en and unlocked.
    monkeypatch.setitem(sys.modules, "services", types.SimpleNamespace(get_locale=lambda: None))
    assert i18n.ensure_locale() == "en"
    assert i18n._auto_detected is False

    class FakeLocale:
        def __init__(self, name):
            self.name = name

    # Game ready (Portuguese): locks pt-BR.
    monkeypatch.setitem(sys.modules, "services",
                        types.SimpleNamespace(get_locale=lambda: FakeLocale("PORTUGUESE_BRAZIL")))
    assert i18n.ensure_locale() == "pt-BR"
    assert i18n._auto_detected is True

    # Locked: later locale changes are ignored.
    monkeypatch.setitem(sys.modules, "services",
                        types.SimpleNamespace(get_locale=lambda: FakeLocale("ENGLISH")))
    assert i18n.ensure_locale() == "pt-BR"


def test_reload_locales():
    """Test that reload_locales clears cache."""
    i18n._load_locale("en")
    assert "en" in i18n._locale_cache

    i18n.reload_locales()
    assert "en" not in i18n._locale_cache


def test_t_formatting_missing_placeholder_returns_raw():
    """M8: a bad placeholder must not raise, returns the raw value."""
    i18n.set_locale("en")
    # ``cmd.autonomy.set`` has {level}/{sim_id}; call without args is raw.
    raw = i18n.t("cmd.autonomy.set")
    assert "{level}" in raw
    # An unrelated arg key still formats (extra kwargs are ignored).
    assert "full" in i18n.t("cmd.autonomy.set", level="full", sim_id=1)


def test_t_non_string_value_is_stringified():
    """M8: non-string locale values cannot break ``str.format``."""
    i18n.set_locale("en")
    saved = i18n._locale_cache.get("en")
    i18n._locale_cache["en"] = {"test.numeric": 42}
    try:
        assert i18n.t("test.numeric", x=1) == "42"
    finally:
        if saved is None:
            i18n._locale_cache.pop("en", None)
        else:
            i18n._locale_cache["en"] = saved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])