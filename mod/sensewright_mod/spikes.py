# Sensewright v2 — Spike Harness & Data Probes
# Python 3.7 compatible
#
# Console commands:
#   sw.spike <name>        — run a named probe (interaction, ui_injection, routing, relationship)
#   sw.smoke_test          — deterministic self-test (~2s, no LLM)
#
# Each probe prints a human summary to the cheat console AND appends a JSON line
# to mod_logs/Sensewright_Spike.log (timestamp + probe name + raw structure).

import services
import sims4.commands
import json
import os
import time
from datetime import datetime

from sims.sim_info import SimInfo
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
from sims4communitylib.utils.sims.common_relationship_utils import CommonRelationshipUtils
from sims4communitylib.utils.sims.common_buff_utils import CommonBuffUtils
from sims4communitylib.utils.common_log_utils import CommonLogUtils

from sensewright_mod.debug_log import log_exception, log_info, log_debug
from sensewright_mod.engine_facade import (
    get_active_sim_info, sim_id_of, sim_info_of, sim_age_stage, sim_gender,
    sim_household_id, sim_room_id, current_interactions, interaction_localized_text,
    interaction_target, social_peers, relationship_edges, spawn_and_visit,
    buff_roundtrip, object_class_name, tuning_resource_loaded,
    find_objects_by_class_name, get_townie_not_on_lot,
    relationship_bits, current_mood, sim_trait_ids, spawn_object_near_sim,
    destroy_object, sim_mood_buffs,
)
# NOTE: `_MOOD_BUFFS` is a reassigned module global in native_hooks (register_mood_buffs
# does `_MOOD_BUFFS = dict(...)`), so it must be accessed via the module, not imported
# by value — importing it snapshots the initial empty dict and the smoke/ui probes
# would always miss the emotion buffs.
from sensewright_mod import native_hooks
from sensewright_mod.tuning import resolve_owned_id

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


# ──────────────────────────────────────────────────────────────────────────────
# Spike log helper
# ──────────────────────────────────────────────────────────────────────────────

_SPIKE_LOG_PATH = None


def _get_spike_log_path():
    """Resolve the spike log file path, creating the directory if needed."""
    global _SPIKE_LOG_PATH
    if _SPIKE_LOG_PATH is not None:
        return _SPIKE_LOG_PATH
    try:
        log_dir = CommonLogUtils.get_mod_logs_location_path()
    except Exception:
        log_dir = None
    if not log_dir:
        # Fallback to Documents/Electronic Arts/The Sims 4/mod_logs
        docs = os.path.expanduser('~/Documents/Electronic Arts/The Sims 4')
        log_dir = os.path.join(docs, 'mod_logs')
    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        pass
    _SPIKE_LOG_PATH = os.path.join(log_dir, 'Sensewright_Spike.log')
    return _SPIKE_LOG_PATH


def _write_spike_log(probe_name, payload):
    """Append a JSON line to the spike log file."""
    try:
        log_path = _get_spike_log_path()
        entry = {
            'timestamp': datetime.now().isoformat(),
            'probe': probe_name,
            'data': payload,
        }
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception as e:
        log_exception('spikes._write_spike_log failed: {}'.format(e))


# ──────────────────────────────────────────────────────────────────────────────
# Probe 1: interaction
# ──────────────────────────────────────────────────────────────────────────────

def _probe_interaction(_connection=None):
    """Read the active Sim's running interaction(s); collect localized action
    text, tuning/class name, target (Sim vs object), relationship bits, and
    social peers. Dump to console + log.

    A Sim mid-conversation has ``queue.running`` plus one or more social
    interactions in ``si_state`` — all are reported, not just the first.
    """
    output = sims4.commands.output
    active_sim_info = get_active_sim_info()
    if active_sim_info is None:
        output('No active sim', _connection)
        _write_spike_log('interaction', {'error': 'no_active_sim'})
        return False

    actor_id = sim_id_of(active_sim_info)
    interactions = current_interactions(active_sim_info)

    payload = {
        'actor_sim_id': actor_id,
        'has_interaction': bool(interactions),
        'interaction_count': len(interactions),
        'interactions': [],
    }

    if not interactions:
        output('Active sim {} has no running interaction'.format(actor_id), _connection)
        # Report the raw diagnostic so a false negative can be debugged.
        payload['diagnostic'] = _interaction_state_diagnostic(active_sim_info)
        _write_spike_log('interaction', payload)
        return True

    output('=== Interaction Probe ({} running) ==='.format(len(interactions)), _connection)
    output('Actor: {} (id={})'.format(
        _safe_getattr(active_sim_info, 'full_name', 'Unknown'), actor_id), _connection)

    for idx, si in enumerate(interactions):
        localized = interaction_localized_text(si)
        class_name = _safe_getattr(si, '__name__', str(si))
        target = interaction_target(si)
        target_id = sim_id_of(target)
        target_class = object_class_name(target)
        target_is_sim = isinstance(target, SimInfo) or (
            target is not None and _safe_getattr(target, 'is_sim', False))

        entry = {
            'index': idx,
            'interaction_class': class_name,
            'interaction_localized': localized,
            'target_sim_id': target_id,
            'target_class': target_class,
            'target_is_sim': target_is_sim,
        }
        payload['interactions'].append(entry)

        output('  [{}] {} [{}]'.format(idx, localized or class_name, class_name), _connection)
        output('       target: {} (id={}, class={}, is_sim={})'.format(
            _safe_getattr(target, 'full_name', target_class), target_id,
            target_class, target_is_sim), _connection)

        # Relationship bits between actor and target (if target is a sim)
        if target_is_sim and target_id:
            target_info = sim_info_of(target)
            if target_info is not None:
                try:
                    friendship = CommonRelationshipUtils.get_friendship_level(active_sim_info, target_info)
                    romance = CommonRelationshipUtils.get_romance_level(active_sim_info, target_info)
                    entry['relationship'] = {
                        'friendship': float(friendship),
                        'romance': float(romance),
                    }
                    output('       relationship: friendship={}, romance={}'.format(
                        friendship, romance), _connection)
                except Exception as e:
                    log_exception('probe_interaction relationship: {}'.format(e))
                    entry['relationship'] = {'error': str(e)}

    # Social peers (from si.social_group)
    peers = social_peers(active_sim_info)
    payload['social_peers'] = peers
    output('Social peers: {}'.format(peers), _connection)

    _write_spike_log('interaction', payload)
    return True


