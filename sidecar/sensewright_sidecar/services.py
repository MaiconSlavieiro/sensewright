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
    SeatManager, build_chat_context, build_cognition_context, build_dream_context,
    build_impulse_context, build_reaction_context, build_reflect_context,
    compute_salience, extract_thought, is_deferred, is_salient, normalize_intent,
    normalize_profile, physical_actions_allowed, preflight, reinforce_block,
    strip_thought, trust_delta,
)
from .agent.psyche import block_for_category
from .agent.social import build_social_context, has_rumor_to_spread
from .fallbacks import render_fallback
from .god import (
    current_zeitgeist, direct_scene as god_direct_scene, get_controls,
    god_tick as god_tick_handler, run_zeitgeist, set_control, steer as god_steer,
)
from .observability.logging import get_logger
from .schemas import normalize_lang, sanitize_payload
from .state import AppState, get_state
from .world.rumors import get_rumors, rumors_known_by

logger = get_logger("services")

#: Max autonomous LLM calls per autonomy tick (keeps realtime budget bounded).
MAX_IMPULSES_PER_TICK = 3
MAX_SOCIAL_PER_TICK = 1


def _store(state: AppState):
    return state.working_store()


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


def _impulse_callback(state: AppState, sim_id: int, tick: int, trace_id):
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
                # The impulse is the seat's own mind: never trust a sim_id the
                # model may have hallucinated from another context entry.
                intent["sim_id"] = int(sim_id)
                out.append(intent)
            if out:
                state.enqueue_intents(out)
        except Exception:  # noqa: BLE001
            logger.exception("impulse callback failed for sim %s", sim_id)

    return _callback


def _social_callback(state: AppState, sim_a: Dict[str, Any], sim_b: Dict[str, Any]):
    """Build the background callback that emits a social pair's speech intents."""

    a_id = int(sim_a.get("sim_id", 0))
    b_id = int(sim_b.get("sim_id", 0))

    def _callback(result) -> None:
        try:
            data = result.data or {}
            a_line = data.get("a_line", "")
            b_line = data.get("b_line", "")
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
                state.enqueue_intents(out)
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
        ctx = build_impulse_context(
            sim.get("sim_id"), sim.get("name", ""), seat.get("tier", "full"),
            sim.get("mood"), sim.get("activity"), sim.get("needs"),
            sim.get("is_off_lot_duty"), sim.get("is_sleeping"), tick,
        )
        # dedup_key throttles to one in-flight impulse per sim.
        state.scheduler.submit_bg(
            "sim.impulse", ctx, lang, trace_id=trace_id,
            dedup_key="{}:{}:impulse".format(save_id, seat["sim_id"]),
            callback=_impulse_callback(state, int(seat["sim_id"]), tick, trace_id),
        )
        scheduled += 1

    # Social layer: detect a conversational pair and schedule sim.social.
    pair = _find_conversational_pair(state, active_sim_id)
    if pair:
        sim_a, sim_b = pair
        gate = preflight(sim_a, sim_b, active_sim_id)
        if gate.get("ok"):
            rumor = _pick_rumor(state, sim_a, sim_b)
            ctx = build_social_context(sim_a, sim_b, tick, rumor=rumor)
            state.scheduler.submit_bg(
                "sim.social", ctx, lang, trace_id=trace_id,
                dedup_key="{}:{}-{}:social".format(
                    save_id, int(sim_a.get("sim_id", 0)), int(sim_b.get("sim_id", 0))),
                callback=_social_callback(state, sim_a, sim_b),
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
        # Reinforce a psyche block.
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
    store = _store(state)
    sim = state.get_census(sim_id) or {"name": ""}
    profile = (store.get_sim_profile(sim_id) or {}).get("profile") if store else None
    ctx = build_reflect_context(sim_id, sim.get("name", ""), profile or {}, 0, int(payload.get("world_sim_tick", 0)))
    result = state.scheduler.run_purpose("evo.reflect", ctx, lang)
    data = result.data or {}
    return {
        "reflection": data.get("reflection", ""),
        "demeanor_drift": data.get("demeanor_drift"),
        "preference_change": data.get("preference_change"),
        "trait_proposal": data.get("trait_proposal"),
    }


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
    return {"consolidated": data}


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
