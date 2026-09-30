"""
Live autonomy probe (PLANO.md §15.7, F1).

``sw.probe`` is a permanent developer cheat: for the active/selected Sim it dumps
a JSON snapshot of the autonomy surface — the autonomy service/component, the
``si_state``, commodity (motive) values, buffs/traits, whims and relationship
tracks — to ``sensewright_output.log``. It also tries to import every module from
the §15.7 module map and records which ones exist in the current patch plus their
public names, which is the raw material for the R1 levers catalog
(``docs/ts4_internals.md``).

Everything is guarded (never raises, never blocks) and stays a no-op outside the
game. Pure helpers (``_describe``, ``_prune``, ``render_probe``) are testable
without The Sims 4.
"""


import importlib
import json
from typing import Any, Dict, List, Optional

from .debug_log import debug_log, log_exception

# ── §15.7 module map: the packages the R1 catalog is read from ──────────
MODULE_MAP: Dict[str, List[str]] = {
    "autonomy": [
        "autonomy.autonomy_service",
        "autonomy.autonomy_request",
        "autonomy.autonomy_component",
        "autonomy.autonomy_modifier",
        "autonomy.autonomy_modifier_enums",
        "autonomy.autonomy_modes",
        "autonomy.autonomy_preference",
        "autonomy.autonomy_object_preference_tracker",
        "autonomy.parameterized_autonomy_request_info",
        "autonomy.distance_based_scoring_modifier",
    ],
    "interactions": [
        "interactions.interaction_queue",
        "interactions.si_state",
        "interactions.aop",
        "interactions.choices",
        "interactions.context",
        "interactions.base.super_interaction",
        "interactions.base.interaction",
        "interactions.social.social_super_interaction",
    ],
    "modifiers": [
        "game_effect_modifier.affordance_reference_scoring_modifier",
        "game_effect_modifier.affordance_filter_modifier",
        "game_effect_modifier.mood_effect_modifier",
        "game_effect_modifier.continuous_statistic_modifier",
        "game_effect_modifier.relationship_track_decay_modifier",
        "game_effect_modifier.statistic_static_modifier",
    ],
    "traits": [
        "traits.traits",
        "traits.trait_commands",
        "traits.preference",
        "traits.gameplay_object_preference",
        "statistics.trait_statistic",
        "statistics.trait_statistic_tracker",
    ],
    "buffs": [
        "buffs.buff",
        "buffs.memory",
        "statistics.mood",
        "statistics.commodity",
        "statistics.commodity_tracker",
    ],
    "whims": [
        "whims.whims_tracker",
        "whims.whim",
        "whims.whim_set",
        "whims.whim_modifiers",
    ],
    "relationships": [
        "relationships.relationship_track",
        "relationships.sentiment_track",
        "relationships.sentiment_tracker",
        "relationships.relationship_bit",
        "relationships.compatibility",
        "relationships.global_relationship_tuning",
    ],
    "debug_commands": [
        "server_commands.autonomy_commands",
        "server_commands.interaction_commands",
        "server_commands.relationship_commands",
        "server_commands.whim_commands",
        "server_commands.sim_commands",
        "server_commands.statistic_commands",
    ],
}

# Attribute names probed on the Sim, in priority order.
_AUTONOMY_COMPONENT_ATTRS = ("autonomy_component", "autonomy", "_autonomy_component")
_SI_STATE_ATTRS = ("si_state", "si_state_machine", "_si_state")
_WHIM_TRACKER_ATTRS = ("whim_tracker", "_whim_tracker")
_COMMODITY_TRACKER_ATTRS = ("commodity_tracker", "_commodity_tracker", "statistic_tracker")


# ── pure helpers (testable outside the game) ────────────────────────────

def _type_name(obj: Any) -> str:
    try:
        return type(obj).__name__
    except Exception:
        return "?"


def _describe(obj: Any, limit: int = 80) -> Optional[Dict[str, Any]]:
    """Summarize an object as ``{type, attrs, methods}`` (names only).

    Keeps the probe small and JSON-safe: values are never stringified wholesale
    (a tracker ``repr`` can be enormous); only member names are recorded.
    """
    if obj is None:
        return None
    attrs: List[str] = []
    methods: List[str] = []
    try:
        names = dir(obj)
    except Exception:
        names = []
    for name in names:
        if name.startswith("__"):
            continue
        try:
            member = getattr(obj, name)
        except Exception as exc:
            log_exception("probe._describe", exc)
            continue
        if callable(member):
            methods.append(name)
        else:
            attrs.append(name)
    return {
        "type": _type_name(obj),
        "attrs": attrs[:limit],
        "methods": methods[:limit],
        "attr_count": len(attrs),
        "method_count": len(methods),
    }


_BUFF_KEYWORDS = ("buff", "mood", "moodlet", "emotion")


