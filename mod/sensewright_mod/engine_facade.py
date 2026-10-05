# Sensewright v2 — Engine Facade (EA/S4CL Access Layer)
# Python 3.7 compatible
#
# Defensive, never-raising helpers that isolate all EA/S4CL API calls.
# Every function wraps its body in try/except, logs via debug_log, and returns
# safe defaults. This is the single place where native engine idiosyncrasies live.

import services
import sims4.resources
from sims.sim_info import SimInfo
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
from sims4communitylib.utils.sims.common_relationship_utils import CommonRelationshipUtils
from sims4communitylib.utils.sims.common_sim_location_utils import CommonSimLocationUtils
from sims4communitylib.utils.sims.common_gender_utils import CommonGenderUtils
from sims4communitylib.utils.sims.common_sim_situation_utils import CommonSimSituationUtils
from sims4communitylib.utils.sims.common_buff_utils import CommonBuffUtils
from sims4communitylib.utils.common_log_utils import CommonLogUtils

from sensewright_mod.debug_log import log_exception, log_debug, log_info
from sensewright_mod.native_hooks import apply_buff, remove_buff

from typing import Optional, List, Dict, Any


def _safe_getattr(obj, attr, default=None):
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def _safe_call(func, *args, **kwargs):
    try:
        return func(*args, **kwargs)
    except Exception:
        return None


def _coerce_int(value, default=0):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def _sim_id(obj):
    """Resolve a stable sim id from a Sim (GameObject) or SimInfo."""
    if obj is None:
        return 0
    try:
        info = CommonSimUtils.get_sim_info(obj)
        if info is not None:
            return _coerce_int(_safe_getattr(info, 'id', 0), 0)
    except Exception:
        pass
    return _coerce_int(_safe_getattr(obj, 'id', 0), 0)


# ──────────────────────────────────────────────────────────────────────────────
# SimInfo accessors
# ──────────────────────────────────────────────────────────────────────────────

def get_active_sim_info():
    """Return the active SimInfo, or None."""
    try:
        return services.active_sim_info()
    except Exception as e:
        log_exception('engine_facade.get_active_sim_info: {}'.format(e))
        return None


def sim_id_of(obj):
    """Return the numeric sim_id from a Sim/SimInfo/object, or 0."""
    return _sim_id(obj)


def sim_info_of(obj):
    """Return SimInfo from a Sim/SimInfo/object, or None."""
    if obj is None:
        return None
    if isinstance(obj, SimInfo):
        return obj
    try:
        return CommonSimUtils.get_sim_info(obj)
    except Exception as e:
        log_exception('engine_facade.sim_info_of: {}'.format(e))
        return None


def sim_age_stage(info):
    """Return normalized age-stage token (e.g. 'YOUNGADULT') from SimInfo, or ''."""
    if info is None:
        return ''
    try:
        age = _safe_getattr(info, 'age', None)
        name = _safe_getattr(age, 'name', None)
        if name:
            token = str(name).upper()
            if token.startswith('AGE.'):
                token = token[4:]
            return token
    except Exception as e:
        log_exception('engine_facade.sim_age_stage: {}'.format(e))
    return ''


def sim_gender(info):
    """Return short gender code 'M'/'F'/'N' from SimInfo, or ''."""
    if info is None:
        return ''
    try:
        if CommonGenderUtils.is_male(info):
            return 'M'
        if CommonGenderUtils.is_female(info):
            return 'F'
    except Exception as e:
        log_exception('engine_facade.sim_gender: {}'.format(e))
    return 'N'


def sim_household_id(info):
    """Return household id from SimInfo, or 0."""
    if info is None:
        return 0
    try:
        household = _safe_getattr(info, 'household', None)
        if household is not None:
            return _coerce_int(_safe_getattr(household, 'id', 0), 0)
    except Exception as e:
        log_exception('engine_facade.sim_household_id: {}'.format(e))
    return 0


