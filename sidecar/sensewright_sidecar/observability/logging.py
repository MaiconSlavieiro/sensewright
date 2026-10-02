"""Logging with rotation and trace-id threading (REQ-OBS-01/02).

All sidecar loggers use :class:`logging.handlers.RotatingFileHandler` with a
10 MB limit and 3 backups. A single trace id threads from the mod's origin
through every log line, HTTP payload and audit record, so a full session can be
reconstructed with a single ``grep <trace_id>`` across the logs.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path
from typing import Optional

LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
LOG_BACKUP_COUNT = 3

#: Default log directory: <sidecar>/../data/logs, falling back to ./logs.
DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "logs"

_configured = False

#: The trace id currently in flight. Thread-local so concurrent requests in the
#: sidecar do not trample each other.
import threading  # noqa: E402

_trace_local = threading.local()


def set_trace_id(trace_id: str) -> None:
    """Set the trace id for the current thread (used by middleware)."""
    _trace_local.trace_id = trace_id


def get_trace_id() -> str:
    """Return the current thread's trace id, or ``"-"`` if unset."""
    return getattr(_trace_local, "trace_id", "-")


class _TraceFilter(logging.Filter):
    """Inject the current trace id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True


def setup_logging(level: str = "INFO", log_dir: Optional[Path] = None) -> None:
    """Configure the process-wide rotating file handler once."""
    global _configured
    if _configured:
        return
    _configured = True

    directory = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)

    log_file = directory / "sensewright-sidecar.log"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear any pre-existing handlers (e.g. from uvicorn reload).
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(trace_id)s] %(name)s: %(message)s"
    )

    file_handler = logging.handlers.RotatingFileHandler(
        str(log_file), maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(_TraceFilter())
    root.addHandler(file_handler)

    # Also emit to stderr when running in a foreground console (dev mode).
    if os.environ.get("SENSEWRIGHT_DEBUG"):
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.addFilter(_TraceFilter())
        root.addHandler(stream_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger (children inherit the root handler)."""
    return logging.getLogger("sensewright." + name)


#: Audit trail logger (JSONL). Separate file, same rotation policy.
def get_audit_logger() -> logging.Logger:
    """Return the audit logger, writing JSONL to ``data/logs/audit.jsonl``."""
    audit_logger = logging.getLogger("sensewright.audit")
    if audit_logger.handlers:
        return audit_logger
    directory = DEFAULT_LOG_DIR
    directory.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        str(directory / "audit.jsonl"),
        maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    audit_logger.addHandler(handler)
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False
    return audit_logger
