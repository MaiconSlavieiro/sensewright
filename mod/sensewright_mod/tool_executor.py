"""
Tool executor for Sensewright.
Dispatches v1 tool calls to local functions, posts results to /v1/tools/result.
All game interactions are guarded; game actions return not_implemented when the
game API is unavailable, so the module imports and tests outside The Sims 4.

Argument contracts mirror the sidecar's ``tools/schemas.py`` (the single source
of truth). Each tool reads its canonical key only; no aliases:

    add_buff            buff_name
    add_trait           trait_name
    queue_interaction   interaction_name, target_sim_id?, target_object_id?
    say_to              target_sim_id, tone? (mapped to an affordance)
    move_to             x/y/z or target_sim_id/target_object_id
    set_mood            mood and/or buff_name
    sim_profile         target_sim_id
    socialize           target_sim_id, tone?
    approach            target_sim_id or target_object_id
    act_out             action, interaction_name?
"""


from typing import Any, Callable, Dict

from .debug_log import (
    debug_log,
    log_exception,
    safe_getattr,
    safe_call,
)
from .http_client import post_json, SidecarUnreachable, SidecarError
from .sim_context import collect
from .rails import DirectiveRails


# Tool function signatures: name/args in, result dict out.
ToolFunc = Callable[[Dict[str, Any]], Dict[str, Any]]


# Module-level safety rails: 10 directives/minute, 10s player-priority lock.
_rails = DirectiveRails(max_per_minute=10, player_lock_seconds=10.0)


def get_rails():
    """Return the module-level DirectiveRails instance."""
    return _rails


# --- Helpers ---

def _get_services():
    """Try to import the game services module. Returns None outside the game."""
    try:
        import services  # type: ignore
        return services
    except Exception:
        return None


def _get_target_sim(sim_id: int = 0):
    """Get SimInfo by ID, or active Sim if 0. Returns None if unavailable."""
    services = _get_services()
    if services is None:
        return None
    try:
        sim_info_manager = services.sim_info_manager()
        if sim_info_manager is None:
            return None
        if sim_id == 0:
            # Get active Sim
            client_manager = services.client_manager()
            if client_manager:
                client = client_manager.get_first_client()
                if client:
                    return client.active_sim_info
            return None
        return sim_info_manager.get(sim_id)
    except Exception:
        return None


def record_player_activity(sim_id=0):
    """Arm the player-priority lock for the player's active Sim. Never raises."""
    try:
        info = _get_target_sim(sim_id)
        resolved = getattr(info, "id", 0) or sim_id or 0
        _rails.record_player_activity(resolved)
        return resolved
    except Exception as exc:
        log_exception("tool_executor.record_player_activity", exc)
        return 0


def _get_object_by_id(object_id):
    """Resolve a game object by id. Returns None if unavailable."""
    services = _get_services()
    if services is None:
        return None
    try:
        manager_getter = _safe_getattr(services, "object_manager", None)
        manager = _safe_call(manager_getter) if manager_getter is not None else None
        if manager is None:
            return None
        getter = _safe_getattr(manager, "get", None)
        if getter is None:
            return None
        return _safe_call(getter, object_id)
    except Exception:
        return None


def _get_sim_instance(sim_info):
    """Get the live Sim instance for a SimInfo."""
    if sim_info is None:
        return None
    getter = _safe_getattr(sim_info, "get_sim_instance", None)
    if getter is not None:
        return _safe_call(getter)
    return _safe_getattr(sim_info, "sim_instance", None)


def _resolve_affordance(args: Dict[str, Any]):
    """Resolve an affordance instance from the schema-defined ``interaction_name``.

    The canonical key is ``interaction_name`` (sidecar ``tools/schemas.py``);
    an int value is accepted as a tuning id.
    """
    services = _get_services()
    if services is None:
        return None
    key = args.get("interaction_name")
    if key is None:
        return None
    try:
        import sims4.resources  # type: ignore
        instance_manager = services.get_instance_manager(sims4.resources.Types.INTERACTION)
    except Exception:
        return None
    if instance_manager is None:
        return None
    getter = _safe_getattr(instance_manager, "get", None)
    if getter is None:
        return None
    return _safe_call(getter, key)


def _resolve_trait(trait_name):
    """Resolve a trait instance by name/tuning id via the instance manager."""
    services = _get_services()
    if services is None:
        return None
    try:
        import sims4.resources  # type: ignore
        instance_manager = services.get_instance_manager(sims4.resources.Types.TRAIT)
    except Exception:
        return None
    if instance_manager is None:
        return None
    getter = _safe_getattr(instance_manager, "get", None)
    if getter is None:
        return None
    return _safe_call(getter, trait_name)


