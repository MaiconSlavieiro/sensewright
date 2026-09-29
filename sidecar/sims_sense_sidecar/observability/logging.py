"""Logging configuration for the sidecar."""

from __future__ import annotations

import logging
import logging.handlers

from sims_sense_sidecar.config import Settings


def setup_logging(settings: Settings) -> None:
    """Configure rotating file + stream logging. Idempotent."""
    root = logging.getLogger()
    if root.handlers:
        # Already configured
        return

    level = getattr(logging, settings.logging.level.upper(), logging.INFO)
    root.setLevel(level)

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Stream handler
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.addHandler(stream)

    # Rotating file handler
    log_path = settings.log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.handlers.RotatingFileHandler(
        log_path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)