def _interaction_state_diagnostic(sim_info):
    """Return a raw diagnostic of the sim's queue/si_state so a false negative
    (has_interaction=false) can be debugged from the spike log."""
    diag = {'queue_running': None, 'si_state_current': None, 'si_state_count': 0}
    try:
        sim_obj = _safe_call(CommonSimUtils.get_sim_instance, sim_info)
        if sim_obj is not None:
            queue = _safe_getattr(sim_obj, 'queue', None)
            running = _safe_getattr(queue, 'running', None)
            diag['queue_running'] = _safe_getattr(running, '__name__', str(running)) if running is not None else None
            si_state = _safe_getattr(sim_obj, 'si_state', None)
            cur = _safe_getattr(si_state, 'current_interaction', None)
            diag['si_state_current'] = _safe_getattr(cur, '__name__', str(cur)) if cur is not None else None
            try:
                diag['si_state_count'] = sum(1 for _ in si_state) if si_state is not None else 0
            except Exception:
                diag['si_state_count'] = -1
    except Exception as e:
        diag['error'] = str(e)
    return diag
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Probe 2: ui_injection
# ──────────────────────────────────────────────────────────────────────────────

def _probe_ui_injection(_connection=None):
    """Attempt in one shot:
    (a) overwrite a buff/moodlet reason text,
    (b) trigger a sleep balloon over the active Sim,
    (c) read a nearby object's tooltip.
    Report which calls succeeded vs threw (JSON log)."""
    output = sims4.commands.output
    active_sim_info = get_active_sim_info()
    if active_sim_info is None:
        output('No active sim', _connection)
        _write_spike_log('ui_injection', {'error': 'no_active_sim'})
        return False

    actor_id = sim_id_of(active_sim_info)
    payload = {'actor_sim_id': actor_id, 'checks': {}}

    # (a) Overwrite a buff/moodlet reason text
    # Use a known mood buff from _MOOD_BUFFS if available, else try a generic one
    buff_id = 0
    try:
        if native_hooks._MOOD_BUFFS:
            buff_id = next(iter(native_hooks._MOOD_BUFFS.values()))
    except Exception:
        pass
    if buff_id == 0:
        # Fallback: try to find any buff tuning. `manager.types` maps Key -> Buff,
        # so use the instance id (an int), never the raw Key (it is not a buff type
        # and crashes S4CL's add_buff with "no attribute can_add").
        try:
            manager = services.get_instance_manager(sims4.resources.Types.BUFF)
            if manager is not None:
                for key in manager.types.keys():
                    buff_id = int(key.instance)
                    break
        except Exception:
            pass

    buff_result = {'attempted': buff_id != 0, 'buff_id': buff_id, 'ok': False, 'error': ''}
    if buff_id != 0:
        try:
            reason_text = 'Spike test reason {}'.format(int(time.time()))
            result = CommonBuffUtils.add_buff(active_sim_info, buff_id, buff_reason=reason_text)
            buff_result['ok'] = bool(result)
            if not buff_result['ok']:
                buff_result['error'] = 'add_buff returned False'
            # Clean up immediately
            try:
                CommonBuffUtils.remove_buff(active_sim_info, buff_id)
            except Exception:
                pass
        except Exception as e:
            buff_result['ok'] = False
            buff_result['error'] = str(e)
    else:
        buff_result['error'] = 'no buff tuning available'
    payload['checks']['buff_reason'] = buff_result

    # (b) Trigger a sleep balloon over the active Sim
    balloon_result = {'attempted': True, 'ok': False, 'error': ''}
    try:
        sim = _safe_call(CommonSimUtils.get_sim_instance, active_sim_info)
        if sim is not None:
            # Try multiple balloon APIs
            for method_name in ('show_thought_balloon', 'show_speech_balloon'):
                method = _safe_getattr(sim, method_name, None)
                if callable(method):
                    try:
                        method('Zzz...')
                        balloon_result['ok'] = True
                        balloon_result['method'] = method_name
                        break
                    except Exception as e:
                        balloon_result['error'] = str(e)
                        continue
            if not balloon_result['ok']:
                # Try native balloon request. The module is `balloon` (singular)
                # per the decompiled `balloon/balloon_request.py`; the constructor
                # is BalloonRequest(sim, icon, icon_object, overlay, balloon_type,
                # priority, duration, delay, delay_randomization, category_icon, ...).
                try:
                    from balloon.balloon_request import BalloonRequest
                    request = BalloonRequest(active_sim_info, 'Zzz...')
                    request.send()
                    balloon_result['ok'] = True
                    balloon_result['method'] = 'BalloonRequest'
                except Exception as e:
                    balloon_result['error'] = str(e)
        else:
            balloon_result['error'] = 'sim instance not available'
    except Exception as e:
        balloon_result['ok'] = False
        balloon_result['error'] = str(e)
    payload['checks']['balloon'] = balloon_result

    # (c) Read a nearby object's tooltip (mirror/diary/mailbox)
    tooltip_result = {'attempted': True, 'ok': False, 'error': '', 'object_class': '', 'tooltip': ''}
    try:
        for marker in ('mirror', 'diary', 'mailbox', 'journal'):
            objects = find_objects_by_class_name(marker)
            if objects:
                obj = objects[0]
                tooltip_result['object_class'] = object_class_name(obj)
                # Server-side has no `TooltipComponent` (it is a client concept);
                # the engine exposes the object's localized tooltip/display name
                # via a few accessors instead. Try each and report which works.
                try:
                    found = False
                    for attr in ('tooltip_text', 'tooltip', 'display_name'):
                        val = _safe_getattr(obj, attr, None)
                        if val:
                            tooltip_result['tooltip'] = str(val)
                            tooltip_result['ok'] = True
                            tooltip_result['method'] = attr
                            found = True
                            break
                    if not found:
                        tooltip_result['error'] = 'no tooltip accessor returned a value'
                except Exception as e:
                    tooltip_result['error'] = str(e)
                break
        if not tooltip_result['object_class']:
            tooltip_result['error'] = 'no mirror/diary/mailbox found on lot'
    except Exception as e:
        tooltip_result['ok'] = False
        tooltip_result['error'] = str(e)
    payload['checks']['tooltip'] = tooltip_result

    # Console output
    output('=== UI Injection Probe ==='.format(), _connection)
    output('Actor: {} (id={})'.format(_safe_getattr(active_sim_info, 'full_name', 'Unknown'), actor_id), _connection)
    for check_name, check in payload['checks'].items():
        status = 'OK' if check.get('ok') else 'FAIL'
        output('  {}: {} (id={}, method={}, error={})'.format(
            check_name, status, check.get('buff_id', check.get('method', '')),
            check.get('method', ''), check.get('error', '')), _connection)

    _write_spike_log('ui_injection', payload)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Probe 3: routing