# R1: candidate module paths for the native interaction APIs. The exact path
# varies by patch, so each is attempted in order and the first import wins.
_INTERACTION_CONTEXT_MODULES = (
    "interactions.context",
    "sims4.interactions.context",
)
_PRIORITY_MODULES = (
    "interactions.priority",
    "interactions.interaction_priority",
)


def _import_first(module_names):
    """Import the first importable module from ``module_names``.

    Returns ``(module, error)``; ``module`` is ``None`` when none import and
    ``error`` is the last import exception (or ``None``).
    """
    last_exc = None
    for name in module_names:
        try:
            return __import__(name, fromlist=["*"]), None
        except Exception as exc:
            last_exc = exc
            continue
    return None, last_exc


def _resolve_priority(priority_module):
    """Return the ``High`` priority member of a priority module, or ``None``."""
    if priority_module is None:
        return None
    for attr in ("Priority", "InteractionPriority"):
        candidate = safe_getattr(priority_module, attr, None)
        if candidate is not None:
            value = safe_getattr(candidate, "High", None)
            if value is None:
                value = safe_getattr(candidate, "HIGH", None)
            if value is not None:
                return value
    return None


def _build_interaction_context(sim_instance, target_context=None):
    """Build the ``InteractionContext`` ``push_super_affordance`` expects.

    The validated signature (shipped ``sim_info_manager.push_sims_to_go_home``)
    is ``sim.push_super_affordance(affordance, target, context)``; passing
    ``None`` as the context makes the push fail, so a SOURCE_SCRIPT / High
    priority context is built here.

    Best-effort against multiple real API shapes (R1): candidate module paths
    are tried for the context/priority classes and construction is attempted
    with ``(source, source_priority, run_priority)``, then ``(source, priority)``,
    then ``(source,)``. Never raises; returns ``target_context`` unchanged when
    one was supplied, else ``None`` when no shape works.
    """
    if target_context is not None:
        return target_context

    context_module, import_exc = _import_first(_INTERACTION_CONTEXT_MODULES)
    if context_module is None:
        if import_exc is not None:
            log_exception("tool_executor._build_interaction_context.import", import_exc)
        return None
    context_cls = safe_getattr(context_module, "InteractionContext", None)
    if context_cls is None:
        log_exception(
            "tool_executor._build_interaction_context.class",
            AttributeError("InteractionContext unavailable"))
        return None

    source_priority = safe_getattr(context_cls, "SOURCE_SCRIPT", None)
    if source_priority is None:
        source_priority = safe_getattr(context_module, "SOURCE_SCRIPT", None)
    priority_module, _priority_exc = _import_first(_PRIORITY_MODULES)
    priority = _resolve_priority(priority_module)

    attempts = []
    if source_priority is not None and priority is not None:
        attempts.append((sim_instance, source_priority, priority))
    if priority is not None:
        attempts.append((sim_instance, priority))
    attempts.append((sim_instance,))

    last_exc = None
    for attempt_args in attempts:
        try:
            return context_cls(*attempt_args)
        except Exception as exc:
            last_exc = exc
            continue
    if last_exc is not None:
        log_exception("tool_executor._build_interaction_context", last_exc)
    return None


def _push_affordance(sim_instance, affordance, target=None, target_context=None):
    """Push an affordance onto a Sim. Returns True if a push method existed.

    Prefers the Sim-level ``push_super_affordance(affordance, target, context)``
    (the validated entry point) and falls back to the interaction queue methods.
    """
    context = _build_interaction_context(sim_instance, target_context)
    push_super = _safe_getattr(sim_instance, "push_super_affordance", None)
    if push_super is not None:
        _safe_call(push_super, affordance, target, context)
        return True
    queue = _safe_getattr(sim_instance, "queue", None)
    if queue is None:
        return False
    queue_push_super = _safe_getattr(queue, "push_super_affordance", None)
    if queue_push_super is not None:
        _safe_call(queue_push_super, affordance, target, context)
        return True
    push_interaction = _safe_getattr(queue, "push_interaction", None)
    if push_interaction is not None:
        _safe_call(push_interaction, affordance, target)
        return True
    return False


# Backwards-compatible aliases (code review item H5): the shared guards in
# ``debug_log`` always log real exceptions. Kept module-level so existing
# callers (and tests) that reference ``tool_executor._safe_getattr`` keep working.
_safe_getattr = safe_getattr
_safe_call = safe_call


# --- Per-key type validation (code review item H6) ---

