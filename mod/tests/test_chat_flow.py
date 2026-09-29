"""
Tests for the chat/hey response rendering in main.py (offline).

Locks in the guarantee that a reply/fallback is always surfaced: the dialog is
tried first, and the cheat console is the fallback (never a silent failure).

Run with system Python (3.10+). Importing ``main`` outside the game uses the
no-op ``sims4.commands`` fallback, so the command decorators are inert.
"""

import os
import sys

mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

from sensewright_mod import main  # noqa: E402


def _no_batch(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "execute_batch", lambda tool_calls: calls.append(tool_calls))
    return calls


def test_render_response_falls_back_to_console(monkeypatch):
    outputs = []
    _no_batch(monkeypatch)
    monkeypatch.setattr(main, "show_simple_notification", lambda *a, **k: False)
    monkeypatch.setattr(main, "_output", lambda connection, message: outputs.append(message))

    main._render_response({"reply": "hi there"}, object(), 3)

    assert outputs == ["hi there"]


def test_render_response_stays_quiet_when_notified(monkeypatch):
    outputs = []
    _no_batch(monkeypatch)
    monkeypatch.setattr(main, "show_simple_notification", lambda *a, **k: True)
    monkeypatch.setattr(main, "_output", lambda connection, message: outputs.append(message))

    main._render_response({"reply": "hi"}, object(), 3)

    assert outputs == []


def test_render_response_brain_foggy_on_empty(monkeypatch):
    shown = []
    _no_batch(monkeypatch)
    monkeypatch.setattr(main, "show_simple_notification",
                        lambda message, *a, **k: shown.append(message) or True)

    main._render_response({}, object(), 3)

    assert shown == [main.i18n.t("error.brain_foggy")]


def test_render_response_executes_tool_calls(monkeypatch):
    batches = _no_batch(monkeypatch)
    monkeypatch.setattr(main, "show_simple_notification", lambda *a, **k: True)

    calls = [{"id": "c1", "name": "add_buff", "args": {}}]
    main._render_response({"tool_calls": calls}, object(), 3)

    assert batches == [calls]


def test_autoboot_attaches_lifecycle_when_sidecar_running(monkeypatch):
    attached = []
    monkeypatch.setattr(main, "health", lambda: {"ok": True})
    monkeypatch.setattr(main, "attach_lifecycle",
                        lambda pid: attached.append(pid) or {"ok": True})
    monkeypatch.setattr(main, "show_simple_notification", lambda *a, **k: True)

    main.autoboot()

    assert attached == [os.getpid()]


def test_cmd_chat_joins_multiword_message(monkeypatch):
    """The game passes tokens positionally; cmd_chat must join them."""
    captured = {}
    monkeypatch.setattr(main, "_get_sim_info", lambda: object())
    monkeypatch.setattr(main, "_build_sim_dict", lambda sim_info: {"sim_id": 1})
    monkeypatch.setattr(main, "collect", lambda sim_info: {})
    monkeypatch.setattr(main, "_get_current_lang", lambda: "en")
    monkeypatch.setattr(main, "chat",
                        lambda sim, message, context, lang="en": captured.update(message=message) or {})
    monkeypatch.setattr(main, "_render_response", lambda *a, **k: None)

    main.cmd_chat("ola", "tudo", "bem", _connection=3)

    assert captured["message"] == "ola tudo bem"


def test_cmd_chat_without_text_reports_bad_request(monkeypatch):
    outputs = []
    monkeypatch.setattr(main, "_output", lambda connection, message: outputs.append(message))

    main.cmd_chat(_connection=3)

    assert outputs == [main.i18n.t("error.bad_request")]


def test_render_response_tool_only_is_silent(monkeypatch):
    outputs = []
    _no_batch(monkeypatch)
    monkeypatch.setattr(main, "show_simple_notification", lambda *a, **k: True)
    monkeypatch.setattr(main, "_output", lambda connection, message: outputs.append(message))

    main._render_response({"tool_calls": [{"id": "c1", "name": "move_to", "args": {}}]},
                          object(), 3)

    assert outputs == []


def test_render_response_surfaces_spontaneous_line(monkeypatch):
    """A tool-only reply with a text-bearing tool must not be silent."""
    outputs = []
    _no_batch(monkeypatch)
    monkeypatch.setattr(main, "show_simple_notification", lambda *a, **k: False)
    monkeypatch.setattr(main, "_output", lambda connection, message: outputs.append(message))

    calls = [{"id": "c1", "name": "spontaneous_line", "args": {"text": "What a day..."}}]
    main._render_response({"tool_calls": calls}, object(), 3)

    assert outputs == ["What a day..."]


