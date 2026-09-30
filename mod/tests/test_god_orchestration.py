"""
Tests for the God-orchestration loop (Phase 5c): the mod-side tick that pulls
the God directives from the sidecar and executes them, plus the ``sw.god``
control command. Fully offline: the sidecar and the game are faked; no network.

Run with the system Python (3.10+).
"""

import json
import os
import sys
import time
import urllib.request
from unittest.mock import patch

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

from sensewright_mod import http_client, main, state_collector


class MockResponse(object):
    def __init__(self, data, status=200):
        self._data = json.dumps(data).encode("utf-8")
        self.status = status

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def _sent_payload(mock_urlopen):
    request = mock_urlopen.call_args[0][0]
    return request.full_url, json.loads(request.data.decode("utf-8"))


# --- http_client ---

def test_god_tick_posts_sim_and_context():
    with patch("urllib.request.urlopen",
               return_value=MockResponse({"ok": True, "directives": []})) as mock_urlopen:
        result = http_client.god_tick(
            {"player_id": "local", "save_id": "s1", "sim_id": 7},
            "evening", "community", "pt-BR",
        )

    assert result["ok"] is True
    url, payload = _sent_payload(mock_urlopen)
    assert url.endswith("/v1/god/tick")
    assert payload["sim"]["sim_id"] == 7
    assert payload["time_of_day"] == "evening"
    assert payload["lot_type"] == "community"
    assert payload["lang"] == "pt-BR"


def test_set_god_controls_posts_only_provided_fields():
    with patch("urllib.request.urlopen",
               return_value=MockResponse({"ok": True})) as mock_urlopen:
        http_client.set_god_controls(
            preset="caos", enabled=True, values={"intensity": "0.9"},
            persist=True,
        )

    url, payload = _sent_payload(mock_urlopen)
    assert url.endswith("/v1/config/god")
    assert payload["preset"] == "caos"
    assert payload["enabled"] is True
    assert payload["settings"] == {"intensity": "0.9"}
    assert payload["persist"] is True


# --- state_collector: tick + execution ---

def _reset_god_clock():
    state_collector._GOD_TICK["last"] = 0.0


def test_maybe_god_tick_executes_tool_call_and_narration(monkeypatch):
    _reset_god_clock()
    monkeypatch.setattr(state_collector.sim_context, "_get_active_sim_info",
                        lambda: None)
    monkeypatch.setattr(state_collector.sim_context, "_get_save_id",
                        lambda: "save-1")
    monkeypatch.setattr(state_collector, "_zone_time_of_day", lambda: "night")
    monkeypatch.setattr(state_collector, "_lot_type", lambda: "residential")

    directive = {
        "id": "god-1", "type": "apply_trait", "target_sim": 2,
        "narration": "A storm brews.", "payload": {},
        "tool_call": {"id": "god-1", "name": "add_buff",
                      "args": {"sim_id": 2, "buff_name": "spooked"}},
    }
    monkeypatch.setattr(http_client, "god_tick",
                        lambda *a, **k: {"ok": True, "preset": "terror",
                                         "directives": [directive]})

    executed = []
    monkeypatch.setattr(state_collector.tool_executor, "execute",
                        lambda call: executed.append(call) or {"ok": True})

    shown = []
    monkeypatch.setattr(
        state_collector.chat_ui, "show_simple_notification",
        lambda message, sim_info=None: shown.append(message) or True)

    result = state_collector.maybe_god_tick(force=True)

    assert result["preset"] == "terror"
    assert executed == [directive["tool_call"]]
    assert any("A storm brews." in message for message in shown)


def test_maybe_god_tick_surfaces_world_event_without_tool_call(monkeypatch):
    _reset_god_clock()
    monkeypatch.setattr(state_collector.sim_context, "_get_active_sim_info",
                        lambda: None)
    monkeypatch.setattr(state_collector.sim_context, "_get_save_id", lambda: "")
    monkeypatch.setattr(state_collector, "_zone_time_of_day", lambda: "unknown")
    monkeypatch.setattr(state_collector, "_lot_type", lambda: "residential")

    monkeypatch.setattr(http_client, "god_tick",
                        lambda *a, **k: {"ok": True, "preset": "caos",
                                         "directives": [{
                                             "id": "god-2", "type": "extreme_event",
                                             "narration": "A fire breaks out!",
                                             "tool_call": None}]})

    executed = []
    monkeypatch.setattr(state_collector.tool_executor, "execute",
                        lambda call: executed.append(call) or {"ok": True})
    shown = []
    monkeypatch.setattr(
        state_collector.chat_ui, "show_simple_notification",
        lambda message, sim_info=None: shown.append(message) or True)

    state_collector.maybe_god_tick(force=True)

    assert executed == []
    assert any("A fire breaks out!" in message for message in shown)


def test_maybe_god_tick_throttles_without_force(monkeypatch):
    calls = []
    monkeypatch.setattr(http_client, "god_tick",
                        lambda *a, **k: calls.append("tick") or {"ok": True})
    state_collector._GOD_TICK["last"] = time.monotonic()

    assert state_collector.maybe_god_tick() is None
    assert calls == []


def test_maybe_god_tick_tolerates_unreachable_sidecar(monkeypatch):
    _reset_god_clock()
    monkeypatch.setattr(state_collector.sim_context, "_get_active_sim_info",
                        lambda: None)
    monkeypatch.setattr(state_collector.sim_context, "_get_save_id", lambda: "")

    def boom(*args, **kwargs):
        raise http_client.SidecarUnreachable("down")

    monkeypatch.setattr(http_client, "god_tick", boom)

    assert state_collector.maybe_god_tick(force=True) is None