def _invalid_argument(key: str) -> Dict[str, Any]:
    """Build the canonical bad-argument result for a schema key."""
    return {"ok": False, "error": "invalid_argument", "detail": key}


def _as_int(value):
    """Coerce a schema integer key: ``int`` passthrough, numeric ``str`` parsed.

    Returns ``None`` for anything else (including ``bool``, which is never a
    valid Sim/object id here).
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # JSON/Pydantic may serialize an integer id as a float (e.g. 1.0).
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _as_str(value):
    """Accept only a real ``str`` (never coerce numbers into a string)."""
    return value if isinstance(value, str) else None


def _validated_id(args: Dict[str, Any], key: str, default=None):
    """Return ``(value, error)`` for an id key.

    Absent/``None`` keys yield ``default`` (preserving the existing "missing
    argument" flows); a present but non-numeric value yields an
    ``invalid_argument`` error dict.
    """
    raw = args.get(key)
    if raw is None:
        return default, None
    coerced = _as_int(raw)
    if coerced is None:
        return None, _invalid_argument(key)
    return coerced, None


# --- Tool implementations ---

def tool_get_needs(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get current needs/motives for a Sim."""
    sim_id, err = _validated_id(args, "sim_id", 0)
    if err is not None:
        return err
    sim_info = _get_target_sim(sim_id)
    if sim_info is None:
        return {"ok": False, "error": "sim_not_found"}

    context = collect(sim_info)
    return {"ok": True, "result": context.get("needs", {})}


def tool_get_relationships(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get relationships for a Sim."""
    sim_id, err = _validated_id(args, "sim_id", 0)
    if err is not None:
        return err
    sim_info = _get_target_sim(sim_id)
    if sim_info is None:
        return {"ok": False, "error": "sim_not_found"}

    context = collect(sim_info)
    return {"ok": True, "result": context.get("relationships", [])}


def tool_get_inventory(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get inventory for a Sim."""
    sim_id, err = _validated_id(args, "sim_id", 0)
    if err is not None:
        return err
    sim_info = _get_target_sim(sim_id)
    if sim_info is None:
        return {"ok": False, "error": "sim_not_found"}

    sim_instance = _get_sim_instance(sim_info)
    if sim_instance is None:
        return {"ok": True, "result": {"items": []}}

    items = []

    inventory = _safe_getattr(sim_instance, "inventory", None)
    if inventory is None:
        inventory = _safe_getattr(sim_instance, "inventory_component", None)

    if inventory is not None:
        get_items = _safe_getattr(inventory, "get_items", None)
        if callable(get_items):
            result = _safe_call(get_items)
            if result is not None:
                try:
                    for item in result:
                        item_name = _safe_getattr(item, "definition", None)
                        if item_name is not None:
                            item_name = _safe_getattr(item_name, "__name__", None)
                        if not isinstance(item_name, str) or not item_name:
                            item_name = _safe_getattr(item, "__name__", None)
                        if not isinstance(item_name, str) or not item_name:
                            item_name = _safe_getattr(item, "name", None)
                        if not isinstance(item_name, str) or not item_name:
                            try:
                                item_name = str(item)
                            except Exception:
                                item_name = ""
                        if item_name:
                            items.append(item_name)
                except Exception:
                    pass

    if not items:
        get_inventory = _safe_getattr(sim_instance, "get_inventory", None)
        if callable(get_inventory):
            result = _safe_call(get_inventory)
            if result is not None:
                try:
                    for item in result:
                        item_name = _safe_getattr(item, "definition", None)
                        if item_name is not None:
                            item_name = _safe_getattr(item_name, "__name__", None)
                        if not isinstance(item_name, str) or not item_name:
                            item_name = _safe_getattr(item, "__name__", None)
                        if not isinstance(item_name, str) or not item_name:
                            item_name = _safe_getattr(item, "name", None)
                        if not isinstance(item_name, str) or not item_name:
                            try:
                                item_name = str(item)
                            except Exception:
                                item_name = ""
                        if item_name:
                            items.append(item_name)
                except Exception:
                    pass

    return {"ok": True, "result": {"items": items}}


def tool_get_world_time(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get current game world time."""
    context = collect()
    return {"ok": True, "result": {"clock": context.get("clock", ""), "save_id": context.get("save_id", "")}}


def _apply_buff(sim_info, buff_name) -> bool:
    """Apply a buff/moodlet via whichever API the sim_info exposes.

    Returns True when an application method existed (call failures are
    swallowed, matching the best-effort contract).
    """
    add_buff = _safe_getattr(sim_info, "add_buff", None)
    if add_buff is not None:
        _safe_call(add_buff, buff_name)
        return True

    add_buff_from_op = _safe_getattr(sim_info, "add_buff_from_op", None)
    if add_buff_from_op is not None:
        _safe_call(add_buff_from_op, buff_name)
        return True

    buff_component = _safe_getattr(sim_info, "buff_component", None)
    component_add = _safe_getattr(buff_component, "add_buff", None) if buff_component is not None else None
    if component_add is not None:
        _safe_call(component_add, buff_name)
        return True

    return False


def tool_add_buff(args: Dict[str, Any]) -> Dict[str, Any]:
    """Add a buff by name to a Sim."""
    try:
        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}

        sim_id, err = _validated_id(args, "sim_id", 0)
        if err is not None:
            return err
        sim_info = _get_target_sim(sim_id)
        if sim_info is None:
            return {"ok": False, "error": "sim_not_found"}

        buff_name = args.get("buff_name")
        if not buff_name:
            return {"ok": False, "error": "missing_argument", "detail": "buff_name"}

        if not _apply_buff(sim_info, buff_name):
            return {"ok": False, "error": "not_implemented"}
        return {"ok": True, "result": {"buff": buff_name}}
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


def tool_add_trait(args: Dict[str, Any]) -> Dict[str, Any]:
    """Add a trait by name to a Sim."""
    try:
        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}

        sim_id, err = _validated_id(args, "sim_id", 0)
        if err is not None:
            return err
        sim_info = _get_target_sim(sim_id)
        if sim_info is None:
            return {"ok": False, "error": "sim_not_found"}

        trait_name = args.get("trait_name")
        if not trait_name:
            return {"ok": False, "error": "missing_argument", "detail": "trait_name"}

        trait = _resolve_trait(trait_name)
        if trait is None:
            return {"ok": False, "error": "not_implemented"}

        add_trait = _safe_getattr(sim_info, "add_trait", None)
        if add_trait is None:
            return {"ok": False, "error": "not_implemented"}
        _safe_call(add_trait, trait)
        return {"ok": True, "result": {"trait": trait_name}}
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


def tool_queue_interaction(args: Dict[str, Any]) -> Dict[str, Any]:
    """Queue an interaction for a Sim (autonomy level: semi/full)."""
    try:
        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}

        sim_id, err = _validated_id(args, "sim_id", 0)
        if err is not None:
            return err
        sim_info = _get_target_sim(sim_id)
        if sim_info is None:
            return {"ok": False, "error": "sim_not_found"}

        target_sim_id, err = _validated_id(args, "target_sim_id", None)
        if err is not None:
            return err
        target_object_id, err = _validated_id(args, "target_object_id", None)
        if err is not None:
            return err

        sim_instance = _get_sim_instance(sim_info)
        if sim_instance is None:
            return {"ok": False, "error": "not_implemented"}

        affordance = _resolve_affordance(args)
        if affordance is None:
            return {"ok": False, "error": "not_implemented"}

        target = None
        if target_sim_id is not None and target_sim_id != 0:
            target = _get_sim_instance(_get_target_sim(target_sim_id))
        elif target_object_id is not None:
            target = _get_object_by_id(target_object_id)

        target_context = args.get("target_context")
        if not _push_affordance(sim_instance, affordance, target, target_context):
            return {"ok": False, "error": "not_implemented"}

        return {"ok": True, "result": {
            "interaction": args.get("interaction_name"),
            "target_sim_id": target_sim_id,
        }}
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


def tool_move_to(args: Dict[str, Any]) -> Dict[str, Any]:
    """Move Sim to a location (autonomy level: semi/full)."""
    try:
        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}

        sim_id, err = _validated_id(args, "sim_id", 0)
        if err is not None:
            return err
        target_sim_id, err = _validated_id(args, "target_sim_id", None)
        if err is not None:
            return err
        target_object_id, err = _validated_id(args, "target_object_id", None)
        if err is not None:
            return err

        sim_info = _get_target_sim(sim_id)
        if sim_info is None:
            return {"ok": False, "error": "sim_not_found"}

        sim_instance = _get_sim_instance(sim_info)
        if sim_instance is None:
            return {"ok": False, "error": "not_implemented"}

        x = args.get("x")
        y = args.get("y")
        target_position = None
        if x is not None and y is not None:
            target_position = (x, y, args.get("z", 0))
        else:
            if target_sim_id is not None and target_sim_id != 0:
                target_instance = _get_sim_instance(_get_target_sim(target_sim_id))
                target_position = _safe_getattr(target_instance, "position", None)
            elif target_object_id is not None:
                target_object = _get_object_by_id(target_object_id)
                target_position = _safe_getattr(target_object, "position", None)

        if target_position is None:
            return {"ok": False, "error": "missing_argument", "detail": "x/y or target"}

        route_to = _safe_getattr(sim_instance, "route_to", None)
        if route_to is not None:
            _safe_call(route_to, target_position)
            return {"ok": True, "result": {"position": target_position}}

        routing = _safe_getattr(sim_instance, "routing_component", None)
        routing_route = _safe_getattr(routing, "route_to", None) if routing is not None else None
        if routing_route is None:
            return {"ok": False, "error": "not_implemented"}
        _safe_call(routing_route, target_position)
        return {"ok": True, "result": {"position": target_position}}
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


# Tone (sidecar ``say_to`` schema) to a base-game social affordance name.
_TONE_AFFORDANCES = {
    "friendly": "sim-chat",
    "romantic": "sim-flirt",
    "funny": "sim-joke",
    "mean": "sim-insult",
    "awkward": "sim-chat",
    "serious": "sim-chat",
}

# Base-game social affordance names tried in order when the tone-mapped name
# cannot be resolved (R1 best-effort; the exact tuning id varies by patch).
_SOCIAL_AFFORDANCE_CANDIDATES = (
    "sim-chat",
    "social_Chat",
    "social-chat",
    "Chat",
)


def tool_say_to(args: Dict[str, Any]) -> Dict[str, Any]:
    """Make Sim say something to another Sim (autonomy level: semi/full)."""
    try:
        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}

        sim_id, err = _validated_id(args, "sim_id", 0)
        if err is not None:
            return err
        sim_info = _get_target_sim(sim_id)
        if sim_info is None:
            return {"ok": False, "error": "sim_not_found"}

        target_sim_id, err = _validated_id(args, "target_sim_id", None)
        if err is not None:
            return err
        if target_sim_id is None or target_sim_id == 0:
            return {"ok": False, "error": "missing_argument", "detail": "target_sim_id"}

        tone_raw = args.get("tone")
        tone_value = _as_str(tone_raw) if tone_raw is not None else ""
        if tone_raw is not None and tone_value is None:
            return _invalid_argument("tone")

        target_info = _get_target_sim(target_sim_id)
        if target_info is None:
            return {"ok": False, "error": "target_not_found"}
        target_instance = _get_sim_instance(target_info)

        sim_instance = _get_sim_instance(sim_info)
        if sim_instance is None:
            return {"ok": False, "error": "not_implemented"}

        # The say_to schema sends a tone (not an affordance); map it to a social
        # affordance and try the base-game social candidates in order (R1).
        tone = (tone_value or "friendly").lower()
        candidates = []
        explicit = args.get("interaction_name")
        if explicit:
            candidates.append(explicit)
        candidates.append(_TONE_AFFORDANCES.get(tone, "sim-chat"))
        candidates.extend(_SOCIAL_AFFORDANCE_CANDIDATES)

        queue_args = dict(args)
        affordance = None
        seen = set()
        for name in candidates:
            if name in seen:
                continue
            seen.add(name)
            queue_args["interaction_name"] = name
            affordance = _resolve_affordance(queue_args)
            if affordance is not None:
                break
        if affordance is None:
            return {"ok": False, "error": "not_implemented"}

        if not _push_affordance(sim_instance, affordance, target_instance, args.get("target_context")):
            return {"ok": False, "error": "not_implemented"}

        return {"ok": True, "result": {"target_sim_id": target_sim_id}}
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


def tool_cancel_current(args: Dict[str, Any]) -> Dict[str, Any]:
    """Cancel Sim's current interaction (autonomy level: full)."""
    try:
        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}

        sim_id, err = _validated_id(args, "sim_id", 0)
        if err is not None:
            return err
        sim_info = _get_target_sim(sim_id)
        if sim_info is None:
            return {"ok": False, "error": "sim_not_found"}

        sim_instance = _get_sim_instance(sim_info)
        if sim_instance is None:
            return {"ok": False, "error": "not_implemented"}

        queue = _safe_getattr(sim_instance, "queue", None)
        if queue is None:
            return {"ok": False, "error": "not_implemented"}

        cancel_all = _safe_getattr(queue, "cancel_all", None)
        if cancel_all is not None:
            _safe_call(cancel_all)
            return {"ok": True, "result": {"cancelled": True}}

        clear = _safe_getattr(queue, "clear", None)
        if clear is not None:
            _safe_call(clear)
            return {"ok": True, "result": {"cancelled": True}}

        return {"ok": False, "error": "not_implemented"}
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


# --- v0.2: autonomous Sim-agent tools (PLANO §14.2) ---

# Mood label to buff/moodlet name (used by set_mood when buff_name is absent).
_MOOD_BUFF_MAP = {
    "happy": "Happy",
    "sad": "Sad",
    "angry": "Angry",
    "tense": "Stressed",
    "stressed": "Stressed",
    "bored": "Bored",
    "flirty": "Flirty",
    "energized": "Energized",
    "uncomfortable": "Uncomfortable",
    "embarrassed": "Embarrassed",
    "confident": "Confident",
    "focused": "Focused",
    "playful": "Playful",
    "dazed": "Dazed",
    "fine": "Fine",
    "neutral": "Fine",
}


def tool_nearby_sims(args: Dict[str, Any]) -> Dict[str, Any]:
    """List nearby instanced Sims (read-only)."""
    try:
        from . import state_collector
        _zone, sims = state_collector.sample_zone()
        return {"ok": True, "sims": sims}
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


def tool_world_state(args: Dict[str, Any]) -> Dict[str, Any]:
    """Read the zone context (read-only)."""
    try:
        from . import state_collector
        zone, _sims = state_collector.sample_zone()
        return {"ok": True, "zone": zone}
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


def tool_sim_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    """Read another Sim's public state (name, mood, needs, traits, relationships)."""
    try:
        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}

        target_sim_id, err = _validated_id(args, "target_sim_id", None)
        if err is not None:
            return err
        if target_sim_id is None or target_sim_id == 0:
            return {"ok": False, "error": "missing_argument", "detail": "target_sim_id"}

        sim_info = _get_target_sim(target_sim_id)
        if sim_info is None:
            return {"ok": False, "error": "target_not_found"}

        context = collect(sim_info)
        return {"ok": True, "result": {
            "sim_id": context.get("sim_id", target_sim_id),
            "full_name": context.get("full_name", ""),
            "mood": context.get("mood", ""),
            "needs": context.get("needs", {}),
            "traits": context.get("traits", []),
            "relationships": context.get("relationships", []),
        }}
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


def tool_spontaneous_line(args: Dict[str, Any]) -> Dict[str, Any]:
    """Acknowledge an unprompted thought/line (surfaced by the caller)."""
    text = args.get("text")
    if not text:
        return {"ok": False, "error": "missing_argument", "detail": "text"}
    return {
        "ok": True,
        "text": text,
        "audience": args.get("audience", "self"),
        "tone": args.get("tone", "neutral"),
    }


def tool_set_mood(args: Dict[str, Any]) -> Dict[str, Any]:
    """Color the Sim's mood by applying a buff (maps mood -> buff when needed)."""
    try:
        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}

        sim_id, err = _validated_id(args, "sim_id", 0)
        if err is not None:
            return err
        sim_info = _get_target_sim(sim_id)
        if sim_info is None:
            return {"ok": False, "error": "sim_not_found"}

        mood = args.get("mood")
        buff_name = args.get("buff_name")
        if not buff_name and mood:
            buff_name = _MOOD_BUFF_MAP.get(str(mood).lower(), str(mood).title())
        if not buff_name:
            return {"ok": False, "error": "missing_argument", "detail": "mood"}

        if not _apply_buff(sim_info, buff_name):
            return {"ok": False, "error": "not_implemented"}
        return {"ok": True, "result": {"mood": mood, "buff": buff_name}}
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


