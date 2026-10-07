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
    SeatManager, action_context, apply_cognition, apply_reflection,
    build_chat_context, build_cognition_context, build_dream_context,
    build_impulse_context, build_reaction_context, build_reflect_context,
    coerce_float, compute_salience, decay_blocks, enforce_life_story,
    extract_thought, family_relation_label, hard_blocked_social, is_deferred,
    is_salient, location_context, normalize_age_stage, normalize_intent,
    normalize_profile, physical_actions_allowed, preflight, record_speech,
    reinforce_block, relationship_context, resolve_limits, sleep_transition,
    speech_allowed, strip_thought, trust_delta,
)
from .agent.psyche import block_for_category
from .agent.profile import PROFILE_SOURCE_LLM, PROFILE_SOURCE_TEMPLATE
from .agent.social import build_social_context, has_rumor_to_spread
from .constants import (
    AFTERMATH_SALIENCE_THRESHOLD, COMPACT_ARCHIVE_COUNT,
    CONSOLIDATED_COMPACT_THRESHOLD, LEGACY_CATEGORIES, TICKS_PER_SIM_DAY,
    TICKS_PER_SIM_MINUTE,
)
from .fallbacks import render_fallback
from .god import (
    beat_ended as god_beat_ended, current_beat, current_zeitgeist,
    deactivate_stale_arcs, direct_scene as god_direct_scene, get_controls,
    god_tick as god_tick_handler, resolve_autonomy_mode, resolve_dial, run_zeitgeist,
    set_control, steer as god_steer,
)
from .god.background_scheduler import select_targets
from .observability.logging import get_logger
from .schemas import normalize_lang, sanitize_payload, to_int
from .state import AppState, get_state
from .world.aftermath import (
    build_aftermath_context, merge_zeitgeist, parse_aftermath,
)
from .world.chronicle import (
    append_chronicle, get_chronicles, get_zeitgeist, set_zeitgeist,
)
from .world.rumors import (
    create_rumor, get_rumors, rumors_known_by, save_rumors, spread,
)

logger = get_logger("services")

#: Max autonomous LLM calls per autonomy tick (keeps realtime budget bounded).
MAX_IMPULSES_PER_TICK = 3
MAX_SOCIAL_PER_TICK = 1


def _store(state: AppState):
    return state.working_store()


def _resolve_family(state: AppState, sim_id: int) -> List[Dict[str, str]]:
    """Resolve a sim's census ``family_links`` into named relatives.

    The Mod stores ``family_links`` as ``{"target_sim_id": int, "relationship": str}``
    (some older builds stored bare ints). This maps each edge to
    ``{"name": ..., "relation": ...}`` using the census for the target's name and
    :func:`family_relation_label` for a readable label. Returns ``[]`` when the sim
    has no recorded relatives, so the chat prompt can explicitly ground (or omit)
    the sim's family.
    """
    sim = state.get_census(int(sim_id))
    links = sim.get("family_links") or []
    resolved: List[Dict[str, str]] = []
    seen: set = set()
    for link in links:
        if isinstance(link, dict):
            target_id = link.get("target_sim_id")
            relation = link.get("relationship") or link.get("relation") or ""
        else:
            target_id = link
            relation = ""
        try:
            target_id = int(target_id or 0)
        except (TypeError, ValueError):
            continue
        if not target_id or target_id == int(sim_id):
            continue
        if target_id in seen:
            continue
        seen.add(target_id)
        target_name = state.get_census(target_id).get("name", "")
        if not target_name:
            continue
        resolved.append({
            "name": str(target_name),
            "relation": family_relation_label(str(relation)),
        })
    return resolved


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


def _is_template_profile(profile: Optional[Dict[str, Any]]) -> bool:
    """True when a profile still lacks an LLM-generated persona (BUG-11).

    ``handle_census`` pre-creates a template profile for every census Sim, and
    ``handle_profile`` used to gate LLM generation on ``profile is None`` — which
    is never true once the template exists. Gate on whether the persona is empty
    instead: a template (or a 0-key fallback) has no core personality, demeanor
    or speech style.
    """
    if not isinstance(profile, dict):
        return True
    return not (
        profile.get("core_personality")
        or profile.get("current_demeanor")
        or profile.get("speech_style")
    )


def _profile_source(data: Dict[str, Any]) -> str:
    """Return ``llm`` when ``data`` carries a real persona, else ``template``.

    The 0-key fallback and the census template both leave the personality fields
    empty; only a successful ``sim.profile`` generation fills them. Tracking this
    on the profile keeps ``_is_template_profile`` honest without a separate flag.
    """
    if data.get("core_personality") or data.get("current_demeanor") or data.get("speech_style"):
        return PROFILE_SOURCE_LLM
    return PROFILE_SOURCE_TEMPLATE


def _profile_callback(state: AppState, sim_id: int, tick: int):
    """Background callback: persist a generated ``sim.profile`` (BUG-11)."""

    def _callback(result) -> None:
        try:
            data = result.data or {}
            sim = state.get_census(sim_id) or {"name": ""}
            profile = normalize_profile(
                data, name=sim.get("name", ""), species=sim.get("species"),
                age_stage=sim.get("age_stage"), traits=sim.get("traits"),
                likes=sim.get("likes"), dislikes=sim.get("dislikes"),
                source=_profile_source(data),
                generated_at_tick=tick,
            )
            _persist_profile(state, sim_id, profile, tick)
            state.incr("profiles_generated")
        except Exception:  # noqa: BLE001
            logger.exception("sim.profile callback failed for sim %s", sim_id)

    return _callback


def _schedule_profile_generation(state: AppState, sim_id: int, tick: int, lang: str) -> bool:
    """Schedule a background ``sim.profile`` generation for one sim (BUG-11).

    Bounded (one attempt per sim per session) and deduped; returns False when no
    job was scheduled (store unavailable, or already attempted this session). The
    LLM call runs off the request thread and the persona is persisted by
    ``_profile_callback``.
    """
    store = _store(state)
    if store is None:
        return False
    if sim_id in state.profile_generation_attempted:
        return False
    state.profile_generation_attempted.add(sim_id)
    sim = state.get_census(sim_id) or {"sim_id": sim_id, "name": ""}
    ctx = {
        "sim_id": sim_id, "sim_name": sim.get("name", ""),
        "species": sim.get("species"), "age_stage": sim.get("age_stage"),
        "gender": sim.get("gender"),
        "traits": sim.get("traits"), "likes": sim.get("likes"),
        "dislikes": sim.get("dislikes"), "world_sim_tick": int(tick),
    }
    state.scheduler.submit_bg(
        "sim.profile", ctx, lang,
        dedup_key="{}:{}:profile".format(state.active_save_id or 0, sim_id),
        callback=state.guard_callback("sim.profile", _profile_callback(state, sim_id, tick)),
    )
    return True


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
        callback=state.guard_callback(
            "sim.cognition", _cognition_callback(state, sim_id, tick)),
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
        callback=state.guard_callback(
            "sim.dream", _dream_callback(state, sim_id, tick, trace_id, lang)),
    )
    logger.info("sleep start sim=%s -> sim.dream", sim_id)


