# Sensewright v2 — Chat UI (UiDialogTextInputOkCancel flow)
# Python 3.7 compatible

import services
import sims4.commands
from sims.sim_info import SimInfo
from sims4communitylib.dialogs.common_input_text_dialog import CommonInputTextDialog
from sims4communitylib.dialogs.common_choose_dialog import CommonChooseButtonDialog
from sims4communitylib.dialogs.common_choose_sim_dialog import CommonChooseSimDialog
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils
from protocolbuffers.Localization_pb2 import LocalizedString
from ui.ui_dialog_notification import UiDialogNotification
from ui.ui_dialog_generic import UiDialogTextInputOkCancel

from sensewright_mod.debug_log import log_error, log_exception, log_info
from sensewright_mod.http_client import post_chat, post_hey, generate_trace_id
from sensewright_mod.i18n import t
from sensewright_mod.config import get_player_confidant_sim_id
from sensewright_mod.native_hooks import get_or_create_player_confidant, add_social_motive_gain, add_fun_motive_gain


# Chat state
_active_chat_sessions = {}  # sim_id -> {channel, last_sim_line, turn_count}
_CHAT_BUFFER_MAX_TURNS = 8


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


def _extract_thought(text):
    """Extract [thought]...[/thought] from response, return (clean_text, thought)."""
    if not text:
        return text, None

    import re
    pattern = r'\[thought\](.*?)\[/thought\]'
    matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
    thought = matches[0].strip() if matches else None
    clean_text = re.sub(pattern, '', text, flags=re.DOTALL | re.IGNORECASE).strip()
    return clean_text, thought


def _show_typing_balloon(sim_info):
    """Show '...' thought balloon while AI is thinking."""
    try:
        sim = CommonSimUtils.get_sim_instance(sim_info)
        if sim is not None:
            sim.show_thought_balloon('...')
    except Exception:
        pass


def _hide_typing_balloon(sim_info):
    """Hide typing balloon."""
    try:
        sim = CommonSimUtils.get_sim_instance(sim_info)
        if sim is not None:
            sim.hide_thought_balloon()
    except Exception:
        pass


def _send_notification_with_response_button(sim_info, title, text, callback, sim_line_header=None):
    """Send a notification with a 'Responder' button that reopens chat."""
    try:
        # Create notification with ui_responses
        from ui.ui_dialog_notification import UiDialogNotification
        from protocolbuffers.UI_pb2 import UiDialogNotification as UiDialogNotificationProto
        from protocolbuffers.Localization_pb2 import LocalizedString

        # Build the notification
        dialog = UiDialogNotification.TunableFactory().default(
            sim_info,
            text=lambda **_: CommonLocalizationUtils.create_localized_string(text),
            title=lambda **_: CommonLocalizationUtils.create_localized_string(title),
            ui_responses=[
                UiDialogNotificationProto.UiDialogNotificationResponse(
                    dialog_response_id=1,
                    text=CommonLocalizationUtils.create_localized_string(t('chat.respond_now'))
                )
            ]
        )

        def _on_response(dialog):
            try:
                if dialog.response == 1:  # Responder button clicked
                    callback()
            except Exception as e:
                log_exception('Notification response error: {}'.format(e))

        dialog.add_listener(_on_response)
        dialog.show_dialog()
        return True
    except Exception as e:
        log_exception('Failed to send notification: {}'.format(e))
        return False


def _open_chat_dialog(sim_info, channel, player_id, save_id, world_sim_tick, lang, header_text=None):
    """Open the text input dialog for chat."""
    try:
        title = t('chat.title', sim_name=sim_info.full_name)
        if header_text:
            title = header_text

        dialog = CommonInputTextDialog(
            title=title,
            text=t('chat.placeholder'),
            on_submit=lambda result: _on_chat_submitted(
                result, sim_info, channel, player_id, save_id, world_sim_tick, lang
            ),
            on_cancel=lambda: _on_chat_cancelled(sim_info)
        )
        dialog.show()
        return True
    except Exception as e:
        log_exception('Failed to open chat dialog: {}'.format(e))
        return False


