"""Game-process watchdog: shut the sidecar down when The Sims 4 exits.

The mod spawns the sidecar as a child of the game process and passes its PID via
``SIMS_SENSE_GAME_PID``. This watchdog watches that PID and, when it disappears,
triggers a graceful shutdown so the sidecar never lingers after the game closes.
A stale sidecar (started before the game) can also be armed at runtime through
``POST /v1/lifecycle/attach``.

The PID check uses only the standard library: ``ctypes`` on Windows
(``OpenProcess`` + ``GetExitCodeProcess``) and ``os.kill(pid, 0)`` elsewhere.
An optional process-name watch is available for the rare case where the game PID
is unknown, but it is off by default (it can false-positive in dev).
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

GAME_PID_ENV = "SIMS_SENSE_GAME_PID"

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def game_pid_from_env(environ: dict[str, str] | None = None) -> int | None:
    """Read ``SIMS_SENSE_GAME_PID`` (set by the mod) as an int, else ``None``."""
    env = os.environ if environ is None else environ
    raw = env.get(GAME_PID_ENV)
    if raw is None:
        return None
    try:
        pid = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87


def _windows_pid_alive(pid: int) -> bool:
    import ctypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not handle:
        # OpenProcess failed. A protected process (e.g. The Sims 4 under EA/DRM
        # protection) returns ERROR_ACCESS_DENIED even though it is alive, so
        # only treat "no such process" (ERROR_INVALID_PARAMETER) as dead; any
        # other error means "unknown" and must never trigger a shutdown.
        error = kernel32.GetLastError()
        return error != _ERROR_INVALID_PARAMETER
    try:
        code = ctypes.c_ulong(0)
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True  # cannot read the code -> don't kill on doubt
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _posix_pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def is_pid_alive(pid: int) -> bool:
    """Best-effort "is this PID alive?" using only the standard library."""
    if os.name == "nt":
        try:
            return _windows_pid_alive(pid)
        except Exception:
            return True  # never kill on a probe failure
    try:
        return _posix_pid_alive(pid)
    except Exception:
        return True


def process_name_running(name: str) -> bool:
    """Best-effort check whether a process named ``name`` is running.

    Uses ``tasklist`` on Windows; on other platforms (or on any failure) it
    returns ``True`` so a probe failure can never trigger a shutdown.
    """
    if os.name != "nt" or not name:
        return True
    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return name.lower() in str(output).lower()
    except Exception:
        return True


class GameProcessWatcher:
    """Background thread that fires ``on_exit`` when the watched game is gone.

    Exactly one target is used: ``pid`` when set, otherwise the optional process
    ``name`` (only when ``watch_name`` is True). With no target the watcher is
    inert (``start`` is a no-op), so dev runs are unaffected.
    """

    def __init__(
        self,
        *,
        pid: int | None = None,
        name: str = "TS4_x64.exe",
        watch_name: bool = False,
        on_exit: Callable[[], None] | None = None,
        is_alive: Callable[[int], bool] | None = None,
        name_running: Callable[[str], bool] | None = None,
        interval: float = 2.0,
        grace: float = 5.0,
    ) -> None:
        self._pid = int(pid) if pid else None
        self._name = name
        self._watch_name = bool(watch_name)
        self._on_exit = on_exit
        self._is_alive = is_alive or is_pid_alive
        self._name_running = name_running or process_name_running
        self._interval = max(0.05, float(interval))
        self._grace = max(0.0, float(grace))

        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._exited = False

    # ── control ───────────────────────────────────────────────────────
    @property
    def has_target(self) -> bool:
        return self._pid is not None or self._watch_name

    def attach(self, pid: int | None) -> bool:
        """Arm the watcher on a game PID (used by ``/v1/lifecycle/attach``)."""
        if not pid or int(pid) <= 0:
            return False
        self._pid = int(pid)
        self._exited = False
        self._stop.clear()
        if not self.running():
            self.start()
        logger.info("game watchdog attached to pid %s", self._pid)
        return True

    def start(self) -> bool:
        """Start the watch loop; no-op (``False``) when there is no target."""
        if self.running():
            return False
        if not self.has_target:
            return False
        self._stop.clear()
        self._exited = False
        self._thread = threading.Thread(
            target=self._run, name="simssense-game-watchdog", daemon=True
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        """Signal the loop to stop and join it briefly."""
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=self._interval + 1.0)

    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── loop ──────────────────────────────────────────────────────────
    def _target_alive(self) -> bool:
        if self._pid is not None:
            return bool(self._is_alive(self._pid))
        if self._watch_name:
            return bool(self._name_running(self._name))
        return True

    def _run(self) -> None:
        missing = 0.0
        while not self._stop.wait(self._interval):
            if self._target_alive():
                missing = 0.0
                continue
            missing += self._interval
            if missing >= self._grace:
                self._trigger()
                return

    def _trigger(self) -> None:
        if self._exited:
            return
        self._exited = True
        logger.info("game process gone; shutting the sidecar down")
        callback = self._on_exit
        if callable(callback):
            try:
                callback()
            except Exception as exc:
                logger.warning("game watchdog on_exit failed: %s", exc)

    # ── introspection ─────────────────────────────────────────────────
    def snapshot(self) -> dict[str, Any]:
        return {
            "running": self.running(),
            "pid": self._pid,
            "watch_name": self._watch_name,
            "name": self._name if self._watch_name else None,
            "exited": self._exited,
        }
