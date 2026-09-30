"""
Event-driven scaffold for Sensewright.
Subscribes to game events via event_manager/test_events and provides alarm scheduling.
All game imports are guarded; no-ops safely outside the game.
"""


from typing import Any, Callable, Dict, List, Optional

from .debug_log import (
    debug_log,
    log_exception,
    safe_call as _safe_call,
    safe_getattr as _safe_getattr,
)

# Event handler type
EventHandler = Callable[[Any], None]

# Registered handlers storage
_registered_handlers: Dict[str, List[EventHandler]] = {}

# (handler, test_event) pairs actually registered, for correct unregistration
_registrations: List[Any] = []

# Handlers already handed to the live event manager, keyed ``(event_name, handler)``.
# The event manager is not available at script-mod import time (services are not
# up yet), so registration is deferred and retried: this set keeps the retries
# idempotent (a bound method is a fresh object on each access, hence the stable
# ``_handlers`` dict cached by the collector).
_registered_pairs: set = set()

# Alarm handles storage
_alarm_handles: List[Any] = []


def _get_test_events():
    """Return the ``event_testing.test_events`` module (home of the TestEvent enum)."""
    try:
        from event_testing import test_events  # type: ignore
        return test_events
    except Exception:
        return None


def _get_event_manager():
    """
    Return ``(event_manager, test_events)``.

    Validated against the live game (patch 1.113): there is no
    ``sims4.event_manager`` module; the manager comes from
    ``services.get_event_manager()`` and the enum from
    ``event_testing.test_events.TestEvent``.
    """
    test_events = _get_test_events()
    manager = None
    try:
        import services  # type: ignore
        getter = _safe_getattr(services, "get_event_manager", None)
        if getter is not None:
            manager = _safe_call(getter)
    except Exception:
        manager = None
    return manager, test_events


# Event constants (TestEvent enum values we care about)
# These are the events we'll subscribe to for state collection
EVENT_ZONE_LOAD = "zone_load"
EVENT_SIM_SPAWN = "sim_spawn"
EVENT_SOCIAL_INTERACTION = "social_interaction"
EVENT_RELATIONSHIP_CHANGE = "relationship_change"
EVENT_BUFF_ADD = "buff_add"
EVENT_BUFF_REMOVE = "buff_remove"
EVENT_TRAIT_CHANGE = "trait_change"
EVENT_SKILL_LEVEL_UP = "skill_level_up"
EVENT_CAREER_CHANGE = "career_change"
EVENT_OBJECT_INTERACTION = "object_interaction"
EVENT_SIM_DEATH = "sim_death"
EVENT_HOUSEHOLD_CHANGE = "household_change"


def register(handlers: Dict[str, List[EventHandler]]) -> bool:
    """
    Register event handlers for game events.

    ``handlers`` maps our event names (strings) to callback lists. The mapping is
    merged into the persistent store (deduplicated by identity), then every
    handler not yet handed to a live event manager is registered. Calling this
    again later (once the game services are up) flushes the queued handlers, so
    its use is idempotent. Returns True only when the manager is available and
    every mapped handler is registered.
    """
    global _registered_handlers

    # Merge (dedup) into the persistent store so a deferred flush can retry.
    for event_name, handler_list in handlers.items():
        bucket = _registered_handlers.setdefault(event_name, [])
        for handler in handler_list:
            if handler not in bucket:
                bucket.append(handler)

    event_manager, test_events = _get_event_manager()
    if event_manager is None:
        # Services not up yet: keep the handlers queued for a later register().
        return False

    return _flush(event_manager, test_events)


def _flush(event_manager, test_events) -> bool:
    """Register every queued handler not yet registered. Idempotent."""
    event_map = _build_event_map(test_events)
    success = True
    for event_name, handler_list in list(_registered_handlers.items()):
        test_event = event_map.get(event_name)
        if test_event is None:
            # No native TestEvent for this name (e.g. sim_spawn): skip silently.
            continue

        for handler in list(handler_list):
            key = (event_name, handler)
            if key in _registered_pairs:
                continue
            try:
                event_manager.register_single_event(handler, test_event)
            except Exception as exc:
                log_exception("events._flush.register", exc)
                success = False
                continue
            _registered_pairs.add(key)
            _registrations.append((handler, test_event))

    return success