def _on_wake(state: AppState, sim: Dict[str, Any], tick: int, lang: str, trace_id) -> None:
    sim_id = int(sim.get("sim_id", 0))
    if not sim_id:
        return
    _apply_psyche_decay(state, sim_id, tick)

    # Always run the wake reflection (4.5): gating it behind a salient event left
    # `sleep_reflection` with zero rows in the audit DB. The salient flag still
    # biases the prompt content, but no longer suppresses persistence.
    salient = state.salient_since_sleep.pop(sim_id, False)
    profile = _sim_profile(state, sim_id)
    ctx = {
        "sim_id": sim_id, "sim_name": sim.get("name", ""),
        "world_sim_tick": tick,
        "psyche_blocks": profile.get("psyche_blocks") or {},
        "dream_urge": profile.get("dream_urge") or {},
        "salient": salient,
    }
    state.scheduler.submit_bg(
        "sim.sleep", ctx, lang, trace_id=trace_id,
        dedup_key="{}:{}:sleep".format(sim_id, tick // TICKS_PER_SIM_DAY),
        callback=state.guard_callback(
            "sim.sleep", _sleep_callback(state, sim_id, tick)),
    )

    last = state.last_reflect_tick.get(sim_id)
    if last is None or (int(tick) - int(last)) >= TICKS_PER_SIM_DAY:
        state.last_reflect_tick[sim_id] = int(tick)
        profile = _sim_profile(state, sim_id)
        ctx = build_reflect_context(sim_id, sim.get("name", ""), profile, 1, tick)
        state.scheduler.submit_bg(
            "evo.reflect", ctx, lang, trace_id=trace_id,
            dedup_key="{}:{}:reflect".format(sim_id, tick // TICKS_PER_SIM_DAY),
            callback=state.guard_callback(
                "evo.reflect", _reflect_callback(state, sim_id, tick)),
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
    store = _store(state)
    recent_rumors = []
    if store:
        try:
            from .world.rumors import get_rumors
            recent_rumors = [r.get("text") for r in get_rumors(store, save_id) if r.get("text")][-3:]
        except Exception:
            pass

    chronicle_ctx = {
        "save_id": save_id,
        "world_sim_tick": tick,
        "day": day,
        "neighborhood_rumors": recent_rumors,
    }
    state.scheduler.submit_bg(
        "world.household.chronicle",
        chronicle_ctx,
        lang, trace_id=trace_id,
        dedup_key="{}:{}:chronicle".format(save_id, day),
        callback=state.guard_callback(
            "world.household.chronicle", _chronicle_callback(state, save_id, tick)),
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
            callback=state.guard_callback(
                "sim.diary", _diary_callback(state, int(active_sim_id), tick)),
        )
        scheduled += 1
    return scheduled


# ── world.aftermath (P25) ─────────────────────────────────────────────────
def _aftermath_callback(state: AppState, save_id: int, tick: int):
    def _callback(result) -> None:
        try:
            data = parse_aftermath(result.data or {})
            store = _store(state)
            if store is not None and any(data["zeitgeist_shift"].values()):
                existing = get_zeitgeist(store, save_id)
                merged = merge_zeitgeist(existing, data["zeitgeist_shift"])
                set_zeitgeist(
                    store, save_id, merged.get("tags", []),
                    merged.get("preset", "drama"),
                    merged.get("weather_preference", "sunny"), tick,
                )
            intents = [
                normalize_intent(raw, default_source="world")
                for raw in data.get("intents", []) if isinstance(raw, dict)
            ]
            if intents:
                state.enqueue_intents(intents)
        except Exception:  # noqa: BLE001
            logger.exception("aftermath callback failed for save %s", save_id)

    return _callback


# ── conversation sessions & close (P06) ───────────────────────────────────
def _conversation_pairs(state: AppState) -> Dict[str, tuple]:
    """Map of active conversing pair -> (sim_a, sim_b), keyed deterministically."""
    items = dict(state.census_items())
    pairs: Dict[str, tuple] = {}
    for sim_id, sim in items.items():
        if not sim.get("is_conversing"):
            continue
        target_id = int(sim.get("social_target_sim_id") or 0)
        if not target_id or target_id not in items:
            continue
        a, b = sorted((int(sim_id), int(target_id)))
        pairs["{}-{}".format(a, b)] = (a, b)
    return pairs


def _track_conversations(state: AppState, tick: int, lang: str, trace_id) -> int:
    """Open/close ConversationSessions from census edges and fire sim.social.close (P06)."""
    current = _conversation_pairs(state)
    previous = set(state.conversations.keys())
    current_keys = set(current.keys())

    for key in current_keys - previous:
        a, b = current[key]
        state.conversations[key] = {"sim_a": a, "sim_b": b, "start_tick": int(tick)}

    closed = 0
    for key in previous - current_keys:
        session = state.conversations.pop(key, None)
        if not session:
            continue
        a_id, b_id = int(session.get("sim_a", 0)), int(session.get("sim_b", 0))
        sim_a, sim_b = state.get_census(a_id), state.get_census(b_id)
        ctx = {
            "sim_id": a_id, "sim_name": sim_a.get("name", ""),
            "target_sim_id": b_id, "target_name": sim_b.get("name", ""),
            "world_sim_tick": int(tick),
        }
        state.scheduler.submit_bg(
            "sim.social.close", ctx, lang, trace_id=trace_id,
            dedup_key="{}:{}-{}:social_close".format(state.active_save_id or 0, a_id, b_id),
            callback=state.guard_callback(
                "sim.social.close", _social_close_callback(state, a_id, b_id, tick)),
        )
        closed += 1
    return closed


def _social_close_callback(state: AppState, a_id: int, b_id: int, tick: int):
    def _callback(result) -> None:
        try:
            data = result.data or {}
            summary = (
                data.get("summary")
                or data.get("event_summary")
                or data.get("social_memory")
                or ""
            )
            store = _store(state)
            if summary and store is not None:
                for src, other in ((a_id, b_id), (b_id, a_id)):
                    store.add_memory(
                        src, "social", {"text": summary, "with": other},
                        search_text=summary, created_sim_tick=tick,
                    )
                state.incr("social_sessions_closed")
        except Exception:  # noqa: BLE001
            logger.exception("social close callback failed for %s/%s", a_id, b_id)

    return _callback


def _social_sessions(state: AppState) -> List[Dict[str, Any]]:
    return [
        {"sim_a": s.get("sim_a"), "sim_b": s.get("sim_b"),
         "start_tick": s.get("start_tick")}
        for s in state.conversations.values()
    ]


def _conversing_sim_ids(state: AppState) -> List[int]:
    """Flat list of sim ids currently in a conversation (SeatManager expects ids)."""
    ids = set()
    for pair in state.conversations.values():
        for key in ("sim_a", "sim_b"):
            try:
                sim_id = int(pair.get(key, 0))
            except (TypeError, ValueError):
                continue
            if sim_id:
                ids.add(sim_id)
    return sorted(ids)


# ── ops.recap (P32) ───────────────────────────────────────────────────────
def _recap_callback(state: AppState, tick: int):
    def _callback(result) -> None:
        try:
            data = result.data or {}
            state.recap = {
                "headline": data.get("headline", ""),
                "recap_text": data.get("recap_text", ""),
                "tick": int(tick),
            }
            state.incr("recap_ready")
        except Exception:  # noqa: BLE001
            logger.exception("recap callback failed")

    return _callback


# ── background scheduler / NPC background (P21/P22/P13) ───────────────────
def _background_callback(state: AppState, sim_id: int, tick: int, purpose: str):
    def _callback(result) -> None:
        try:
            data = result.data or {}
            text = data.get("background") or data.get("backstory") or ""
            store = _store(state)
            if text and store is not None:
                store.set_sim_background(sim_id, str(text), tick)
                state.incr("npc_backgrounds")
        except Exception:  # noqa: BLE001
            logger.exception("%s callback failed for sim %s", purpose, sim_id)

    return _callback


def _maybe_background(state: AppState, tick: int, lang: str, trace_id, active_sim_id) -> int:
    """Populate a background for the highest-priority sim lacking one (P21)."""
    store = _store(state)
    if store is None:
        return 0
    scheduled = 0
    for sim in select_targets(state, active_sim_id, cap=1):
        sim_id = int(sim.get("sim_id", 0))
        if not sim_id:
            continue
        sim = state.get_census(sim_id)
        if (store.get_sim_profile(sim_id) or {}).get("background"):
            continue
        state.scheduler.submit_bg(
            "god.background",
            {"sim_id": sim_id, "sim_name": sim.get("name", ""), "world_sim_tick": tick},
            lang, trace_id=trace_id,
            dedup_key="{}:{}:god_background".format(state.active_save_id or 0, sim_id),
            callback=state.guard_callback(
                "god.background", _background_callback(state, sim_id, tick, "god.background")),
        )
        scheduled += 1
    return scheduled


def _maybe_npc_backstory(state: AppState, tick: int, lang: str, trace_id) -> int:
    """Generate a background for a recurring non-player townie (P22)."""
    store = _store(state)
    if store is None:
        return 0
    recurring = []
    for _sid, sim in state.census_items():
        if sim.get("is_player"):
            continue
        sim_id = int(sim.get("sim_id", 0))
        if not sim_id:
            continue
        state.townie_sightings[sim_id] = state.townie_sightings.get(sim_id, 0) + 1
        if state.townie_sightings[sim_id] == 2:
            recurring.append(sim_id)
    if not recurring:
        return 0
    sim_id = recurring[0]
    if (store.get_sim_profile(sim_id) or {}).get("background"):
        return 0
    sim = state.get_census(sim_id)
    state.scheduler.submit_bg(
        "world.npc.backstory",
        {"sim_id": sim_id, "sim_name": sim.get("name", ""), "world_sim_tick": tick},
        lang, trace_id=trace_id,
        dedup_key="{}:{}:npc_backstory".format(state.active_save_id or 0, sim_id),
        callback=state.guard_callback(
            "world.npc.backstory", _background_callback(state, sim_id, tick, "world.npc.backstory")),
    )
    return 1


def _maybe_expand_background(state: AppState, tick: int, lang: str, trace_id, active_sim_id) -> int:
    """Seed 3 backstory memories for the active sim's family (P13)."""
    if not active_sim_id:
        return 0
    active = state.get_census(int(active_sim_id))
    scheduled = 0
    for link in active.get("family_links") or []:
        target = int(link.get("target_sim_id") or 0) if isinstance(link, dict) else int(link or 0)
        if not target or target in state.background_expanded:
            continue
        state.background_expanded.add(target)
        sim = state.get_census(target)

        def _expand_callback(result, target_id=target):
            try:
                data = result.data or {}
                entries = data.get("backstory") or data.get("memories") or data.get("background") or []
                if isinstance(entries, str):
                    entries = [entries]
                store = _store(state)
                if store is not None:
                    for text in list(entries)[:3]:
                        if text:
                            store.add_memory(
                                target_id, "backstory", {"text": str(text)},
                                search_text=str(text), created_sim_tick=tick,
                            )
                    state.incr("background_expanded")
            except Exception:  # noqa: BLE001
                logger.exception("background expand callback failed for sim %s", target_id)

        state.scheduler.submit_bg(
            "sim.background.expand",
            {"sim_id": target, "sim_name": sim.get("name", ""), "world_sim_tick": tick},
            lang, trace_id=trace_id,
            dedup_key="{}:{}:bg_expand".format(state.active_save_id or 0, target),
            callback=state.guard_callback("sim.background.expand", _expand_callback),
        )
        scheduled += 1
    return scheduled


# ── mem.relationship.review (P29) ─────────────────────────────────────────
def _maybe_relationship_review(state: AppState, tick: int, lang: str, trace_id, active_sim_id) -> int:
    """Review the active sim's strongest edge once per sim-day (P29)."""
    if not active_sim_id:
        return 0
    sim_id = int(active_sim_id)
    last = state.last_relationship_review_tick.get(sim_id, -(10 ** 12))
    if tick - last < TICKS_PER_SIM_DAY:
        return 0
    edges = []
    prefix = "{}:".format(sim_id)
    for key, rel in state.relationships.items():
        if not key.startswith(prefix):
            continue
        try:
            target_id = int(key.split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        strength = abs(float(rel.get("friendship", 0.0))) + abs(float(rel.get("romance", 0.0)))
        edges.append((strength, target_id))
    if not edges:
        return 0
    edges.sort(reverse=True)
    _, target_id = edges[0]
    sim = state.get_census(sim_id)
    target = state.get_census(target_id)

    def _callback(result) -> None:
        try:
            # Advance the cadence only once the job actually landed, so a job
            # dropped by a stale session epoch is retried instead of silently
            # skipping a whole sim-day (P29).
            state.last_relationship_review_tick[sim_id] = tick
            data = result.data or {}
            note = data.get("qualitative_note") or data.get("note") or ""
            store = _store(state)
            if note and store is not None:
                store.upsert_relationship(
                    sim_id, target_id, qualitative_note=str(note), updated_sim_tick=tick,
                )
                state.incr("relationship_reviews")
        except Exception:  # noqa: BLE001
            logger.exception("relationship review callback failed for %s", sim_id)

    state.scheduler.submit_bg(
        "mem.relationship.review",
        {"sim_id": sim_id, "sim_name": sim.get("name", ""),
         "target_sim_id": target_id, "target_name": target.get("name", ""),
         "world_sim_tick": tick},
        lang, trace_id=trace_id,
        dedup_key="{}:{}:{}:rel_review".format(state.active_save_id or 0, sim_id, target_id),
        callback=state.guard_callback("mem.relationship.review", _callback),
    )
    return 1


# ── ops.panel.summary (P33) ───────────────────────────────────────────────
def _panel_summary(state: AppState) -> Dict[str, Any]:
    """Deterministic 2-line diagnostic summary (P33), no LLM cost."""
    arc = state.active_arc or {}
    beats = arc.get("beats") or []
    mode = str(state.config.god("director_mode", "AUTONOMOUS"))
    line1 = "{} | arc {} | beat {}/{}".format(
        mode, arc.get("id", "-"), int(arc.get("current_beat_idx", 0)), len(beats),
    )
    metrics = state.metrics_snapshot()
    line2 = "epoch {} | intents {} | stale {} | rewinds {}".format(
        state.session_epoch, metrics.get("intents_emitted", 0),
        metrics.get("stale_epoch_dropped", 0), metrics.get("rewinds", 0),
    )
    return {"line1": line1, "line2": line2, "text": line1 + "\n" + line2}


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
    save_id = to_int(payload.get("save_id", 0))
    tick = int(payload.get("world_sim_tick", 0))
    lang = normalize_lang(payload.get("lang"))
    state.current_lang = lang
    # reset_ram() bumps the epoch, invalidating callbacks from the prior session.
    state.reset_ram()
    result = state.save_vault.session_start(save_id, tick)
    state.active_save_id = save_id
    if result.get("rewound"):
        # A real rewind changed the memory timeline: invalidate in-flight jobs
        # again so none of them writes into the restored store (2.4).
        state.bump_epoch()
        state.incr("rewinds")
    # Seed just below the restored/current tick: the first autonomy pulse lands
    # on the same tick as session-start and must not be rejected as a duplicate.
    restored = result.get("restored_tick")
    baseline = restored if restored is not None else tick
    state.set_processed_tick(max(0, int(baseline) - 1))

    # BUG-02: self-heal a store polluted with duplicate active arcs. Keep the
    # most recent one (ordered by created_sim_tick DESC) and abort the rest so
    # the God Director has exactly one progressing narrative.
    store = state.working_store()
    if store is not None:
        actives = store.list_arcs(status="active")
        if len(actives) > 1:
            removed = deactivate_stale_arcs(store, actives[0].get("id"))
            state.incr("stale_arcs_deactivated", removed)
            logger.info("BUG-02: deactivated %d stale active arc(s)", removed)
        state.active_arc = actives[0] if actives else None

    # R8/P0: read persisted confidant sim_id from metadata so the Mod doesn't
    # re-create a duplicate confidant each session.
    confidant_sim_id = 0
    if store is not None:
        try:
            meta_val = store.get_metadata("player_confidant_sim_id")
            if meta_val:
                confidant_sim_id = int(meta_val)
        except Exception:  # noqa: BLE001
            pass

    # P32: always generate the "Previously on…" recap at session-start and keep
    # the (synthetic) job key so the client can correlate it via GET /v1/recap.
    recap_job_id = "{}:{}:ops.recap".format(save_id, tick)
    state.scheduler.submit_bg(
        "ops.recap",
        {"save_id": save_id, "world_sim_tick": tick},
        lang, dedup_key=recap_job_id,
        callback=state.guard_callback("ops.recap", _recap_callback(state, tick)),
    )

    return {
        "ok": True,
        "restored_tick": result.get("restored_tick"),
        "bootstrap_needed": bool(result.get("bootstrap_needed")),
        "rewound": bool(result.get("rewound")),
        "recap_job_id": recap_job_id,
        "player_confidant_sim_id": confidant_sim_id,
    }


def handle_zone_transition(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    save_id = to_int(payload.get("save_id", 0))
    tick = int(payload.get("world_sim_tick", 0))
    lang = normalize_lang(payload.get("lang")) or state.current_lang
    # 4.5(a): consolidate live chat threads before the zone clears them.
    consolidated = _consolidate_active_chats(state, tick, lang, limit=2)
    state.save_vault.zone_transition(save_id, tick)
    # Clear spatial intents only (REQ-MEM-02).
    cleared = state.drain_intents()
    state.conversations = {}
    return {"ok": True, "cleared_spatial_intents": len(cleared),
            "consolidated_sims": consolidated}


def handle_save(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    save_id = to_int(payload.get("save_id", 0))
    previous_save_id = payload.get("previous_save_id")
    tick = int(payload.get("world_sim_tick", 0))
    lang = normalize_lang(payload.get("lang")) or state.current_lang
    # 4.5(b): fold live chat threads into the store before it becomes committed.
    _consolidate_active_chats(state, tick, lang, limit=3)
    result = state.save_vault.save(save_id, previous_save_id, tick)
    return {"ok": True, "committed_tick": result.get("committed_tick", tick), "snapshot_rev": result.get("snapshot_rev", tick)}


def handle_census(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    sims = payload.get("sims") or []
    packs = payload.get("installed_packs")
    if isinstance(packs, list):
        state.installed_packs = {str(pack).upper() for pack in packs if pack}
    mods = payload.get("detected_mods")
    if isinstance(mods, list):
        state.detected_mods = [str(mod) for mod in mods if mod]
    hydrated = 0
    store = _store(state)
    census_update: Dict[int, Dict[str, Any]] = {}
    household_sim_ids: List[int] = []
    for sim in sims:
        if not isinstance(sim, dict):
            continue
        sim_id = int(sim.get("sim_id", 0))
        if not sim_id:
            continue
        # BUG-15: legacy builds report ``Age.YOUNGADULT``; normalize so the
        # enum keys (and every downstream age comparison) match the canonical token.
        if "age_stage" in sim:
            sim["age_stage"] = normalize_age_stage(sim.get("age_stage"))
        census_update[sim_id] = sim
        hydrated += 1
        if sim.get("is_player"):
            household_sim_ids.append(sim_id)
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
            # Aspiration collected by the Mod (2.2) seeds the profile ambition
            # without clobbering a value already evolved by sim.aspiration.
            if sim.get("aspiration") and not profile.get("ambition"):
                profile["ambition"] = str(sim.get("aspiration"))
                store.upsert_sim_profile(sim_id, profile, int(payload.get("world_sim_tick", 0)))
    # Ingest relationship edges for later mem.relationship.review (P29).
    relationships = payload.get("relationships") or []
    imported_edges = 0
    tick = int(payload.get("world_sim_tick", 0))
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        try:
            sim_id = int(rel.get("sim_id", 0))
            target_id = int(rel.get("target_sim_id", 0))
        except (TypeError, ValueError):
            continue
        if not sim_id or not target_id:
            continue
        friendship = float(rel.get("friendship", 0.0) or 0.0)
        romance = float(rel.get("romance", 0.0) or 0.0)
        bits = rel.get("bits") or []
        sentiments = rel.get("sentiments") or []
        state.relationships["{}:{}".format(sim_id, target_id)] = {
            "friendship": friendship, "romance": romance,
            "bits": bits, "sentiments": sentiments,
        }
        if store is not None:
            store.upsert_relationship(
                sim_id, target_id, friendship=friendship, romance=romance,
                updated_sim_tick=tick,
            )
        imported_edges += 1

    state.update_census(census_update)

    # BUG-11: generate a real persona for household sims at session-start (bounded,
    # background, deduped). The template profile created above is only a placeholder;
    # without this the LLM never runs and every dialogue is generic.
    lang = normalize_lang(payload.get("lang"))
    tick = int(payload.get("world_sim_tick", 0))
    max_profiles = int(state.config.gameplay("agent_seats", 12))
    scheduled_profiles = 0
    if store is not None:
        for sim_id in household_sim_ids[:max_profiles]:
            existing = store.get_sim_profile(sim_id)
            profile = (existing or {}).get("profile")
            if _is_template_profile(profile):
                if _schedule_profile_generation(state, sim_id, tick, lang):
                    scheduled_profiles += 1
    logger.info(
        "census: %d sims hydrated, %d household, %d profiles scheduled (relationships=%d)",
        hydrated, len(household_sim_ids), scheduled_profiles, imported_edges,
    )

    return {
        "ok": True,
        "hydrated_count": hydrated,
        "relationships_imported": imported_edges,
        "profiles_scheduled": scheduled_profiles,
    }


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


def _reaction_callback(state: AppState, sim_id: int, category: str, tick: int):
    """Enqueue the intents a realtime-async sim.reaction produced (4.2)."""

    def _callback(result) -> None:
        try:
            data = result.data or {}
            out: List[Dict[str, Any]] = []
            for raw in (data.get("intents", []) or []):
                if not isinstance(raw, dict):
                    continue
                intent = normalize_intent(raw, default_source="agent")
                # The reaction is the causer's own mind: never trust a sim_id the
                # model may have hallucinated (mirrors _impulse_callback). Without
                # this, `speak` intents carried sim_id=0 and were dropped by the
                # Mod as `sim_not_found`.
                intent["sim_id"] = int(sim_id)
                out.append(intent)
            if out:
                state.enqueue_intents(out)
        except Exception:  # noqa: BLE001
            logger.exception("reaction callback failed for sim %s", sim_id)

    return _callback


# ── R1: Closed-loop intent telemetry ──────────────────────────────────────
def _ingest_outcomes(state: AppState, save_id: int, tick: int, outcomes: List[Dict[str, Any]]) -> None:
    """Validate, count, and persist intent outcomes from the Mod.

    Each outcome must have: intent_id (str), status (applied|failed|expired|preempted_by_player),
    reason (str), sim_tick (int), action_id (optional str/int).
    Malformed entries are dropped silently. Capped at 200 per tick.
    """
    if not outcomes:
        return
    valid_statuses = {"applied", "failed", "expired", "preempted_by_player"}
    cleaned: List[Dict[str, Any]] = []
    for oc in outcomes[:200]:  # cap per tick
        if not isinstance(oc, dict):
            continue
        intent_id = oc.get("intent_id")
        status = oc.get("status")
        reason = oc.get("reason", "")
        sim_tick = oc.get("sim_tick")
        action_id = oc.get("action_id")
        if not isinstance(intent_id, (str, int)) or not intent_id:
            continue
        if not isinstance(status, str) or status not in valid_statuses:
            continue
        try:
            sim_tick = int(sim_tick or 0)
        except (TypeError, ValueError):
            sim_tick = 0
        cleaned.append({
            "intent_id": str(intent_id),
            "status": status,
            "reason": str(reason) if reason else "",
            "sim_tick": sim_tick,
            "action_id": str(action_id) if action_id is not None else None,
        })
        # Increment per-status counters in AppState metrics
        state.incr("outcomes_{}".format(status))
    if cleaned:
        state.incr("outcomes_total", len(cleaned))
        store = state.working_store()
        if store is not None:
            try:
                store.record_intent_outcomes(save_id, cleaned)
            except Exception:  # noqa: BLE001
                logger.exception("record_intent_outcomes failed for save %s", save_id)


def handle_action_outcomes(payload: Dict[str, Any]) -> Dict[str, Any]:
    """POST /v1/actions/outcomes — immediate/latency-sensitive outcome reports.

    Accepts the same payload shape as the `outcomes` field on autonomy tick.
    Returns a simple ack with the count of accepted outcomes.
    """
    state = get_state()
    save_id = to_int(payload.get("save_id", 0))
    tick = int(payload.get("world_sim_tick", 0))
    outcomes = payload.get("outcomes") or []
    _ingest_outcomes(state, save_id, tick, outcomes)
    return {"ok": True, "accepted": len([o for o in outcomes if isinstance(o, dict) and o.get("intent_id") and o.get("status") in ("applied", "failed", "expired", "preempted_by_player")])}


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
    save_id = to_int(payload.get("save_id", 0))
    active_sim_id = payload.get("active_sim_id")
    clock_speed = int(payload.get("clock_speed", 1))
    trace_id = payload.get("trace_id")

    # Tick idempotency (2.3): a re-delivered or replayed tick must not re-run
    # the ingestion side effects. Already-ready intents are still returned so a
    # duplicate request cannot strand them.
    if not state.accept_tick(tick):
        state.incr("duplicate_ticks")
        return {"ok": True, "scheduled": 0, "intents": state.drain_intents(),
                "social_sessions": [], "duplicate_tick": True}

    # R1: Closed-loop intent telemetry — ingest outcomes from the Mod.
    _ingest_outcomes(state, save_id, tick, payload.get("outcomes") or [])

    _merge_delta(state, payload.get("sims_delta") or [])

    # Venue context (venue_type / is_residential) grounds the location tone of
    # social and chat prompts.
    venue = payload.get("venue")
    if isinstance(venue, dict):
        state.zone_context = dict(venue)

    # R8/P0: Persist player_confidant_sim_id when the Mod reports it.
    confidant_id = payload.get("player_confidant_sim_id")
    if confidant_id:
        try:
            confidant_id = int(confidant_id)
            if confidant_id != 0:
                store = state.working_store()
                if store is not None:
                    store.set_metadata("player_confidant_sim_id", str(confidant_id))
        except Exception:  # noqa: BLE001
            pass

    # Pause handling: freeze autonomy when paused (REQ-ARCH-04).
    if clock_speed == 0:
        return {"ok": True, "scheduled": 0, "intents": state.drain_intents(), "social_sessions": []}

    # Panic switch (FC4/4.8): the player suspended autonomy from the Quick Menu.
    if state.paused:
        return {"ok": True, "scheduled": 0, "intents": state.drain_intents(),
                "social_sessions": _social_sessions(state), "paused": True}

    intents: List[Dict[str, Any]] = []
    scheduled = 0

    # Sleep-cycle edges drive sim.dream/cognition/sleep and evo.reflect (P07-P09).
    _process_sleep_transitions(state, tick, lang, trace_id)

    # End-of-day pipeline: household chronicle + diary (P23/P10).
    _maybe_end_of_day(state, save_id, tick, lang, trace_id, active_sim_id)

    # Silence-driven consolidation: one quiet chat thread per tick (4.5c).
    _maybe_silence_consolidate(state, tick, lang)

    # Conversation session edges -> sim.social.close (P06).
    _track_conversations(state, tick, lang, trace_id)

    # Long-horizon enrichment (bounded + deduped): family backstories, NPC
    # backgrounds, recurring-townie stories and relationship reviews (P13/P21/P22/P29).
    _maybe_expand_background(state, tick, lang, trace_id, active_sim_id)
    _maybe_background(state, tick, lang, trace_id, active_sim_id)
    _maybe_npc_backstory(state, tick, lang, trace_id)
    _maybe_relationship_review(state, tick, lang, trace_id, active_sim_id)

    # Recompute seats (purely local, no LLM).
    catalyst_ids = list(state.catalyst_leases.keys())
    max_seats = _effective_max_seats(state)
    lease_min = int(state.config.gameplay("lease_min_sim_minutes", 60))
    manager = SeatManager()
    active_household_id = None
    active_pos = None
    if active_sim_id:
        active_entry = state.get_census(int(active_sim_id))
        active_household_id = active_entry.get("household_id")
        active_pos = active_entry.get("pos")
    state.set_seats(manager.assign(
        dict(state.census_items()), active_household_id, active_sim_id, catalyst_ids,
        _conversing_sim_ids(state), tick, max_seats, lease_min,
        existing_seats=state.get_seats(), active_pos=active_pos,
    ))

    # Schedule idle impulses for the active sim + a bounded set of full seats.
    # 4.1: throttle per sim and shrink the per-tick budget when the scheduler is
    # already backed up, so a slow provider cannot make impulses bursty.
    budget = MAX_IMPULSES_PER_TICK
    queue_depth = int(state.scheduler.status().get("queue_depth", 0) or 0)
    if queue_depth >= int(state.config.gameplay("impulse_backpressure_queue_depth", 6)):
        budget = 1
    cooldown_ticks = (
        int(state.config.gameplay("impulse_cooldown_sim_minutes", 60)) * TICKS_PER_SIM_MINUTE
    )
    seats_snapshot = state.get_seats()
    full_seats = [s for s in seats_snapshot.values() if s.get("tier") == "full" and s.get("role") == "household"]
    order = []
    if active_sim_id and int(active_sim_id) in seats_snapshot:
        order.append(seats_snapshot[int(active_sim_id)])
    for seat in full_seats:
        if seat["sim_id"] not in [s["sim_id"] for s in order]:
            order.append(seat)
    order = order[:budget]
    # S-H01: sovereign-agent autonomy mode. ``off`` disables agent autonomy
    # entirely (player/God only); ``reactive`` keeps event reactions but skips
    # idle impulses. Default ``full`` preserves prior behavior.
    autonomy_mode = resolve_autonomy_mode(state.panel, state.config)
    schedule_impulses = autonomy_mode == "full"
    if not schedule_impulses:
        order = []

    # BUG-11: ensure the active sim and household seats have a real persona. The
    # census pass may miss them (e.g. ``is_player`` not yet resolved when the
    # census is collected at session-start), so re-check here on every autonomy
    # tick using the seat assignment — which already proved it can identify
    # household sims. RAM-guarded, so each sim is attempted once per session.
    for seat in order:
        profile = _sim_profile(state, int(seat["sim_id"]))
        if _is_template_profile(profile):
            _schedule_profile_generation(state, int(seat["sim_id"]), tick, lang)

    for seat in order:
        sim_id = int(seat["sim_id"])
        last_impulse = state.last_impulse_tick.get(sim_id)
        if last_impulse is not None and cooldown_ticks > 0 and (tick - last_impulse) < cooldown_ticks:
            continue
        sim = state.get_census(seat["sim_id"])
        if sim.get("is_sleeping") or sim.get("is_off_lot_duty"):
            continue
        state.last_impulse_tick[sim_id] = tick
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
            callback=state.guard_callback(
                "sim.impulse",
                _impulse_callback(
                    state, int(seat["sim_id"]), tick, trace_id, physical_ok,
                ),
            ),
        )
        scheduled += 1

    # Social layer: detect a conversational pair and schedule sim.social.
    # ``autonomy_mode == "off"`` suppresses agent-initiated social too.
    pair = _find_conversational_pair(state, active_sim_id) if autonomy_mode != "off" else None
    if pair:
        sim_a, sim_b = pair
        gate = preflight(sim_a, sim_b, active_sim_id)
        a_id = int(sim_a.get("sim_id", 0))
        b_id = int(sim_b.get("sim_id", 0))
        if gate.get("ok"):
            logger.info("sim.social pair %s/%s gate=%s", a_id, b_id, gate)
        if gate.get("ok") and _speech_allowed(state, [a_id, b_id], time.time()):
            rumor = _pick_rumor(state, sim_a, sim_b)
            # F04/P18: if one of the pair holds a catalyst lease, route the
            # dialogue asymmetrically (sovereign agent answers a puppeteered NPC).
            puppeteer = _puppeteer_context(state, sim_a, sim_b)
            ctx = build_social_context(
                sim_a, sim_b, tick, rumor=rumor, puppeteer=puppeteer,
                location=location_context(state, sim_a, sim_b),
                relationship=relationship_context(state, sim_a, sim_b),
            )
            state.scheduler.submit_bg(
                "sim.social", ctx, lang, trace_id=trace_id,
                dedup_key="{}:{}-{}:social".format(save_id, a_id, b_id),
                callback=state.guard_callback(
                    "sim.social", _social_callback(state, sim_a, sim_b, rumor, tick)),
            )
            scheduled += 1

    # God Director: plans/zeitgeist are already submitted in the background;
    # narration is scheduled asynchronously inside god_tick.
    god_result = god_tick_handler(state, save_id, tick, lang, active_sim_id=active_sim_id)
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
        "social_sessions": _social_sessions(state),
    }


#: Substrings that mark an interaction as conversational. The mod reports the
#: interaction class name (e.g. "SocialInteraction"), not a semantic activity,
#: so match case-insensitively instead of requiring an exact vocabulary.
_CONVERSATION_MARKERS = ("social", "talk", "chat", "convers")


def _is_conversing(sim: Dict[str, Any]) -> bool:
    # BUG-01: the Mod reports a reliable boolean because the target of a social
    # interaction is another Sim; class-name matching is only a fallback.
    if sim.get("is_conversing"):
        return True
    activity = (sim.get("activity") or "").lower()
    return any(marker in activity for marker in _CONVERSATION_MARKERS)


def _find_conversational_pair(state: AppState, active_sim_id: Optional[int]):
    """Find a conversing pair, preferring the Mod's explicit signal (BUG-01).

    1. A sim flagged ``is_conversing`` whose ``social_target_sim_id`` is known.
    2. Two sims whose ``activity`` matches a conversation marker.
    3. Relaxed fallback: two awake, visibly busy sims in the same room/range.
    """
    items = dict(state.census_items())

    for sim_id, sim in items.items():
        if not sim.get("is_conversing"):
            continue
        target_id = int(sim.get("social_target_sim_id") or 0)
        target = items.get(target_id)
        if target is not None and int(target.get("sim_id", target_id)) != int(sim_id):
            return sim, target

    candidates = [sim for _sid, sim in items.items() if _is_conversing(sim)]
    if len(candidates) >= 2:
        return candidates[0], candidates[1]

    return _proximity_pair(items, active_sim_id)


def _proximity_pair(items: Dict[int, Dict[str, Any]], active_sim_id: Optional[int]):
    """Conservative fallback for social classes whose target we could not resolve."""
    pool = [
        sim for _sid, sim in items.items()
        if not sim.get("is_sleeping")
        and str(sim.get("activity") or "").lower() not in ("", "idle")
        and sim.get("room_id") not in (None, 0)
    ]
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            a, b = pool[i], pool[j]
            if a.get("room_id") != b.get("room_id"):
                continue
            gate = preflight(a, b, active_sim_id)
            if gate.get("same_room") and gate.get("within_distance") and gate.get("capable_a") and gate.get("capable_b"):
                return a, b
    return None


def _puppeteer_context(
    state: AppState, sim_a: Dict[str, Any], sim_b: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build the asymmetric-dialogue context when a catalyst lease is in play."""
    lease = None
    catalyst_id = 0
    for sim in (sim_a, sim_b):
        sid = int(sim.get("sim_id", 0))
        if sid in state.catalyst_leases:
            lease = state.catalyst_leases.get(sid) or {}
            catalyst_id = sid
            break
    if catalyst_id == 0:
        return None
    other = sim_b if int(sim_a.get("sim_id", 0)) == catalyst_id else sim_a
    return {
        "objective": lease.get("objective", ""),
        "catalyst_name": (state.get_census(catalyst_id) or {}).get("name", ""),
        "agent_name": other.get("name", ""),
    }


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
            "ok": True,
            "response": render_fallback("sim.chat", lang, {"sim_name": sim.get("name", "")}).get("response", ""),
            "thought": "",
            "intents": [],
            "trust_delta": 0.0,
            "deferred": True,
        }

    store = _store(state)
    memories = store.recent_memories(sim_id, limit=8) if store else []
    profile = (store.get_sim_profile(sim_id) or {}).get("profile") if store else None

    # BUG-11 fallback: if the sim opens a chat while its persona is still an empty
    # template, kick off a background profile generation (non-blocking) so the
    # reply has a persona on the next message. The census pass usually covers this,
    # but a chat can arrive before that job lands.
    if _is_template_profile(profile):
        _schedule_profile_generation(state, sim_id, tick, lang)

    # BUG: friendship was never available — the mod never sent it and the census
    # omits it, so trust was pinned to the lowest tier. Prefer the wire value,
    # fall back to the census, then to the relationship store.
    friendship = coerce_float(payload.get("friendship"), sim.get("friendship", 0.0))
    player_name = payload.get("player_name") or sim.get("player_name") or ""
    history = state.chat_turns(sim_id)

    ctx = build_chat_context(
        sim_id, sim.get("name", ""), player_name,
        channel, message, friendship, profile, memories,
        sim.get("mood", ""), sim.get("activity", ""), tick,
        history=history, family=_resolve_family(state, sim_id),
        location=location_context(state, sim),
        action=action_context(sim),
        gender=sim.get("gender"),
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
        "ok": True,
        "response": response,
        "thought": "",
        "intents": intents,
        "trust_delta": trust_delta(data.get("trust_delta", 0.0)),
        "deferred": False,
    }


# ── events ───────────────────────────────────────────────────────────────
def _handle_legacy_event(
    state: AppState,
    sim_id: int,
    category: str,
    target_sim_id: Optional[int],
    tick: int,
    lang: str,
    trace_id,
) -> None:
    """Fire ``mem.legacy`` (+ ``sim.lifestory``) for a lifecycle event (P28/P11).

    Runs synchronously (like ``sim.reaction``) so the legacy memory is durable
    before the request returns and no background closure outlives the session.
    """
    store = _store(state)
    if store is None or not sim_id:
        return
    sim = state.get_census(sim_id) or {"sim_id": sim_id, "name": ""}
    target = state.get_census(int(target_sim_id or 0)) or {}
    ctx = {
        "sim_id": sim_id, "sim_name": sim.get("name", ""),
        "event_category": category,
        "target_sim_id": int(target_sim_id or 0), "target_name": target.get("name", ""),
        "world_sim_tick": int(tick),
    }
    result = state.scheduler.run_purpose("mem.legacy", ctx, lang, trace_id=trace_id)
    text = (result.data or {}).get("legacy", "")
    if text:
        store.add_memory(
            sim_id, "legacy",
            {"text": text, "category": category, "target_sim_id": int(target_sim_id or 0)},
            search_text=text, created_sim_tick=int(tick),
        )

    # A legacy event also appends a life-story chapter (kept within the budget).
    story_result = state.scheduler.run_purpose("sim.lifestory", ctx, lang, trace_id=trace_id)
    line = (story_result.data or {}).get("life_story") or (story_result.data or {}).get("chapter") or ""
    if line:
        profile = _sim_profile(state, sim_id)
        story = list(profile.get("life_story") or [])
        story.append(str(line))
        profile["life_story"] = enforce_life_story(story)
        _persist_profile(state, sim_id, profile, int(tick))
    logger.info("lifecycle %s event -> mem.legacy sim=%s", category, sim_id)


def handle_event(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    sim_id = int(payload.get("sim_id", 0))
    category = payload.get("event_category", "mundane")
    impact = float(payload.get("impact", 0.0))
    tick = int(payload.get("world_sim_tick", 0))
    trace_id = payload.get("trace_id")
    target_id = payload.get("target_sim_id")
    salience = compute_salience(category, impact)

    triggered_jobs = []
    store = _store(state)
    save_id = state.active_save_id or to_int(payload.get("save_id", 0))

    # Lifecycle events (2.1) produce a decay-immune legacy memory (P28) and a
    # life-story chapter, regardless of the salience threshold.
    if category in LEGACY_CATEGORIES:
        _handle_legacy_event(state, sim_id, category, target_id, tick, lang, trace_id)
        triggered_jobs.append("mem.legacy")

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
        target = state.get_census(int(target_id or 0)) or {"name": ""}
        ctx = build_reaction_context(
            sim_id, sim.get("name", ""), target_id, target.get("name", ""),
            category, impact, salience, tick,
        )
        # 4.2: run the reaction on the realtime pool so /v1/events never blocks
        # on provider latency. Intents land on the IntentBus via the callback.
        state.scheduler.submit_async(
            "sim.reaction", ctx, lang, trace_id=trace_id,
            dedup_key="{}:{}:{}:reaction".format(sim_id, category, tick),
            callback=state.guard_callback(
                "sim.reaction", _reaction_callback(state, sim_id, category, tick)),
        )
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

    # Post-climax aftermath: high-salience events nudge the zeitgeist and
    # enqueue durable world intents (P25).
    if salience >= AFTERMATH_SALIENCE_THRESHOLD:
        sim = state.get_census(sim_id) or {"sim_id": sim_id, "name": ""}
        ctx = build_aftermath_context(sim, category, impact, salience, tick)
        state.scheduler.submit_bg(
            "world.aftermath", ctx, lang, trace_id=trace_id,
            dedup_key="{}:{}:{}:aftermath".format(save_id, sim_id, tick),
            callback=state.guard_callback(
                "world.aftermath", _aftermath_callback(state, save_id, tick)),
        )
        triggered_jobs.append("world.aftermath")

    return {"ok": True, "salience": salience, "triggered_jobs": triggered_jobs}


# ── profile / evolve / consolidate ───────────────────────────────────────
def handle_profile(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    sim_id = int(payload.get("sim_id", 0))
    store = _store(state)
    sim = state.get_census(sim_id) or {"name": ""}
    force_interactive = bool(payload.get("force_interactive", False))
    tick = int(payload.get("world_sim_tick", 0))

    # 4.1: accept a profile edited in the Web Studio and persist it (native
    # traits/likes/dislikes/species/age remain ground truth via normalize).
    posted = payload.get("profile")
    if isinstance(posted, dict) and posted:
        profile = normalize_profile(
            posted, name=sim.get("name", ""), species=sim.get("species"),
            age_stage=sim.get("age_stage"), traits=sim.get("traits"),
            likes=sim.get("likes"), dislikes=sim.get("dislikes"),
            generated_at_tick=tick,
        )
        if store:
            store.upsert_sim_profile(sim_id, profile, tick)
        return {"profile": profile}

    profile = None
    if store:
        existing = store.get_sim_profile(sim_id)
        profile = existing["profile"] if existing else None

    # BUG-11: regenerate when there is no stored profile, when the caller forces
    # an interactive regeneration, OR when the stored profile is still a template
    # (empty persona) — the census pre-creates a template, which used to make the
    # `profile is None` gate never fire.
    if profile is None or force_interactive or _is_template_profile(profile):
        ctx = {"sim_id": sim_id, "sim_name": sim.get("name", ""), "species": sim.get("species"), "age_stage": sim.get("age_stage"),
               "gender": sim.get("gender"),
               "traits": sim.get("traits"), "likes": sim.get("likes"), "dislikes": sim.get("dislikes"),
               "world_sim_tick": int(payload.get("world_sim_tick", 0))}
        result = state.scheduler.run_purpose("sim.profile", ctx, lang)
        data = result.data or {}
        profile = normalize_profile(
            data, name=sim.get("name", ""), species=sim.get("species"),
            age_stage=sim.get("age_stage"), traits=sim.get("traits"),
            likes=sim.get("likes"), dislikes=sim.get("dislikes"),
            source=_profile_source(data), generated_at_tick=tick,
        )
        if store:
            store.upsert_sim_profile(sim_id, profile, int(payload.get("world_sim_tick", 0)))

    return {"profile": profile}


# ── FC2 Export/Import ────────────────────────────────────────────────────
#: Version of the portable Sim export bundle (bump on schema changes).
SIM_EXPORT_VERSION = 1


def handle_sim_export(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Export a Sim's profile, background, relationships and memories (FC2)."""
    state = get_state()
    store = _store(state)
    if not store:
        return {"error": "no active store"}
    sim_id = to_int(payload.get("sim_id"), 0)
    if not sim_id:
        return {"error": "missing sim_id"}

    bundle = store.export_sim_bundle(sim_id)
    export_data: Dict[str, Any] = {"version": SIM_EXPORT_VERSION, "sim_id": sim_id}
    export_data.update(bundle)
    return {"export_data": export_data}


def handle_sim_import(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Import an export bundle onto a target Sim (replaces profile + memories).

    Relationships are intentionally NOT imported: target sim ids differ across
    saves, so a robust relationship import needs an id-mapping step (FC5).
    """
    state = get_state()
    store = _store(state)
    if not store:
        return {"error": "no active store"}
    target_sim_id = to_int(payload.get("sim_id"), 0)
    if not target_sim_id:
        return {"error": "missing target sim_id"}
    export_data = payload.get("export_data")
    if not isinstance(export_data, dict) or not isinstance(export_data.get("profile"), dict):
        return {"error": "invalid export data"}
    version = to_int(export_data.get("version"), 0)
    if version > SIM_EXPORT_VERSION:
        return {"error": "unsupported export version {}".format(version)}
    try:
        imported = store.import_sim_bundle(target_sim_id, export_data, store.get_tick())
    except (ValueError, TypeError) as exc:
        return {"error": "invalid export data: {}".format(exc)}
    logger.info("sim.import target=%s memories=%d", target_sim_id, imported)
    return {"ok": True, "imported_memories": imported}


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


def _consolidate_active_chats(state: AppState, tick: int, lang: str, limit: int = 1) -> int:
    """Consolidate sims with live chat buffers (4.5). Returns the count handled."""
    count = 0
    for sim_id in list(state.chat_buffers.keys()):
        if limit > 0 and count >= limit:
            break
        if not state.chat_turns(sim_id):
            continue
        try:
            handle_consolidate({"sim_id": int(sim_id), "world_sim_tick": tick, "lang": lang})
            count += 1
        except Exception:  # noqa: BLE001
            logger.exception("consolidate on transition/save failed for sim %s", sim_id)
    return count


def _maybe_silence_consolidate(state: AppState, tick: int, lang: str) -> int:
    """Consolidate one sim whose chat went quiet for ``silence_consolidate_seconds``.

    Closes the black hole where ``silence_consolidate_seconds`` was dead config:
    without a caller, ``consolidated``/``sleep_reflection``/``compact`` never
    reached the DB (4.5c).
    """
    silence_seconds = float(state.config.gameplay("silence_consolidate_seconds", 300) or 0)
    if silence_seconds <= 0:
        return 0
    threshold_ticks = int(silence_seconds * (TICKS_PER_SIM_MINUTE / 60.0))
    for sim_id, buffer in list(state.chat_buffers.items()):
        if not (buffer.get("turns") or []):
            continue
        last_tick = int(buffer.get("last_tick", 0))
        if tick - last_tick >= threshold_ticks:
            try:
                handle_consolidate({"sim_id": int(sim_id), "world_sim_tick": tick, "lang": lang})
                return 1
            except Exception:  # noqa: BLE001
                logger.exception("silence consolidate failed for sim %s", sim_id)
    return 0


# ── god ──────────────────────────────────────────────────────────────────
def handle_god_tick(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    return god_tick_handler(state, to_int(payload.get("save_id", 0)), int(payload.get("world_sim_tick", 0)), lang)


def handle_direct_scene(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    return god_direct_scene(
        state, to_int(payload.get("save_id", 0)), int(payload.get("world_sim_tick", 0)),
        payload.get("catalyst_sim_ids") or [], payload.get("target_sim_ids") or [],
        payload.get("prompt_text", ""), payload.get("mode", "soft_catalyst"), lang,
    )


def handle_arc_steer(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    return god_steer(
        state, to_int(payload.get("save_id", 0)), payload.get("action", ""),
        payload.get("beat_id"), payload.get("custom_instruction"), lang,
    )


def handle_beat_ended(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Handle /v1/god/beat-ended: branch the arc after a catalyst interaction (2.9/P19)."""
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    return god_beat_ended(
        state,
        to_int(payload.get("save_id", 0)),
        int(payload.get("world_sim_tick", 0)),
        payload.get("decision", "ignore"),
        payload.get("agent_sim_id"),
        lang,
        target_sim_id=payload.get("target_sim_id"),
    )


def handle_zeitgeist(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    return run_zeitgeist(state, to_int(payload.get("save_id", 0)), payload.get("zeitgeist_text", ""), lang)


# ── diary (3.4) ──────────────────────────────────────────────────────────
def handle_diary_get(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a Sim's most recent saved diary entry (for the Diary Tooltip/Snoop)."""
    state = get_state()
    sim_id = int(payload.get("sim_id", 0))
    store = _store(state)
    if store is None or not sim_id:
        return {"ok": True, "sim_id": sim_id, "entry": ""}
    for memory in store.recent_memories(sim_id, limit=50):
        if memory.get("type") != "diary":
            continue
        content = memory.get("content") or {}
        entry = content.get("text", "") if isinstance(content, dict) else str(content)
        if entry:
            return {"ok": True, "sim_id": sim_id, "entry": entry}
    return {"ok": True, "sim_id": sim_id, "entry": ""}


# ── world / mailbox (P23 / P24 / 3.9) ────────────────────────────────────
def handle_neighborhood(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the save's chronicles, zeitgeist and (optionally) a Sim's rumors.

    The Mod's Mailbox "Neighborhood Stories" interaction consumes this (3.9).
    """
    state = get_state()
    save_id = to_int(payload.get("save_id", 0))
    sim_id = int(payload.get("sim_id", 0))
    store = _store(state)
    zeitgeist = current_zeitgeist(state, save_id)
    if store is None:
        return {"ok": True, "save_id": save_id, "zeitgeist": zeitgeist,
                "chronicles": [], "rumors": []}
    chronicles = get_chronicles(store, save_id)
    rumors = get_rumors(store, save_id)
    if sim_id:
        rumors = rumors_known_by(rumors, sim_id)
    return {
        "ok": True,
        "save_id": save_id,
        "zeitgeist": zeitgeist,
        "chronicles": chronicles,
        "rumors": rumors,
    }


# ── arc / cast read (4.3) ─────────────────────────────────────────────────
def handle_get_arc(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state = get_state()
    store = _store(state)
    arc = state.active_arc
    if arc is None and store is not None:
        actives = store.list_arcs(status="active")
        arc = actives[0] if actives else None
    return {"ok": True, "arc": arc or {}}


def handle_get_cast(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state = get_state()
    arc = state.active_arc or {}
    return {"ok": True, "cast": arc.get("cast", [])}


# ── aspiration (P12) ──────────────────────────────────────────────────────
def handle_aspiration(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    lang = normalize_lang(payload.get("lang"))
    sim_id = int(payload.get("sim_id", 0))
    tick = int(payload.get("world_sim_tick", 0))
    store = _store(state)
    sim = state.get_census(sim_id) or {"name": ""}
    profile = (store.get_sim_profile(sim_id) or {}).get("profile") if store else {}
    profile = profile or {}
    ctx = {
        "sim_id": sim_id, "sim_name": sim.get("name", ""),
        "current_ambition": profile.get("ambition", ""),
        "world_sim_tick": tick,
    }
    result = state.scheduler.run_purpose("sim.aspiration", ctx, lang)
    data = result.data or {}
    profile["ambition"] = data.get("ambition", profile.get("ambition", ""))
    if store:
        store.upsert_sim_profile(sim_id, profile, tick)
    return {"ambition": profile.get("ambition", ""), "milestone": data.get("milestone", "")}


# ── ops: recap + panel summary (P32/P33) ──────────────────────────────────
def handle_recap_get(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state = get_state()
    return {"ok": True, "recap": state.recap}


def handle_panel_summary() -> Dict[str, Any]:
    state = get_state()
    return {"ok": True, "summary": _panel_summary(state)}


# ── config: provider credentials (4.2) + panic (4.8/FC4) ──────────────────
def handle_provider_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    provider = str(payload.get("provider") or "").strip()
    if not provider:
        return {"ok": False, "error": "provider required"}
    providers = state.config.raw().setdefault("llm", {}).setdefault("providers", {})
    entry = providers.setdefault(provider, {})
    for key in ("enabled", "base_url", "api_key", "models", "rpm", "rpd", "tpm"):
        if key in payload:
            entry[key] = payload[key]
    for limit in ("rpm", "rpd", "tpm"):
        entry.setdefault(limit, 0)
    try:
        state.scheduler.reload_provider(provider)
    except Exception:  # noqa: BLE001
        logger.exception("provider reload failed for %s", provider)
    return {
        "ok": True, "provider": provider,
        "enabled": bool(entry.get("enabled")),
        "api_key_set": bool(entry.get("api_key")),
        "models": entry.get("models", []),
    }


def handle_config_panic(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state = get_state()
    state.paused = True
    drained = state.drain_intents()
    state.incr("panic_activations")
    return {"ok": True, "paused": True, "drained_intents": len(drained)}


def handle_config_resume(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    state = get_state()
    state.paused = False
    return {"ok": True, "paused": False}


def handle_config_panic_state(payload: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Read-only view of the panic switch so the Web Studio can render its state.

    ``GET /v1/config/panic`` is required because the Web Studio polls it; without
    this route the client received HTTP 405 and always showed "not paused".
    """
    state = get_state()
    return {"ok": True, "paused": bool(state.paused)}


def handle_controls_get() -> Dict[str, Any]:
    state = get_state()
    return {"controls": get_controls(state.panel, state.config)}


def handle_controls_post(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    key = str(payload.get("key", ""))
    value = payload.get("value")
    # 4.2: the Web Studio posts provider credentials as "provider.<name>.<field>".
    if key.startswith("provider."):
        parts = key.split(".")
        if len(parts) >= 3:
            return handle_provider_config({"provider": parts[1], ".".join(parts[2:]): value})
    ok = set_control(state.panel, state.config, key, value)
    return {"ok": bool(ok)}


# ── seats / player activity / health / status ────────────────────────────
def _effective_max_seats(state: AppState) -> int:
    """Seat cap: a persisted panel override wins over the config default (S-M01)."""
    override = state.panel.get("agent_seats")
    if override is not None:
        try:
            return max(1, min(int(override), 64))
        except (TypeError, ValueError):
            pass
    return int(state.config.gameplay("agent_seats", 12))


def handle_seats_get() -> Dict[str, Any]:
    state = get_state()
    max_seats = _effective_max_seats(state)
    seats = state.get_seats()
    store = _store(state)

    # The raw seat dict only carries sim_id/role/tier/lease; merge in the census
    # identity + stored profile/background + relationship edges so the Web Studio
    # Sims tab can show names and backstories (they previously rendered "Sim <id>"
    # with empty profiles).
    enriched = []
    for seat in seats.values():
        sim_id = int(seat.get("sim_id", 0))
        census = state.get_census(sim_id) or {}
        profile: Dict[str, Any] = {}
        background = ""
        if store is not None:
            row = store.get_sim_profile(sim_id)
            if row:
                profile = row.get("profile") or {}
                background = row.get("background") or ""
        name = census.get("name") or profile.get("name") or ""

        relationships = []
        prefix = "{}:".format(sim_id)
        for key, rel in state.relationships.items():
            if not key.startswith(prefix):
                continue
            try:
                target_id = int(key.split(":", 1)[1])
            except (IndexError, ValueError):
                continue
            target_census = state.get_census(target_id) or {}
            target_profile: Dict[str, Any] = {}
            if store is not None:
                trow = store.get_sim_profile(target_id)
                if trow:
                    target_profile = trow.get("profile") or {}
            relationships.append({
                "target_id": target_id,
                "target_name": target_census.get("name") or target_profile.get("name") or "",
                "friendship": rel.get("friendship", 0.0),
                "romance": rel.get("romance", 0.0),
            })

        enriched.append({
            "sim_id": sim_id,
            "role": seat.get("role"),
            "tier": seat.get("tier"),
            "lease_expires_tick": seat.get("lease_expires_tick"),
            "name": name,
            "household_id": census.get("household_id"),
            "profile": profile,
            "background": background,
            "relationships": relationships,
        })

    return {"seats": enriched, "pool": max(0, max_seats - len(enriched))}


def handle_seats_post(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    try:
        seats = int(payload.get("seats", 12))
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_seats"}
    seats = max(1, min(seats, 64))
    # Persist the override so it actually takes effect (S-M01); previously the
    # POST echoed the request but the pool always came from config.
    state.panel.set("agent_seats", seats)
    return {"ok": True, "seats": seats}


def handle_player_activity(payload: Dict[str, Any]) -> Dict[str, Any]:
    state = get_state()
    idle = bool(payload.get("idle", False))
    clock_speed = int(payload.get("clock_speed", 1))
    # Deep window is open when the game is idle (paused / player away).
    deep_window_open = idle or clock_speed == 0
    state.deep_window_open = deep_window_open
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
        # Flat provider->limiter map for the diagnostics panel; `chain` keeps the
        # richer nested shape (limiters + purpose cooldowns + cooldown seconds).
        "limits": (scheduler_status.get("chain") or {}).get("limiters", {}),
        "pool": {},
        "routes": state.config.raw().get("llm", {}).get("routes", {}),
        "tiers": state.config.raw().get("llm", {}).get("tiers", {}),
        "queue": {"depth": scheduler_status.get("queue_depth", 0)},
        "active_save": state.active_save_id,
        "installed_packs": sorted(state.installed_packs),
        "detected_mods": list(state.detected_mods),
        # 5.1: runtime counters, session epoch and tick/idle state.
        "metrics": state.metrics_snapshot(),
        "session_epoch": state.session_epoch,
        "last_processed_tick": state.last_processed_tick,
        "arc_planning": state.arc_planning,
        "paused": state.paused,
        "deep_window_open": state.deep_window_open,
        "recap": state.recap,
        # P33: deterministic 2-line diagnostic summary for the Quick Menu.
        "panel_summary": _panel_summary(state),
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
    """Generate a supplemental language .package for a community locale (4.5)."""
    from .i18n_compile import strings_to_stbl, write_locale_package
    from .i18n_engine import get_engine

    state = get_state()
    engine = get_engine()
    code = engine.resolve_locale(payload.get("locale", ""))
    raw_strings = payload.get("strings") or payload.get("manifest") or {}
    try:
        strings = strings_to_stbl(raw_strings) if raw_strings else {}
    except Exception:  # noqa: BLE001
        logger.exception("compile-addon: could not flatten strings")
        strings = {}
    if not strings:
        # Fall back to the engine's compiled content for the locale, if any.
        content = getattr(engine, "content", None)
        if callable(content):
            try:
                strings = content(code) or {}
            except Exception:  # noqa: BLE001
                strings = {}
    try:
        locale_byte = int(payload.get("locale_byte", 0) or 0)
    except (TypeError, ValueError):
        locale_byte = 0
    out_dir = state.data_dir / "compiled"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = str(out_dir / "Sensewright_Locale_{}.package".format(code))
    if strings:
        write_locale_package(path, locale_byte, strings)
    return {"ok": True, "locale": code, "path": path, "strings": len(strings)}
