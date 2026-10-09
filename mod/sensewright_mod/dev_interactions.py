# sensewright_mod/dev_interactions.py
import sims4.log
from sims4communitylib.classes.interactions.common_immediate_super_interaction import CommonImmediateSuperInteraction
from sims4communitylib.classes.testing.common_execution_result import CommonExecutionResult
from sims4communitylib.classes.testing.common_test_result import CommonTestResult
from sims4communitylib.mod_support.mod_identity import CommonModIdentity
from sims4communitylib.modinfo import ModInfo

from sensewright_mod.dev_manager import SensewrightDevManager
from sensewright_mod.debug_log import log_exception

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
    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        show_notification("WIP", "Co-author UI not fully implemented yet.")
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
        show_notification("Sim Profile Dump", "Triggering dump...")
        return CommonExecutionResult.TRUE


# --- GOD DEVS ---
class SensewrightDevGodToggleDebugInteraction(_SensewrightDevBaseInteraction):
    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        new_state = SensewrightDevManager.toggle_debug_god()
        state_str = "ENABLED" if new_state else "DISABLED"
        show_notification("God Debug", "God Mod Debug is now {}".format(state_str))
        return CommonExecutionResult.TRUE

class SensewrightDevGodRewriteBackgroundInteraction(_SensewrightDevBaseInteraction):
    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        show_notification("WIP", "Neighborhood co-author UI not fully implemented yet.")
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
        show_notification("Zeitgeist Dump", "Triggering dump...")
        return CommonExecutionResult.TRUE
