"""God Director — ``god.react`` (P19): branch the arc when a beat interaction ends.

The Mod reports the end of the catalyst ConversationSession (and the sovereign
agent's accept/reject/fight decision) to ``/v1/god/beat-ended``. ``run_react``
asks ``god.react`` for a narrative pivot, inserts any returned ``next_beat`` and
advances the arc; when the last beat is consumed the arc is marked ``done``
(so long as the callback runs, the narrative never stalls).
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from ..observability.logging import get_logger
from ..state import AppState
from .arcs import ARC_DONE, advance_arc, current_beat, load_active_arc, save_arc

logger = get_logger("god.react")

#: Decisions the Mod can report for an agent reacting to a catalyst.
REACT_DECISIONS = ("accept", "reject", "fight", "ignore")


def apply_react(arc: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Fold a ``god.react`` result into the arc and advance to the next beat.

    - annotates the just-finished beat with ``outcome``/``pivot``;
    - inserts a ``next_beat`` (when present) immediately after it;
    - advances ``current_beat_idx`` (marking ARC_DONE when exhausted).
    """
    arc = dict(arc)
    beats = list(arc.get("beats", []) or [])
    idx = int(arc.get("current_beat_idx", 0))
    beat = current_beat(arc)
    if beat is not None:
        beat = dict(beat)
        beat["outcome"] = data.get("outcome") or data.get("decision") or ""
        beat["pivot"] = data.get("pivot", "")
        beat["resolved"] = True
        if 0 <= idx < len(beats):
            beats[idx] = beat
    next_beat = data.get("next_beat")
    if isinstance(next_beat, dict) and next_beat:
        insert_at = idx + 1
        if 0 <= insert_at <= len(beats):
            beats.insert(insert_at, next_beat)
        else:
            beats.append(next_beat)
    arc["beats"] = beats
    arc = advance_arc(arc)
    return arc


def _react_callback(state: AppState, arc: Dict[str, Any], tick: int):
    def _callback(result) -> None:
        try:
            updated = apply_react(arc, result.data or {})
            store = state.working_store()
            if store is not None:
                save_arc(store, updated)
            state.active_arc = None if updated.get("status") == ARC_DONE else updated
            logger.info(
                "god.react beat resolved idx=%s status=%s",
                updated.get("current_beat_idx"), updated.get("status"),
            )
        except Exception:  # noqa: BLE001
            logger.exception("god.react callback failed")

    return _callback


def run_react(
    state: AppState,
    save_id: int,
    tick: int,
    decision: str,
    agent_sim_id: Optional[int],
    lang: str,
    arc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Schedule a ``god.react`` continuation for the active beat (P19)."""
    store = state.working_store()
    arc = arc or state.active_arc or (load_active_arc(store) if store else None)
    if arc is None:
        return {"ok": False, "reason": "no_active_arc"}
    beat = current_beat(arc)
    if beat is None:
        return {"ok": False, "reason": "no_current_beat"}
    decision = str(decision or "ignore").lower()
    if decision not in REACT_DECISIONS:
        decision = "ignore"
    ctx = {
        "save_id": int(save_id),
        "world_sim_tick": int(tick),
        "beat": beat,
        "theme": arc.get("theme", ""),
        "decision": decision,
        "agent_sim_id": int(agent_sim_id) if agent_sim_id else 0,
    }
    state.scheduler.submit_bg(
        "god.react", ctx, lang,
        dedup_key="{}:{}:god:react".format(save_id, arc.get("current_beat_idx", 0)),
        callback=state.guard_callback("god.react", _react_callback(state, arc, tick)),
    )
    return {"ok": True, "scheduled": "god.react", "beat_index": arc.get("current_beat_idx", 0)}
