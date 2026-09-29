"""
Sim context collection for Sensewright.
Gathers best-effort state from the game (mood, needs, traits, skills, etc.).
Never raises - returns whatever it could collect plus {"source": "native"}.
Outside the game returns {} plus keys without crashing.
"""


from typing import Any, Dict, List

from .debug_log import log_exception


def _safe_getattr(obj: Any, attr: str, default=None):
    """Safely get an attribute, logging the real exception when it fails."""
    try:
        return getattr(obj, attr, default)
    except Exception as exc:
        log_exception("sim_context._safe_getattr({!r})".format(attr), exc)
        return default


def _safe_call(func, *args, **kwargs):
    """Safely call a function, logging the real exception when it fails."""
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        log_exception("sim_context._safe_call({!r})".format(getattr(func, "__name__", func)), exc)
        return None


def _get_services():
    """Try to get the services module."""
    try:
        import services  # type: ignore
        return services
    except Exception:
        return None


def _as_str(value) -> str:
    """Best-effort primitive string so game objects never leak into payloads.

    Prefers ``__name__`` (tuning identifiers) and falls back to ``str()``.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    name = _safe_getattr(value, "__name__", None)
    if isinstance(name, str) and name:
        return name
    try:
        return str(value)
    except Exception:
        return ""


def _get_sim_info_manager():
    """Get the SimInfoManager (calling the ``sim_info_manager`` accessor)."""
    services = _get_services()
    if services is None:
        return None
    getter = _safe_getattr(services, "sim_info_manager", None)
    if getter is None:
        return None
    return _safe_call(getter) if callable(getter) else getter


def _get_active_sim_info():
    """Get the active Sim's SimInfo."""
    services = _get_services()
    if services is None:
        return None
    getter = _safe_getattr(services, "client_manager", None)
    if getter is None:
        return None
    client_manager = _safe_call(getter) if callable(getter) else getter
    if client_manager is None:
        return None
    get_first_client = _safe_getattr(client_manager, "get_first_client", None)
    client = _safe_call(get_first_client) if callable(get_first_client) else None
    if client is None:
        return None
    return _safe_getattr(client, "active_sim_info", None)


def _get_save_id() -> str:
    """Get the current save GUID.

    Preferred: the persistence service's save-slot GUID
    (``get_save_slot_proto_guid()``), which is stable across save reloads. Falls
    back to the active zone's ``save_slot_data_id``. Zeros/empties are skipped.
    """
    services = _get_services()
    if services is None:
        return ""

    def _clean(value) -> str:
        if value is None:
            return ""
        text = _as_str(value)
        return "" if text in ("", "0") else text

    # 1. Save-slot GUID (stable per save).
    try:
        getter = _safe_getattr(services, "get_persistence_service", None)
        persistence = _safe_call(getter) if callable(getter) else getter
        if persistence is not None:
            guid_getter = _safe_getattr(persistence, "get_save_slot_proto_guid", None)
            if callable(guid_getter):
                save_id = _clean(_safe_call(guid_getter))
                if save_id:
                    return save_id
    except Exception:
        pass

    # 2. Active zone's save-slot id.
    try:
        zone = None
        for accessor in ("current_zone", "get_zone"):
            getter = _safe_getattr(services, accessor, None)
            if callable(getter):
                zone = _safe_call(getter)
                if zone is not None:
                    break
        if zone is not None:
            save_id = _clean(_safe_getattr(zone, "save_slot_data_id", None))
            if save_id:
                return save_id
    except Exception:
        pass

    # 3. Persistence save-slot data fallback (other patches).
    try:
        getter = _safe_getattr(services, "get_persistence_service", None)
        persistence = _safe_call(getter) if callable(getter) else getter
        if persistence is None:
            return ""
        save_slot_data = _safe_getattr(persistence, "get_save_slot_data", None)
        if save_slot_data is None:
            return ""
        slot_data = _safe_call(save_slot_data)
        if slot_data is None:
            return ""
        return _clean(_safe_getattr(slot_data, "save_slot_guid", None))
    except Exception:
        return ""


def _get_game_clock():
    """Get the game clock service.

    ``services.game_clock_service`` / ``services.time_service`` are *accessors*
    (functions), so they must be called to get the service instance.
    """
    services = _get_services()
    if services is None:
        return None
    for accessor in ("game_clock_service", "time_service"):
        getter = _safe_getattr(services, accessor, None)
        if getter is None:
            continue
        clock = _safe_call(getter) if callable(getter) else getter
        if clock is not None:
            return clock
    return None


def _get_time_string() -> str:
    """Get current game time as a string."""
    clock = _get_game_clock()
    if clock is None:
        return ""
    now = None
    # TimeService exposes ``sim_now``; a clock exposes ``now`` (method or property).
    for name in ("now", "sim_now"):
        value = _safe_getattr(clock, name, None)
        if value is None:
            continue
        now = _safe_call(value) if callable(value) else value
        if now is not None:
            break
    if now is None:
        return ""
    return _as_str(now)


