"""Agent graph: main entry point for chat, hey, and tool handling."""

from __future__ import annotations

import logging
import time
from typing import Any

from ..config import Settings
from ..god.budgeter import BackgroundBudgeter
from ..god.orchestrator import GodOrchestrator
from ..god.scheduler import (
    PRIORITY_HOUSEHOLD_ACTIVE,
    PRIORITY_HOUSEHOLD_PLAYER,
    PRIORITY_PLAYER,
    PRIORITY_RELATED,
    PRIORITY_SIM_ACTIVE,
    PRIORITY_SIM_PLAYER,
    BackgroundJob,
    BackgroundScheduler,
)
from ..god.world_model import WorldState
from ..llm import ProviderRegistry, build_registry, langguard
from ..llm.budgeter import ChatBudgeter
from ..memory import MemoryStore, build_memory_store
from ..observability import AuditLog
from ..schemas import (
    DEFAULT_LANG,
    BackgroundRequest,
    ChatRequest,
    ChatResponse,
    EvolveRequest,
    HeyRequest,
    SimRef,
    ToolResultRequest,
    normalize_lang,
)
from ..tools.rails import DirectiveRails
from . import evolution, personality, profiler
from .agency import Agency, ImpulseJob
from .cognition import CognitionLayer
from .context_forge import ContextForge
from .coordinator import Coordinator
from .intents import intent_from_directive, normalize_intent
from .nodes import AgentNodes
from .presence import distance_between

logger = logging.getLogger(__name__)

# Tool names that carry spoken text (v0.4 P1 speech gating).
_SPEECH_NAMES = frozenset({"spontaneous_line", "say_to", "socialize"})

# Module-level state (configured by configure())
_registry: ProviderRegistry | None = None
_memory: MemoryStore | None = None
_nodes: AgentNodes | None = None
_settings: Settings | None = None
_current_lang: str = DEFAULT_LANG
_autonomy_default: str = "semi"
_rails: DirectiveRails | None = None
_audit: AuditLog | None = None

# Progressive batch pipeline that writes backgrounds off the request path.
_scheduler: BackgroundScheduler | None = None

# Per-Sim daily LLM budget for the real-time chat path.
_chat_budget: ChatBudgeter | None = None

# God orchestration tier (Phase 5c): the periodic decision loop that turns the
# world model into directives.
_orchestrator: GodOrchestrator | None = None

# v0.2 A2/A3: per-Sim initiative scheduler and single-writer arbitration.
_agency: Agency | None = None
_coordinator: Coordinator | None = None

# v0.3 R3: assembles the per-Sim context once per "think".
_context_forge: ContextForge | None = None

# Last census pushed by the mod, keyed by "player_id:save_id". Used to ground
# zeitgeist suggestions and background writing.
_census_by_save: dict[str, dict[str, Any]] = {}

# M2 retention: wall-clock of the last physical prune (throttled, see
# ``maybe_prune_memory``). 0.0 means "never pruned this process".
_last_prune_at: float = 0.0
_PRUNE_INTERVAL_SECONDS = 86400.0


def _census_key(player_id: str, save_id: str) -> str:
    return f"{player_id}:{save_id}"


def _note_lang(lang: Any) -> None:
    """Adopt the language the client (mod) reports as the running game language.

    The sidecar's own ``settings.lang`` starts at the default (en) and is only
    correct once a client request carries the real language. Every request path
    that knows the language funnels through here so event/reaction/God/background
    work uses the *game* language, not the sidecar default (v0.4 live fix).
    """
    global _current_lang
    if not lang:
        return
    try:
        code = normalize_lang(lang)
    except Exception:
        return
    if code and code != _current_lang:
        _current_lang = code
        logger.info("active language from client: %s", code)


def configure(settings: Settings) -> None:
    """(Re)build registry + memory + rails; idempotent."""
    global _registry, _memory, _nodes, _settings, _current_lang, _autonomy_default
    global _rails, _audit, _scheduler, _chat_budget, _orchestrator
    global _agency, _coordinator, _context_forge

    _settings = settings
    _current_lang = normalize_lang(settings.lang)
    _autonomy_default = settings.agents.autonomy_default
    _chat_budget = ChatBudgeter(per_sim_per_day=settings.llm.budget_per_sim_per_day)
    _orchestrator = GodOrchestrator(settings.god, lang=_current_lang)

    # A previous scheduler (if any) belongs to the old settings; rebuild lazily
    # in ``start_backgrounds`` so no task outlives its configuration.
    if _scheduler is not None:
        _scheduler.stop_now()
        _scheduler = None

    # Safety rails shared by every agent; audit log is best-effort.
    audit = None
    try:
        if _audit is not None:
            _audit.close()
        audit = AuditLog(settings.audit_path())
    except Exception as e:
        logger.warning(f"Audit log unavailable: {e}")
    _audit = audit
    _rails = DirectiveRails(
        max_per_minute=settings.agents.tool_calls_per_minute,
        player_lock_seconds=settings.agents.player_lock_seconds,
        audit=audit,
    )

    # Release the previous store's DB file handle before replacing it, else a
    # reconfigure (e.g. config reload or repeated ``configure`` in tests) leaks a
    # connection to the old data dir.
    if _memory is not None:
        close_previous = getattr(_memory, "close_sync", None)
        if callable(close_previous):
            try:
                close_previous()
            except Exception:
                pass

    # Build memory store
    try:
        _memory = build_memory_store(settings)
        logger.info("Memory store initialized")
    except Exception as e:
        logger.error(f"Failed to initialize memory store: {e}")
        # Create a minimal fallback memory
        from .memory_fallback import FallbackMemory
        _memory = FallbackMemory()

    # Build LLM registry
    try:
        _registry = build_registry(settings)
        logger.info("LLM registry initialized")
    except Exception as e:
        logger.error(f"Failed to initialize LLM registry: {e}")
        _registry = None

    # Build nodes
    if _registry and _memory:
        _nodes = AgentNodes(
            registry=_registry,
            memory=_memory,
            default_autonomy=_autonomy_default,
            default_lang=_current_lang,
            rails=_rails,
            dejavu_chance=settings.memory.dejavu_chance,
            memory_enabled=bool(getattr(settings.agents.layers, "memory", True)),
        )
    else:
        _nodes = None
        logger.warning("Agent nodes not initialized (missing registry or memory)")

    # v0.2 A2/A3: single-writer arbitration + per-Sim initiative scheduler.
    _coordinator = Coordinator()
    _context_forge = ContextForge(_memory, settings)
    if _agency is not None:
        _agency.stop_now()
    _agency = Agency(settings, runner=_run_agency_job)
    _agency.set_registry(_effective_registry())
    _agency.set_context_forge(_context_forge)


async def _run_background_job(job: BackgroundJob) -> dict[str, Any]:
    """Execute one scheduled job (background generation or memory consolidation)."""
    if job.kind == "consolidate":
        return await consolidate_now(
            SimRef(player_id=job.player_id, save_id=job.save_id, sim_id=job.sim_id),
            job.lang,
        )

    if _memory is None:
        return {"ok": False, "error": "memory not initialized"}

    census = _census_by_save.get(_census_key(job.player_id, job.save_id), {})
    census_entry = _census_entry_for_job(census, job)

    req = BackgroundRequest(
        sim=SimRef(
            player_id=job.player_id,
            save_id=job.save_id,
            sim_id=job.sim_id,
            household_id=job.household_id,
        ),
        scope=job.scope,
        household_id=job.household_id,
        player_hints=job.player_hints,
        census=census_entry,
        lang=job.lang,
    )
    return await generate_background(req)


# ─── v0.2 A2/A3/P1: per-Sim initiative runner ─────────────────────────

def _autonomy_for_job(job: ImpulseJob) -> str:
    """Resolve the autonomy level for an impulse (player Sims use their own)."""
    if _agency is not None:
        world = _agency.world_context(job.player_id, job.save_id)
        state = (world.get("sims") or {}).get(str(job.sim_id)) or {}
        level = state.get("autonomy")
        if level:
            return str(level)
        if _settings is not None and _agency.is_player(
            job.player_id, job.save_id, job.sim_id
        ):
            return _settings.agents.initiative.player_sim_level
    return _autonomy_default or "semi"


def _partner_in_conversation(job: ImpulseJob, world: dict[str, Any]) -> int | None:
    """A Sim currently targeting ``job.sim_id`` in a native interaction."""
    sims = (world or {}).get("sims") or {}
    for state in sims.values():
        if not isinstance(state, dict):
            continue
        try:
            if int(state.get("interaction_target_sim_id") or 0) == int(job.sim_id):
                return int(state.get("sim_id") or 0) or None
        except (TypeError, ValueError):
            continue
    return None


def _repair_intent(
    intent: dict[str, Any], job: ImpulseJob, world: dict[str, Any]
) -> dict[str, Any] | None:
    """Repair a malformed speech intent, or return None to drop it.

    ``socialize``/``say_to`` without a target are repaired to the Sim currently
    talking to the agent; if there is none they degrade to a murmur
    (``spontaneous_line``) so the mod never sees ``missing_argument``. Other
    tools pass through unchanged.
    """
    name = str(intent.get("name") or "")
    if name not in ("say_to", "socialize"):
        return intent
    args = intent.get("args")
    if not isinstance(args, dict):
        args = {}
    params = intent.get("params")
    if not isinstance(params, dict):
        params = {}

    target = (
        args.get("target_sim_id")
        or params.get("target_sim_id")
        or intent.get("target_sim_id")
    )
    if not target:
        target = _partner_in_conversation(job, world)
    if not target:
        text = (
            args.get("message")
            or args.get("text")
            or args.get("reason")
            or intent.get("reason")
            or intent.get("thought")
            or ""
        )
        text = str(text).strip()
        if not text:
            return None
        intent["name"] = "spontaneous_line"
        intent["kind"] = "speak"
        intent["target_sim_id"] = None
        intent["args"] = {"text": text, "audience": "self"}
        intent["params"] = {"text": text}
        return intent

    try:
        target_id = int(target)
    except (TypeError, ValueError):
        return None
    if name == "say_to" and not (args.get("message") or params.get("message")):
        message = str(intent.get("reason") or intent.get("thought") or "").strip()
        if not message:
            return None
        args["message"] = message
    args["target_sim_id"] = target_id
    params["target_sim_id"] = target_id
    intent["target_sim_id"] = target_id
    intent["args"] = args
    intent["params"] = params
    return intent


