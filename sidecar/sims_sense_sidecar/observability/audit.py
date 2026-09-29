"""Audit logging for the sidecar."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class AuditLog:
    """Append-only JSONL audit log with UTC ISO timestamps."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self._path.open("a", encoding="utf-8")

    def record(self, event: str, **fields: object) -> None:
        """Write one JSON line with timestamp and event."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **fields,
        }
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        """Close the underlying file handle."""
        try:
            self._file.close()
        except OSError:
            pass