def _get_funds(sim_info) -> int:
    """Get household funds as an int."""
    try:
        household = _safe_getattr(sim_info, "household", None)
        if household is None:
            return 0
        funds = _safe_getattr(household, "funds", 0) or 0
        try:
            return int(funds)
        except (TypeError, ValueError):
            return 0
    except Exception:
        return 0


def _get_mood(sim_info) -> str:
    """Get current mood as a primitive string (SimInfo exposes ``get_mood()``)."""
    try:
        getter = _safe_getattr(sim_info, "get_mood", None)
        mood = _safe_call(getter) if callable(getter) else None
        if mood is None:
            mood = _safe_getattr(sim_info, "mood", None)
        return _as_str(mood)
    except Exception:
        return ""


def _get_needs(sim_info) -> Dict[str, float]:
    """Get motive/commodity levels (needs)."""
    needs = {}
    try:
        commodity_tracker = _safe_getattr(sim_info, "commodity_tracker", None)
        if commodity_tracker is None:
            return needs

        # Common motive commodity IDs (these are tuned in the game)
        motive_names = {
            "hunger": "motive_hunger",
            "bladder": "motive_bladder",
            "energy": "motive_energy",
            "hygiene": "motive_hygiene",
            "fun": "motive_fun",
            "social": "motive_social",
        }

        for name, commodity_type in motive_names.items():
            try:
                # Try to get the commodity instance
                get_commodity = _safe_getattr(commodity_tracker, "get_commodity", None)
                commodity = _safe_call(get_commodity, commodity_type) if callable(get_commodity) else None
                if commodity is not None:
                    value = _safe_getattr(commodity, "get_value", None)
                    if value is not None:
                        needs[name] = float(_safe_call(value) if callable(value) else value)
            except Exception:
                pass
    except Exception:
        pass
    return needs


def _get_traits(sim_info) -> List[str]:
    """Get trait names.

    The trait API on the live patch (1.113) is ``SimInfo.get_traits()``
    (``HasTraitTrackerMixin``) and ``TraitTracker.equipped_traits``; the tracker
    has neither ``get_traits`` nor ``traits`` (those were the bugs logged before).
    """
    traits: List[str] = []
    try:
        traits_list = None

        # Preferred: SimInfo.get_traits() when the mixin is present.
        getter = _safe_getattr(sim_info, "get_traits", None)
        if callable(getter):
            traits_list = _safe_call(getter)

        # Fallback: the tracker's equipped_traits (a property/iterable).
        if not traits_list:
            trait_tracker = _safe_getattr(sim_info, "trait_tracker", None)
            if trait_tracker is not None:
                equipped = _safe_getattr(trait_tracker, "equipped_traits", None)
                traits_list = _safe_call(equipped) if callable(equipped) else equipped

        if traits_list:
            for trait in traits_list:
                trait_name = _as_str(trait)
                if trait_name:
                    traits.append(trait_name)
    except Exception:
        pass
    return traits


def _get_skills(sim_info) -> Dict[str, int]:
    """Get skill levels."""
    skills = {}
    try:
        source = _safe_getattr(sim_info, "skill_tracker", None) or sim_info

        # Try to get all skills
        for method_name in ("get_skills", "skills", "all_skills"):
            getter = _safe_getattr(source, method_name, None)
            skills_list = _safe_call(getter) if callable(getter) else getter
            if skills_list:
                for skill in skills_list:
                    skill_name = _as_str(skill)
                    if not skill_name:
                        continue
                    level = _safe_getattr(skill, "level", 0)
                    try:
                        skills[skill_name] = int(level)
                    except (TypeError, ValueError):
                        skills[skill_name] = 0
                break
    except Exception:
        pass
    return skills


def _career_display_name(career) -> str:
    """Resolve a career's tuning name without leaking the game object.

    A raw ``career`` object stringifies to its id, so prefer the tuning
    ``__name__`` (or the nested ``career_type.__name__``) and only then fall
    back to ``_as_str``.
    """
    name = _safe_getattr(career, "__name__", None)
    if isinstance(name, str) and name and not name.isdigit():
        return name
    career_type = _safe_getattr(career, "career_type", None)
    if career_type is not None:
        type_name = _safe_getattr(career_type, "__name__", None)
        if isinstance(type_name, str) and type_name and not type_name.isdigit():
            return type_name
    return _as_str(career)


def _get_careers(sim_info) -> List[Dict[str, Any]]:
    """Get career information (primitive-only; no game objects leak)."""
    careers = []
    try:
        career_tracker = _safe_getattr(sim_info, "career_tracker", None)
        if career_tracker is None:
            return careers

        getter = _safe_getattr(career_tracker, "careers", None)
        careers_list = _safe_call(getter) if callable(getter) else getter
        if careers_list:
            for career in careers_list:
                level = _safe_getattr(career, "level", 0)
                try:
                    level = int(level)
                except (TypeError, ValueError):
                    level = 0
                career_data = {
                    "name": _career_display_name(career),
                    "level": level,
                    "is_active": bool(_safe_getattr(career, "is_active_career", False)),
                }
                careers.append(career_data)
    except Exception:
        pass
    return careers


