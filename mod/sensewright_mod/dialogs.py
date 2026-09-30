"""
Native dialog helpers for Sensewright (text input, confirmation).

The stack base is used first (S4CL ok/cancel via ``integrations``); the
previously validated native dialogs remain the fallback. All game/library
imports are lazy and guarded; the public functions are best-effort and never
raise.
"""

from . import i18n, integrations
from .debug_log import log_exception


def _owner(sim_info=None):
    """Resolve the live Sim instance a dialog should be shown to."""
    if sim_info is not None:
        try:
            getter = getattr(sim_info, "get_sim_instance", None)
            instance = getter() if callable(getter) else None
            if instance is not None:
                return instance
        except Exception as exc:
            log_exception("dialogs._owner.instance", exc)
        return sim_info
    try:
        import services  # type: ignore

        client_manager = services.client_manager()
        if client_manager:
            client = client_manager.get_first_client()
            if client:
                return (getattr(client, "active_sim", None)
                        or getattr(client, "active_sim_info", None))
    except Exception as exc:
        log_exception("dialogs._owner.client", exc)
    return None


def _raw(text):
    try:
        from sims4.localization import LocalizationHelperTuning  # type: ignore
        return LocalizationHelperTuning.get_raw_text(text)
    except Exception:
        return text


def _factory(text):
    localized = _raw(text)

    def _value(*args, **kwargs):
        return localized

    return _value


def _make_length_restriction():
    """The ``length_restriction`` object ``UiTextInput`` expects."""

    def build_msg(self, dialog, msg, *additional_tokens):
        try:
            msg.max_length = 255
            msg.min_length = 0
        except Exception as exc:
            log_exception("dialogs.length_restriction.build_msg", exc)

    try:
        from sims4.tuning.tunable import (  # type: ignore
            AutoFactoryInit, HasTunableSingletonFactory)
        bases = (HasTunableSingletonFactory, AutoFactoryInit)
    except Exception:
        bases = (object,)
    return type("SensewrightTextInputLength", bases, {"build_msg": build_msg})


def prompt_text(sim_info, title, body, placeholder="", initial="", on_submit=None):
    """Open a native **text** input dialog. Returns True when it was shown.

    Calls ``on_submit(text)`` with the entered (non-empty) text on OK. Never raises.
    """
    try:
        from sims4.collections import AttributeDict  # type: ignore
        from ui.ui_dialog_generic import UiDialogTextInputOk  # type: ignore
        from ui.ui_text_input import UiTextInput  # type: ignore
    except Exception as exc:
        log_exception("dialogs.prompt_text.import", exc)
        return False

    owner = _owner(sim_info)
    if owner is None:
        return False

    try:
        text_input = UiTextInput(sort_order=0, restricted_characters=None, height=0)
        text_input.default_text = _factory(placeholder or initial)
        text_input.title = _factory(body)
        text_input.initial_value = _factory(initial)
        text_input.check_profanity = False
        text_input.length_restriction = _make_length_restriction()()
        inputs = AttributeDict({"primary": text_input})

        dialog = UiDialogTextInputOk.TunableFactory().default(
            owner,
            title=_factory(title),
            text=_factory(body),
            text_inputs=inputs,
            text_ok=_factory(i18n.t("god.zeitgeist.button.ok")),
            is_special_dialog=False,
        )
    except Exception as exc:
        log_exception("dialogs.prompt_text.build", exc)
        return False

    def _on_done(response):
        value = None
        try:
            value = getattr(response.text_inputs["primary"], "value", None)
        except Exception as exc:
            log_exception("dialogs.prompt_text.on_done", exc)
        if value and on_submit is not None:
            try:
                on_submit(value)
            except Exception as exc:
                log_exception("dialogs.prompt_text.submit", exc)

    for name in ("add_callback", "add_listener"):
        callback = getattr(dialog, name, None)
        if callable(callback):
            try:
                callback(_on_done)
                break
            except Exception:
                pass

    try:
        dialog.show_dialog()
        return True
    except Exception as exc:
        log_exception("dialogs.prompt_text.show", exc)
        return False


def confirm(sim_info, title, body, on_ok=None):
    """Open a confirmation dialog. Returns True when shown.

    Tries the S4CL ok/cancel dialog (stack base) first, then the validated
    native ``god_ui._show_ok_cancel`` path.
    """
    # Stack base: S4CL ok/cancel.
    try:
        dialog = integrations.s4cl_ok_cancel(title, body)
        if dialog is not None and integrations.s4cl_show_ok_cancel(
                dialog, _owner(sim_info), on_confirm=on_ok):
            return True
    except Exception as exc:
        log_exception("dialogs.confirm.s4cl", exc)

    try:
        from .god_ui import _show_ok_cancel
    except Exception as exc:
        log_exception("dialogs.confirm.import", exc)
        return False
    try:
        return _show_ok_cancel(sim_info, title, body, on_ok or (lambda: None))
    except Exception as exc:
        log_exception("dialogs.confirm", exc)
        return False