def tool_socialize(args: Dict[str, Any]) -> Dict[str, Any]:
    """Initiate a friendly social interaction, reusing the queue logic."""
    try:
        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}

        target_sim_id, err = _validated_id(args, "target_sim_id", None)
        if err is not None:
            return err
        if target_sim_id is None or target_sim_id == 0:
            return {"ok": False, "error": "missing_argument", "detail": "target_sim_id"}

        target_info = _get_target_sim(target_sim_id)
        if target_info is None:
            return {"ok": False, "error": "target_not_found"}

        queue_args = dict(args)
        queue_args.setdefault("interaction_name", "sim-chat")
        return tool_queue_interaction(queue_args)
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


def tool_approach(args: Dict[str, Any]) -> Dict[str, Any]:
    """Walk the Sim toward a Sim/object, reusing the move_to logic."""
    try:
        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}

        target_sim_id, err = _validated_id(args, "target_sim_id", None)
        if err is not None:
            return err
        target_object_id, err = _validated_id(args, "target_object_id", None)
        if err is not None:
            return err
        if not target_sim_id and target_object_id is None:
            return {"ok": False, "error": "missing_argument",
                    "detail": "target_sim_id or target_object_id"}

        return tool_move_to(args)
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


def tool_act_out(args: Dict[str, Any]) -> Dict[str, Any]:
    """Perform an autonomous action; queue an interaction when named, else ack."""
    try:
        interaction_name = args.get("interaction_name")
        action = args.get("action")
        if not interaction_name:
            if not action:
                return {"ok": False, "error": "missing_argument", "detail": "action"}
            return {"ok": True, "action": action}

        if _get_services() is None:
            return {"ok": False, "error": "not_implemented"}
        return tool_queue_interaction(args)
    except Exception as e:
        return {"ok": False, "error": "execution_failed", "detail": str(e)}


