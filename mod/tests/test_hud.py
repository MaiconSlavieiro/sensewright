"""Tests for the debug HUD (in-game proof the loop is alive).

The HUD is quiet by default: the periodic status line and the intent traces are
**log-only**; only sidecar state flips (connected/lost/error) raise a
notification, and ``sw.hud now`` surfaces the line on demand.
"""

from __future__ import annotations

import pytest

from sensewright_mod import debug_log, hud, i18n


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Isolate state; capture notifications and log lines instead of the UI."""
    hud.reset()
    hud.set_enabled(False)
    seen = []
    logged = []
    monkeypatch.setattr(hud, "notify", lambda message: seen.append(message) or True)
    monkeypatch.setattr(debug_log, "validation_log", lambda message: logged.append(message))
    yield {"notify": seen, "log": logged}
    hud.reset()
    hud.set_enabled(False)


def test_disabled_by_default_and_silent(_clean):
    assert hud.is_enabled() is False

    hud.note_heartbeat(tick_result={"ok": True}, pull_result={"intents": []}, sims=5)

    assert _clean["notify"] == []
    assert _clean["log"] == []


def test_periodic_line_is_log_only(_clean):
    hud.set_enabled(True)

    hud.note_heartbeat(tick_result={"ok": True}, pull_result={"intents": []}, sims=12)

    assert _clean["notify"] == []
    joined = " ".join(_clean["log"])
    assert "sidecar ON" in joined
    assert "#1" in joined


def test_sidecar_flip_emits_connected_then_lost(_clean):
    hud.set_enabled(True)

    # Establish the sidecar as down, then up, then down again.
    hud.note_heartbeat(tick_result=None, pull_result=None)
    hud.note_heartbeat(tick_result={"ok": True}, pull_result={"intents": []})
    hud.note_heartbeat(tick_result=None, pull_result=None)

    joined = " | ".join(_clean["notify"])
    assert "connected" in joined
    assert "LOST" in joined


def test_note_intent_counts_even_when_disabled(_clean):
    hud.note_intent({"kind": "speak", "name": "say_to"}, {"ok": True})

    assert _clean["notify"] == []
    assert "1/1" in hud.render_status()


def test_note_intent_trace_is_log_only(_clean):
    hud.set_enabled(True)

    hud.note_intent({"kind": "speak", "name": "say_to"}, {"ok": False, "error": "not_implemented"})

    assert _clean["notify"] == []
    joined = " ".join(_clean["log"])
    assert "say_to" in joined
    assert "not_implemented" in joined


def test_render_status_reports_state_and_counters(_clean):
    hud.set_enabled(True)
    hud.note_heartbeat(tick_result={"ok": True}, pull_result={"intents": [{"id": "x"}]}, sims=7)

    status = hud.render_status()

    assert "Sensewright HUD" in status
    assert "7" in status
    assert "pulled 1" in status


def test_emit_line_notifies_when_sidecar_down(_clean):
    hud.set_enabled(True)

    hud.emit_line()

    assert any("OFF" in message for message in _clean["notify"])


def test_sidecar_state_error_is_reported(_clean):
    hud.set_enabled(True)

    hud.note_heartbeat(tick_result=None, pull_result=None, sidecar_state="error")

    assert "ERR" in hud.render_status()
    assert any("ERROR" in message for message in _clean["log"])


def test_explicit_sidecar_state_overrides_inference(_clean):
    hud.set_enabled(True)

    # No results, but the caller probed health and knows the sidecar is up.
    hud.note_heartbeat(tick_result=None, pull_result=None, sidecar_state="on")

    assert "sidecar ON" in hud.render_status()


def test_line_uses_canonical_sidecar_token_not_localized_word(_clean):
    """M7: {sidecar} must receive ON even when the locale word differs."""
    i18n.set_locale("pt-BR")
    try:
        hud.set_enabled(True)
        hud.note_heartbeat(tick_result={"ok": True},
                           pull_result={"intents": []}, sims=3)

        joined = " ".join(_clean["log"])
        assert "sidecar ON" in joined
        assert "LIGADO" not in joined
        assert "ON" in hud.render_status()
    finally:
        i18n.set_locale("en")