# ──────────────────────────────────────────────────────────────────────────────

def _probe_routing(_connection=None):
    """Pick a non-player townie not on the current lot, attempt to spawn/route
    them via create_visit_situation (or RouteToTarget fallback), report the
    situation id and routing success/failure."""
    output = sims4.commands.output
    active_sim_info = get_active_sim_info()
    if active_sim_info is None:
        output('No active sim', _connection)
        _write_spike_log('routing', {'error': 'no_active_sim'})
        return False

    actor_id = sim_id_of(active_sim_info)
    payload = {'actor_sim_id': actor_id}

    # Find a townie not on lot
    townie = get_townie_not_on_lot(active_sim_info)
    if townie is None:
        output('No suitable townie found off-lot', _connection)
        payload['error'] = 'no_townie_found'
        _write_spike_log('routing', payload)
        return True

    townie_id = sim_id_of(townie)
    payload['townie_sim_id'] = townie_id
    payload['townie_name'] = _safe_getattr(townie, 'full_name', 'Unknown')

    output('Found townie: {} (id={})'.format(payload['townie_name'], townie_id), _connection)

    # Spawn and start visit situation
    result = spawn_and_visit(townie)
    payload['spawn_result'] = result

    if result.get('ok'):
        output('Visit situation started: situation_id={}'.format(result.get('situation_id')), _connection)
    else:
        output('Visit situation failed: {}'.format(result.get('error')), _connection)

    _write_spike_log('routing', payload)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Probe 4: relationship
# ──────────────────────────────────────────────────────────────────────────────

def _probe_relationship(_connection=None):
    """Read the active Sim + a target Sim, extract friendship/romance/sentiments
    and known relationship bits; dump numeric values + sentiment names to console + JSON."""
    output = sims4.commands.output
    active_sim_info = get_active_sim_info()
    if active_sim_info is None:
        output('No active sim', _connection)
        _write_spike_log('relationship', {'error': 'no_active_sim'})
        return False

    actor_id = sim_id_of(active_sim_info)
    payload = {'actor_sim_id': actor_id, 'actor_name': _safe_getattr(active_sim_info, 'full_name', 'Unknown')}

    # Get a target sim (first social peer, or first relationship edge, or any other sim)
    target_id = 0
    target_info = None

    # Try social peers first
    peers = social_peers(active_sim_info)
    if peers:
        target_id = peers[0]
        target_info = services.sim_info_manager().get(target_id)

    # Fallback: first relationship edge
    if target_info is None:
        edges = relationship_edges(active_sim_info)
        if edges:
            target_id = edges[0]['target_sim_id']
            target_info = services.sim_info_manager().get(target_id)

    # Fallback: any other sim in active household
    if target_info is None:
        try:
            active_household = services.active_household()
            if active_household is not None:
                for sim_info in active_household.sim_infos:
                    if sim_info is not None and sim_info.id != actor_id:
                        target_info = sim_info
                        target_id = sim_id_of(sim_info)
                        break
        except Exception:
            pass

    if target_info is None:
        output('No target sim found for relationship probe', _connection)
        payload['error'] = 'no_target_sim'
        _write_spike_log('relationship', payload)
        return True

    payload['target_sim_id'] = target_id
    payload['target_name'] = _safe_getattr(target_info, 'full_name', 'Unknown')

    # Friendship / Romance
    try:
        friendship = CommonRelationshipUtils.get_friendship_level(active_sim_info, target_info)
        romance = CommonRelationshipUtils.get_romance_level(active_sim_info, target_info)
        payload['friendship'] = float(friendship)
        payload['romance'] = float(romance)
    except Exception as e:
        log_exception('probe_relationship friendship/romance: {}'.format(e))
        payload['friendship'] = 0.0
        payload['romance'] = 0.0
        payload['track_error'] = str(e)

    # Relationship bits (sentiments, family, etc.)
    bits = []
    try:
        rels = CommonRelationshipUtils.get_relationships_gen(active_sim_info)
        for rel in rels:
            other_id = _coerce_int(_safe_call(getattr(rel, 'get_other_sim_id', None), actor_id), 0)
            a = _coerce_int(_safe_getattr(rel, 'sim_id_a', 0), 0)
            b = _coerce_int(_safe_getattr(rel, 'sim_id_b', 0), 0)
            if other_id == target_id or (a == actor_id and b == target_id) or (b == actor_id and a == target_id):
                all_bits = _safe_call(getattr(rel, 'get_all_bits', None))
                if all_bits:
                    for bit in all_bits:
                        bit_name = _safe_getattr(bit, '__name__', str(bit))
                        bits.append(str(bit_name))
                break
    except Exception as e:
        log_exception('probe_relationship bits: {}'.format(e))
        payload['bits_error'] = str(e)

    payload['bits'] = bits

    # Console output
    output('=== Relationship Probe ==='.format(), _connection)
    output('Actor: {} (id={})'.format(payload['actor_name'], actor_id), _connection)
    output('Target: {} (id={})'.format(payload['target_name'], target_id), _connection)
    output('Friendship: {}'.format(payload['friendship']), _connection)
    output('Romance: {}'.format(payload['romance']), _connection)
    output('Bits ({}):'.format(len(bits)), _connection)
    for bit in bits[:20]:  # Limit output
        output('  - {}'.format(bit), _connection)
    if len(bits) > 20:
        output('  ... and {} more'.format(len(bits) - 20), _connection)

    _write_spike_log('relationship', payload)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers for the phase-2 probes
