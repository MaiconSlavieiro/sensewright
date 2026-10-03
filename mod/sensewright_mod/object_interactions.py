# Sensewright v2 â€” Object Interactions (Mirror / Diary / Snoop / Mailbox)
# Python 3.7 compatible
#
# Tasks 3.2 (mirror "Reflect"), 3.4 (diary Tooltip + "Snoop") and 3.9 (mailbox
# "Neighborhood Stories"). Interactions are attached to the relevant base-game
# objects by matching the object definition name, because EA exposes no stable
# tuning id for these objects across packs/builds.

from sims4communitylib.classes.interactions.common_immediate_super_interaction import CommonImmediateSuperInteraction
from sims4communitylib.classes.testing.common_execution_result import CommonExecutionResult
from sims4communitylib.classes.testing.common_test_result import CommonTestResult
from sims4communitylib.mod_support.mod_identity import CommonModIdentity
from sims4communitylib.modinfo import ModInfo
from sims4communitylib.services.interactions.interaction_registration_service import (
    CommonInteractionRegistry,
    CommonInteractionType,
    CommonScriptObjectInteractionHandler,
)
from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils

from sensewright_mod.debug_log import log_debug, log_exception, log_info, log_warn, worker_log_info
from sensewright_mod.tuning import resolve_owned_id


_MIRROR_MARKERS = ('mirror',)
_DIARY_MARKERS = ('diary', 'journal')
_MAILBOX_MARKERS = ('mailbox',)


def _safe_getattr(obj, attr, default=None):
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def _resolve_sim_info(interaction_sim):
    try:
        return CommonSimUtils.get_sim_info(interaction_sim)
    except Exception:
        return interaction_sim


def _object_name(script_object):
    """Best-effort lowercased name for matching (class name first).

    BUG (observed): ``script_object.definition.name`` is ``None`` for many
    base-game objects, and the ``str(definition)`` fallback produced
    ``"<definition: 30457>"`` — so the mirror/diary/mailbox markers never
    matched and the interactions never appeared. The Python class name
    (``Mirror``, ``Mailbox``, …) is stable and contains the marker, so prefer it.
    """
    if script_object is not None:
        cls = _safe_getattr(script_object, '__class__', None)
        class_name = _safe_getattr(cls, '__name__', None)
        if class_name:
            return str(class_name).lower()
    definition = _safe_getattr(script_object, 'definition', None)
    name = _safe_getattr(definition, 'name', None)
    if not name:
        name = _safe_getattr(definition, '__name__', None) or str(definition or '')
    return str(name or '').lower()


# ── Diagnostics: why an object interaction may not appear (BUG-02 style) ──
_tuning_status_logged = False
_seen_log = {}


def _log_object_tuning_status():
    """Log (once) whether each object-interaction tuning actually loaded.

    This mirrors ``interactions._log_tuning_load_status``. If a tuning id does not
    resolve or the engine never loaded the resource, the interaction can never
    appear in a pie menu — this line is what makes that visible.
    """
    global _tuning_status_logged
    if _tuning_status_logged:
        return
    _tuning_status_logged = True
    try:
        import services
        from sims4.resources import Types
        interaction_type = getattr(Types, 'INTERACTION', None)
        manager = services.get_instance_manager(interaction_type) if interaction_type is not None else None
        for label, key in (
            ('interaction.mirror_reflect', 'interaction_mirror_reflect'),
            ('interaction.diary_read', 'interaction_diary_read'),
            ('interaction.diary_snoop', 'interaction_diary_snoop'),
            ('interaction.mailbox', 'interaction_mailbox'),
        ):
            tuning_id = resolve_owned_id(key)
            loaded = False
            if manager is not None and tuning_id:
                try:
                    loaded = manager.get(tuning_id) is not None
                except Exception:
                    loaded = False
            worker_log_info('tuning {} id={} loaded={}'.format(label, tuning_id, loaded))
    except Exception as e:
        worker_log_warn('object tuning check error: {}'.format(e))


def _note_object_seen(handler_name, matched, object_name, tuning_id):
    """Throttled diagnostic: log the first object seen + first match per handler.

    ``should_add`` fires for every object in the zone, so we log only the first
    object (proves the handler is invoked and shows the real object-definition
    name) and the first match (proves the interaction was actually attached).
    """
    seen_key = handler_name + ':seen'
    match_key = handler_name + ':matched'
    if seen_key not in _seen_log:
        _seen_log[seen_key] = True
        worker_log_info('object_interactions: {} handler first object name="{}"'.format(handler_name, object_name))
    if matched and match_key not in _seen_log:
        _seen_log[match_key] = True
        worker_log_info('object_interactions: {} MATCHED "{}" -> adding interaction id={}'.format(
            handler_name, object_name, tuning_id))


