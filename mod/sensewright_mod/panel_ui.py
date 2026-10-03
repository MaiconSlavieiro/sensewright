# Sensewright v2 — Quick Menu Panel UI (sw.panel)
# Python 3.7 compatible

import services
import sims4.commands
import webbrowser
from sims4communitylib.dialogs.common_choose_response_dialog import CommonChooseResponseDialog
from sims4communitylib.dialogs.common_ui_dialog_response import CommonUiDialogResponse
from sims4communitylib.dialogs.common_choice_outcome import CommonChoiceOutcome
from sims4communitylib.modinfo import ModInfo
from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils
from protocolbuffers.Localization_pb2 import LocalizedString

from sensewright_mod.debug_log import log_error, log_exception, log_info
from sensewright_mod.http_client import post_async, post_config_panic, post_config_resume
from sensewright_mod.intent_bus import get_intent_bus
from sensewright_mod.config import get_sidecar_url
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


def _show_button_dialog(title, text, buttons):
    """Show a multi-button dialog via S4CL's CommonChooseResponseDialog.

    `buttons` is a list of (label, callback) pairs. Each row gets a stable
    integer value used to map the chosen row back to its callback.
    """
    responses = tuple(
        CommonUiDialogResponse(index + 1, index + 1, text=label)
        for index, (label, _callback) in enumerate(buttons)
    )
    callbacks = {index + 1: callback for index, (_label, callback) in enumerate(buttons)}

    def _on_chosen(choice, outcome):
        if outcome != CommonChoiceOutcome.CHOICE_MADE:
            return
        callback = callbacks.get(choice)
        if callback is not None:
            callback()

    dialog = CommonChooseResponseDialog(
        ModInfo.get_identity(),
        title,
        text,
        responses,
        per_page=10,
    )
    dialog.show(
        sim_info=services.active_sim_info(),
        on_chosen=_on_chosen,
        include_pagination=False,
        include_previous_button=False,
    )


def _notify(title, body):
    """Show a basic S4CL notification, ignoring failures."""
    try:
        from sims4communitylib.notifications.common_basic_notification import CommonBasicNotification
        from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils
        CommonBasicNotification(
            CommonLocalizationUtils.create_localized_string(title),
            CommonLocalizationUtils.create_localized_string(body),
        ).show()
    except Exception as e:
        log_exception('Notification failed: {}'.format(e))


def panic_now():
    """FC4: clear queued intents and suspend sidecar autonomy."""
    try:
        get_intent_bus().clear_all()
        post_config_panic()
        _notify(t('notify.paused.title'), t('notify.paused.body'))
        log_info('Panic: autonomy suspended, intents cleared')
    except Exception as e:
        log_exception('Panic error: {}'.format(e))
    show_quick_menu()


def resume_now():
    """FC4: restore sidecar autonomy after a panic pause."""
    try:
        post_config_resume()
        _notify(t('notify.resumed.title'), t('notify.resumed.body'))
        log_info('Resume: autonomy restored')
    except Exception as e:
        log_exception('Resume error: {}'.format(e))
    show_quick_menu()


def show_quick_menu():
    """Show the main Quick Menu panel."""
    try:
        summary = _build_panel_summary()
        _show_button_dialog(
            t('panel.title'),
            summary,
            [
                (t('panel.btn.director_preset'), _show_preset_menu),
                (t('panel.btn.director_mode'), _show_mode_menu),
                (t('panel.btn.autonomy'), _show_autonomy_menu),
                (t('panel.btn.panic'), panic_now),
                (t('panel.btn.resume'), resume_now),
                (t('panel.btn.web_studio'), _open_web_studio),
                (t('panel.btn.refresh'), show_quick_menu),
            ],
        )
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

        _show_button_dialog(t('panel.preset.title'), t('panel.preset.desc'), buttons)
    except Exception as e:
        log_exception('Preset menu error: {}'.format(e))


def _set_preset(preset_id):
    """Set director preset."""
    # The sidecar control is named `preset` (not `director_preset`); the old key
    # was silently rejected by set_control and never reached the Web Studio.
    _send_god_control('preset', preset_id)
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

        _show_button_dialog(t('panel.mode.title'), t('panel.mode.desc'), buttons)
    except Exception as e:
        log_exception('Mode menu error: {}'.format(e))


def _set_mode(mode_id):
    """Set director mode."""
    # The sidecar's GOD_MODES are uppercase ("AUTONOMOUS", "CO_DIRECTOR",
    # "SANDBOX"); lowercase values were rejected and never persisted.
    _send_god_control('director_mode', mode_id.upper())
    log_info('Director mode set to: {}'.format(mode_id.upper()))
    show_quick_menu()


def _show_autonomy_menu():
    """Show autonomy mode selection."""
    try:
        modes = _get_autonomy_modes()
        buttons = []
        for mode_id, mode_name in modes:
            buttons.append((mode_name, lambda mid=mode_id: _set_autonomy(mid)))

        buttons.append((t('common.back'), show_quick_menu))

        _show_button_dialog(t('panel.autonomy.title'), t('panel.autonomy.desc'), buttons)
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


@sims4.commands.Command('sw.panic', command_type=sims4.commands.CommandType.Live)
def cmd_sw_panic(_connection=None):
    """Pause Sensewright and clear queued intents (FC4)."""
    panic_now()


@sims4.commands.Command('sw.resume', command_type=sims4.commands.CommandType.Live)
def cmd_sw_resume(_connection=None):
    """Resume Sensewright autonomy (FC4)."""
    resume_now()
    return True