# ──────────────────────────────────────────────────────────────────────────────

def _find_target_sim_info(active_sim_info):
    """Resolve a target SimInfo for relationship probes (never the actor itself).

    Order: first social peer, then first relationship edge, then any other
    member of the active household, then any other instanced Sim on the lot.
    Every candidate is filtered against the actor id — the previous version
    returned the actor when ``social_peers`` included the actor's own id
    (a social group contains the actor too), which made ``relationship_bits``
    read a self-relationship (empty) instead of a real pair.
    """
    if active_sim_info is None:
        return None
    actor_id = sim_id_of(active_sim_info)
    for pid in social_peers(active_sim_info):
        if pid and pid != actor_id:
            info = services.sim_info_manager().get(pid)
            if info is not None:
                return info
    for edge in relationship_edges(active_sim_info):
        tid = _coerce_int(edge.get('target_sim_id', 0), 0)
        if tid and tid != actor_id:
            info = services.sim_info_manager().get(tid)
            if info is not None:
                return info
    try:
        household = services.active_household()
        if household is not None:
            for sim_info in household.sim_infos:
                if sim_info is None:
                    continue
                sid = sim_id_of(sim_info)
                if sid and sid != actor_id:
                    return sim_info
    except Exception:
        pass
    try:
        for sim_info in CommonSimUtils.get_instanced_sim_info_for_all_sims_generator():
            if sim_info is None:
                continue
            sid = sim_id_of(sim_info)
            if sid and sid != actor_id:
                return sim_info
    except Exception:
        pass
    return None


def _relationship_bit_names():
    """Build {guid64: name} from S4CL CommonRelationshipBitId (defensive)."""
    mapping = {}
    try:
        from sims4communitylib.enums.relationship_bits_enum import CommonRelationshipBitId
        for member in CommonRelationshipBitId:
            try:
                mapping[int(member.value)] = str(member.name)
            except Exception:
                continue
    except Exception as e:
        log_exception('spikes._relationship_bit_names: {}'.format(e))
    return mapping


def _sentiment_names():
    """Build {guid64: name} from the long/short-term sentiment enums (defensive)."""
    mapping = {}
    try:
        from sims4communitylib.enums.long_term_sentiments_enum import CommonLongTermSentimentId
        for member in CommonLongTermSentimentId:
            try:
                mapping[int(member.value)] = str(member.name)
            except Exception:
                continue
    except Exception:
        pass
    try:
        from sims4communitylib.enums.short_term_sentiments_enum import CommonShortTermSentimentId
        for member in CommonShortTermSentimentId:
            try:
                mapping[int(member.value)] = str(member.name)
            except Exception:
                continue
    except Exception:
        pass
    return mapping


def _as_bool(value):
    """Coerce an S4CL CommonTestResult/CommonExecutionResult (or bool) to bool."""
    if value is None:
        return False
    try:
        return bool(value)
    except Exception:
        return False


def _public_properties(cls):
    """Return the public property names of a class (defensive introspection)."""
    names = []
    try:
        for attr in dir(cls):
            if attr.startswith('_'):
                continue
            try:
                if isinstance(getattr(cls, attr, None), property):
                    names.append(attr)
            except Exception:
                continue
    except Exception:
        pass
    return names


def _probe_sentiments(actor_info, target_info):
    """Best-effort read of the sentiments between two Sims.

    The decompiled source exposes ``Relationship.sentiment_track_tracker(sim_id)``
    but the full tracker API was not extracted; probe several accessors and
    report whatever is found so the next integration can target reality.
    """
    result = {'found': False, 'error': '', 'items': [], 'name_map': {}}
    try:
        actor_id = sim_id_of(actor_info)
        target_id = sim_id_of(target_info)
        tracker = _safe_getattr(actor_info, 'relationship_tracker', None)
        if tracker is None:
            result['error'] = 'no relationship tracker'
            return result
        relationship = None
        for rel in tracker:
            other = _coerce_int(_safe_call(getattr(rel, 'get_other_sim_id', None), actor_id), 0)
            if not other:
                a = _coerce_int(_safe_getattr(rel, 'sim_id_a', 0), 0)
                b = _coerce_int(_safe_getattr(rel, 'sim_id_b', 0), 0)
                other = b if a == actor_id else a
            if other == target_id:
                relationship = rel
                break
        if relationship is None:
            result['error'] = 'no relationship object between actor and target'
            return result
        # sentiment_track_tracker(sim_id) is the engine entry point.
        stt_fn = _safe_getattr(relationship, 'sentiment_track_tracker', None)
        if callable(stt_fn):
            stt = _safe_call(stt_fn, actor_id)
            if stt is not None:
                result['found'] = True
                result['tracker_repr'] = str(stt)[:300]
                items = []
                try:
                    for item in stt:
                        items.append(_describe_sentiment(item))
                except Exception as e:
                    result['iter_error'] = str(e)
                result['items'] = items
        # Fallback accessors on the relationship object itself.
        fallback = {}
        for attr in ('sentiments', 'sentiment_tracks', 'get_sentiments', 'get_sentiment_tracks'):
            val = _safe_getattr(relationship, attr, None)
            if callable(val):
                val = _safe_call(val)
            if val is not None:
                fallback[attr] = str(val)[:200]
        if fallback:
            result['fallback'] = fallback
            result['found'] = True
        result['name_map'] = _sentiment_names()
    except Exception as e:
        result['error'] = str(e)
    return result


def _describe_sentiment(item):
    if item is None:
        return None
    return {
        'type': str(object_class_name(item)),
        'guid64': _coerce_int(_safe_getattr(item, 'guid64', 0), 0),
        'name': str(_safe_getattr(item, '__name__', '') or ''),
    }