def test_execute_god_directives_tolerates_executor_failure(monkeypatch):
    def boom(call):
        raise RuntimeError("game exploded")

    monkeypatch.setattr(state_collector.tool_executor, "execute", boom)
    directive = {"id": "g", "type": "apply_trait", "narration": "",
                 "tool_call": {"id": "g", "name": "add_trait", "args": {}}}

    results = state_collector.execute_god_directives([directive])

    assert results == [{"ok": False, "error": "execution_failed"}]


def test_maybe_god_tick_tolerates_executor_failure(monkeypatch):
    _reset_god_clock()
    monkeypatch.setattr(state_collector.sim_context, "_get_active_sim_info",
                        lambda: None)
    monkeypatch.setattr(state_collector.sim_context, "_get_save_id",
                        lambda: "save-1")
    monkeypatch.setattr(http_client, "god_tick",
                        lambda *a, **k: {"ok": True, "preset": "caos",
                                         "directives": [{
                                             "id": "g", "type": "apply_trait",
                                             "narration": "",
                                             "tool_call": {"id": "g",
                                                           "name": "add_trait",
                                                           "args": {}}}]})

    def boom(call):
        raise RuntimeError("game exploded")

    monkeypatch.setattr(state_collector.tool_executor, "execute", boom)

    result = state_collector.maybe_god_tick(force=True)

    assert result["ok"] is True


def test_execute_god_directives_skips_bad_input(monkeypatch):
    shown = []
    monkeypatch.setattr(
        state_collector.chat_ui, "show_simple_notification",
        lambda message, sim_info=None: shown.append(message) or True)

    assert state_collector.execute_god_directives(None) == []
    assert state_collector.execute_god_directives([None, "x", 3]) == []
    assert shown == []


# --- main.cmd_god ---

def _capture_output(monkeypatch):
    out = []
    monkeypatch.setattr(main, "_output", lambda connection, message: out.append(message))
    monkeypatch.setattr(main, "_note_player_active", lambda sim_id=0: None)
    return out


def test_cmd_god_on_and_off(monkeypatch):
    out = _capture_output(monkeypatch)
    calls = []
    monkeypatch.setattr(main, "set_god_controls",
                        lambda **kwargs: calls.append(kwargs) or {"ok": True})

    main.cmd_god("on")
    main.cmd_god("off")

    assert calls == [{"enabled": True}, {"enabled": False}]
    assert len(out) == 2


def test_cmd_god_preset_enables(monkeypatch):
    out = _capture_output(monkeypatch)
    calls = []
    monkeypatch.setattr(main, "set_god_controls",
                        lambda **kwargs: calls.append(kwargs) or {"ok": True})

    main.cmd_god("preset", "caos")

    assert calls == [{"preset": "caos", "enabled": True}]
    assert out


def test_cmd_god_bare_preset_name(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "_output", lambda connection, message: None)
    monkeypatch.setattr(main, "_note_player_active", lambda sim_id=0: None)
    monkeypatch.setattr(main, "set_god_controls",
                        lambda **kwargs: calls.append(kwargs) or {"ok": True})

    main.cmd_god("novela")

    assert calls == [{"preset": "novela", "enabled": True}]


def test_cmd_god_rejects_unknown_preset(monkeypatch):
    out = _capture_output(monkeypatch)
    calls = []
    monkeypatch.setattr(main, "set_god_controls",
                        lambda **kwargs: calls.append(kwargs) or {"ok": True})

    main.cmd_god("preset", "nope")

    assert calls == []
    assert out


def test_cmd_god_set_value(monkeypatch):
    out = _capture_output(monkeypatch)
    calls = []
    monkeypatch.setattr(main, "set_god_controls",
                        lambda **kwargs: calls.append(kwargs) or {"ok": True})

    main.cmd_god("set", "intensity", "0.9")

    assert calls == [{"values": {"intensity": "0.9"}}]
    assert out


def test_cmd_god_set_reports_invalid_control(monkeypatch):
    out = _capture_output(monkeypatch)
    monkeypatch.setattr(main, "set_god_controls",
                        lambda **kwargs: {"ok": False, "detail": "unknown control: nope"})

    main.cmd_god("set", "nope", "1")

    assert out and "nope" in out[0]


def test_cmd_god_tick_reports_directives(monkeypatch):
    out = _capture_output(monkeypatch)
    monkeypatch.setattr(
        state_collector, "maybe_god_tick",
        lambda force=False: {"ok": True, "preset": "novela",
                             "directives": [{"id": "g1"}, {"id": "g2"}]})

    main.cmd_god("tick")

    assert out


def test_cmd_god_scan_maps_neighborhood(monkeypatch):
    out = _capture_output(monkeypatch)
    calls = []
    monkeypatch.setattr(
        state_collector, "scan_neighborhood",
        lambda force=False: calls.append(force) or {
            "ok": True, "sims": 4, "households": 2, "queued": 6})

    main.cmd_god("scan")

    assert calls == [True]
    assert out


def test_cmd_god_tick_surfaces_failure(monkeypatch):
    out = _capture_output(monkeypatch)
    monkeypatch.setattr(state_collector, "maybe_god_tick",
                        lambda force=False: {"ok": False})

    main.cmd_god("tick")

    assert out


def test_cmd_god_summary_shows_preset(monkeypatch):
    out = _capture_output(monkeypatch)
    monkeypatch.setattr(
        main, "get_god_controls",
        lambda: {"controls": [{"key": "intensity", "kind": "slider",
                               "label_key": "god.control.intensity.label",
                               "default": 0.5}],
                 "values": {"intensity": 0.5, "preset": "sitcom"}})

    main.cmd_god()

    assert any("sitcom" in message for message in out)


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
