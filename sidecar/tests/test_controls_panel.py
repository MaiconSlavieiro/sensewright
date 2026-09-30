"""Tests for the P1 ControlSpec promotion + ``panel.toml`` overlay.

Covers the promoted §1.4 settings (target/path mapping), the generic
``apply_values_to_settings`` / ``apply_control_values_to_settings`` helpers, the
overlay loader/serializer round-trip and the ``persist`` endpoint behaviour.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from sensewright_sidecar import content_i18n, panel_store
from sensewright_sidecar.config import Settings, load_settings
from sensewright_sidecar.god.controls import (
    CONTROL_SPEC_BY_KEY,
    apply_control_values_to_settings,
    apply_values_to_settings,
    controls_payload,
    get_control,
    list_controls,
    merge_with_defaults,
    values_from_settings,
)

_PROMOTED_KEYS = (
    "ui.language",
    "llm.temperature",
    "llm.max_tokens",
    "llm.budget_per_sim_per_day",
    "memory.consolidation_enabled",
    "memory.decay_preset",
    "memory.dejavu_chance",
    "agents.personality.absorption_enabled",
    "agents.personality.salience_threshold",
    "agents.personality.sleep_consolidation",
    "agents.evolution.enabled",
    "agents.evolution.trait_swap",
    "agents.evolution.drift_strength",
    "agents.social.max_pairs_per_tick",
    "agents.social.pair_cooldown_seconds",
    "god.backgrounds.enabled",
    "god.backgrounds.batch_size",
    "runtime.expose_roster",
)


# ─── specs ───────────────────────────────────────────────────────────────


def test_promoted_specs_have_target_and_path():
    for key in _PROMOTED_KEYS:
        spec = get_control(key)
        assert spec is not None, key
        assert spec.target, key
        assert spec.path, key
        assert spec.advanced is True, key
        assert spec.model_dump()["target"] == spec.target


def test_promoted_specs_not_restart_only():
    for key in _PROMOTED_KEYS:
        assert CONTROL_SPEC_BY_KEY[key].restart_only is False


def test_select_specs_validate_options():
    assert get_control("ui.language").validate("pt-BR") == "pt-BR"
    assert get_control("memory.decay_preset").validate("fast") == "fast"
    assert get_control("agents.evolution.trait_swap").validate("auto") == "auto"
    with pytest.raises(ValueError):
        get_control("agents.evolution.trait_swap").validate("bogus")


def test_ui_language_options_are_data_driven():
    spec = get_control("ui.language")
    assert [opt.value for opt in spec.options] == ["auto", *content_i18n.available_locales()]
    labels = {opt.value: opt.label for opt in spec.options}
    assert labels["en"] == "English"
    assert labels["pt-BR"] == "Português (Brasil)"
    # Non-language selects keep the label_key shape only (no inline label).
    other = get_control("memory.decay_preset")
    assert all(opt.label is None for opt in other.options)


def test_slider_specs_clamp_and_step():
    spec = get_control("llm.temperature")
    assert spec.validate(5.0) == 2.0
    assert spec.validate(-1.0) == 0.0
    spec = get_control("agents.social.pair_cooldown_seconds")
    assert spec.validate(200) == 210.0
    assert spec.validate(10) == 30.0


def test_restart_only_specs_hidden_by_default():
    default_keys = {spec.key for spec in list_controls()}
    assert "network.host" not in default_keys
    assert "runtime.shutdown_on_game_exit" not in default_keys

    all_keys = {spec.key for spec in list_controls(include_restart_only=True)}
    assert "network.host" in all_keys
    assert "runtime.shutdown_on_game_exit" in all_keys

    payload_keys = {entry["key"] for entry in controls_payload()}
    assert "network.host" not in payload_keys


# ─── mapping ─────────────────────────────────────────────────────────────


def test_merge_with_defaults_includes_promoted_defaults():
    values = merge_with_defaults(None)
    for key in _PROMOTED_KEYS:
        assert key in values
    assert values["llm.temperature"] == 0.8


def test_apply_values_to_settings_sets_promoted_paths():
    settings = Settings()
    applied = apply_values_to_settings(
        settings,
        {
            "llm.temperature": 1.5,
            "agents.personality.salience_threshold": 2.5,
            "god.backgrounds.batch_size": 3,
        },
    )
    assert settings.llm.temperature == 1.5
    assert settings.agents.personality.salience_threshold == 2.5
    assert settings.god.backgrounds.batch_size == 3
    assert applied["llm.temperature"] == 1.5


def test_apply_values_to_settings_ignores_god_and_agent_keys():
    settings = Settings()
    assert apply_values_to_settings(settings, {"autonomy_degree": 0.9}) == {}
    assert apply_values_to_settings(settings, {"reasoning_effort": "low"}) == {}


def test_apply_control_values_to_settings_covers_all_groups():
    settings = Settings()
    applied = apply_control_values_to_settings(
        settings,
        {
            "autonomy_degree": 0.9,
            "power_extreme_events": True,
            "impulse_frequency": 0.4,
            "layer_social": False,
            "llm.max_tokens": 1024,
        },
    )
    assert set(applied) == {
        "autonomy_degree",
        "power_extreme_events",
        "impulse_frequency",
        "layer_social",
        "llm.max_tokens",
    }
    assert settings.god.autonomy_degree == 0.9
    assert settings.god.powers["extreme_events"] is True
    assert settings.agents.initiative.impulse_frequency == 0.4
    assert settings.agents.layers.social is False
    assert settings.llm.max_tokens == 1024


def test_values_from_settings_reads_promoted_paths():
    settings = Settings()
    settings.llm.temperature = 0.95
    settings.god.backgrounds.batch_size = 4
    values = values_from_settings(settings)
    assert values["llm.temperature"] == 0.95
    assert values["god.backgrounds.batch_size"] == 4


# ─── panel_store ─────────────────────────────────────────────────────────


def test_dumps_is_valid_toml_round_trip():
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - py3.10
        import tomli as tomllib

    text = panel_store.dumps({"llm": {"temperature": 0.9}, "god": {"powers": {"gossip": True}}})
    parsed = tomllib.loads(text)
    assert parsed["llm"]["temperature"] == 0.9
    assert parsed["god"]["powers"]["gossip"] is True


def test_save_load_overrides_round_trip(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    path = panel_store.save_overrides(
        data_dir, {"llm.temperature": 1.25, "agents.social.max_pairs_per_tick": 3}
    )
    assert path.is_file()

    loaded = panel_store.load_overrides(data_dir)
    assert loaded["llm.temperature"] == 1.25
    assert loaded["agents.social.max_pairs_per_tick"] == 3.0


def test_save_overrides_merges_existing_keys(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    panel_store.save_overrides(data_dir, {"llm.temperature": 1.1})
    panel_store.save_overrides(data_dir, {"llm.max_tokens": 900})

    loaded = panel_store.load_overrides(data_dir)
    assert loaded["llm.temperature"] == 1.1
    # max_tokens steps by 64 from 128 → 900 rounds to 896.
    assert loaded["llm.max_tokens"] == 896.0


def test_save_overrides_skips_restart_only(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    panel_store.save_overrides(data_dir, {"network.host": "0.0.0.0", "llm.temperature": 1.2})

    loaded = panel_store.load_overrides(data_dir)
    assert "network.host" not in loaded
    text = panel_store.panel_path(data_dir).read_text(encoding="utf-8")
    assert "network" not in text


def test_save_overrides_rejects_unknown_key(tmp_path: Path):
    with pytest.raises(ValueError):
        panel_store.save_overrides(tmp_path, {"nope": 1})


def test_overlay_round_trip_across_sections(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    values = {
        "autonomy_degree": 0.75,
        "power_gossip": False,
        "mood_tags": ["novela", "caos"],
        "evolution_speed": "fast",
        "agents.personality.salience_threshold": 2.5,
        "agents.evolution.trait_swap": "auto",
        "agents.social.max_pairs_per_tick": 2,
        "god.backgrounds.enabled": False,
        "llm.temperature": 1.1,
    }
    panel_store.save_overrides(data_dir, values)
    loaded = panel_store.load_overrides(data_dir)

    assert loaded["autonomy_degree"] == 0.75
    assert loaded["power_gossip"] is False
    assert loaded["mood_tags"] == ["novela", "caos"]
    assert loaded["evolution_speed"] == "fast"
    assert loaded["agents.personality.salience_threshold"] == 2.5
    assert loaded["agents.evolution.trait_swap"] == "auto"
    assert loaded["god.backgrounds.enabled"] is False

    settings = Settings()
    apply_control_values_to_settings(settings, loaded)
    assert settings.god.autonomy_degree == 0.75
    assert settings.god.powers["gossip"] is False
    assert settings.god.settings["mood_tags"] == ["novela", "caos"]
    assert settings.agents.personality.salience_threshold == 2.5
    assert settings.agents.evolution.trait_swap == "auto"
    assert settings.god.backgrounds.enabled is False


def test_load_overrides_missing_file_returns_empty(tmp_path: Path):
    assert panel_store.load_overrides(tmp_path / "data") == {}


def test_load_overrides_bad_toml_returns_empty(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "panel.toml").write_text("not = [valid toml", encoding="utf-8")
    assert panel_store.load_overrides(data_dir) == {}


def test_clear_overrides(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    panel_store.save_overrides(data_dir, {"llm.temperature": 1.0})
    assert panel_store.clear_overrides(data_dir) is True
    assert panel_store.clear_overrides(data_dir) is False


# ─── load_settings overlay ───────────────────────────────────────────────


def test_load_settings_applies_panel_overlay(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "data").mkdir()
    (home / "config.toml").write_text("[llm]\ntemperature = 0.5\n", encoding="utf-8")
    panel_store.save_overrides(home / "data", {"llm.temperature": 1.75})

    monkeypatch.setenv("SENSEWRIGHT_HOME", str(home))
    settings = load_settings()
    assert settings.llm.temperature == 1.75


def test_load_settings_without_overlay_uses_config(tmp_path: Path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    (home / "data").mkdir()
    (home / "config.toml").write_text("[llm]\ntemperature = 0.5\n", encoding="utf-8")

    monkeypatch.setenv("SENSEWRIGHT_HOME", str(home))
    settings = load_settings()
    assert settings.llm.temperature == 0.5


# ─── endpoint ────────────────────────────────────────────────────────────


class TestConfigGodPersist:
    async def test_persist_writes_panel_toml(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        settings: Settings,
    ):
        resp = await client.post(
            "/v1/config/god",
            json={"settings": {"llm.temperature": 1.3}, "persist": True},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert settings.llm.temperature == 1.3
        assert panel_store.panel_path(settings.data_dir).is_file()
        assert panel_store.load_overrides(settings.data_dir)["llm.temperature"] == 1.3

    async def test_no_persist_does_not_write(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        settings: Settings,
    ):
        resp = await client.post(
            "/v1/config/god",
            json={"settings": {"llm.temperature": 1.4}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert settings.llm.temperature == 1.4
        assert not panel_store.panel_path(settings.data_dir).is_file()

    async def test_reset_panel_deletes_overlay(
        self,
        client: httpx.AsyncClient,
        auth_headers: dict[str, str],
        settings: Settings,
    ):
        panel_store.save_overrides(settings.data_dir, {"llm.temperature": 1.0})
        resp = await client.post("/v1/config/panel/reset", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert not panel_store.panel_path(settings.data_dir).is_file()

    async def test_reset_panel_requires_auth(self, client: httpx.AsyncClient):
        resp = await client.post("/v1/config/panel/reset")
        assert resp.status_code == 401
