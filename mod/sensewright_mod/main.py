# Sensewright v2 — Main Entry Point
# Python 3.7 compatible

import services
import sims4.commands
from lot51_core.services.events import event_service, CoreEvent

from sensewright_mod.debug_log import log_info, log_error, log_exception, get_mod_logger
from sensewright_mod.http_client import start_worker, stop_worker, process_inbound_queue, post_lifecycle_attach
from sensewright_mod.state_collector import collect_sims_delta, collect_full_census, get_current_game_state
from sensewright_mod.intent_bus import get_intent_bus
from sensewright_mod.tool_executor import execute_intents
from sensewright_mod.tuning import register_all_tuning
from sensewright_mod.native_hooks import get_or_create_player_confidant
from sensewright_mod.chat_ui import cmd_sw_chat, cmd_sw_chat_picker
from sensewright_mod.panel_ui import cmd_sw_panel
from sensewright_mod.pie_menu import register_pie_menu_interactions, cmd_pie_chat, cmd_pie_provoke, cmd_pie_panel
# Importing the interactions module registers the S4CL pie menu handler as an
# import side effect (must happen before household/sims load).
from sensewright_mod import interactions as _interactions  # noqa: F401
# Object-target interactions (mirror/diary/mailbox) and lifecycle event listeners
# also register via import side effects.
from sensewright_mod import object_interactions as _object_interactions  # noqa: F401
from sensewright_mod import lifecycle_hooks as _lifecycle_hooks  # noqa: F401
from sensewright_mod import catalyst_tracker
from sensewright_mod.visit_situation import register_visit_situation
from sensewright_mod.player_activity import register_player_activity_hooks, update_idle_detection, clear_all_player_locks
from sensewright_mod.i18n import load_locales, get_current_language, detect_and_apply_game_language, t


# Mod service class for Lot 51 Core service manager
class SensewrightService(object):
    """Main mod service that owns collector/worker lifecycle."""

    def __init__(self):
        self._started = False
        self._last_autonomy_tick = 0
        self._autonomy_interval = 15 * 1000  # 15 sim-minutes in ticks
        self._language_applied = False

    def _ensure_language(self):
        """Apply the game's configured language once it becomes available.

        `account.locale` is assigned inside `c_api_client_connect`, which can be
        after our start hook, so we retry on each tick until it resolves.
        """
        if self._language_applied:
            return
        language = detect_and_apply_game_language()
        if language:
            self._language_applied = True
            log_info('Sensewright active language: {}'.format(language))

    def start(self):
        if self._started:
            return
        self._started = True

        # Load locales
        load_locales()

        # Match the language configured in the game (retried on tick if not yet
        # available).
        self._ensure_language()

        # Resolve tuning IDs (Sensewright-owned + native archetypes) and register
        # them with native_hooks / tool_executor. See tuning.py.
        register_all_tuning()

        # Resolve the catalyst VisitSituation tuning (2.4 / 3.3).
        register_visit_situation()

        # Start HTTP worker thread
        start_worker()

        # Register player activity hooks
        register_player_activity_hooks()

        # Register pie menu interactions
        register_pie_menu_interactions()

        log_info('Sensewright service started')

    def stop(self):
        if not self._started:
            return
        self._started = False

        stop_worker()
        clear_all_player_locks()

        log_info('Sensewright service stopped')

    def on_game_tick(self):
        """Called every GAME_TICK from Lot 51 Core event."""
        if not self._started:
            return

        try:
            # Apply the game language as soon as the client account is ready.
            self._ensure_language()

            # Process inbound HTTP responses/intents
            process_inbound_queue()

            # Update intent bus (delays, dispatch, expiration)
            intent_bus = get_intent_bus()
            ready_intents = intent_bus.update()

            # Execute ready intents
            if ready_intents:
                execute_intents(ready_intents)

            # Update idle detection
            update_idle_detection()

            # Autonomy pulse check
            current_tick = get_current_game_state()['world_sim_tick']
            if current_tick - self._last_autonomy_tick >= self._autonomy_interval:
                self._last_autonomy_tick = current_tick
                self._send_autonomy_pulse()

        except Exception as e:
            log_exception('GAME_TICK error: {}'.format(e))

    def _send_autonomy_pulse(self):
        """Send autonomy tick to sidecar."""
        try:
            from sensewright_mod.http_client import post_autonomy_tick, generate_trace_id
            from sensewright_mod.native_hooks import get_player_confidant_sim_id

            state = get_current_game_state()
            trace_id = generate_trace_id()

            # Collect sims delta
            sims_delta = collect_sims_delta()

            # Report the end of any catalyst conversation (2.9 -> god.react).
            try:
                catalyst_tracker.observe(sims_delta)
            except Exception as tracker_error:
                log_exception('Catalyst tracker error: {}'.format(tracker_error))

            post_autonomy_tick(
                trace_id=trace_id,
                player_id='player_1',
                save_id=state['save_id'],
                world_sim_tick=state['world_sim_tick'],
                clock_speed=state['clock_speed'],
                active_sim_id=state['active_sim_id'],
                player_confidant_sim_id=get_player_confidant_sim_id(),
                sims_delta=sims_delta,
                lang=get_current_language()
            )
        except Exception as e:
            log_exception('Autonomy pulse error: {}'.format(e))