def _spoken_text(intent: dict[str, Any]) -> str:
    """The spoken line carried by a speech intent (params or args), else ''."""
    for source in (intent.get("params"), intent.get("args")):
        if not isinstance(source, dict):
            continue
        for key in ("text", "message"):
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _annotate_speech(
    intents: list[dict[str, Any]],
    *,
    job_kind: str,
    world: dict[str, Any],
    player_id: str,
    save_id: str,
    lang: str,
) -> None:
    """Set ``surfaced``/``speech_kind`` on every speech intent (v0.4 P1).

    A line detected in the wrong language is marked ``speech_lang_rejected`` and
    never surfaces (v0.4 P2); the caller drops rejected intents.
    """
    policy = getattr(_agency, "speech", None) if _agency is not None else None
    if policy is None:
        return
    sims = (world or {}).get("sims") or {}
    active_id = (world or {}).get("active_sim_id")
    active_sim = sims.get(str(active_id)) if active_id is not None else None

    for intent in intents:
        name = str(intent.get("name") or "")
        kind = str(intent.get("kind") or "")
        if kind != "speak" and name not in _SPEECH_NAMES:
            continue
        text = _spoken_text(intent)
        if text and langguard.is_wrong_lang(text, lang):
            intent["speech_lang_rejected"] = True
            logger.info(
                "langguard rejected speech sim=%s lang=%s text=%r",
                intent.get("sim_id"),
                lang,
                text[:80],
            )
        target = intent.get("target_sim_id")
        speech_kind = policy.classify(
            job_kind=job_kind, has_target=bool(target), intent_kind=kind
        )
        sim_state = sims.get(str(intent.get("sim_id")))
        distance = None
        if active_sim is not None and sim_state is not None:
            try:
                if int(sim_state.get("sim_id", 0)) != int(active_id):
                    distance = distance_between(sim_state, active_sim)
            except (TypeError, ValueError):
                distance = None
        sim_key = f"{player_id}:{save_id}:{intent.get('sim_id')}"
        surfaced = (
            not intent.get("speech_lang_rejected")
            and policy.should_surface(sim_key, kind=speech_kind, distance=distance)
        )
        params = intent.get("params")
        if not isinstance(params, dict):
            params = {}
        params["surfaced"] = surfaced
        intent["params"] = params
        intent["speech_kind"] = speech_kind
        if surfaced:
            policy.note(sim_key, kind=speech_kind)
        policy.log_line(
            sim_id=int(intent.get("sim_id") or 0),
            kind=speech_kind,
            surfaced=surfaced,
            lang=lang,
            distance=distance,
        )


async def _gate_intents(job: ImpulseJob, outcome: dict[str, Any]) -> list[dict[str, Any]]:
    """Pass impulse intents through the rails/coordinator; return the allowed ones.

    Intents are preferred over the legacy directive list; when only directives
    are present they are converted (tools the palette still emits). A command
    intent keeps its ``name``/``args`` so ``/v1/tools/result`` can still match it.
    """
    from ..memory.base import MemKey

    candidates: list[dict[str, Any]] = []
    if outcome.get("intents"):
        for raw in outcome.get("intents") or []:
            intent = normalize_intent(raw, default_sim_id=job.sim_id)
            if intent is not None:
                candidates.append(intent)
    else:
        for raw in outcome.get("directives") or []:
            intent = intent_from_directive(job.sim_id, raw, priority=job.priority)
            if intent is not None:
                candidates.append(intent)

    sim_key = f"{job.player_id}:{job.save_id}:{job.sim_id}"
    is_played = bool(_agency.is_player(job.player_id, job.save_id, job.sim_id)) if _agency else False
    allowed: list[dict[str, Any]] = []
    denied: list[tuple[str, str]] = []
    world = _agency.world_context(job.player_id, job.save_id) if _agency else {}

    for raw_intent in candidates:
        intent = _repair_intent(raw_intent, job, world)
        if intent is None:
            continue
        check_name = str(intent.get("name") or "")
        if _rails is not None and check_name:
            decision = _rails.check(sim_key, check_name)
            if not decision.allowed:
                denied.append((check_name, decision.reason))
                continue
            _rails.note_executed(sim_key, check_name)
        # Single-writer arbitration (the agent owns played Sims; God never controls).
        if _coordinator is not None:
            _coordinator.arbitrate(
                is_played=is_played,
                source=str(intent.get("source") or "agent"),
                tool_name=check_name,
            )
        allowed.append(intent)

    _annotate_speech(
        allowed,
        job_kind=job.kind,
        world=world,
        player_id=job.player_id,
        save_id=job.save_id,
        lang=job.lang or _current_lang,
    )
    # v0.4 P2: never surface/execute a line detected in the wrong language.
    allowed = [intent for intent in allowed if not intent.get("speech_lang_rejected")]

    if denied and _memory is not None:
        mem_key = MemKey(job.player_id, job.save_id, int(job.sim_id))
        for name, reason in denied:
            try:
                await _memory.add_event(
                    mem_key,
                    {
                        "type": "directive_denied",
                        "content": {"tool": name, "reason": reason},
                        "importance": 0.4,
                    },
                )
            except Exception:
                pass

    # Register command intents as pending so /v1/tools/result can match them.
    if _nodes is not None:
        commands = [intent for intent in allowed if intent.get("name")]
        if commands:
            try:
                state = _nodes._get_state(sim_key)
                pending = list(state.pending_tool_calls)
                pending.extend(
                    {
                        "id": intent["id"],
                        "name": intent["name"],
                        "args": intent.get("args") or intent.get("params") or {},
                        "status": "pending",
                    }
                    for intent in commands
                )
                state.set_pending_tool_calls(pending)
            except Exception:
                pass
    return allowed


async def _sleep_consolidation(
    job: ImpulseJob,
    key,
    profile: dict[str, Any],
    lang: str,
    registry: ProviderRegistry | None,
) -> dict[str, Any]:
    """Absorb a sleep episode: fold dialogue (M1) + drift psyche (P1)."""
    from ..memory import consolidation as dialogue_consolidation

    assert _memory is not None and _settings is not None
    used_llm = False

    # M1 — collapse the raw chat turns into one consolidated memory.
    if _settings.memory.consolidation_enabled:
        try:
            turns = await _memory.unconsolidated_events(key, limit=100)
        except Exception:
            turns = []
        if len(turns) >= 2:
            if registry is not None:
                used_llm = True
            result = await dialogue_consolidation.consolidate_turns(
                turns, profile, registry, lang
            )
            try:
                await _memory.add_event(
                    key,
                    {
                        "type": "consolidated_memory",
                        "content": result,
                        "importance": 1.2,
                        "emotion": (result.get("emotional_takeaways") or [None])[0],
                        "salience": 1.2,
                    },
                )
            except Exception as exc:
                logger.warning(f"consolidated memory persist failed: {exc}")
            try:
                await _memory.mark_consolidated(
                    key, [turn.get("id") for turn in turns if turn.get("id") is not None]
                )
            except Exception:
                pass

    # P1 — absorb salient events into psyche + life_story.
    config = _settings.agents.personality
    try:
        events = await _memory.recent_events(key, limit=50)
    except Exception:
        events = []
    if config.absorption_enabled:
        if events and registry is not None:
            used_llm = True
        try:
            updated = await personality.absorb_events(
                profile,
                events,
                config,
                lang=lang,
                registry=registry,
            )
            if updated:
                profile = updated
                await _memory.upsert_profile(key, profile)
        except Exception as exc:
            logger.warning(f"sleep absorption failed: {exc}")

    # R4 — cognition layer: write tomorrow's daily plan (absorbs Phase 4).
    try:
        cognition = CognitionLayer(_settings)
        if cognition.enabled:
            if registry is not None:
                used_llm = True
            plan = await cognition.think(profile, events, registry, lang)
            if plan:
                profile = dict(profile or {})
                profile["daily_plan"] = plan
                profile["day_focus"] = plan.get("day_focus", "")
                profile["goals"] = plan.get("goals", [])
                await _memory.upsert_profile(key, profile)
                logger.info(
                    "cognition sim=%s source=%s focus=%r goals=%s",
                    job.sim_id,
                    plan.get("source"),
                    plan.get("day_focus", ""),
                    plan.get("goals", []),
                )
    except Exception as exc:
        logger.warning(f"sleep cognition failed: {exc}")

    return {"ok": True, "directives": [], "intents": [], "thought": "", "used_llm": used_llm}


async def _run_agency_job(job: ImpulseJob) -> dict[str, Any]:
    """Runner injected into the Agency scheduler (impulses + sleep)."""
    if _memory is None:
        return {"ok": False, "error": "memory not initialized"}

    from ..memory.base import MemKey
    from . import initiative as impulse_builder

    key = MemKey(job.player_id, job.save_id, int(job.sim_id))
    lang = job.lang or _current_lang
    registry = _effective_registry()

    forge = _context_forge or ContextForge(_memory, _settings)
    context = await forge.build(job)
    profile = context.get("profile") or {}

    if job.kind == "sleep":
        return await _sleep_consolidation(job, key, profile, lang, registry)

    memories = context.get("memories") or []
    world = _agency.world_context(job.player_id, job.save_id) if _agency else {}
    autonomy = str(profile.get("autonomy") or _autonomy_for_job(job))
    reasoning_effort = (
        _settings.agents.initiative.reasoning_effort
        or _settings.llm.reasoning_effort
    )
    try:
        outcome = await impulse_builder.build_impulse(
            job=job,
            profile=profile,
            world=world,
            memories=memories,
            registry=registry,
            lang=lang,
            autonomy=autonomy,
            reasoning_effort=reasoning_effort,
        )
    except Exception as exc:
        logger.warning(f"agency impulse failed: {exc}")
        outcome = {"directives": [], "intents": [], "thought": "", "used_llm": False}

    intents = await _gate_intents(job, outcome)
    thought = str(outcome.get("thought") or "").strip()
    logger.info(
        "impulse sim=%s kind=%s autonomy=%s intents=%s thought=%r used_llm=%s",
        job.sim_id,
        job.kind,
        autonomy,
        [intent.get("kind") for intent in intents],
        thought[:120],
        bool(outcome.get("used_llm")),
    )
    if thought:
        try:
            await _memory.add_event(
                key,
                {
                    "type": "thought",
                    "content": {"text": thought, "kind": job.kind},
                    "importance": 0.6,
                },
            )
        except Exception:
            pass

    return {
        "ok": True,
        "intents": intents,
        # Legacy alias so older runners/tests that read ``directives`` still work.
        "directives": [intent for intent in intents if intent.get("name")],
        "thought": thought,
        "used_llm": bool(outcome.get("used_llm")),
    }


