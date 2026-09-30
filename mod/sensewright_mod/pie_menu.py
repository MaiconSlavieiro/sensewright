"""
Pie-menu interactions for Sensewright, built on S4CL (the new stack base).

Each interaction is an S4CL ``CommonImmediateSuperInteraction`` registered in
Python - no tuning XML, no DBPF package and no XmlInjector dependency. When S4CL
is unavailable the classes degrade to the native ``ImmediateSuperInteraction``
(or a plain object) so this module still imports on a plain CPython for tests.

Display names come from the data-driven locale system (``i18n.t``) and are
resolved at interaction time, so ``sw.lang`` still switches language at runtime.
"""

from . import i18n, integrations
from .debug_log import log_exception, debug_log


def _native_interaction_base():
    try:
        from interactions.base.immediate_interaction import (  # type: ignore
            ImmediateSuperInteraction)
        return ImmediateSuperInteraction
    except Exception:
        return object


# Stack base: S4CL. Native fallback otherwise.
_S4CL_BASE = integrations.s4cl_interaction_base()
_INTERACTION_BASE = _S4CL_BASE or _native_interaction_base()


def _localize(text):
    """Best-effort LocalizedString for the interaction display name."""
    return integrations.native_localized_string(text)


class _SensewrightInteraction(_INTERACTION_BASE):
    """Base pie-menu interaction: runs ``ACTION`` when chosen."""

    ACTION = ""
    DISPLAY_KEY = ""

    @classmethod
    def _display_name(cls):
        """Localized display name resolved at interaction time (sw.lang aware)."""
        key = getattr(cls, "DISPLAY_KEY", "")
        try:
            text = i18n.t(key) if key else getattr(cls, "__name__", "Sensewright")
        except Exception:
            text = getattr(cls, "__name__", "Sensewright")
        return _localize(text)

    # S4CL reads ``display_name``; provide it as a class attribute when possible.
    try:
        if _S4CL_BASE is not None:
            display_name = _display_name.__func__(None)  # noqa: B010 (best-effort)
    except Exception:
        pass

    def _run_interaction_gen(self, timeline):
        try:
            super()._run_interaction_gen(timeline)
        except Exception as exc:
            log_exception("pie_menu.run.super", exc)
        try:
            _dispatch(self.ACTION, getattr(self, "target", None))
        except Exception as exc:
            log_exception("pie_menu.run.dispatch", exc)
        return True


class SensewrightPanelInteraction(_SensewrightInteraction):
    """Open the Sensewright configuration panel."""

    ACTION = "panel"
    DISPLAY_KEY = "cmd.pie.panel"


class SensewrightChatInteraction(_SensewrightInteraction):
    """Open a text-input dialog and chat with the clicked Sim."""

    ACTION = "chat"
    DISPLAY_KEY = "cmd.pie.chat"


class SensewrightConfirmInteraction(_SensewrightInteraction):
    """Open a confirmation (Ok/Cancel) dialog."""

    ACTION = "confirm"
    DISPLAY_KEY = "cmd.pie.confirm"


class SensewrightHudInteraction(_SensewrightInteraction):
    """Toggle the debug HUD."""

    ACTION = "hud"
    DISPLAY_KEY = "cmd.pie.hud"


_INTERACTIONS = (
    SensewrightPanelInteraction,
    SensewrightChatInteraction,
    SensewrightConfirmInteraction,
    SensewrightHudInteraction,
)

_REGISTERED = {"done": False}


def install() -> bool:
    """Register the interactions with S4CL so they appear in the pie menu.

    Best-effort and idempotent. Returns True when at least one interaction was
    registered. Requires S4CL; without it the classes exist but are not offered.
    """
    if _REGISTERED["done"]:
        return True
    if _S4CL_BASE is None:
        debug_log("pie_menu.install: S4CL unavailable; interactions not registered")
        return False
    registered = 0
    for interaction_cls in _INTERACTIONS:
        try:
            if integrations.s4cl_register_interaction(interaction_cls):
                registered += 1
        except Exception as exc:
            log_exception("pie_menu.install", exc)
    _REGISTERED["done"] = registered > 0
    debug_log("pie_menu.install: registered {}/{} interactions".format(
        registered, len(_INTERACTIONS)))
    return registered > 0


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
        elif action == "panel":
            from . import panel_ui
            panel_ui.open_panel(sim_info)
    except Exception as exc:
        log_exception("pie_menu._dispatch." + str(action), exc)
