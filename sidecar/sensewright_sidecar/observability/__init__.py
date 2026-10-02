"""Observability package for the Sensewright sidecar."""
from __future__ import annotations

from .logging import get_logger, setup_logging  # noqa: F401

__all__ = ["get_logger", "setup_logging"]
