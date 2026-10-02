"""Panel overrides store (REQ-PNL-01).

Persists Quick Menu / Web Studio overrides (God dials, preset, director mode,
powers, free_only) to ``data/panel.toml`` — never corrupting the base
``config.toml``. Overrides merge over the config defaults at read time.
"""
from __future__ import annotations

import copy
import threading
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]

try:
    import tomli_w  # type: ignore
except ImportError:  # pragma: no cover
    tomli_w = None


def _write_toml(data: Dict[str, Any], path: Path) -> None:
    if tomli_w is not None:
        path.write_text(tomli_w.dumps(data), encoding="utf-8")
        return
    # Minimal fallback writer (flat sections only).
    lines = []
    for section, values in data.items():
        if isinstance(values, dict):
            lines.append("[{}]".format(section))
            for key, value in values.items():
                lines.append("{} = {}".format(key, _toml_value(value)))
        else:
            lines.append("{} = {}".format(section, _toml_value(values)))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return '"{}"'.format(value.replace('"', '\\"'))
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    return '"{}"'.format(str(value))


class PanelStore:
    """Loads and saves panel overrides with a process lock."""

    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / "panel.toml"
        self._lock = threading.RLock()
        self._data: Dict[str, Any] = {}

    def load(self) -> Dict[str, Any]:
        with self._lock:
            if not self._path.is_file():
                self._data = {}
                return copy.deepcopy(self._data)
            try:
                if tomllib is not None:
                    with open(self._path, "rb") as handle:
                        self._data = dict(tomllib.load(handle))
            except (OSError, ValueError):
                self._data = {}
            return copy.deepcopy(self._data)

    def get(self, key: str, default: Any = None) -> Any:
        data = self.load()
        return data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self.load()
            self._data[key] = value
            self._path.parent.mkdir(parents=True, exist_ok=True)
            _write_toml(self._data, self._path)

    def all(self) -> Dict[str, Any]:
        return self.load()
