"""Persistence overlay for panel-managed ControlSpec values (P1).

The in-game configuration panel must survive a sidecar restart **without ever
touching the user's ``config.toml``**. Validated overrides are written to a
separate ``data/panel.toml`` file (nested sections mirroring each spec's
``target``) and deep-merged over ``config.toml`` at load time, for
ControlSpec-known paths only.

There is no TOML writer dependency here: a tiny serializer handles the flat
``[section] key = value`` grammar this overlay needs. ``restart_only`` specs are
never persisted (they are read once at startup).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .god.controls import CONTROL_SPECS, validate_values

FILENAME = "panel.toml"

_HEADER = (
    "# Sensewright panel overlay - generated automatically.\n"
    "# Values here override config.toml for settings changed from the in-game\n"
    "# panel. Safe to delete; it never modifies your config.toml.\n"
    "\n"
)

_MISSING = object()


def panel_path(data_dir: str | Path) -> Path:
    """Return the overlay path for a given ``data`` directory."""
    return Path(data_dir) / FILENAME


def _sections(values: dict[str, Any]) -> dict[str, Any]:
    """Build nested TOML sections from a flat ``{control_key: value}`` map."""
    root: dict[str, Any] = {}
    for spec in CONTROL_SPECS:
        if spec.restart_only or spec.key not in values:
            continue
        parts = [part for part in (spec.target or "panel").split(".") if part]
        parts.append(spec.path or spec.key)
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = values[spec.key]
    return root


def _read_spec_value(sections: dict[str, Any], spec: Any) -> Any:
    node: Any = sections
    for part in (spec.target or "panel").split("."):
        if not part:
            continue
        if not isinstance(node, dict):
            return _MISSING
        node = node.get(part)
    if not isinstance(node, dict):
        return _MISSING
    return node.get(spec.path or spec.key, _MISSING)


def _format_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        # A JSON string literal is also a valid TOML basic string (escapes match).
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(_format_scalar(item) for item in value) + "]"
    return json.dumps(str(value))


def _write_table(lines: list[str], path: list[str], table: dict[str, Any]) -> None:
    scalars = {key: value for key, value in table.items() if not isinstance(value, dict)}
    subtables = {key: value for key, value in table.items() if isinstance(value, dict)}
    if scalars:
        lines.append("[" + ".".join(path) + "]")
        for key, value in scalars.items():
            lines.append(f"{key} = {_format_scalar(value)}")
    for key, sub in subtables.items():
        _write_table(lines, path + [key], sub)


def dumps(root: dict[str, Any]) -> str:
    """Serialize a nested dict to TOML (flat ``[section] key = value`` grammar)."""
    lines: list[str] = []
    _write_table(lines, [], root)
    return "\n".join(lines) + ("\n" if lines else "")


def load_overrides(data_dir: str | Path) -> dict[str, Any]:
    """Read ``panel.toml`` and return a flat ``{control_key: value}`` map.

    Only ControlSpec-known, non-``restart_only`` paths are returned. Any read or
    parse error yields ``{}`` (best effort - never raises).
    """
    path = panel_path(data_dir)
    if not path.is_file():
        return {}
    try:
        import tomllib  # py>=3.11
    except ModuleNotFoundError:  # pragma: no cover - py3.10
        import tomli as tomllib  # type: ignore[no-redef]

    try:
        with path.open("rb") as handle:
            sections = tomllib.load(handle)
    except Exception:
        return {}
    if not isinstance(sections, dict):
        return {}

    overrides: dict[str, Any] = {}
    for spec in CONTROL_SPECS:
        if spec.restart_only:
            continue
        value = _read_spec_value(sections, spec)
        if value is _MISSING:
            continue
        overrides[spec.key] = value
    return overrides


def save_overrides(data_dir: str | Path, values: dict[str, Any] | None) -> Path:
    """Validate, merge and persist overrides, returning the written path.

    Existing overrides are preserved; only the supplied keys are updated.
    Unknown/invalid keys raise ``ValueError``.
    """
    validated = validate_values(values)
    merged = load_overrides(data_dir)
    merged.update(validated)

    path = panel_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_HEADER + dumps(_sections(merged)), encoding="utf-8")
    return path


def clear_overrides(data_dir: str | Path) -> bool:
    """Delete the overlay, reverting to ``config.toml``. Returns True if removed."""
    try:
        panel_path(data_dir).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
