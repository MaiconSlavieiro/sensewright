"""
Event-driven state collection and event ingestion for Sensewright.

Samples the active Sim on a recurring game-clock alarm and forwards compact
game events to the sidecar. All game access is guarded and every send is
best-effort: public functions never block and never raise.
"""


import time
from typing import Any, Dict, List, Optional

from . import chat_ui, events, god_ui, http_client, hud, i18n, sim_context, tool_executor
from .debug_log import debug_log, log_exception, validation_log


# Default sampling interval in Sim minutes.
DEFAULT_INTERVAL_MINUTES = 30.0

# Zone-pulse cadence (PLANO §14.2): the 30-minute snapshot becomes a ~10
# sim-minute pulse that samples the zone and nearby instanced Sims. The pending
# directives are pulled on the same cadence.
AUTONOMY_INTERVAL_MINUTES = 10.0
DIRECTIVE_PULL_INTERVAL_MINUTES = 10.0

# God orchestration tick cadence (PLANO §8.3, Phase 5c). The mod polls the
# sidecar for one directive batch on a slow wall-clock cadence and executes it;
# the orchestrator enforces its own (>= 30 s) minimum interval, so this is only
# a poll rate and never the real limiter.
GOD_TICK_INTERVAL_SECONDS = 60.0

# Safety net: also fire a pulse/pull off gameplay events (throttled by wall
# clock). The game-clock alarms pause with the game; events only fire during
# active play, so this guarantees the agency loop runs while the player plays.
PULSE_MIN_INTERVAL_SECONDS = 8.0

# Autonomy reported for sampled Sims (the per-Sim level lives in the sidecar).
DEFAULT_AUTONOMY = "semi"

# Exact buff/moodlet tuning names that mean the Sim is asleep. Matching whole
# identifiers avoids false positives from unrelated buffs such as
# "Not sleeping well" or "Dreaming of sleeping" (code review item 4).
_SLEEP_BUFF_IDS = frozenset((
    "sleeping",
    "asleep",
    "buff_sleeping",
    "buff_asleep",
    "moodlet_sleeping",
    "moodlet_sleeping_buff",
))

# Importance assigned to each forwarded event type.
IMPORTANCE_SNAPSHOT = 1.0
IMPORTANCE_ZONE_LOAD = 1.5
IMPORTANCE_RELATIONSHIP = 1.2
IMPORTANCE_SOCIAL = 0.8
IMPORTANCE_BUFF = 0.7
IMPORTANCE_HOUSEHOLD = 1.0


def _safe_getattr(obj: Any, attr: str, default=None):
    """Safely get an attribute, logging the real exception when it fails."""
    try:
        return getattr(obj, attr, default)
    except Exception as exc:
        log_exception("state_collector._safe_getattr({!r})".format(attr), exc)
        return default


def _safe_call(func, *args, **kwargs):
    """Safely call a function, logging the real exception when it fails."""
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        log_exception("state_collector._safe_call({!r})".format(getattr(func, "__name__", func)), exc)
        return None


def _name_of(value: Any) -> str:
    """Best-effort human readable name for a game object."""
    if value is None:
        return ""
    for attr in ("__name__", "name"):
        name = _safe_getattr(value, attr, None)
        if isinstance(name, str) and name:
            return name
    try:
        return str(value)
    except Exception:
        return ""


def _first_attr(values, names):
    """Return the first non-None attribute found in any of the given values."""
    for value in values:
        if value is None:
            continue
        for name in names:
            found = _safe_getattr(value, name, None)
            if found is not None:
                return found
    return None


def _current_lang() -> str:
    """Current UI language for outgoing events (retries game detection)."""
    try:
        i18n.ensure_locale()
    except Exception:
        pass
    try:
        lang = i18n.current_locale()
        if lang:
            return lang
    except Exception:
        pass
    return "en"


