"""Entry point for the Sensewright sidecar."""

from __future__ import annotations

import argparse
import logging
import socket
import sys

import uvicorn

from sensewright_sidecar.auth import ensure_token
from sensewright_sidecar.config import load_settings
from sensewright_sidecar.observability import setup_logging
from sensewright_sidecar.server import create_app

logger = logging.getLogger(__name__)


def _port_in_use(host: str, port: int) -> bool:
    """True when a socket cannot bind ``(host, port)`` (something is listening).

    A plain bind probe (no SO_REUSEADDR, which on Windows would let two sockets
    share the port and hide the conflict).
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((host, port))
                return False
            except OSError:
                return True
    except Exception:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sensewright sidecar — FastAPI orchestration host")
    parser.add_argument("--config", help="Path to config.toml")
    parser.add_argument("--host", help="Bind host (overrides config)")
    parser.add_argument("--port", type=int, help="Bind port (overrides config)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload (dev only)")
    args = parser.parse_args(argv)

    # Load settings
    settings = load_settings(args.config)

    # Apply CLI overrides
    if args.host:
        settings.network.host = args.host
    if args.port:
        settings.network.port = args.port

    # Setup logging early
    setup_logging(settings)

    # Ensure token exists
    token = ensure_token(settings)

    # A second sidecar on the same port is never useful (the mod reuses the one
    # already up). Exit cleanly instead of an opaque uvicorn bind crash.
    if _port_in_use(settings.network.host, settings.network.port):
        logger.info(
            "port %s:%s already in use; an existing sidecar is likely running — exiting",
            settings.network.host,
            settings.network.port,
        )
        return 0

    # Create app
    app = create_app(settings, token)

    # Run server. A Server instance is exposed on app.state so the game-process
    # watchdog (lifecycle.py) can request a graceful shutdown when the game exits.
    if args.reload:
        # Reload runs in a subprocess and cannot expose a Server handle; keep the
        # plain runner for development (no auto-shutdown in this mode).
        uvicorn.run(
            app,
            host=settings.network.host,
            port=settings.network.port,
            log_config=None,
            reload=True,
        )
    else:
        config = uvicorn.Config(
            app,
            host=settings.network.host,
            port=settings.network.port,
            log_config=None,
        )
        server = uvicorn.Server(config)
        app.state.server = server
        server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())