# ──────────────────────────────────────────────────────────────────────────────
# Probe 5: relationship_bits (bits + sentiments)
# ──────────────────────────────────────────────────────────────────────────────

def _probe_relationship_bits(_connection=None):
    """Prove the correct accessor for relationship bits + sentiments.

    The old ``relationship`` probe read ``Relationship.get_all_bits()`` (no args),
    which does not exist on the vanilla object (it lives on the tracker) and
    always returned ``[]``. This probe uses ``relationship_tracker.get_all_bits``
    and reverse-maps each ``guid64`` to a ``CommonRelationshipBitId`` name, then
    best-effort reads sentiments. Unblocks `sim.social` tier,
    `mem.relationship.review` and sentiment feedback.
    """
    output = sims4.commands.output
    active_sim_info = get_active_sim_info()
    if active_sim_info is None:
        output('No active sim', _connection)
        _write_spike_log('relationship_bits', {'error': 'no_active_sim'})
        return False

    actor_id = sim_id_of(active_sim_info)
    target_info = _find_target_sim_info(active_sim_info)
    if target_info is None:
        output('No target sim found', _connection)
        _write_spike_log('relationship_bits', {'actor_sim_id': actor_id, 'error': 'no_target_sim'})
        return True

    payload = {
        'actor_sim_id': actor_id,
        'actor_name': _safe_getattr(active_sim_info, 'full_name', 'Unknown'),
        'target_sim_id': sim_id_of(target_info),
        'target_name': _safe_getattr(target_info, 'full_name', 'Unknown'),
    }

    try:
        payload['friendship'] = float(CommonRelationshipUtils.get_friendship_level(active_sim_info, target_info))
        payload['romance'] = float(CommonRelationshipUtils.get_romance_level(active_sim_info, target_info))
    except Exception as e:
        payload['track_error'] = str(e)

    bits_result = relationship_bits(active_sim_info, target_info)
    payload['tracker_get_all_bits'] = bits_result

    name_by_id = _relationship_bit_names()
    mapped = []
    for bit in bits_result.get('bits', []):
        entry = dict(bit)
        entry['mapped_name'] = name_by_id.get(bit.get('guid64', 0), '')
        mapped.append(entry)
    payload['bits_mapped'] = mapped

    payload['sentiments'] = _probe_sentiments(active_sim_info, target_info)

    output('=== Relationship Bits Probe ===', _connection)
    output('Actor {} <-> Target {}'.format(payload['actor_name'], payload['target_name']), _connection)
    output('friendship={} romance={}'.format(payload.get('friendship'), payload.get('romance')), _connection)
    output('bits ({}) via relationship_tracker.get_all_bits:'.format(len(bits_result.get('bits', []))), _connection)
    for bit in mapped:
        output('  - guid64={} name={} mapped={}'.format(bit.get('guid64'), bit.get('name'), bit.get('mapped_name')), _connection)
    if bits_result.get('error'):
        output('bit accessor error: {}'.format(bits_result['error']), _connection)
    output('sentiments: {}'.format(payload['sentiments']), _connection)

    _write_spike_log('relationship_bits', payload)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Probe 6: mood_effect (does a mood buff actually move the mood)
# ──────────────────────────────────────────────────────────────────────────────

def _probe_mood_effect(_connection=None):
    """Prove applying buff_mood_happy actually moves the Sim's mood.

    The buff *applies* without error (proven), but whether the mood changes was
    never confirmed. Reads ``SimInfo.get_mood()`` before/after and compares the
    ``guid64`` against HAPPY (14640).
    """
    output = sims4.commands.output
    active_sim_info = get_active_sim_info()
    if active_sim_info is None:
        output('No active sim', _connection)
        _write_spike_log('mood_effect', {'error': 'no_active_sim'})
        return False

    actor_id = sim_id_of(active_sim_info)
    happy_buff_id = resolve_owned_id('mood_buff_happy')
    happy_mood_id = 14640  # CommonMoodId.HAPPY

    before = current_mood(active_sim_info)
    payload = {
        'actor_sim_id': actor_id,
        'happy_buff_id': happy_buff_id,
        'happy_mood_id': happy_mood_id,
        'before': before,
        'buffs_before': sim_mood_buffs(active_sim_info),
        'apply_ok': False,
        'after': {},
        'buffs_after': [],
        'moved_to_happy': False,
        'error': '',
    }

    if not happy_buff_id:
        payload['error'] = 'mood_buff_happy tuning id unresolved'
        _write_spike_log('mood_effect', payload)
        output('mood_effect: {}'.format(payload['error']), _connection)
        return True

    applied = native_hooks.apply_buff(active_sim_info, happy_buff_id, 90)
    payload['apply_ok'] = _as_bool(applied)
    if not payload['apply_ok']:
        payload['error'] = 'apply_buff returned False'
    else:
        after = current_mood(active_sim_info)
        payload['after'] = after
        payload['buffs_after'] = sim_mood_buffs(active_sim_info)
        live_guid = after.get('sim_guid64', after.get('guid64', 0))
        payload['moved_to_happy'] = (live_guid == happy_mood_id)
        native_hooks.remove_buff(active_sim_info, happy_buff_id)

    output('=== Mood Effect Probe ===', _connection)
    output('before: {}'.format(before), _connection)
    output('buffs_before: {}'.format(payload['buffs_before']), _connection)
    output('apply buff_mood_happy({}): {}'.format(happy_buff_id, payload['apply_ok']), _connection)
    output('after: {}'.format(payload['after']), _connection)
    output('buffs_after: {}'.format(payload['buffs_after']), _connection)
    output('moved_to_happy (live guid=={}): {}'.format(happy_mood_id, payload['moved_to_happy']), _connection)

    _write_spike_log('mood_effect', payload)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Probe 7: lifecycle (death / marriage / birth wiring + payload shape)
# ──────────────────────────────────────────────────────────────────────────────

