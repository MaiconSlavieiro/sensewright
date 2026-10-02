"""Sensewright sidecar entry point.

Run with: ``python -m sensewright_sidecar`` (from the ``sidecar`` directory).
The sidecar serves the REST API on 127.0.0.1:8765 and the Web Studio at /ui.

When launched by the game mod, the parent game PID is passed via
``--game-pid <pid>`` (and/or the ``SENSEWRIGHT_GAME_PID`` environment
variable). The watchdog then terminates this process as soon as the game exits,
so the sidecar's lifetime is bound to the game even if the HTTP
``/lifecycle/attach`` call never lands.
"""
from __future__ import annotations

import os
import sys


def resolve_game_pid(argv=None):
    """Resolve the parent game PID from ``--game-pid`` or the env var.

    Returns a positive int, or None when not supplied/parseable.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    raw = os.environ.get("SENSEWRIGHT_GAME_PID")
    for index, arg in enumerate(args):
        if arg == "--game-pid" and index + 1 < len(args):
            raw = args[index + 1]
        elif arg.startswith("--game-pid="):
            raw = arg.split("=", 1)[1]
    if not raw:
        return None
    try:
        pid = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return pid if pid > 0 else None


def main() -> None:
    # Allow running from the sidecar directory without installing the package.
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from sensewright_sidecar.config import get_config
    from sensewright_sidecar.observability.logging import get_logger, setup_logging
    from sensewright_sidecar.state import get_state

    config = get_config()
    setup_logging(config.log_level)

    # Arm the watchdog before uvicorn imports the app, so the sidecar cannot
    # outlive the game even if /lifecycle/attach is delayed or fails.
    game_pid = resolve_game_pid()
    if game_pid:
        get_state().game_pid = game_pid
        get_logger("sidecar").info("watchdog armed with game pid %s", game_pid)

    import uvicorn

    uvicorn.run(
        "sensewright_sidecar.server:app",
        host=config.server_host,
        port=config.server_port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
