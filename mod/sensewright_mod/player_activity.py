# Sensewright v2 — Player Activity Detection
# Python 3.7 compatible

import services
import sims4.commands
from sims.sim_info import SimInfo
from sims4communitylib.utils.common_injection_utils import CommonInjectionUtils
from sims4communitylib.mod_support.mod_identity import CommonModIdentity
from sims4communitylib.modinfo import ModInfo

from sensewright_mod.debug_log import log_error, log_exception, log_info
from sensewright_mod.http_client import post_player_activity, get_world_sim_tick as http_get_world_sim_tick


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


def register_player_activity_hooks():
    """Register hooks to detect player manual interactions."""
    try:
        # Hook into Sim's interaction queue to detect player-directed interactions
        # This is a simplified version - real implementation would inject into
        # the interaction queue processing

        # Inject into Sim.push_interaction to detect player clicks
        @CommonInjectionUtils.inject_safely_into(ModInfo.get_identity(), 'sims.sim.Sim', 'push_interaction')
        def _injected_push_interaction(original, self, interaction, *args, **kwargs):
            try:
                # Check if this is a player-directed interaction
                # Player interactions typically have a specific context
                context = _safe_getattr(interaction, 'context', None)
                if context is not None:
                    source = _safe_getattr(context, 'source', None)
                    # Player-directed interactions have source = InteractionContext.SOURCE_SCRIPT_WITH_USER_INTENT
                    # or similar
                    if source is not None:
                        sim_info = _safe_getattr(self, 'sim_info', None)
                        if sim_info is not None:
                            _on_player_interaction_start(sim_info, interaction)
            except Exception:
                pass
            return original(self, interaction, *args, **kwargs)

        log_info('Player activity hooks registered')
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