"""God Director — orchestrator (god.tick, direct-scene, arc steering)."""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from ..agent import normalize_intent
from ..observability.logging import get_logger
from ..state import AppState
from ..constants import TICKS_PER_SIM_DAY
from .arcs import (
    ARC_DONE, advance_arc, create_arc, current_beat, load_active_arc, save_arc, steer_arc,
)
from .cast import run_cast
from .controls import current_preset, resolve_dial, resolve_mode
from .puppeteer import run_puppeteer
from .react import apply_react, run_react

logger = get_logger("god.orchestrator")


def _plan_callback(state: AppState, tick: int):
    """Background callback: build and persist an arc from a god.plan result (P15).

    The synchronous ``arc_planning`` claim released here is what guarantees a
    single active arc even when several ticks fire before the LLM responds (3.1).
    """

    def _callback(result) -> None:
        try:
            data = result.data or {}
            beats = data.get("beats", []) or []
            if not beats:
                # Models sometimes return a theme without beats (or the 0-key
                # fallback supplies one). Synthesize a single default beat so the
                # narrative always starts instead of re-planning forever (1.1/1.2).
                theme = str(data.get("theme") or "").strip()
                if not theme:
                    return
                beats = [{
                    "title": theme,
                    "catalyst_role": data.get("catalyst_role") or "catalyst",
                    "scene_hint": theme,
                }]
            arc = create_arc(
                data.get("theme", ""), beats, data.get("cast", []) or [], tick,
            )
            store = state.working_store()
            if store is not None:
                save_arc(store, arc)
                state.active_arc = arc
                logger.info("god.plan created arc id=%s beats=%d", arc["id"], len(beats))
        except Exception:  # noqa: BLE001
            logger.exception("god.plan callback failed")
        finally:
            state.end_arc_plan()

    return _callback


def _scene_callback(state: AppState, arc: Dict[str, Any], beat_idx: int):
    """Background callback: fold a god.scene draft into the armed beat (P17)."""

    def _callback(result) -> None:
        try:
            data = result.data or {}
            beat = current_beat(arc)
            if beat is None:
                return
            beat["scene_draft"] = data.get("scene_draft", "")
            beat["scene_subtext"] = data.get("scene_subtext", "")
            beats = list(arc.get("beats", []) or [])
            if 0 <= beat_idx < len(beats):
                beats[beat_idx] = beat
                arc["beats"] = beats
            store = state.working_store()
            if store is not None:
                save_arc(store, arc)
            state.active_arc = arc
        except Exception:  # noqa: BLE001
            logger.exception("god.scene callback failed")

    return _callback


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


def god_tick(
    state: AppState, save_id: int, tick: int, lang: str,
    active_sim_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Drive the God Director loop: plan arcs, assign cast, advance beats."""
    store = state.working_store()
    directives: List[Dict[str, Any]] = []

    # F13: drop expired catalyst leases so a stale puppeteer objective cannot
    # linger on a sim after the scene window closed.
    for lease_sim_id in list(state.catalyst_leases.keys()):
        lease = state.catalyst_leases.get(lease_sim_id) or {}
        expires = int(lease.get("lease_expires_tick", 0) or 0)
        if expires and int(tick) > expires:
            state.catalyst_leases.pop(lease_sim_id, None)

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
            # Single-flight: claim the slot synchronously so a burst of ticks
            # cannot each schedule their own god.plan before the first lands.
            if state.try_begin_arc_plan():
                state.scheduler.submit_bg(
                    "god.plan",
                    {"save_id": save_id, "world_sim_tick": tick, "preset": current_preset(state.panel, state.config)},
                    lang, dedup_key="{}:{}:god:plan".format(save_id, tick // 720),
                    callback=state.guard_callback("god.plan", _plan_callback(state, tick)),
                )
        return {
            "directives": directives,
            "active_arc": {},
            "active_catalyst_leases": list(state.catalyst_leases.keys()),
        }

    # 2. Liveness (BUG-03): advance a beat that never received a catalyst
    # reaction within the configured window, so an arc can never stall forever.
    beat = current_beat(active_arc)
    if beat is not None and beat.get("armed"):
        if "beat_armed_tick" not in beat:
            # Legacy/loaded arc without a stamp: start its liveness window now.
            beat["beat_armed_tick"] = int(tick)
            beats = list(active_arc.get("beats", []) or [])
            idx = int(active_arc.get("current_beat_idx", 0))
            if 0 <= idx < len(beats):
                beats[idx] = beat
                active_arc["beats"] = beats
            if store is not None:
                save_arc(store, active_arc)
        timeout_days = int(state.config.god("beat_timeout_sim_days", 1) or 0)
        armed_tick = int(beat.get("beat_armed_tick", tick))
        if timeout_days > 0 and (int(tick) - armed_tick) >= timeout_days * TICKS_PER_SIM_DAY:
            logger.info(
                "god beat timeout: arc=%s beat=%s stalled %d ticks -> advance",
                active_arc.get("id"), active_arc.get("current_beat_idx"), int(tick) - armed_tick,
            )
            state.incr("god_beat_timeouts")
            active_arc = advance_arc(active_arc)
            if store is not None:
                save_arc(store, active_arc)
            state.active_arc = active_arc
            if active_arc.get("status") == ARC_DONE:
                state.enqueue_intents([normalize_intent({
                    "sim_id": 0, "kind": "command", "source": "god",
                    "params": {"visual_type": "SPECIAL_MOMENT",
                               "text": active_arc.get("theme", "")},
                }, default_source="god")])
                return {
                    "directives": directives,
                    "active_arc": active_arc,
                    "active_catalyst_leases": list(state.catalyst_leases.keys()),
                }
            beat = current_beat(active_arc)

    # 3. Advance/arm beats and emit narration.
    if beat and not beat.get("armed"):
        beat["armed"] = True
        beat["beat_armed_tick"] = tick
        beat_idx = int(active_arc.get("current_beat_idx", 0))
        active_arc["beats"][beat_idx] = beat
        save_arc(store, active_arc) if store else None
        # Narration is a realtime LLM call; run it in the background so the
        # autonomy tick response is never blocked by provider latency.
        state.scheduler.submit_bg(
            "god.narration",
            {"sim_name": "", "world_sim_tick": tick, "beat": beat.get("title", "")},
            lang,
            callback=state.guard_callback("god.narration", _narration_callback(state)),
        )
        # Prepare the catalyst scene draft for P18 (god.puppeteer).
        state.scheduler.submit_bg(
            "god.scene",
            {"save_id": save_id, "world_sim_tick": tick, "beat": beat,
             "theme": active_arc.get("theme", "")},
            lang, dedup_key="{}:{}:god:scene".format(save_id, beat_idx),
            callback=state.guard_callback(
                "god.scene", _scene_callback(state, active_arc, beat_idx)),
        )

        # P16: assign a catalyst (reuse a townie, or emit spawn_npc for the Mod).
        if not active_arc.get("cast"):
            cast_result = run_cast(
                state, save_id, beat, tick, lang,
                target_sim_id=active_sim_id, arc=active_arc,
            )
            if cast_result.get("cast"):
                active_arc["cast"] = cast_result["cast"]
                beat["cast"] = cast_result["cast"][0]
                active_arc["beats"][beat_idx] = beat
            if cast_result.get("intents"):
                state.enqueue_intents(cast_result["intents"])
            save_arc(store, active_arc) if store else None

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


def beat_ended(
    state: AppState,
    save_id: int,
    tick: int,
    decision: str,
    agent_sim_id: Optional[int],
    lang: str,
    target_sim_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Handle /v1/god/beat-ended: branch the arc after a catalyst interaction (P19)."""
    return run_react(state, save_id, tick, decision, agent_sim_id, lang, target_sim_id=target_sim_id)
