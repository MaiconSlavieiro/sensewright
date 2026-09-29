"""Tests for the debug HUD (in-game proof the loop is alive)."""

from __future__ import annotations

import pytest

from sensewright_mod import hud, i18n


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """Isolate state and capture notifications instead of touching the UI."""
    hud.reset()
    hud.set_enabled(False)
    seen = []
    monkeypatch.setattr(hud, "notify", lambda message: seen.append(message) or True)
    yield seen
    hud.reset()
    hud.set_enabled(False)


def test_disabled_by_default_and_silent(_clean):
    assert hud.is_enabled() is False

    hud.note_heartbeat(tick_result={"ok": True}, pull_result={"intents": []}, sims=5)

    assert _clean == []


def test_enabled_emits_heartbeat_line(_clean):
    hud.set_enabled(True)

    hud.note_heartbeat(tick_result={"ok": True}, pull_result={"intents": []}, sims=12)

    assert _clean
    assert any("sidecar" in message for message in _clean)
    assert any("#1" in message for message in _clean)


def test_sidecar_flip_emits_connected_then_lost(_clean):
    hud.set_enabled(True)

    # Establish the sidecar as down, then up, then down again.
    hud.note_heartbeat(tick_result=None, pull_result=None)
    hud.note_heartbeat(tick_result={"ok": True}, pull_result={"intents": []})
    hud.note_heartbeat(tick_result=None, pull_result=None)

    joined = " | ".join(_clean)
    assert "connected" in joined
    assert "LOST" in joined


def test_note_intent_counts_even_when_disabled(_clean):
    hud.note_intent({"kind": "speak", "name": "say_to"}, {"ok": True})

    assert _clean == []
    assert "1/1" in hud.render_status()


def test_note_intent_traces_when_enabled(_clean):
    hud.set_enabled(True)

    hud.note_intent({"kind": "speak", "name": "say_to"}, {"ok": False, "error": "not_implemented"})

    assert any("say_to" in message for message in _clean)
    assert any("not_implemented" in message for message in _clean)


def test_render_status_reports_state_and_counters(_clean):
    hud.set_enabled(True)
    hud.note_heartbeat(tick_result={"ok": True}, pull_result={"intents": [{"id": "x"}]}, sims=7)

    status = hud.render_status()

    assert "Sensewright HUD" in status
    assert "7" in status
    assert "pulled 1" in status


def test_emit_line_native_when_sidecar_down(_clean):
    hud.set_enabled(True)

    hud.emit_line()

    assert any("OFF" in message for message in _clean)


def test_sidecar_state_error_is_reported(_clean):
    hud.set_enabled(True)

    hud.note_heartbeat(tick_result=None, pull_result=None, sidecar_state="error")

    assert any("ERROR" in message for message in _clean)
    assert "ERR" in hud.render_status()


def test_explicit_sidecar_state_overrides_inference(_clean):
    hud.set_enabled(True)

    # No results, but the caller probed health and knows the sidecar is up.
    hud.note_heartbeat(tick_result=None, pull_result=None, sidecar_state="on")

    assert any("sidecar ON" in message for message in _clean)


def test_line_uses_canonical_sidecar_token_not_localized_word(_clean):
    """M7: {sidecar} must receive ON even when the locale word differs."""
    i18n.set_locale("pt-BR")
    try:
        hud.set_enabled(True)
        hud.note_heartbeat(tick_result={"ok": True},
                           pull_result={"intents": []}, sims=3)

        joined = " ".join(_clean)
        assert "sidecar ON" in joined
        assert "LIGADO" not in joined
        assert "ON" in hud.render_status()
    finally:
        i18n.set_locale("en")
