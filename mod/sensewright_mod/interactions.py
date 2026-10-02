# Sensewright v2 — Custom Pie Menu Interactions (S4CL)
# Python 3.7 compatible
#
# The interaction classes here are referenced by the `<I c="..." m="...">`
# tuning files under mod/tuning/interactions/. They are added to every Sim by
# `pie_menu.register_pie_menu_interactions()` through S4CL's
# CommonInteractionRegistry, which is the supported replacement for the old
# InteractionSnippet tuning path (snippets referencing non-existent test globals
# silently never appear).

from sims.sim import Sim
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

from sensewright_mod.debug_log import log_exception, log_info, worker_log_info, worker_log_warn
from sensewright_mod.tuning import resolve_owned_id, owned_bias_keys


def _resolve_target_sim_info(interaction_target):
    """Best-effort conversion of an interaction target to a SimInfo."""
    if interaction_target is None:
        return None
    try:
        sim_info = CommonSimUtils.get_sim_info(interaction_target)
        if sim_info is not None:
            return sim_info
    except Exception:
        pass
    return interaction_target


class _SensewrightBaseInteraction(CommonImmediateSuperInteraction):
    """Shared plumbing for Sensewright's custom immediate interactions."""

    @classmethod
    def get_mod_identity(cls) -> CommonModIdentity:
        return ModInfo.get_identity()

    @classmethod
    def get_log_identifier(cls) -> str:
        return 'sensewright_interaction'

    @classmethod
    def on_test(cls, interaction_sim, interaction_target, interaction_context, **kwargs) -> CommonTestResult:
        return CommonTestResult.TRUE


class SensewrightChatInteraction(_SensewrightBaseInteraction):
    """Right-click a Sim -> 'Mandar SMS...' opens the chat dialog."""

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        try:
            from sensewright_mod.chat_ui import start_chat
            target = _resolve_target_sim_info(interaction_target) or interaction_sim
            if target is not None:
                start_chat(target, 'phone_sms')
        except Exception as e:
            log_exception('SensewrightChatInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE


class SensewrightProvokeInteraction(_SensewrightBaseInteraction):
    """Right-click a Sim -> 'Provocar Cena Aqui...' asks the sidecar for a scene."""

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        try:
            from sensewright_mod.pie_menu import _on_provoke_scene_interaction
            target = _resolve_target_sim_info(interaction_target)
            _on_provoke_scene_interaction(interaction_sim, target)
        except Exception as e:
            log_exception('SensewrightProvokeInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE


class SensewrightQuickMenuInteraction(_SensewrightBaseInteraction):
    """Right-click a Sim -> 'Menu Rapido Sensewright' opens the Quick Menu."""

    def on_started(self, interaction_sim, interaction_target) -> CommonExecutionResult:
        try:
            from sensewright_mod.panel_ui import show_quick_menu
            show_quick_menu()
        except Exception as e:
            log_exception('SensewrightQuickMenuInteraction failed: {}'.format(e))
        return CommonExecutionResult.TRUE


log_info('Sensewright pie menu interaction classes loaded')


# Register interaction handlers at module import time. S4CL injects
# `ScriptObject.on_add`, so registering here (before households and sims load)
# ensures every Sim instance receives the Sensewright interactions. Registering
# at session-start would be too late for already-spawned Sims.
_diagnostic_logged = False
_hook_seen = False


def _resolve_interaction_ids():
    """Resolve our interaction tuning IDs, logging the result once."""
    global _diagnostic_logged
    ids = tuple(
        interaction_id for interaction_id in (
            resolve_owned_id('interaction_chat'),
            resolve_owned_id('interaction_provoke'),
            resolve_owned_id('interaction_panel'),
        ) if interaction_id
    )
    if not _diagnostic_logged:
        _diagnostic_logged = True
        if ids:
            worker_log_info('pie menu: resolved interaction ids {}'.format(ids))
        else:
            worker_log_warn('pie menu: could NOT resolve interaction ids')
    return ids


def _log_tuning_load_status():
    """Log whether each Sensewright-owned tuning actually loaded in the game."""
    try:
        import services
        from sims4.resources import Types
    except Exception as e:
        worker_log_warn('tuning check: cannot import services/Types: {}'.format(e))
        return

    checks = [
        ('interaction.chat', getattr(Types, 'INTERACTION', None), resolve_owned_id('interaction_chat')),
        ('interaction.provoke', getattr(Types, 'INTERACTION', None), resolve_owned_id('interaction_provoke')),
        ('interaction.panel', getattr(Types, 'INTERACTION', None), resolve_owned_id('interaction_panel')),
        ('buff.epiphany', getattr(Types, 'BUFF', None), resolve_owned_id('buff_dream_epiphany')),
        ('trait.confidant', getattr(Types, 'TRAIT', None), resolve_owned_id('trait_hidden_no_walkby')),
    ]
    # Autonomy-bias buffs must actually load or bias_interaction is a no-op.
    for key in owned_bias_keys():
        checks.append(('buff.' + key, getattr(Types, 'BUFF', None), resolve_owned_id(key)))
    for label, tuning_type, tuning_id in checks:
        if tuning_type is None:
            worker_log_warn('tuning {}: Types attribute missing'.format(label))
            continue
        try:
            manager = services.get_instance_manager(tuning_type)
            instance = manager.get(tuning_id) if manager is not None else None
            worker_log_info('tuning {} id={} loaded={}'.format(label, tuning_id, instance is not None))
        except Exception as e:
            worker_log_warn('tuning {} check error: {}'.format(label, e))


class _SensewrightSimInteractionHandler(CommonScriptObjectInteractionHandler):
    """Adds Sensewright's interactions to every Sim instance."""

    @property
    def interactions_to_add(self):
        return _resolve_interaction_ids()

    def should_add(self, script_object, *args, **kwargs):
        global _hook_seen
        is_sim = isinstance(script_object, Sim)
        if is_sim and not _hook_seen:
            _hook_seen = True
            worker_log_info('pie menu: interaction hook reached a Sim instance')
            _log_tuning_load_status()
        return is_sim


# Expose the interactions on the Sim pie menu, the relationship panel and the
# phone, so the player has multiple in-game entry points.
_register = CommonInteractionRegistry().register_handler
_handler = _SensewrightSimInteractionHandler()
_register(_handler, CommonInteractionType.ON_SCRIPT_OBJECT_LOAD)
_register(_handler, CommonInteractionType.ADD_TO_SIM_RELATIONSHIP_PANEL_INTERACTIONS)
_register(_handler, CommonInteractionType.ADD_TO_SIM_PHONE_INTERACTIONS)
worker_log_info('pie menu: handlers registered (pie, relationship panel, phone)')