def _get_relationships(sim_info) -> List[Dict[str, Any]]:
    """Get relationship data.

    ``RelationshipTracker`` has no ``get_all_relationships``/``relationships`` on
    the live patch; the supported surface is ``get_target_sim_infos()`` (targets)
    plus ``get_relationship_depth(target_sim_id)``.
    """
    relationships: List[Dict[str, Any]] = []
    try:
        rel_tracker = _safe_getattr(sim_info, "relationship_tracker", None)
        if rel_tracker is None:
            return relationships

        get_targets = _safe_getattr(rel_tracker, "get_target_sim_infos", None)
        targets = _safe_call(get_targets) if callable(get_targets) else None
        if not targets:
            # Fallback: the tracker is iterable and yields its relationships.
            try:
                targets = list(rel_tracker)
            except Exception:
                targets = []

        depth_fn = _safe_getattr(rel_tracker, "get_relationship_depth", None)

        for entry in targets or []:
            target_sim = None
            if isinstance(entry, int):
                target_id = entry
            else:
                target_sim = entry
                # The iterable may yield Relationship wrappers, not SimInfos.
                inner = _safe_getattr(entry, "target_sim_info", None)
                if inner is None:
                    inner = _safe_getattr(entry, "target_sim", None)
                if inner is not None:
                    target_sim = inner
                target_id = _safe_getattr(target_sim, "sim_id", None)
                if target_id is None:
                    target_id = _safe_getattr(target_sim, "id", None)
                try:
                    target_id = int(target_id)
                except (TypeError, ValueError):
                    target_id = 0

            depth = None
            if callable(depth_fn) and target_id:
                depth = _safe_call(depth_fn, target_id)
            if depth is None:
                inner_depth = _safe_getattr(entry, "get_relationship_depth", None)
                if callable(inner_depth):
                    depth = _safe_call(inner_depth)
            try:
                depth = float(depth)
            except (TypeError, ValueError):
                depth = 0.0

            if target_sim is not None:
                target_name = _safe_getattr(target_sim, "full_name", None)
                target_name = _as_str(target_name) if target_name is not None else _as_str(target_sim)
            else:
                target_name = ""

            relationships.append({
                "target_id": target_id,
                "target_name": target_name,
                "depth": depth,
                "track": "",
            })
    except Exception:
        pass
    return relationships


def _get_sim_instance(sim_info):
    """Call ``sim_info.get_sim_instance()`` (may be None for off-zone Sims)."""
    getter = _safe_getattr(sim_info, "get_sim_instance", None)
    return _safe_call(getter) if callable(getter) else None


def _get_queue_size(sim_info) -> int:
    """Get interaction queue size."""
    try:
        sim_instance = _get_sim_instance(sim_info)
        if sim_instance is None:
            return 0
        queue = _safe_getattr(sim_instance, "queue", None)
        if queue is None:
            return 0
        return len(_safe_getattr(queue, "queue", []) or [])
    except Exception:
        return 0


def _get_location(sim_info) -> Dict[str, Any]:
    """Get location info."""
    loc = {}
    try:
        sim_instance = _get_sim_instance(sim_info)
        if sim_instance is not None:
            position = _safe_getattr(sim_instance, "position", None)
            if position is not None:
                loc["x"] = _safe_getattr(position, "x", 0.0)
                loc["y"] = _safe_getattr(position, "y", 0.0)
                loc["z"] = _safe_getattr(position, "z", 0.0)

            zone_id = _safe_getattr(sim_instance, "zone_id", None)
            if zone_id is not None:
                loc["zone_id"] = _as_str(zone_id)
    except Exception:
        pass
    return loc


def collect(sim_info=None) -> Dict[str, Any]:
    """
    Collect best-effort Sim context.
    If sim_info is None, uses the active Sim.
    Returns dict with collected data plus {"source": "native"}.
    Never raises.
    """
    context = {
        "source": "native",
        "sim_id": 0,
        "save_id": "",
        "full_name": "",
        "mood": "",
        "needs": {},
        "traits": [],
        "skills": {},
        "careers": [],
        "relationships": [],
        "queue_size": 0,
        "location": {},
        "clock": "",
        "funds": 0,
    }

    # Get sim_info if not provided
    if sim_info is None:
        sim_info = _get_active_sim_info()

    if sim_info is None:
        return context

    # Basic info (primitive-coerced so no game object leaks into the payload)
    try:
        context["sim_id"] = int(_safe_getattr(sim_info, "id", 0) or 0)
    except (TypeError, ValueError):
        context["sim_id"] = 0
    context["full_name"] = _as_str(_safe_getattr(sim_info, "full_name", ""))
    context["save_id"] = _get_save_id()

    # State
    context["mood"] = _get_mood(sim_info)
    context["needs"] = _get_needs(sim_info)
    context["traits"] = _get_traits(sim_info)
    context["skills"] = _get_skills(sim_info)
    context["careers"] = _get_careers(sim_info)
    context["relationships"] = _get_relationships(sim_info)
    context["queue_size"] = _get_queue_size(sim_info)
    context["location"] = _get_location(sim_info)
    context["clock"] = _get_time_string()
    context["funds"] = _get_funds(sim_info)

    return context