def _probe_lifecycle(_connection=None):
    """Report the lifecycle listener wiring and event payload shapes.

    death/marriage/birth S4CL events are registered in lifecycle_hooks but never
    exercised in-game. This probe reports: listener registration, the payload
    fields each event exposes (introspected from the S4CL event classes), the
    current pre-session buffer / marriage snapshot state, and a marriage-marker
    dry-run against the active Sim's real relationship bits. A real death/birth
    must still be observed in-game; this confirms the wiring and the data shapes.
    """
    output = sims4.commands.output
    payload = {'checks': {}}

    lh = None
    try:
        import sensewright_mod.lifecycle_hooks as lh
    except Exception as e:
        payload['listeners'] = {'error': str(e)}

    # 1. lifecycle_hooks registration + state.
    if lh is not None:
        payload['listeners'] = {
            's4cl_available': bool(_safe_getattr(lh, '_S4CL_AVAILABLE', False)),
            'lifecycle_ready': bool(lh.is_lifecycle_ready()),
            'event_buffer_len': len(_safe_getattr(lh, '_event_buffer', []) or []),
            'event_buffer_max': int(_safe_getattr(lh, '_EVENT_BUFFER_MAX', 0) or 0),
            'known_marriage_pairs': len(_safe_getattr(lh, '_known_marriage_pairs', set()) or set()),
            'marriage_markers': list(_safe_getattr(lh, '_MARRIAGE_MARKERS', ()) or ()),
            'handlers': {
                'death': callable(_safe_getattr(lh, '_handle_sim_died', None)),
                'pregnancy': callable(_safe_getattr(lh, '_handle_pregnancy_ended', None)),
                'relationship_bit': callable(_safe_getattr(lh, '_handle_relationship_bit_added', None)),
            },
        }

    # 2. Event payload fields (introspected from the S4CL classes).
    payload['event_fields'] = {}
    try:
        from sims4communitylib.events.sim.events.sim_died import S4CLSimDiedEvent
        from sims4communitylib.events.sim.events.sim_pregnancy_ended import S4CLSimPregnancyEndedEvent
        from sims4communitylib.events.sim.events.sim_relationship_bit_added import S4CLSimRelationshipBitAddedEvent
        payload['event_fields']['S4CLSimDiedEvent'] = _public_properties(S4CLSimDiedEvent)
        payload['event_fields']['S4CLSimPregnancyEndedEvent'] = _public_properties(S4CLSimPregnancyEndedEvent)
        payload['event_fields']['S4CLSimRelationshipBitAddedEvent'] = _public_properties(S4CLSimRelationshipBitAddedEvent)
    except Exception as e:
        payload['event_fields']['error'] = str(e)

    # 3. Marriage-marker dry-run on the active Sim's real bits.
    active_sim_info = get_active_sim_info()
    target_info = _find_target_sim_info(active_sim_info) if active_sim_info is not None else None
    if active_sim_info is not None and target_info is not None:
        bits_result = relationship_bits(active_sim_info, target_info)
        name_by_id = _relationship_bit_names()
        markers = tuple(_safe_getattr(lh, '_MARRIAGE_MARKERS', ()) or ()) if lh is not None else ()
        matched = []
        for bit in bits_result.get('bits', []):
            guid = bit.get('guid64', 0)
            name = name_by_id.get(guid, '') or bit.get('name', '')
            if any(m in str(name).lower() for m in markers):
                matched.append({'guid64': guid, 'name': name})
        payload['marriage_dry_run'] = {
            'target_sim_id': sim_id_of(target_info),
            'matched_bits': matched,
        }
    else:
        payload['marriage_dry_run'] = {'error': 'no active/target sim'}

    output('=== Lifecycle Probe ===', _connection)
    output('listeners: {}'.format(payload['listeners']), _connection)
    output('event_fields: {}'.format(payload['event_fields']), _connection)
    output('marriage_dry_run: {}'.format(payload['marriage_dry_run']), _connection)

    _write_spike_log('lifecycle', payload)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Probe 8: diary_object (custom diary placement)
# ──────────────────────────────────────────────────────────────────────────────

def _probe_diary_object(_connection=None):
    """Prove the custom sw_diary_object tuning is buildable/spawnable.

    The smoke test reports ``object:diary found=0`` (the custom object is never
    placed). Spawn it near the active Sim, report the definition/instance and its
    affordances, then destroy it immediately to avoid save pollution (PC-07).
    """
    output = sims4.commands.output
    active_sim_info = get_active_sim_info()
    object_def_id = resolve_owned_id('object_diary')

    payload = {
        'object_def_id': object_def_id,
        'active_sim_id': 0,
        'loaded': False,
        'spawned': False,
        'object_id': 0,
        'class_name': '',
        'affordances': [],
        'destroyed': False,
        'error': '',
    }

    if object_def_id:
        try:
            from sims4.resources import Types
            manager = services.get_instance_manager(Types.OBJECT)
            payload['loaded'] = manager is not None and manager.get(object_def_id) is not None
        except Exception as e:
            payload['error'] = 'definition check failed: {}'.format(e)

    if active_sim_info is None:
        payload['error'] = payload['error'] or 'no active sim'
        _write_spike_log('diary_object', payload)
        output('diary_object: {}'.format(payload), _connection)
        return True

    payload['active_sim_id'] = sim_id_of(active_sim_info)

    if not object_def_id:
        payload['error'] = 'object_diary tuning id unresolved'
        _write_spike_log('diary_object', payload)
        output('diary_object: {}'.format(payload), _connection)
        return True

    game_object = spawn_object_near_sim(object_def_id, active_sim_info)
    if game_object is None:
        payload['spawned'] = False
        payload['error'] = payload['error'] or 'spawn_object_near_sim returned None'
    else:
        payload['spawned'] = True
        payload['object_id'] = _coerce_int(_safe_getattr(game_object, 'id', 0), 0)
        payload['class_name'] = object_class_name(game_object)
        try:
            affordances = []
            for attr in ('super_affordances', '_super_affordances'):
                for aff in _safe_getattr(game_object, attr, ()) or ():
                    affordances.append(str(aff)[:120])
                if affordances:
                    break
            payload['affordances'] = affordances
        except Exception as e:
            payload['affordances'] = []
            payload['affordances_error'] = str(e)
        # Always destroy, even if introspection above failed (PC-07).
        payload['destroyed'] = _as_bool(destroy_object(game_object))

    output('=== Diary Object Probe ===', _connection)
    output('object_def_id={} loaded={}'.format(object_def_id, payload['loaded']), _connection)
    output('spawned={} object_id={} class={}'.format(
        payload['spawned'], payload.get('object_id'), payload.get('class_name', '')), _connection)
    output('affordances={}'.format(payload['affordances']), _connection)
    output('destroyed={}'.format(payload['destroyed']), _connection)
    if payload['error']:
        output('error: {}'.format(payload['error']), _connection)

    _write_spike_log('diary_object', payload)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Probe 9: trait_levers (traits + relationship bits stick)
