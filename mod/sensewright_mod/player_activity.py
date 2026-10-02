# Sensewright v2 — Player Activity Detection
# Python 3.7 compatible

import services
import sims4.commands
from sims.sim_info import SimInfo
from sims4communitylib.modinfo import ModInfo
from sims4communitylib.events.event_handling.common_event_registry import CommonEventRegistry
from sims4communitylib.events.interaction.events.interaction_started import S4CLInteractionStartedEvent

from sensewright_mod.debug_log import log_error, log_exception, log_info
from sensewright_mod.http_client import post_player_activity


# Player manual lock state
_player_manual_locks = {}  # sim_id -> expiry_tick
_PLAYER_LOCK_DURATION_TICKS = 15 * 1000  # 15 sim-minutes in ticks (approx)


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


def _get_world_sim_tick():
    """Get current world sim tick."""
    try:
        clock = services.game_clock_service()
        if clock is not None:
            now = clock.now()
            if now is not None:
                return now.absolute_ticks()
    except Exception:
        pass
    return 0


def is_player_manual_locked(sim_id):
    """Check if a sim has a player manual lock."""
    current_tick = _get_world_sim_tick()
    expiry = _player_manual_locks.get(sim_id, 0)
    if current_tick < expiry:
        return True
    elif sim_id in _player_manual_locks:
        del _player_manual_locks[sim_id]
    return False


def set_player_manual_lock(sim_id, duration_ticks=None):
    """Set a player manual lock on a sim."""
    if duration_ticks is None:
        duration_ticks = _PLAYER_LOCK_DURATION_TICKS
    current_tick = _get_world_sim_tick()
    _player_manual_locks[sim_id] = current_tick + duration_ticks
    log_info('Player manual lock set on sim {} for {} ticks'.format(sim_id, duration_ticks))


def clear_player_manual_lock(sim_id):
    """Clear player manual lock."""
    if sim_id in _player_manual_locks:
        del _player_manual_locks[sim_id]


def clear_all_player_locks():
    """Clear all player manual locks."""
    _player_manual_locks.clear()


def _on_player_interaction_start(sim_info, interaction):
    """Called when player starts a manual interaction on a sim."""
    if sim_info is None:
        return

    sim_id = sim_info.id
    set_player_manual_lock(sim_id)

    # Notify sidecar of player activity
    try:
        from sensewright_mod.state_collector import get_current_game_state
        state = get_current_game_state()
        post_player_activity('player_1', state['save_id'], False, state['clock_speed'])
    except Exception as e:
        log_exception('Player activity notification error: {}'.format(e))


def _on_player_interaction_end(sim_info, interaction):
    """Called when player interaction ends."""
    # Lock persists for the full duration, don't clear immediately
    pass


def _is_user_directed(interaction):
    """Best-effort check for a player-directed interaction.

    Uses the Interaction.is_user_directed property when available and falls back
    to inspecting the interaction context source.
    """
    if interaction is None:
        return False

    try:
        value = _safe_getattr(interaction, 'is_user_directed', False)
        if callable(value):
            value = value()
        if value:
            return True
    except Exception:
        pass

    try:
        from interactions.context import InteractionSource
        source = _safe_getattr(_safe_getattr(interaction, 'context', None), 'source', None)
        if source in (InteractionSource.SOURCE_PIE_MENU,
                      InteractionSource.SOURCE_SCRIPT_WITH_USER_INTENT):
            return True
    except Exception:
        pass

    return False


class _SensewrightPlayerActivityListener(object):
    """S4CL event listener that flags player-directed interactions.

    The listener is registered at import time via the @handle_events decorator.
    """

    @staticmethod
    @CommonEventRegistry.handle_events(ModInfo.get_identity())
    def _handle_interaction_started(event_data: S4CLInteractionStartedEvent) -> bool:
        try:
            interaction = event_data.interaction
            sim_info = event_data.sim_info
            if sim_info is not None and _is_user_directed(interaction):
                _on_player_interaction_start(sim_info, interaction)
        except Exception as e:
            log_exception('Player activity event error: {}'.format(e))
        return True


def register_player_activity_hooks():
    """Player activity detection is registered via the S4CL event listener class.

    The @CommonEventRegistry.handle_events decorator runs when this module is
    imported, so this function only reports status.
    """
    try:
        log_info('Player activity hooks registered (S4CL interaction event listener)')
        return True
    except Exception as e:
        log_exception('Player activity hook registration error: {}'.format(e))
        return False


# Periodic idle detection
_last_player_input_tick = 0
_IDLE_THRESHOLD_TICKS = 60 * 1000  # 60 sim-minutes


def update_idle_detection():
    """Call from GAME_TICK to update idle detection."""
    global _last_player_input_tick

    current_tick = _get_world_sim_tick()
    clock_speed = 1
    try:
        clock = services.game_clock_service()
        if clock is not None:
            clock_speed = _safe_getattr(clock, 'clock_speed', 1)
    except Exception:
        pass

    # Check if any player manual locks are active
    has_active_locks = False
    for sim_id, expiry in list(_player_manual_locks.items()):
        if current_tick < expiry:
            has_active_locks = True
        else:
            del _player_manual_locks[sim_id]

    # Determine idle state
    # Simplified: if no locks and clock running, consider idle after threshold
    idle = not has_active_locks and clock_speed > 0

    # Notify sidecar periodically (every ~15 sim-minutes)
    if current_tick - _last_player_input_tick > 15 * 1000:
        try:
            from sensewright_mod.state_collector import get_current_game_state
            state = get_current_game_state()
            post_player_activity('player_1', state['save_id'], idle, clock_speed)
            _last_player_input_tick = current_tick
        except Exception as e:
            log_exception('Idle detection notification error: {}'.format(e))