def sim_room_id(sim):
    """Return the room id the sim is in, or 0."""
    try:
        sim_info = sim_info_of(sim)
        if sim_info is None:
            return 0
        room_id = CommonSimLocationUtils.get_current_room_id(sim_info)
        if room_id is not None and room_id >= 0:
            return int(room_id)
    except Exception as e:
        log_exception('engine_facade.sim_room_id: {}'.format(e))
    # Fallback: raw routing component
    try:
        sim_obj = _safe_call(CommonSimUtils.get_sim_instance, sim)
        routing_component = _safe_getattr(sim_obj, 'routing_component', None)
        if routing_component is not None:
            room_id = _safe_getattr(routing_component, 'current_room_id', 0)
            if room_id:
                return int(room_id)
    except Exception:
        pass
    return 0


# ──────────────────────────────────────────────────────────────────────────────
# Interaction accessors
# ──────────────────────────────────────────────────────────────────────────────

def current_interaction(sim):
    """Return the current interaction instance for a Sim, or None."""
    try:
        sim_obj = _safe_call(CommonSimUtils.get_sim_instance, sim)
        if sim_obj is None:
            return None
        si_state = _safe_getattr(sim_obj, 'si_state', None)
        if si_state is not None:
            return _safe_getattr(si_state, 'current_interaction', None)
        # Fallback: queue.running
        queue = _safe_getattr(sim_obj, 'queue', None)
        if queue is not None:
            return _safe_getattr(queue, 'running', None)
    except Exception as e:
        log_exception('engine_facade.current_interaction: {}'.format(e))
    return None


def interaction_localized_text(si):
    """Return the localized display text of an interaction (menu title), or ''."""
    if si is None:
        return ''
    try:
        from sims4.localization import LocalizationHelperTuning
        display_name = _safe_getattr(si, 'display_name', None)
        if display_name is not None:
            text = LocalizationHelperTuning.get_raw_text(display_name)
            if text:
                return str(text)
    except Exception as e:
        log_exception('engine_facade.interaction_localized_text (localization): {}'.format(e))
    try:
        short = _safe_getattr(si, '__name__', None)
        if short:
            return str(short)
    except Exception:
        pass
    return str(si) if si else ''


def interaction_target(si):
    """Return the target object/Sim of an interaction, or None."""
    if si is None:
        return None
    try:
        for accessor in ('get_target', 'get_target_sim', 'get_target_sim_info'):
            fn = _safe_getattr(si, accessor, None)
            if callable(fn):
                target = _safe_call(fn)
                if target is not None:
                    return target
        for attr in ('target', 'target_sim', 'target_sim_info', 'picked_sim'):
            target = _safe_getattr(si, attr, None)
            if target is not None:
                return target
    except Exception as e:
        log_exception('engine_facade.interaction_target: {}'.format(e))
    return None


# ──────────────────────────────────────────────────────────────────────────────
# Social peers
# ──────────────────────────────────────────────────────────────────────────────

def _member_sim_id(member):
    """Coerce a social-group member (Sim or SimInfo) to its numeric id."""
    if member is None:
        return 0
    sim_info = _safe_getattr(member, 'sim_info', None)
    if sim_info is not None:
        return _coerce_int(_safe_getattr(sim_info, 'id', 0), 0)
    return _coerce_int(_safe_getattr(member, 'id', 0), 0)


def social_peers(sim):
    """Return a list of peer sim ids the sim is socially grouped with (from si.social_group)."""
    peer_ids = []
    try:
        sim_obj = _safe_call(CommonSimUtils.get_sim_instance, sim)
        if sim_obj is None:
            return peer_ids
        for source_name in ('si_state', 'queue'):
            collection = _safe_getattr(sim_obj, source_name, None)
            if collection is None:
                continue
            try:
                for social_interaction in collection:
                    social_group = _safe_getattr(social_interaction, 'social_group', None)
                    if social_group is None:
                        continue
                    try:
                        for member in social_group:
                            member_id = _member_sim_id(member)
                            if member_id:
                                peer_ids.append(member_id)
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception as e:
        log_exception('engine_facade.social_peers: {}'.format(e))
    # Deduplicate
    seen = set()
    unique = []
    for pid in peer_ids:
        if pid not in seen:
            seen.add(pid)
            unique.append(pid)
    return unique


