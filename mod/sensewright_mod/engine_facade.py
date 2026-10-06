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

def _iter_social_interactions(si_state):
    """Yield each social interaction in an SIState, defensively.

    ``si_state`` is iterable (``for si in si_state``) and also exposes
    ``sis_actor_gen()``; ``current_interaction`` is a property that is only
    populated in some builds. We try all three and dedupe by identity.
    """
    seen = set()
    gen = _safe_getattr(si_state, 'sis_actor_gen', None)
    if callable(gen):
        for si in _safe_call(gen) or ():
            if si is not None and id(si) not in seen:
                seen.add(id(si))
                yield si
    for si in _safe_iter_collection(si_state):
        if si is not None and id(si) not in seen:
            seen.add(id(si))
            yield si
    cur = _safe_getattr(si_state, 'current_interaction', None)
    if cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        yield cur


def _safe_iter_collection(collection):
    """Safely iterate a collection, yielding its items; empty on failure."""
    if collection is None:
        return
    try:
        for item in collection:
            yield item
    except Exception:
        return


def current_interaction(sim):
    """Return the Sim's primary current interaction, or None.

    Order of preference: the running queued interaction (``sim.queue.running``)
    first, then the first social interaction in ``sim.si_state``. The previous
    implementation read ``si_state.current_interaction`` (a property that is
    empty during social interactions on TS4 1.128.x) and only fell back to the
    queue when ``si_state`` was None — so it always returned None mid-interaction.
    """
    interactions = current_interactions(sim)
    return interactions[0] if interactions else None


def current_interactions(sim):
    """Return a list of the Sim's currently-running interactions (never raises).

    A Sim mid-conversation has ``queue.running`` plus one or more social
    interactions in ``si_state``; both are returned (deduped by identity).
    """
    result = []
    try:
        sim_obj = _safe_call(CommonSimUtils.get_sim_instance, sim)
        if sim_obj is None:
            return result
        seen = set()
        queue = _safe_getattr(sim_obj, 'queue', None)
        running = _safe_getattr(queue, 'running', None)
        if running is not None:
            result.append(running)
            seen.add(id(running))
        si_state = _safe_getattr(sim_obj, 'si_state', None)
        if si_state is not None:
            for si in _iter_social_interactions(si_state):
                if id(si) not in seen:
                    result.append(si)
                    seen.add(id(si))
    except Exception as e:
        log_exception('engine_facade.current_interactions: {}'.format(e))
    return result


def interaction_localized_text(si):
    """Return the localized display text of an interaction (menu title), or ''."""
    if si is None:
        return ''
    try:
        display_name = _safe_getattr(si, 'display_name', None)
        if display_name is not None:
            # str() resolves through the localization system, whereas
            # get_raw_text() returns the unresolved 'hash: … tokens { type:
            # INVALID }' repr for hash-based localized strings. Prefer the
            # resolved text and reject the hash repr.
            resolved = ''
            try:
                resolved = str(display_name)
            except Exception:
                resolved = ''
            if resolved and 'hash:' not in resolved:
                return resolved
            from sims4.localization import LocalizationHelperTuning
            raw = LocalizationHelperTuning.get_raw_text(display_name)
            if raw and 'hash:' not in str(raw) and 'tokens' not in str(raw):
                return str(raw)
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
            # Bits (correct accessor: the tracker's get_all_bits, not the
            # Relationship object — validated in-game 2026-10-05).
            bits = []
            try:
                tracker = _safe_getattr(sim_info, 'relationship_tracker', None)
                if tracker is not None:
                    all_bits = _safe_call(getattr(tracker, 'get_all_bits', None), target_id)
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
        situation_manager = services.get_zone_situation_manager()
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
# Relationship bits & moods (relationship_bits / mood_effect probes)
# ──────────────────────────────────────────────────────────────────────────────

def relationship_bits(sim_info, target_sim_info):
    """Return relationship bits between two Sims via the engine's own accessor.

    ``SimInfo.relationship_tracker.get_all_bits(target_sim_id)`` is the correct
    edge reader (it delegates to ``relationship_service.get_all_bits``). The old
    ``relationship`` probe called ``Relationship.get_all_bits()`` (no args) on
    the vanilla Relationship object — that method lives on the *tracker*, so the
    old probe silently returned ``[]``. Each bit is returned with its ``guid64``
    (a ``CommonRelationshipBitId`` int), plus any ``__name__``/``display_name``.
    """
    result = {'target_sim_id': 0, 'bits': [], 'error': ''}
    if sim_info is None or target_sim_info is None:
        result['error'] = 'sim_info/target missing'
        return result
    try:
        tracker = _safe_getattr(sim_info, 'relationship_tracker', None)
        target_id = _coerce_int(_safe_getattr(target_sim_info, 'id', 0), 0)
        result['target_sim_id'] = target_id
        if tracker is None or not target_id:
            result['error'] = 'no relationship tracker or target id'
            return result
        bits = _safe_call(getattr(tracker, 'get_all_bits', None), target_id)
        if bits is None:
            result['error'] = 'get_all_bits returned None'
            return result
        for bit in bits:
            entry = {
                'guid64': _coerce_int(_safe_getattr(bit, 'guid64', 0), 0),
                'name': str(_safe_getattr(bit, '__name__', '') or ''),
                'display_name': str(_safe_getattr(bit, 'display_name', '') or ''),
            }
            result['bits'].append(entry)
    except Exception as e:
        log_exception('engine_facade.relationship_bits: {}'.format(e))
        result['error'] = str(e)
    return result


