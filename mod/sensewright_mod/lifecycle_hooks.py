# Sensewright v2 — Lifecycle Listeners (death / marriage / birth)
# Python 3.7 compatible
#
# Task 2.1: surface real S4CL lifecycle events to the sidecar so `mem.legacy`
# (P28) and `sim.lifestory` (P11) fire with real gameplay data. Every handler is
# defensive: a missing event class or a failed HTTP post must never break the
# game loop. The whole S4CL dependency is isolated here (facade pattern).

from sensewright_mod.debug_log import log_debug, log_exception, log_info, log_warn
from sensewright_mod.http_client import post_events, generate_trace_id
from sensewright_mod.state_collector import get_current_game_state
from sensewright_mod.i18n import get_current_language


#: A marriage is detected from the relationship bit's name (the engine keeps the
#: bit, not a discrete "married" event). Matching is name-based and language
#: independent because tuning names are English identifiers.
_MARRIAGE_MARKERS = ('married', 'spouse', 'fiance', 'engaged', 'soulmate')


def _safe_getattr(obj, attr, default=None):
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def _sim_id(sim_info):
    try:
        return int(_safe_getattr(sim_info, 'id', 0) or 0)
    except (TypeError, ValueError):
        return 0


def _post_lifecycle(category, sim_info, target_sim_info=None, impact=1.0, content=""):
    """Post one lifecycle event to /v1/events. Never raises."""
    try:
        sim_id = _sim_id(sim_info)
        if not sim_id:
            return False
        state = get_current_game_state()
        trace_id = generate_trace_id()
        target_id = _sim_id(target_sim_info) if target_sim_info is not None else None
        post_events(
            trace_id=trace_id,
            sim_id=sim_id,
            player_id='player_1',
            save_id=state['save_id'],
            world_sim_tick=state['world_sim_tick'],
            event_category=category,
            content=content,
            impact=impact,
            witnesses=[],
            lang=get_current_language(),
            target_sim_id=target_id or None,
        )
        log_info('lifecycle event posted: {} sim={} target={}'.format(category, sim_id, target_id))
        return True
    except Exception as e:
        log_exception('Failed to post lifecycle event {}: {}'.format(category, e))
        return False


try:
    from sims4communitylib.events.event_handling.common_event_registry import CommonEventRegistry
    from sims4communitylib.events.sim.events.sim_died import S4CLSimDiedEvent
    from sims4communitylib.events.sim.events.sim_pregnancy_ended import S4CLSimPregnancyEndedEvent
    from sims4communitylib.events.sim.events.sim_relationship_bit_added import S4CLSimRelationshipBitAddedEvent
    from sims4communitylib.modinfo import ModInfo
    from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils

    _S4CL_AVAILABLE = True
except Exception as e:  # pragma: no cover - depends on the installed S4CL build
    _S4CL_AVAILABLE = False
    log_warn('lifecycle: S4CL event classes unavailable: {}'.format(e))


if _S4CL_AVAILABLE:

    @CommonEventRegistry.handle_events(ModInfo.get_identity())
    def _handle_sim_died(event_data: S4CLSimDiedEvent):
        """Death -> /v1/events (category=death)."""
        try:
            death_type = _safe_getattr(event_data, 'death_type', '')
            _post_lifecycle('death', event_data.sim_info, impact=1.0,
                            content=str(death_type))
        except Exception as e:
            log_exception('sim_died handler failed: {}'.format(e))
        return True

    @CommonEventRegistry.handle_events(ModInfo.get_identity())
    def _handle_pregnancy_ended(event_data: S4CLSimPregnancyEndedEvent):
        """Pregnancy end -> /v1/events (category=birth)."""
        try:
            _post_lifecycle('birth', event_data.sim_info, impact=1.0)
        except Exception as e:
            log_exception('pregnancy_ended handler failed: {}'.format(e))
        return True

    @CommonEventRegistry.handle_events(ModInfo.get_identity())
    def _handle_relationship_bit_added(event_data: S4CLSimRelationshipBitAddedEvent):
        """Marriage/engagement relationship bit -> /v1/events (category=marriage)."""
        try:
            bit = _safe_getattr(event_data, 'relationship_bit', None)
            bit_name = ''
            if bit is not None:
                bit_name = str(_safe_getattr(bit, '__name__', '') or bit).lower()
            if not any(marker in bit_name for marker in _MARRIAGE_MARKERS):
                return True
            sim_a = _safe_getattr(event_data, 'sim_info_a', None)
            sim_b = _safe_getattr(event_data, 'sim_info_b', None)
            _post_lifecycle('marriage', sim_a, target_sim_info=sim_b, impact=1.0,
                            content=bit_name)
        except Exception as e:
            log_exception('relationship_bit_added handler failed: {}'.format(e))
        return True

    log_info('lifecycle listeners registered (death/pregnancy/marriage)')
else:
    log_debug('lifecycle listeners not registered (S4CL unavailable)')