# Tool registry
_TOOL_REGISTRY: Dict[str, ToolFunc] = {
    "get_needs": tool_get_needs,
    "get_relationships": tool_get_relationships,
    "get_inventory": tool_get_inventory,
    "get_world_time": tool_get_world_time,
    "add_buff": tool_add_buff,
    "add_trait": tool_add_trait,
    "queue_interaction": tool_queue_interaction,
    "move_to": tool_move_to,
    "say_to": tool_say_to,
    "cancel_current": tool_cancel_current,
    "nearby_sims": tool_nearby_sims,
    "world_state": tool_world_state,
    "sim_profile": tool_sim_profile,
    "spontaneous_line": tool_spontaneous_line,
    "set_mood": tool_set_mood,
    "socialize": tool_socialize,
    "approach": tool_approach,
    "act_out": tool_act_out,
}


# --- v0.3 R3: GameLever — intent -> native lever adapter (PLANO §15.5) ---
#
# The agent emits intents (not commands). Each intent is translated here into
# the closest native lever available; the hybrid rule inserts a *gated*
# candidate into the queue when no pure bias exists. Intents whose native lever
# is not implemented yet acknowledge without side effects so the loop stays alive.

def _speak_as_line(args: Dict[str, Any], target: Any = None) -> Dict[str, Any]:
    """Surface a spoken intent as a notification line (native-push fallback).

    The native social affordance is not reliably resolvable yet (R1 pending), so
    a targeted ``say_to`` that cannot be pushed degrades to a visible
    ``spontaneous_line`` instead of a silent no-op.
    """
    text = args.get("text") or args.get("message")
    if not text:
        return {"ok": False, "error": "missing_argument", "detail": "text"}
    return tool_spontaneous_line({
        "text": text,
        "audience": str(target) if target else str(args.get("audience") or "nearby"),
        "tone": args.get("tone") or "neutral",
    })


