"""Multichannel chat & player persona progression (F01 / REQ-CHAT-*).

Manages the short-term chat buffer (8 turns), the trust-level ladder
(Acquaintance -> Confidant -> Advisor/Soulmate), and the deferred-response rule
(sleeping / off-lot sims do not answer phone_sms in real time).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

#: Trust-level thresholds (friendship 0..100).
TRUST_ACQUAINTANCE = 25.0
TRUST_CONFIDANT = 65.0

#: Relationship-bit name fragments -> canonical family relation label. The Mod
#: reports the raw EA tuning name (e.g. ``FAMILY_BROTHER_SISTER``); these map the
#: ambiguous pair-bits to a short label the LLM can ground on.
_FAMILY_RELATION_MAP = (
    ("brother_sister", "sibling"),
    ("step_sibling", "step-sibling"),
    ("husband_wife", "spouse"),
    ("son_daughter", "child"),
    ("niece_nephew", "niece/nephew"),
    ("aunt_uncle", "aunt/uncle"),
    ("grandparent", "grandparent"),
    ("grandchild", "grandchild"),
    ("parent", "parent"),
    ("cousin", "cousin"),
)


def family_relation_label(bit_name: str) -> str:
    """Map a raw EA relationship-bit name to a short family relation label.

    Falls back to the lowercased name with the ``family_`` prefix stripped, so an
    unknown family bit still yields something readable.
    """
    if not bit_name:
        return ""
    lowered = str(bit_name).lower().replace("-", "_")
    for fragment, label in _FAMILY_RELATION_MAP:
        if fragment in lowered:
            return label
    for prefix in ("family_", "relationship_bit_family_"):
        if lowered.startswith(prefix):
            return lowered[len(prefix):]
    return lowered


def trust_level(friendship: float) -> int:
    """Map friendship to an epistemic bond level (1..3)."""
    if float(friendship) >= TRUST_CONFIDANT:
        return 3  # Advisor / Soulmate
    if float(friendship) >= TRUST_ACQUAINTANCE:
        return 2  # Confidant
    return 1  # Acquaintance


def trust_delta(sentiment_score: float) -> float:
    """Convert a chat sentiment score into a friendship/trust delta."""
    try:
        return max(-2.0, min(2.0, float(sentiment_score)))
    except (TypeError, ValueError):
        return 0.0


def is_deferred(sim: Dict[str, Any], channel: str) -> bool:
    """Sleeping / off-lot sims defer phone_sms (REQ-CHAT-03)."""
    if channel != "phone_sms":
        return False
    return bool(sim.get("is_sleeping", False)) or bool(sim.get("is_off_lot_duty", False))


def build_chat_context(
    sim_id: int,
    sim_name: str,
    player_name: str,
    channel: str,
    message: str,
    friendship: float,
    profile: Optional[Dict[str, Any]],
    memories: Optional[List[Dict[str, Any]]],
    mood: str,
    activity: str,
    tick: int,
    history: Optional[List[Dict[str, str]]] = None,
    family: Optional[List[Dict[str, str]]] = None,
    location: Optional[Dict[str, Any]] = None,
    action: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the ``sim.chat`` context (profile slicing by channel).

    ``history`` carries the short-term chat buffer (prior user/assistant turns)
    so a follow-up message is not treated as a standalone greeting. ``family``
    carries the sim's real family-tree edges (resolved to ``name``/``relation``)
    so the model grounds relatives instead of hallucinating siblings that do not
    exist in the genealogy. ``location``/``action`` carry the setting (venue,
    indoor/outdoor) and the selected interaction menu text, so the reply reflects
    where the sim is and what it is doing.
    """
    context: Dict[str, Any] = {
        "sim_id": sim_id,
        "sim_name": sim_name,
        "player_name": player_name,
        "channel": channel,
        "message": message,
        "friendship": friendship,
        "trust": trust_level(friendship),
        "mood": mood,
        "activity": activity,
        "profile": profile or {},
        "memories": memories or [],
        "world_sim_tick": tick,
        "history": history or [],
        "family": family or [],
    }
    if location:
        context["location"] = location
    if action:
        context["action"] = action
    return context


def extract_thought(text: str) -> str:
    """Extract [thought]...[/thought] content (REQ-CHAT-01); never shown in UI."""
    if "[thought]" not in text:
        return ""
    start = text.find("[thought]") + len("[thought]")
    end = text.find("[/thought]", start)
    if end == -1:
        return text[start:]
    return text[start:end]


def strip_thought(text: str) -> str:
    """Remove [thought] blocks so only clean speech remains (REQ-CHAT-02)."""
    out = []
    rest = text
    while "[thought]" in rest:
        start = rest.find("[thought]")
        end = rest.find("[/thought]", start)
        if end == -1:
            out.append(rest[:start])
            rest = ""
            break
        out.append(rest[:start])
        rest = rest[end + len("[/thought]"):]
    out.append(rest)
    return "".join(out).strip()