def flush_pending() -> bool:
    """Retry registering queued handlers. True when the manager is up."""
    event_manager, test_events = _get_event_manager()
    if event_manager is None:
        return False
    return _flush(event_manager, test_events)


def have_event_manager() -> bool:
    """Whether the game event manager is currently available."""
    manager, _ = _get_event_manager()
    return manager is not None


def _build_event_map(test_events) -> Dict[str, Any]:
    """
    Map our event names to real ``TestEvent`` enum members.

    Validated against the live game (patch 1.113): the members live on the
    ``TestEvent`` class, **not** on the ``test_events`` module, so a module-level
    ``hasattr`` never matched. Candidate order is by relevance; the first member
    that exists wins. ``EVENT_SIM_SPAWN`` has no native TestEvent and stays
    unmapped on purpose (spawn is detected via census diff on zone load).
    """
    test_event_enum = _safe_getattr(test_events, "TestEvent", None)
    if test_event_enum is None:
        return {}

    mapping = {
        EVENT_ZONE_LOAD: ["LoadingScreenLifted", "SimHomeZoneChanged", "SimTravel"],
        EVENT_SIM_SPAWN: [],
        EVENT_SOCIAL_INTERACTION: [
            "InteractionComplete",
            "EncouragedInteractionStarted",
        ],
        EVENT_RELATIONSHIP_CHANGE: [
            "RelationshipChanged",
            "PrerelationshipChanged",
            "AddRelationshipBit",
            "RemoveRelationshipBit",
        ],
        EVENT_BUFF_ADD: ["BuffBeganEvent"],
        EVENT_BUFF_REMOVE: ["BuffEndedEvent"],
        EVENT_TRAIT_CHANGE: ["TraitAddEvent", "TraitRemoveEvent"],
        EVENT_SKILL_LEVEL_UP: ["SkillLevelChange"],
        EVENT_CAREER_CHANGE: ["CareerEvent", "CareerPromoted"],
        EVENT_OBJECT_INTERACTION: ["InteractionComplete"],
        EVENT_SIM_DEATH: ["SimDeathTypeSet"],
        EVENT_HOUSEHOLD_CHANGE: ["HouseholdChanged"],
    }

    event_map = {}
    for our_name, candidates in mapping.items():
        for candidate in candidates:
            test_event = _safe_getattr(test_event_enum, candidate, None)
            if test_event is not None:
                event_map[our_name] = test_event
                break

    return event_map


def unregister_all() -> None:
    """Unregister all registered event handlers."""
    global _registered_handlers, _registrations

    event_manager, _ = _get_event_manager()
    if event_manager is None:
        _registered_handlers.clear()
        _registrations = []
        _registered_pairs.clear()
        return

    # Unregister needs the event type alongside the handler (validated signature:
    # unregister_single_event(self, handler, event_type)).
    for handler, test_event in _registrations:
        try:
            event_manager.unregister_single_event(handler, test_event)
        except Exception as exc:
            log_exception("events.unregister_all", exc)

    _registered_handlers.clear()
    _registrations = []
    _registered_pairs.clear()