def _on_chat_submitted(input_text, sim_info, channel, player_id, save_id, world_sim_tick, lang):
    """Handle player submitting a chat message."""
    if not input_text or not input_text.strip():
        return

    sim_id = sim_info.id
    trace_id = generate_trace_id()

    # Show typing balloon immediately
    _show_typing_balloon(sim_info)

    # Update chat session
    session = _active_chat_sessions.get(sim_id, {})
    session['channel'] = channel
    session['turn_count'] = session.get('turn_count', 0) + 1
    _active_chat_sessions[sim_id] = session

    # Send to sidecar
    if channel == 'phone_sms':
        post_hey(trace_id, sim_id, player_id, save_id, world_sim_tick, input_text.strip(), lang)
    else:
        post_chat(trace_id, sim_id, channel, player_id, save_id, world_sim_tick, input_text.strip(), lang)


def _on_chat_cancelled(sim_info):
    """Handle player cancelling chat."""
    sim_id = sim_info.id
    if sim_id in _active_chat_sessions:
        del _active_chat_sessions[sim_id]
    _hide_typing_balloon(sim_info)


def _handle_chat_response(response, trace_id, sim_info, channel, player_id, save_id, world_sim_tick, lang):
    """Callback for chat response from sidecar."""
    _hide_typing_balloon(sim_info)

    if not response or not response.get('ok', False):
        # Show error notification
        _show_error_notification(sim_info, t('chat.error_failed'))
        return

    response_text = response.get('response', '')
    thought = response.get('thought', None)
    intents = response.get('intents', [])
    trust_delta = response.get('trust_delta', 0)
    deferred = response.get('deferred', False)
    message_key = response.get('message_key', None)

    # Extract thought if embedded in response
    if not thought:
        response_text, thought = _extract_thought(response_text)

    # Store thought as private memory (sidecar handles this via remember intent)
    # But we can log it locally
    if thought:
        log_info('Sim {} thought: {}'.format(sim_info.full_name, thought))

    # Handle deferred (sim sleeping/off-lot)
    if deferred:
        _show_deferred_notification(sim_info, response_text, channel)
        return

    # Apply trust delta to relationship with player confidant
    if trust_delta != 0:
        _apply_trust_delta(sim_info, trust_delta)

    # Execute any intents from chat
    if intents:
        from sensewright_mod.intent_bus import get_intent_bus
        intent_bus = get_intent_bus()
        for intent_data in intents:
            intent_bus.add_intent(intent_data)

    # Show response notification with "Responder" button
    sim_id = sim_info.id
    session = _active_chat_sessions.get(sim_id, {})
    turn_count = session.get('turn_count', 0)

    # Build header with last sim line for chained conversation
    header = t('chat.response_header', sim_name=sim_info.full_name, turn=turn_count)
    if session.get('last_sim_line'):
        header = '{} — "{}"'.format(header, session['last_sim_line'][:50])

    session['last_sim_line'] = response_text

    def _reopen_chat():
        _open_chat_dialog(sim_info, channel, player_id, save_id, world_sim_tick, lang, header_text=header)

    _send_notification_with_response_button(
        sim_info,
        title=t('chat.notification_title', sim_name=sim_info.full_name),
        text=response_text,
        callback=_reopen_chat,
        sim_line_header=header
    )

    # Grant social/fun motive for chatting
    add_social_motive_gain(sim_info, 50)
    add_fun_motive_gain(sim_info, 30)


def _show_deferred_notification(sim_info, message, channel):
    """Show notification that message will be delivered later."""
    try:
        from sims4communitylib.dialogs.common_ok_dialog import CommonOkDialog
        dialog = CommonOkDialog(
            title=t('chat.deferred_title'),
            text=t('chat.deferred_text', channel=channel, message=message)
        )
        dialog.show()
    except Exception:
        pass