# ──────────────────────────────────────────────────────────────────────────────
# Relationship edges
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_other_sim_id(rel, sim_id):
    """Return the id of the other sim in a vanilla Relationship object."""
    getter = _safe_getattr(rel, 'get_other_sim_id', None)
    if callable(getter):
        other = _safe_call(getter, sim_id)
        if other:
            return _coerce_int(other, 0)
    a = _coerce_int(_safe_getattr(rel, 'sim_id_a', 0), 0)
    b = _coerce_int(_safe_getattr(rel, 'sim_id_b', 0), 0)
    if a == sim_id:
        return b
    if b == sim_id:
        return a
    return 0


def relationship_edges(sim_info):
    """Return a list of relationship edges for a SimInfo.
    Each edge is a dict: {target_sim_id, friendship, romance, bits: []}.
    """
    edges = []
    if sim_info is None:
        return edges
    try:
        sim_id = _coerce_int(_safe_getattr(sim_info, 'id', 0), 0)
        if not sim_id:
            return edges
        rels = CommonRelationshipUtils.get_relationships_gen(sim_info)
        for rel in rels:
            target_id = _resolve_other_sim_id(rel, sim_id)
            if not target_id:
                continue
            target_info = services.sim_info_manager().get(target_id)
            if target_info is None:
                continue
            try:
                friendship = CommonRelationshipUtils.get_friendship_level(sim_info, target_info)
                romance = CommonRelationshipUtils.get_romance_level(sim_info, target_info)
            except Exception:
                friendship, romance = 0.0, 0.0
            # Bits
            bits = []
            try:
                all_bits = _safe_call(getattr(rel, 'get_all_bits', None))
                if all_bits:
                    for bit in all_bits:
                        bit_name = _safe_getattr(bit, '__name__', str(bit))
                        bits.append(str(bit_name))
            except Exception:
                pass
            edges.append({
                'target_sim_id': target_id,
                'friendship': float(friendship),
                'romance': float(romance),
                'bits': bits,
            })
    except Exception as e:
        log_exception('engine_facade.relationship_edges: {}'.format(e))
    return edges


# ──────────────────────────────────────────────────────────────────────────────
# Situation / NPC spawning
# ──────────────────────────────────────────────────────────────────────────────

def spawn_and_visit(sim_info):
    """Start a native visit situation for sim_info.
    Returns {ok: bool, situation_id: int, error: str}.
    """
    result = {'ok': False, 'situation_id': 0, 'error': ''}
    if sim_info is None:
        result['error'] = 'sim_info is None'
        return result
    try:
        situation_manager = services.get_situation_manager()
        if situation_manager is None:
            result['error'] = 'situation_manager unavailable'
            return result
        # Try create_visit_situation first (native)
        try:
            situation_id = situation_manager.create_visit_situation(sim_info)
            if situation_id:
                result['ok'] = True
                result['situation_id'] = _coerce_int(situation_id, 0)
                return result
        except Exception as e:
            log_debug('engine_facade.spawn_and_visit: create_visit_situation failed: {}'.format(e))
        # Fallback: create_situation with the visit situation type
        try:
            from sims4communitylib.utils.sims.common_sim_situation_utils import CommonSimSituationUtils
            CommonSimSituationUtils.create_visit_situation(sim_info)
            # We don't get the ID back easily, but mark ok
            result['ok'] = True
            return result
        except Exception as e:
            log_exception('engine_facade.spawn_and_visit: fallback create_visit_situation failed: {}'.format(e))
            result['error'] = str(e)
    except Exception as e:
        log_exception('engine_facade.spawn_and_visit: {}'.format(e))
        result['error'] = str(e)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Buff roundtrip
