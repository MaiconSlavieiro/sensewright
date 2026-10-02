# Sensewright v2 — Quick Menu Panel UI (sw.panel)
# Python 3.7 compatible

import services
import sims4.commands
import webbrowser
from sims4communitylib.dialogs.common_choose_dialog import CommonChooseButtonDialog
from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils
from protocolbuffers.Localization_pb2 import LocalizedString

from sensewright_mod.debug_log import log_error, log_exception, log_info
from sensewright_mod.http_client import post_async, get_sidecar_url
from sensewright_mod.i18n import t
from sensewright_mod.config import get_agent_seats


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


def _get_director_presets():
    """Get available director presets."""
    return [
        ('off', t('panel.preset.off')),
        ('novela', t('panel.preset.novela')),
        ('sitcom', t('panel.preset.sitcom')),
        ('drama', t('panel.preset.drama')),
        ('terror', t('panel.preset.terror')),
        ('romance', t('panel.preset.romance')),
        ('caos', t('panel.preset.caos')),
        ('filme_adolescente', t('panel.preset.filme_adolescente')),
    ]


def _get_director_modes():
    """Get available director modes."""
    return [
        ('autonomous', t('panel.mode.autonomous')),
        ('co_director', t('panel.mode.co_director')),
        ('sandbox', t('panel.mode.sandbox')),
    ]


def _get_autonomy_modes():
    """Get available autonomy modes."""
    return [
        ('full', t('panel.autonomy.full')),
        ('reactive', t('panel.autonomy.reactive')),
        ('off', t('panel.autonomy.off')),
    ]


def _build_panel_summary():
    """Build the diagnostic summary for panel header."""
    try:
        from sensewright_mod.state_collector import get_current_game_state
        from sensewright_mod.intent_bus import get_intent_bus
        from sensewright_mod.http_client import get_outbound_queue, get_inbound_intents_queue

        state = get_current_game_state()
        intent_bus = get_intent_bus()
        bus_stats = intent_bus.get_stats()
        outbound_q = get_outbound_queue()
        inbound_q = get_inbound_intents_queue()

        summary_lines = [
            t('panel.summary.line1',
              tick=state['world_sim_tick'],
              speed=state['clock_speed'],
              zone=state['zone_id']),
            t('panel.summary.line2',
              seats=get_agent_seats(),
              intents=bus_stats['total'],
              pending=bus_stats['pending'],
              outbound=outbound_q.qsize(),
              inbound=inbound_q.qsize())
        ]
        return '\n'.join(summary_lines)
    except Exception as e:
        log_exception('Panel summary error: {}'.format(e))
        return t('panel.summary.error')


def _open_web_studio():
    """Open the Sensewright Web Studio in browser."""
    try:
        url = '{}/ui'.format(get_sidecar_url())
        webbrowser.open(url)
        log_info('Opened Web Studio: {}'.format(url))
        return True
    except Exception as e:
        log_exception('Failed to open Web Studio: {}'.format(e))
        return False


def _send_god_control(key, value):
    """Send a god control change to sidecar."""
    try:
        post_async('/god/controls', {'key': key, 'value': value})
        return True
    except Exception as e:
        log_exception('God control error: {}'.format(e))
        return False


def show_quick_menu():
    """Show the main Quick Menu panel."""
    try:
        summary = _build_panel_summary()

        dialog = CommonChooseButtonDialog(
            title=t('panel.title'),
            text=summary,
            buttons=[
                (t('panel.btn.director_preset'), _show_preset_menu),
                (t('panel.btn.director_mode'), _show_mode_menu),
                (t('panel.btn.autonomy'), _show_autonomy_menu),
                (t('panel.btn.web_studio'), _open_web_studio),
                (t('panel.btn.refresh'), show_quick_menu),
            ]
        )
        dialog.show()
    except Exception as e:
        log_exception('Quick menu error: {}'.format(e))


def _show_preset_menu():
    """Show director preset selection."""
    try:
        presets = _get_director_presets()
        buttons = []
        for preset_id, preset_name in presets:
            buttons.append((preset_name, lambda pid=preset_id: _set_preset(pid)))

        buttons.append((t('common.back'), show_quick_menu))

        dialog = CommonChooseButtonDialog(
            title=t('panel.preset.title'),
            text=t('panel.preset.desc'),
            buttons=buttons
        )
        dialog.show()
    except Exception as e:
        log_exception('Preset menu error: {}'.format(e))


def _set_preset(preset_id):
    """Set director preset."""
    _send_god_control('director_preset', preset_id)
    log_info('Director preset set to: {}'.format(preset_id))
    show_quick_menu()


def _show_mode_menu():
    """Show director mode selection."""
    try:
        modes = _get_director_modes()
        buttons = []
        for mode_id, mode_name in modes:
            buttons.append((mode_name, lambda mid=mode_id: _set_mode(mid)))

        buttons.append((t('common.back'), show_quick_menu))

        dialog = CommonChooseButtonDialog(
            title=t('panel.mode.title'),
            text=t('panel.mode.desc'),
            buttons=buttons
        )
        dialog.show()
    except Exception as e:
        log_exception('Mode menu error: {}'.format(e))


def _set_mode(mode_id):
    """Set director mode."""
    _send_god_control('director_mode', mode_id)
    log_info('Director mode set to: {}'.format(mode_id))
    show_quick_menu()


def _show_autonomy_menu():
    """Show autonomy mode selection."""
    try:
        modes = _get_autonomy_modes()
        buttons = []
        for mode_id, mode_name in modes:
            buttons.append((mode_name, lambda mid=mode_id: _set_autonomy(mid)))

        buttons.append((t('common.back'), show_quick_menu))

        dialog = CommonChooseButtonDialog(
            title=t('panel.autonomy.title'),
            text=t('panel.autonomy.desc'),
            buttons=buttons
        )
        dialog.show()
    except Exception as e:
        log_exception('Autonomy menu error: {}'.format(e))


def _set_autonomy(mode_id):
    """Set autonomy mode."""
    _send_god_control('autonomy_mode', mode_id)
    log_info('Autonomy mode set to: {}'.format(mode_id))
    show_quick_menu()


# Command registration
@sims4.commands.Command('sw.panel', command_type=sims4.commands.CommandType.Live)
def cmd_sw_panel(_connection=None):
    """Open the Sensewright Quick Menu panel."""
    show_quick_menu()
    return True