def current_mood(sim_info):
    """Return the Sim's current mood as {guid64, name, intensity}, or {}.

    ``SimInfo.get_mood()`` returns a Mood object whose ``.guid64`` is the vanilla
    mood instance id (HAPPY=14640, SAD=14643, …); ``get_mood_intensity()`` is the
    accompanying strength. Because ``SimInfo.get_mood()`` can be stale (it is the
    save-path accessor), also read the instanced ``Sim.get_mood()`` (the live
    value) under ``sim_*`` keys when a Sim instance exists. Used by the
    ``mood_effect`` probe to prove a buff's ``mood_type`` actually moves the needle.
    """
    if sim_info is None:
        return {}
    result = {}
    try:
        mood = _safe_call(getattr(sim_info, 'get_mood', None))
        if mood is not None:
            result['guid64'] = _coerce_int(_safe_getattr(mood, 'guid64', 0), 0)
            result['name'] = str(_safe_getattr(mood, '__name__', '') or '')
    except Exception as e:
        log_exception('engine_facade.current_mood (SimInfo): {}'.format(e))
    try:
        result['intensity'] = float(_safe_call(getattr(sim_info, 'get_mood_intensity', None)))
    except (TypeError, ValueError):
        pass
    # Live mood from the instanced Sim (the authoritative, freshly-recomputed one).
    try:
        sim = _safe_call(CommonSimUtils.get_sim_instance, sim_info)
        if sim is not None:
            live_mood = _safe_call(getattr(sim, 'get_mood', None))
            if live_mood is not None:
                result['sim_guid64'] = _coerce_int(_safe_getattr(live_mood, 'guid64', 0), 0)
                result['sim_name'] = str(_safe_getattr(live_mood, '__name__', '') or '')
            try:
                result['sim_intensity'] = float(_safe_call(getattr(sim, 'get_mood_intensity', None)))
            except (TypeError, ValueError):
                pass
    except Exception as e:
        log_exception('engine_facade.current_mood (Sim): {}'.format(e))
    return result


def sim_mood_buffs(sim_info):
    """Return the Sim's active mood-affecting buffs as {buff_class, mood_type, mood_weight}.

    Used by the ``mood_effect`` probe to show what a new mood buff competes with
    (the prevailing mood is the summed highest ``mood_weight``).
    """
    buffs = []
    if sim_info is None:
        return buffs
    try:
        buff_handler = _safe_getattr(sim_info, 'Buffs', None)
        if buff_handler is None:
            return buffs
        for buff in buff_handler:
            mood_type = _safe_getattr(buff, 'mood_type', None)
            if mood_type is None:
                continue
            buffs.append({
                'buff_class': str(_safe_getattr(buff, '__class__', '') or ''),
                'mood_type': _coerce_int(_safe_getattr(mood_type, 'guid64', 0), 0),
                'mood_weight': _coerce_int(_safe_getattr(buff, 'mood_weight', 0), 0),
            })
    except Exception as e:
        log_exception('engine_facade.sim_mood_buffs: {}'.format(e))
    return buffs


def sim_trait_ids(sim_info):
    """Return a list of trait guids (CommonTraitId ints) the Sim has.

    Uses S4CL's canonical ``CommonTraitUtils.get_trait_ids`` (which reads
    ``sim_info.get_traits()`` and returns each ``Trait.guid64``). Reading
    ``sim_info.trait_tracker.traits`` directly produced a false negative: that
    legacy tracker can expose a different id space than ``CommonTraitId``, so a
    freshly-added trait showed up in ``has_trait`` but not in the raw list.
    """
    trait_ids = []
    if sim_info is None:
        return trait_ids
    try:
        from sims4communitylib.utils.sims.common_trait_utils import CommonTraitUtils
        for tid in CommonTraitUtils.get_trait_ids(sim_info):
            try:
                trait_ids.append(int(tid))
            except (TypeError, ValueError):
                pass
    except Exception as e:
        log_exception('engine_facade.sim_trait_ids: {}'.format(e))
    return trait_ids


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


# ──────────────────────────────────────────────────────────────────────────────
# Object spawning (diary_object probe)
# ──────────────────────────────────────────────────────────────────────────────

def spawn_object_near_sim(object_def_id, sim_info):
    """Spawn a tuned object on the lot at the Sim's location.

    Returns the created ``GameObject`` (or None). Used by the ``diary_object``
    probe to prove a custom object definition is buildable; the caller is
    responsible for destroying the result to avoid save pollution (PC-07).
    """
    if not object_def_id or sim_info is None:
        return None
    try:
        from sims4communitylib.utils.objects.common_object_spawn_utils import CommonObjectSpawnUtils
        from sims4communitylib.utils.sims.common_sim_location_utils import CommonSimLocationUtils
        location = CommonSimLocationUtils.get_location(sim_info)
        return CommonObjectSpawnUtils.spawn_object_on_lot(object_def_id, location)
    except Exception as e:
        log_exception('engine_facade.spawn_object_near_sim: {}'.format(e))
        return None


def destroy_object(game_object):
    """Destroy a GameObject immediately (safe no-op on None)."""
    if game_object is None:
        return False
    try:
        from sims4communitylib.utils.objects.common_object_spawn_utils import CommonObjectSpawnUtils
        return bool(CommonObjectSpawnUtils.destroy_object(game_object))
    except Exception as e:
        log_exception('engine_facade.destroy_object: {}'.format(e))
        return False