# ──────────────────────────────────────────────────────────────────────────────

def _probe_trait_levers(_connection=None):
    """Prove the trait + relationship-bit levers (evo.trait P31) stick.

    Add/remove a base-game trait (SELF_ASSURED) and a relationship bit
    (FRIENDSHIP_FRIEND) via native_hooks, verifying each with has_* checks, and
    always clean up (remove what was added) so the save is left unchanged.
    """
    output = sims4.commands.output
    active_sim_info = get_active_sim_info()
    if active_sim_info is None:
        output('No active sim', _connection)
        _write_spike_log('trait_levers', {'error': 'no_active_sim'})
        return False

    actor_id = sim_id_of(active_sim_info)
    target_info = _find_target_sim_info(active_sim_info)

    try:
        from sims4communitylib.enums.traits_enum import CommonTraitId
        trait_id = int(CommonTraitId.SELF_ASSURED)
    except Exception:
        trait_id = 16824  # CommonTraitId.SELF_ASSURED

    try:
        from sims4communitylib.enums.relationship_bits_enum import CommonRelationshipBitId
        bit_id = int(CommonRelationshipBitId.FRIENDSHIP_FRIEND)
    except Exception:
        bit_id = 15797  # CommonRelationshipBitId.FRIENDSHIP_FRIEND

    payload = {
        'actor_sim_id': actor_id,
        'target_sim_id': sim_id_of(target_info) if target_info is not None else 0,
        'trait': {},
        'relationship_bit': {},
    }

    # Trait lever (SELF_ASSURED).
    trait = payload['trait']
    trait['id'] = trait_id
    trait['had_before'] = _as_bool(native_hooks.has_trait(active_sim_info, trait_id))
    trait['in_trait_list_before'] = trait_id in sim_trait_ids(active_sim_info)
    trait['add_ok'] = _as_bool(native_hooks.set_trait(active_sim_info, trait_id))
    trait['has_after_add'] = _as_bool(native_hooks.has_trait(active_sim_info, trait_id))
    trait['in_trait_list_after'] = trait_id in sim_trait_ids(active_sim_info)
    if not trait['had_before']:
        trait['remove_ok'] = _as_bool(native_hooks.remove_trait(active_sim_info, trait_id))
        trait['has_after_remove'] = _as_bool(native_hooks.has_trait(active_sim_info, trait_id))
    else:
        trait['remove_ok'] = True  # leave the pre-existing trait untouched
        trait['has_after_remove'] = trait['had_before']

    # Relationship bit lever (FRIENDSHIP_FRIEND).
    relbit = payload['relationship_bit']
    relbit['id'] = bit_id
    relbit['usable'] = target_info is not None
    if target_info is not None:
        relbit['had_before'] = _as_bool(native_hooks.has_relationship_bit(active_sim_info, target_info, bit_id))
        relbit['add_ok'] = _as_bool(native_hooks.add_relationship_bit(active_sim_info, target_info, bit_id))
        relbit['has_after_add'] = _as_bool(native_hooks.has_relationship_bit(active_sim_info, target_info, bit_id))
        if not relbit['had_before']:
            relbit['remove_ok'] = _as_bool(native_hooks.remove_relationship_bit(active_sim_info, target_info, bit_id))
            relbit['has_after_remove'] = _as_bool(native_hooks.has_relationship_bit(active_sim_info, target_info, bit_id))
        else:
            relbit['remove_ok'] = True
            relbit['has_after_remove'] = relbit['had_before']
    else:
        relbit['error'] = 'no target sim'

    output('=== Trait Levers Probe ===', _connection)
    output('trait: {}'.format(trait), _connection)
    output('relationship_bit: {}'.format(relbit), _connection)

    _write_spike_log('trait_levers', payload)
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Smoke test
# ──────────────────────────────────────────────────────────────────────────────