def _lever_speak(args: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    """Say something: ``say_to`` when a target exists, else a spontaneous line.

    A failed targeted push (native affordance unresolved / Sim off-lot) falls
    back to surfacing the line so the intent is never silently dropped.
    """
    target = intent.get("target_sim_id") or args.get("target_sim_id")
    if target:
        queue_args = dict(args)
        queue_args["target_sim_id"] = target
        result = tool_say_to(queue_args)
        if result.get("ok"):
            return result
        line = _speak_as_line(args, target)
        if result.get("error"):
            line["native_error"] = result.get("error")
        return line
    return tool_spontaneous_line(args)


def _lever_set_mood(args: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    return tool_set_mood(args)


def _lever_approach(args: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    target = intent.get("target_sim_id") or args.get("target_sim_id")
    if target and not args.get("target_sim_id"):
        args = dict(args)
        args["target_sim_id"] = target
    return tool_approach(args)


def _lever_bias_interaction(args: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    """Bias the Sim toward an interaction kind (a gated queue candidate).

    When the native affordance/queue push is unavailable the intent is
    acknowledged without side effects so the loop is not marked as failed.
    """
    queue_args = dict(args)
    queue_args.setdefault("interaction_name", _TONE_AFFORDANCES.get(
        str(args.get("tone", "friendly")).lower(), "sim-chat"))
    target = intent.get("target_sim_id")
    if target and not queue_args.get("target_sim_id"):
        queue_args["target_sim_id"] = target
    result = tool_queue_interaction(queue_args)
    if result.get("ok"):
        return result
    acknowledged = _lever_ack(args, intent)
    acknowledged["result"]["native_error"] = result.get("error")
    return acknowledged


def _lever_ack(args: Dict[str, Any], intent: Dict[str, Any]) -> Dict[str, Any]:
    """Acknowledge an intent with no native lever yet (degrades gracefully)."""
    return {"ok": True, "result": {"intent": intent.get("kind", ""), "applied": False}}


_INTENT_LEVERS = {
    "speak": _lever_speak,
    "set_mood": _lever_set_mood,
    "approach": _lever_approach,
    "bias_interaction": _lever_bias_interaction,
    "prefer_target": _lever_ack,
    "set_goal": _lever_ack,
    "remember": _lever_ack,
    "forget": _lever_ack,
}


def _intent_args(intent: Dict[str, Any]) -> Dict[str, Any]:
    """Merge an intent's ``params`` (or legacy ``args``) and its Sim id."""
    params = intent.get("params")
    if not isinstance(params, dict) or not params:
        legacy = intent.get("args")
        params = legacy if isinstance(legacy, dict) else {}
    args = dict(params)
    sim_id = intent.get("sim_id")
    if sim_id is not None and "sim_id" not in args:
        args["sim_id"] = sim_id
    return args


def _post_tool_result(tool_call_id: str, result: Dict[str, Any]) -> None:
    """Best-effort POST of an execution result to ``/v1/tools/result``."""
    if not tool_call_id:
        return
    posted_result = result.get("result")
    if posted_result is None and "result" not in result and result.get("ok"):
        posted_result = {k: v for k, v in result.items() if k not in ("ok", "error")} or None
    try:
        post_json("/v1/tools/result", {
            "tool_call_id": tool_call_id,
            "ok": result.get("ok", False),
            "result": posted_result,
            "error": result.get("error"),
        })
    except (SidecarUnreachable, SidecarError) as exc:
        # Sidecar unreachable - result will be lost but game continues.
        debug_log("tool result post failed ({}): sidecar unreachable".format(
            type(exc).__name__))
    except Exception as exc:
        log_exception("tool_executor._post_tool_result", exc)


def execute_intent(intent: Dict[str, Any]) -> Dict[str, Any]:
    """Translate one intent into a native lever (GameLever adapter).

    Falls back to the gated command escape hatch when the intent carries a tool
    ``name`` and has no dedicated lever. Never raises; posts the result back.
    """
    if not isinstance(intent, dict):
        return {"ok": False, "error": "bad_intent"}

    kind = str(intent.get("kind") or "command")
    args = _intent_args(intent)
    sim_id = args.get("sim_id", 0)

    lever = _INTENT_LEVERS.get(kind)
    if lever is not None:
        decision = _rails.check(sim_id, kind)
        if not decision.allowed:
            result: Dict[str, Any] = {"ok": False, "error": decision.reason}
        else:
            try:
                result = lever(args, intent)
                if not isinstance(result, dict):
                    result = {"ok": False, "error": "execution_failed", "detail": "invalid result"}
            except Exception as exc:
                result = {"ok": False, "error": "execution_failed", "detail": str(exc)}
            try:
                _rails.note_executed(sim_id, kind)
            except Exception as exc:
                log_exception("tool_executor.execute_intent.note_executed", exc)
        _post_tool_result(intent.get("id", ""), result)
        return result

    if intent.get("name"):
        # Escape hatch: the v0.2 command palette, still gated by rails.
        return execute({
            "id": intent.get("id", ""),
            "name": intent.get("name", ""),
            "args": args,
        })

    return {"ok": False, "error": "unknown_intent"}


def execute(tool_call: Dict[str, Any]) -> Dict[str, Any]:
    """
    Execute a tool call and post result to sidecar.
    tool_call: {"id": "", "name": "", "args": {}}
    Returns the tool result dict.
    """
    tool_call_id = tool_call.get("id", "")
    tool_name = tool_call.get("name", "")
    tool_args = tool_call.get("args", {})
    if not isinstance(tool_args, dict):
        tool_args = {}

    sim_id = tool_args.get("sim_id", 0)

    # Safety rails run before any dispatch.
    decision = _rails.check(sim_id, tool_name)
    if not decision.allowed:
        result = {"ok": False, "error": decision.reason}
    else:
        tool_func = _TOOL_REGISTRY.get(tool_name)
        if tool_func is None:
            result = {"ok": False, "error": "unknown_tool"}
        else:
            try:
                result = tool_func(tool_args)
                if not isinstance(result, dict):
                    result = {"ok": False, "error": "execution_failed", "detail": "invalid result"}
            except Exception as e:
                result = {"ok": False, "error": "execution_failed", "detail": str(e)}
            try:
                _rails.note_executed(sim_id, tool_name)
            except Exception as exc:
                log_exception("tool_executor.execute.note_executed", exc)

    # Post result to sidecar (best effort). Read tools and spontaneous lines
    # return their payload at the top level (e.g. {"ok": True, "sims": [...]});
    # fall back to those keys when there is no explicit ``result`` field.
    _post_tool_result(tool_call_id, result)
    return result


def execute_batch(tool_calls: list) -> list:
    """Execute multiple tool calls sequentially."""
    results = []
    for tool_call in tool_calls:
        results.append(execute(tool_call))
    return results
