"""Tests for sensewright_sidecar.god modules."""
from __future__ import annotations

import pytest

from sensewright_sidecar.config import Config, DEFAULT_CONFIG
from sensewright_sidecar.god.controls import (
    get_controls,
    set_control,
    resolve_dial,
    resolve_mode,
    current_preset,
    PRESET_DIALS,
    GOD_DIALS,
    GOD_MODES,
    GOD_PRESETS,
    POWERS,
)
from sensewright_sidecar.god.coordinator import (
    player_lock,
    is_player_locked,
    lease_for,
    can_god_puppeteer,
    is_sovereign_agent,
    set_catalyst_lease,
    clear_catalyst_lease,
    LEASE_PLAYER_MANUAL,
    LEASE_GOD_CATALYST_PUPPET,
    LEASE_SOVEREIGN_AGENT,
)
from sensewright_sidecar.god.arcs import (
    create_arc,
    current_beat,
    advance_arc,
    steer_arc,
    ARC_DRAFT,
    ARC_ACTIVE,
    ARC_DONE,
    ARC_ABORTED,
)
from sensewright_sidecar.panel_store import PanelStore
from sensewright_sidecar.state import AppState, reset_state
import tempfile
from pathlib import Path


class TestGodControls:
    """Tests for god.controls."""

    @pytest.fixture
    def panel_and_config(self, tmp_path):
        panel = PanelStore(tmp_path)
        import copy
        raw = copy.deepcopy(DEFAULT_CONFIG)
        config = Config(raw)
        return panel, config

    def test_get_controls_includes_dials_preset_mode(self, panel_and_config):
        panel, config = panel_and_config
        controls = get_controls(panel, config)
        control_keys = {c["key"] for c in controls}

        # Check dials
        for dial in GOD_DIALS:
            assert dial in control_keys

        # Check preset
        assert "preset" in control_keys

        # Check director_mode
        assert "director_mode" in control_keys

        # Check spoiler_shield
        assert "spoiler_shield" in control_keys

        # Check free_only
        assert "free_only" in control_keys

        # Check powers
        for power in POWERS:
            assert f"power.{power}" in control_keys

    def test_set_control_dial_persists(self, panel_and_config):
        panel, config = panel_and_config
        ok = set_control(panel, config, "intensity", 0.75)
        assert ok is True
        assert panel.get("intensity") == 0.75

    def test_set_control_dial_clamped(self, panel_and_config):
        panel, config = panel_and_config
        set_control(panel, config, "intensity", 1.5)
        assert panel.get("intensity") == 1.0
        set_control(panel, config, "intensity", -0.5)
        assert panel.get("intensity") == 0.0

    def test_set_control_preset(self, panel_and_config):
        panel, config = panel_and_config
        ok = set_control(panel, config, "preset", "sitcom")
        assert ok is True
        assert panel.get("preset") == "sitcom"

    def test_set_control_invalid_preset_rejected(self, panel_and_config):
        panel, config = panel_and_config
        ok = set_control(panel, config, "preset", "invalid")
        assert ok is False

    def test_set_control_director_mode(self, panel_and_config):
        panel, config = panel_and_config
        ok = set_control(panel, config, "director_mode", "CO_DIRECTOR")
        assert ok is True
        assert panel.get("director_mode") == "CO_DIRECTOR"

    def test_set_control_spoiler_shield(self, panel_and_config):
        panel, config = panel_and_config
        ok = set_control(panel, config, "spoiler_shield", False)
        assert ok is True
        assert panel.get("spoiler_shield") is False

    def test_set_control_free_only(self, panel_and_config):
        panel, config = panel_and_config
        ok = set_control(panel, config, "free_only", False)
        assert ok is True
        assert panel.get("free_only") is False

    def test_set_control_power(self, panel_and_config):
        panel, config = panel_and_config
        ok = set_control(panel, config, "power.dream_whispers", False)
        assert ok is True
        powers = panel.get("powers") or {}
        assert powers["dream_whispers"] is False

    def test_resolve_dial_override_wins(self, panel_and_config):
        panel, config = panel_and_config
        panel.set("intensity", 0.9)
        value = resolve_dial(panel, config, "intensity")
        assert value == 0.9

    def test_resolve_dial_preset_default(self, panel_and_config):
        panel, config = panel_and_config
        panel.set("preset", "sitcom")
        value = resolve_dial(panel, config, "intensity")
        assert value == PRESET_DIALS["sitcom"]["intensity"]

    def test_resolve_dial_config_fallback(self, panel_and_config):
        panel, config = panel_and_config
        # No panel override, preset defaults to "novela" -> preset default
        value = resolve_dial(panel, config, "intensity")
        # novela preset has intensity=0.7
        assert value == 0.7
        # If we set preset to "off", it uses "off" preset values (intensity=0.0)
        panel.set("preset", "off")
        value = resolve_dial(panel, config, "intensity")
        assert value == 0.0  # "off" preset has intensity=0.0
        # For a dial not in any preset, it falls back to config
        # (all current dials are in presets, so this is theoretical)

    def test_resolve_mode(self, panel_and_config):
        panel, config = panel_and_config
        panel.set("director_mode", "SANDBOX")
        assert resolve_mode(panel, config) == "SANDBOX"

    def test_current_preset(self, panel_and_config):
        panel, config = panel_and_config
        panel.set("preset", "drama")
        assert current_preset(panel, config) == "drama"

    def test_current_preset_fallback_to_config(self, panel_and_config):
        panel, config = panel_and_config
        assert current_preset(panel, config) == config.god("preset", "novela")


