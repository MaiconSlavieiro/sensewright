# Sensewright v2 — Catalyst VisitSituation (2.4 / 3.3)
# Python 3.7 compatible
#
# Consumes the `spawn_npc` intent: pick or create a townie, spawn them on the
# active lot, start the native/custom visit situation (so the NPC walks to the
# door) and route them toward the target. The God Director then drives the
# asymmetric objective through the ordinary puppeteer/approach levers.

import services

from sensewright_mod.debug_log import log_debug, log_exception, log_info, log_warn
from sensewright_mod.tuning import resolve_owned_id


_ADULT_STAGES = ('TEEN', 'YOUNGADULT', 'ADULT', 'ELDER')

_situation_visit_id = 0


#: Custom situation class bound by mod/tuning/situations/sw_visit_situation.xml.
#: Defined defensively so a game-build mismatch never blocks mod import.
try:
    from situations.situation import Situation

    class SensewrightVisitSituation(Situation):
        """A visit situation the God Director can start for a catalyst NPC."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._sensewright_objective = ''

except Exception as e:  # pragma: no cover - depends on the game build
    SensewrightVisitSituation = None
    log_warn('visit_situation: Situation base unavailable: {}'.format(e))


def register_visit_situation():
    """Resolve the Sensewright visit situation tuning id at startup."""
    global _situation_visit_id
    _situation_visit_id = resolve_owned_id('situation_visit')
    log_info('visit_situation: tuning id={}'.format(_situation_visit_id))
    return _situation_visit_id


def _safe_getattr(obj, attr, default=None):
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def _pick_townie(target_sim_info):
    """Choose an adult, non-player SimInfo already present in the save."""
    try:
        manager = services.sim_info_manager()
        if manager is None:
            return None
        active_household = services.active_household()
        active_household_id = _safe_getattr(active_household, 'id', 0)
        target_id = _safe_getattr(target_sim_info, 'id', 0)
        for sim_info in manager.values():
            if sim_info is None:
                continue
            if target_id and sim_info.id == target_id:
                continue
            household_id = _safe_getattr(_safe_getattr(sim_info, 'household', None), 'id', 0)
            if active_household_id and household_id == active_household_id:
                continue
            if str(_safe_getattr(sim_info, 'age', '')).upper() not in _ADULT_STAGES:
                continue
            return sim_info
    except Exception as e:
        log_exception('visit_situation: townie pick failed: {}'.format(e))
    return None


def _spawn_sim(sim_info):
    """Instantiate the chosen SimInfo on the active lot via S4CL."""
    try:
        from sims4communitylib.utils.sims.common_sim_spawn_utils import CommonSimSpawnUtils
        return bool(CommonSimSpawnUtils.spawn_sim_at_active_sim_location(sim_info))
    except Exception as e:
        log_exception('visit_situation: spawn failed: {}'.format(e))
        return False


def _create_visitor_sim_info():
    """Last-resort NPC creation when the save has no suitable townie."""
    try:
        from sims4communitylib.utils.sims.common_sim_spawn_utils import CommonSimSpawnUtils
        from sims4communitylib.enums.common_age import CommonAge
        return CommonSimSpawnUtils.create_human_sim_info(age=CommonAge.YOUNGADULT, source='sensewright')
    except Exception as e:
        log_exception('visit_situation: create NPC failed: {}'.format(e))
        return None


def _start_visit(sim_info):
    """Start the native visit situation so the NPC walks up to the lot.

    The custom ``sw_visit_situation`` tuning was removed from this path (BUG-03):
    ``CommonSimSituationUtils.create_situation_for_sim`` builds a
    ``SituationGuestInfo.construct_from_purpose(..., situation_type.default_job(), ...)``
    and our tuning had no default job, so ``default_job()`` returned ``None`` and
    the call raised ``'NoneType' object has no attribute 'no_show_action'``. The
    native visit situation is engine-tested and covers the walk-up behaviour.
    """
    try:
        from sims4communitylib.utils.sims.common_sim_situation_utils import CommonSimSituationUtils
        CommonSimSituationUtils.create_visit_situation(sim_info)
        log_info('visit_situation: started native visit for {}'.format(_safe_getattr(sim_info, 'id', 0)))
        return 'native'
    except Exception as e:
        log_exception('visit_situation: native visit failed: {}'.format(e))
    return 'none'


def _route_to_target(sim_info, target_sim_info, params):
    """Route the visitor toward the target as a fallback to the situation goal."""
    try:
        from sensewright_mod.tool_executor import GameLever
        target_id = _safe_getattr(target_sim_info, 'id', 0) or int(params.get('approach_target', 0) or 0)
        if target_id:
            GameLever._execute_approach(_safe_getattr(sim_info, 'id', 0), target_id, params)
    except Exception as e:
        log_debug('visit_situation: route fallback failed: {}'.format(e))


def spawn_catalyst_visitor(sim_id, params):
    """Handle the `spawn_npc` intent. Returns (success, result_dict)."""
    params = params or {}
    try:
        target_sim_info = None
        if sim_id:
            target_sim_info = services.sim_info_manager().get(int(sim_id))
        if target_sim_info is None:
            target_sim_info = services.active_sim_info()

        npc_id = int(params.get('npc_sim_id', 0) or 0)
        npc_info = services.sim_info_manager().get(npc_id) if npc_id else None
        if npc_info is None:
            npc_info = _pick_townie(target_sim_info)
        if npc_info is None:
            npc_info = _create_visitor_sim_info()
        if npc_info is None:
            return False, {'error': 'no_candidate'}

        spawned = _spawn_sim(npc_info)
        situation = _start_visit(npc_info)
        # Do not report success when nothing actually reached the lot (M-B02).
        if not spawned and situation == 'none':
            return False, {
                'error': 'spawn_failed',
                'npc_sim_id': _safe_getattr(npc_info, 'id', 0),
                'spawned': spawned,
                'situation': situation,
            }
        _route_to_target(npc_info, target_sim_info, params)
        return True, {
            'npc_sim_id': _safe_getattr(npc_info, 'id', 0),
            'spawned': spawned,
            'situation': situation,
            'objective': params.get('objective', ''),
            'ring_doorbell': bool(params.get('ring_doorbell', True)),
        }
    except Exception as e:
        log_exception('spawn_catalyst_visitor failed: {}'.format(e))
        return False, {'error': 'spawn_failed', 'details': str(e)}
