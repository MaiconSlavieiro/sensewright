"""Tests for sensewright_sidecar.config module."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sensewright_sidecar.config import (
    Config,
    DEFAULT_CONFIG,
    load_config,
    reset_config,
    get_config,
    _deep_merge,
    _normalize_provider_limits,
)


class TestDeepMerge:
    """Tests for the internal _deep_merge helper."""

    def test_simple_merge(self):
        base = {"a": 1, "b": {"x": 10}}
        overlay = {"b": {"y": 20}, "c": 3}
        result = _deep_merge(base, overlay)
        assert result == {"a": 1, "b": {"x": 10, "y": 20}, "c": 3}

    def test_overlay_replaces_non_dict(self):
        base = {"a": {"nested": 1}}
        overlay = {"a": "replaced"}
        result = _deep_merge(base, overlay)
        assert result == {"a": "replaced"}

    def test_base_unchanged(self):
        base = {"a": 1}
        overlay = {"b": 2}
        _deep_merge(base, overlay)
        assert base == {"a": 1}  # base not mutated


class TestNormalizeProviderLimits:
    """Tests for _normalize_provider_limits."""

    def test_adds_missing_limit_fields(self):
        providers = {
            "openrouter": {"enabled": True, "models": ["m1"]},
            "gemini": {"enabled": False, "models": ["m2"], "rpm": 10},
        }
        result = _normalize_provider_limits(providers)
        for cfg in result.values():
            assert "rpm" in cfg
            assert "rpd" in cfg
            assert "tpm" in cfg
            assert cfg["rpm"] >= 0
            assert cfg["rpd"] >= 0
            assert cfg["tpm"] >= 0

    def test_preserves_existing_limits(self):
        providers = {"test": {"enabled": True, "models": ["m"], "rpm": 5, "rpd": 100, "tpm": 1000}}
        result = _normalize_provider_limits(providers)
        assert result["test"]["rpm"] == 5
        assert result["test"]["rpd"] == 100
        assert result["test"]["tpm"] == 1000


class TestConfigLoad:
    """Tests for Config.load_config and Config class."""

    def test_load_config_defaults_when_no_file(self, tmp_path):
        # Point to a non-existent file
        config = load_config(str(tmp_path / "nonexistent.toml"))
        assert isinstance(config, Config)
        # Check defaults are present
        assert config.server_host == "127.0.0.1"
        assert config.server_port == 8765
        assert config.free_only is True
        assert config.embeddings == "none"

    def test_load_config_merges_file(self, tmp_path):
        config_file = tmp_path / "config.toml"
        config_file.write_text("""
[server]
port = 9999

[llm]
free_only = false
""")
        config = load_config(str(config_file))
        assert config.server_port == 9999
        assert config.free_only is False
        # Unspecified defaults remain
        assert config.server_host == "127.0.0.1"

    def test_providers_returns_dict(self):
        config = load_config()
        providers = config.providers()
        assert isinstance(providers, dict)
        assert "openrouter" in providers
        assert "gemini" in providers

    def test_enabled_providers_filters(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.toml"))
        # By default none are enabled
        assert config.enabled_providers() == []

    def test_provider_lookup(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.toml"))
        provider = config.provider("openrouter")
        assert provider.get("base_url") == "https://openrouter.ai/api/v1"
        assert provider.get("models") == ["openai/gpt-4o-mini"]

    def test_route_for_returns_default_when_missing(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.toml"))
        route = config.route_for("unknown.purpose")
        assert route == config.route_for("default")

    def test_route_for_returns_specific(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.toml"))
        route = config.route_for("default")
        assert route.get("provider") == "openrouter"
        assert route.get("model") == "openai/gpt-4o-mini"

    def test_tier_lookup(self):
        config = load_config()
        tier = config.tier("interactive")
        assert tier.get("slo_seconds") == 3.0
        assert tier.get("max_input_tokens") == 1500

    def test_tier_missing_returns_empty(self):
        config = load_config()
        tier = config.tier("nonexistent")
        assert tier == {}

    def test_gameplay_getter(self):
        config = load_config()
        assert config.gameplay("agent_seats") == 12
        assert config.gameplay("unknown", "default") == "default"

    def test_god_getter(self):
        config = load_config()
        assert config.god("preset") == "novela"
        assert config.god("unknown", "default") == "default"

    def test_raw_returns_full_dict(self):
        config = load_config()
        raw = config.raw()
        assert "server" in raw
        assert "llm" in raw
        assert "gameplay" in raw
        assert "god" in raw


class TestConfigSingleton:
    """Tests for get_config and reset_config."""

    def test_get_config_returns_singleton(self):
        reset_config()
        c1 = get_config()
        c2 = get_config()
        assert c1 is c2

    def test_reset_config_clears_singleton(self):
        reset_config()
        c1 = get_config()
        reset_config()
        c2 = get_config()
        assert c1 is not c2


class TestDefaultConfigStructure:
    """Verify DEFAULT_CONFIG has expected structure."""

    def test_has_all_top_level_keys(self):
        assert "server" in DEFAULT_CONFIG
        assert "llm" in DEFAULT_CONFIG
        assert "gameplay" in DEFAULT_CONFIG
        assert "god" in DEFAULT_CONFIG

    def test_llm_has_providers_routes_tiers(self):
        llm = DEFAULT_CONFIG["llm"]
        assert "providers" in llm
        assert "routes" in llm
        assert "tiers" in llm

    def test_all_providers_have_required_fields(self):
        for name, cfg in DEFAULT_CONFIG["llm"]["providers"].items():
            assert "enabled" in cfg
            assert "base_url" in cfg
            assert "api_key" in cfg
            assert "models" in cfg
            assert "rpm" in cfg
            assert "rpd" in cfg
            assert "tpm" in cfg

    def test_tiers_have_required_fields(self):
        for name, cfg in DEFAULT_CONFIG["llm"]["tiers"].items():
            assert "slo_seconds" in cfg
            assert "max_input_tokens" in cfg
            assert "max_output_tokens" in cfg
            assert "concurrency" in cfg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])