def _build_sim_ref(context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the sim reference from a collected context."""
    context = context or {}
    try:
        sim_id = int(context.get("sim_id", 0) or 0)
    except (TypeError, ValueError):
        sim_id = 0
    save_id = context.get("save_id", "")
    if not isinstance(save_id, str):
        save_id = str(save_id)
    return {
        "player_id": "local",
        "save_id": save_id,
        "sim_id": sim_id,
    }


def _active_sim_ref() -> Dict[str, Any]:
    """Lightweight sim reference for the active Sim (used by census sends)."""
    sim_id = 0
    save_id = ""
    try:
        sim_info = sim_context._get_active_sim_info()
    except Exception:
        sim_info = None
    if sim_info is not None:
        try:
            sim_id = int(_safe_getattr(sim_info, "id", 0) or 0)
        except (TypeError, ValueError):
            sim_id = 0
    try:
        save_id = sim_context._get_save_id() or ""
    except Exception:
        save_id = ""
    if not isinstance(save_id, str):
        save_id = str(save_id)
    return {
        "player_id": "local",
        "save_id": save_id,
        "sim_id": sim_id,
    }


# --- census ---

def _get_sim_info_manager():
    """Get the SimInfoManager (guarded)."""
    try:
        services = sim_context._get_services()
    except Exception:
        services = None
    if services is None:
        return None
    getter = _safe_getattr(services, "sim_info_manager", None)
    if getter is None:
        return None
    return _safe_call(getter)


def _iter_sim_infos(manager=None):
    """Iterate every known SimInfo, trying the common manager shapes."""
    if manager is None:
        manager = _get_sim_info_manager()
    if manager is None:
        return []

    for attr in ("get_all", "values", "all_sims", "sim_infos"):
        candidate = _safe_getattr(manager, attr, None)
        if candidate is None:
            continue
        result = _safe_call(candidate) if callable(candidate) else candidate
        if result is None:
            continue
        try:
            return list(result)
        except Exception:
            continue

    try:
        return list(manager.values())
    except Exception:
        pass
    try:
        return list(manager)
    except Exception:
        return []


def _household_of(sim_info):
    """Return the household object of a SimInfo, if any."""
    return _safe_getattr(sim_info, "household", None)


def _household_id_of(sim_info) -> Optional[int]:
    """Return the household id of a SimInfo as int, or None."""
    household = _household_of(sim_info)
    if household is None:
        return None
    household_id = _safe_getattr(household, "id", None)
    if household_id is None:
        return None
    try:
        return int(household_id)
    except (TypeError, ValueError):
        return None


def _full_name_of(sim_info) -> str:
    """Best-effort full name for a SimInfo."""
    name = _safe_getattr(sim_info, "full_name", None)
    if name is None:
        return ""
    if isinstance(name, str):
        return name
    tuning_name = _safe_getattr(name, "__name__", None)
    if isinstance(tuning_name, str) and tuning_name:
        return tuning_name
    try:
        return str(name)
    except Exception:
        return ""


def _enum_name(value: Any) -> str:
    """Return a readable name for a string/enum value."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return _name_of(value)


def _age_of(sim_info) -> str:
    """Best-effort age/life-stage string."""
    for attr in ("age", "age_state", "life_stage"):
        value = _safe_getattr(sim_info, attr, None)
        if value is None:
            continue
        name = _enum_name(value)
        if name:
            return name
    return ""


def _gender_of(sim_info) -> str:
    """Best-effort gender string."""
    for attr in ("gender", "gender_type"):
        value = _safe_getattr(sim_info, attr, None)
        if value is None:
            continue
        name = _enum_name(value)
        if name:
            return name
    return ""


def _career_name_of(sim_info) -> str:
    """First real career name reported by sim_context, or empty.

    ``sim_context._get_careers`` already resolves the tuning name at the source
    (``_career_display_name``), so its ``name`` is primitive and non-numeric;
    numeric ids are dropped so the caller never shows a raw id.
    """
    try:
        careers = sim_context._get_careers(sim_info)
    except Exception:
        careers = []
    for career in careers or []:
        name = career.get("name") if isinstance(career, dict) else _name_of(career)
        if isinstance(name, str) and name and not name.isdigit():
            return name
    return ""


def _traits_of(sim_info) -> List[str]:
    """Trait names reported by sim_context."""
    try:
        traits = sim_context._get_traits(sim_info)
    except Exception:
        traits = []
    if not traits:
        return []
    try:
        return list(traits)
    except Exception:
        return []


def _skills_of(sim_info) -> Dict[str, Any]:
    """Skill levels reported by sim_context."""
    try:
        skills = sim_context._get_skills(sim_info)
    except Exception:
        skills = {}
    return skills if isinstance(skills, dict) else {}


def _relationships_of(sim_info) -> List[Dict[str, Any]]:
    """Compact relationship list: [{"target_id": int, "depth": float}]."""
    result = []
    try:
        relationships = sim_context._get_relationships(sim_info)
    except Exception:
        relationships = []
    for relationship in relationships or []:
        if not isinstance(relationship, dict):
            continue
        try:
            target_id = int(relationship.get("target_id"))
        except (TypeError, ValueError):
            continue
        try:
            depth = float(relationship.get("depth", 0.0) or 0.0)
        except (TypeError, ValueError):
            depth = 0.0
        result.append({"target_id": target_id, "depth": depth})
    return result


def _kinship_of(sim_info) -> List[Dict[str, Any]]:
    """Native family relations: [{"relation", "target_id", "name"}].

    Compact/primitive-only so no game object leaks into the census payload.
    """
    result: List[Dict[str, Any]] = []
    try:
        kinship = sim_context._get_kinship(sim_info)
    except Exception:
        kinship = []
    for relation in kinship or []:
        if not isinstance(relation, dict):
            continue
        try:
            target_id = int(relation.get("target_id"))
        except (TypeError, ValueError):
            continue
        label = relation.get("relation")
        name = relation.get("name")
        result.append({
            "relation": label if isinstance(label, str) else str(label or ""),
            "target_id": target_id,
            "name": name if isinstance(name, str) else str(name or ""),
        })
    return result


def _is_player_of(sim_info, player_household_id: Optional[int]) -> bool:
    """Whether a SimInfo belongs to the played household."""
    for attr in ("is_selectable", "is_player", "is_played"):
        value = _safe_getattr(sim_info, attr, None)
        if value is not None:
            return bool(value)
    household_id = _household_id_of(sim_info)
    return household_id is not None and household_id == player_household_id


# --- v0.2: zone pulse sampling (PLANO §14.2) ---

def _buff_name(buff: Any) -> str:
    """Best-effort name for a buff/moodlet object or tuning key."""
    for attr in ("__name__", "name", "buff_name"):
        name = _safe_getattr(buff, attr, None)
        if isinstance(name, str) and name:
            return name
    buff_type = _safe_getattr(buff, "buff_type", None)
    if buff_type is not None:
        return _name_of(buff_type)
    return _name_of(buff)


def _buff_type_name(buff: Any) -> str:
    """Exact tuning id of a buff (``Buff.buff_type.__name__``), best-effort.

    Returns only the exact tuning identifier — never a localized display name.
    ``buff_type.__name__`` is preferred, then the nested
    ``buff_type.buff_type.__name__``, then ``buff.__name__`` when the value is
    itself the tuning. ``_buff_name`` is deliberately **not** used because it may
    fall back to a localized ``name`` (code review item M5).
    """
    if buff is None:
        return ""
    buff_type = _safe_getattr(buff, "buff_type", None) or _safe_getattr(buff, "_buff_type", None)
    candidates = [buff_type]
    if buff_type is not None:
        candidates.append(_safe_getattr(buff_type, "buff_type", None))
    candidates.append(buff)
    for candidate in candidates:
        name = _safe_getattr(candidate, "__name__", None)
        if isinstance(name, str) and name:
            return name
    return ""


def _buff_names_of(sim_info) -> List[str]:
    """List active buff/moodlet tuning ids for a SimInfo.

    Confirmed against the shipped scripts (``sims/sim_info.py``): the buffs live
    on ``SimInfo.Buffs`` (a ``BuffComponent``), whose active buffs are in
    ``_active_buffs`` (handle id -> ``Buff``); each ``Buff`` exposes
    ``buff_type`` (the tuning, whose ``__name__`` is e.g. ``buff_Sleeping``).
    """
    names: List[str] = []

    component = _safe_getattr(sim_info, "Buffs", None)
    if callable(component):  # property already evaluated; guard a method variant
        component = _safe_call(component)
    if component is None:
        try:
            sim_instance = sim_context._get_sim_instance(sim_info)
        except Exception:
            sim_instance = None
        component = _safe_getattr(sim_instance, "Buffs", None)

    if component is not None:
        active = _safe_getattr(component, "_active_buffs", None)
        if active is None:
            active = _safe_getattr(component, "buffs", None)
        entries: List[Any] = []
        if isinstance(active, dict):
            entries = list(active.values())
        elif active is not None:
            try:
                entries = list(active)
            except Exception:
                entries = []
        for entry in entries:
            buff = _safe_getattr(entry, "buff", entry)
            name = _buff_type_name(buff) or _buff_type_name(entry)
            if name:
                names.append(name)

    return names


def _is_sleeping(buff_names) -> bool:
    """True when a buff/moodlet name exactly matches a known sleep tuning id.

    Compares whole identifiers (case-insensitively, trimmed) rather than
    substrings, so buffs that merely mention sleep cannot produce a false
    positive. Pure helper (no game access) so the rule is trivially testable.
    """
    for name in buff_names or []:
        if not name:
            continue
        try:
            text = str(name).strip().lower()
        except Exception:
            continue
        if text in _SLEEP_BUFF_IDS:
            return True
    return False


def _get_sim_instance_of(sim_info):
    """Get the live Sim instance for a SimInfo (or None)."""
    getter = _safe_getattr(sim_info, "get_sim_instance", None)
    if getter is None:
        return None
    return _safe_call(getter)


def _iter_instanced_sim_infos(manager=None):
    """Best-effort list of SimInfos with a live instance, plus the active Sim."""
    if manager is None:
        manager = _get_sim_info_manager()

    result: List[Any] = []
    if manager is not None:
        for attr in ("get_instanced_sim_infos", "instanced_sim_infos",
                     "get_all_instanced_sim_infos"):
            candidate = _safe_getattr(manager, attr, None)
            if candidate is None:
                continue
            value = _safe_call(candidate) if callable(candidate) else candidate
            if value is None:
                continue
            try:
                items = list(value)
            except Exception:
                continue
            if items:
                result = items
                break

    if not result:
        for sim_info in _iter_sim_infos(manager):
            if _get_sim_instance_of(sim_info) is not None:
                result.append(sim_info)

    try:
        active = sim_context._get_active_sim_info()
    except Exception:
        active = None
    if active is not None:
        result.append(active)

    # De-duplicate by Sim id, preserving order.
    unique: List[Any] = []
    seen = set()
    for sim_info in result:
        key = _safe_getattr(sim_info, "id", None)
        if key is None:
            key = id(sim_info)
        if key in seen:
            continue
        seen.add(key)
        unique.append(sim_info)
    return unique


def _location_string_of(sim_info) -> str:
    """Compact location string for the wire ('x,y' or the zone id)."""
    try:
        location = sim_context._get_location(sim_info)
    except Exception:
        location = {}
    if not isinstance(location, dict) or not location:
        return ""
    x = location.get("x")
    y = location.get("y")
    if x is not None and y is not None:
        try:
            return "{:.1f},{:.1f}".format(float(x), float(y))
        except (TypeError, ValueError):
            pass
    zone_id = location.get("zone_id")
    return "" if zone_id is None else str(zone_id)


def _current_interaction_of(sim_info) -> str:
    """Best-effort name of the Sim's current interaction, or ''."""
    sim_instance = _get_sim_instance_of(sim_info)
    if sim_instance is None:
        return ""
    queue = _safe_getattr(sim_instance, "queue", None)
    if queue is None:
        return ""
    for attr in ("get_current_interaction", "current_interaction"):
        value = _safe_getattr(queue, attr, None)
        if value is None:
            continue
        result = _safe_call(value) if callable(value) else value
        if result is not None:
            return _name_of(result)
    return ""


def _zone_time_of_day() -> str:
    """Current game clock string (best effort)."""
    try:
        return sim_context._get_time_string() or ""
    except Exception:
        return ""


def _zone_id() -> str:
    """Current save/zone id (best effort)."""
    try:
        value = sim_context._get_save_id() or ""
    except Exception:
        value = ""
    return value if isinstance(value, str) else str(value)


def _lot_type() -> str:
    """Best-effort lot type for the loaded zone."""
    try:
        services = sim_context._get_services()
    except Exception:
        services = None
    if services is None:
        return ""
    zone_getter = _safe_getattr(services, "current_zone", None)
    zone = _safe_call(zone_getter) if zone_getter is not None else None
    if zone is None:
        return ""
    for attr in ("lot_type", "is_residential"):
        value = _safe_getattr(zone, attr, None)
        if isinstance(value, bool):
            return "residential" if value else "community"
        if value is not None:
            name = _enum_name(value)
            if name:
                return name
    lot = _safe_getattr(zone, "lot", None)
    if lot is not None:
        return _enum_name(_safe_getattr(lot, "lot_type", "")) or ""
    return ""


def _weather() -> str:
    """Best-effort current weather ('' when Seasons is absent)."""
    try:
        services = sim_context._get_services()
    except Exception:
        services = None
    if services is None:
        return ""
    for getter_name in ("weather_service", "get_weather_service"):
        getter = _safe_getattr(services, getter_name, None)
        service = _safe_call(getter) if callable(getter) else getter
        if service is None:
            continue
        for attr in ("current_weather", "weather", "weather_state"):
            value = _safe_getattr(service, attr, None)
            if value is not None:
                name = _enum_name(value)
                if name:
                    return name
    return ""


def _autonomy_sim_state(sim_info, player_household_id=None) -> Dict[str, Any]:
    """Build the ``AutonomySimState`` shape for a single Sim."""
    try:
        sim_id = int(_safe_getattr(sim_info, "id", 0) or 0)
    except (TypeError, ValueError):
        sim_id = 0

    try:
        mood = sim_context._get_mood(sim_info) or "neutral"
    except Exception:
        mood = "neutral"

    try:
        needs = sim_context._get_needs(sim_info)
    except Exception:
        needs = {}
    if not isinstance(needs, dict):
        needs = {}

    return {
        "sim_id": sim_id,
        "full_name": _full_name_of(sim_info),
        "household_id": _household_id_of(sim_info),
        "mood": mood,
        "needs": needs,
        "location": _location_string_of(sim_info),
        "current_interaction": _current_interaction_of(sim_info),
        "sleeping": _is_sleeping(_buff_names_of(sim_info)),
        "is_player": _is_player_of(sim_info, player_household_id),
        "autonomy": DEFAULT_AUTONOMY,
        "relationships": _relationships_of(sim_info),
    }


def sample_zone():
    """Sample the zone context plus the active/nearby instanced Sims.

    Returns ``(zone, sims)`` following the wire shapes. Never raises; a failure
    on one Sim is skipped so it cannot abort the pulse.
    """
    zone = {
        "time_of_day": _zone_time_of_day(),
        "lot_type": _lot_type(),
        "weather": _weather(),
        "zone_id": _zone_id(),
    }

    try:
        active = sim_context._get_active_sim_info()
    except Exception:
        active = None
    player_household_id = _household_id_of(active) if active is not None else None

    try:
        sim_infos = _iter_instanced_sim_infos()
    except Exception:
        sim_infos = []
    if active is not None and active not in sim_infos:
        sim_infos = list(sim_infos) + [active]

    sims: List[Dict[str, Any]] = []
    for sim_info in sim_infos:
        if _safe_getattr(sim_info, "id", None) is None:
            continue
        try:
            sims.append(_autonomy_sim_state(sim_info, player_household_id))
        except Exception:
            continue
    return zone, sims


# Last observed pulse size, for the debug HUD (never sent anywhere).
_LAST_PULSE_SIMS = {"value": 0}


def send_autonomy_tick(sim: Optional[Dict[str, Any]] = None):
    """Sample the zone and POST /v1/autonomy/tick. Never raises; None on failure."""
    try:
        zone, sims = sample_zone()
        if sim is None:
            sim = _active_sim_ref()
        _LAST_PULSE_SIMS["value"] = len(sims)
        validation_log(
            "pulse: {} sim(s) zone={} lot={}".format(
                len(sims), zone.get("zone_id"), zone.get("lot_type")
            )
        )
        result = http_client.autonomy_tick(sim, zone, sims, _current_lang())
        try:
            social = result.get("social") if isinstance(result, dict) else None
            if social:
                validation_log(
                    "social: {} dialogue pair(s) topic={}".format(
                        len(social),
                        [d.get("topic") for d in social if isinstance(d, dict)],
                    )
                )
        except Exception as exc:
            log_exception("state_collector.send_autonomy_tick(social)", exc)
        return result
    except (http_client.SidecarUnreachable, http_client.SidecarError):
        return None
    except Exception as exc:
        log_exception("state_collector.send_autonomy_tick", exc)
        return None


def _sidecar_state(tick_result, pull_result) -> str:
    """Classify sidecar reachability for the HUD: ``on`` / ``off`` / ``error``.

    ``off`` means the sidecar is unreachable; ``error`` means it answered a
    health probe but the tick/pull failed (so the UI shows a distinct warning
    instead of a false "down").
    """
    if isinstance(tick_result, dict) or isinstance(pull_result, dict):
        return "on"
    try:
        health = http_client.health()
        if isinstance(health, dict) and health.get("ok"):
            return "error"
    except Exception as exc:
        log_exception("state_collector._sidecar_state(health)", exc)
    return "off"


def pulse_and_pull() -> None:
    """Run one pulse + intent pull and feed the debug HUD. Never raises."""
    tick_result = None
    try:
        tick_result = send_autonomy_tick()
    except Exception as exc:
        log_exception("state_collector.pulse_and_pull(tick)", exc)
    pull_result = None
    try:
        pull_result = pull_and_execute_directives()
    except Exception as exc:
        log_exception("state_collector.pulse_and_pull(pull)", exc)
    try:
        maybe_god_tick()
    except Exception as exc:
        log_exception("state_collector.pulse_and_pull(god)", exc)
    try:
        hud.note_heartbeat(
            tick_result=tick_result,
            pull_result=pull_result,
            sims=_LAST_PULSE_SIMS["value"],
            sidecar_state=_sidecar_state(tick_result, pull_result),
        )
    except Exception as exc:
        log_exception("state_collector.pulse_and_pull(hud)", exc)


def _sim_info_by_id(sim_id) -> Optional[Any]:
    """Resolve a SimInfo by id (best-effort). Never raises."""
    try:
        import services  # type: ignore

        manager = services.sim_info_manager()
        if manager is not None and sim_id:
            return manager.get(int(sim_id))
    except Exception as exc:
        log_exception("state_collector._sim_info_by_id", exc)
    return None


def _show_autonomy_text(key: str, text: str, speaker_sim_info=None) -> None:
    """Best-effort speech notification attributed to the speaking Sim."""
    try:
        message = i18n.t(key, text=text)
    except Exception:
        message = text

    sim_info = speaker_sim_info
    if sim_info is None:
        try:
            sim_info = sim_context._get_active_sim_info()
        except Exception:
            sim_info = None

    # Attribute the line to the speaker (shows who is talking).
    try:
        name = _full_name_of(sim_info) if sim_info is not None else ""
    except Exception:
        name = ""
    if name:
        message = "{}: {}".format(name, message)

    try:
        if chat_ui.show_simple_notification(message, sim_info):
            return
    except Exception as exc:
        log_exception("state_collector._show_autonomy_text(notify)", exc)
    debug_log("[Sensewright] {}".format(message))


def pull_and_execute_directives(sim: Optional[Dict[str, Any]] = None):
    """Pull pending intents and translate them with the GameLever. Never raises.

    Each intent's ``narration``/``thought``/speech text is surfaced best-effort,
    then the intent is translated by ``tool_executor.execute_intent`` (which also
    handles the ``command`` escape hatch and posts the result back to the sidecar).
    """
    save_id = ""
    try:
        save_id = sim_context._get_save_id() or ""
    except Exception:
        save_id = ""
    if not isinstance(save_id, str):
        save_id = str(save_id)

    response = _pull_intents(save_id)
    if not isinstance(response, dict):
        return response

    intents = response.get("intents") or []
    if not isinstance(intents, list):
        intents = []

    validation_log("pull: {} intent(s) for save={}".format(len(intents), save_id))
    for intent in intents:
        if not isinstance(intent, dict):
            continue
        narration = intent.get("narration")
        if narration:
            _show_autonomy_text("notify.autonomy.directive", narration)
        thought = intent.get("thought")
        if thought:
            _show_autonomy_text("notify.autonomy.thought", thought)
        try:
            result = tool_executor.execute_intent(intent)
        except Exception as exc:
            log_exception("pull_and_execute(intent)", exc)
            result = {"ok": False, "error": "execution_failed"}
        validation_log(
            "intent id={} kind={} name={} sim={} -> ok={} err={}".format(
                intent.get("id", ""),
                intent.get("kind", ""),
                intent.get("name", ""),
                intent.get("sim_id"),
                (result or {}).get("ok") if isinstance(result, dict) else None,
                (result or {}).get("error") if isinstance(result, dict) else None,
            )
        )
        try:
            hud.note_intent(intent, result)
        except Exception as exc:
            log_exception("state_collector.pull_and_execute(hud)", exc)
        # A "speak" intent surfaces its line as a speech notification, attributed
        # to the speaking Sim (name + native owner portrait).
        if isinstance(result, dict):
            text = result.get("text")
            if isinstance(text, str) and text.strip():
                _show_autonomy_text(
                    "notify.social.speech", text,
                    _sim_info_by_id(intent.get("sim_id")),
                )
    return response


def _pull_intents(save_id: str):
    """Pull intents from the v0.3 endpoint, falling back to the v0.2 alias.

    A 404 (older sidecar without ``/v1/autonomy/intents``) transparently falls
    back to ``/v1/autonomy/directives``; those items are command intents and are
    executed through the GameLever escape hatch.
    """
    try:
        return http_client.get_intents(save_id, player_id="local")
    except http_client.SidecarError as exc:
        if getattr(exc, "status", None) != 404:
            return None
        try:
            legacy = http_client.get_directives(save_id, player_id="local")
        except Exception as exc:
            log_exception("state_collector._pull_intents(legacy)", exc)
            return None
        if isinstance(legacy, dict):
            return {"ok": legacy.get("ok", True), "intents": legacy.get("directives") or []}
        return None
    except http_client.SidecarUnreachable:
        return None
    except Exception as exc:
        log_exception("state_collector._pull_intents", exc)
        return None


# --- God orchestration (Phase 5c) ---

# Last God tick bookkeeping (wall-clock throttled; never sent anywhere).
_GOD_TICK = {"last": 0.0, "count": 0}


def _show_narration(text: str) -> None:
    """Surface a God narration as a notification (the narrator's voice)."""
    if not text:
        return
    try:
        message = i18n.t("notify.god.directive", text=text)
    except Exception:
        message = text
    try:
        if chat_ui.show_simple_notification(message):
            return
    except Exception as exc:
        log_exception("state_collector._show_narration", exc)
    debug_log("[Sensewright] {}".format(message))


def execute_god_directives(directives: Any) -> List[Any]:
    """Execute the directives from one God tick. Never raises.

    Each directive may carry a ``tool_call`` (a real game tool the standard
    executor runs and whose result it posts back) plus a ``narration`` surfaced
    as a narrator notification. World/knowledge events with no ``tool_call``
    stay notification-only. Returns the per-directive execution results.
    """
    if not isinstance(directives, list):
        return []

    results: List[Any] = []
    for directive in directives:
        if not isinstance(directive, dict):
            continue

        narration = directive.get("narration")
        if narration:
            _show_narration(narration)

        tool_call = directive.get("tool_call")
        result: Any = None
        if isinstance(tool_call, dict) and tool_call.get("name"):
            try:
                result = tool_executor.execute(tool_call)
            except Exception as exc:
                log_exception("state_collector.execute_god_directives", exc)
                result = {"ok": False, "error": "execution_failed"}

        validation_log(
            "god: directive id={} type={} sim={} tool={} -> ok={}".format(
                directive.get("id", ""),
                directive.get("type", ""),
                directive.get("target_sim"),
                tool_call.get("name") if isinstance(tool_call, dict) else "",
                result.get("ok") if isinstance(result, dict) else None,
            )
        )
        results.append(result)
    return results


def maybe_god_tick(force: bool = False):
    """Run one God-orchestration tick on a slow cadence. Never raises.

    Posts ``/v1/god/tick`` and executes the returned directives. Throttled by
    ``GOD_TICK_INTERVAL_SECONDS`` unless ``force``. Returns the response dict,
    or ``None`` when throttled or when the sidecar is unreachable.
    """
    now = time.monotonic()
    if not force and (now - _GOD_TICK["last"]) < GOD_TICK_INTERVAL_SECONDS:
        return None
    _GOD_TICK["last"] = now

    try:
        sim = _active_sim_ref()
    except Exception:
        sim = None
    if not isinstance(sim, dict):
        sim = {"player_id": "local", "save_id": "unknown", "sim_id": 0}

    try:
        time_of_day = _zone_time_of_day()
    except Exception:
        time_of_day = "unknown"
    try:
        lot_type = _lot_type()
    except Exception:
        lot_type = "residential"

    try:
        response = http_client.god_tick(
            sim,
            time_of_day or "unknown",
            lot_type or "residential",
            _current_lang(),
        )
    except (http_client.SidecarUnreachable, http_client.SidecarError):
        return None
    except Exception as exc:
        log_exception("state_collector.maybe_god_tick", exc)
        return None

    directives = response.get("directives") if isinstance(response, dict) else None
    if directives:
        preset = response.get("preset", "") if isinstance(response, dict) else ""
        validation_log(
            "god-tick: {} directive(s) preset={}".format(len(directives), preset)
        )
        execute_god_directives(directives)
    _GOD_TICK["count"] = len(directives) if isinstance(directives, list) else 0
    return response


def build_census(scope: str = "active_zone"):
    """
    Build the census for the given scope.

    ``active_zone`` (default) reads only the **instanced** Sims of the loaded
    zone (plus the active Sim); ``full_save`` reads every Sim in the save. The
    zone scope keeps the payload and the seat pool small (the God still covers
    unplayed Sims). Returns ``(sims, households)`` following the wire shapes:
    sim = {sim_id, full_name, household_id, traits, age, gender, career,
           skills, relationships, kinship, is_player}
    household = {household_id, name, members, funds}
    Never raises; returns ``([], [])`` outside the game.
    """
    sims: List[Dict[str, Any]] = []
    households: Dict[int, Dict[str, Any]] = {}

    player_household_id = None
    try:
        active = sim_context._get_active_sim_info()
    except Exception:
        active = None
    if active is not None:
        player_household_id = _household_id_of(active)

    if scope == "full_save":
        sim_infos = _iter_sim_infos()
    else:
        sim_infos = _iter_instanced_sim_infos()

    for sim_info in sim_infos:
        try:
            sim_id = int(_safe_getattr(sim_info, "id", None))
        except (TypeError, ValueError):
            continue

        household_id = _household_id_of(sim_info)
        sims.append({
            "sim_id": sim_id,
            "full_name": _full_name_of(sim_info),
            "household_id": household_id,
            "traits": _traits_of(sim_info),
            "age": _age_of(sim_info),
            "gender": _gender_of(sim_info),
            "career": _career_name_of(sim_info),
            "skills": _skills_of(sim_info),
            "relationships": _relationships_of(sim_info),
            "kinship": _kinship_of(sim_info),
            "is_player": _is_player_of(sim_info, player_household_id),
        })

        if household_id is None:
            continue
        bucket = households.get(household_id)
        if bucket is None:
            household = _household_of(sim_info)
            name = _safe_getattr(household, "name", "") if household is not None else ""
            if not isinstance(name, str):
                name = _name_of(name)
            try:
                funds = int(_safe_getattr(household, "funds", 0) or 0)
            except (TypeError, ValueError):
                funds = 0
            bucket = {
                "household_id": household_id,
                "name": name,
                "members": [],
                "funds": funds,
            }
            households[household_id] = bucket
        bucket["members"].append(sim_id)

    return sims, list(households.values())


def send_census(sim: Optional[Dict[str, Any]] = None,
                sims: Optional[List[Dict[str, Any]]] = None,
                households: Optional[List[Dict[str, Any]]] = None,
                scope: str = "active_zone", lang: Optional[str] = None):
    """Best-effort POST /v1/census. Never raises; returns None on failure."""
    try:
        if sims is None or households is None:
            built_sims, built_households = build_census(scope)
            if sims is None:
                sims = built_sims
            if households is None:
                households = built_households
        if sim is None:
            sim = _active_sim_ref()
        if lang is None:
            lang = _current_lang()
        validation_log(
            "census: {} sim(s), {} household(s) scope={}".format(
                len(sims or []), len(households or []), scope
            )
        )
        return http_client.send_census(sim, sims, households, scope=scope, lang=lang)
    except (http_client.SidecarUnreachable, http_client.SidecarError):
        return None
    except Exception as exc:
        log_exception("state_collector.send_census", exc)
        return None


# The neighborhood (full-save) scan is heavier than the active-zone pulse, so it
# runs once per session automatically (or on demand via ``sw.god scan``).
_NEIGHBORHOOD_SCAN = {"done": False}


def scan_neighborhood(force: bool = False):
    """Census the whole save so the God maps and backgrounds every Sim.

    Sends a ``full_save`` census: the sidecar then models every Sim/household and
    queues a background per household, per Sim and for relationship-linked NPCs.
    Runs once per session unless ``force`` (``sw.god scan``). Never raises;
    returns the census response or ``None``.
    """
    if _NEIGHBORHOOD_SCAN["done"] and not force:
        return None
    validation_log("neighborhood-scan: full-save census")
    response = send_census(scope="full_save")
    # Only mark the session as scanned on success, so an unreachable sidecar at
    # zone load is retried on the next zone load / household change.
    if isinstance(response, dict):
        _NEIGHBORHOOD_SCAN["done"] = True
    return response


class StateCollector:
    """Recurring snapshot sampler plus game-event ingestion."""

    def __init__(self, interval_minutes: float = DEFAULT_INTERVAL_MINUTES):
        self.interval_minutes = interval_minutes
        self._started = False
        self._bootstrapped = False
        self._handlers_registered = False
        self._alarm_handle = None
        self._autonomy_alarm_handle = None
        self._pull_alarm_handle = None
        self._last_snapshot = None
        self._last_pulse = 0.0

        # Cache the handler dict once: bound methods are fresh objects on each
        # attribute access, so caching keeps the deferred event flush idempotent.
        self._handlers = {
            events.EVENT_ZONE_LOAD: [self._on_zone_load],
            events.EVENT_BUFF_ADD: [self._on_buff_add],
            events.EVENT_RELATIONSHIP_CHANGE: [self._on_relationship_change],
            events.EVENT_SOCIAL_INTERACTION: [self._on_social],
            events.EVENT_HOUSEHOLD_CHANGE: [self._on_household_change],
        }

    # --- lifecycle ---

    def start(self) -> bool:
        """
        Start the recurring alarms (snapshot, zone pulse, directive pull) and
        register game-event handlers.

        Script mods load *before* the game services exist, so the event manager
        and the clock are often unavailable at import. Every piece is therefore
        retried on each call: a later ``start()`` (once the game is ready) fills
        in whatever failed earlier. Idempotent, safe outside the game and never
        raises. Returns True once at least one piece is live.
        """
        # Alarms: add only the ones still missing (retry after an early failure).
        self._ensure_alarm("_alarm_handle", self.interval_minutes, self._on_snapshot_alarm)
        self._ensure_alarm("_autonomy_alarm_handle", AUTONOMY_INTERVAL_MINUTES, self._on_autonomy_alarm)
        self._ensure_alarm("_pull_alarm_handle", DIRECTIVE_PULL_INTERVAL_MINUTES, self._on_directive_alarm)

        # Event handlers: register (or flush the queue kept from import time).
        try:
            self._handlers_registered = bool(events.register(self._handlers))
        except Exception as exc:
            log_exception("StateCollector.start(register handlers)", exc)

        ready = bool(
            self._handlers_registered
            or self._alarm_handle
            or self._autonomy_alarm_handle
            or self._pull_alarm_handle
        )
        was_started = self._started
        if ready:
            self._started = True
        try:
            from .debug_log import debug_log
            debug_log(
                "StateCollector.start: events={} alarms(snapshot={},pulse={},pull={}) ready={}".format(
                    self._handlers_registered,
                    self._alarm_handle is not None,
                    self._autonomy_alarm_handle is not None,
                    self._pull_alarm_handle is not None,
                    ready,
                )
            )
        except Exception:
            pass
        # True only on the call that actually brought the collector live.
        return ready and not was_started

    def is_ready(self) -> bool:
        """Whether any collector piece (events or an alarm) is live."""
        return bool(
            self._handlers_registered
            or self._alarm_handle
            or self._autonomy_alarm_handle
            or self._pull_alarm_handle
        )

    def _ensure_alarm(self, attr: str, minutes: float, callback) -> None:
        """Add a recurring alarm if its handle is still missing. Never raises."""
        if getattr(self, attr, None) is not None:
            return
        try:
            handle = events.add_alarm(minutes, callback, repeating=True)
            setattr(self, attr, handle)
            if handle is None:
                # No live/instanced owner yet: the alarm stays deferred and the
                # zone hook re-arms it once the active Sim is instanced (M3).
                debug_log("StateCollector._ensure_alarm({}): alarm deferred (no live owner)".format(attr))
        except Exception as exc:
            log_exception("StateCollector.start({})".format(attr), exc)
            setattr(self, attr, None)

    def ensure_started(self) -> bool:
        """
        Retry ``start()``; on the first successful boot, push the zone census.

        Called from the command paths (and autoboot) so a save loaded before the
        services were ready still gets its census, events and alarms wired.
        """
        try:
            self.start()
        except Exception as exc:
            log_exception("StateCollector.ensure_started(start)", exc)
        ready = self.is_ready()
        if ready and not self._bootstrapped:
            self._bootstrapped = True
            try:
                send_census()
            except Exception as exc:
                log_exception("StateCollector.ensure_started(census)", exc)
        return ready

    def stop(self) -> bool:
        """
        Cancel every recurring alarm and unregister game-event handlers.
        Idempotent and safe outside the game. Never raises.
        Returns True if the collector was running.
        """
        was_started = self._started
        self._started = False
        self._bootstrapped = False
        self._handlers_registered = False

        for attr in ("_alarm_handle", "_autonomy_alarm_handle", "_pull_alarm_handle"):
            handle = getattr(self, attr, None)
            try:
                if handle is not None:
                    events.cancel_alarm(handle)
            except Exception as exc:
                log_exception("StateCollector.stop(cancel_alarm)", exc)
            setattr(self, attr, None)

        try:
            events.unregister_all()
        except Exception as exc:
            log_exception("StateCollector.stop(unregister_all)", exc)

        return was_started

    # --- collection ---

    def sample(self) -> Dict[str, Any]:
        """Collect the active Sim context and remember it as the last snapshot."""
        try:
            context = sim_context.collect()
        except Exception as exc:
            log_exception("StateCollector.sample", exc)
            context = {}
        if not isinstance(context, dict):
            context = {}
        self._last_snapshot = context
        return context

    def sample_and_send(self) -> Dict[str, Any]:
        """Collect a context snapshot and forward it as a 'snapshot' event."""
        context = self.sample()
        self._emit("snapshot", context, IMPORTANCE_SNAPSHOT, sim_ref=_build_sim_ref(context))
        return context

    def last_snapshot(self) -> Optional[Dict[str, Any]]:
        """Return the most recent collected snapshot (debugging aid)."""
        return self._last_snapshot

    # --- player activity ---

    def notify_player_activity(self, sim: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Best-effort POST to /v1/config/player-activity (arms priority lock)."""
        try:
            return http_client.send_player_activity(sim)
        except (http_client.SidecarUnreachable, http_client.SidecarError):
            return None
        except Exception as exc:
            log_exception("state_collector.notify_player_activity", exc)
            return None

    # --- sending ---

    def _send(self, event_list: List[Dict[str, Any]]) -> None:
        """Best-effort event batch send."""
        try:
            http_client.send_events(event_list)
        except (http_client.SidecarUnreachable, http_client.SidecarError) as exc:
            log_exception("state_collector._send", exc)
        except Exception as exc:
            log_exception("state_collector._send", exc)

    def _emit(self, event_type: str, content: Dict[str, Any],
              importance: float, sim_ref: Optional[Dict[str, Any]] = None) -> None:
        """Build and forward a single event."""
        validation_log("event: {} (importance={})".format(event_type, importance))
        try:
            sim = sim_ref if sim_ref is not None else self._current_sim_ref()
            event = {
                "sim": sim,
                "type": event_type,
                "content": content if isinstance(content, dict) else {},
                "importance": float(importance),
                "lang": _current_lang(),
            }
            self._send([event])
        except Exception as exc:
            log_exception("StateCollector._emit({})".format(event_type), exc)
        self._maybe_pulse()

    def _maybe_pulse(self) -> None:
        """Throttled pulse/pull driven by gameplay events (alarm safety net).

        Game-clock alarms pause with the game, so a session where the player is
        paused (or an alarm owner that does not tick) would never pulse. Events
        only fire during active play, so piggy-back the pulse here to guarantee
        the agency loop runs. Best-effort and wall-clock throttled.
        """
        if not self._started:
            return
        now = time.monotonic()
        if (now - self._last_pulse) < PULSE_MIN_INTERVAL_SECONDS:
            return
        self._last_pulse = now
        validation_log("event-pulse: alarm safety net fired")
        pulse_and_pull()

    def _current_sim_ref(self) -> Dict[str, Any]:
        """Lightweight sim reference for game events."""
        sim_id = 0
        save_id = ""
        try:
            sim_info = sim_context._get_active_sim_info()
        except Exception:
            sim_info = None
        if sim_info is not None:
            try:
                sim_id = int(_safe_getattr(sim_info, "id", 0) or 0)
            except (TypeError, ValueError):
                sim_id = 0
        try:
            save_id = sim_context._get_save_id() or ""
        except Exception:
            save_id = ""
        if not isinstance(save_id, str):
            save_id = str(save_id)
        return {
            "player_id": "local",
            "save_id": save_id,
            "sim_id": sim_id,
        }

    # --- handlers ---

    def _on_snapshot_alarm(self, *args, **kwargs) -> None:
        """Alarm callback: sample and forward a snapshot.

        The game calls alarm callbacks with an argument (the alarm handle), so
        ``*args`` is required (a bare ``self`` raised
        "_on_snapshot_alarm() takes 1 positional argument but 2 were given").
        """
        debug_log("_on_snapshot_alarm fired")
        try:
            self.sample_and_send()
        except Exception as exc:
            log_exception("StateCollector._on_snapshot_alarm", exc)

    def _on_autonomy_alarm(self, *args, **kwargs) -> None:
        """Alarm callback: send the zone pulse to the sidecar."""
        debug_log("_on_autonomy_alarm fired")
        try:
            result = send_autonomy_tick()
            debug_log("_on_autonomy_alarm result={!r}".format(result))
        except Exception as exc:
            log_exception("StateCollector._on_autonomy_alarm", exc)

    def _on_directive_alarm(self, *args, **kwargs) -> None:
        """Alarm callback: pull and execute pending per-Sim directives."""
        debug_log("_on_directive_alarm fired")
        try:
            result = pull_and_execute_directives()
            debug_log("_on_directive_alarm result={!r}".format(result))
        except Exception as exc:
            log_exception("StateCollector._on_directive_alarm", exc)

    def _on_zone_load(self, *args, **kwargs) -> None:
        """Forward a compact zone-load event, then offer God onboarding/census."""
        validation_log("zone_load event fired")
        content = {"event": "zone_load"}
        zone_id = kwargs.get("zone_id")
        if zone_id is None:
            zone_id = _first_attr(args, ("zone_id", "id"))
        if zone_id is not None:
            content["zone_id"] = zone_id
        self._emit("zone_load", content, IMPORTANCE_ZONE_LOAD)

        try:
            sim_info = sim_context._get_active_sim_info()
        except Exception:
            sim_info = None
        try:
            god_ui.maybe_show_zeitgeist_onboarding(sim_info)
        except Exception as exc:
            log_exception("StateCollector._on_zone_load(god_ui)", exc)
        try:
            send_census()
        except Exception as exc:
            log_exception("StateCollector._on_zone_load(census)", exc)
        try:
            scan_neighborhood()
        except Exception as exc:
            log_exception("StateCollector._on_zone_load(neighborhood)", exc)

        # Re-arm the game-clock alarms for the new zone/active Sim (the alarm
        # owner may have changed) and send one immediate pulse so the agency
        # loop gets data even if a recurring alarm stalls.
        try:
            for attr in ("_alarm_handle", "_autonomy_alarm_handle", "_pull_alarm_handle"):
                handle = getattr(self, attr, None)
                if handle is not None:
                    try:
                        events.cancel_alarm(handle)
                    except Exception as exc:
                        log_exception("StateCollector._on_zone_load(cancel_alarm)", exc)
                    setattr(self, attr, None)
            self.ensure_started()
        except Exception as exc:
            log_exception("StateCollector._on_zone_load(re-arm)", exc)
        try:
            send_autonomy_tick(sim_info)
        except Exception as exc:
            log_exception("StateCollector._on_zone_load(pulse)", exc)

    def _on_household_change(self, *args, **kwargs) -> None:
        """Forward a compact household-change event and offer background UI."""
        content = {"event": "household_change"}
        household = _first_attr(args, ("household", "household_info"))
        household_id = kwargs.get("household_id")
        if household_id is None and household is not None:
            household_id = _safe_getattr(household, "id", None)
        if household_id is not None:
            try:
                content["household_id"] = int(household_id)
            except (TypeError, ValueError):
                household_id = None
        self._emit("household_change", content, IMPORTANCE_HOUSEHOLD)

        try:
            sim_info = sim_context._get_active_sim_info()
        except Exception:
            sim_info = None
        census = None
        try:
            census_sims, census_households = build_census()
            census = {"sims": census_sims, "households": census_households}
        except Exception as exc:
            log_exception("StateCollector._on_household_change(census)", exc)
            census = None
        try:
            god_ui.prompt_household_background(
                sim_info,
                household_id=content.get("household_id"),
                census=census,
            )
        except Exception as exc:
            log_exception("StateCollector._on_household_change(god_ui)", exc)

    def _on_buff_add(self, *args, **kwargs) -> None:
        """Forward a compact buff-added event."""
        content = {}
        buff = _first_attr(args, ("buff_type", "buff", "buff_name", "commodity"))
        name = _name_of(buff)
        if name:
            content["buff"] = name
        sim = _first_attr(args, ("sim", "sim_info"))
        sim_id = _safe_getattr(sim, "id", None) if sim is not None else None
        if sim_id is not None:
            try:
                content["sim_id"] = int(sim_id)
            except (TypeError, ValueError):
                pass
        self._emit("buff_add", content, IMPORTANCE_BUFF)

    def _on_relationship_change(self, *args, **kwargs) -> None:
        """Forward a compact relationship-change event."""
        content = {}
        relationship = _first_attr(args, ("relationship", "relationship_change", "target"))
        target = _first_attr(
            [relationship], ("target_sim_info", "target_sim", "sim_info", "target")
        )
        target_name = _name_of(target)
        if target_name:
            content["target"] = target_name
        target_id = _safe_getattr(target, "id", None) if target is not None else None
        if target_id is not None:
            try:
                content["target_id"] = int(target_id)
            except (TypeError, ValueError):
                pass
        depth = _safe_getattr(relationship, "relationship_depth", None)
        if depth is not None:
            try:
                content["depth"] = float(depth)
            except (TypeError, ValueError):
                pass
        self._emit("relationship_change", content, IMPORTANCE_RELATIONSHIP)

    def _on_social(self, *args, **kwargs) -> None:
        """Forward a compact social-interaction event."""
        content = {}
        interaction = _first_attr(args, ("interaction", "social_interaction", "action"))
        name = _name_of(interaction)
        if name:
            content["interaction"] = name
        target = _first_attr(args, ("target_sim_info", "target_sim", "target"))
        target_name = _name_of(target)
        if target_name:
            content["target"] = target_name
        self._emit("social", content, IMPORTANCE_SOCIAL)


# --- module-level singleton ---

_collector: Optional[StateCollector] = None


def get_collector() -> StateCollector:
    """Return the module-level StateCollector singleton."""
    global _collector
    if _collector is None:
        _collector = StateCollector()
    return _collector


def start() -> bool:
    """Start the module-level collector. Never raises."""
    try:
        return get_collector().start()
    except Exception as exc:
        log_exception("state_collector.start", exc)
        return False


def ensure_started() -> bool:
    """
    Retry starting the module-level collector and bootstrap once when it becomes
    live (sends the zone census so a save loaded before the services were ready
    still reaches the sidecar). Never raises.
    """
    try:
        return get_collector().ensure_started()
    except Exception as exc:
        log_exception("state_collector.ensure_started", exc)
        return False


# Zone-load hook: keep the agency loop running during normal play.
#
# The command paths are user-driven and the game-clock alarms proved unreliable
# in live validation (owner/zone semantics), so ``Zone.update`` is used as the
# reliable heartbeat: it runs every frame the zone is live. The wrapper starts
# the collector once the active Sim is instanced (a live alarm owner + a
# non-empty census) and then drives a **wall-clock throttled** pulse/pull. The
# per-frame cost after startup is one timestamp comparison.
ZONE_PULSE_INTERVAL_SECONDS = 15.0
_ZONE_HOOK = {"installed": False, "started": False, "last_pulse": 0.0, "driver": None}


def _active_sim_ready() -> bool:
    """True once the active Sim is instanced (zone fully loaded)."""
    try:
        sim_info = sim_context._get_active_sim_info()
        if sim_info is None:
            return False
        return sim_context._get_sim_instance(sim_info) is not None
    except Exception:
        return False


def _zone_tick_impl() -> None:
    """One heartbeat: start the collector once, then pulse on a wall-clock cadence.

    Driven by the Lot 51 game tick when available (stack base), else by the
    native ``Zone.update`` wrapper. Never raises.
    """
    if not _ZONE_HOOK["started"]:
        # Wait for the active Sim instance: it makes the census non-empty.
        if _active_sim_ready() and ensure_started():
            _ZONE_HOOK["started"] = True
            debug_log("zone hook: collector auto-started (driver={})".format(
                _ZONE_HOOK["driver"]))
        else:
            return
    now = time.monotonic()
    if (now - _ZONE_HOOK["last_pulse"]) < ZONE_PULSE_INTERVAL_SECONDS:
        return
    _ZONE_HOOK["last_pulse"] = now
    validation_log("zone-pulse: heartbeat")
    pulse_and_pull()


def install_zone_hook() -> bool:
    """Start the pulse loop: Lot 51 game tick first, native ``Zone.update`` fallback.

    Never raises; a no-op outside the game.
    """
    if _ZONE_HOOK["installed"]:
        return True

    # Stack base: the Lot 51 CoreEvent bus drives the loop with no injection.
    if events.register_lot51_tick(_zone_tick_impl):
        _ZONE_HOOK["installed"] = True
        _ZONE_HOOK["driver"] = "lot51"
        debug_log("zone hook: driven by Lot 51 game tick")
        return True

    # Fallback: wrap ``Zone.update`` (native heartbeat).
    try:
        import zone as zone_module  # type: ignore
    except Exception:
        debug_log("zone hook: 'zone' module unavailable")
        return False
    zone_cls = getattr(zone_module, "Zone", None)
    original = getattr(zone_cls, "update", None) if zone_cls is not None else None
    if original is None:
        debug_log("zone hook: Zone.update not found")
        return False
    if getattr(original, "_sensewright_zone_hook", False):
        _ZONE_HOOK["installed"] = True
        return True

    def _wrapper(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        try:
            _zone_tick_impl()
        except Exception as exc:
            log_exception("state_collector.zone_hook", exc)
        return result

    _wrapper._sensewright_zone_hook = True
    zone_cls.update = _wrapper
    _ZONE_HOOK["installed"] = True
    _ZONE_HOOK["driver"] = "native"
    debug_log("zone hook installed (native Zone.update)")
    return True


def stop() -> bool:
    """Stop the module-level collector. Never raises."""
    try:
        return get_collector().stop()
    except Exception as exc:
        log_exception("state_collector.stop", exc)
        return False


def notify_player_activity(sim: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Best-effort player-activity notification. Never raises."""
    try:
        return get_collector().notify_player_activity(sim)
    except Exception as exc:
        log_exception("state_collector.notify_player_activity", exc)
        return None


def last_snapshot() -> Optional[Dict[str, Any]]:
    """Return the most recent snapshot from the singleton (debugging aid)."""
    return get_collector().last_snapshot()