class TestGodCoordinator:
    """Tests for god.coordinator."""

    @pytest.fixture
    def state(self):
        reset_state()
        state = AppState()
        yield state
        reset_state()

    def test_player_lock_and_is_locked(self, state):
        player_lock(state, 1, 10.0)
        assert is_player_locked(state, 1) is True
        assert is_player_locked(state, 2) is False

    def test_lease_for_player_lock_wins(self, state):
        player_lock(state, 1, 10.0)
        state.catalyst_leases[1] = {"objective": "test", "lease_expires_tick": 1000}
        assert lease_for(state, 1) == LEASE_PLAYER_MANUAL

    def test_lease_for_catalyst_when_no_player_lock(self, state):
        state.catalyst_leases[1] = {"objective": "test", "lease_expires_tick": 1000}
        assert lease_for(state, 1) == LEASE_GOD_CATALYST_PUPPET

    def test_lease_for_sovereign_default(self, state):
        assert lease_for(state, 1) == LEASE_SOVEREIGN_AGENT

    def test_can_god_puppeteer_catalyst_not_player_locked(self, state):
        state.catalyst_leases[1] = {"objective": "test", "lease_expires_tick": 1000}
        assert can_god_puppeteer(state, 1) is True

    def test_can_god_puppeteer_false_when_player_locked(self, state):
        player_lock(state, 1, 10.0)
        state.catalyst_leases[1] = {"objective": "test", "lease_expires_tick": 1000}
        assert can_god_puppeteer(state, 1) is False

    def test_can_god_puppeteer_false_when_not_catalyst(self, state):
        assert can_god_puppeteer(state, 1) is False

    def test_is_sovereign_agent(self, state):
        assert is_sovereign_agent(state, 1) is True
        state.catalyst_leases[1] = {"objective": "test", "lease_expires_tick": 1000}
        assert is_sovereign_agent(state, 1) is False
        player_lock(state, 1, 10.0)
        assert is_sovereign_agent(state, 1) is False

    def test_set_and_clear_catalyst_lease(self, state):
        set_catalyst_lease(state, 1, "Test objective", 100)
        assert 1 in state.catalyst_leases
        assert state.catalyst_leases[1]["objective"] == "Test objective"
        assert state.catalyst_leases[1]["lease_expires_tick"] == 1540  # 100 + 1440

        clear_catalyst_lease(state, 1)
        assert 1 not in state.catalyst_leases


class TestGodArcs:
    """Tests for god.arcs."""

    def test_create_arc(self):
        arc = create_arc("Romance", [{"id": "b1"}], [1, 2], 100)
        assert arc["theme"] == "Romance"
        assert arc["beats"] == [{"id": "b1"}]
        assert arc["current_beat_idx"] == 0
        assert arc["cast"] == [1, 2]
        assert arc["status"] == ARC_ACTIVE
        assert arc["created_sim_tick"] == 100
        assert len(arc["id"]) == 12  # uuid hex[:12]

    def test_create_arc_empty_beats_is_draft(self):
        arc = create_arc("Test", [], [1], 100)
        assert arc["status"] == ARC_DRAFT

    def test_current_beat(self):
        arc = create_arc("Test", [{"id": "b1"}, {"id": "b2"}], [1], 100)
        beat = current_beat(arc)
        assert beat == {"id": "b1"}

        arc["current_beat_idx"] = 1
        beat = current_beat(arc)
        assert beat == {"id": "b2"}

        arc["current_beat_idx"] = 2
        beat = current_beat(arc)
        assert beat is None

    def test_advance_arc(self):
        arc = create_arc("Test", [{"id": "b1"}, {"id": "b2"}], [1], 100)
        arc = advance_arc(arc)
        assert arc["current_beat_idx"] == 1
        assert arc["status"] == ARC_ACTIVE

        arc = advance_arc(arc)
        assert arc["current_beat_idx"] == 2
        assert arc["status"] == ARC_DONE

    def test_steer_arc_abort(self):
        arc = create_arc("Test", [{"id": "b1"}], [1], 100)
        arc = steer_arc(arc, "abort_arc")
        assert arc["status"] == ARC_ABORTED

    def test_steer_arc_skip_beat(self):
        arc = create_arc("Test", [{"id": "b1"}, {"id": "b2"}], [1], 100)
        arc = steer_arc(arc, "skip_beat")
        assert arc["current_beat_idx"] == 1

    def test_steer_arc_approve_beat(self):
        arc = create_arc("Test", [{"id": "b1"}], [1], 100)
        arc = steer_arc(arc, "approve_beat")
        assert arc["beats"][0]["approved"] is True

    def test_steer_arc_rewrite_beat(self):
        arc = create_arc("Test", [{"id": "b1"}], [1], 100)
        arc = steer_arc(arc, "rewrite_beat", custom_instruction="Make it dramatic")
        assert arc["beats"][0]["rewrite_instruction"] == "Make it dramatic"

    def test_steer_arc_unknown_action_no_change(self):
        arc = create_arc("Test", [{"id": "b1"}], [1], 100)
        original = dict(arc)
        arc = steer_arc(arc, "unknown_action")
        assert arc == original


if __name__ == "__main__":
    pytest.main([__file__, "-v"])