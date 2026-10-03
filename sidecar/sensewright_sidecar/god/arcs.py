"""God Director — narrative arcs and beats (F14 / REQ-GOD-*)."""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from ..memory.sqlite_store import SqliteStore

#: Arc lifecycle states.
ARC_DRAFT = "draft"
ARC_ACTIVE = "active"
ARC_DONE = "done"
ARC_ABORTED = "aborted"


def create_arc(theme: str, beats: List[Dict[str, Any]], cast: List[Any], tick: int) -> Dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:12],
        "theme": theme,
        "beats": beats or [],
        "current_beat_idx": 0,
        "cast": cast or [],
        "status": ARC_ACTIVE if beats else ARC_DRAFT,
        "created_sim_tick": int(tick),
    }


def current_beat(arc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    beats = arc.get("beats", []) or []
    idx = int(arc.get("current_beat_idx", 0))
    if 0 <= idx < len(beats):
        return beats[idx]
    return None


def advance_arc(arc: Dict[str, Any]) -> Dict[str, Any]:
    arc = dict(arc)
    arc["current_beat_idx"] = int(arc.get("current_beat_idx", 0)) + 1
    if int(arc["current_beat_idx"]) >= len(arc.get("beats", []) or []):
        arc["status"] = ARC_DONE
    return arc


def steer_arc(
    arc: Dict[str, Any],
    action: str,
    beat_id: Optional[str] = None,
    custom_instruction: Optional[str] = None,
) -> Dict[str, Any]:
    """Apply a steering action (approve/skip/rewrite/abort) to an arc."""
    arc = dict(arc)
    beats = list(arc.get("beats", []) or [])
    if action == "abort_arc":
        arc["status"] = ARC_ABORTED
        return arc
    if action == "skip_beat":
        return advance_arc(arc)
    if action == "approve_beat":
        beat = current_beat(arc)
        if beat:
            beat["approved"] = True
            if beats:
                beats[int(arc.get("current_beat_idx", 0))] = beat
        arc["beats"] = beats
        return arc
    if action == "rewrite_beat":
        beat = current_beat(arc)
        if beat and custom_instruction:
            beat["rewrite_instruction"] = custom_instruction
            if beats:
                beats[int(arc.get("current_beat_idx", 0))] = beat
        arc["beats"] = beats
        return arc
    return arc


def save_arc(store: SqliteStore, arc: Dict[str, Any]) -> None:
    store.save_arc(arc)


def deactivate_stale_arcs(store: SqliteStore, keep_id: Optional[str] = None) -> int:
    """Abort every active arc except ``keep_id`` (BUG-02).

    ``load_active_arc`` calls this so a store polluted with duplicate actives
    (from builds predating the single-flight claim) self-heals on first load.
    """
    deactivate = getattr(store, "deactivate_stale_arcs", None)
    if not callable(deactivate):
        return 0
    return int(deactivate(keep_id) or 0)


def load_active_arc(store: SqliteStore) -> Optional[Dict[str, Any]]:
    arcs = store.list_arcs(status=ARC_ACTIVE)
    if not arcs:
        return None
    keep = arcs[0]
    if len(arcs) > 1:
        deactivate_stale_arcs(store, keep.get("id"))
    return keep
