"""FastAPI application factory for the Sensewright sidecar."""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from . import __version__
from .config import get_config
from .observability.logging import get_logger, set_trace_id, setup_logging
from .routers import api_router
from .schemas import generate_trace_id
from .state import get_state
from .webui.router import router as webui_router

logger = get_logger("server")


def _is_pid_alive(pid: int) -> bool:
    """Best-effort cross-platform process liveness check."""
    if pid is None or pid <= 0:
        return False
    if sys.platform == "win32":
        try:
            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return False
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return True
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _watchdog_loop() -> None:
    """Monitor the attached game_pid; shut down cleanly when the game exits."""
    while True:
        try:
            state = get_state()
            pid = state.game_pid
            if pid and not _is_pid_alive(int(pid)):
                logger.info("game process %s exited; shutting down sidecar", pid)
                try:
                    state.save_vault.shutdown()
                except Exception:  # noqa: BLE001
                    pass
                os._exit(0)  # noqa: PLR1722
        except Exception:  # noqa: BLE001
            pass
        time.sleep(5.0)


def create_app() -> FastAPI:
    config = get_config()
    setup_logging(config.log_level)

    app = FastAPI(title="Sensewright Sidecar", version=__version__)

    # Local-only service; allow loopback + the in-game Web Studio origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:{}".format(config.server_port), "http://localhost:{}".format(config.server_port)],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or generate_trace_id()
        set_trace_id(trace_id)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

    app.include_router(api_router)
    app.include_router(webui_router)

    @app.on_event("startup")
    def _startup() -> None:
        threading.Thread(target=_watchdog_loop, name="sensewright-watchdog", daemon=True).start()

    return app


app = create_app()
