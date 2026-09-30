"""Tests for the notification/chat UI helpers (render fallback path)."""

import os
import sys

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest

from sensewright_mod import chat_ui, i18n


@pytest.fixture(autouse=True)
def _reset_locale():
    i18n.set_locale("en")
    yield
    i18n.set_locale("en")


class _FakeSimInfo:
    def __init__(self, instance):
        self._instance = instance

    def get_sim_instance(self):
        return self._instance


def test_notification_owner_prefers_live_instance():
    instance = object()
    owner = chat_ui._notification_owner(_FakeSimInfo(instance))

    assert owner is instance


def test_notification_owner_falls_back_to_sim_info():
    sim_info = _FakeSimInfo(None)

    assert chat_ui._notification_owner(sim_info) is sim_info


def test_notification_owner_without_services_is_none():
    assert chat_ui._notification_owner(None) is None


def test_notification_diagnostics_reports_build_failure_outside_game():
    diag = chat_ui.notification_diagnostics("Title", "Body")

    assert diag["ok"] is False
    assert diag["layer"] == "build"
    assert diag["error"]


def test_show_notification_falls_back_to_debug_log_outside_game(monkeypatch):
    # No ui/services modules outside the game: the last-resort log path runs.
    logged = []
    monkeypatch.setattr(
        chat_ui, "debug_log", lambda message: logged.append(message))

    assert chat_ui.show_notification("Title", "Body") is True

    assert any("Title" in message and "Body" in message for message in logged)


def test_show_simple_notification_uses_localized_title(monkeypatch):
    captured = {}

    def fake_show(title, text, sim_info=None, urgent=False, connection=None):
        captured["title"] = title
        captured["text"] = text
        return True

    monkeypatch.setattr(chat_ui, "show_notification", fake_show)

    chat_ui.show_simple_notification("hello")

    assert captured["title"] == i18n.t("notify.app_title")
    assert captured["text"] == "hello"


def test_show_error_uses_localized_title(monkeypatch):
    i18n.set_locale("pt-BR")
    captured = {}

    def fake_show(title, text, sim_info=None, urgent=False, connection=None):
        captured["title"] = title
        captured["urgent"] = urgent
        return True

    monkeypatch.setattr(chat_ui, "show_notification", fake_show)

    chat_ui.show_error("boom")

    assert captured["title"] == i18n.t("error.title")
    assert captured["urgent"] is True
