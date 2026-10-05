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
    sim_household_id, sim_room_id, current_interaction, interaction_localized_text,
    interaction_target, social_peers, relationship_edges, spawn_and_visit,
    buff_roundtrip, object_class_name, tuning_resource_loaded,
    find_objects_by_class_name, get_townie_not_on_lot,
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
    """Read the active Sim's current interaction; collect localized action text,
    tuning/class name, target (Sim vs object), and relationship bits between
    actor and target. Dump to console + log."""
    output = sims4.commands.output
    active_sim_info = get_active_sim_info()
    if active_sim_info is None:
        output('No active sim', _connection)
        _write_spike_log('interaction', {'error': 'no_active_sim'})
        return False

    actor_id = sim_id_of(active_sim_info)
    si = current_interaction(active_sim_info)

    payload = {
        'actor_sim_id': actor_id,
        'has_interaction': si is not None,
    }

    if si is None:
        output('Active sim {} has no current interaction'.format(actor_id), _connection)
        _write_spike_log('interaction', payload)
        return True

    # Interaction details
    localized = interaction_localized_text(si)
    class_name = _safe_getattr(si, '__name__', str(si))
    target = interaction_target(si)
    target_id = sim_id_of(target)
    target_class = object_class_name(target)
    target_is_sim = isinstance(target, SimInfo) or (target is not None and _safe_getattr(target, 'is_sim', False))

    payload.update({
        'interaction_class': class_name,
        'interaction_localized': localized,
        'target_sim_id': target_id,
        'target_class': target_class,
        'target_is_sim': target_is_sim,
    })

    # Relationship bits between actor and target (if target is a sim)
    if target_is_sim and target_id:
        target_info = sim_info_of(target)
        if target_info is not None:
            try:
                friendship = CommonRelationshipUtils.get_friendship_level(active_sim_info, target_info)
                romance = CommonRelationshipUtils.get_romance_level(active_sim_info, target_info)
                payload['relationship'] = {
                    'friendship': float(friendship),
                    'romance': float(romance),
                }
            except Exception as e:
                log_exception('probe_interaction relationship: {}'.format(e))
                payload['relationship'] = {'error': str(e)}

    # Social peers
    peers = social_peers(active_sim_info)
    payload['social_peers'] = peers

    # Console output
    output('=== Interaction Probe ==='.format(), _connection)
    output('Actor: {} (id={})'.format(_safe_getattr(active_sim_info, 'full_name', 'Unknown'), actor_id), _connection)
    output('Interaction: {} [{}]'.format(localized, class_name), _connection)
    output('Target: {} (id={}, class={}, is_sim={})'.format(
        _safe_getattr(target, 'full_name', target_class), target_id, target_class, target_is_sim), _connection)
    if 'relationship' in payload:
        rel = payload['relationship']
        output('Relationship: friendship={}, romance={}'.format(rel.get('friendship'), rel.get('romance')), _connection)
    output('Social peers: {}'.format(peers), _connection)

    _write_spike_log('interaction', payload)
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
                # Try native balloon request
                try:
                    from balloons.balloon_request import BalloonRequest
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
                # Try to get tooltip component
                try:
                    from objects.components.tooltip_component import TooltipComponent
                    getter = _safe_getattr(obj, 'get_component', None)
                    if callable(getter):
                        component = getter(TooltipComponent)
                        if component is not None:
                            for attr in ('_dynamic_tooltip', 'tooltip', 'dynamic_tooltip'):
                                val = _safe_getattr(component, attr, None)
                                if val:
                                    tooltip_result['tooltip'] = str(val)
                                    tooltip_result['ok'] = True
                                    break
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
}


@sims4.commands.Command('sw.spike', command_type=sims4.commands.CommandType.Live)
def cmd_sw_spike(probe_name=None, _connection=None):
    """Run a spike probe by name.
    Usage: sw.spike <interaction|ui_injection|ui|routing|relationship>
    """
    output = sims4.commands.output
    if probe_name is None:
        output('Usage: sw.spike <interaction|ui_injection|ui|routing|relationship>', _connection)
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