def _make_time_span(minutes: float) -> Optional[Any]:
    """
    Build a game time span for the given number of Sim minutes.

    Validated against the live game (patch 1.113): the factory is
    ``date_and_time.create_time_span(days=0, hours=0, minutes=0)``. The legacy
    ``sims4.math.TimeSpan`` fallback is kept for other patches/loaders.
    Returns None if a game time span cannot be built.
    """
    try:
        from date_and_time import create_time_span  # type: ignore
        span = _safe_call(create_time_span, minutes=minutes)
        if span is not None:
            return span
    except Exception:
        pass

    try:
        import sims4.math  # type: ignore
    except Exception:
        return None

    span_type = _safe_getattr(sims4.math, "TimeSpan", None)
    if span_type is None:
        return None

    # Classmethod factories (e.g. TimeSpan.from_minutes)
    for method_name in ("from_minutes", "of_minutes", "from_seconds", "of_seconds"):
        method = _safe_getattr(span_type, method_name, None)
        if method is None:
            continue
        argument = minutes if "minutes" in method_name else minutes * 60.0
        try:
            span = method(argument)
            if span is not None:
                return span
        except Exception:
            continue

    # Constructor with keyword arguments
    for kwargs in (
        {"minutes": minutes},
        {"seconds": minutes * 60.0},
        {"hours": minutes / 60.0},
    ):
        try:
            span = span_type(**kwargs)
            if span is not None:
                return span
        except Exception:
            continue

    # Constructor with a positional argument
    try:
        return span_type(minutes)
    except Exception:
        return None


def _resolve_alarm_owner():
    """
    Return the active Sim *instance* for use as an alarm owner, or None.

    ``alarms.add_alarm`` requires a non-None owner (``AlarmHandle`` raises
    ``ValueError('Alarm created without owner')``) **and** the owner must be
    advanced by the alarm service. Only the active Sim instance (a live GameObject
    in the zone) is reliably ticked; the zone/household/service managers may
    register a handle that never fires (validated). When no live instance exists
    yet, return None so ``add_alarm`` stays deferred and the ``zone.Zone.update``
    hook arms it once the Sim is instanced (code review item M3).
    """
    try:
        import services  # type: ignore
    except Exception:
        return None

    try:
        client_getter = _safe_getattr(services, "client_manager", None)
        client_manager = _safe_call(client_getter) if callable(client_getter) else client_getter
        if client_manager is not None:
            client = _safe_call(_safe_getattr(client_manager, "get_first_client", None))
            sim = _safe_getattr(client, "active_sim", None)
            if sim is not None and _safe_getattr(sim, "queue", None) is not None:
                return sim
            sim_info = _safe_getattr(client, "active_sim_info", None)
            instance = _safe_call(_safe_getattr(sim_info, "get_sim_instance", None))
            if instance is not None:
                return instance
    except Exception as exc:
        log_exception("events._resolve_alarm_owner", exc)

    return None


def _try_add_alarm(time_span: Any, callback: Callable[[], None], repeating: bool,
                   owner: Any = None) -> Optional[Any]:
    """
    Try the validated ``alarms.add_alarm`` signature and close fallbacks.
    Returns the first successful handle, or None.
    """
    try:
        import alarms  # type: ignore
    except Exception:
        return None

    add = _safe_getattr(alarms, "add_alarm", None)
    if add is None:
        return None

    # Validated signature (patch 1.113):
    #   add_alarm(owner, time_span, callback, repeating=False,
    #             repeating_time_span=None, use_sleep_time=True, cross_zone=False)
    # ``owner`` must be non-None (AlarmHandle validates it). ``use_sleep_time``
    # is disabled first so the repeating pulse keeps advancing while a Sim owner
    # sleeps (otherwise the alarm silently stalls at night).
    attempts = (
        lambda: add(owner, time_span, callback, repeating=repeating, use_sleep_time=False),
        lambda: add(owner, time_span, callback, repeating=repeating),
        lambda: add(owner, time_span, callback, repeating=repeating, use_sleep_time=True),
        lambda: add(owner, time_span, callback),
        lambda: add(owner, callback, time_span),
    )

    errors = []
    for index, attempt in enumerate(attempts):
        try:
            handle = attempt()
        except Exception as exc:
            errors.append(exc)
            log_exception("events._try_add_alarm(attempt {})".format(index), exc)
            continue
        if handle is not None:
            return handle

    if errors:
        debug_log(
            "events._try_add_alarm failed after {} attempt(s): {}".format(
                len(errors), "; ".join(repr(error) for error in errors)
            )
        )
    return None


