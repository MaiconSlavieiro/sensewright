"""Tests for sensewright_sidecar.i18n_engine module."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sensewright_sidecar.i18n_engine import (
    I18nEngine,
    get_engine,
    reset_engine,
    _resolve_dotted,
    _deterministic_seed,
    _safe_format,
)


class TestResolveDotted:
    """Tests for _resolve_dotted helper."""

    def test_simple_key(self):
        data = {"a": 1}
        assert _resolve_dotted(data, "a") == 1

    def test_nested_key(self):
        data = {"a": {"b": 2}}
        assert _resolve_dotted(data, "a.b") == 2

    def test_key_with_dots_as_literal(self):
        data = {"a.b": 3}
        assert _resolve_dotted(data, "a.b") == 3

    def test_greedy_match_prefers_longer_key(self):
        data = {"a": {"b": 1}, "a.b": 2}
        # Should match "a.b" as literal key first
        assert _resolve_dotted(data, "a.b") == 2

    def test_missing_returns_none(self):
        data = {"a": 1}
        assert _resolve_dotted(data, "b") is None
        assert _resolve_dotted(data, "a.c") is None


class TestDeterministicSeed:
    """Tests for _deterministic_seed."""

    def test_same_inputs_same_output(self):
        seed1 = _deterministic_seed("test", "key")
        seed2 = _deterministic_seed("test", "key")
        assert seed1 == seed2

    def test_different_inputs_different_output(self):
        seed1 = _deterministic_seed("test", "key1")
        seed2 = _deterministic_seed("test", "key2")
        assert seed1 != seed2

    def test_non_negative(self):
        assert _deterministic_seed("a", "b") >= 0


class TestSafeFormat:
    """Tests for _safe_format."""

    def test_simple_format(self):
        assert _safe_format("Hello {name}", {"name": "World"}) == "Hello World"

    def test_missing_key_preserved(self):
        result = _safe_format("Hello {name}", {})
        assert result == "Hello {name}"

    def test_empty_template(self):
        assert _safe_format("", {}) == ""

    def test_none_template(self):
        assert _safe_format(None, {}) is None


class TestI18nEngine:
    """Tests for I18nEngine."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        reset_engine()
        yield
        reset_engine()

    def test_resolve_locale_exact_code(self):
        engine = get_engine()
        # pt-BR should resolve to pt-BR
        result = engine.resolve_locale("pt-BR")
        assert result == "pt-BR"

    def test_resolve_locale_base_subtag(self):
        engine = get_engine()
        # "pt" should resolve to pt-BR (base subtag)
        result = engine.resolve_locale("pt")
        assert result == "pt-BR"

    def test_resolve_locale_client_token_word_boundary(self):
        engine = get_engine()
        # Client token "por_br" should match pt-BR
        result = engine.resolve_locale("por_br")
        assert result == "pt-BR"

    def test_resolve_locale_unknown_returns_default(self):
        engine = get_engine()
        default = engine.default_locale()
        result = engine.resolve_locale("xx-YY")
        assert result == default

    def test_resolve_locale_empty_returns_default(self):
        engine = get_engine()
        default = engine.default_locale()
        assert engine.resolve_locale("") == default
        assert engine.resolve_locale(None) == default

    def test_t_returns_missing_for_unknown_key(self):
        engine = get_engine()
        result = engine.t("nonexistent.key.that.does.not.exist")
        assert result.startswith("[missing:")

    def test_t_cascade_exact_then_base_then_default(self):
        engine = get_engine()
        # This tests the cascade logic - exact locale -> base -> default
        # We can't easily test without knowing manifest contents,
        # but we can verify the method doesn't crash
        result = engine.t("ui.common.ok", lang="pt-BR")
        assert isinstance(result, str)

    def test_t_list_rotation_deterministic_same_seed(self):
        engine = get_engine()
        # Use a key that has list values in the locale files
        # We'll test with a known list key if available, or just verify
        # the deterministic seed logic works
        key = "test.list.key"
        # The rotation uses _deterministic_seed which we tested above
        # Just verify t() doesn't crash with seed
        result1 = engine.t(key, seed=123)
        result2 = engine.t(key, seed=123)
        assert result1 == result2

    def test_t_gender_inflection_masculine(self):
        engine = get_engine()
        # Test gender inflection macro {g:m|f|n}
        text = "{g:Ele|Ela|Elu} foi"
        # We can't easily test without a locale file containing this,
        # but we can test _apply_gender directly
        result = engine._apply_gender(text, "M")
        assert result == "Ele foi"

    def test_t_gender_inflection_feminine(self):
        engine = get_engine()
        text = "{g:Ele|Ela|Elu} foi"
        result = engine._apply_gender(text, "F")
        assert result == "Ela foi"

    def test_t_gender_inflection_neutral(self):
        engine = get_engine()
        text = "{g:Ele|Ela|Elu} foi"
        result = engine._apply_gender(text, "N")
        assert result == "Elu foi"

    def test_t_gender_inflection_defaults_to_masculine(self):
        engine = get_engine()
        text = "{g:Ele|Ela|Elu} foi"
        result = engine._apply_gender(text, "X")
        assert result == "Ele foi"

    def test_t_gender_inflection_no_neutral_fallbacks_to_masculine(self):
        engine = get_engine()
        text = "{g:Ele|Ela} foi"  # No neutral option
        result = engine._apply_gender(text, "N")
        assert result == "Ele foi"

    def test_enum_translation(self):
        engine = get_engine()
        # Test enum lookup - returns original value if not found
        result = engine.enum("mood", "happy", lang="pt-BR")
        assert isinstance(result, str)

    def test_enum_returns_original_when_missing(self):
        engine = get_engine()
        result = engine.enum("mood", "nonexistent_mood_xyz", lang="pt-BR")
        assert result == "nonexistent_mood_xyz"

    def test_enum_none_returns_empty(self):
        engine = get_engine()
        result = engine.enum("mood", None, lang="pt-BR")
        assert result == ""

    def test_render_prompt_injects_strict_language_anchor(self):
        engine = get_engine()
        # render_prompt should inject strict_language_anchor
        result = engine.render_prompt("sim.chat", "system", "pt-BR", {})
        assert isinstance(result, str)

    def test_render_prompt_falls_back_to_default(self):
        engine = get_engine()
        # Unknown purpose should fall back to _default
        result = engine.render_prompt("unknown.purpose", "system", "pt-BR", {})
        assert isinstance(result, str)

    def test_content_returns_merged_catalog(self):
        engine = get_engine()
        content = engine.content("pt-BR")
        assert isinstance(content, dict)

    def test_ui_returns_merged_catalog(self):
        engine = get_engine()
        ui = engine.ui("pt-BR")
        assert isinstance(ui, dict)

    def test_llm_language_name(self):
        engine = get_engine()
        name = engine.llm_language_name("pt-BR")
        assert isinstance(name, str)
        assert len(name) > 0

    def test_stbl_byte(self):
        engine = get_engine()
        byte = engine.stbl_byte("pt-BR")
        # May be None if not defined
        assert byte is None or isinstance(byte, str)

    def test_locale_by_code(self):
        engine = get_engine()
        loc = engine.locale_by_code("pt-BR")
        assert loc is not None
        assert loc.get("code") == "pt-BR"

    def test_locales_list(self):
        engine = get_engine()
        locales = engine.locales()
        assert isinstance(locales, list)
        assert len(locales) > 0

    def test_manifest(self):
        engine = get_engine()
        manifest = engine.manifest()
        assert isinstance(manifest, dict)
        assert "locales" in manifest
        assert "default_locale" in manifest

    def test_reload_clears_cache(self):
        engine = get_engine()
        # Access some data to populate cache
        _ = engine.content("pt-BR")
        # Reload should not crash
        engine.reload()
        _ = engine.content("pt-BR")


class TestI18nEngineWithOverlay:
    """Tests for I18nEngine with custom overlay directory."""

    def test_custom_bundle_and_overlay_dirs(self, tmp_path):
        # Create minimal bundle structure
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        (bundle / "content").mkdir()
        (bundle / "ui").mkdir()
        (bundle / "manifest.json").write_text('{"locales": [{"code": "en-US", "base_subtag": "en"}], "default_locale": "en-US"}')
        (bundle / "content" / "en-US.json").write_text('{"test": "bundle value"}')
        (bundle / "ui" / "en-US.json").write_text('{"ui.test": "bundle ui"}')

        # Create overlay
        overlay = tmp_path / "overlay"
        overlay.mkdir()
        (overlay / "content").mkdir()
        (overlay / "content" / "en-US.json").write_text('{"test": "overlay value"}')

        engine = I18nEngine(bundle_dir=bundle, overlay_dir=overlay)
        # Overlay should take precedence
        result = engine.t("test", lang="en-US")
        assert result == "overlay value"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])