# ──────────────────────────────────────────────────────────────────────────────

def buff_roundtrip(sim, buff_type):
    """Apply then remove a buff via native_hooks helpers.
    Returns {ok: bool, error: str}.
    """
    result = {'ok': False, 'error': ''}
    if sim is None or buff_type == 0:
        result['error'] = 'invalid args'
        return result
    try:
        sim_info = sim_info_of(sim)
        if sim_info is None:
            result['error'] = 'sim_info not found'
            return result
        # Apply
        applied = apply_buff(sim_info, buff_type, 60)
        if not applied:
            result['error'] = 'apply_buff returned False'
            return result
        # Remove
        removed = remove_buff(sim_info, buff_type)
        if not removed:
            result['error'] = 'remove_buff returned False'
            return result
        result['ok'] = True
    except Exception as e:
        log_exception('engine_facade.buff_roundtrip: {}'.format(e))
        result['error'] = str(e)
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Object / misc
# ──────────────────────────────────────────────────────────────────────────────

def object_class_name(obj):
    """Return obj.__class__.__name__ or ''."""
    if obj is None:
        return ''
    try:
        cls = _safe_getattr(obj, '__class__', None)
        if cls is not None:
            return _safe_getattr(cls, '__name__', '') or ''
    except Exception:
        pass
    return ''


# ──────────────────────────────────────────────────────────────────────────────
# Tuning / resource checks (for smoke_test)
# ──────────────────────────────────────────────────────────────────────────────

def tuning_resource_loaded(type_enum, tuning_id):
    """Best-effort check if a tuning resource is loaded in the InstanceManager."""
    if tuning_id == 0:
        return False
    try:
        manager = services.get_instance_manager(type_enum)
        if manager is None:
            return False
        return manager.get(tuning_id) is not None
    except Exception as e:
        log_exception('engine_facade.tuning_resource_loaded: {}'.format(e))
        return False


def find_objects_by_class_name(class_name_substring):
    """Find objects on the current lot whose class name contains the substring (case-insensitive)."""
    results = []
    try:
        object_manager = services.object_manager()
        if object_manager is None:
            return results
        target_lower = class_name_substring.lower()
        for obj in object_manager.values():
            if obj is None:
                continue
            cls_name = object_class_name(obj).lower()
            if target_lower in cls_name:
                results.append(obj)
    except Exception as e:
        log_exception('engine_facade.find_objects_by_class_name: {}'.format(e))
    return results


def get_townie_not_on_lot(exclude_sim_info=None):
    """Return a SimInfo for an adult townie not in the active household and not on the current lot, or None."""
    try:
        manager = services.sim_info_manager()
        if manager is None:
            return None
        active_household = services.active_household()
        active_household_id = _safe_getattr(active_household, 'id', 0)
        exclude_id = _coerce_int(_safe_getattr(exclude_sim_info, 'id', 0), 0) if exclude_sim_info else 0
        adult_stages = ('TEEN', 'YOUNGADULT', 'ADULT', 'ELDER')
        for sim_info in manager.values():
            if sim_info is None:
                continue
            if exclude_id and sim_info.id == exclude_id:
                continue
            household_id = _safe_getattr(_safe_getattr(sim_info, 'household', None), 'id', 0)
            if active_household_id and household_id == active_household_id:
                continue
            age_name = sim_age_stage(sim_info)
            if age_name not in adult_stages:
                continue
            # Check if instanced (on lot)
            try:
                sim_instance = CommonSimUtils.get_sim_instance(sim_info)
                if sim_instance is not None:
                    continue  # Already on lot
            except Exception:
                pass
            return sim_info
    except Exception as e:
        log_exception('engine_facade.get_townie_not_on_lot: {}'.format(e))
    return None