def add_alarm(minutes: float, callback: Callable[[], None], repeating: bool = False) -> Optional[Any]:
    """
    Add a game-clock alarm (respects pause/speed).
    Returns an alarm handle that can be passed to cancel_alarm.
    Returns None if alarms are not available yet (retried later).
    """
    try:
        owner = _resolve_alarm_owner()
        if owner is None:
            debug_log("events.add_alarm deferred (no alarm owner yet)")
            return None

        time_span = _make_time_span(minutes)
        if time_span is None:
            debug_log("events.add_alarm failed (could not build time span)")
            return None

        handle = _try_add_alarm(time_span, callback, repeating, owner)
        if handle is not None:
            _alarm_handles.append(handle)
            debug_log(
                "events.add_alarm ok: {:.1f}min repeating={} owner={} ({})".format(
                    minutes,
                    repeating,
                    type(owner).__name__,
                    getattr(callback, "__name__", callback),
                )
            )
        return handle
    except Exception as exc:
        log_exception("events.add_alarm", exc)
        return None


def cancel_alarm(handle: Any) -> bool:
    """Cancel a previously added alarm."""
    if handle is None:
        return False
    try:
        import alarms  # type: ignore
        alarms.cancel_alarm(handle)
        if handle in _alarm_handles:
            _alarm_handles.remove(handle)
        return True
    except Exception as exc:
        log_exception("events.cancel_alarm", exc)
        return False


def cancel_all_alarms() -> None:
    """Cancel all alarms added by this module."""
    global _alarm_handles
    for handle in _alarm_handles:
        try:
            cancel_alarm(handle)
        except Exception as exc:
            log_exception("events.cancel_all_alarms", exc)
    _alarm_handles.clear()


def get_registered_events() -> List[str]:
    """Get list of event names we have handlers for."""
    return list(_registered_handlers.keys())


# Document which events will be used (for future reference)
"""
Planned event subscriptions:

1. Zone Load (EVENT_ZONE_LOAD)
   - Trigger: Player loads a save / travels to a lot
   - Action: Re-initialize Sim context, re-register Sim-specific alarms

2. Sim Spawn (EVENT_SIM_SPAWN)
   - Trigger: A Sim is instantiated in the world
   - Action: If it's a tracked Sim, start its autonomy loop

3. Social Interaction (EVENT_SOCIAL_INTERACTION)
   - Trigger: Any social interaction completes
   - Action: Update relationship memory, maybe trigger reflection

4. Relationship Change (EVENT_RELATIONSHIP_CHANGE)
   - Trigger: Relationship bits/depth change
   - Action: Update relationship graph in sidecar

5. Buff Add/Remove (EVENT_BUFF_ADD, EVENT_BUFF_REMOVE)
   - Trigger: Moodlets added/removed
   - Action: Track emotional state for personality modeling

6. Trait Change (EVENT_TRAIT_CHANGE)
   - Trigger: Traits added/removed (by LLM or player)
   - Action: Update personality profile, notify sidecar

7. Skill Level Up (EVENT_SKILL_LEVEL_UP)
   - Trigger: Sim gains a skill level
   - Action: Update skill memory, maybe trigger reflection

8. Career Change (EVENT_CAREER_CHANGE)
   - Trigger: Job change, promotion, retirement
   - Action: Update career memory

9. Object Interaction (EVENT_OBJECT_INTERACTION)
   - Trigger: Sim uses an object
   - Action: Track preferences, routines

10. Sim Death (EVENT_SIM_DEATH)
    - Trigger: Sim dies
    - Action: Archive memory, notify relationships

11. Household Change (EVENT_HOUSEHOLD_CHANGE)
    - Trigger: Sim moves in/out, marriage, birth
    - Action: Update household context

Alarms (recurring):
- Every 30 sim-minutes: Collect full context for active Sims, send to sidecar
- Every 2 sim-hours: Run reflection/evolution for tracked Sims
- Every 10 sim-minutes: Check for autonomy directives from sidecar
"""