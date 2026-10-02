"""Tests for the sidecar game-process watchdog.
 
The sidecar must open and close together with The Sims 4. The parent PID is
seeded at launch (``--game-pid`` / ``SENSEWRIGHT_GAME_PID``) and refreshed via
``POST /lifecycle/attach``; the watchdog terminates the sidecar when the game
process disappears.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time

from sensewright_sidecar.__main__ import resolve_game_pid
from sensewright_sidecar.server import _is_pid_alive

# ── resolve_game_pid ─────────────────────────────────────────────────────


def test_resolve_pid_from_flag():
    assert resolve_game_pid(["--game-pid", "1234"]) == 1234


def test_resolve_pid_from_equals_flag():
    assert resolve_game_pid(["--game-pid=42"]) == 42


def test_resolve_pid_from_env(monkeypatch):
    monkeypatch.setenv("SENSEWRIGHT_GAME_PID", "55")
    assert resolve_game_pid([]) == 55


def test_cli_overrides_env(monkeypatch):
    monkeypatch.setenv("SENSEWRIGHT_GAME_PID", "55")
    assert resolve_game_pid(["--game-pid", "99"]) == 99


def test_resolve_pid_none_when_absent(monkeypatch):
    monkeypatch.delenv("SENSEWRIGHT_GAME_PID", raising=False)
    assert resolve_game_pid([]) is None


def test_resolve_pid_invalid(monkeypatch):
    monkeypatch.delenv("SENSEWRIGHT_GAME_PID", raising=False)
    assert resolve_game_pid(["--game-pid", "abc"]) is None
    assert resolve_game_pid(["--game-pid", "0"]) is None
    assert resolve_game_pid(["--game-pid", "-5"]) is None


# ── _is_pid_alive ────────────────────────────────────────────────────────


def test_own_pid_is_alive():
    assert _is_pid_alive(os.getpid()) is True


def test_invalid_pids_are_not_alive():
    assert _is_pid_alive(None) is False
    assert _is_pid_alive(0) is False


def test_dead_process_is_not_alive():
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"]
    )
    try:
        assert _is_pid_alive(process.pid) is True
    finally:
        process.terminate()
        process.wait(timeout=10)
    time.sleep(0.2)
    assert _is_pid_alive(process.pid) is False
