"""Wire contract: JSON payload sanitization, trace ids and language handling.

The mod and the sidecar communicate exclusively over a local HTTP wire. Every
payload must be sanitized to JSON primitives (`str`, `int`, `float`, `bool`,
`None`, `list`, `dict`), use exactly one canonical key per argument (no legacy
aliases) and carry a mandatory `lang` code. This module is dependency-free and
is safe to import in tests and tooling.
"""
from __future__ import annotations

import secrets
from typing import Any, Dict, List

#: JSON primitive types allowed on the wire.
_JSON_PRIMITIVES = (str, int, float, bool, type(None))

#: Canonical chat channels.
CHANNELS = ("phone_sms", "pc_chat", "pc_email")

#: Canonical Intent kinds (no legacy `name`/`args` fields).
INTENT_KINDS = (
    "speak", "approach", "set_mood", "bias_interaction", "prefer_target",
    "set_goal", "remember", "forget", "command",
)

#: Canonical Intent sources.
INTENT_SOURCES = ("agent", "god", "puppeteer", "social")

#: Intent expiry modes.
INTENT_EXPIRY_MODES = ("ttl", "next_sleep", "zone_transition")


def generate_trace_id() -> str:
    """Return an 8-char hexadecimal trace id, unique per pulse/chat message."""
    return secrets.token_hex(4)


def _sanitize_payload(obj: Any, _depth: int = 0) -> Any:
    """Recursively coerce ``obj`` into JSON-safe primitives only.

    Unknown types are stringified. Dict keys are coerced to ``str``. Cycles are
    impossible since we only recurse into freshly-created containers. Depth is
    capped defensively to avoid pathological nesting.
    """
    if _depth > 64:
        return None
    if obj is None or isinstance(obj, _JSON_PRIMITIVES):
        return obj
    if isinstance(obj, dict):
        return {
            str(key): _sanitize_payload(value, _depth + 1)
            for key, value in obj.items()
        }
    if isinstance(obj, (list, tuple, set)):
        return [_sanitize_payload(item, _depth + 1) for item in obj]
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    # Fallback for arbitrary objects (enums, etc.)
    return str(obj)


def sanitize_payload(obj: Any) -> Any:
    """Public wrapper around :func:`_sanitize_payload`."""
    return _sanitize_payload(obj)


def normalize_lang(lang: Any) -> str:
    """Coerce a language code/client token to a registered locale code.

    Language discovery is manifest-driven (zero locale literals in code). The
    resolution consults the unified manifest's ``code``/``base_subtag``/
    ``ts4_client_tokens`` and falls back to ``default_locale``.
    """
    from .i18n_engine import get_engine

    if not isinstance(lang, str) or not lang.strip():
        return get_engine().default_locale()
    return get_engine().resolve_locale(lang)


def require_lang(payload: Dict[str, Any]) -> str:
    """Return the normalized ``lang`` from a payload, defaulting safely."""
    return normalize_lang(payload.get("lang"))


def require_str(payload: Dict[str, Any], key: str, default: str = "") -> str:
    """Return a string field, coercing non-strings safely."""
    value = payload.get(key, default)
    if not isinstance(value, str):
        return default
    return value


def require_int(payload: Dict[str, Any], key: str, default: int = 0) -> int:
    """Return an int field, coercing floats/strings safely."""
    value = payload.get(key, default)
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def require_float(payload: Dict[str, Any], key: str, default: float = 0.0) -> float:
    """Return a float field, coercing safely."""
    value = payload.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def require_bool(payload: Dict[str, Any], key: str, default: bool = False) -> bool:
    """Return a bool field, coercing safely."""
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return default
