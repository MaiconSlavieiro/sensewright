# sensewright_mod/dev_interactions.py
#
# Dev Mode actions (commit 3985684 shipped the menu shell; the functions behind
# the items are implemented here). Plan: docs/dev-mode-coauthor.md (S2/S5, B1-B5).
#
# The rewrite flows are LLM merges grounded in the native truth (R-0..R-7): the
# player's free text is sent as ``coauthor_text`` and the sidecar merges it with
# the stored profile/history and the director theme.
#
# Python 3.7 compatible.
import sims4.log
from sims4communitylib.classes.interactions.common_immediate_super_interaction import CommonImmediateSuperInteraction
from sims4communitylib.classes.testing.common_execution_result import CommonExecutionResult
from sims4communitylib.classes.testing.common_test_result import CommonTestResult
from sims4communitylib.dialogs.common_choice_outcome import CommonChoiceOutcome
from sims4communitylib.mod_support.mod_identity import CommonModIdentity
from sims4communitylib.modinfo import ModInfo

from sensewright_mod.dev_manager import SensewrightDevManager
from sensewright_mod.debug_log import log_exception, worker_log_info


def show_notification(title, text):
    try:
        from sims4communitylib.notifications.common_basic_notification import CommonBasicNotification
        from sims4communitylib.utils.localization.common_localization_utils import CommonLocalizationUtils
        CommonBasicNotification(
            CommonLocalizationUtils.create_localized_string(title),
            CommonLocalizationUtils.create_localized_string(text)
        ).show()
    except Exception as e:
        log_exception('Failed to show notification: {}'.format(e))


def _safe_getattr(obj, attr, default=None):
    try:
        return getattr(obj, attr, default)
    except Exception:
        return default


def _sim_info_and_id(interaction_sim):
    """Resolve (SimInfo, sim_id) from the interaction's source Sim object."""
    try:
        from sims4communitylib.utils.sims.common_sim_utils import CommonSimUtils
        info = CommonSimUtils.get_sim_info(interaction_sim)
    except Exception:
        info = interaction_sim
    return info, int(_safe_getattr(info, 'id', 0) or 0)


def _open_input_dialog(title, description, initial_value, on_submit):
    """Open S4CL's text-input dialog prefilled with ``initial_value``."""
    try:
        from sims4communitylib.dialogs.common_input_text_dialog import CommonInputTextDialog
        dialog = CommonInputTextDialog(ModInfo.get_identity(), title, description, initial_value)
        dialog.show(on_submit=on_submit)
        return True
    except Exception as e:
        log_exception('dev: input dialog failed: {}'.format(e))
        return False


logger = sims4.log.Logger('SensewrightDev')

class _SensewrightDevBaseInteraction(CommonImmediateSuperInteraction):
    @classmethod
    def get_mod_identity(cls) -> CommonModIdentity:
        return ModInfo.get_identity()

    @classmethod
    def get_log_identifier(cls) -> str:
        return 'sensewright_dev_interaction'

    @classmethod
    def on_test(cls, interaction_sim, interaction_target, interaction_context, **kwargs) -> CommonTestResult:
        if not SensewrightDevManager.dev_mode_enabled:
            return CommonTestResult(False, "Dev mode disabled.")
        return CommonTestResult.TRUE


# --- SIM DEVS ---
class SensewrightDevSimToggleDebugInteraction(_SensewrightDevBaseInteraction):
    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        new_state = SensewrightDevManager.toggle_debug_sim()
        state_str = "ENABLED" if new_state else "DISABLED"
        show_notification("Sim Debug", "Sim Debug is now {}".format(state_str))
        return CommonExecutionResult.TRUE