# Global service instance
_sensewright_service = None
_onboarding_shown = False


def _show_onboarding_notification():
    """Show a one-time notification with the in-game entry points."""
    global _onboarding_shown
    if _onboarding_shown:
        return
    _onboarding_shown = True
    try:
        from sims4communitylib.notifications.common_basic_notification import CommonBasicNotification
        from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils

        body = '{}\n\n{}'.format(t('notify.onboarding.body'), t('notify.onboarding.hint'))
        CommonBasicNotification(
            CommonLocalizationUtils.create_localized_string(t('notify.onboarding.title')),
            CommonLocalizationUtils.create_localized_string(body),
        ).show()
    except Exception as e:
        log_exception('Onboarding notification failed: {}'.format(e))


def get_service():
    global _sensewright_service
    if _sensewright_service is None:
        _sensewright_service = SensewrightService()
    return _sensewright_service


# Lot 51 Core event handlers
@event_service.handler(CoreEvent.GAME_TICK)
def _on_game_tick(event_service, *args, **kwargs):
    """Main game tick handler."""
    get_service().on_game_tick()


@event_service.handler(CoreEvent.HOUSEHOLDS_AND_SIMS_LOADED)
def _on_households_and_sims_loaded(event_service, *args, **kwargs):
    """Called when all households and sims are loaded (session start)."""
    try:
        service = get_service()
        service.start()

        # Get or create player confidant
        get_or_create_player_confidant()

        # Send session-start to sidecar
        from sensewright_mod.http_client import post_lifecycle_session_start
        state = get_current_game_state()
        # Re-arm the sidecar watchdog (covers a sidecar restarted mid-session).
        post_lifecycle_attach()
        post_lifecycle_session_start('player_1', state['save_id'], state['world_sim_tick'], get_current_language())

        # Send full census
        from sensewright_mod.http_client import post_census
        sims, households, relationships = collect_full_census()
        post_census('player_1', state['save_id'], state['world_sim_tick'],
                    sims, households, relationships, state['installed_packs'])

        # Surface the in-game entry points to the player.
        _show_onboarding_notification()

        log_info('Session started, census sent')
    except Exception as e:
        log_exception('Session start error: {}'.format(e))


@event_service.handler(CoreEvent.ZONE_LOAD)
def _on_zone_load(event_service, *args, **kwargs):
    """Called on zone load (including travel)."""
    try:
        state = get_current_game_state()
        from sensewright_mod.http_client import post_lifecycle_zone_transition
        post_lifecycle_zone_transition('player_1', state['save_id'], state['zone_id'], state['world_sim_tick'])

        # Clear zone-specific intents
        get_intent_bus().clear_zone_intents()

        log_info('Zone loaded: {}'.format(state['zone_id']))
    except Exception as e:
        log_exception('Zone load error: {}'.format(e))


@event_service.handler(CoreEvent.ZONE_UNLOAD)
def _on_zone_unload(event_service, *args, **kwargs):
    """Called on zone unload."""
    try:
        get_intent_bus().clear_zone_intents()
        log_info('Zone unloaded')
    except Exception as e:
        log_exception('Zone unload error: {}'.format(e))


@event_service.handler(CoreEvent.GAME_PRE_SAVE)
def _on_game_pre_save(event_service, *args, **kwargs):
    """Called before game saves."""
    try:
        # Flush any pending data
        log_info('Pre-save: flushing buffers')
    except Exception as e:
        log_exception('Pre-save error: {}'.format(e))


@event_service.handler(CoreEvent.GAME_SAVE)
def _on_game_save(event_service, *args, **kwargs):
    """Called after game saves."""
    try:
        state = get_current_game_state()
        from sensewright_mod.http_client import post_lifecycle_save
        post_lifecycle_save('player_1', state['save_id'], None, state['world_sim_tick'])
        log_info('Game saved, lifecycle/save sent')
    except Exception as e:
        log_exception('Game save error: {}'.format(e))


@event_service.handler(CoreEvent.LOADING_SCREEN_LIFTED)
def _on_loading_screen_lifted(event_service, *args, **kwargs):
    """Called when loading screen is lifted (fallback start point)."""
    try:
        # Idempotent: start() returns early if already started. This is a
        # safety net in case HOUSEHOLDS_AND_SIMS_LOADED does not fire.
        get_service().start()
        log_info('Loading screen lifted')
    except Exception as e:
        log_exception('Loading screen lifted error: {}'.format(e))


log_info('Sensewright v2 mod loaded')