def _show_notification(title, body):
    try:
        from sims4communitylib.notifications.common_basic_notification import CommonBasicNotification
        from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils
        CommonBasicNotification(
            CommonLocalizationUtils.create_localized_string(title),
            CommonLocalizationUtils.create_localized_string(body),
        ).show()
    except Exception as e:
        log_exception('object_interactions: notification failed: {}'.format(e))


class _SensewrightObjectInteraction(CommonImmediateSuperInteraction):
    """Shared plumbing for Sensewright object-target interactions."""

    @classmethod
    def get_mod_identity(cls) -> CommonModIdentity:
        return ModInfo.get_identity()

    @classmethod
    def get_log_identifier(cls) -> str:
        return 'sensewright_object_interaction'

    @classmethod
    def on_test(cls, interaction_sim, interaction_target, interaction_context, **kwargs) -> CommonTestResult:
        return CommonTestResult.TRUE


class SensewrightMirrorReflectInteraction(_SensewrightObjectInteraction):
    """Click a mirror -> 'Reflect on Life...' fires evo.reflect (A8 / 3.2)."""

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        try:
            from sensewright_mod.http_client import post_async, generate_trace_id
            from sensewright_mod.state_collector import get_current_game_state
            from sensewright_mod.i18n import get_current_language, t

            sim_info = _resolve_sim_info(interaction_sim)
            state = get_current_game_state()
            worker_log_info('object_interactions: mirror reflect clicked sim={}'.format(
                _safe_getattr(sim_info, 'id', 0)))
            post_async('/evolve', {
                'trace_id': generate_trace_id(),
                'sim_id': _safe_getattr(sim_info, 'id', 0),
                'trigger': 'mirror',
                'player_id': 'player_1',
                'save_id': state['save_id'],
                'world_sim_tick': state['world_sim_tick'],
                'lang': get_current_language(),
            })
            _show_notification(t('notify.mirror.reflect_title'), t('notify.mirror.reflect_body'))
        except Exception as e:
            log_exception('SensewrightMirrorReflectInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE


def _request_diary(interaction_sim, interaction_target=None, snoop=False):
    """Fetch the saved diary text from the sidecar, show it, and cache it on the
    diary object so its TooltipComponent can surface it (3.4)."""
    try:
        from sensewright_mod.http_client import post_async, generate_trace_id
        from sensewright_mod.state_collector import get_current_game_state
        from sensewright_mod.i18n import get_current_language, t

        sim_info = _resolve_sim_info(interaction_sim)
        sim_id = _safe_getattr(sim_info, 'id', 0)
        state = get_current_game_state()
        worker_log_info('object_interactions: diary {} clicked sim={}'.format(
            'snoop' if snoop else 'read', sim_id))

        def _callback(response, trace_id=None):
            entry = ''
            if isinstance(response, dict):
                entry = response.get('entry', '') or ''
            # Cache on the diary object and refresh its TooltipComponent.
            if interaction_target is not None and entry:
                try:
                    interaction_target._sensewright_diary_tooltip = entry
                    apply_diary_tooltip(interaction_target, entry)
                except Exception:
                    pass
            title = t('notify.diary.snoop_title') if snoop else t('notify.diary.read_title')
            body = entry if entry else t('notify.diary.empty')
            _show_notification(title, body)

        post_async('/memory/diary', {
            'trace_id': generate_trace_id(),
            'sim_id': sim_id,
            'player_id': 'player_1',
            'save_id': state['save_id'],
            'world_sim_tick': state['world_sim_tick'],
            'lang': get_current_language(),
        }, callback=_callback)
    except Exception as e:
        log_exception('Diary request failed: {}'.format(e))


class SensewrightDiaryReadInteraction(_SensewrightObjectInteraction):
    """Click a diary/journal -> read the saved diary entry (3.4)."""

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        _request_diary(interaction_sim, interaction_target, snoop=False)
        return CommonExecutionResult.TRUE


class SensewrightDiarySnoopInteraction(_SensewrightObjectInteraction):
    """Click a diary/journal -> 'Snoop' reveals the saved diary entry (3.4)."""

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        _request_diary(interaction_sim, interaction_target, snoop=True)
        return CommonExecutionResult.TRUE


class SensewrightMailboxInteraction(_SensewrightObjectInteraction):
    """Click the mailbox -> 'Neighborhood Stories' lists chronicles + rumors (3.9)."""

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        try:
            from sensewright_mod.http_client import get_async, generate_trace_id
            from sensewright_mod.state_collector import get_current_game_state
            from sensewright_mod.i18n import get_current_language, t

            state = get_current_game_state()
            save_id = state['save_id']
            worker_log_info('object_interactions: mailbox clicked save={}'.format(save_id))

            def _callback(response, trace_id=None):
                data = response if isinstance(response, dict) else {}
                lines = []
                for chronicle in (data.get('chronicles') or [])[-3:]:
                    text = chronicle.get('text') if isinstance(chronicle, dict) else str(chronicle)
                    if text:
                        lines.append(text)
                for rumor in (data.get('rumors') or [])[:3]:
                    text = rumor.get('text') if isinstance(rumor, dict) else str(rumor)
                    if text:
                        lines.append('â€¢ {}'.format(text))
                body = '\n\n'.join(lines) if lines else t('notify.mailbox.empty')
                _show_notification(t('notify.mailbox.title'), body)

            get_async('/world/neighborhood?save_id={}'.format(save_id), callback=_callback)
        except Exception as e:
            log_exception('SensewrightMailboxInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE


# â”€â”€ Tooltip component injection for the diary object (3.4) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def apply_diary_tooltip(script_object, text):
    """Best-effort dynamic tooltip on the diary object via its TooltipComponent.

    The component API differs across builds, so every access is guarded; the
    interaction itself always shows the text, so the tooltip is an enhancement.
    """
    if not text:
        return False
    component = None
    try:
        from objects.components.tooltip_component import TooltipComponent
        getter = _safe_getattr(script_object, 'get_component', None)
        if callable(getter):
            component = getter(TooltipComponent)
    except Exception:
        component = None
    if component is None:
        return False
    for setter_name in ('set_dynamic_tooltip', 'set_tooltip'):
        setter = _safe_getattr(component, setter_name, None)
        if callable(setter):
            try:
                setter(text)
                return True
            except Exception:
                continue
    try:
        component._dynamic_tooltip = text
        return True
    except Exception:
        return False


# â”€â”€ Interaction handlers (attached to the relevant object types) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class _MirrorInteractionHandler(CommonScriptObjectInteractionHandler):
    @property
    def interactions_to_add(self):
        tuning_id = resolve_owned_id('interaction_mirror_reflect')
        return (tuning_id,) if tuning_id else ()

    def should_add(self, script_object, *args, **kwargs):
        _log_object_tuning_status()
        name = _object_name(script_object)
        matched = any(marker in name for marker in _MIRROR_MARKERS)
        _note_object_seen('mirror', matched, name, resolve_owned_id('interaction_mirror_reflect'))
        return matched


class _DiaryInteractionHandler(CommonScriptObjectInteractionHandler):
    @property
    def interactions_to_add(self):
        return tuple(
            tuning_id for tuning_id in (
                resolve_owned_id('interaction_diary_read'),
                resolve_owned_id('interaction_diary_snoop'),
            ) if tuning_id
        )

    def should_add(self, script_object, *args, **kwargs):
        _log_object_tuning_status()
        is_diary = any(marker in _object_name(script_object) for marker in _DIARY_MARKERS)
        _note_object_seen('diary', is_diary, _object_name(script_object),
                          resolve_owned_id('interaction_diary_read'))
        if is_diary:
            # Refresh the object's TooltipComponent from the cached entry, when set.
            text = _safe_getattr(script_object, '_sensewright_diary_tooltip', '')
            if text:
                apply_diary_tooltip(script_object, text)
        return is_diary


class _MailboxInteractionHandler(CommonScriptObjectInteractionHandler):
    @property
    def interactions_to_add(self):
        tuning_id = resolve_owned_id('interaction_mailbox')
        return (tuning_id,) if tuning_id else ()

    def should_add(self, script_object, *args, **kwargs):
        _log_object_tuning_status()
        name = _object_name(script_object)
        matched = any(marker in name for marker in _MAILBOX_MARKERS)
        _note_object_seen('mailbox', matched, name, resolve_owned_id('interaction_mailbox'))
        return matched


_register = CommonInteractionRegistry().register_handler
_register(_MirrorInteractionHandler(), CommonInteractionType.ON_SCRIPT_OBJECT_LOAD)
_register(_DiaryInteractionHandler(), CommonInteractionType.ON_SCRIPT_OBJECT_LOAD)
_register(_MailboxInteractionHandler(), CommonInteractionType.ON_SCRIPT_OBJECT_LOAD)
log_info('object_interactions: handlers registered (mirror, diary, mailbox)')

