import sims4.log
from interactions.base.interaction import Interaction
from interactions.base.super_interaction import SuperInteraction
from sensewright_mod.dev_manager import SensewrightDevManager
from sensewright_mod.engine_facade import show_notification

logger = sims4.log.Logger('SensewrightDev')

class SensewrightDevSimBaseInteraction(SuperInteraction):
    @classmethod
    def _test(cls, target, context, **kwargs):
        if not SensewrightDevManager.dev_mode_enabled:
            return sims4.tuning.instances.TestResult(False, "Dev mode disabled.")
        return super()._test(target, context, **kwargs)

class SensewrightDevGodBaseInteraction(SuperInteraction):
    @classmethod
    def _test(cls, target, context, **kwargs):
        if not SensewrightDevManager.dev_mode_enabled:
            return sims4.tuning.instances.TestResult(False, "Dev mode disabled.")
        return super()._test(target, context, **kwargs)

class SensewrightDevSysBaseInteraction(SuperInteraction):
    @classmethod
    def _test(cls, target, context, **kwargs):
        if not SensewrightDevManager.dev_mode_enabled:
            return sims4.tuning.instances.TestResult(False, "Dev mode disabled.")
        return super()._test(target, context, **kwargs)

# --- SIM DEVS ---
class SensewrightDevSimToggleDebugInteraction(SensewrightDevSimBaseInteraction):
    def _run_interaction_gen(self, timeline):
        new_state = SensewrightDevManager.toggle_debug_sim()
        state_str = "ENABLED" if new_state else "DISABLED"
        show_notification("Sim Debug", f"Sim Debug is now {state_str}")
        return True

class SensewrightDevSimRewriteProfileInteraction(SensewrightDevSimBaseInteraction):
    def _run_interaction_gen(self, timeline):
        # Trigger input dialog for co-author
        show_notification("WIP", "Co-author UI not fully implemented yet.")
        return True

class SensewrightDevSimDumpProfileInteraction(SensewrightDevSimBaseInteraction):
    @classmethod
    def _test(cls, target, context, **kwargs):
        if not SensewrightDevManager.debug_sim_enabled:
            return sims4.tuning.instances.TestResult(False, "Sim debug disabled.")
        return super()._test(target, context, **kwargs)

    def _run_interaction_gen(self, timeline):
        show_notification("Sim Profile Dump", "Triggering dump...")
        return True

# --- GOD DEVS ---
class SensewrightDevGodToggleDebugInteraction(SensewrightDevGodBaseInteraction):
    def _run_interaction_gen(self, timeline):
        new_state = SensewrightDevManager.toggle_debug_god()
        state_str = "ENABLED" if new_state else "DISABLED"
        show_notification("God Debug", f"God Mod Debug is now {state_str}")
        return True

class SensewrightDevGodRewriteBackgroundInteraction(SensewrightDevGodBaseInteraction):
    def _run_interaction_gen(self, timeline):
        show_notification("WIP", "Neighborhood co-author UI not fully implemented yet.")
        return True

class SensewrightDevGodDumpZeitgeistInteraction(SensewrightDevGodBaseInteraction):
    @classmethod
    def _test(cls, target, context, **kwargs):
        if not SensewrightDevManager.debug_god_enabled:
            return sims4.tuning.instances.TestResult(False, "God debug disabled.")
        return super()._test(target, context, **kwargs)

    def _run_interaction_gen(self, timeline):
        show_notification("Zeitgeist Dump", "Triggering dump...")
        return True
