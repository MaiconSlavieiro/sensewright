"""Pure helpers for graded memory strength and forgetting (v0.2 M2).

Strength decays lazily on read: ``s(t) = clamp01(s0 * e^(-lambda * dt_hours))``.
The lambda comes from a preset (``fast`` / ``normal`` / ``slow``) and importance
acts as a mild lift. Everything here is deterministic and side-effect free, and
every function tolerates ``None`` inputs so a missing column never breaks a read.
"""

from __future__ import annotations

import math
from typing import Any

# Per-hour decay constants. A larger lambda means the memory fades faster.
DECAY_PRESETS: dict[str, float] = {
    "fast": 0.02,
    "normal": 0.005,
    "slow": 0.001,
}

DEFAULT_PRESET = "normal"


def clamp01(value: Any) -> float:
    """Clamp ``value`` to the ``[0.0, 1.0]`` range (``None`` -> 0.0)."""
    number = _to_float(value)
    if number is None:
        return 0.0
    return max(0.0, min(1.0, number))


def decay_preset_or_default(preset: str) -> float:
    """Return the per-hour decay constant for ``preset`` (unknown -> normal)."""
    key = str(preset or "").strip().lower()
    return DECAY_PRESETS.get(key, DECAY_PRESETS[DEFAULT_PRESET])


def decay_lambda(preset: str) -> float:
    """Return the per-hour decay constant for ``preset`` (unknown -> normal)."""
    return decay_preset_or_default(preset)


def effective_strength(
    strength: Any,
    last_accessed_at: Any,
    importance: Any,
    now: float,
    preset: str = "normal",
    *,
    initial: float = 1.0,
) -> float:
    """Compute the effective strength of a memory at ``now``.

    ``strength`` is the stored base value (``initial`` when missing). It decays
    exponentially with the hours since ``last_accessed_at`` (fallback: no decay)
    and is lifted mildly by ``importance``.
    """
    base = _to_float(strength)
    if base is None:
        base = float(initial)

    lam = decay_preset_or_default(preset)
    dt_hours = _hours_since(last_accessed_at, now)
    decayed = base * math.exp(-lam * dt_hours)

    imp = _to_float(importance)
    if imp is None:
        imp = 1.0
    lift = 0.75 + 0.25 * max(0.0, min(imp, 2.0))
    return clamp01(decayed * lift)


def annotate(
    events: list[dict[str, Any]],
    now: float,
    preset: str = "normal",
) -> list[dict[str, Any]]:
    """Return shallow copies of ``events`` with a float ``strength`` key added."""
    annotated: list[dict[str, Any]] = []
    for event in events or []:
        if not isinstance(event, dict):
            continue
        copy = dict(event)
        copy["strength"] = effective_strength(
            copy.get("strength"),
            copy.get("last_accessed_at"),
            copy.get("importance"),
            now,
            preset,
        )
        annotated.append(copy)
    return annotated


def touch_strength(strength: Any) -> float:
    """Boost a memory that was just used: ``min(1, s*1.1 + 0.05)``."""
    base = _to_float(strength)
    if base is None:
        base = 1.0
    return clamp01(base * 1.1 + 0.05)


def is_vivid(strength: Any, weaken_threshold: float = 0.5) -> bool:
    """True when a memory is vivid enough for full text in context."""
    value = _to_float(strength)
    if value is None:
        return False
    return value > weaken_threshold


def is_weak(
    strength: Any,
    weaken_threshold: float = 0.5,
    forget_threshold: float = 0.2,
) -> bool:
    """True when a memory is weak: only a vague semantic recall."""
    value = _to_float(strength)
    if value is None:
        return False
    return forget_threshold <= value <= weaken_threshold


def is_forgotten(strength: Any, forget_threshold: float = 0.2) -> bool:
    """True when a memory has faded below the forget threshold."""
    value = _to_float(strength)
    if value is None:
        return False
    return value < forget_threshold


def dejavu_hint(text: str, max_chars: int = 60) -> str:
    """Return the first ``max_chars`` characters, adding an ellipsis if cut."""
    raw = str(text or "").strip()
    limit = max(0, int(max_chars))
    if len(raw) <= limit:
        return raw
    return raw[:limit] + "…"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _hours_since(reference: Any, now: float) -> float:
    if reference is None:
        return 0.0
    try:
        delta = float(now) - float(reference)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, delta) / 3600.0