async def start_agency() -> bool:
    """Start the per-Sim initiative scheduler (idempotent)."""
    if _agency is None:
        return False
    return await _agency.start()


async def stop_agency() -> None:
    """Stop the per-Sim initiative scheduler, if running."""
    if _agency is not None:
        await _agency.stop()


async def process_agency_once() -> int:
    """Drain one batch of impulses (used by tests and manual kicks)."""
    if _agency is None:
        return 0
    return await _agency.process_once()



def _effective_registry() -> ProviderRegistry | None:
    """Return the registry only when a provider is actually available.

    In native mode (no keys) this avoids futile provider calls and keeps the
    background budget from being spent on template fallbacks.
    """
    if _registry is None:
        return None
    try:
        if _registry.chain.available_providers():
            return _registry
    except Exception:
        return _registry
    return None


async def maybe_prune_memory(*, force: bool = False, now: float | None = None) -> int:
    """Physically prune forgotten memories at most once per day (M2).

    ``prune_forgotten`` + ``memory.retention_days`` used to be defined but never
    called in production, so forgotten events were never removed. This throttled
    hook is invoked from the zone pulse (and once at startup) so retention is
    actually enforced without touching the DB on every tick.
    """
    global _last_prune_at

    if _memory is None or _settings is None:
        return 0
    reference = time.time() if now is None else float(now)
    if not force and _last_prune_at and (reference - _last_prune_at) < _PRUNE_INTERVAL_SECONDS:
        return 0
    _last_prune_at = reference
    try:
        deleted = await _memory.prune_forgotten(_settings.memory.retention_days, now=reference)
    except Exception as exc:
        logger.warning(f"memory prune failed: {exc}")
        return 0
    if deleted:
        logger.info(
            "memory pruned=%d retention_days=%s", deleted, _settings.memory.retention_days
        )
    return deleted


def _enrich_sim_entry(census: dict[str, Any], sim_data: dict[str, Any]) -> dict[str, Any]:
    """Enrich a census Sim with relationship names and kinship labels.

    A census relationship only carries ``target_id``/``depth``; the census knows
    every Sim's name, so the target name is resolved here. The Sim's own kinship
    provides the relation label (mother/father/sibling/...). Without this the
    background prompt only saw numeric relationship ids and wrote a "lonely" Sim.
    """
    entry = dict(sim_data)
    by_id = {
        str(sim.get("sim_id")): str(sim.get("full_name") or "").strip()
        for sim in census.get("sims") or []
        if isinstance(sim, dict)
    }
    relation_by_id: dict[str, str] = {}
    for rel in sim_data.get("kinship") or []:
        if isinstance(rel, dict) and rel.get("target_id") is not None:
            relation_by_id[str(rel.get("target_id"))] = str(rel.get("relation") or "")

    relationships: list[dict[str, Any]] = []
    for rel in sim_data.get("relationships") or []:
        if not isinstance(rel, dict):
            continue
        enriched = dict(rel)
        target_id = str(rel.get("target_id"))
        if not enriched.get("target_name"):
            enriched["target_name"] = by_id.get(target_id, "")
        if not enriched.get("relation"):
            enriched["relation"] = relation_by_id.get(target_id, "")
        relationships.append(enriched)
    if relationships:
        entry["relationships"] = relationships
    return entry


def _census_entry_for_job(census: dict[str, Any], job: BackgroundJob) -> dict[str, Any] | None:
    """Find the census record that grounds a job, enriching household members."""
    if not isinstance(census, dict):
        return None

    if job.scope == "household":
        for household in census.get("households") or []:
            if str(household.get("household_id")) == str(job.household_id):
                entry = dict(household)
                entry.setdefault("lang", job.lang)
                names = _member_names(census, entry.get("members") or [])
                if names:
                    entry["member_names"] = names
                return entry
        return None

    for sim_data in census.get("sims") or []:
        if str(sim_data.get("sim_id")) == str(job.sim_id):
            entry = _enrich_sim_entry(census, sim_data)
            entry.setdefault("lang", job.lang)
            return entry
    return None


def _member_names(census: dict[str, Any], member_ids: list[Any]) -> list[str]:
    """Resolve household member ids to names using the census Sims."""
    by_id = {
        str(sim.get("sim_id")): str(sim.get("full_name") or "").strip()
        for sim in census.get("sims") or []
    }
    names: list[str] = []
    for member_id in member_ids:
        name = by_id.get(str(member_id), "")
        if name and name not in names:
            names.append(name)
    return names


def _census_entry_for_sim(player_id: str, save_id: str, sim_id: Any) -> dict[str, Any] | None:
    """Find a Sim in the last census and enrich its relationships with names.

    Used by the inline background path (no ``req.census``): without it the
    generator only saw the stored profile, whose relationships may carry bare
    ids and no kinship, so backgrounds read "lonely" for Sims with families.
    """
    census = _census_by_save.get(_census_key(player_id, save_id), {})
    if not isinstance(census, dict):
        return None
    for sim_data in census.get("sims") or []:
        if str(sim_data.get("sim_id")) == str(sim_id):
            return _enrich_sim_entry(census, sim_data)
    return None


def _census_entry_for_household(
    player_id: str, save_id: str, household_id: Any
) -> dict[str, Any] | None:
    """Find a household in the last census with its member names resolved."""
    census = _census_by_save.get(_census_key(player_id, save_id), {})
    if not isinstance(census, dict):
        return None
    for household in census.get("households") or []:
        if str(household.get("household_id")) == str(household_id):
            entry = dict(household)
            names = _member_names(census, entry.get("members") or [])
            if names:
                entry["member_names"] = names
            return entry
    return None


async def start_backgrounds() -> bool:
    """Build and start the background batch scheduler (idempotent)."""
    global _scheduler

    if _settings is None:
        return False
    if _scheduler is not None and _scheduler.running():
        return False

    config = _settings.god.backgrounds
    if not config.enabled:
        _scheduler = None
        return False

    _scheduler = BackgroundScheduler(
        _run_background_job,
        budgeter=BackgroundBudgeter(per_minute=config.per_minute, daily=config.daily_limit),
        batch_size=config.batch_size,
        interval_seconds=config.interval_seconds,
        idle_seconds=config.idle_seconds,
        max_queue=config.max_queue,
        max_attempts=config.max_attempts,
    )
    return _scheduler.start()


async def stop_backgrounds() -> None:
    """Stop the background scheduler, if running."""
    if _scheduler is not None:
        await _scheduler.stop()


async def process_backgrounds_once() -> int:
    """Drain one batch synchronously (used by tests and manual kicks)."""
    if _scheduler is None:
        return 0
    return await _scheduler.process_once()


def _enqueue_background_refresh(
    player_id: str,
    save_id: str,
    household_ids: list[int],
    *,
    source: str = "refresh",
) -> int:
    """Re-queue known households and census Sims (e.g. after a zeitgeist change)."""
    if _scheduler is None:
        return 0

    census = _census_by_save.get(_census_key(player_id, save_id), {})
    lang = census.get("lang") or _current_lang

    jobs = [
        BackgroundJob(
            priority=PRIORITY_HOUSEHOLD_ACTIVE,
            seq=0,
            player_id=player_id,
            save_id=save_id,
            scope="household",
            household_id=int(household_id),
            lang=lang,
            source=source,
        )
        for household_id in household_ids
    ]
    for sim_data in census.get("sims") or []:
        jobs.append(
            BackgroundJob(
                priority=PRIORITY_SIM_ACTIVE,
                seq=0,
                player_id=player_id,
                save_id=save_id,
                scope="sim",
                sim_id=int(sim_data.get("sim_id", 0)),
                household_id=sim_data.get("household_id"),
                lang=lang,
                source=source,
            )
        )
    return _scheduler.submit_many(jobs)


