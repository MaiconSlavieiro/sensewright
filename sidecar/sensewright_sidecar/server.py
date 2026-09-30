"""FastAPI application factory for Sensewright sidecar."""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI

from sensewright_sidecar import __version__
from sensewright_sidecar.auth import remove_runtime, write_runtime
from sensewright_sidecar.config import Settings
from sensewright_sidecar.lifecycle import GameProcessWatcher, game_pid_from_env
from sensewright_sidecar.observability import setup_logging
from sensewright_sidecar.routers import (
    admin,
    autonomy,
    chat,
    events,
    god,
    health,
    lifecycle,
    profiles,
)

logger = logging.getLogger(__name__)


def _start_game_watcher(app: FastAPI, settings: Settings) -> GameProcessWatcher | None:
    """Arm the game-process watchdog so the sidecar exits with The Sims 4.

    The watcher is always created (when ``shutdown_on_game_exit`` is on) even
    without a target, so a sidecar that is already running can be armed later
    through ``POST /v1/lifecycle/attach``. The target is the mod-set
    ``SENSEWRIGHT_GAME_PID`` (or the ``runtime.game_pid`` override), or the
    optional process-name watch; with no target the watcher stays inert.
    """
    runtime = settings.runtime
    if not runtime.shutdown_on_game_exit:
        return None

    pid = game_pid_from_env() or runtime.game_pid

    def _on_exit() -> None:
        server = getattr(app.state, "server", None)
        if server is not None:
            server.should_exit = True

    watcher = GameProcessWatcher(
        pid=pid,
        name=runtime.game_process_name,
        watch_name=bool(runtime.watch_game_process_name),
        on_exit=_on_exit,
        interval=runtime.game_watch_interval_seconds,
        grace=runtime.game_watch_grace_seconds,
    )
    logger.info(
        "game watchdog armed: pid=%s watch_name=%s name=%s",
        pid,
        runtime.watch_game_process_name,
        runtime.game_process_name,
    )
    watcher.start()
    return watcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup observability, agent config, runtime file."""
    settings: Settings = app.state.settings
    token: str = app.state.token

    # Setup logging
    setup_logging(settings)

    # Best-effort agent configuration (configure is synchronous).
    try:
        from sensewright_sidecar.agent import graph as agent_graph

        if hasattr(agent_graph, "configure"):
            agent_graph.configure(settings)
        if hasattr(agent_graph, "start_backgrounds"):
            await agent_graph.start_backgrounds()
        if hasattr(agent_graph, "start_agency"):
            await agent_graph.start_agency()
    except Exception:
        # Agent module may not exist yet; ignore
        pass

    # Write runtime file for the mod
    write_runtime(settings, token)

    # Exit with the game: watch the game process and stop uvicorn when it dies.
    app.state.game_watcher = _start_game_watcher(app, settings)

    yield

    # Shutdown: stop the watchdog, background work and release resources.
    watcher = getattr(app.state, "game_watcher", None)
    if watcher is not None:
        watcher.stop()
    try:
        from sensewright_sidecar.agent import graph as agent_graph

        if hasattr(agent_graph, "shutdown"):
            await agent_graph.shutdown()
    except Exception:
        pass
    remove_runtime(settings)


def create_app(settings: Settings, token: str) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Sensewright Sidecar",
        version=__version__,
        lifespan=lifespan,
    )

    # Store settings and token on app state
    app.state.settings = settings
    app.state.token = token
    app.state.start_time = time.time()

    # Include routers with /v1 prefix
    app.include_router(health.router, prefix="/v1")
    app.include_router(chat.router, prefix="/v1")
    app.include_router(admin.router, prefix="/v1")
    app.include_router(events.router, prefix="/v1")
    app.include_router(god.router, prefix="/v1")
    app.include_router(profiles.router, prefix="/v1")
    app.include_router(autonomy.router, prefix="/v1")
    app.include_router(lifecycle.router, prefix="/v1")

    return app