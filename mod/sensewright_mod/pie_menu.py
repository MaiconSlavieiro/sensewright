"""
Pie-menu interactions for Sensewright, built on S4CL (the new stack base).

Each interaction is an S4CL ``CommonImmediateSuperInteraction``. The interaction
is declared by a tuning resource shipped in ``Sensewright.package`` (see
``mod/tuning/interactions/*.xml``), whose ``m``/``c`` attributes point at the
classes below. S4CL's ``CommonInteractionRegistry`` then adds those tuning ids to
the matching script objects at load - no XmlInjector and no runtime injection.

When S4CL is unavailable (offline tests) the classes degrade to the native
``ImmediateSuperInteraction`` (or a plain object) so this module still imports on
a plain CPython, and ``install()`` is a no-op. Display names come from the
packaged STBL (en + pt-BR); ``sw.lang`` can still override them at runtime via
``get_name``.
"""

from . import i18n, integrations
from .debug_log import log_exception, debug_log


# Tuning instance ids: the ``s`` attribute of ``mod/tuning/interactions/*.xml``.
# Keep in sync with the XML and ``mod/tuning/stbl.json`` display-name ids.
TUNING_PANEL = 16907656493241729025
TUNING_CHAT = 16907656493241729026
TUNING_CONFIRM = 16907656493241729027
TUNING_HUD = 16907656493241729028

# Vanilla tag used to add the panel entry to computers (matches the old snippet).
_COMPUTER_TAG = "FUNC_COMPUTER"


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


def _name_override():
    """A ``flexmethod`` ``get_name`` that resolves the runtime locale.

    Returns ``None`` when the game's ``flexmethod`` is unavailable (offline), so
    the packaged STBL display name is used instead.
    """
    try:
        from sims4.utils import flexmethod  # type: ignore
    except Exception:
        return None

    def get_name(cls, inst, target=None, context=None, **interaction_parameters):
        try:
            key = getattr(cls, "DISPLAY_KEY", "")
            text = i18n.t(key) if key else getattr(cls, "__name__", "Sensewright")
        except Exception as exc:
            log_exception("pie_menu.get_name", exc)
            text = getattr(cls, "__name__", "Sensewright")
        return _localize(text)

    return flexmethod(get_name)


class _SensewrightInteraction(_INTERACTION_BASE):
    """Base pie-menu interaction: runs ``ACTION`` when chosen."""

    ACTION = ""
    DISPLAY_KEY = ""

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


# Runtime language switching: only when S4CL/game present (flexmethod available).
if _S4CL_BASE is not None:
    _get_name = _name_override()
    if _get_name is not None:
        _SensewrightInteraction.get_name = _get_name


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


def _build_handlers():
    """Build the S4CL interaction handlers, or return an empty tuple.

    * all four interactions are added to **Sims**;
    * the panel interaction is added to **computers** (tag ``Func_Computer``).
    """
    handler_base = integrations.s4cl_interaction_handler_base()
    if handler_base is None:
        return ()

    all_ids = (TUNING_PANEL, TUNING_CHAT, TUNING_CONFIRM, TUNING_HUD)

    class _SimInteractionHandler(handler_base):
        @property
        def interactions_to_add(self):
            return all_ids

        def should_add(self, script_object, *args, **kwargs):
            try:
                type_utils = integrations.s4cl_type_utils()
                return bool(type_utils
                            and type_utils.is_sim_instance(script_object))
            except Exception:
                return False

    class _ComputerInteractionHandler(handler_base):
        @property
        def interactions_to_add(self):
            return (TUNING_PANEL,)

        def should_add(self, script_object, *args, **kwargs):
            try:
                tag_utils = integrations.s4cl_object_tag_utils()
                tag = integrations.s4cl_game_tag(_COMPUTER_TAG)
                return bool(tag_utils and tag is not None
                            and tag_utils.has_game_tag(script_object, tag))
            except Exception:
                return False

    return (_SimInteractionHandler(), _ComputerInteractionHandler())


def install() -> bool:
    """Register the interactions with S4CL so they appear in the pie menu.

    Best-effort and idempotent. Returns True when at least one handler was
    registered. Requires S4CL; without it the classes exist but are not offered.
    """
    if _REGISTERED["done"]:
        return True
    if _S4CL_BASE is None:
        debug_log("pie_menu.install: S4CL unavailable; interactions not registered")
        return False
    try:
        interaction_type = integrations.s4cl_interaction_type("ON_SCRIPT_OBJECT_LOAD")
    except Exception as exc:
        log_exception("pie_menu.install.type", exc)
        return False
    if interaction_type is None:
        debug_log("pie_menu.install: CommonInteractionType unavailable")
        return False

    registered = 0
    for handler in _build_handlers():
        try:
            if integrations.s4cl_register_interaction_handler(handler, interaction_type):
                registered += 1
        except Exception as exc:
            log_exception("pie_menu.install", exc)
    _REGISTERED["done"] = registered > 0
    debug_log("pie_menu.install: registered {}/2 interaction handlers".format(
        registered))
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