def _smoke_test(_connection=None):
    """Deterministic self-test (~2s, NO LLM):
    - Check tuning resources are loaded (best-effort via InstanceManager)
    - Active Sim's age/gender/room_id/relationship_tracker return valid types
    - Mirror/mailbox/diary object resolution on current lot (by class name)
    - One emotion-buff add+remove roundtrip that completes silently
    Print PASS/FAIL summary line per check and the total to the console."""
    output = sims4.commands.output
    output('=== Sensewright Smoke Test ===', _connection)

    checks = []
    active_sim_info = get_active_sim_info()

    def check(name, condition, detail=''):
        status = 'PASS' if condition else 'FAIL'
        msg = '  [{}] {}'.format(status, name)
        if detail:
            msg += ' — {}'.format(detail)
        output(msg, _connection)
        checks.append((name, condition, detail))
        return condition

    # 1. Tuning resources loaded
    tuning_checks = [
        ('interaction_mirror_reflect', sims4.resources.Types.INTERACTION, 'interaction_mirror_reflect'),
        ('interaction_diary_read', sims4.resources.Types.INTERACTION, 'interaction_diary_read'),
        ('interaction_diary_snoop', sims4.resources.Types.INTERACTION, 'interaction_diary_snoop'),
        ('interaction_mailbox', sims4.resources.Types.INTERACTION, 'interaction_mailbox'),
        ('situation_visit', sims4.resources.Types.SITUATION, 'situation_visit'),
        ('trait_hidden_no_walkby', sims4.resources.Types.TRAIT, 'trait_hidden_no_walkby'),
        ('buff_dream_epiphany', sims4.resources.Types.BUFF, 'buff_dream_epiphany'),
        ('buff_dream_surreal', sims4.resources.Types.BUFF, 'buff_dream_surreal'),
        ('buff_dream_omen', sims4.resources.Types.BUFF, 'buff_dream_omen'),
        ('buff_dream_nightmare', sims4.resources.Types.BUFF, 'buff_dream_nightmare'),
        ('buff_missing_player', sims4.resources.Types.BUFF, 'buff_missing_player'),
    ]
    tuning_passed = 0
    for label, type_enum, key in tuning_checks:
        tid = resolve_owned_id(key)
        loaded = tuning_resource_loaded(type_enum, tid) if tid else False
        if check('tuning:{}'.format(label), loaded, 'id={}'.format(tid)):
            tuning_passed += 1
    check('tuning_summary', tuning_passed > 0, '{}/{} loaded'.format(tuning_passed, len(tuning_checks)))

    # 2. Active Sim basic fields
    if active_sim_info is not None:
        actor_id = sim_id_of(active_sim_info)
        age = sim_age_stage(active_sim_info)
        gender = sim_gender(active_sim_info)
        household_id = sim_household_id(active_sim_info)
        room_id = sim_room_id(active_sim_info)
        check('active_sim:age', bool(age), 'age={}'.format(age))
        check('active_sim:gender', gender in ('M', 'F', 'N'), 'gender={}'.format(gender))
        check('active_sim:household_id', household_id > 0, 'household_id={}'.format(household_id))
        check('active_sim:room_id', room_id >= 0, 'room_id={}'.format(room_id))
        # relationship_tracker existence
        rt = _safe_getattr(active_sim_info, 'relationship_tracker', None)
        check('active_sim:relationship_tracker', rt is not None, 'tracker={}'.format(type(rt).__name__ if rt else 'None'))
    else:
        check('active_sim:exists', False, 'no active sim')

    # 3. Object resolution on lot
    for marker in ('mirror', 'mailbox', 'diary', 'journal'):
        objects = find_objects_by_class_name(marker)
        check('object:{}'.format(marker), len(objects) > 0, 'found={}'.format(len(objects)))

    # 4. Emotion buff roundtrip
    buff_id = 0
    try:
        if native_hooks._MOOD_BUFFS:
            buff_id = next(iter(native_hooks._MOOD_BUFFS.values()))
    except Exception:
        pass
    if buff_id == 0 and active_sim_info is not None:
        # Try any buff (convert the raw Key to its int instance id).
        try:
            manager = services.get_instance_manager(sims4.resources.Types.BUFF)
            if manager is not None:
                for key in manager.types.keys():
                    buff_id = int(key.instance)
                    break
        except Exception:
            pass

    if buff_id != 0 and active_sim_info is not None:
        result = buff_roundtrip(active_sim_info, buff_id)
        check('buff_roundtrip', result.get('ok', False), 'buff_id={}, error={}'.format(buff_id, result.get('error', '')))
    else:
        check('buff_roundtrip', False, 'no buff tuning available')

    # Summary
    passed = sum(1 for _, ok, _ in checks if ok)
    total = len(checks)
    output('', _connection)
    output('=== Smoke Test Summary: {}/{} passed ==='.format(passed, total), _connection)
    if passed == total:
        output('ALL CHECKS PASSED', _connection)
    else:
        output('SOME CHECKS FAILED', _connection)

    # Log
    _write_spike_log('smoke_test', {
        'passed': passed,
        'total': total,
        'checks': [{'name': n, 'passed': ok, 'detail': d} for n, ok, d in checks],
    })
    return True


# ──────────────────────────────────────────────────────────────────────────────
# Command dispatch
# ──────────────────────────────────────────────────────────────────────────────

_PROBE_DISPATCH = {
    'interaction': _probe_interaction,
    'ui_injection': _probe_ui_injection,
    'ui': _probe_ui_injection,
    'routing': _probe_routing,
    'relationship': _probe_relationship,
    'relationship_bits': _probe_relationship_bits,
    'mood_effect': _probe_mood_effect,
    'lifecycle': _probe_lifecycle,
    'diary_object': _probe_diary_object,
    'trait_levers': _probe_trait_levers,
}


@sims4.commands.Command('sw.spike', command_type=sims4.commands.CommandType.Live)
def cmd_sw_spike(probe_name=None, _connection=None):
    """Run a spike probe by name.
    Usage: sw.spike <interaction|ui_injection|ui|routing|relationship|relationship_bits|mood_effect|lifecycle|diary_object|trait_levers>
    """
    output = sims4.commands.output
    if probe_name is None:
        output('Usage: sw.spike <probe>', _connection)
        output('Available probes: {}'.format(', '.join(sorted(set(_PROBE_DISPATCH.keys())))), _connection)
        return False

    probe_name = probe_name.lower()
    handler = _PROBE_DISPATCH.get(probe_name)
    if handler is None:
        output('Unknown probe: {}. Available: {}'.format(probe_name, ', '.join(sorted(set(_PROBE_DISPATCH.keys())))), _connection)
        return False

    try:
        return handler(_connection)
    except Exception as e:
        log_exception('sw.spike {} failed: {}'.format(probe_name, e))
        output('Probe {} crashed: {}'.format(probe_name, e), _connection)
        _write_spike_log(probe_name, {'error': 'probe_crashed', 'exception': str(e)})
        return False


@sims4.commands.Command('sw.smoke_test', command_type=sims4.commands.CommandType.Live)
def cmd_sw_smoke_test(_connection=None):
    """Run the deterministic smoke test (no LLM)."""
    try:
        return _smoke_test(_connection)
    except Exception as e:
        log_exception('sw.smoke_test failed: {}'.format(e))
        sims4.commands.output('Smoke test crashed: {}'.format(e), _connection)
        _write_spike_log('smoke_test', {'error': 'crashed', 'exception': str(e)})
        return False