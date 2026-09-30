"""Tests for the validation logging and log rotation (debug_log)."""

from __future__ import annotations

from sensewright_mod import debug_log


def test_validation_log_prefixes_when_enabled(monkeypatch):
    captured = []
    monkeypatch.setattr(debug_log, "debug_log", lambda message: captured.append(message))
    monkeypatch.setattr(debug_log, "VALIDATION_MODE", True)

    debug_log.validation_log("intent kind=speak")

    assert captured == ["[validate] intent kind=speak"]


def test_validation_log_is_muted_when_disabled(monkeypatch):
    captured = []
    monkeypatch.setattr(debug_log, "debug_log", lambda message: captured.append(message))
    monkeypatch.setattr(debug_log, "VALIDATION_MODE", False)

    debug_log.validation_log("intent kind=speak")

    assert captured == []


def test_debug_log_rotates_instead_of_stopping(monkeypatch, tmp_path):
    monkeypatch.setattr(debug_log, "DEBUG_LOG_MAX_BYTES", 200)
    monkeypatch.setattr(debug_log, "mod_root", lambda: str(tmp_path))

    for index in range(60):
        debug_log.debug_log("line {:02d} padding padding padding".format(index))

    data = (tmp_path / "sensewright_output.log").read_text(encoding="utf-8")
    assert "line 59" in data  # the tail survives
    assert "... [log truncated] ..." in data
