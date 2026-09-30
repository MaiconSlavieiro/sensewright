"""
Chat UI rendering for Sensewright.
3-layer fallback: UiDialogNotification -> sims4.commands output -> debug log.
All game imports are lazy/guarded so module imports fine outside the game.
"""

from . import i18n
from .debug_log import debug_log, log_exception




def _try_import_ui_dialog():
    """Try to import UiDialogNotification and related classes."""
    try:
        from ui.ui_dialog_notification import UiDialogNotification  # type: ignore
        from sims4.localization import TunableLocalizedStringFactory  # type: ignore
        from sims4.localization import LocalizationHelperTuning  # type: ignore
        return UiDialogNotification, TunableLocalizedStringFactory, LocalizationHelperTuning
    except Exception:
        pass

    try:
        from sims4.ui import UiDialogNotification  # type: ignore
        from sims4.localization import TunableLocalizedStringFactory  # type: ignore
        from sims4.localization import LocalizationHelperTuning  # type: ignore
        return UiDialogNotification, TunableLocalizedStringFactory, LocalizationHelperTuning
    except Exception:
        pass

    return None, None, None


def _try_import_commands():
    """Try to import sims4.commands for console output."""
    try:
        import sims4.commands  # type: ignore
        return sims4.commands
    except Exception:
        return None


def _log(context, exc):
    """Best-effort diagnostic logging to sensewright_output.log. Never raises."""
    try:
        if isinstance(exc, str):
            exc = RuntimeError(exc)
        log_exception("chat_ui.{}".format(context), exc)
    except Exception:
        pass


def _notification_owner(sim_info=None):
    """Resolve the owner a notification dialog should be shown to.

    Prefers the live Sim instance, then the passed SimInfo, then the active
    client's Sim. Returns None when the game services are unavailable.
    """
    if sim_info is not None:
        try:
            getter = getattr(sim_info, "get_sim_instance", None)
            instance = getter() if getter is not None else None
            if instance is not None:
                return instance
        except Exception as exc:
            _log("_notification_owner", exc)
        return sim_info
    try:
        import services  # type: ignore

        client_manager = services.client_manager()
        if client_manager:
            client = client_manager.get_first_client()
            if client:
                return getattr(client, "active_sim", None) or getattr(
                    client, "active_sim_info", None)
    except Exception as exc:
        _log("_notification_owner", exc)
        return None
    return None


def _build_dialog(title, text, sim_info=None):
    """Build a ``UiDialogNotification`` for ``title``/``text``.

    Returns ``(dialog, error)``: ``dialog`` is None on failure and ``error`` is a
    short human-readable reason (import root, owner, ``get_raw_text``, ``default``).
    Never raises.
    """
    try:
        from ui.ui_dialog_notification import UiDialogNotification  # type: ignore
    except Exception as exc:
        return None, "import ui.ui_dialog_notification: {!r}".format(exc)
    try:
        from sims4.localization import LocalizationHelperTuning  # type: ignore
    except Exception as exc:
        return None, "import LocalizationHelperTuning: {!r}".format(exc)

    owner = _notification_owner(sim_info)
    if owner is None:
        return None, "no owner (services/active Sim unavailable)"
    if not hasattr(owner, "ref"):
        return None, "owner {!r} has no .ref()".format(type(owner).__name__)

    try:
        loc_title = LocalizationHelperTuning.get_raw_text(title)
        loc_text = LocalizationHelperTuning.get_raw_text(text)
    except Exception as exc:
        return None, "get_raw_text: {!r}".format(exc)

    # The dialog resolves text/title by *calling* them with tokens
    # (``_build_localized_string_msg`` does ``string(*tokens)``), so pass
    # factories that return the LocalizedString -- not the LocalizedString
    # itself (that raised "'LocalizedString' object is not callable").
    def _title_factory(*args, **kwargs):
        return loc_title

    def _text_factory(*args, **kwargs):
        return loc_text

    try:
        dialog = UiDialogNotification.TunableFactory().default(
            owner, title=_title_factory, text=_text_factory,
        )
    except Exception as exc:
        return None, "default(...): {!r}".format(exc)
    if dialog is None:
        return None, "default(...) returned None"
    return dialog, None


def notification_diagnostics(title, text, sim_info=None):
    """Attempt the dialog path and report the exact failure. Never raises.

    Used by the ``sw.uitest`` cheat to pinpoint why no in-game UI appears.
    Returns ``{"ok", "layer", "error"}``.
    """
    dialog, error = _build_dialog(title, text, sim_info)
    if dialog is None:
        return {"ok": False, "layer": "build", "error": error}
    try:
        dialog.show_dialog()
        return {"ok": True, "layer": "dialog", "error": None}
    except Exception as exc:
        return {"ok": False, "layer": "show_dialog", "error": repr(exc)}


def show_notification(
    title: str,
    text: str,
    sim_info=None,
    urgent: bool = False,
    connection=None
) -> bool:
    """
    Show a notification to the player.
    Returns True if successful, False if all fallbacks failed.

    ``title``/``text`` are plain strings turned into localized strings via
    ``LocalizationHelperTuning.get_raw_text`` (the validated runtime path).
    ``urgent`` is kept for API compatibility; the notification tunable exposes
    urgency as an enum, so it is not forwarded here.
    """
    # Layer 1: UiDialogNotification
    dialog, error = _build_dialog(title, text, sim_info)
    if dialog is not None:
        try:
            dialog.show_dialog()
            return True
        except Exception as exc:
            _log("show_dialog", exc)
    elif error:
        _log("_build_dialog", error)

    # Layer 2: sims4.commands output (cheat console)
    commands = _try_import_commands()
    if commands is not None:
        cheat_cls = getattr(commands, "CheatOutput", None)
        if cheat_cls is not None:
            for conn in (connection, None):
                try:
                    cheat_cls(conn)("{}: {}".format(title, text))
                    return True
                except Exception as exc:
                    _log("show_notification.console", exc)

    # Layer 3: debug log (last resort, visible in sensewright_output.log)
    try:
        debug_log("[Sensewright] {}: {}".format(title, text))
        return True
    except Exception as exc:
        _log("show_notification.log", exc)

    return False


def show_simple_notification(message: str, sim_info=None, connection=None) -> bool:
    """Show a simple notification with the localized default title."""
    return show_notification(i18n.t("notify.app_title"), message, sim_info,
                             connection=connection)


def show_error(message: str, sim_info=None, connection=None) -> bool:
    """Show an error notification with the localized error title."""
    return show_notification(i18n.t("error.title"), message, sim_info, urgent=True,
                             connection=connection)


def output_to_console(message: str, connection=None) -> bool:
    """Output a message to the cheat console."""
    commands = _try_import_commands()
    if commands is not None:
        cheat_cls = getattr(commands, "CheatOutput", None)
        if cheat_cls is not None:
            for conn in (connection, None):
                try:
                    cheat_cls(conn)(message)
                    return True
                except Exception as exc:
                    _log("output_to_console", exc)
    return False