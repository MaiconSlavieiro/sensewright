"""Service layer — orchestrates agent, god and world domains for the routers.

This is the single place where HTTP payloads meet the domain logic. Every
handler is defensive (never raises into the web framework) and returns plain
JSON-safe dicts. Language resolution is manifest-driven via the payload ``lang``.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from . import __version__
from .agent import (
    SeatManager, apply_cognition, apply_reflection, build_chat_context,
    build_cognition_context, build_dream_context, build_impulse_context,
    build_reaction_context, build_reflect_context, compute_salience, decay_blocks,
    extract_thought, hard_blocked_social, is_deferred, is_salient,
    normalize_intent, normalize_profile, physical_actions_allowed, preflight,
    record_speech, reinforce_block, resolve_limits, sleep_transition,
    speech_allowed, strip_thought, trust_delta,
)
from .agent.psyche import block_for_category
from .agent.social import build_social_context, has_rumor_to_spread
from .constants import (
    COMPACT_ARCHIVE_COUNT, CONSOLIDATED_COMPACT_THRESHOLD, TICKS_PER_SIM_DAY,
)
from .fallbacks import render_fallback
from .god import (
    current_beat, current_zeitgeist, direct_scene as god_direct_scene, get_controls,
    god_tick as god_tick_handler, resolve_dial, run_zeitgeist, set_control,
    steer as god_steer,
)
from .observability.logging import get_logger
from .schemas import normalize_lang, sanitize_payload
from .state import AppState, get_state
from .world.chronicle import append_chronicle
from .world.rumors import (
    create_rumor, get_rumors, rumors_known_by, save_rumors, spread,
)

logger = get_logger("services")

#: Max autonomous LLM calls per autonomy tick (keeps realtime budget bounded).
MAX_IMPULSES_PER_TICK = 3
MAX_SOCIAL_PER_TICK = 1


def _store(state: AppState):
    return state.working_store()


# ── sleep cycle, cognition & evolution (F07 / P07-P09 / P30) ─────────────
def _sim_profile(state: AppState, sim_id: int) -> Dict[str, Any]:
    store = _store(state)
    if store is None:
        return {}
    return (store.get_sim_profile(sim_id) or {}).get("profile") or {}


def _persist_profile(state: AppState, sim_id: int, profile: Dict[str, Any], tick: int) -> None:
    store = _store(state)
    if store is not None and profile:
        store.upsert_sim_profile(sim_id, profile, tick)


def _schedule_cognition(state: AppState, sim_id: int, tick: int, lang: str, trace_id) -> None:
    """Build and schedule the post-dream cognition plan (P08)."""
    sim = state.get_census(sim_id)
    profile = _sim_profile(state, sim_id)
    ctx = build_cognition_context(
        sim_id, sim.get("name", ""),
        sim.get("schedule_blocks") or [],
        sim.get("obligatory_tasks") or [],
        sim.get("wants") or [],
        profile.get("dream_urge"),
        tick,
    )
    state.scheduler.submit_bg(
        "sim.cognition", ctx, lang, trace_id=trace_id,
        dedup_key="{}:{}:cognition".format(sim_id, tick // TICKS_PER_SIM_DAY),
        callback=_cognition_callback(state, sim_id, tick),
    )


def _cognition_callback(state: AppState, sim_id: int, tick: int):
    def _callback(result) -> None:
        try:
            data = result.data or {}
            profile = apply_cognition(_sim_profile(state, sim_id), data)
            _persist_profile(state, sim_id, profile, tick)
        except Exception:  # noqa: BLE001
            logger.exception("cognition callback failed for sim %s", sim_id)

    return _callback


def _dream_callback(state: AppState, sim_id: int, tick: int, trace_id, lang: str):
    def _callback(result) -> None:
        try:
            data = result.data or {}
            store = _store(state)
            narrative = data.get("dream_narrative", "")
            if narrative and store:
                store.add_memory(
                    sim_id, "dream",
                    {"text": narrative, "archetype": data.get("archetype", ""),
                     "urge": data.get("dream_urge", {})},
                    search_text=narrative, created_sim_tick=tick,
                )
            profile = _sim_profile(state, sim_id)
            if data.get("dream_urge"):
                profile["dream_urge"] = data.get("dream_urge")
                profile["last_dream_tick"] = int(tick)
                _persist_profile(state, sim_id, profile, tick)
            # The dream urge feeds the day's cognition plan.
            _schedule_cognition(state, sim_id, tick, lang, trace_id)
        except Exception:  # noqa: BLE001
            logger.exception("dream callback failed for sim %s", sim_id)

    return _callback


def _sleep_callback(state: AppState, sim_id: int, tick: int):
    def _callback(result) -> None:
        try:
            data = result.data or {}
            store = _store(state)
            reflection = data.get("reflection", "")
            if reflection and store:
                store.add_memory(
                    sim_id, "sleep_reflection", {"text": reflection},
                    search_text=reflection, created_sim_tick=tick,
                )
            updates = data.get("psyche_updates")
            if isinstance(updates, dict) and updates:
                profile = _sim_profile(state, sim_id)
                blocks = dict(profile.get("psyche_blocks") or {})
                for key, intensity in updates.items():
                    blocks = reinforce_block(blocks, str(key), float(intensity))
                profile["psyche_blocks"] = blocks
                _persist_profile(state, sim_id, profile, tick)
        except Exception:  # noqa: BLE001
            logger.exception("sleep callback failed for sim %s", sim_id)

    return _callback


def _reflect_callback(state: AppState, sim_id: int, tick: int):
    def _callback(result) -> None:
        try:
            data = result.data or {}
            profile = apply_reflection(_sim_profile(state, sim_id), data)
            if data.get("preference_change") or data.get("trait_proposal"):
                profile["evolution_proposal"] = {
                    "preference_change": data.get("preference_change"),
                    "trait_proposal": data.get("trait_proposal"),
                }
            _persist_profile(state, sim_id, profile, tick)
        except Exception:  # noqa: BLE001
            logger.exception("reflect callback failed for sim %s", sim_id)

    return _callback


def _apply_psyche_decay(state: AppState, sim_id: int, tick: int) -> None:
    """Exponential psyche decay in sim-days, applied once per wake (P08)."""
    last = state.last_psyche_decay_tick.get(sim_id)
    state.last_psyche_decay_tick[sim_id] = int(tick)
    if last is None:
        return
    delta_days = (int(tick) - int(last)) / float(TICKS_PER_SIM_DAY)
    if delta_days <= 0:
        return
    profile = _sim_profile(state, sim_id)
    blocks = profile.get("psyche_blocks") or {}
    if not blocks:
        return
    profile["psyche_blocks"] = decay_blocks(blocks, delta_days)
    _persist_profile(state, sim_id, profile, tick)


def _on_sleep_start(state: AppState, sim: Dict[str, Any], tick: int, lang: str, trace_id) -> None:
    store = _store(state)
    sim_id = int(sim.get("sim_id", 0))
    if store is None or not sim_id:
        return
    profile = _sim_profile(state, sim_id)
    zeitgeist = current_zeitgeist(state, state.active_save_id or 0)
    whisper = ""
    if state.active_arc:
        beat = current_beat(state.active_arc)
        if beat:
            whisper = beat.get("god_whisper_hint", "") or ""
    chaos = resolve_dial(state.panel, state.config, "chaos_degree")
    ctx = build_dream_context(
        sim_id, store, sim.get("name", ""),
        sim.get("traits") or profile.get("traits") or [],
        profile.get("psyche_blocks") or {},
        sim.get("mood"), chaos, whisper,
        zeitgeist.get("tags", []) or [], tick,
    )
    state.scheduler.submit_bg(
        "sim.dream", ctx, lang, trace_id=trace_id,
        dedup_key="{}:{}:dream".format(sim_id, tick // TICKS_PER_SIM_DAY),
        callback=_dream_callback(state, sim_id, tick, trace_id, lang),
    )
    logger.info("sleep start sim=%s -> sim.dream", sim_id)


def _on_wake(state: AppState, sim: Dict[str, Any], tick: int, lang: str, trace_id) -> None:
    sim_id = int(sim.get("sim_id", 0))
    if not sim_id:
        return
    _apply_psyche_decay(state, sim_id, tick)

    if state.salient_since_sleep.pop(sim_id, False):
        profile = _sim_profile(state, sim_id)
        ctx = {
            "sim_id": sim_id, "sim_name": sim.get("name", ""),
            "world_sim_tick": tick,
            "psyche_blocks": profile.get("psyche_blocks") or {},
            "dream_urge": profile.get("dream_urge") or {},
        }
        state.scheduler.submit_bg(
            "sim.sleep", ctx, lang, trace_id=trace_id,
            dedup_key="{}:{}:sleep".format(sim_id, tick // TICKS_PER_SIM_DAY),
            callback=_sleep_callback(state, sim_id, tick),
        )

    last = state.last_reflect_tick.get(sim_id)
    if last is None or (int(tick) - int(last)) >= TICKS_PER_SIM_DAY:
        state.last_reflect_tick[sim_id] = int(tick)
        profile = _sim_profile(state, sim_id)
        ctx = build_reflect_context(sim_id, sim.get("name", ""), profile, 1, tick)
        state.scheduler.submit_bg(
            "evo.reflect", ctx, lang, trace_id=trace_id,
            dedup_key="{}:{}:reflect".format(sim_id, tick // TICKS_PER_SIM_DAY),
            callback=_reflect_callback(state, sim_id, tick),
        )


def _process_sleep_transitions(state: AppState, tick: int, lang: str, trace_id) -> int:
    """Detect per-sim sleep edges and fan out the P07-P09 / P30 pipeline."""
    transitions = 0
    for _sim_id, sim in state.census_items():
        if "is_sleeping" not in sim:
            continue
        sim_id = int(sim.get("sim_id", 0))
        if not sim_id:
            continue
        current = bool(sim.get("is_sleeping"))
        edge = sleep_transition(state.sleep_state.get(sim_id), current)
        state.sleep_state[sim_id] = current
        if edge == "sleep_start":
            _on_sleep_start(state, sim, tick, lang, trace_id)
            transitions += 1
        elif edge == "wake":
            _on_wake(state, sim, tick, lang, trace_id)
            transitions += 1
    return transitions


# ── end-of-day world pipeline (P23 / P10) ─────────────────────────────────
def _diary_callback(state: AppState, sim_id: int, tick: int):
    def _callback(result) -> None:
        try:
            entry = (result.data or {}).get("entry", "")
            store = _store(state)
            if entry and store:
                store.add_memory(
                    sim_id, "diary", {"text": entry},
                    search_text=entry, created_sim_tick=tick,
                )
        except Exception:  # noqa: BLE001
            logger.exception("diary callback failed for sim %s", sim_id)

    return _callback


def _chronicle_callback(state: AppState, save_id: int, tick: int):
    def _callback(result) -> None:
        try:
            text = (result.data or {}).get("chronicle", "")
            store = _store(state)
            if text and store:
                append_chronicle(store, save_id, text, tick)
        except Exception:  # noqa: BLE001
            logger.exception("chronicle callback failed for save %s", save_id)

    return _callback


def _maybe_end_of_day(
    state: AppState, save_id: int, tick: int, lang: str, trace_id, active_sim_id=None,
) -> int:
    """Run the once-per-in-game-day pipeline (P23 chronicle + P10 diary)."""
    day = int(tick) // TICKS_PER_SIM_DAY
    last = state.last_day_tick
    state.last_day_tick = day
    if last == 0 or day <= last:
        return 0

    scheduled = 0
    state.scheduler.submit_bg(
        "world.household.chronicle",
        {"save_id": save_id, "world_sim_tick": tick, "day": day},
        lang, trace_id=trace_id,
        dedup_key="{}:{}:chronicle".format(save_id, day),
        callback=_chronicle_callback(state, save_id, tick),
    )
    scheduled += 1

    if active_sim_id:
        sim = state.get_census(int(active_sim_id))
        state.scheduler.submit_bg(
            "sim.diary",
            {"sim_id": int(active_sim_id), "sim_name": sim.get("name", ""),
             "world_sim_tick": tick},
            lang, trace_id=trace_id,
            dedup_key="{}:{}:diary".format(active_sim_id, day),
            callback=_diary_callback(state, int(active_sim_id), tick),
        )
        scheduled += 1
    return scheduled


# ── speech policy (F11) ───────────────────────────────────────────────────
def _speech_allowed(state: AppState, sim_ids: List[int], now: float) -> bool:
    max_lines, min_interval = resolve_limits(state.config)
    for sim_id in sim_ids:
        if not speech_allowed(
            state.speak_history.get(int(sim_id), []), now, max_lines, min_interval
        ):
            return False
    return True


def _record_speech(state: AppState, sim_id: int, now: float) -> None:
    state.speak_history[int(sim_id)] = record_speech(
        state.speak_history.get(int(sim_id), []), now
    )



# ── lifecycle ────────────────────────────────────────────────────────────
def handle_attach(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    state.game_pid = payload.get("game_pid")
    return {"ok": True}


def handle_session_start(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    save_id = int(payload.get("save_id", 0))
    tick = int(payload.get("world_sim_tick", 0))
    lang = normalize_lang(payload.get("lang"))
    state.current_lang = lang
    state.reset_ram()
    result = state.save_vault.session_start(save_id, tick)
    state.active_save_id = save_id

    recap_job_id = None
    if result.get("bootstrap_needed"):
        # Bootstrap: schedule zero-minute profile hydration in bg.
        state.scheduler.submit_bg(
            "ops.recap",
            {"save_id": save_id, "world_sim_tick": tick},
            lang, dedup_key="{}:{}:ops.recap".format(save_id, tick),
        )

    return {
        "ok": True,
        "restored_tick": result.get("restored_tick"),
        "bootstrap_needed": bool(result.get("bootstrap_needed")),
        "recap_job_id": recap_job_id,
    }


def handle_zone_transition(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    save_id = int(payload.get("save_id", 0))
    tick = int(payload.get("world_sim_tick", 0))
    state.save_vault.zone_transition(save_id, tick)
    # Clear spatial intents only (REQ-MEM-02).
    cleared = state.drain_intents()
    state.conversations = {}
    return {"ok": True, "cleared_spatial_intents": len(cleared)}


def handle_save(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    save_id = int(payload.get("save_id", 0))
    previous_save_id = payload.get("previous_save_id")
    tick = int(payload.get("world_sim_tick", 0))
    result = state.save_vault.save(save_id, previous_save_id, tick)
    return {"ok": True, "committed_tick": result.get("committed_tick", tick), "snapshot_rev": result.get("snapshot_rev", tick)}


def handle_census(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    sims = payload.get("sims") or []
    packs = payload.get("installed_packs")
    if isinstance(packs, list):
        state.installed_packs = {str(pack).upper() for pack in packs if pack}
    hydrated = 0
    store = _store(state)
    census_update: Dict[int, Dict[str, Any]] = {}
    for sim in sims:
        if not isinstance(sim, dict):
            continue
        sim_id = int(sim.get("sim_id", 0))
        if not sim_id:
            continue
        census_update[sim_id] = sim
        hydrated += 1
        if store is not None:
            existing = store.get_sim_profile(sim_id)
            profile = existing["profile"] if existing else None
            if profile is None:
                profile = normalize_profile(
                    {}, name=sim.get("name", ""), species=sim.get("species"),
                    age_stage=sim.get("age_stage"), traits=sim.get("traits"),
                    likes=sim.get("likes"), dislikes=sim.get("dislikes"),
                    generated_at_tick=int(payload.get("world_sim_tick", 0)),
                )
                store.upsert_sim_profile(sim_id, profile, int(payload.get("world_sim_tick", 0)))
    state.update_census(census_update)
    return {"ok": True, "hydrated_count": hydrated}


# ── autonomy ─────────────────────────────────────────────────────────────
def _merge_delta(state: AppState, delta: List[Dict[str, Any]]) -> None:
    state.merge_census_delta(delta)


def _impulse_callback(state: AppState, sim_id: int, tick: int, trace_id, physical_allowed: bool = True):
    """Build the background callback that records an impulse result as intents."""

    def _callback(result) -> None:
        try:
            data = result.data or {}
            thought = data.get("thought", "")
            store = _store(state)
            if thought and store:
                store.add_memory(
                    sim_id, "thought", {"text": thought},
                    search_text=thought, created_sim_tick=tick,
                )
            out: List[Dict[str, Any]] = []
            # REQ-IMP-01: an idle impulse emits at most one non-verbal intent.
            for raw in (data.get("intents", []) or [])[:1]:
                if not isinstance(raw, dict):
                    continue
                intent = normalize_intent(raw, trace_id=trace_id, default_source="agent")
                if intent["kind"] == "speak":
                    # Idle impulse never speaks (REQ-IMP-01); drop the line.
                    continue
                # REQ-IMP-03: survival & punctuality guard blocks physical acts.
                if not physical_allowed and intent["kind"] in ("approach", "command"):
                    continue
                # The impulse is the seat's own mind: never trust a sim_id the
                # model may have hallucinated from another context entry.
                intent["sim_id"] = int(sim_id)
                out.append(intent)
            if out:
                state.enqueue_intents(out)
        except Exception:  # noqa: BLE001
            logger.exception("impulse callback failed for sim %s", sim_id)

    return _callback


def _social_callback(
    state: AppState,
    sim_a: Dict[str, Any],
    sim_b: Dict[str, Any],
    rumor: Optional[Dict[str, Any]] = None,
    tick: int = 0,
):
    """Build the background callback that emits a social pair's speech intents."""

    a_id = int(sim_a.get("sim_id", 0))
    b_id = int(sim_b.get("sim_id", 0))

    def _callback(result) -> None:
        try:
            data = result.data or {}
            a_line = data.get("a_line", "")
            b_line = data.get("b_line", "")
            category = data.get("category")
            # F12: CHILD sims are hard-blocked from flirty/intimate categories.
            blocked = (
                hard_blocked_social(category, sim_a.get("age_stage"))
                or hard_blocked_social(category, sim_b.get("age_stage"))
            )
            if blocked:
                a_line, b_line = "", ""
            out: List[Dict[str, Any]] = []
            if a_line:
                out.append(normalize_intent({
                    "sim_id": a_id, "kind": "speak", "target_sim_id": b_id,
                    "params": {"text": a_line}, "source": "social",
                }, default_source="social"))
            if b_line:
                out.append(normalize_intent({
                    "sim_id": b_id, "kind": "speak", "target_sim_id": a_id,
                    "params": {"text": b_line}, "source": "social",
                }, default_source="social"))
            if out:
                now = time.time()
                if a_line:
                    _record_speech(state, a_id, now)
                if b_line:
                    _record_speech(state, b_id, now)
                state.enqueue_intents(out)
            # Conversation close: the listener learns the rumor (F22 / REQ-WLD-01).
            if rumor and (a_line or b_line):
                _spread_rumor(state, rumor, a_id, b_id, tick)
        except Exception:  # noqa: BLE001
            logger.exception("social callback failed for pair %s/%s", a_id, b_id)

    return _callback


def handle_autonomy_tick(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the delta, schedule autonomous LLM work in the background and
    immediately return any intents that are ready.

    The heavy LLM calls (impulse/social) must not run on the HTTP request
    thread: a single free-provider call can take tens of seconds, which would
    exceed the mod's request timeout and drop the returned intents. Jobs are
    enqueued on the scheduler's background worker; their callbacks push intents
    onto the pending IntentBus, which the next tick drains and returns.
    """
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    state.current_lang = lang
    tick = int(payload.get("world_sim_tick", 0))
    save_id = int(payload.get("save_id", 0))
    active_sim_id = payload.get("active_sim_id")
    clock_speed = int(payload.get("clock_speed", 1))
    trace_id = payload.get("trace_id")

    _merge_delta(state, payload.get("sims_delta") or [])

    # Pause handling: freeze autonomy when paused (REQ-ARCH-04).
    if clock_speed == 0:
        return {"ok": True, "scheduled": 0, "intents": state.drain_intents(), "social_sessions": []}

    intents: List[Dict[str, Any]] = []
    scheduled = 0

    # Sleep-cycle edges drive sim.dream/cognition/sleep and evo.reflect (P07-P09).
    _process_sleep_transitions(state, tick, lang, trace_id)

    # End-of-day pipeline: household chronicle + diary (P23/P10).
    _maybe_end_of_day(state, save_id, tick, lang, trace_id, active_sim_id)

    # Recompute seats (purely local, no LLM).
    catalyst_ids = list(state.catalyst_leases.keys())
    max_seats = int(state.config.gameplay("agent_seats", 12))
    lease_min = int(state.config.gameplay("lease_min_sim_minutes", 60))
    manager = SeatManager()
    state.set_seats(manager.assign(
        dict(state.census_items()), None, active_sim_id, catalyst_ids,
        list(state.conversations.keys()), tick, max_seats, lease_min,
        existing_seats=state.get_seats(),
    ))

    # Schedule idle impulses for the active sim + a bounded set of full seats.
    seats_snapshot = state.get_seats()
    full_seats = [s for s in seats_snapshot.values() if s.get("tier") == "full" and s.get("role") == "household"]
    order = []
    if active_sim_id and int(active_sim_id) in seats_snapshot:
        order.append(seats_snapshot[int(active_sim_id)])
    for seat in full_seats:
        if seat["sim_id"] not in [s["sim_id"] for s in order]:
            order.append(seat)
    order = order[:MAX_IMPULSES_PER_TICK]

    for seat in order:
        sim = state.get_census(seat["sim_id"])
        if sim.get("is_sleeping") or sim.get("is_off_lot_duty"):
            continue
        physical_ok = physical_actions_allowed(
            sim.get("needs"), sim.get("schedule_blocks"), tick
        )
        ctx = build_impulse_context(
            sim.get("sim_id"), sim.get("name", ""), seat.get("tier", "full"),
            sim.get("mood"), sim.get("activity"), sim.get("needs"),
            sim.get("is_off_lot_duty"), sim.get("is_sleeping"), tick,
            schedule_blocks=sim.get("schedule_blocks"),
        )
        # dedup_key throttles to one in-flight impulse per sim.
        state.scheduler.submit_bg(
            "sim.impulse", ctx, lang, trace_id=trace_id,
            dedup_key="{}:{}:impulse".format(save_id, seat["sim_id"]),
            callback=_impulse_callback(
                state, int(seat["sim_id"]), tick, trace_id, physical_ok,
            ),
        )
        scheduled += 1

    # Social layer: detect a conversational pair and schedule sim.social.
    pair = _find_conversational_pair(state, active_sim_id)
    if pair:
        sim_a, sim_b = pair
        gate = preflight(sim_a, sim_b, active_sim_id)
        a_id = int(sim_a.get("sim_id", 0))
        b_id = int(sim_b.get("sim_id", 0))
        if gate.get("ok") and _speech_allowed(state, [a_id, b_id], time.time()):
            rumor = _pick_rumor(state, sim_a, sim_b)
            ctx = build_social_context(sim_a, sim_b, tick, rumor=rumor)
            state.scheduler.submit_bg(
                "sim.social", ctx, lang, trace_id=trace_id,
                dedup_key="{}:{}-{}:social".format(save_id, a_id, b_id),
                callback=_social_callback(state, sim_a, sim_b, rumor, tick),
            )
            scheduled += 1

    # God Director: plans/zeitgeist are already submitted in the background;
    # narration is scheduled asynchronously inside god_tick.
    god_result = god_tick_handler(state, save_id, tick, lang)
    for directive in god_result.get("directives", []):
        intents.append(normalize_intent({
            "sim_id": active_sim_id or 0,
            "kind": "command",
            "params": {"visual_type": directive.get("visual_type", "SPECIAL_MOMENT"), "text": directive.get("text", "")},
            "source": "god",
        }, default_source="god"))

    # Drain intents ready now (from this call and previous background jobs).
    intents.extend(state.drain_intents())

    return {
        "ok": True,
        "scheduled": scheduled,
        "intents": intents,
        "social_sessions": [],
    }


#: Substrings that mark an interaction as conversational. The mod reports the
#: interaction class name (e.g. "SocialInteraction"), not a semantic activity,
#: so match case-insensitively instead of requiring an exact vocabulary.
_CONVERSATION_MARKERS = ("social", "talk", "chat", "convers")


def _is_conversing(sim: Dict[str, Any]) -> bool:
    activity = (sim.get("activity") or "").lower()
    return any(marker in activity for marker in _CONVERSATION_MARKERS)


def _find_conversational_pair(state: AppState, active_sim_id: Optional[int]):
    candidates = [
        sim for _sim_id, sim in state.census_items() if _is_conversing(sim)
    ]
    if len(candidates) >= 2:
        return candidates[0], candidates[1]
    return None


def _pick_rumor(state: AppState, sim_a: Dict[str, Any], sim_b: Dict[str, Any]):
    store = _store(state)
    if store is None:
        return None
    save_id = state.active_save_id or 0
    rumors = get_rumors(store, save_id)
    for rumor in rumors:
        if has_rumor_to_spread(int(sim_a.get("sim_id", 0)), rumor) and not has_rumor_to_spread(int(sim_b.get("sim_id", 0)), rumor):
            return rumor
    return None


#: Event categories that are by nature public (become neighborhood rumors).
_PUBLIC_CATEGORIES = ("death", "betrayal", "romance", "fight", "promotion")


def _create_rumor_from_event(
    state: AppState,
    sim_id: int,
    category: str,
    impact: float,
    salience: float,
    tick: int,
    lang: str,
    witnesses: List[Any],
) -> Optional[Dict[str, Any]]:
    """Generate and persist a RumorNode from a salient public event (F22)."""
    store = _store(state)
    if store is None:
        return None
    save_id = state.active_save_id or 0
    source = state.get_census(sim_id)
    ctx = {
        "sim_id": sim_id, "sim_name": source.get("name", ""),
        "event_category": category, "impact": impact,
        "salience": salience, "world_sim_tick": tick,
    }
    result = state.scheduler.run_purpose("world.gossip", ctx, lang)
    data = result.data or {}
    text = data.get("rumor", "")
    if not text:
        return None
    rumor = create_rumor(text, data.get("tags", []) or [category], sim_id, tick)
    for witness in witnesses or []:
        try:
            witness_id = int(witness)
        except (TypeError, ValueError):
            continue
        if witness_id and witness_id != sim_id:
            rumor = spread(rumor, witness_id)
    rumors = get_rumors(store, save_id)
    rumors.append(rumor)
    save_rumors(store, save_id, rumors[-50:], tick)
    logger.info("rumor created from %s event by sim=%s", category, sim_id)
    return rumor


def _spread_rumor(state: AppState, rumor: Dict[str, Any], a_id: int, b_id: int, tick: int) -> None:
    """Contagion: both conversation participants become rumor knowers (REQ-WLD-01)."""
    store = _store(state)
    if store is None:
        return
    save_id = state.active_save_id or 0
    updated: List[Dict[str, Any]] = []
    changed = False
    for existing in get_rumors(store, save_id):
        if existing.get("id") == rumor.get("id"):
            before = [int(s) for s in (existing.get("known_by_sim_ids", []) or [])]
            existing = spread(existing, a_id)
            existing = spread(existing, b_id)
            after = [int(s) for s in (existing.get("known_by_sim_ids", []) or [])]
            changed = changed or after != before
        updated.append(existing)
    if changed:
        save_rumors(store, save_id, updated, tick)


# ── chat ─────────────────────────────────────────────────────────────────
def handle_chat(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    state.current_lang = lang
    sim_id = int(payload.get("sim_id", 0))
    channel = payload.get("channel", "phone_sms")
    message = payload.get("message", "")
    tick = int(payload.get("world_sim_tick", 0))

    sim = state.get_census(sim_id) or {"sim_id": sim_id, "name": ""}
    if is_deferred(sim, channel):
        return {
            "response": render_fallback("sim.chat", lang, {"sim_name": sim.get("name", "")}).get("response", ""),
            "thought": "",
            "intents": [],
            "trust_delta": 0.0,
            "deferred": True,
        }

    store = _store(state)
    memories = store.recent_memories(sim_id, limit=8) if store else []
    profile = (store.get_sim_profile(sim_id) or {}).get("profile") if store else None

    ctx = build_chat_context(
        sim_id, sim.get("name", ""), payload.get("player_name", ""),
        channel, message, sim.get("friendship", 0.0), profile, memories,
        sim.get("mood", ""), sim.get("activity", ""), tick,
    )
    result = state.scheduler.run_purpose("sim.chat", ctx, lang)
    data = result.data or {}

    thought = extract_thought(data.get("response", "")) or data.get("thought", "")
    response = strip_thought(data.get("response", ""))

    # Short-term buffer + memory.
    state.append_chat_turn(sim_id, "user", message, tick)
    state.append_chat_turn(sim_id, "assistant", response, tick)
    if thought and store:
        store.add_memory(sim_id, "thought", {"text": thought}, search_text=thought, created_sim_tick=tick)

    intents = [normalize_intent(r, default_source="agent") for r in (data.get("intents", []) or []) if isinstance(r, dict)]
    state.enqueue_intents(intents)

    return {
        "response": response,
        "thought": "",
        "intents": intents,
        "trust_delta": trust_delta(data.get("trust_delta", 0.0)),
        "deferred": False,
    }


# ── events ───────────────────────────────────────────────────────────────
def handle_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    sim_id = int(payload.get("sim_id", 0))
    category = payload.get("event_category", "mundane")
    impact = float(payload.get("impact", 0.0))
    tick = int(payload.get("world_sim_tick", 0))
    salience = compute_salience(category, impact)

    triggered_jobs = []
    store = _store(state)
    if is_salient(category, impact):
        # Reinforce a psyche block and mark the sim for sleep consolidation.
        state.salient_since_sleep[sim_id] = True
        if store:
            existing = store.get_sim_profile(sim_id)
            profile = (existing or {}).get("profile") or {}
            blocks = profile.get("psyche_blocks", {}) or {}
            key = block_for_category(category)
            blocks = reinforce_block(blocks, key, min(1.0, salience - 1.5))
            profile["psyche_blocks"] = blocks
            store.upsert_sim_profile(sim_id, profile, tick)
        # Trigger a reaction (speak intent at the causer).
        sim = state.get_census(sim_id) or {"sim_id": sim_id, "name": ""}
        target_id = payload.get("target_sim_id")
        target = state.get_census(int(target_id or 0)) or {"name": ""}
        ctx = build_reaction_context(
            sim_id, sim.get("name", ""), target_id, target.get("name", ""),
            category, impact, salience, tick,
        )
        result = state.scheduler.run_purpose("sim.reaction", ctx, lang)
        data = result.data or {}
        for raw in (data.get("intents", []) or []):
            if isinstance(raw, dict):
                state.enqueue_intents([normalize_intent(raw, default_source="agent")])
        triggered_jobs.append("sim.reaction")

        # Public salient events seed a neighborhood rumor (F22 / P24).
        witnesses = payload.get("witnesses") or []
        if witnesses or category in _PUBLIC_CATEGORIES:
            rumor = _create_rumor_from_event(
                state, sim_id, category, impact, salience, tick, lang, witnesses,
            )
            if rumor:
                triggered_jobs.append("world.gossip")
                state.enqueue_intents([normalize_intent({
                    "sim_id": sim_id, "kind": "command",
                    "params": {
                        "command": "world.gossip",
                        "args": {"text": rumor.get("text", ""),
                                 "from": sim.get("name", "")},
                    },
                    "source": "god",
                }, default_source="god")])

    return {"ok": True, "salience": salience, "triggered_jobs": triggered_jobs}


# ── profile / evolve / consolidate ───────────────────────────────────────
def handle_profile(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    sim_id = int(payload.get("sim_id", 0))
    store = _store(state)
    sim = state.get_census(sim_id) or {"name": ""}
    force_interactive = bool(payload.get("force_interactive", False))

    profile = None
    if store:
        existing = store.get_sim_profile(sim_id)
        profile = existing["profile"] if existing else None

    if profile is None or force_interactive:
        ctx = {"sim_id": sim_id, "sim_name": sim.get("name", ""), "species": sim.get("species"), "age_stage": sim.get("age_stage"),
               "traits": sim.get("traits"), "likes": sim.get("likes"), "dislikes": sim.get("dislikes"),
               "world_sim_tick": int(payload.get("world_sim_tick", 0))}
        result = state.scheduler.run_purpose("sim.profile", ctx, lang)
        data = result.data or {}
        profile = normalize_profile(
            data, name=sim.get("name", ""), species=sim.get("species"),
            age_stage=sim.get("age_stage"), traits=sim.get("traits"),
            likes=sim.get("likes"), dislikes=sim.get("dislikes"),
        )
        if store:
            store.upsert_sim_profile(sim_id, profile, int(payload.get("world_sim_tick", 0)))

    return {"profile": profile}


def handle_evolve(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    sim_id = int(payload.get("sim_id", 0))
    tick = int(payload.get("world_sim_tick", 0))
    store = _store(state)
    sim = state.get_census(sim_id) or {"name": ""}
    profile = (store.get_sim_profile(sim_id) or {}).get("profile") if store else None
    ctx = build_reflect_context(sim_id, sim.get("name", ""), profile or {}, 0, tick)
    result = state.scheduler.run_purpose("evo.reflect", ctx, lang)
    data = result.data or {}
    # Fold the reflection back into the profile: only current_demeanor changes
    # (REQ-EVO-01), plus any evolution proposal surfaced to the panel (P31).
    if store and profile is not None:
        updated = apply_reflection(profile, data)
        if data.get("preference_change") or data.get("trait_proposal"):
            updated["evolution_proposal"] = {
                "preference_change": data.get("preference_change"),
                "trait_proposal": data.get("trait_proposal"),
            }
        store.upsert_sim_profile(sim_id, updated, tick)
    return {
        "reflection": data.get("reflection", ""),
        "demeanor_drift": data.get("demeanor_drift"),
        "preference_change": data.get("preference_change"),
        "trait_proposal": data.get("trait_proposal"),
    }


def _maybe_compact(state: AppState, sim_id: int, tick: int, lang: str) -> bool:
    """Archive + VACUUM once a sim accumulates enough consolidated memories (P27/A9)."""
    store = _store(state)
    if store is None:
        return False
    if store.count_consolidated(sim_id) < CONSOLIDATED_COMPACT_THRESHOLD:
        return False
    ids = store.consolidated_memory_ids(sim_id, COMPACT_ARCHIVE_COUNT)
    result = state.scheduler.run_purpose(
        "mem.compact", {"sim_id": sim_id, "world_sim_tick": tick}, lang,
    )
    text = (result.data or {}).get("compact", "")
    if text:
        store.add_memory(sim_id, "compact", {"text": text}, search_text=text,
                         created_sim_tick=tick)
    store.archive_memories(ids)
    store.vacuum()
    logger.info("mem.compact sim=%s archived=%d", sim_id, len(ids))
    return True


def handle_consolidate(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    sim_id = int(payload.get("sim_id", 0))
    tick = int(payload.get("world_sim_tick", 0))
    turns = state.chat_turns(sim_id)
    ctx = {"sim_id": sim_id, "turns": turns, "world_sim_tick": tick}
    result = state.scheduler.run_purpose("mem.consolidate", ctx, lang)
    data = result.data or {}
    store = _store(state)
    if store:
        store.add_memory(sim_id, "consolidated", {"text": data.get("consolidated", "")},
                         search_text=data.get("consolidated", ""), created_sim_tick=tick, consolidated=True)
    state.clear_chat_buffer(sim_id)
    compacted = _maybe_compact(state, sim_id, tick, lang)
    return {"consolidated": data, "compacted": compacted}


# ── god ──────────────────────────────────────────────────────────────────
def handle_god_tick(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    return god_tick_handler(state, int(payload.get("save_id", 0)), int(payload.get("world_sim_tick", 0)), lang)


def handle_direct_scene(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    return god_direct_scene(
        state, int(payload.get("save_id", 0)), int(payload.get("world_sim_tick", 0)),
        payload.get("catalyst_sim_ids") or [], payload.get("target_sim_ids") or [],
        payload.get("prompt_text", ""), payload.get("mode", "soft_catalyst"), lang,
    )


def handle_arc_steer(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    return god_steer(
        state, int(payload.get("save_id", 0)), payload.get("action", ""),
        payload.get("beat_id"), payload.get("custom_instruction"), lang,
    )


def handle_zeitgeist(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    return run_zeitgeist(state, int(payload.get("save_id", 0)), payload.get("zeitgeist_text", ""), lang)


def handle_controls_get() -> Dict[str, Any]:
    state = get_state()
    return {"controls": get_controls(state.panel, state.config)}


def handle_controls_post(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    ok = set_control(state.panel, state.config, payload.get("key", ""), payload.get("value"))
    return {"ok": bool(ok)}


# ── seats / player activity / health / status ────────────────────────────
def handle_seats_get() -> Dict[str, Any]:
    state = get_state()
    return SeatManager.snapshot(state.get_seats(), int(state.config.gameplay("agent_seats", 12)))


def handle_seats_post(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    seats = int(payload.get("seats", 12))
    # Seats are derived from census + priority; the POST is a hint only.
    return {"ok": True, "seats": min(seats, 64)}


def handle_player_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    idle = bool(payload.get("idle", False))
    clock_speed = int(payload.get("clock_speed", 1))
    # Deep window is open when the game is idle (paused / player away).
    deep_window_open = idle or clock_speed == 0
    return {"deep_window_open": deep_window_open}


def health() -> Dict[str, Any]:
    state = get_state()
    return {"status": "ok", "version": __version__, "game_pid": state.game_pid}


def status() -> Dict[str, Any]:
    state = get_state()
    scheduler_status = state.scheduler.status()
    providers = {}
    for name, cfg in state.config.providers().items():
        providers[name] = {
            "enabled": bool(cfg.get("enabled")),
            "models": cfg.get("models", []),
            "rpm": cfg.get("rpm", 0),
            "rpd": cfg.get("rpd", 0),
            "tpm": cfg.get("tpm", 0),
        }
    return {
        "chain": scheduler_status.get("chain", {}),
        "providers": providers,
        "limits": scheduler_status.get("chain", {}),
        "pool": {},
        "routes": state.config.raw().get("llm", {}).get("routes", {}),
        "tiers": state.config.raw().get("llm", {}).get("tiers", {}),
        "queue": {"depth": scheduler_status.get("queue_depth", 0)},
        "active_save": state.active_save_id,
        "installed_packs": sorted(state.installed_packs),
    }


# ── i18n ─────────────────────────────────────────────────────────────────
def handle_config_lang(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    state.current_lang = lang
    from .i18n_engine import get_engine
    get_engine().reload()
    return {"ok": True, "lang": lang}


def handle_compile_addon(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Generate a supplemental language .package for a community locale."""
    from .i18n_engine import get_engine
    engine = get_engine()
    requested = payload.get("locale", "")
    code = engine.resolve_locale(requested)
    # Best-effort: report the resolved locale; actual DBPF compilation is done
    # by the build_package.py tooling (kept sidecar-side free of heavy I/O).
    return {"ok": True, "locale": code, "path": "Sensewright_Locale_{}.package".format(code)}