def _show_error_notification(sim_info, message):
    """Show error notification."""
    try:
        from sims4communitylib.dialogs.common_ok_dialog import CommonOkDialog
        dialog = CommonOkDialog(
            title=t('chat.error_title'),
            text=message
        )
        dialog.show()
    except Exception:
        pass


def _apply_trust_delta(sim_info, trust_delta):
    """Apply trust delta to relationship with player confidant."""
    confidant_id = get_player_confidant_sim_id()
    if confidant_id <= 0:
        return

    confidant_info = services.sim_info_manager().get(confidant_id)
    if confidant_info is None:
        return

    try:
        from sensewright_mod.native_hooks import add_relationship_bit
        # Trust delta maps to friendship/romance change
        # This is simplified - real implementation would use relationship track
        from sims4communitylib.utils.sims.common_relationship_utils import CommonRelationshipUtils
        current_friendship = CommonRelationshipUtils.get_relationship_level(sim_info.id, confidant_id, 'friendship')
        new_friendship = max(-100, min(100, current_friendship + trust_delta))
        CommonRelationshipUtils.set_relationship_level(sim_info.id, confidant_id, 'friendship', new_friendship)
    except Exception as e:
        log_exception('Failed to apply trust delta: {}'.format(e))


def start_chat(sim_info, channel='phone_sms'):
    """Start a chat session with a sim."""
    if sim_info is None:
        return False

    # Ensure player confidant exists
    confidant = get_or_create_player_confidant()
    if confidant is None:
        log_error('Player confidant not available')
        return False

    # Get game state
    from sensewright_mod.state_collector import get_current_game_state
    state = get_current_game_state()

    player_id = 'player_1'  # Simplified
    save_id = state['save_id']
    world_sim_tick = state['world_sim_tick']
    lang = get_current_language()

    # Check if sim is sleeping or off-lot (for phone_sms)
    if channel == 'phone_sms':
        from sensewright_mod.state_collector import _safe_call
        from sensewright_mod.state_collector import _get_sim_info
        # The sidecar will handle deferred response

    _open_chat_dialog(sim_info, channel, player_id, save_id, world_sim_tick, lang)
    return True


def start_chat_by_sim_picker():
    """Open sim picker to choose who to chat with."""
    try:
        active_sim = services.active_sim_info()
        if active_sim is None:
            return

        def _on_sim_chosen(chosen_sim_info):
            if chosen_sim_info is not None:
                start_chat(chosen_sim_info, 'phone_sms')

        dialog = CommonChooseSimDialog(
            title=t('chat.choose_sim_title'),
            text=t('chat.choose_sim_text'),
            on_sim_chosen=_on_sim_chosen,
            include_sim_callback=lambda sim_info: sim_info.is_human and not sim_info.is_npc
        )
        dialog.show()
    except Exception as e:
        log_exception('Sim picker error: {}'.format(e))


# Command registration
@sims4.commands.Command('sw.chat', command_type=sims4.commands.CommandType.Live)
def cmd_sw_chat(sim_id=None, channel='phone_sms', _connection=None):
    """Start chat with a sim. Usage: sw.chat [sim_id] [channel]"""
    try:
        if sim_id is None:
            sim_info = services.active_sim_info()
        else:
            sim_info = services.sim_info_manager().get(sim_id)

        if sim_info is None:
            sims4.commands.output('Sim not found', _connection)
            return False

        start_chat(sim_info, channel)
        return True
    except Exception as e:
        log_exception('sw.chat command error: {}'.format(e))
        return False


@sims4.commands.Command('sw.chat_picker', command_type=sims4.commands.CommandType.Live)
def cmd_sw_chat_picker(_connection=None):
    """Open sim picker to start chat."""
    start_chat_by_sim_picker()
    return True