def _stub_player_lock(monkeypatch):
    """Replace tool_executor.record_player_activity with a recorder (C1 wiring)."""
    from sensewright_mod import tool_executor

    armed = []
    monkeypatch.setattr(
        tool_executor,
        "record_player_activity",
        lambda sim_id=0: armed.append(sim_id),
        raising=False,
    )
    return armed


def test_note_player_active_arms_lock(monkeypatch):
    armed = _stub_player_lock(monkeypatch)

    main._note_player_active(7)

    assert armed == [7]


def test_cmd_chat_arms_player_lock(monkeypatch):
    armed = _stub_player_lock(monkeypatch)
    monkeypatch.setattr(main, "_get_sim_info", lambda: object())
    monkeypatch.setattr(main, "_build_sim_dict", lambda sim_info: {"sim_id": 1})
    monkeypatch.setattr(main, "collect", lambda sim_info: {})
    monkeypatch.setattr(main, "_get_current_lang", lambda: "en")
    monkeypatch.setattr(main, "chat", lambda sim, message, context, lang="en": {})
    monkeypatch.setattr(main, "_render_response", lambda *a, **k: None)

    main.cmd_chat("hello", _connection=3)

    assert armed == [0]


def test_cmd_autonomy_persists_level(monkeypatch):
    _stub_player_lock(monkeypatch)
    persisted = []
    outputs = []
    monkeypatch.setattr(main, "_get_sim_info", lambda: object())
    monkeypatch.setattr(main, "_build_sim_dict", lambda sim_info: {"sim_id": 4})
    monkeypatch.setattr(main, "set_autonomy", lambda sim, level: {})
    monkeypatch.setattr(main, "write_autonomy_level",
                        lambda level: persisted.append(level) or True)
    monkeypatch.setattr(main, "_output",
                        lambda connection, message: outputs.append(message))

    main.cmd_autonomy("semi", _connection=3)

    assert persisted == ["semi"]
    assert outputs == [main.i18n.t("cmd.autonomy.set", level="semi", sim_id=4)]


def test_cmd_autonomy_reports_set_when_persist_fails(monkeypatch):
    _stub_player_lock(monkeypatch)
    logs = []
    outputs = []
    monkeypatch.setattr(main, "_get_sim_info", lambda: object())
    monkeypatch.setattr(main, "_build_sim_dict", lambda sim_info: {"sim_id": 4})
    monkeypatch.setattr(main, "set_autonomy", lambda sim, level: {})
    monkeypatch.setattr(main, "write_autonomy_level", lambda level: False)
    monkeypatch.setattr(main, "_debug_log", lambda message: logs.append(message))
    monkeypatch.setattr(main, "_output",
                        lambda connection, message: outputs.append(message))

    main.cmd_autonomy("semi", _connection=3)

    assert outputs == [main.i18n.t("cmd.autonomy.set", level="semi", sim_id=4)]
    assert logs


def test_cmd_autonomy_no_arg_reapplies_persisted_level(monkeypatch):
    _stub_player_lock(monkeypatch)
    applied = []
    outputs = []
    monkeypatch.setattr(main, "_get_sim_info", lambda: object())
    monkeypatch.setattr(main, "_build_sim_dict", lambda sim_info: {"sim_id": 4})
    monkeypatch.setattr(main, "read_autonomy_level", lambda: "full")
    monkeypatch.setattr(main, "set_autonomy", lambda sim, level: applied.append(level) or {})
    monkeypatch.setattr(main, "write_autonomy_level", lambda level: True)
    monkeypatch.setattr(main, "_output",
                        lambda connection, message: outputs.append(message))

    main.cmd_autonomy("", _connection=3)

    assert applied == ["full"]
    assert outputs == [main.i18n.t("cmd.autonomy.set", level="full", sim_id=4)]


def test_cmd_zeitgeist_auto_forwards_lang(monkeypatch):
    _stub_player_lock(monkeypatch)
    captured = {}
    monkeypatch.setattr(main, "_get_sim_info", lambda: object())
    monkeypatch.setattr(main, "_build_sim_dict", lambda sim_info: {"sim_id": 1})
    monkeypatch.setattr(main, "_get_current_lang", lambda: "pt-BR")
    monkeypatch.setattr(
        main, "suggest_zeitgeist",
        lambda sim, tags, text, lang="en": captured.update(lang=lang) or {"suggested_text": "x"},
    )
    monkeypatch.setattr(main, "_output", lambda *a, **k: None)

    main.cmd_zeitgeist("auto", _connection=3)

    assert captured["lang"] == "pt-BR"


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