def _enqueue_census_backgrounds(req, sims: list[dict], households: list[dict]) -> int:
    """Queue active-zone households/Sims first, then related NPCs."""
    if _scheduler is None:
        return 0

    player_id = req.sim.player_id
    save_id = req.sim.save_id
    lang = req.lang

    def _int_or_none(value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    # The player's own household is generated before every other household/Sim
    # in the zone (a dedicated top-priority tier).
    active_household = _int_or_none(getattr(req.sim, "household_id", None))

    jobs = []
    for household in households:
        household_id = _int_or_none(household.get("household_id")) or 0
        is_player = active_household is not None and household_id == active_household
        jobs.append(
            BackgroundJob(
                priority=PRIORITY_HOUSEHOLD_PLAYER if is_player else PRIORITY_HOUSEHOLD_ACTIVE,
                seq=0,
                player_id=player_id,
                save_id=save_id,
                scope="household",
                household_id=household_id,
                lang=lang,
                source="census",
            )
        )

    known_ids = {str(sim.get("sim_id")) for sim in sims}
    for sim_data in sims:
        sim_household = _int_or_none(sim_data.get("household_id"))
        is_player = active_household is not None and sim_household == active_household
        jobs.append(
            BackgroundJob(
                priority=PRIORITY_SIM_PLAYER if is_player else PRIORITY_SIM_ACTIVE,
                seq=0,
                player_id=player_id,
                save_id=save_id,
                scope="sim",
                sim_id=int(sim_data.get("sim_id", 0)),
                household_id=sim_data.get("household_id"),
                lang=lang,
                source="census",
            )
        )

    related: set[int] = set()
    for sim_data in sims:
        for rel in sim_data.get("relationships") or []:
            if not isinstance(rel, dict):
                continue
            target = rel.get("target_id") or rel.get("target_sim_id") or rel.get("sim_id")
            try:
                target_id = int(target)
            except (TypeError, ValueError):
                continue
            if target_id and str(target_id) not in known_ids:
                related.add(target_id)
    for sim_id in sorted(related):
        jobs.append(
            BackgroundJob(
                priority=PRIORITY_RELATED,
                seq=0,
                player_id=player_id,
                save_id=save_id,
                scope="sim",
                sim_id=sim_id,
                lang=lang,
                source="related",
            )
        )

    return _scheduler.submit_many(jobs)


async def _cached_background(req: BackgroundRequest) -> dict[str, Any] | None:
    """Return an existing background for the request, or None (no generation)."""
    if _memory is None:
        return None
    try:
        if req.scope == "household":
            from ..memory.base import HouseholdKey

            household_id = req.household_id if req.household_id is not None else req.sim.household_id
            if household_id is None:
                return None
            stored = await _memory.get_household(
                HouseholdKey(req.sim.player_id, req.sim.save_id, int(household_id))
            ) or {}
            background = stored.get("background")
        else:
            from ..memory.base import MemKey

            profile = await _memory.get_profile(
                MemKey(req.sim.player_id, req.sim.save_id, req.sim.sim_id)
            ) or {}
            background = profile.get("background")
    except Exception:
        return None
    return background if isinstance(background, dict) and background else None


async def enqueue_background(req: BackgroundRequest) -> dict[str, Any]:
    """Player-requested background: cache hit inline, else enqueue at top priority.

    A player action never blocks the game thread: on a cache miss (or ``force``)
    the job is submitted at ``PRIORITY_PLAYER`` and the request returns
    immediately with ``queued=True``. When the background pipeline is disabled it
    falls back to the synchronous generator.
    """
    if _memory is None:
        return await generate_background(req)

    household_id = req.household_id if req.household_id is not None else req.sim.household_id

    if not req.force:
        cached = await _cached_background(req)
        if cached:
            return {
                "ok": True,
                "scope": req.scope,
                "sim_id": req.sim.sim_id,
                "household_id": household_id,
                "background": cached,
                "cached": True,
                "queued": False,
                "provider": cached.get("provider"),
            }

    if _scheduler is None:
        # Background pipeline disabled: generate inline (best effort).
        return await generate_background(req)

    job = BackgroundJob(
        priority=PRIORITY_PLAYER,
        seq=0,
        player_id=req.sim.player_id,
        save_id=req.sim.save_id,
        scope=req.scope,
        sim_id=req.sim.sim_id,
        household_id=household_id,
        lang=req.lang,
        player_hints=req.player_hints,
        source="player",
    )
    submitted = _scheduler.submit(job)
    logger.info("player background queued scope=%s sim=%s", req.scope, req.sim.sim_id)
    return {
        "ok": True,
        "scope": req.scope,
        "sim_id": req.sim.sim_id,
        "household_id": household_id,
        "background": {},
        "cached": False,
        "queued": True,
        "submitted": submitted,
    }


async def enqueue_consolidate(sim, lang: str) -> dict[str, Any]:
    """Player-requested memory consolidation: enqueue at top priority.

    Returns immediately with ``queued=True`` when the scheduler is available;
    otherwise falls back to the synchronous :func:`consolidate_now`.
    """
    if _memory is None or _settings is None:
        return {"ok": False, "consolidated": 0, "message_key": "error.memory_unavailable"}
    if not _settings.memory.consolidation_enabled:
        return {"ok": False, "consolidated": 0, "message_key": "notify.consolidate.disabled"}
    if _scheduler is None:
        return await consolidate_now(sim, lang)

    job = BackgroundJob(
        priority=PRIORITY_PLAYER,
        seq=0,
        player_id=sim.player_id,
        save_id=sim.save_id,
        scope="sim",
        sim_id=sim.sim_id,
        lang=lang,
        source="player",
        kind="consolidate",
    )
    _scheduler.submit(job)
    logger.info("player consolidate queued sim=%s", sim.sim_id)
    return {"ok": True, "consolidated": 0, "queued": True, "message_key": "notify.consolidate.queued"}


def _sim_key(sim) -> str:
    return f"{sim.player_id}:{sim.save_id}:{sim.sim_id}"


def _chat_budget_exhausted(sim) -> bool:
    """True when the Sim hit its daily chat request cap (LLM path only)."""
    if _chat_budget is None or _effective_registry() is None:
        return False
    return not _chat_budget.try_acquire(_sim_key(sim))


async def handle_chat(req: ChatRequest) -> ChatResponse:
    """Handle a chat request from the mod."""
    _note_lang(getattr(req, "lang", None))
    if not _nodes:
        logger.warning("Chat requested but agent not configured")
        return ChatResponse(
            reply="",
            provider=None,
            model=None,
            message_key="notify.no_llm_native",
            message_args={},
        )

    if _chat_budget_exhausted(req.sim):
        return ChatResponse(reply="", message_key="error.budget_exhausted", message_args={})

    try:
        # M1: fold an idle dialogue before recalling the fresh context.
        await maybe_consolidate(req.sim, req.lang or _current_lang)
        # Pipeline: recall -> build_prompt -> llm -> persist -> format
        recall = await _nodes.recall_node(req)
        prompt = await _nodes.build_prompt_node(recall, req)
        llm_result = await _nodes.llm_node(prompt)
        persist = await _nodes.persist_node(llm_result, req)
        response = await _nodes.format_response_node(persist)
        return response
    except Exception as e:
        logger.error(f"Error in handle_chat: {e}")
        return ChatResponse(
            reply="",
            provider=None,
            model=None,
            message_key="error.brain_foggy",
            message_args={},
        )


async def handle_hey(req: HeyRequest) -> ChatResponse:
    """Handle a spontaneous hey request from the mod."""
    _note_lang(getattr(req, "lang", None))
    if not _nodes:
        logger.warning("Hey requested but agent not configured")
        return ChatResponse(
            reply="",
            provider=None,
            model=None,
            message_key="notify.no_llm_native",
            message_args={},
        )

    if _chat_budget_exhausted(req.sim):
        return ChatResponse(reply="", message_key="error.budget_exhausted", message_args={})

    try:
        await maybe_consolidate(req.sim, req.lang or _current_lang)
        recall = await _nodes.recall_node(req)
        prompt = await _nodes.build_hey_prompt_node(recall, req)
        llm_result = await _nodes.llm_node(prompt)
        persist = await _nodes.persist_node(llm_result, req)
        response = await _nodes.format_hey_response_node(persist)
        return response
    except Exception as e:
        logger.error(f"Error in handle_hey: {e}")
        return ChatResponse(
            reply="",
            provider=None,
            model=None,
            message_key="error.brain_foggy",
            message_args={},
        )


async def handle_tool_result(req: ToolResultRequest) -> dict[str, Any]:
    """Handle a tool result from the mod."""
    if not _nodes:
        return {"ok": False, "error": "agent not configured"}
    return await _nodes.handle_tool_result(req)


def status() -> dict[str, Any]:
    """Return status snapshot for /v1/status."""
    result: dict[str, Any] = {
        "lang": _current_lang,
        "autonomy_default": _autonomy_default,
    }

    if _registry:
        try:
            result["providers"] = _registry.status()
        except Exception as e:
            logger.error(f"Error getting registry status: {e}")
            result["providers"] = {"error": str(e)}
    else:
        result["providers"] = {"error": "registry not initialized"}

    if _memory:
        try:
            # Can't await here, so we return a placeholder
            result["memory"] = {"status": "initialized", "type": type(_memory).__name__}
        except Exception as e:
            logger.error(f"Error getting memory status: {e}")
            result["memory"] = {"error": str(e)}
    else:
        result["memory"] = {"error": "memory not initialized"}

    if _orchestrator is not None:
        result["god"] = _orchestrator.status()
    else:
        result["god"] = {"enabled": False}

    if _rails:
        result["rails"] = _rails.snapshot()

    result["backgrounds"] = (
        _scheduler.snapshot() if _scheduler is not None else {"enabled": False, "running": False}
    )
    result["budget"] = _chat_budget.snapshot() if _chat_budget is not None else {}

    agency = _agency.snapshot() if _agency is not None else {"enabled": False}
    if _coordinator is not None:
        agency["coordinator"] = _coordinator.snapshot()
    result["agency"] = agency
    if _settings is not None:
        result["personality"] = _settings.agents.personality.model_dump()

    return result


async def reset(scope: str, sim) -> dict[str, Any]:
    """Clear memory by scope."""
    if not _memory:
        return {"ok": False, "error": "memory not initialized"}

    from ..memory.base import MemKey
    mem_key = MemKey(player_id=sim.player_id, save_id=sim.save_id, sim_id=sim.sim_id) if sim else None

    try:
        deleted = await _memory.reset(scope, mem_key)
        # Also clear in-process state
        if _nodes and mem_key:
            sim_key = f"{mem_key.player_id}:{mem_key.save_id}:{mem_key.sim_id}"
            if sim_key in _nodes._states:
                del _nodes._states[sim_key]
        if _rails:
            _rails.reset(str(mem_key) if mem_key else None)
        if scope == "all":
            _census_by_save.clear()
            if _scheduler is not None:
                _scheduler.clear()
            if _agency is not None:
                _agency.clear()
            if _chat_budget is not None:
                _chat_budget.reset()
        elif scope == "save" and mem_key:
            _census_by_save.pop(_census_key(mem_key.player_id, mem_key.save_id), None)
            if _agency is not None:
                _agency.clear(mem_key.player_id, mem_key.save_id)
        if _chat_budget is not None and scope in ("sim", "save") and mem_key:
            _chat_budget.reset(str(mem_key))
        return {"ok": True, "deleted": deleted}
    except Exception as e:
        logger.error(f"Error in reset: {e}")
        return {"ok": False, "error": str(e)}


async def set_autonomy(sim, level: str) -> dict[str, Any]:
    """Update autonomy level for a Sim."""
    if level not in ("off", "observe", "suggest", "semi", "full"):
        return {"ok": False, "error": f"invalid autonomy level: {level}"}

    global _autonomy_default
    _autonomy_default = level

    if _nodes:
        sim_key = f"{sim.player_id}:{sim.save_id}:{sim.sim_id}"
        state = _nodes._get_state(sim_key)
        state.autonomy_level = level

    if _settings:
        _settings.agents.autonomy_default = level

    # Persist the per-Sim level so the initiative loop honors it (§14.2).
    if _memory is not None:
        from ..memory.base import MemKey

        key = MemKey(sim.player_id, sim.save_id, sim.sim_id)
        try:
            profile = await _memory.get_profile(key) or {}
            profile["autonomy"] = level
            await _memory.upsert_profile(key, profile)
        except Exception:
            pass
    if _agency is not None:
        world = _agency.world_context(sim.player_id, sim.save_id)
        state = (world.get("sims") or {}).get(str(sim.sim_id))
        if isinstance(state, dict):
            state["autonomy"] = level

    return {"ok": True, "autonomy": level}


def set_lang(lang: str) -> dict[str, Any]:
    """Update the active language."""
    from ..schemas import SUPPORTED_LANGS, normalize_lang

    normalized = normalize_lang(lang)
    if normalized not in SUPPORTED_LANGS:
        return {"ok": False, "error": f"unsupported language: {lang}"}

    global _current_lang
    _current_lang = normalized

    if _nodes:
        _nodes.default_lang = normalized

    if _settings:
        _settings.lang = normalized

    return {"ok": True, "lang": normalized}


def _maybe_enqueue_reaction(
    sim, event_type: str, content: dict[str, Any], importance: float,
    lang: str | None = None,
) -> None:
    """Schedule a prioritized Sim reaction to a salient event (A1/A3)."""
    if _agency is None or _settings is None:
        return
    if event_type in ("tool_result", "directive_denied", "thought", "player_activity", "player_interaction"):
        return
    threshold = _settings.agents.initiative.event_react_threshold
    if importance < threshold:
        return
    try:
        _agency.enqueue_reaction(
            getattr(sim, "player_id", "local"),
            getattr(sim, "save_id", "unknown"),
            int(getattr(sim, "sim_id", 0)),
            {"type": event_type, "content": content, "importance": importance, "source": "agent"},
            lang=lang or _current_lang,
        )
    except Exception as exc:
        logger.debug(f"reaction enqueue failed: {exc}")


async def _absorb_extreme_event(
    mem_key, event_type: str, content: dict[str, Any], importance: float
) -> None:
    """Absorb one extreme event into the Sim's psyche right away (P1)."""
    if _memory is None or _settings is None:
        return
    config = _settings.agents.personality
    if not config.absorption_enabled:
        return
    event = {"type": event_type, "content": content, "importance": importance}
    if not personality.is_extreme(event, config.salience_threshold):
        return
    try:
        profile = await _memory.get_profile(mem_key) or {}
        updated = personality.absorb(profile, event, config, lang=_current_lang)
        if updated:
            await _memory.upsert_profile(mem_key, updated)
            logger.info("immediate absorption sim=%s type=%s", mem_key.sim_id, event_type)
    except Exception as exc:
        logger.debug(f"immediate absorption failed: {exc}")


async def ingest_events(events) -> dict[str, Any]:
    """Persist game events forwarded by the mod.

    Events of type ``player_activity`` / ``player_interaction`` also arm the
    per-Sim player-priority lock so AI directives don't fight the player.
    """
    if not _memory:
        return {"ok": False, "error": "memory not initialized"}

    from ..memory.base import MemKey

    count = 0
    for event in events or []:
        sim = getattr(event, "sim", None)
        if sim is None:
            continue

        mem_key = MemKey(player_id=sim.player_id, save_id=sim.save_id, sim_id=sim.sim_id)
        event_type = getattr(event, "type", "event") or "event"
        content = dict(getattr(event, "content", {}) or {})
        importance = float(getattr(event, "importance", 1.0))
        event_lang = getattr(event, "lang", None)
        _note_lang(event_lang)

        # v0.4 P4: a player social interaction seeds a conversation session.
        if event_type == "player_interaction" and _agency is not None:
            target = content.get("target_sim_id")
            if target is not None:
                _agency.note_interaction_seed(
                    sim.player_id,
                    sim.save_id,
                    sim.sim_id,
                    target,
                    interaction=str(content.get("interaction") or ""),
                    interaction_text=str(content.get("interaction_text") or ""),
                )

        if _rails is not None and event_type in ("player_activity", "player_interaction"):
            _rails.record_player_activity(str(mem_key))

        try:
            await _memory.add_event(
                mem_key,
                {
                    "type": event_type,
                    "content": content,
                    "importance": importance,
                },
            )
            count += 1
        except Exception as e:
            logger.warning(f"Failed to persist event {event_type}: {e}")

        # P1: an extreme event (death, betrayal) is absorbed immediately instead
        # of waiting for the next sleep (PLANO §14.4).
        await _absorb_extreme_event(mem_key, event_type, content, importance)

        # A1/A3: schedule a prioritized reaction to salient events.
        _maybe_enqueue_reaction(sim, event_type, content, importance, lang=event_lang)

    logger.info(
        "events ingested=%d types=%s",
        count,
        [
            getattr(event, "type", "event")
            for event in (events or [])
            if getattr(event, "sim", None) is not None
        ],
    )
    return {"ok": True, "ingested": count}


def record_player_activity(sim) -> dict[str, Any]:
    """Arm the player-priority lock for a Sim (called by the mod)."""
    if _rails is None:
        return {"ok": False, "error": "rails not initialized"}
    sim_key = f"{sim.player_id}:{sim.save_id}:{sim.sim_id}"
    _rails.record_player_activity(sim_key)
    return {"ok": True}


async def get_zeitgeist(save_id: str, player_id: str = "local") -> dict[str, Any]:
    """Return the neighborhood zeitgeist (``configured=False`` when unset)."""
    from ..god.zeitgeist import normalize_zeitgeist

    default = normalize_zeitgeist({})
    if not _memory:
        return {"ok": False, "zeitgeist": default}

    try:
        data = await _memory.get_neighborhood(player_id, save_id)
    except Exception as e:
        logger.warning(f"get_neighborhood failed: {e}")
        return {"ok": False, "zeitgeist": default}

    if not data or not data.get("zeitgeist"):
        return {"ok": True, "zeitgeist": default}

    zeitgeist = normalize_zeitgeist(data.get("zeitgeist"))
    zeitgeist["configured"] = True
    return {"ok": True, "zeitgeist": zeitgeist}


async def set_zeitgeist(
    sim,
    mood_tags: list[str],
    free_text: str,
    mood_influence: float,
    lang: str,
) -> dict[str, Any]:
    """Persist the zeitgeist, rewriting the text with the agent when possible."""
    from ..god.zeitgeist import normalize_zeitgeist
    from ..god.zeitgeist import suggest_zeitgeist as _suggest

    if not _memory:
        return {"ok": False, "zeitgeist": normalize_zeitgeist({})}

    player_id = getattr(sim, "player_id", "local")
    save_id = getattr(sim, "save_id", "unknown")
    census = _census_by_save.get(_census_key(player_id, save_id), {})

    suggestion = await _suggest(census, mood_tags, free_text, lang, _effective_registry())

    zeitgeist = normalize_zeitgeist(
        {
            "mood_tags": suggestion.get("mood_tags", mood_tags),
            "free_text": free_text,
            "rewritten_text": suggestion.get("suggested_text", ""),
            "mood_influence": mood_influence,
            "configured": True,
            "updated_at": time.time(),
        }
    )

    try:
        data = await _memory.get_neighborhood(player_id, save_id) or {}
    except Exception:
        data = {}
    data["zeitgeist"] = zeitgeist

    try:
        await _memory.upsert_neighborhood(player_id, save_id, data)
    except Exception as e:
        logger.warning(f"upsert_neighborhood failed: {e}")
        return {"ok": False, "zeitgeist": zeitgeist}

    await _mark_household_backgrounds_stale(player_id, save_id)
    return {"ok": True, "zeitgeist": zeitgeist}


async def suggest_zeitgeist(
    sim,
    mood_tags: list[str],
    free_text: str,
    lang: str,
) -> dict[str, Any]:
    """Propose a zeitgeist rewrite grounded in the last census."""
    from ..god.zeitgeist import suggest_zeitgeist as _suggest

    player_id = getattr(sim, "player_id", "local")
    save_id = getattr(sim, "save_id", "unknown")
    census = _census_by_save.get(_census_key(player_id, save_id), {})

    result = await _suggest(census, mood_tags, free_text, lang, _effective_registry())
    return {"ok": True, **result}


async def _mark_household_backgrounds_stale(player_id: str, save_id: str) -> None:
    """Flag cached household backgrounds as stale after a zeitgeist change."""
    from ..memory.base import HouseholdKey

    if not _memory:
        return
    try:
        households = await _memory.list_households(player_id, save_id)
    except Exception:
        return

    household_ids: list[int] = []
    for entry in households:
        household_id = int(entry.get("household_id", 0))
        household_ids.append(household_id)
        data = entry.get("data") or {}
        background = data.get("background")
        if not isinstance(background, dict):
            continue
        background["stale"] = True
        data["background"] = background
        key = HouseholdKey(player_id, save_id, household_id)
        try:
            await _memory.upsert_household(key, data)
        except Exception:
            pass

    # Lazily regenerate the stale backgrounds in the batch pipeline.
    _enqueue_background_refresh(player_id, save_id, household_ids, source="zeitgeist")


async def generate_background(req) -> dict[str, Any]:
    """Generate (or return a cached) background for a Sim or household."""
    from ..god import backgrounder as bg
    from ..god.zeitgeist import normalize_zeitgeist
    from ..memory.base import HouseholdKey, MemKey

    player_id = req.sim.player_id
    save_id = req.sim.save_id

    if not _memory:
        return {
            "ok": False,
            "scope": req.scope,
            "sim_id": req.sim.sim_id,
            "household_id": req.household_id or req.sim.household_id,
            "message_key": "god.background.unavailable",
        }

    try:
        neighborhood = await _memory.get_neighborhood(player_id, save_id) or {}
    except Exception:
        neighborhood = {}

    zeitgeist = normalize_zeitgeist(neighborhood.get("zeitgeist") or {})
    mood_influence = zeitgeist.get("mood_influence", 0.5)
    mood_tags = zeitgeist.get("mood_tags", [])

    if req.scope == "household":
        household_id = req.household_id if req.household_id is not None else req.sim.household_id
        if household_id is None:
            return {
                "ok": False,
                "scope": "household",
                "sim_id": req.sim.sim_id,
                "message_key": "god.background.no_household",
            }

        key = HouseholdKey(player_id, save_id, int(household_id))
        try:
            stored = await _memory.get_household(key) or {}
        except Exception:
            stored = {}

        cached = stored.get("background")
        if cached and not req.force and not bg.is_stale(cached, mood_influence, mood_tags):
            return {
                "ok": True,
                "scope": "household",
                "sim_id": req.sim.sim_id,
                "household_id": int(household_id),
                "background": cached,
                "cached": True,
                "provider": cached.get("provider"),
            }

        household_data = req.census if isinstance(req.census, dict) and req.census else (
            _census_entry_for_household(player_id, save_id, household_id) or stored
        )
        result = await bg.generate_household_background(
            household_data, zeitgeist, req.player_hints, req.lang, _effective_registry(), mood_influence
        )
        background = result["background"]

        merged = dict(stored)
        merged.update({"household_id": int(household_id), "background": background})
        try:
            await _memory.upsert_household(key, merged)
        except Exception as e:
            logger.warning(f"upsert_household failed: {e}")

        return {
            "ok": True,
            "scope": "household",
            "sim_id": req.sim.sim_id,
            "household_id": int(household_id),
            "background": background,
            "cached": False,
            "provider": result.get("provider"),
        }

    key = MemKey(player_id, save_id, req.sim.sim_id)
    try:
        profile = await _memory.get_profile(key) or {}
    except Exception:
        profile = {}

    cached = profile.get("background")
    if cached and not req.force and not bg.is_stale(cached, mood_influence, mood_tags):
        return {
            "ok": True,
            "scope": "sim",
            "sim_id": req.sim.sim_id,
            "household_id": profile.get("household_id"),
            "background": cached,
            "cached": True,
            "provider": cached.get("provider"),
        }

    sim_data = req.census if isinstance(req.census, dict) and req.census else (
        _census_entry_for_sim(player_id, save_id, req.sim.sim_id) or profile
    )
    result = await bg.generate_sim_background(
        sim_data, zeitgeist, req.player_hints, req.lang, _effective_registry(), mood_influence
    )
    background = result["background"]

    try:
        await _memory.set_sim_background(key, background)
    except Exception as e:
        logger.warning(f"set_sim_background failed: {e}")

    return {
        "ok": True,
        "scope": "sim",
        "sim_id": req.sim.sim_id,
        "household_id": profile.get("household_id"),
        "background": background,
        "cached": False,
        "provider": result.get("provider"),
    }


def _merge_census(
    existing: dict[str, Any] | None,
    scope: str,
    lang: str,
    sims: list[dict],
    households: list[dict],
) -> dict[str, Any]:
    """Merge a census snapshot into the cached one, never shrinking it.

    A full-save ("neighborhood") scan must survive the smaller active-zone
    censuses the mod re-sends on every zone load and household change, so
    records are merged by id and the widest scope is kept. Household member
    lists are unioned (an active-zone census only sees the instanced members)
    and newer native data wins for each Sim.
    """
    base = existing if isinstance(existing, dict) else {}

    merged_scope = "full_save" if "full_save" in (base.get("scope"), scope) else scope

    by_sim: dict[str, dict] = {}
    for entry in (base.get("sims") or []) + (sims or []):
        if isinstance(entry, dict) and entry.get("sim_id") is not None:
            by_sim[str(entry.get("sim_id"))] = entry

    by_household: dict[str, dict] = {}
    for entry in (base.get("households") or []) + (households or []):
        if not isinstance(entry, dict) or entry.get("household_id") is None:
            continue
        key = str(entry.get("household_id"))
        prev = by_household.get(key) or {}
        merged = dict(prev)
        merged.update(entry)
        merged["members"] = list(
            dict.fromkeys(
                list(prev.get("members") or [])
                + list(entry.get("members") or [])
            )
        )
        by_household[key] = merged

    return {
        "scope": merged_scope,
        "lang": lang or base.get("lang") or _current_lang,
        "sims": list(by_sim.values()),
        "households": list(by_household.values()),
    }


def _diff_census(
    previous: dict[str, Any] | None,
    scope: str,
    sims: list[dict],
    households: list[dict],
) -> dict[str, Any]:
    """Previous-vs-current census diff (Phase 2b, no CAS/spawn TestEvent).

    Additions are always reliable (an id we had never seen). Removals are only
    reported when the incoming scope matches the previous snapshot's scope, so a
    small active-zone re-send never pretends the missing full-save Sims left.
    """
    prev = previous if isinstance(previous, dict) else {}

    def _ids(entries: Any, key: str) -> set[str]:
        out: set[str] = set()
        for entry in entries or []:
            if not isinstance(entry, dict) or entry.get(key) is None:
                continue
            out.add(str(entry.get(key)))
        return out

    def _ints(values: set[str]) -> list[int]:
        return sorted(int(v) for v in values if str(v).lstrip("-").isdigit())

    prev_sims = _ids(prev.get("sims"), "sim_id")
    cur_sims = _ids(sims, "sim_id")
    prev_households = _ids(prev.get("households"), "household_id")
    cur_households = _ids(households, "household_id")

    same_scope = bool(prev) and prev.get("scope") == scope

    return {
        "scope": scope,
        "sims_added": _ints(cur_sims - prev_sims),
        "sims_removed": _ints(prev_sims - cur_sims) if same_scope else [],
        "households_added": _ints(cur_households - prev_households),
        "households_removed": _ints(prev_households - cur_households) if same_scope else [],
    }


async def ingest_census(req) -> dict[str, Any]:
    """Store a census snapshot; it grounds zeitgeist suggestions and backgrounds."""
    from ..memory.base import HouseholdKey, MemKey

    player_id = req.sim.player_id
    save_id = req.sim.save_id
    sims = [s.model_dump() for s in req.sims]
    households = [h.model_dump() for h in req.households]

    census_key = _census_key(player_id, save_id)
    previous = _census_by_save.get(census_key)
    diff = _diff_census(previous, req.scope, sims, households)
    _census_by_save[census_key] = _merge_census(
        previous, req.scope, req.lang, sims, households
    )

    if not _memory:
        return {"ok": False, "sims": 0, "households": 0}

    for household in households:
        key = HouseholdKey(player_id, save_id, int(household.get("household_id", 0)))
        try:
            existing = await _memory.get_household(key) or {}
        except Exception:
            existing = {}
        existing.update(
            {
                "household_id": key.household_id,
                "name": household.get("name", ""),
                "members": household.get("members", []),
                "funds": household.get("funds", 0),
            }
        )
        try:
            await _memory.upsert_household(key, existing)
        except Exception as e:
            logger.warning(f"census household upsert failed: {e}")

    for sim_data in sims:
        key = MemKey(player_id, save_id, int(sim_data.get("sim_id", 0)))
        try:
            profile = await _memory.get_profile(key) or {}
        except Exception:
            profile = {}
        profile["name"] = sim_data.get("full_name") or profile.get("name", "")
        profile["household_id"] = sim_data.get("household_id")
        profile["native"] = {
            "traits": sim_data.get("traits", []),
            "age": sim_data.get("age", ""),
            "gender": sim_data.get("gender", ""),
            "aspiration": sim_data.get("aspiration", ""),
            "career": sim_data.get("career", ""),
            "skills": sim_data.get("skills", {}),
            "relationships": sim_data.get("relationships", []),
            "kinship": sim_data.get("kinship", []),
        }
        try:
            await _memory.upsert_profile(key, profile)
        except Exception as e:
            logger.warning(f"census sim upsert failed: {e}")

        # Phase 2b: persist the Sim's relationship edges so they are actually
        # considered (previously only used to schedule related backgrounds).
        for rel in sim_data.get("relationships") or []:
            if not isinstance(rel, dict):
                continue
            target = rel.get("target_id") or rel.get("target_sim_id")
            try:
                target_id = int(target)
            except (TypeError, ValueError):
                continue
            if not target_id:
                continue
            sentiment = rel.get("friendship")
            if sentiment is None:
                sentiment = rel.get("depth", 0.0)
            try:
                sentiment = float(sentiment or 0.0)
            except (TypeError, ValueError):
                sentiment = 0.0
            metadata = {
                "target_name": rel.get("target_name", ""),
                "track": rel.get("track", ""),
                "friendship": rel.get("friendship"),
                "romance": rel.get("romance"),
                "known_traits": rel.get("known_traits", []),
            }
            try:
                await _memory.upsert_relationship(key, target_id, sentiment, metadata)
            except Exception as e:
                logger.debug(f"census relationship upsert failed: {e}")

    result: dict[str, Any] = {"ok": True, "sims": len(sims), "households": len(households)}
    if any(
        diff[key]
        for key in ("sims_added", "sims_removed", "households_added", "households_removed")
    ):
        result["diff"] = diff
        logger.info(
            "census diff scope=%s sims+%s -%s households+%s -%s",
            req.scope,
            diff["sims_added"],
            diff["sims_removed"],
            diff["households_added"],
            diff["households_removed"],
        )
    if _scheduler is not None:
        result["queued"] = _enqueue_census_backgrounds(req, sims, households)
    if _agency is not None:
        # v0.3 R2: seed the seat pool from the census (households + members).
        try:
            seat_sims = []
            member_ids: dict[int, set[int]] = {}
            for household in households:
                hid = int(household.get("household_id", 0))
                member_ids[hid] = {int(m) for m in (household.get("members") or [])}
            for sim_data in sims:
                hid = sim_data.get("household_id")
                seat_sims.append(
                    {
                        "sim_id": int(sim_data.get("sim_id", 0)),
                        "household_id": int(hid) if hid is not None else None,
                        "is_player": bool(sim_data.get("is_player")),
                    }
                )
            result["seats"] = _agency.seats.sync(
                player_id, save_id, seat_sims, active_sim_id=req.sim.sim_id
            )
            logger.info("census seats=%s", result["seats"])
        except Exception as exc:
            logger.warning(f"seat sync from census failed: {exc}")
    return result


async def generate_profile(req) -> dict[str, Any]:
    """Generate (or return a cached) structured profile for a Sim (Phase 3)."""
    from ..memory.base import MemKey

    if _memory is None:
        return {"ok": False, "sim_id": req.sim.sim_id, "message_key": "profile.unavailable"}

    key = MemKey(req.sim.player_id, req.sim.save_id, req.sim.sim_id)
    try:
        stored = await _memory.get_profile(key) or {}
    except Exception:
        stored = {}

    cached = stored.get("generated_profile")
    if cached and not req.force:
        return {
            "ok": True,
            "sim_id": req.sim.sim_id,
            "profile": cached,
            "cached": True,
            "provider": cached.get("source"),
        }

    native = req.native if isinstance(req.native, dict) and req.native else (stored.get("native") or {})
    seed = req.seed or stored.get("seed") or ""

    result = await profiler.generate_profile(
        seed,
        req.lang or _current_lang,
        _effective_registry(),
        hints=req.hints,
        native=native,
    )
    profile = result["profile"]

    stored["generated_profile"] = profile
    if not stored.get("name"):
        stored["name"] = profile.get("name", "")
    if seed:
        stored["seed"] = seed
    if native:
        stored.setdefault("native", native)
    try:
        await _memory.upsert_profile(key, stored)
    except Exception as e:
        logger.warning(f"profile upsert failed: {e}")

    return {
        "ok": True,
        "sim_id": req.sim.sim_id,
        "profile": profile,
        "cached": False,
        "provider": result.get("provider"),
    }


def _effective_evolution_config():
    """Return (min_events, cooldown_seconds, trait_swap_mode) for the loop."""
    assert _settings is not None
    config = _settings.agents.evolution
    min_events = config.min_events
    cooldown = config.cooldown_seconds
    speed = _settings.agents.evolution_speed
    if speed == "fast":
        min_events = max(2, min_events // 2)
        cooldown = cooldown / 2
    elif speed == "slow":
        min_events = min_events * 2
        cooldown = cooldown * 2
    return min_events, cooldown, config.trait_swap


async def evolve(req: EvolveRequest) -> dict[str, Any]:
    """Run the reflection/evolution loop for one Sim or a whole save (Phase 4)."""
    from ..memory.base import MemKey

    if _memory is None or _settings is None:
        return {"ok": False, "scope": req.scope, "reflected": 0, "skipped": 0, "results": []}

    config = _settings.agents.evolution
    if not config.enabled:
        return {
            "ok": True,
            "scope": req.scope,
            "reflected": 0,
            "skipped": 0,
            "results": [],
            "message_key": "evolve.disabled",
        }

    if req.sim is None:
        return {"ok": False, "scope": req.scope, "reflected": 0, "skipped": 0, "results": []}

    player_id = req.sim.player_id
    save_id = req.sim.save_id
    lang = req.lang or _current_lang

    if req.scope == "save":
        try:
            entries = await _memory.list_profiles(player_id, save_id)
        except Exception:
            entries = []
        targets = [(entry.get("sim_id", 0), entry.get("profile", {})) for entry in entries]
    else:
        try:
            profile = await _memory.get_profile(MemKey(player_id, save_id, req.sim.sim_id)) or {}
        except Exception:
            profile = {}
        targets = [(req.sim.sim_id, profile)]

    min_events, cooldown, swap_mode = _effective_evolution_config()
    reflected = 0
    skipped = 0
    results: list[dict[str, Any]] = []

    for sim_id, profile in targets:
        key = MemKey(player_id, save_id, int(sim_id))
        try:
            events = await _memory.recent_events(key, limit=30)
            reflections = await _memory.recent_reflections(key, limit=1)
        except Exception:
            skipped += 1
            continue

        last_ts = float(reflections[-1].get("created_at", 0.0)) if reflections else 0.0
        if not req.force and not evolution.should_reflect(
            profile,
            events,
            min_events=min_events,
            last_reflection_ts=last_ts,
            cooldown_seconds=cooldown,
        ):
            skipped += 1
            continue

        outcome = await evolution.reflect(profile, events, lang, _effective_registry())
        reflection = outcome["reflection"]
        try:
            await _memory.add_reflection(key, reflection)
        except Exception as e:
            logger.warning(f"reflection persist failed: {e}")

        if reflection.get("personality"):
            profile["personality"] = reflection["personality"]
        profile["last_reflection_at"] = reflection.get("generated_at")

        proposal = {"add": None, "remove": None, "reason": ""}
        if swap_mode != "off":
            swap = outcome.get("trait_swap") or {}
            known = profile.get("native", {}).get("traits") if isinstance(profile.get("native"), dict) else None
            known = known or profile.get("traits") or None
            proposal = evolution.propose_trait_swap(
                profile,
                {
                    "trait_add": swap.get("add"),
                    "trait_remove": swap.get("remove"),
                    "trait_reason": swap.get("reason"),
                },
                known_traits=list(known) if known else None,
            )
            if proposal.get("add") or proposal.get("remove"):
                profile["proposed_trait_swap"] = proposal

        try:
            await _memory.upsert_profile(key, profile)
        except Exception as e:
            logger.warning(f"profile evolve upsert failed: {e}")

        reflected += 1
        results.append(
            {
                "sim_id": int(sim_id),
                "source": reflection.get("source"),
                "provider": outcome.get("provider"),
                "trait_swap": (proposal if (proposal.get("add") or proposal.get("remove")) else None),
            }
        )

    return {
        "ok": True,
        "scope": req.scope,
        "reflected": reflected,
        "skipped": skipped,
        "results": results,
    }


def god_controls() -> dict[str, Any]:
    """Return the ControlSpec registry plus the current God/agent values."""
    from ..god.controls import controls_payload, merge_with_defaults, values_from_settings

    if _settings:
        values = values_from_settings(_settings)
    else:
        values = merge_with_defaults(None)
    return {"ok": True, "controls": controls_payload(), "values": values}


def god_status() -> dict[str, Any]:
    """Return the God orchestrator snapshot (Phase 5c)."""
    if _orchestrator is None:
        return {"enabled": False}
    return _orchestrator.status()


def update_god() -> dict[str, Any]:
    """Re-apply the current ``settings.god`` to the orchestrator (called after config)."""
    global _orchestrator
    if _settings is None:
        return {"ok": False}
    if _orchestrator is None:
        _orchestrator = GodOrchestrator(_settings.god, lang=_current_lang)
    else:
        _orchestrator.configure(_settings.god, lang=_current_lang)
    return {"ok": True, "god": _orchestrator.status()}


def update_agents() -> dict[str, Any]:
    """Re-apply ``settings.agents`` to the live agency scheduler (v0.3 dials)."""
    if _settings is None:
        return {"ok": False}
    global _context_forge
    _context_forge = ContextForge(_memory, _settings)
    if _agency is None:
        return {"ok": False}
    _agency.configure(_settings)
    return {"ok": True, "agency": _agency.snapshot()}


def _directive_payload(directive) -> dict[str, Any]:
    """Serialize a ``Directive`` for the wire (``GodDirective``)."""
    return {
        "id": directive.id,
        "type": directive.type,
        "target_sim": int(directive.target_sim) if str(directive.target_sim).lstrip("-").isdigit() else None,
        "priority": directive.priority,
        "payload": dict(directive.payload or {}),
        "narration": directive.narration,
        "tool_call": directive.tool_call,
        "source": "god",
    }


async def _broadcast_god_directive(player_id: str, save_id: str, directive) -> None:
    """Record a God directive in the target Sim's memory so the agent reacts."""
    if _memory is None or directive.target_sim is None:
        return
    sim_id = str(directive.target_sim)
    if not sim_id.lstrip("-").isdigit():
        return

    from ..memory.base import MemKey

    event = {
        "type": "god",
        "content": {
            "directive_id": directive.id,
            "event_type": directive.type,
            "narration": directive.narration,
            "payload": dict(directive.payload or {}),
            "source": "god",
        },
        "importance": 0.9,
    }
    try:
        await _memory.add_event(MemKey(player_id, save_id, int(sim_id)), event)
    except Exception as exc:
        logger.warning(f"God directive broadcast failed: {exc}")

    # Broadcast world events always reach affected/witness Sims' feeds so the
    # Sim agents react to them (§14.5); the God never reacts to its own events.
    if _agency is not None:
        try:
            _agency.enqueue_reaction(
                player_id,
                save_id,
                int(sim_id),
                {
                    "type": directive.type,
                    "content": dict(event["content"]),
                    "importance": 0.9,
                    "source": "god",
                },
                lang=_current_lang,
            )
        except Exception:
            pass


async def god_tick(req) -> dict[str, Any]:
    """Run one God-orchestration tick against the last census (Phase 5c)."""
    if _orchestrator is None or _settings is None:
        return {"ok": False, "enabled": False, "preset": "", "directives": []}

    player_id = req.sim.player_id
    save_id = req.sim.save_id
    census = _census_by_save.get(_census_key(player_id, save_id), {})
    world_state = WorldState.from_census(
        census,
        time_of_day=req.time_of_day,
        lot_type=req.lot_type,
    )

    _orchestrator.set_registry(_effective_registry())

    try:
        directives = await _orchestrator.maybe_intervene(world_state, lang=req.lang or _current_lang)
    except Exception as exc:
        logger.error(f"God tick failed: {exc}")
        return {"ok": False, "enabled": _orchestrator.enabled, "preset": _orchestrator.preset, "directives": []}

    for directive in directives:
        await _broadcast_god_directive(player_id, save_id, directive)

    return {
        "ok": True,
        "enabled": _orchestrator.enabled,
        "preset": _orchestrator.preset,
        "directives": [_directive_payload(directive) for directive in directives],
    }


async def ingest_autonomy_tick(req) -> dict[str, Any]:
    """Ingest a zone pulse and schedule per-Sim impulses (v0.2 A1/A2)."""
    if _agency is None:
        return {"ok": False, "scheduled": 0, "sleeping": [], "seats": {}}
    # The pulse carries the running game language; adopt it sidecar-wide.
    _note_lang(getattr(req, "lang", None))
    # M2: enforce memory retention at most once per day, off the critical path.
    await maybe_prune_memory()
    try:
        result = await _agency.ingest_tick(req)
        if isinstance(result, dict):
            await _store_social(req, result)
            return result
        return {"ok": False, "scheduled": 0, "sleeping": [], "seats": {}}
    except Exception as exc:
        logger.error(f"autonomy tick failed: {exc}")
        return {"ok": False, "scheduled": 0, "sleeping": [], "seats": {}}


async def _store_social(req, result: dict[str, Any]) -> None:
    """Gate, store and remember the sim<->sim dialogues from a zone pulse (R5).

    The dialogues already carry one ``speak`` intent per line; each is passed
    through the same rails as other intents before landing on the bus, and the
    exchange is written to both participants' memory so it outlives the seat.
    v0.4 P4: closed conversation sessions also yield a narrator summary event
    and a ``notify`` intent the mod surfaces (inside the hearing radius).
    """
    sim_ref = getattr(req, "sim", None)
    player_id = getattr(sim_ref, "player_id", "local")
    save_id = getattr(sim_ref, "save_id", "unknown")
    lang = getattr(req, "lang", None) or _current_lang
    world = _agency.world_context(player_id, save_id) if _agency is not None else {}

    dialogues = result.get("social") or []
    stored = 0
    if dialogues and _agency is not None:
        passed: list[dict[str, Any]] = []
        for intent in result.get("social_intents") or []:
            sim_id = intent.get("sim_id")
            name = str(intent.get("name") or "")
            sim_key = f"{player_id}:{save_id}:{sim_id}"
            if _rails is not None and name:
                decision = _rails.check(sim_key, name)
                if not decision.allowed:
                    logger.debug("social intent denied (%s): %s", name, decision.reason)
                    continue
                _rails.note_executed(sim_key, name)
            passed.append(intent)
        _annotate_speech(
            passed,
            job_kind="social",
            world=world,
            player_id=player_id,
            save_id=save_id,
            lang=lang,
        )
        # v0.4 P2: drop a dialogue line detected in the wrong language.
        passed = [intent for intent in passed if not intent.get("speech_lang_rejected")]
        for intent in passed:
            stored += _agency.store_intents(player_id, save_id, [intent])
    if stored:
        logger.info("social dialogues=%d intents=%d", len(dialogues), stored)

    if _memory is not None:
        from ..memory.base import MemKey

        for dialogue in dialogues:
            if not isinstance(dialogue, dict):
                continue
            lines = dialogue.get("lines") or []
            for participant in (dialogue.get("a"), dialogue.get("b")):
                if participant is None:
                    continue
                partner = dialogue.get("b") if participant == dialogue.get("a") else dialogue.get("a")
                try:
                    await _memory.add_event(
                        MemKey(player_id, save_id, int(participant)),
                        {
                            "type": "social",
                            "content": {
                                "topic": str(dialogue.get("topic") or ""),
                                "lines": lines,
                                "with": partner,
                                # v0.5 R5: provenance so a dialogue can be
                                # audited (llm vs template + which model).
                                "source": str(dialogue.get("source") or "agent"),
                                "provider": str(dialogue.get("provider") or ""),
                                "model": str(dialogue.get("model") or ""),
                                "object": str(dialogue.get("object") or ""),
                                "interaction": str(dialogue.get("interaction") or ""),
                            },
                            "importance": 0.7,
                        },
                    )
                except Exception:
                    pass

    await _store_conversation_summaries(
        result.get("conversations") or [],
        player_id=player_id,
        save_id=save_id,
        world=world,
    )


async def _store_conversation_summaries(
    summaries: list[Any],
    *,
    player_id: str,
    save_id: str,
    world: dict[str, Any],
) -> None:
    """Remember closed conversation sessions and notify the player (v0.4 P4b)."""
    if not summaries:
        return
    policy = getattr(_agency, "speech", None) if _agency is not None else None
    sims = (world or {}).get("sims") or {}
    active_id = (world or {}).get("active_sim_id")
    active_sim = sims.get(str(active_id)) if active_id is not None else None

    for summary in summaries:
        if not isinstance(summary, dict):
            continue
        a, b = summary.get("a"), summary.get("b")
        text = str(summary.get("text") or "").strip()
        if not text:
            continue
        if _memory is not None:
            from ..memory.base import MemKey

            for participant, partner in ((a, b), (b, a)):
                if participant is None:
                    continue
                try:
                    await _memory.add_event(
                        MemKey(player_id, save_id, int(participant)),
                        {
                            "type": "conversation",
                            "content": {
                                "with": partner,
                                "topic": summary.get("topic") or "",
                                "tone": summary.get("tone") or "",
                                "outcome": text,
                                "leaving": bool(summary.get("leaving")),
                                "relationship_shift": summary.get("relationship_shift"),
                                "source": "agent",
                            },
                            "importance": 0.8,
                        },
                    )
                except Exception:
                    pass

        if _agency is None:
            continue
        distance = None
        if active_sim is not None and a is not None:
            distance = distance_between(sims.get(str(a)), active_sim)
        surfaced = policy.within_hearing(distance) if policy is not None else True
        notify = {
            "id": f"conv-{a}-{b}-{summary.get('topic', '')[:12]}",
            "sim_id": int(a) if a is not None else 0,
            "kind": "notify",
            "target_sim_id": b,
            "params": {"surfaced": surfaced},
            "reason": str(summary.get("topic") or ""),
            "narration": text,
            "name": "",
            "args": {},
            "thought": "",
        }
        _agency.store_intents(player_id, save_id, [notify])


async def pull_intents(
    player_id: str = "local",
    save_id: str = "unknown",
    sim_id: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Drain the pending per-Sim intents for the mod's GameLever (v0.3 R3)."""
    if _agency is None:
        return {"ok": False, "intents": []}
    try:
        intents = _agency.pull(player_id, save_id, sim_id=sim_id, limit=limit)
    except Exception as exc:
        logger.error(f"intent pull failed: {exc}")
        return {"ok": False, "intents": []}
    if intents:
        logger.info(
            "pull intents save=%s/%s count=%d kinds=%s",
            player_id,
            save_id,
            len(intents),
            [intent.get("kind") for intent in intents],
        )
    return {"ok": True, "intents": intents}


async def pull_directives(
    player_id: str = "local",
    save_id: str = "unknown",
    sim_id: int | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Transitional alias for :func:`pull_intents` (§15.5)."""
    result = await pull_intents(player_id, save_id, sim_id=sim_id, limit=limit)
    if not result.get("ok"):
        return {"ok": False, "directives": []}
    intents = result.get("intents") or []
    # The legacy alias only carries executable command intents.
    return {"ok": True, "directives": [i for i in intents if i.get("name")]}


def _roster_exposed() -> bool:
    """Honor ``runtime.expose_roster`` (v0.3 R7/§15.11)."""
    if _settings is None:
        return True
    return bool(getattr(_settings.runtime, "expose_roster", True))


def _empty_roster(save_id: str) -> dict[str, Any]:
    return {
        "ok": True,
        "save_id": save_id,
        "seats": 0,
        "used": 0,
        "agents": [],
        "exposed": False,
    }


def seats_roster(save_id: str, player_id: str = "local") -> dict[str, Any]:
    """Return the live agent-roster (seat occupancy) for a save (v0.3 R2)."""
    if _agency is None:
        return {"ok": False, "save_id": save_id, "seats": 0, "used": 0, "agents": []}
    if not _roster_exposed():
        return _empty_roster(save_id)
    roster = _agency.seats.roster(player_id, save_id)
    return {"ok": True, "save_id": save_id, **roster}


def assign_seat(
    save_id: str,
    player_id: str = "local",
    *,
    seats: int | None = None,
    sim_id: int | None = None,
    impulse_frequency: float | None = None,
) -> dict[str, Any]:
    """Resize the seat pool and/or set a per-Sim impulse frequency (v0.3 R2/R7)."""
    if _agency is None:
        return {"ok": False, "save_id": save_id, "seats": 0, "used": 0, "agents": []}
    if seats is not None:
        _agency.seats.configure(seats)
    if sim_id is not None and impulse_frequency is not None:
        _agency.seats.set_impulse_frequency(player_id, save_id, sim_id, impulse_frequency)
    return seats_roster(save_id, player_id)


def god_aggregates(save_id: str, player_id: str = "local") -> dict[str, Any]:
    """Return the aggregated neighborhood state the God may read (v0.2 G1)."""
    from ..god.world_model import aggregates as _aggregates

    census = _census_by_save.get(_census_key(player_id, save_id), {})
    return {"ok": True, "save_id": save_id, "neighborhood": _aggregates(census)}


async def maybe_consolidate(sim, lang: str) -> None:
    """Fold an idle dialogue into one memory (M1), best-effort and off the path."""
    if _memory is None or _settings is None or not _settings.memory.consolidation_enabled:
        return
    from ..memory import consolidation as dialogue_consolidation
    from ..memory.base import MemKey

    key = MemKey(sim.player_id, sim.save_id, sim.sim_id)
    try:
        turns = await _memory.unconsolidated_events(key, limit=100)
    except Exception:
        return
    if len(turns) < 2:
        return
    last_ts = float(turns[-1].get("created_at") or 0.0)
    if (time.time() - last_ts) < _settings.memory.dialogue_idle_seconds:
        return
    try:
        profile = await _memory.get_profile(key) or {}
    except Exception:
        profile = {}
    result = await dialogue_consolidation.consolidate_turns(
        turns, profile, _effective_registry(), lang
    )
    try:
        await _memory.add_event(
            key,
            {
                "type": "consolidated_memory",
                "content": result,
                "importance": 1.2,
                "emotion": (result.get("emotional_takeaways") or [None])[0],
                "salience": 1.2,
            },
        )
        await _memory.mark_consolidated(
            key, [turn.get("id") for turn in turns if turn.get("id") is not None]
        )
    except Exception as exc:
        logger.warning(f"dialogue consolidation persist failed: {exc}")


async def consolidate_now(sim, lang: str) -> dict[str, Any]:
    """Forcefully fold a Sim's pending dialogue into one memory (manual trigger).

    Unlike :func:`maybe_consolidate` this ignores the idle window, so the pie
    menu can consolidate on demand. Never raises.
    """
    if _memory is None or _settings is None:
        return {"ok": False, "consolidated": 0, "message_key": "error.memory_unavailable"}
    if not _settings.memory.consolidation_enabled:
        return {"ok": False, "consolidated": 0, "message_key": "notify.consolidate.disabled"}

    from ..memory import consolidation as dialogue_consolidation
    from ..memory.base import MemKey

    key = MemKey(sim.player_id, sim.save_id, sim.sim_id)
    try:
        turns = await _memory.unconsolidated_events(key, limit=100)
    except Exception as exc:
        logger.warning(f"consolidate_now read failed: {exc}")
        return {"ok": False, "consolidated": 0, "message_key": "error.memory_unavailable"}

    if len(turns) < 2:
        return {"ok": True, "consolidated": 0, "message_key": "notify.consolidate.none"}

    try:
        profile = await _memory.get_profile(key) or {}
    except Exception:
        profile = {}

    try:
        result = await dialogue_consolidation.consolidate_turns(
            turns, profile, _effective_registry(), lang
        )
    except Exception as exc:
        logger.warning(f"consolidate_now failed: {exc}")
        return {"ok": False, "consolidated": 0, "message_key": "error.brain_foggy"}

    try:
        await _memory.add_event(
            key,
            {
                "type": "consolidated_memory",
                "content": result,
                "importance": 1.2,
                "emotion": (result.get("emotional_takeaways") or [None])[0],
                "salience": 1.2,
            },
        )
        await _memory.mark_consolidated(
            key, [turn.get("id") for turn in turns if turn.get("id") is not None]
        )
    except Exception as exc:
        logger.warning(f"consolidate_now persist failed: {exc}")
        return {"ok": False, "consolidated": 0, "message_key": "error.brain_foggy"}

    logger.info("consolidate_now sim=%s turns=%d", sim.sim_id, len(turns))
    return {"ok": True, "consolidated": len(turns), "message_key": "notify.consolidate.done"}


async def shutdown() -> None:
    """Clean up resources."""
    global _registry, _memory, _nodes, _rails, _audit, _scheduler, _chat_budget, _orchestrator
    global _agency, _coordinator, _context_forge, _last_prune_at
    _context_forge = None
    if _scheduler is not None:
        await _scheduler.stop()
        _scheduler = None
    if _agency is not None:
        await _agency.stop()
        _agency = None
    _coordinator = None
    _chat_budget = None
    _orchestrator = None
    if _registry:
        await _registry.close()
    if _memory:
        await _memory.close()
    if _audit:
        _audit.close()
    _registry = None
    _memory = None
    _nodes = None
    _rails = None
    _audit = None
    _census_by_save.clear()
    _last_prune_at = 0.0