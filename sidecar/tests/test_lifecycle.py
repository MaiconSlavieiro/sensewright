"""Tests for the game-process watchdog and the lifecycle endpoint."""

from __future__ import annotations

import os
import threading
import time

import httpx
import pytest

from sims_sense_sidecar.lifecycle import (
    GameProcessWatcher,
    game_pid_from_env,
    is_pid_alive,
)
from sims_sense_sidecar.schemas import LifecycleResponse
from sims_sense_sidecar.server import _start_game_watcher


class _FakeApp:
    def __init__(self) -> None:
        self.state = type("State", (), {})()


def test_start_game_watcher_creates_inert_watcher_without_target(settings, monkeypatch):
    monkeypatch.delenv("SIMS_SENSE_GAME_PID", raising=False)
    settings.runtime.game_pid = None
    settings.runtime.watch_game_process_name = False
    settings.runtime.shutdown_on_game_exit = True

    watcher = _start_game_watcher(_FakeApp(), settings)

    assert watcher is not None
    assert watcher.has_target is False
    assert watcher.running() is False


def test_start_game_watcher_arms_on_env_pid(settings, monkeypatch):
    monkeypatch.setenv("SIMS_SENSE_GAME_PID", str(os.getpid()))
    settings.runtime.shutdown_on_game_exit = True

    watcher = _start_game_watcher(_FakeApp(), settings)
    try:
        assert watcher is not None
        assert watcher.has_target is True
        assert watcher.running() is True
        assert watcher.snapshot()["pid"] == os.getpid()
    finally:
        watcher.stop()


def test_start_game_watcher_disabled(settings):
    settings.runtime.shutdown_on_game_exit = False

    assert _start_game_watcher(_FakeApp(), settings) is None


def test_game_pid_from_env_parses_and_validates():
    assert game_pid_from_env({"SIMS_SENSE_GAME_PID": "1234"}) == 1234
    assert game_pid_from_env({"SIMS_SENSE_GAME_PID": " 42 "}) == 42
    assert game_pid_from_env({"SIMS_SENSE_GAME_PID": "abc"}) is None
    assert game_pid_from_env({"SIMS_SENSE_GAME_PID": "0"}) is None
    assert game_pid_from_env({}) is None


def test_is_pid_alive_for_current_process():
    assert is_pid_alive(os.getpid()) is True


def test_is_pid_alive_for_missing_process():
    assert is_pid_alive(999_999) is False


@pytest.mark.skipif(os.name != "nt", reason="Windows-only access check")
def test_windows_pid_alive_access_denied_counts_as_alive(monkeypatch):
    # A protected process (The Sims 4 under DRM) makes OpenProcess fail with
    # ERROR_ACCESS_DENIED even while running; it must be reported as alive so
    # the watchdog does not kill the sidecar mid-session.
    import ctypes

    class _FakeKernel32:
        def OpenProcess(self, *args):
            return 0

        def GetLastError(self):
            return 5  # ERROR_ACCESS_DENIED

    fake_windll = type("W", (), {"kernel32": _FakeKernel32()})
    monkeypatch.setattr(ctypes, "windll", fake_windll, raising=False)

    assert is_pid_alive(4242) is True


def _wait(event: threading.Event, timeout: float = 3.0) -> bool:
    return event.wait(timeout)


def test_watcher_triggers_when_pid_dies():
    alive = {"value": True}
    fired = threading.Event()
    watcher = GameProcessWatcher(
        pid=100,
        on_exit=fired.set,
        is_alive=lambda _pid: alive["value"],
        interval=0.02,
        grace=0.05,
    )

    assert watcher.start() is True
    time.sleep(0.05)
    alive["value"] = False

    assert _wait(fired) is True
    watcher.stop()
    assert watcher.snapshot()["exited"] is True


def test_watcher_without_target_is_inert():
    watcher = GameProcessWatcher(on_exit=lambda: None)

    assert watcher.has_target is False
    assert watcher.start() is False
    assert watcher.running() is False


def test_watcher_stop_prevents_trigger():
    fired = threading.Event()
    watcher = GameProcessWatcher(
        pid=100,
        on_exit=fired.set,
        is_alive=lambda _pid: False,
        interval=0.02,
        grace=0.05,
    )

    watcher.start()
    watcher.stop()
    time.sleep(0.15)

    assert fired.is_set() is False


def test_watcher_attach_arms_and_starts():
    fired = threading.Event()
    watcher = GameProcessWatcher(
        on_exit=fired.set,
        is_alive=lambda _pid: False,
        interval=0.02,
        grace=0.05,
    )

    assert watcher.attach(4321) is True
    assert watcher.running() is True
    assert _wait(fired) is True
    watcher.stop()


def test_watcher_name_watch_triggers_when_absent():
    fired = threading.Event()
    watcher = GameProcessWatcher(
        name="TS4_x64.exe",
        watch_name=True,
        on_exit=fired.set,
        name_running=lambda _name: False,
        interval=0.02,
        grace=0.05,
    )

    assert watcher.start() is True
    assert _wait(fired) is True
    watcher.stop()


class TestLifecycleEndpoint:
    async def test_attach_401_without_token(self, client: httpx.AsyncClient):
        resp = await client.post("/v1/lifecycle/attach", json={"pid": 1})
        assert resp.status_code == 401

    async def test_attach_without_watcher_is_not_ok(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str]
    ):
        resp = await client.post(
            "/v1/lifecycle/attach", json={"pid": 1}, headers=auth_headers
        )
        assert resp.status_code == 200
        body = LifecycleResponse(**resp.json())
        assert body.ok is False
        assert body.watching is False

    async def test_attach_with_watcher(
        self, client: httpx.AsyncClient, auth_headers: dict[str, str], app
    ):
        watcher = GameProcessWatcher(
            on_exit=lambda: None,
            is_alive=lambda _pid: True,
            interval=0.05,
        )
        app.state.game_watcher = watcher
        try:
            resp = await client.post(
                "/v1/lifecycle/attach", json={"pid": os.getpid()}, headers=auth_headers
            )
            assert resp.status_code == 200
            body = LifecycleResponse(**resp.json())
            assert body.ok is True
            assert body.watching is True
            assert body.pid == os.getpid()
        finally:
            watcher.stop()
