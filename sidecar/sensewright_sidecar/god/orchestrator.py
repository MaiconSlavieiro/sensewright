"""God Director — orchestrator (god.tick, direct-scene, arc steering)."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from ..agent import normalize_intent
from ..observability.logging import get_logger
from ..state import AppState
from .arcs import advance_arc, current_beat, load_active_arc, save_arc, steer_arc
from .controls import current_preset, resolve_dial, resolve_mode
from .puppeteer import run_puppeteer

logger = get_logger("god.orchestrator")


def _narration_callback(state: AppState):
    """Background callback: turn a god.narration result into a command intent."""

    def _callback(result) -> None:
        try:
            data = result.data or {}
            text = data.get("narration", "")
            if text:
                state.enqueue_intents([normalize_intent({
                    "sim_id": 0,
                    "kind": "command",
                    "params": {"visual_type": "SPECIAL_MOMENT", "text": text},
                    "source": "god",
                }, default_source="god")])
        except Exception:  # noqa: BLE001
            logger.exception("god.narration callback failed")

    return _callback


def god_tick(state: AppState, save_id: int, tick: int, lang: str) -> Dict[str, Any]:
    """Drive the God Director loop: plan arcs, advance beats, emit directives."""
    store = state.working_store()
    directives: List[Dict[str, Any]] = []
    active_arc = state.active_arc or (load_active_arc(store) if store else None)

    mode = resolve_mode(state.panel, state.config)
    if mode == "SANDBOX":
        # Only act when manually triggered.
        return {
            "directives": directives,
            "active_arc": active_arc or {},
            "active_catalyst_leases": list(state.catalyst_leases.keys()),
        }

    # 1. Plan a new arc when none is active and the intervention dial fires.
    if active_arc is None:
        frequency = resolve_dial(state.panel, state.config, "intervention_frequency")
        if random.random() < float(frequency) * 0.05:
            state.scheduler.submit_bg(
                "god.plan",
                {"save_id": save_id, "world_sim_tick": tick, "preset": current_preset(state.panel, state.config)},
                lang, dedup_key="{}:{}:god:plan".format(save_id, tick // 720),
            )
        return {
            "directives": directives,
            "active_arc": {},
            "active_catalyst_leases": list(state.catalyst_leases.keys()),
        }

    # 2. Advance/arm beats and emit narration.
    beat = current_beat(active_arc)
    if beat and not beat.get("armed"):
        beat["armed"] = True
        active_arc["beats"][int(active_arc.get("current_beat_idx", 0))] = beat
        save_arc(store, active_arc) if store else None
        # Narration is a realtime LLM call; run it in the background so the
        # autonomy tick response is never blocked by provider latency.
        state.scheduler.submit_bg(
            "god.narration",
            {"sim_name": "", "world_sim_tick": tick, "beat": beat.get("title", "")},
            lang,
            callback=_narration_callback(state),
        )

    state.active_arc = active_arc
    return {
        "directives": directives,
        "active_arc": active_arc,
        "active_catalyst_leases": list(state.catalyst_leases.keys()),
    }


def direct_scene(
    state: AppState,
    save_id: int,
    tick: int,
    catalyst_sim_ids: List[int],
    target_sim_ids: List[int],
    prompt_text: str,
    mode: str,
    lang: str,
) -> Dict[str, Any]:
    """Handle /v1/god/direct-scene (soft_catalyst | sandbox_full)."""
    intents: List[Dict[str, Any]] = []
    scene_id = None
    if catalyst_sim_ids and target_sim_ids:
        catalyst_id = int(catalyst_sim_ids[0])
        target_id = int(target_sim_ids[0])
        catalyst_name = (state.get_census(catalyst_id) or {}).get("name", "Catalyst")
        target_name = (state.get_census(target_id) or {}).get("name", "Target")
        result = run_puppeteer(
            state, catalyst_id, catalyst_name, target_id, target_name,
            prompt_text or "Strike up a conversation.", lang, tick,
        )
        intents.extend(result.get("intents", []))
        scene_id = result.get("scene_id")
    state.enqueue_intents(intents)
    return {"ok": True, "scene_id": scene_id, "intents": intents}


def steer(
    state: AppState,
    save_id: int,
    action: str,
    beat_id: Optional[str],
    custom_instruction: Optional[str],
    lang: str,
) -> Dict[str, Any]:
    """Handle /v1/god/arc/steer."""
    store = state.working_store()
    arc = state.active_arc or (load_active_arc(store) if store else None)
    if arc is None:
        return {"ok": False, "updated_arc": {}}
    updated = steer_arc(arc, action, beat_id, custom_instruction)
    if store:
        save_arc(store, updated)
    state.active_arc = updated
    return {"ok": True, "updated_arc": updated}
