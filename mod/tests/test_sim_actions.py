"""
Offline tests for the per-Sim pie-menu actions (``sim_actions.py``).

No game and no sidecar: the HTTP calls, dialogs and notifications are faked.
The public functions must never raise and must surface a notification in every
outcome.

Run with the system Python (3.10+).
"""

import os
import sys

mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

from sensewright_mod import sim_actions  # noqa: E402


class FakeSimInfo:
    def __init__(self, name="Ana"):
        self.full_name = name


class Recorder:
    def __init__(self):
        self.notify = []
        self.error = []
        self.confirm = []
        self.request_background = []
        self.request_consolidate = []


def _patch(monkeypatch, *, background=None, consolidate=None, run_confirm=True):
    rec = Recorder()
    monkeypatch.setattr(
        sim_actions.god_ui, "_sim_ref",
        lambda sim_info: {"player_id": "local", "save_id": "s1", "sim_id": 7},
    )
    monkeypatch.setattr(sim_actions.god_ui, "_current_lang", lambda: "en")

    # Realistic signatures: a body passed in the wrong slot must NOT be captured
    # as the message (regression guard for the background-view arg bug).
    def _simple(message, sim_info=None, connection=None):
        rec.notify.append((message,))
        return True

    def _notification(title, text, sim_info=None, urgent=False, connection=None):
        rec.notify.append((title, text))
        return True

    monkeypatch.setattr(sim_actions.chat_ui, "show_simple_notification", _simple)
    monkeypatch.setattr(sim_actions.chat_ui, "show_notification", _notification)
    monkeypatch.setattr(
        sim_actions.chat_ui, "show_error",
        lambda message, sim_info=None, connection=None: rec.error.append((message,)) or True,
    )

    def _background(sim, **kwargs):
        rec.request_background.append(kwargs)
        return background if background is not None else {"ok": False}

    def _consolidate(sim, **kwargs):
        rec.request_consolidate.append(kwargs)
        return consolidate if consolidate is not None else {"ok": False}

    monkeypatch.setattr(sim_actions.http_client, "request_background", _background)
    monkeypatch.setattr(sim_actions.http_client, "request_consolidate", _consolidate)

    def _confirm(sim_info, title, body, on_ok=None):
        rec.confirm.append((title, body))
        if run_confirm and on_ok is not None:
            on_ok()
        return True

    monkeypatch.setattr(sim_actions.dialogs, "confirm", _confirm)
    return rec


def _joined(items):
    return " ".join(str(part) for args in items for part in args)


def test_view_background_shows_the_text(monkeypatch):
    rec = _patch(
        monkeypatch,
        background={"ok": True, "background": {"text": "Born in Willow Creek."}},
    )
    sim_actions.view_background(FakeSimInfo("Ana"))
    assert "Born in Willow Creek." in _joined(rec.notify)
    assert rec.request_background and rec.request_background[0]["force"] is False


def test_view_background_when_unavailable(monkeypatch):
    rec = _patch(monkeypatch, background={"ok": False})
    sim_actions.view_background(FakeSimInfo("Ana"))
    assert rec.notify  # a localized "unavailable" notification


def test_view_background_when_empty(monkeypatch):
    rec = _patch(monkeypatch, background={"ok": True, "background": {}})
    sim_actions.view_background(FakeSimInfo("Ana"))
    assert rec.notify


def test_regenerate_background_confirms_and_forces(monkeypatch):
    rec = _patch(
        monkeypatch,
        background={"ok": True, "background": {"text": "A brand new story."}},
    )
    sim_actions.regenerate_background(FakeSimInfo("Ana"))
    assert rec.confirm  # asked for confirmation first
    assert rec.request_background and rec.request_background[0]["force"] is True
    assert "A brand new story." in _joined(rec.notify)


def test_regenerate_background_waits_for_confirmation(monkeypatch):
    rec = _patch(
        monkeypatch,
        background={"ok": True, "background": {"text": "x"}},
        run_confirm=False,
    )
    sim_actions.regenerate_background(FakeSimInfo("Ana"))
    assert rec.confirm
    assert rec.request_background == []  # nothing until the player confirms


def test_consolidate_memory_reports_the_count(monkeypatch):
    rec = _patch(
        monkeypatch,
        consolidate={"ok": True, "consolidated": 3, "message_key": "notify.consolidate.done"},
    )
    sim_actions.consolidate_memory(FakeSimInfo("Ana"))
    assert rec.confirm
    assert rec.request_consolidate
    assert "3" in _joined(rec.notify)


def test_consolidate_memory_error(monkeypatch):
    rec = _patch(monkeypatch, consolidate={"ok": False})
    sim_actions.consolidate_memory(FakeSimInfo("Ana"))
    assert rec.error


def test_background_text_unwraps_dict_and_string():
    assert sim_actions._background_text({"text": "hello"}) == "hello"
    assert sim_actions._background_text("raw") == "raw"
    assert sim_actions._background_text({}) == ""


def test_view_background_puts_text_in_the_notification_body(monkeypatch):
    """Regression: the background text is the notification body, not a bogus sim_info."""
    rec = _patch(
        monkeypatch,
        background={"ok": True, "background": {"text": "Only in the body"}},
    )
    sim_actions.view_background(FakeSimInfo("Ana"))
    # The body is the second positional arg of show_notification (locale-independent).
    assert any(
        len(args) >= 2 and args[1] == "Only in the body" for args in rec.notify
    )


def test_view_background_queued_notifies(monkeypatch):
    rec = _patch(monkeypatch, background={"ok": True, "queued": True})
    sim_actions.view_background(FakeSimInfo("Ana"))
    assert rec.notify
    # The queue flag must be requested so the sidecar does not block the game.
    assert rec.request_background and rec.request_background[0]["queue"] is True


def test_regenerate_background_queued_notifies(monkeypatch):
    rec = _patch(monkeypatch, background={"ok": True, "queued": True})
    sim_actions.regenerate_background(FakeSimInfo("Ana"))
    assert rec.confirm
    assert rec.notify
    assert rec.request_background[0]["force"] is True
    assert rec.request_background[0]["queue"] is True


def test_consolidate_memory_queued_notifies(monkeypatch):
    rec = _patch(monkeypatch, consolidate={"ok": True, "queued": True})
    sim_actions.consolidate_memory(FakeSimInfo("Ana"))
    assert rec.confirm
    assert rec.notify
    assert rec.request_consolidate and rec.request_consolidate[0]["queue"] is True