class SensewrightDevSimRewriteProfileInteraction(_SensewrightDevBaseInteraction):
    """B1 — co-author the Sim profile via an LLM merge (R-1/R-4/R-6)."""

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        try:
            from sensewright_mod.http_client import post_async, generate_trace_id
            from sensewright_mod.state_collector import get_current_game_state
            from sensewright_mod.i18n import get_current_language, t

            _info, sim_id = _sim_info_and_id(interaction_sim)
            state = get_current_game_state()

            def _submit(value, outcome):
                if outcome == CommonChoiceOutcome.CANCEL or not value:
                    return

                def _on_rewrite(response, trace_id=None):
                    profile = (response or {}).get('profile') or {}
                    summary = (profile.get('core_personality')
                               or profile.get('backstory')
                               or t('notify.dev.rewrite_done'))
                    show_notification(t('notify.dev.rewrite_title'), summary)

                post_async('/profile', {
                    'trace_id': generate_trace_id(),
                    'sim_id': sim_id,
                    'coauthor_text': value,
                    'player_id': 'player_1',
                    'save_id': state['save_id'],
                    'world_sim_tick': state['world_sim_tick'],
                    'lang': get_current_language(),
                }, callback=_on_rewrite)

            def _prefill(response, trace_id=None):
                profile = (response or {}).get('profile') or {}
                initial = profile.get('core_personality') or ''
                worker_log_info('dev.rewrite profile opened sim={}'.format(sim_id))
                _open_input_dialog(
                    t('notify.dev.rewrite_title'), t('notify.dev.rewrite_hint'),
                    initial, _submit,
                )

            post_async('/profile', {
                'trace_id': generate_trace_id(),
                'sim_id': sim_id,
                'force_interactive': False,
                'player_id': 'player_1',
                'save_id': state['save_id'],
                'world_sim_tick': state['world_sim_tick'],
                'lang': get_current_language(),
            }, callback=_prefill)
        except Exception as e:
            log_exception('SensewrightDevSimRewriteProfileInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE

class SensewrightDevSimDumpProfileInteraction(_SensewrightDevBaseInteraction):
    @classmethod
    def on_test(cls, interaction_sim, interaction_target, interaction_context, **kwargs) -> CommonTestResult:
        res = super().on_test(interaction_sim, interaction_target, interaction_context, **kwargs)
        if not res:
            return res
        if not SensewrightDevManager.debug_sim_enabled:
            return CommonTestResult(False, "Sim debug disabled.")
        return CommonTestResult.TRUE

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        """B3 — dump the Sim bundle to the worker log + a summarized notification."""
        try:
            from sensewright_mod.http_client import post_async, generate_trace_id
            from sensewright_mod.state_collector import get_current_game_state
            from sensewright_mod.i18n import get_current_language, t

            _info, sim_id = _sim_info_and_id(interaction_sim)
            state = get_current_game_state()

            def _callback(response, trace_id=None):
                data = response if isinstance(response, dict) else {}
                worker_log_info('dev.dump profile sim={} payload={}'.format(sim_id, data))
                profile = (data.get('export_data') or {}).get('profile') or {}
                body = profile.get('core_personality') or t('notify.dev.dump_done')
                show_notification(t('notify.dev.dump_profile_title'), body)

            post_async('/sim/export', {
                'trace_id': generate_trace_id(),
                'sim_id': sim_id,
                'save_id': state['save_id'],
                'world_sim_tick': state['world_sim_tick'],
                'lang': get_current_language(),
            }, callback=_callback)
        except Exception as e:
            log_exception('SensewrightDevSimDumpProfileInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE


# --- GOD DEVS ---
class SensewrightDevGodToggleDebugInteraction(_SensewrightDevBaseInteraction):
    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        new_state = SensewrightDevManager.toggle_debug_god()
        state_str = "ENABLED" if new_state else "DISABLED"
        show_notification("God Debug", "God Mod Debug is now {}".format(state_str))
        return CommonExecutionResult.TRUE

class SensewrightDevGodRewriteBackgroundInteraction(_SensewrightDevBaseInteraction):
    """B2 — co-author the neighborhood zeitgeist via an LLM merge (R-5/R-7)."""

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        try:
            from sensewright_mod.http_client import get_async, post_async, generate_trace_id
            from sensewright_mod.state_collector import get_current_game_state
            from sensewright_mod.i18n import get_current_language, t

            state = get_current_game_state()
            save_id = state['save_id']

            def _submit(value, outcome):
                if outcome == CommonChoiceOutcome.CANCEL or not value:
                    return

                def _on_rewrite(response, trace_id=None):
                    tags = (response or {}).get('tags') or []
                    body = ', '.join(tags) if tags else t('notify.dev.bg_done')
                    show_notification(t('notify.dev.bg_title'), body)

                post_async('/god/zeitgeist', {
                    'trace_id': generate_trace_id(),
                    'save_id': save_id,
                    'zeitgeist_text': value,
                    'lang': get_current_language(),
                }, callback=_on_rewrite)

            def _prefill(response, trace_id=None):
                zeitgeist = (response or {}).get('zeitgeist') or {}
                initial = ', '.join(zeitgeist.get('tags') or [])
                worker_log_info('dev.rewrite background opened save={}'.format(save_id))
                _open_input_dialog(
                    t('notify.dev.bg_title'), t('notify.dev.bg_hint'),
                    initial, _submit,
                )

            get_async('/world/neighborhood?save_id={}'.format(save_id), callback=_prefill)
        except Exception as e:
            log_exception('SensewrightDevGodRewriteBackgroundInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE

class SensewrightDevGodDumpZeitgeistInteraction(_SensewrightDevBaseInteraction):
    @classmethod
    def on_test(cls, interaction_sim, interaction_target, interaction_context, **kwargs) -> CommonTestResult:
        res = super().on_test(interaction_sim, interaction_target, interaction_context, **kwargs)
        if not res:
            return res
        if not SensewrightDevManager.debug_god_enabled:
            return CommonTestResult(False, "God debug disabled.")
        return CommonTestResult.TRUE

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        """B4 — dump the God Director state to the worker log + a summary."""
        try:
            from sensewright_mod.http_client import get_async
            from sensewright_mod.state_collector import get_current_game_state
            from sensewright_mod.i18n import get_current_language, t

            state = get_current_game_state()
            save_id = state['save_id']

            def _callback(response, trace_id=None):
                data = response if isinstance(response, dict) else {}
                worker_log_info('dev.dump god save={} payload={}'.format(save_id, data))
                tags = (data.get('zeitgeist') or {}).get('tags') or []
                theme = (data.get('arc') or {}).get('theme') or ''
                parts = [p for p in (theme, ', '.join(tags)) if p]
                body = ' | '.join(parts) if parts else t('notify.dev.dump_done')
                show_notification(t('notify.dev.dump_zeitgeist_title'), body)

            get_async('/god/dump?save_id={}'.format(save_id), callback=_callback)
        except Exception as e:
            log_exception('SensewrightDevGodDumpZeitgeistInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE


# --- SYSTEM DEVS (B5) ---
class SensewrightDevSysToggleDebugInteraction(_SensewrightDevBaseInteraction):
    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        new_state = SensewrightDevManager.toggle_debug_sys()
        state_str = "ENABLED" if new_state else "DISABLED"
        show_notification("System Debug", "System Debug is now {}".format(state_str))
        return CommonExecutionResult.TRUE

class SensewrightDevSysDumpStatusInteraction(_SensewrightDevBaseInteraction):
    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        try:
            from sensewright_mod.http_client import get_async
            from sensewright_mod.i18n import t

            def _callback(response, trace_id=None):
                data = response if isinstance(response, dict) else {}
                worker_log_info('dev.dump status payload={}'.format(data))
                summary = data.get('summary') or data.get('status') or t('notify.dev.dump_done')
                show_notification(t('notify.dev.status_title'), str(summary))

            get_async('/status', callback=_callback)
        except Exception as e:
            log_exception('SensewrightDevSysDumpStatusInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE

class SensewrightDevSysPanicInteraction(_SensewrightDevBaseInteraction):
    """Toggle the autonomy freeze (panic -> resume -> panic)."""

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        try:
            from sensewright_mod.http_client import get_async, post_async
            from sensewright_mod.i18n import t

            def _on_state(response, trace_id=None):
                paused = bool((response or {}).get('paused', False))
                endpoint = '/config/resume' if paused else '/config/panic'

                def _on_toggle(result, trace_id=None):
                    now_paused = bool((result or {}).get('paused', not paused))
                    body_key = 'notify.dev.panic_on' if now_paused else 'notify.dev.panic_off'
                    show_notification(t('notify.dev.panic_title'), t(body_key))

                post_async(endpoint, {}, callback=_on_toggle)

            get_async('/config/panic', callback=_on_state)
        except Exception as e:
            log_exception('SensewrightDevSysPanicInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE

class SensewrightDevSysReloadI18nInteraction(_SensewrightDevBaseInteraction):
    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        try:
            from sensewright_mod.http_client import post_async
            from sensewright_mod.i18n import t

            def _callback(response, trace_id=None):
                worker_log_info('dev.reload i18n payload={}'.format(response))
                show_notification(t('notify.dev.reload_title'), t('notify.dev.reload_done'))

            post_async('/i18n/reload', {}, callback=_callback)
        except Exception as e:
            log_exception('SensewrightDevSysReloadI18nInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE
