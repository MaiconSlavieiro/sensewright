# Sensewright v2 — Pie Menu Interactions (S4CL)
# Python 3.7 compatible

import services
import sims4.commands
from sims.sim_info import SimInfo
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
from sims4communitylib.utils.common_injection_utils import CommonInjectionUtils
from sims4communitylib.mod_support.mod_identity import CommonModIdentity
from sims4communitylib.modinfo import ModInfo

from sensewright_mod.debug_log import log_error, log_exception, log_info, worker_log_info
from sensewright_mod.chat_ui import start_chat, start_chat_by_sim_picker
from sensewright_mod.panel_ui import show_quick_menu


# Mod identity (S4CL's identity; used for logging/attribution only)
MOD_IDENTITY = ModInfo.get_identity()


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


def _on_chat_interaction(sim_info, target_sim_info):
    """Handle 'Conversar / Mandar SMS' pie menu action."""
    if target_sim_info is not None:
        start_chat(target_sim_info, 'phone_sms')
    return True


def _on_provoke_scene_interaction(sim_info, target_sim_info):
    """Handle 'Provocar Cena Aqui' pie menu action."""
    # This would open a dialog to select catalyst NPC and instruction
    # For now, send a god.direct-scene request
    from sensewright_mod.http_client import post_async, generate_trace_id
    from sensewright_mod.state_collector import get_current_game_state

    state = get_current_game_state()
    trace_id = generate_trace_id()

    from sensewright_mod.i18n import get_current_language

    worker_log_info('pie menu: provoke scene clicked target={}'.format(
        target_sim_info.id if target_sim_info is not None else None))

    post_async('/god/direct-scene', {
        'trace_id': trace_id,
        'player_id': 'player_1',
        'save_id': state['save_id'],
        'world_sim_tick': state['world_sim_tick'],
        'catalyst_sim_ids': [target_sim_info.id] if target_sim_info else [],
        'target_sim_ids': [sim_info.id],
        'prompt_text': 'Provocar uma cena interessante',
        'mode': 'soft_catalyst',
        'lang': get_current_language()
    })
    return True


def _on_panel_interaction(sim_info, target_sim_info):
    """Handle 'Menu Rápido Sensewright' pie menu action."""
    show_quick_menu()
    return True


# Pie menu registration is performed at import time by
# `sensewright_mod.interactions` (S4CL's CommonInteractionRegistry handler).
# This hook is kept for the service lifecycle and simply confirms the handler
# module was imported.
_handler_registered = False


def register_pie_menu_interactions():
    """Confirm the pie menu interaction handler module is loaded."""
    global _handler_registered
    if _handler_registered:
        return True

    try:
        from sensewright_mod import interactions  # noqa: F401  (registers handler)
        _handler_registered = True
        log_info('Pie menu interactions registered via sensewright_mod.interactions')
        return True
    except Exception as e:
        log_exception('Pie menu registration error: {}'.format(e))
        return False


# Command-based fallbacks for testing
@sims4.commands.Command('sw.pie_chat', command_type=sims4.commands.CommandType.Live)
def cmd_pie_chat(target_sim_id=None, _connection=None):
    """Pie menu: Conversar / Mandar SMS"""
    try:
        active_sim = services.active_sim_info()
        if target_sim_id:
            target_sim = services.sim_info_manager().get(target_sim_id)
        else:
            target_sim = active_sim

        if target_sim:
            start_chat(target_sim, 'phone_sms')
        return True
    except Exception as e:
        log_exception('Pie chat error: {}'.format(e))
        return False


@sims4.commands.Command('sw.pie_provoke', command_type=sims4.commands.CommandType.Live)
def cmd_pie_provoke(target_sim_id=None, _connection=None):
    """Pie menu: Provocar Cena Aqui"""
    try:
        active_sim = services.active_sim_info()
        if target_sim_id:
            target_sim = services.sim_info_manager().get(target_sim_id)
        else:
            target_sim = active_sim

        if target_sim:
            _on_provoke_scene_interaction(active_sim, target_sim)
        return True
    except Exception as e:
        log_exception('Pie provoke error: {}'.format(e))
        return False


@sims4.commands.Command('sw.pie_panel', command_type=sims4.commands.CommandType.Live)
def cmd_pie_panel(_connection=None):
    """Pie menu: Menu Rápido Sensewright"""
    show_quick_menu()
    return True