def _find_members(obj: Any, keywords: Any, limit: int = 120) -> List[str]:
    """List member names of ``obj`` containing any of ``keywords`` (case-insensitive).

    Used to discover the buff/mood API on the Sim in the current patch, where
    ``sim_info.buff_component`` is absent.
    """
    if obj is None:
        return []
    try:
        names = dir(obj)
    except Exception as exc:
        log_exception("probe._find_members", exc)
        names = []
    keys = tuple(k.lower() for k in keywords)
    found = [name for name in names if any(key in name.lower() for key in keys)]
    return sorted(found)[:limit]


def _prune(value: Any, depth: int = 3) -> Any:
    """Reduce a value to JSON primitives, dropping anything unknown."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        try:
            if value != value or value in (float("inf"), float("-inf")):
                return None
        except Exception:
            return None
        return value
    if depth <= 0:
        return _type_name(value)
    if isinstance(value, dict):
        return {str(k): _prune(v, depth - 1) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_prune(v, depth - 1) for v in list(value)[:50]]
    return _type_name(value)


def _attr(obj: Any, names: Any, default=None):
    for name in names:
        try:
            value = getattr(obj, name, None)
        except Exception as exc:
            log_exception("probe._attr({})".format(name), exc)
            value = None
        if value is not None:
            return value
    return default


def _call(obj: Any, name: str):
    try:
        member = getattr(obj, name, None)
        if callable(member):
            return member()
    except Exception as exc:
        log_exception("probe._call({})".format(name), exc)
    return None


def _iter_values(value: Any, limit: int = 60) -> List[Any]:
    if value is None:
        return []
    try:
        return list(value)[:limit]
    except TypeError:
        return []


def _name_of(value: Any) -> str:
    for attr in ("__name__", "name", "tuning_name", "buff_name"):
        try:
            name = getattr(value, attr, None)
        except Exception as exc:
            log_exception("probe._name_of({})".format(attr), exc)
            name = None
        if isinstance(name, str) and name:
            return name
    try:
        return type(value).__name__
    except Exception:
        return "?"


# ── game-side collection (guarded) ──────────────────────────────────────

def _probe_modules(module_map: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """Import each §15.7 module and record its public names (F2 raw material)."""
    result: Dict[str, Any] = {}
    for area, modules in (module_map or MODULE_MAP).items():
        area_result: Dict[str, Any] = {}
        for module_name in modules:
            try:
                module = importlib.import_module(module_name)
                public = sorted(n for n in dir(module) if not n.startswith("_"))
                area_result[module_name] = {"importable": True, "names": public[:80]}
            except Exception as exc:
                area_result[module_name] = {
                    "importable": False,
                    "error": type(exc).__name__,
                }
        result[area] = area_result
    return result


def _probe_commodities(sim_info) -> Dict[str, Any]:
    """Best-effort commodity (motive) values from the tracker."""
    from . import sim_context

    tracker = _attr(sim_info, _COMMODITY_TRACKER_ATTRS)
    section = {"tracker": _describe(tracker), "values": {}}
    if tracker is None:
        return section
    commodities = _call(tracker, "get_all_commodities")
    if not commodities:
        commodities = getattr(tracker, "_commodities", None)
    for commodity in _iter_values(commodities):
        name = _name_of(commodity)
        value = _call(commodity, "get_value")
        if value is None:
            value = getattr(commodity, "value", None)
        if value is not None:
            section["values"][name] = _prune(value)
    try:
        section["needs"] = sim_context._get_needs(sim_info)
    except Exception as exc:
        log_exception("probe._probe_commodities.needs", exc)
        section["needs"] = {}
    return section


def _probe_whims(sim_info) -> Dict[str, Any]:
    tracker = _attr(sim_info, _WHIM_TRACKER_ATTRS)
    section = {"tracker": _describe(tracker)}
    if tracker is None:
        return section
    whims = None
    for name in ("get_active_whims", "get_whims", "active_whims", "whims"):
        member = getattr(tracker, name, None)
        whims = member() if callable(member) else member
        if whims:
            break
    section["active"] = [_name_of(whim) for whim in _iter_values(whims)]
    return section


def _probe_relationships(sim_info) -> Dict[str, Any]:
    from . import sim_context

    tracker = _attr(sim_info, ("relationship_tracker",))
    section = {"tracker": _describe(tracker)}
    try:
        section["targets"] = sim_context._get_relationships(sim_info)[:30]
    except Exception as exc:
        log_exception("probe._probe_relationships", exc)
        section["targets"] = []
    return section


def collect_probe(sim_info=None, *, include_modules: bool = True) -> Dict[str, Any]:
    """Build a JSON-safe snapshot of the Sim's autonomy surface. Never raises."""
    from . import sim_context

    data: Dict[str, Any] = {"sim": {}, "sections": {}}
    if sim_info is None:
        try:
            sim_info = sim_context._get_active_sim_info()
        except Exception as exc:
            log_exception("probe.collect_probe.active_sim", exc)
            sim_info = None

    if sim_info is None:
        data["sim"] = {"available": False}
        if include_modules:
            data["modules"] = _probe_modules()
        return data

    sim_instance = None
    try:
        sim_instance = sim_context._get_sim_instance(sim_info)
    except Exception as exc:
        log_exception("probe.collect_probe.sim_instance", exc)
        sim_instance = None

    base: Dict[str, Any] = {"available": True}
    for key, getter in (
        ("sim_id", lambda: getattr(sim_info, "id", None)),
        ("full_name", lambda: str(getattr(sim_info, "full_name", "") or "")),
        ("save_id", sim_context._get_save_id),
        ("mood", lambda: sim_context._get_mood(sim_info)),
        ("traits", lambda: sim_context._get_traits(sim_info)[:30]),
        ("skills", lambda: sim_context._get_skills(sim_info)),
        ("careers", lambda: sim_context._get_careers(sim_info)[:5]),
    ):
        try:
            base[key] = _prune(getter())
        except Exception as exc:
            log_exception("probe.collect_probe.sim.{}".format(key), exc)
            base[key] = None
    data["sim"] = base

    sections = data["sections"]
    # Autonomy: the service (global) and the component (per Sim).
    try:
        services = sim_context._get_services()
    except Exception as exc:
        log_exception("probe.collect_probe.services", exc)
        services = None
    autonomy_service = None
    for getter_name in ("autonomy_service", "get_autonomy_service"):
        getter = getattr(services, getter_name, None) if services is not None else None
        autonomy_service = getter() if callable(getter) else getter
        if autonomy_service is not None:
            break
    sections["autonomy_service"] = _describe(autonomy_service)

    autonomy_component = _attr(sim_instance, _AUTONOMY_COMPONENT_ATTRS)
    if autonomy_component is None:
        autonomy_component = _attr(sim_info, _AUTONOMY_COMPONENT_ATTRS)
    sections["autonomy_component"] = _describe(autonomy_component)

    si_state = _attr(sim_instance, _SI_STATE_ATTRS)
    sections["si_state"] = _describe(si_state)

    sections["commodities"] = _probe_commodities(sim_info)
    sections["whims"] = _probe_whims(sim_info)
    sections["relationships"] = _probe_relationships(sim_info)

    try:
        from . import state_collector

        sections["buffs"] = state_collector._buff_names_of(sim_info)
    except Exception as exc:
        log_exception("probe.collect_probe.buffs", exc)
        sections["buffs"] = []
    sections["trait_tracker"] = _describe(_attr(sim_info, ("trait_tracker",)))
    # Confirmed: buffs live on ``SimInfo.Buffs`` (a BuffComponent) -> ``_active_buffs``.
    sections["buff_component"] = _describe(
        _attr(sim_info, ("Buffs", "buff_component"))
    ) or _describe(_attr(sim_instance, ("Buffs", "buff_component")))
    sections["sim_instance"] = _describe(sim_instance)
    sections["sim_info.buff_members"] = _find_members(sim_info, _BUFF_KEYWORDS)
    sections["sim_instance.buff_members"] = _find_members(sim_instance, _BUFF_KEYWORDS)

    queue = _attr(sim_instance, ("queue",))
    queue_desc = _describe(queue) or {}
    queue_desc.setdefault("current_interaction", None)
    if queue is not None:
        try:
            current = getattr(queue, "get_current_interaction", None)
            current = current() if callable(current) else getattr(queue, "current_interaction", None)
            queue_desc["current_interaction"] = _name_of(current) if current else None
        except Exception as exc:
            log_exception("probe.collect_probe.queue", exc)
    sections["queue"] = queue_desc

    # Stack base introspection: which libraries resolved, the Lot 51 event bus
    # state and whether the custom service registered (live-validation aid).
    try:
        from . import events as events_module
        from . import integrations as integrations_module
        from . import stack_service

        sections["stack"] = {
            "summary": integrations_module.stack_summary(),
            "lot51": events_module.lot51_status(),
            "service_registered": stack_service.registered(),
        }
    except Exception as exc:
        log_exception("probe.collect_probe.stack", exc)
        sections["stack"] = {}

    if include_modules:
        data["modules"] = _probe_modules()
    return data


# ── rendering + command entry point ─────────────────────────────────────

def render_probe(data: Dict[str, Any], header: str = "sw.probe") -> str:
    """Render the probe dict as indented JSON for the debug log.

    Uses the shared payload sanitizer instead of ``default=str`` so leaked game
    objects are dropped (not masked as huge repr strings) (L6).
    """
    try:
        from .http_client import _sanitize_payload

        body = json.dumps(_sanitize_payload(data), ensure_ascii=False, indent=2)
    except Exception as exc:
        log_exception("probe.render", exc)
        body = "{}"
    return "=== {} ===\n{}".format(header, body)


def dump_probe(sim_info=None, *, include_modules: bool = True, header: str = "sw.probe") -> Dict[str, Any]:
    """Collect the probe and append it to ``sensewright_output.log``. Never raises."""
    try:
        data = collect_probe(sim_info, include_modules=include_modules)
    except Exception as exc:
        log_exception("probe.collect", exc)
        data = {"error": type(exc).__name__}
    try:
        for line in render_probe(data, header=header).splitlines():
            debug_log(line)
    except Exception as exc:
        log_exception("probe.write", exc)
    return data
