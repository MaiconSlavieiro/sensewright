"""
Pie-menu interactions for Sensewright (spike).

The tuning lives in ``mod/tuning/interactions/*.xml`` and references these
classes through ``m="sensewright_mod.pie_menu"``. Each interaction opens a
native dialog (or runs a small action) so the entry can be judged in-game.

Phase 1 (this spike) puts the items in an existing EA pie-menu category
("Actions") to validate the pipeline; a custom "Sensewright" category comes
later. The classes are import-safe outside the game (the guards below).
"""

from . import i18n
from .debug_log import log_exception

try:
    from interactions.base.immediate_interaction import (  # type: ignore
        ImmediateSuperInteraction)
    _AVAILABLE = True
except Exception as exc:  # outside the game
    ImmediateSuperInteraction = object
    _AVAILABLE = False
    try:
        log_exception("pie_menu.import", exc)
    except Exception:
        pass

try:
    from event_testing.results import TestResult  # type: ignore
    from sims4.utils import flexmethod  # type: ignore
except Exception:
    TestResult = None

    def flexmethod(function):
        return function

# Diagnostic: if this line shows in sensewright_output.log, the game loaded the
# tuning package and imported this module (so the .package format is right).
try:
    from .debug_log import debug_log
    debug_log("[pie_menu] module imported (interactions available={})".format(
        _AVAILABLE))
except Exception:
    pass


def _sim_info_for(target):
    """Best-effort SimInfo behind a clicked pie-menu target. Never raises."""
    try:
        if target is None:
            return None
        info = getattr(target, "sim_info", None)
        if info is not None:
            return info
        getter = getattr(target, "get_sim_info", None)
        if callable(getter):
            return getter()
    except Exception as exc:
        log_exception("pie_menu._sim_info_for", exc)
    return None


def _chat(text, sim_info):
    try:
        from . import main
        main.run_chat(text, sim_info)
    except Exception as exc:
        log_exception("pie_menu._chat", exc)


def _confirmed(sim_info):
    try:
        from . import chat_ui
        chat_ui.show_simple_notification(i18n.t("cmd.pie.confirm.done"), sim_info)
    except Exception as exc:
        log_exception("pie_menu._confirmed", exc)


def _dispatch(action, target=None):
    """Run the action behind a pie-menu item. Never raises."""
    try:
        from . import hud

        sim_info = _sim_info_for(target)
        debug_log("[pie_menu] dispatch {}".format(action))

        if action == "hud":
            hud.toggle()
            hud.emit_line()
        elif action == "chat":
            from . import dialogs
            dialogs.prompt_text(
                sim_info,
                i18n.t("cmd.pie.chat.title"),
                i18n.t("cmd.pie.chat.body"),
                placeholder=i18n.t("cmd.pie.chat.placeholder"),
                on_submit=lambda text: _chat(text, sim_info),
            )
        elif action == "confirm":
            from . import dialogs
            dialogs.confirm(
                sim_info,
                i18n.t("cmd.pie.confirm.title"),
                i18n.t("cmd.pie.confirm.body"),
                on_ok=lambda: _confirmed(sim_info),
            )
        else:
            from . import ui_probe
            ui_probe.run(action)
    except Exception as exc:
        log_exception("pie_menu._dispatch." + str(action), exc)


_TEST_SEEN = set()


class _SensewrightInteraction(ImmediateSuperInteraction):
    """Base pie-menu interaction: runs ``ACTION`` when chosen."""

    ACTION = ""

    @flexmethod
    def test(cls, inst, *args, **kwargs):
        """Always available on the clicked Sim/object.

        The base ``ImmediateSuperInteraction.test`` does not surface a tuning
        with no tests, so — like the working TS4ControlAnySim interactions — we
        return ``TestResult.TRUE`` explicitly. Logs each class once so the log
        shows whether the game even considers the interaction.
        """
        try:
            name = getattr(cls, "__name__", "?")
            if name not in _TEST_SEEN:
                _TEST_SEEN.add(name)
                debug_log("[pie_menu] test() called for {}".format(name))
        except Exception:
            pass
        if TestResult is not None:
            return TestResult.TRUE
        return True

    def _run_interaction_gen(self, timeline):
        try:
            super()._run_interaction_gen(timeline)
        except Exception as exc:
            log_exception("pie_menu.run.super", exc)
        _dispatch(self.ACTION, getattr(self, "target", None))
        return True


class SensewrightPanelInteraction(_SensewrightInteraction):
    """Open the navigable panel mock."""

    ACTION = "panel"


class SensewrightChatInteraction(_SensewrightInteraction):
    """Open a text-input dialog and chat with the clicked Sim."""

    ACTION = "chat"


class SensewrightConfirmInteraction(_SensewrightInteraction):
    """Open a confirmation (Ok/Cancel) dialog."""

    ACTION = "confirm"


class SensewrightHudInteraction(_SensewrightInteraction):
    """Toggle the debug HUD."""

    ACTION = "hud"

