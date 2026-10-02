"""Intent shape validation and normalization (F05 / REQ-INT-*).

The canonical Intent Shape has no legacy fields (``name``/``args`` at the root
are eliminated). Cognitive intents expire at ``next_sleep``; physical/social
intents expire at ``ttl`` (15 sim minutes) or on ``zone_transition``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from ..schemas import (
    INTENT_EXPIRY_MODES, INTENT_KINDS, INTENT_SOURCES, generate_trace_id,
)

#: Default physical/social intent TTL in sim minutes (REQ-INT-02).
DEFAULT_TTL_SIM_MINUTES = 15.0

#: Cognitive intents that expire at next_sleep.
COGNITIVE_KINDS = ("bias_interaction", "prefer_target", "set_goal")
#: Physical/social intents that expire at ttl / zone_transition.
PHYSICAL_KINDS = ("speak", "approach", "command", "spawn_npc")

INTENT_REQUIRED_KEYS = ("sim_id", "kind", "source")


def normalize_intent(
    raw: Dict[str, Any],
    trace_id: Optional[str] = None,
    default_source: str = "agent",
) -> Dict[str, Any]:
    """Return a fully-populated canonical intent, filling safe defaults.

    This never raises: invalid kinds are downgraded to ``command`` and invalid
    sources to ``agent``, so a malformed tool call cannot break the game loop.
    """
    if not isinstance(raw, dict):
        raw = {}

    kind = raw.get("kind") if raw.get("kind") in INTENT_KINDS else "command"
    source = raw.get("source") if raw.get("source") in INTENT_SOURCES else default_source

    # Physical/social intents default to ttl expiry; cognitive to next_sleep.
    if kind in COGNITIVE_KINDS:
        default_expiry = "next_sleep"
    elif kind in PHYSICAL_KINDS:
        default_expiry = "ttl"
    else:
        default_expiry = "ttl"
    expiry = raw.get("expires_on") if raw.get("expires_on") in INTENT_EXPIRY_MODES else default_expiry

    intent: Dict[str, Any] = {
        "id": raw.get("id") or "{}-{}".format(trace_id or "tr", raw.get("id", generate_trace_id())[-4:]),
        "trace_id": raw.get("trace_id") or trace_id or generate_trace_id(),
        "sim_id": int(raw.get("sim_id", 0)),
        "kind": kind,
        "target_sim_id": int(raw.get("target_sim_id", 0)) if raw.get("target_sim_id") is not None else None,
        "params": raw.get("params") if isinstance(raw.get("params"), dict) else {},
        "thought": raw.get("thought", ""),
        "narration": raw.get("narration", ""),
        "delay_sim_minutes": float(raw.get("delay_sim_minutes", 0.0)),
        "ttl_sim_minutes": float(raw.get("ttl_sim_minutes", DEFAULT_TTL_SIM_MINUTES)),
        "expires_on": expiry,
        "priority": int(raw.get("priority", 0)),
        "source": source,
        "retry_count": int(raw.get("retry_count", 0)),
        "max_retries": int(raw.get("max_retries", 2)),
    }
    return intent


def validate_intent(intent: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Return (ok, error) for a normalized intent."""
    if not intent.get("sim_id"):
        return False, "missing sim_id"
    if intent.get("kind") not in INTENT_KINDS:
        return False, "invalid kind"
    return True, None
