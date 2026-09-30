"""
P0 UI spike for Sensewright (see ``docs/ui_panel.md`` section 6).

Probes The Sims 4's *native* dialog family in the live client so the
configuration panel (P2) can be built on confirmed APIs instead of guesses:

- ``notification`` — the validated ``UiDialogNotification`` path (chat_ui).
- ``okcancel``     — ``UiDialogOkCancel`` with an Ok/Cancel response.
- ``picker``       — ``UiObjectPicker`` rows + automatic pagination.
- ``response``     — a notification whose button runs a command (SEND_COMMAND).
- ``input``        — ``UiDialogTextInputOk`` (the numeric-input vehicle).
- ``multi``        — a picker with ``max_selectable > 1`` (the tags vehicle).

Every probe is best-effort: imports are lazy, no exception escapes, and each
result is a small diagnostics dict (also written to ``sensewright_output.log``)
with ``{kind, ok, layer, error}``. ``run_all`` runs them in order so the player
can tick each one off in-game.

``inspect``/``format_report`` only report which classes exist (no UI), so the
spike still yields information when a dialog fails to render.

Run in-game with ``sw.uitest`` (notification), ``sw.uitest all``, a single kind,
or ``sw.uitest probe`` for the class report.
"""


from collections import namedtuple

from . import i18n
from .debug_log import debug_log, log_exception, validation_log

# Wire shape of ``UiDialogResponse.response_command`` (matches the game's own
# ``ui.ui_dialog`` command/arg namedtuples; the dialog reads ``.command`` and
# each arg's ``.arg_type``/``.arg_value``).
_CommandArgument = namedtuple("CommandArgument", ("arg_type", "arg_value"))
_Command = namedtuple("Command", ("command", "arguments"))

# Probe order shown by ``sw.uitest all``.
KINDS = ("notification", "okcancel", "picker", "picker_icons", "picker_text",
         "dropdown", "labeled_icons", "info_columns", "response", "input",
         "multi", "panel", "panel_home", "pie")

# Bare ``sw.uitest`` keeps the original notification behaviour.
DEFAULT_KIND = "notification"

# Class candidates the spike cares about: (label, module, attribute).
_CANDIDATES = (
    ("ui.ui_dialog.UiDialogResponse", "ui.ui_dialog", "UiDialogResponse"),
    ("ui.ui_dialog.ButtonType", "ui.ui_dialog", "ButtonType"),
    ("ui.ui_dialog.UiDialogOkCancel", "ui.ui_dialog", "UiDialogOkCancel"),
    ("ui.ui_dialog_generic.UiDialogOkCancel", "ui.ui_dialog_generic", "UiDialogOkCancel"),
    ("ui.ui_dialog_generic.UiDialogTextInputOk", "ui.ui_dialog_generic", "UiDialogTextInputOk"),
    ("ui.ui_text_input.UiTextInput", "ui.ui_text_input", "UiTextInput"),
    ("ui.ui_dialog_picker.UiObjectPicker", "ui.ui_dialog_picker", "UiObjectPicker"),
    ("ui.ui_dialog_picker.ObjectPickerRow", "ui.ui_dialog_picker", "ObjectPickerRow"),
    ("ui.ui_dialog_picker.UiSimPicker", "ui.ui_dialog_picker", "UiSimPicker"),
    ("ui.ui_dialog_picker.SimPickerRow", "ui.ui_dialog_picker", "SimPickerRow"),
    ("ui.ui_dialog_notification.UiDialogNotification", "ui.ui_dialog_notification",
     "UiDialogNotification"),
)


# --- diagnostics plumbing ---

def _result(kind, ok, layer, error=None):
    """Build the diagnostics dict every probe returns. Never raises."""
    try:
        error_text = None if error is None else str(error)
    except Exception:
        error_text = "?"
    return {"kind": kind, "ok": bool(ok), "layer": str(layer), "error": error_text}


def format_result(result):
    """Localized one-line rendering of a probe result (used by the command)."""
    if not isinstance(result, dict):
        return ""
    return i18n.t(
        "cmd.uitest.result",
        kind=result.get("kind"),
        ok=result.get("ok"),
        layer=result.get("layer"),
        error=result.get("error") or "-",
    )


def format_report():
    """Localized one-line rendering of the class-availability report."""
    try:
        return " | ".join(inspect())
    except Exception as exc:
        log_exception("ui_probe.format_report", exc)
        return ""


def inspect():
    """Return one line per candidate class: ``<label>: yes|no|err <detail>``.

    No UI is shown; this only imports modules and checks attributes so the
    spike still produces data when a dialog cannot be created.
    """
    lines = []
    for label, module_name, attr in _CANDIDATES:
        try:
            module = __import__(module_name, fromlist=[attr])
            present = hasattr(module, attr)
        except Exception as exc:
            lines.append("{}: err {!r}".format(label, exc))
            continue
        lines.append("{}: {}".format(label, "yes" if present else "no"))
    return lines


# --- game helpers (lazy, guarded) ---

def _owner(sim_info=None):
    """Resolve the active Sim *instance* a dialog should be shown to.

    Prefers the live instance behind ``sim_info``, then the active client Sim.
    Returns ``None`` when the game services are unavailable. Never raises.
    """
    if sim_info is not None:
        try:
            getter = getattr(sim_info, "get_sim_instance", None)
            instance = getter() if callable(getter) else None
            if instance is not None:
                return instance
        except Exception as exc:
            log_exception("ui_probe._owner.instance", exc)
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
        log_exception("ui_probe._owner.client", exc)
    return None


def _raw(text):
    """Wrap a plain string in a game localized string when possible."""
    try:
        from sims4.localization import LocalizationHelperTuning  # type: ignore
        return LocalizationHelperTuning.get_raw_text(text)
    except Exception:
        return text


def _factory(text):
    """A zero-arg-ish callable returning a localized string (dialog text args)."""
    localized = _raw(text)

    def _value(*args, **kwargs):
        return localized

    return _value


def _show(dialog):
    """Show a dialog, retrying the ``on_response`` form when needed. Never raises."""
    try:
        dialog.show_dialog()
        return True
    except Exception as exc:
        log_exception("ui_probe._show", exc)
        return False


def _make_length_restriction():
    """Build the ``length_restriction`` object ``UiTextInput`` expects.

    The dialog calls ``restriction.build_msg(dialog, msg, *tokens)``; a plain
    object works, but the game's own base factories are used when importable.
    """
    def build_msg(self, dialog, msg, *additional_tokens):
        try:
            msg.max_length = 12
            msg.min_length = 0
        except Exception as exc:
            log_exception("ui_probe.length_restriction.build_msg", exc)

    try:
        from sims4.tuning.tunable import (  # type: ignore
            AutoFactoryInit, HasTunableSingletonFactory)
        bases = (HasTunableSingletonFactory, AutoFactoryInit)
    except Exception:
        bases = (object,)
    return type("SensewrightTextInputLength", bases, {"build_msg": build_msg})


def _is_resource_key(value):
    """True when ``value`` looks like a ResourceKey (``.type/.group/.instance``)."""
    if value is None:
        return False
    return all(hasattr(value, attr) for attr in ("type", "group", "instance"))


def _icon_pool(sim_info=None, limit=18):
    """Collect distinct EA icons (``ResourceKey``) for picker rows.

    Multi-source and best-effort: object definitions on the lot first (the most
    reliable), then the active Sim's mood and traits. Returns ``[]`` when no
    source yields a usable ResourceKey. Never raises.
    """
    keys = []
    seen = set()

    def _add(value):
        if not _is_resource_key(value):
            return
        try:
            signature = (value.type, value.group, value.instance)
        except Exception:
            return
        if signature in seen:
            return
        seen.add(signature)
        keys.append(value)

    try:
        import services  # type: ignore
        manager = services.object_manager()
        objects = []
        if manager is not None:
            for attr in ("values", "objects"):
                getter = getattr(manager, attr, None)
                if callable(getter):
                    try:
                        objects = list(getter())
                    except Exception:
                        objects = []
                    if objects:
                        break
        for obj in objects:
            definition = getattr(obj, "definition", None)
            if definition is not None:
                _add(getattr(definition, "icon", None))
            if len(keys) >= limit:
                return keys
    except Exception as exc:
        log_exception("ui_probe._icon_pool.objects", exc)

    if sim_info is not None:
        try:
            mood = sim_info.get_mood()
            _add(getattr(mood, "icon", None))
        except Exception as exc:
            log_exception("ui_probe._icon_pool.mood", exc)
        try:
            for trait in sim_info.get_traits():
                _add(getattr(trait, "icon", None))
                if len(keys) >= limit:
                    break
        except Exception as exc:
            log_exception("ui_probe._icon_pool.traits", exc)

    return keys


# --- probes ---

def _probe_notification(sim_info):
    """The validated notification path (delegates to ``chat_ui``)."""
    from . import chat_ui

    diag = chat_ui.notification_diagnostics(
        i18n.t("notify.app_title"), i18n.t("cmd.uitest.body"), sim_info)
    return _result("notification", diag.get("ok"), diag.get("layer"),
                   diag.get("error"))


def _probe_okcancel(sim_info):
    owner = _owner(sim_info)
    if owner is None:
        return _result("okcancel", False, "owner", "no active Sim")

    dialog_class = None
    layer = "import ui.ui_dialog_generic.UiDialogOkCancel"
    try:
        from ui.ui_dialog_generic import UiDialogOkCancel  # type: ignore
        dialog_class = UiDialogOkCancel
    except Exception:
        try:
            from ui.ui_dialog import UiDialogOkCancel  # type: ignore
            dialog_class = UiDialogOkCancel
            layer = "import ui.ui_dialog.UiDialogOkCancel"
        except Exception as exc:
            return _result("okcancel", False, layer, exc)

    try:
        dialog = dialog_class.TunableFactory().default(
            owner,
            title=_factory(i18n.t("cmd.uitest.okcancel.title")),
            text=_factory(i18n.t("cmd.uitest.okcancel.body")),
            text_ok=_factory(i18n.t("god.zeitgeist.button.ok")),
            text_cancel=_factory(i18n.t("god.zeitgeist.button.cancel")),
            is_special_dialog=False,
        )
    except Exception as exc:
        return _result("okcancel", False, "default", exc)

    if _show(dialog):
        return _result("okcancel", True, "dialog")
    return _result("okcancel", False, "show_dialog")


def _build_picker(owner, rows, title, text, multi, text_rows=False, icons=None):
    """Build a ``UiObjectPicker`` with ``rows``. Never raises.

    ``rows`` is a list of ``(label, tooltip, tag)``. ``text_rows`` asks for the
    text list skin (``ObjectPickerType.OBJECT_TEXT``) instead of the default
    object/thumbnail skin — the two are compared in the spike. ``icons`` is an
    optional list of ``ResourceKey``s cycled across the rows.
    """
    try:
        from ui.ui_dialog_picker import ObjectPickerRow, UiObjectPicker  # type: ignore
    except Exception as exc:
        raise RuntimeError("import picker: {!r}".format(exc))

    picker_type = None
    if text_rows:
        try:
            from ui.ui_dialog_picker import ObjectPickerType  # type: ignore
            picker_type = getattr(ObjectPickerType, "OBJECT_TEXT", None)
        except Exception as exc:
            log_exception("ui_probe._build_picker.picker_type", exc)

    candidates = []
    if picker_type is not None:
        candidates.append({"owner": owner, "resolver": None, "picker_type": picker_type})
    candidates.append({"owner": owner, "resolver": None})
    candidates.append({"owner": owner})

    picker = None
    errors = []
    for factory_kwargs in candidates:
        try:
            picker = UiObjectPicker.TunableFactory().default(**factory_kwargs)
            break
        except Exception as exc:
            errors.append(repr(exc))
    if picker is None:
        raise RuntimeError("default failed: " + "; ".join(errors))

    picker.title = _factory(title)
    picker.text = _factory(text)
    # Keep rows compact: no filter dropdown, no description line (long text
    # overflows) — the explanation goes in the row tooltip instead.
    for attr, value in (("use_dropdown_filter", False),
                        ("hide_row_description", True),
                        ("is_sortable", False),
                        ("bubble_up_selected", False)):
        try:
            setattr(picker, attr, value)
        except Exception:
            pass
    if multi:
        picker.max_selectable = 3
        picker.min_selectable = 1
    else:
        picker.max_selectable = 1
        picker.min_selectable = 1

    for index, (label, tooltip, tag) in enumerate(rows):
        # Row ``name``/``row_description`` are used as-is (LocalizedStrings),
        # but ``row_tooltip`` is *called* by the row (CALL_METHOD) so it must be
        # a factory. ``icon`` must be a ResourceKey (.type/.group/.instance).
        localized = _raw(label)
        icon = icons[index % len(icons)] if icons else None
        picker.add_row(ObjectPickerRow(
            name=localized,
            row_description=localized,
            row_tooltip=_factory(tooltip) if tooltip else None,
            tag=str(tag),
            icon=icon,
        ))
    return picker


def _picker_callback(kind):
    """A picker response callback that logs the chosen tags. Never raises."""
    def _on_response(dialog):
        try:
            tags = []
            getter = getattr(dialog, "get_result_tags", None)
            if callable(getter):
                tags = list(getter())
            validation_log("uitest {}: picked {}".format(kind, tags))
        except Exception as exc:
            log_exception("ui_probe._picker_callback", exc)

    return _on_response


def _setting_rows():
    """A realistic settings list for the picker spike: ``(label, tooltip, tag)``.

    The label stays short (long labels overflow); the explanation goes in the
    hover tooltip.
    """
    keys = (
        "autonomy_degree", "chaos_degree", "mood_influence",
        "intervention_frequency", "intensity", "evolution_speed",
        "agent_seats", "impulse_frequency", "reasoning_effort",
        "layer_memory", "layer_cognition", "layer_social",
        "power_spawn_npc", "power_apply_trait", "power_force_social",
        "power_gossip", "power_relationship_shift", "power_extreme_events",
    )
    return [
        (i18n.t("god.control.{}.label".format(key)),
         i18n.t("god.control.{}.desc".format(key)),
         index)
        for index, key in enumerate(keys)
    ]


def _show_picker(kind, owner, text_rows=False, icons=None):
    """Build + show a picker variant. Returns a diagnostics dict."""
    title = i18n.t("cmd.uitest.{}.title".format(kind))
    body = i18n.t("cmd.uitest.{}.body".format(kind))
    try:
        picker = _build_picker(owner, _setting_rows(), title, body,
                               multi=False, text_rows=text_rows, icons=icons)
    except Exception as exc:
        return _result(kind, False, "build", exc)
    try:
        picker.show_dialog(on_response=_picker_callback(kind))
        return _result(kind, True, "dialog")
    except Exception as exc:
        log_exception("ui_probe._show_picker.show", exc)
        return _result(kind, False, "show_dialog", exc)


def _probe_picker(sim_info):
    owner = _owner(sim_info)
    if owner is None:
        return _result("picker", False, "owner", "no active Sim")
    return _show_picker("picker", owner)


def _probe_picker_icons(sim_info):
    """Same list with real EA icons (from object definitions / mood / traits)."""
    owner = _owner(sim_info)
    if owner is None:
        return _result("picker_icons", False, "owner", "no active Sim")
    icons = _icon_pool(sim_info)
    if not icons:
        return _result("picker_icons", False, "no_icons",
                       "no EA icon resource key found")
    debug_log("[uitest] picker_icons: {} icon(s)".format(len(icons)))
    return _show_picker("picker_icons", owner, icons=icons)


def _probe_picker_text(sim_info):
    """Same rows via the plain-text list skin (``ObjectPickerType.OBJECT_TEXT``)."""
    owner = _owner(sim_info)
    if owner is None:
        return _result("picker_text", False, "owner", "no active Sim")
    return _show_picker("picker_text", owner, text_rows=True)


def _build_dropdown(owner, rows, title, text):
    """Build a ``UiDropdownPicker`` with ``rows`` as options. Never raises."""
    from ui.ui_dialog_picker import ObjectPickerRow, UiDropdownPicker  # type: ignore

    picker = None
    errors = []
    for factory_kwargs in ({"owner": owner, "resolver": None}, {"owner": owner}):
        try:
            picker = UiDropdownPicker.TunableFactory().default(**factory_kwargs)
            break
        except Exception as exc:
            errors.append(repr(exc))
    if picker is None:
        raise RuntimeError("default failed: " + "; ".join(errors))

    picker.title = _factory(title)
    picker.text = _factory(text)
    try:
        picker.default_item_text = _factory(i18n.t("cmd.uitest.dropdown.placeholder"))
    except Exception:
        pass
    for label, tooltip, tag in rows:
        picker.add_row(ObjectPickerRow(name=_raw(label), tag=str(tag)))
    return picker


def _probe_dropdown(sim_info):
    """A native dropdown (`UiDropdownPicker`) for single-choice settings."""
    owner = _owner(sim_info)
    if owner is None:
        return _result("dropdown", False, "owner", "no active Sim")
    try:
        picker = _build_dropdown(owner, _setting_rows(),
                                 i18n.t("cmd.uitest.dropdown.title"),
                                 i18n.t("cmd.uitest.dropdown.body"))
    except Exception as exc:
        return _result("dropdown", False, "build", exc)
    try:
        picker.show_dialog(on_response=_picker_callback("dropdown"))
        return _result("dropdown", True, "dialog")
    except Exception as exc:
        log_exception("ui_probe._probe_dropdown.show", exc)
        return _result("dropdown", False, "show_dialog", exc)


class _LabeledIcon(object):
    """A minimal ``labeled_icons`` entry (``.icon`` + ``.label``)."""

    __slots__ = ("icon", "label")

    def __init__(self, icon, label):
        self.icon = icon
        self.label = label


def _probe_labeled_icons(sim_info):
    """An icon-grid dialog (`UiDialogLabeledIcons`) — the panel-home candidate."""
    owner = _owner(sim_info)
    if owner is None:
        return _result("labeled_icons", False, "owner", "no active Sim")

    try:
        from ui.ui_dialog_labeled_icons import UiDialogLabeledIcons  # type: ignore
    except Exception as exc:
        return _result("labeled_icons", False, "import", exc)

    icons = _icon_pool(sim_info)
    entries = []
    for index, (label, tooltip, tag) in enumerate(_setting_rows()):
        entry = _LabeledIcon(
            icons[index % len(icons)] if icons else None,
            _factory(label),
        )
        entries.append(entry)

    try:
        dialog = UiDialogLabeledIcons.TunableFactory().default(
            owner,
            title=_factory(i18n.t("cmd.uitest.labeled_icons.title")),
            text=_factory(i18n.t("cmd.uitest.labeled_icons.body")),
            labeled_icons=entries,
        )
    except Exception as exc:
        return _result("labeled_icons", False, "default", exc)
    if _show(dialog):
        return _result("labeled_icons", True, "dialog")
    return _result("labeled_icons", False, "show_dialog")


def _probe_info_columns(sim_info):
    """A read-only column table (`UiDialogInfoInColumns`) for status pages."""
    owner = _owner(sim_info)
    if owner is None:
        return _result("info_columns", False, "owner", "no active Sim")

    try:
        from ui.ui_dialog_info_columns import UiDialogInfoInColumns  # type: ignore
    except Exception as exc:
        return _result("info_columns", False, "import", exc)

    headers = [
        _factory(i18n.t("cmd.uitest.info_columns.h1")),
        _factory(i18n.t("cmd.uitest.info_columns.h2")),
    ]
    try:
        dialog = UiDialogInfoInColumns.TunableFactory().default(
            owner,
            title=_factory(i18n.t("cmd.uitest.info_columns.title")),
            column_headers=headers,
        )
    except Exception as exc:
        return _result("info_columns", False, "default", exc)
    if _show(dialog):
        return _result("info_columns", True, "dialog")
    return _result("info_columns", False, "show_dialog")


def _probe_pie(sim_info):
    """Introspect the pie-menu tuning: did our interactions load? valid category?"""
    try:
        import services  # type: ignore
        from sims4.resources import Types  # type: ignore
    except Exception as exc:
        return _result("pie", False, "import", exc)

    report = []

    try:
        manager = services.get_instance_manager(Types.PIE_MENU_CATEGORY)
        classes = getattr(manager, "_tuned_classes", None) or {}
        entries = []
        for tuning in classes.values():
            guid = getattr(tuning, "guid64", None)
            name = getattr(tuning, "__name__", "?")
            if guid is not None:
                entries.append("{}:{}".format(int(guid), name))
        ids = set(int(entry.split(":", 1)[0]) for entry in entries)
        report.append("pie_categories={} has_129388={}".format(
            len(ids), 129388 in ids))
        debug_log("[uitest] pie categories: " + " ".join(sorted(entries)))
    except Exception as exc:
        log_exception("ui_probe._probe_pie.categories", exc)
        report.append("categories_err={!r}".format(exc))

    try:
        manager = services.get_instance_manager(Types.INTERACTION)
        ours = (0xEAA4100000000001, 0xEAA4100000000002,
                0xEAA4100000000003, 0xEAA4100000000004)
        present = 0
        for guid in ours:
            try:
                if manager.get(guid) is not None:
                    present += 1
            except Exception:
                pass
        report.append("our_interactions={}/{}".format(present, len(ours)))
    except Exception as exc:
        log_exception("ui_probe._probe_pie.interactions", exc)
        report.append("interactions_err={!r}".format(exc))

    text = " | ".join(report)
    validation_log("pie: " + text)
    debug_log("[uitest] pie: " + text)
    return _result("pie", True, "report", text)


def _probe_response(sim_info):
    owner = _owner(sim_info)
    if owner is None:
        return _result("response", False, "owner", "no active Sim")

    try:
        from ui.ui_dialog import ButtonType, CommandArgType, UiDialogResponse  # type: ignore
        from ui.ui_dialog_notification import UiDialogNotification  # type: ignore
    except Exception as exc:
        return _result("response", False, "import", exc)

    try:
        # A button that runs ``sw.uitest clicked`` proves SEND_COMMAND end to end.
        arg = _CommandArgument(CommandArgType.ARG_TYPE_STRING, "clicked")
        command = _Command("sw.uitest", (arg,))
        responses = (
            UiDialogResponse(
                dialog_response_id=ButtonType.DIALOG_RESPONSE_OK,
                text=_factory(i18n.t("cmd.uitest.response.ok")),
                ui_request=UiDialogResponse.UiDialogUiRequest.SEND_COMMAND,
                response_command=command,
            ),
            UiDialogResponse(
                dialog_response_id=ButtonType.DIALOG_RESPONSE_CANCEL,
                text=_factory(i18n.t("cmd.uitest.response.cancel")),
                ui_request=UiDialogResponse.UiDialogUiRequest.NO_REQUEST,
            ),
        )
    except Exception as exc:
        return _result("response", False, "build_response", exc)

    dialog = None
    errors = []
    for factory_kwargs in (
        {"ui_responses": responses},
        {"ui_responses": responses, "information_level":
            getattr(UiDialogNotification, "UiDialogNotificationLevel", None)},
        {},
    ):
        try:
            dialog = UiDialogNotification.TunableFactory().default(
                owner,
                title=_factory(i18n.t("cmd.uitest.response.title")),
                text=_factory(i18n.t("cmd.uitest.response.body")),
                **factory_kwargs
            )
            break
        except Exception as exc:
            errors.append(repr(exc))
    if dialog is None:
        return _result("response", False, "default", "; ".join(errors))

    if _show(dialog):
        return _result("response", True, "dialog")
    return _result("response", False, "show_dialog")


def _probe_input(sim_info):
    owner = _owner(sim_info)
    if owner is None:
        return _result("input", False, "owner", "no active Sim")

    try:
        from sims4.collections import AttributeDict  # type: ignore
        from ui.ui_dialog_generic import UiDialogTextInputOk  # type: ignore
        from ui.ui_text_input import UiTextInput  # type: ignore
    except Exception as exc:
        return _result("input", False, "import", exc)

    restricted = None
    try:
        from sims4.localization import _create_localized_string  # type: ignore
        # ``restricted_characters`` is called by the dialog, so it must be a
        # factory, not a bare LocalizedString.
        restricted = (lambda *args, **kwargs:
                      _create_localized_string(0x8FE40C44))  # numeric set
    except Exception as exc:
        log_exception("ui_probe._probe_input.restricted", exc)

    try:
        text_input = UiTextInput(sort_order=0, restricted_characters=restricted, height=0)
        text_input.default_text = _factory("0.5")
        text_input.title = _factory(i18n.t("cmd.uitest.input.body"))
        text_input.initial_value = _factory("0.5")
        text_input.check_profanity = False
        # The dialog reads ``length_restriction`` (the documented min/max path);
        # ``min_length``/``max_length`` are read-only properties on this patch.
        text_input.length_restriction = _make_length_restriction()()
        for attr, value in (("max_length", 6), ("min_value", 0.0), ("max_value", 1.0)):
            try:
                setattr(text_input, attr, value)
            except Exception:
                pass
        inputs = AttributeDict({"primary": text_input})
    except Exception as exc:
        return _result("input", False, "build_input", exc)

    try:
        dialog = UiDialogTextInputOk.TunableFactory().default(
            owner,
            title=_factory(i18n.t("cmd.uitest.input.title")),
            text=_factory(i18n.t("cmd.uitest.input.body")),
            text_inputs=inputs,
            text_ok=_factory(i18n.t("god.zeitgeist.button.ok")),
            is_special_dialog=False,
        )
    except Exception as exc:
        return _result("input", False, "default", exc)

    if _show(dialog):
        return _result("input", True, "dialog")
    return _result("input", False, "show_dialog")


def _probe_multi(sim_info):
    owner = _owner(sim_info)
    if owner is None:
        return _result("multi", False, "owner", "no active Sim")

    try:
        from .god_ui import MOOD_TAGS
        tags = list(MOOD_TAGS)
    except Exception:
        tags = ["novela", "sitcom", "drama", "caos", "terror", "romance", "filme_adolescente"]
    rows = [(i18n.t("god.tag.{}".format(tag)), "", tag) for tag in tags]

    try:
        picker = _build_picker(owner, rows,
                               i18n.t("cmd.uitest.multi.title"),
                               i18n.t("cmd.uitest.multi.body"), multi=True)
    except Exception as exc:
        return _result("multi", False, "build", exc)

    try:
        picker.show_dialog(on_response=_picker_callback("multi"))
        return _result("multi", True, "dialog")
    except Exception as exc:
        log_exception("ui_probe._probe_multi.show", exc)
        return _result("multi", False, "show_dialog", exc)


# --- realistic panel mock (P2 preview) ---

# Slider steps for a 0..1 dial. The real panel reads the ControlSpec step; the
# mock uses a fixed set so the stepped-choices look can be judged.
_PANEL_STEPS = (0.0, 0.25, 0.5, 0.75, 1.0)

# A miniature of the real ControlSpec inventory (docs/ui_panel.md §1.1/§1.2).
# P2 fetches this from the sidecar; the mock is self-contained (offline).
_PANEL_SECTIONS = (
    {
        "key": "god",
        "title": "cmd.panel.section.god.title",
        "body": "cmd.panel.section.god.body",
        "settings": (
            {"key": "autonomy_degree", "kind": "slider", "value": 0.5},
            {"key": "chaos_degree", "kind": "slider", "value": 0.3},
            {"key": "mood_influence", "kind": "slider", "value": 0.5},
            {"key": "evolution_speed", "kind": "select", "value": "normal",
             "options": ("slow", "normal", "fast"),
             "option_prefix": "god.speed."},
            {"key": "mood_tags", "kind": "tags", "value": []},
        ),
    },
    {
        "key": "agents",
        "title": "cmd.panel.section.agents.title",
        "body": "cmd.panel.section.agents.body",
        "settings": (
            {"key": "agent_seats", "kind": "number", "value": 12},
            {"key": "impulse_frequency", "kind": "slider", "value": 0.2},
            {"key": "reasoning_effort", "kind": "select", "value": "none",
             "options": ("none", "minimal", "low", "medium", "high"),
             "option_prefix": "god.reasoning."},
            {"key": "reactions_enabled", "kind": "toggle", "value": True},
            {"key": "layer_memory", "kind": "toggle", "value": True},
            {"key": "layer_social", "kind": "toggle", "value": True},
        ),
    },
    {
        "key": "powers",
        "title": "cmd.panel.section.powers.title",
        "body": "cmd.panel.section.powers.body",
        "settings": (
            {"key": "power_spawn_npc", "kind": "toggle", "value": True},
            {"key": "power_apply_trait", "kind": "toggle", "value": True},
            {"key": "power_force_social", "kind": "toggle", "value": True},
            {"key": "power_gossip", "kind": "toggle", "value": True},
            {"key": "power_relationship_shift", "kind": "toggle", "value": True},
            {"key": "power_extreme_events", "kind": "toggle", "value": False},
        ),
    },
)


def _apply(setting_key, value):
    """Record a mocked panel change. The real P2 applies + persists via `sw.set`."""
    try:
        validation_log("panel: {}={}".format(setting_key, value))
        debug_log("[panel] set {}={}".format(setting_key, value))
    except Exception:
        pass


def _first(values):
    """First item of a sequence, or ``None``."""
    if not values:
        return None
    try:
        return values[0]
    except Exception:
        return None


def _picked(dialog):
    """Tags chosen in a picker response (list of strings). Never raises."""
    tags = []
    try:
        getter = getattr(dialog, "get_result_tags", None)
        if callable(getter):
            tags = [str(tag) for tag in getter()]
    except Exception as exc:
        log_exception("ui_probe._picked", exc)
    return tags


def _control_label(setting):
    key = setting.get("label_key") or "god.control.{}.label".format(setting.get("key"))
    return i18n.t(key)


def _control_desc(setting):
    key = setting.get("description_key") or "god.control.{}.desc".format(setting.get("key"))
    return i18n.t(key)


def _format_value(value):
    """Compact rendering of a setting value for a picker row."""
    if isinstance(value, bool):
        return i18n.t("cmd.panel.value.on") if value else i18n.t("cmd.panel.value.off")
    if isinstance(value, float):
        if not value:
            return "0"
        return ("%.2f" % value).rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _show_number_input(owner, setting):
    """The numeric-input widget (best for bounded integers)."""
    from sims4.collections import AttributeDict  # type: ignore
    from ui.ui_dialog_generic import UiDialogTextInputOk  # type: ignore
    from ui.ui_text_input import UiTextInput  # type: ignore

    initial = str(setting.get("value", ""))
    text_input = UiTextInput(sort_order=0, restricted_characters=None, height=0)
    text_input.default_text = _factory(initial)
    text_input.title = _factory(_control_label(setting))
    text_input.initial_value = _factory(initial)
    text_input.check_profanity = False
    text_input.length_restriction = _make_length_restriction()()
    inputs = AttributeDict({"primary": text_input})

    dialog = UiDialogTextInputOk.TunableFactory().default(
        owner,
        title=_factory(_control_label(setting)),
        text=_factory(_control_desc(setting)),
        text_inputs=inputs,
        text_ok=_factory(i18n.t("god.zeitgeist.button.ok")),
        is_special_dialog=False,
    )

    def _on_done(response):
        value = None
        try:
            value = getattr(response.text_inputs["primary"], "value", None)
        except Exception as exc:
            log_exception("ui_probe._show_number_input.on_done", exc)
        _apply(setting.get("key"), value)

    for name in ("add_callback", "add_listener"):
        callback = getattr(dialog, name, None)
        if callable(callback):
            try:
                callback(_on_done)
                break
            except Exception:
                pass
    dialog.show_dialog()


def _open_control(owner, setting):
    """Open the best native widget for a setting's ``kind``. Never raises."""
    kind = setting.get("kind")
    key = setting.get("key")
    label = _control_label(setting)
    desc = _control_desc(setting)
    try:
        if kind == "toggle":
            rows = [(i18n.t("cmd.panel.value.on"), "", "on"),
                    (i18n.t("cmd.panel.value.off"), "", "off")]
            picker = _build_picker(owner, rows, label, desc, multi=False)
            picker.show_dialog(
                on_response=lambda d: _apply(key, _first(_picked(d))))
        elif kind == "slider":
            rows = [(str(step), "", str(step)) for step in _PANEL_STEPS]
            picker = _build_picker(owner, rows, label, desc, multi=False)
            picker.show_dialog(
                on_response=lambda d: _apply(key, _first(_picked(d))))
        elif kind == "select":
            prefix = setting.get("option_prefix", "")
            rows = [(i18n.t("{}{}".format(prefix, option)), "", option)
                    for option in setting.get("options", ())]
            picker = _build_dropdown(owner, rows, label, desc)
            picker.show_dialog(
                on_response=lambda d: _apply(key, _first(_picked(d))))
        elif kind == "number":
            _show_number_input(owner, setting)
        elif kind == "tags":
            from .god_ui import MOOD_TAGS
            rows = [(i18n.t("god.tag.{}".format(tag)), "", tag)
                    for tag in MOOD_TAGS]
            picker = _build_picker(owner, rows, label, desc, multi=True)
            picker.show_dialog(
                on_response=lambda d: _apply(key, ",".join(_picked(d))))
    except Exception as exc:
        log_exception("ui_probe._open_control." + str(kind), exc)


def _open_section(owner, section):
    """Open a section page: one row per setting, with its current value."""
    icons = _icon_pool()
    rows = []
    by_key = {}
    for setting in section.get("settings", ()):
        label = "{}: {}".format(_control_label(setting),
                                _format_value(setting.get("value")))
        rows.append((label, _control_desc(setting), setting.get("key")))
        by_key[setting.get("key")] = setting
    try:
        picker = _build_picker(owner, rows, i18n.t(section["title"]),
                               i18n.t(section["body"]), multi=False,
                               icons=icons or None)
    except Exception as exc:
        log_exception("ui_probe._open_section.build", exc)
        return

    def _on_choice(dialog):
        setting = by_key.get(_first(_picked(dialog)))
        if setting is not None:
            _open_control(owner, setting)

    picker.show_dialog(on_response=_on_choice)


def _probe_panel(sim_info):
    """A navigable mock of the P2 panel: sections -> settings -> best widget."""
    owner = _owner(sim_info)
    if owner is None:
        return _result("panel", False, "owner", "no active Sim")

    icons = _icon_pool(sim_info)
    rows = [(i18n.t(section["title"]), i18n.t(section["body"]), section["key"])
            for section in _PANEL_SECTIONS]
    try:
        picker = _build_picker(owner, rows, i18n.t("cmd.panel.title"),
                               i18n.t("cmd.panel.body"), multi=False,
                               icons=icons or None)
    except Exception as exc:
        return _result("panel", False, "build", exc)

    by_key = {section["key"]: section for section in _PANEL_SECTIONS}

    def _on_section(dialog):
        section = by_key.get(_first(_picked(dialog)))
        if section is not None:
            _open_section(owner, section)

    try:
        picker.show_dialog(on_response=_on_section)
        return _result("panel", True, "dialog")
    except Exception as exc:
        log_exception("ui_probe._probe_panel.show", exc)
        return _result("panel", False, "show_dialog", exc)


def _probe_panel_home(sim_info):
    """Preview the panel home as a labeled-icons dialog (sections only)."""
    owner = _owner(sim_info)
    if owner is None:
        return _result("panel_home", False, "owner", "no active Sim")

    try:
        from ui.ui_dialog_labeled_icons import UiDialogLabeledIcons  # type: ignore
    except Exception as exc:
        return _result("panel_home", False, "import", exc)

    icons = _icon_pool(sim_info)
    entries = []
    for index, section in enumerate(_PANEL_SECTIONS):
        entries.append(_LabeledIcon(
            icons[index % len(icons)] if icons else None,
            _factory(i18n.t(section["title"])),
        ))
    try:
        dialog = UiDialogLabeledIcons.TunableFactory().default(
            owner,
            title=_factory(i18n.t("cmd.panel.title")),
            text=_factory(i18n.t("cmd.panel.home_body")),
            labeled_icons=entries,
        )
    except Exception as exc:
        return _result("panel_home", False, "default", exc)
    if _show(dialog):
        return _result("panel_home", True, "dialog")
    return _result("panel_home", False, "show_dialog")


_PROBES = {
    "notification": _probe_notification,
    "okcancel": _probe_okcancel,
    "picker": _probe_picker,
    "picker_icons": _probe_picker_icons,
    "picker_text": _probe_picker_text,
    "dropdown": _probe_dropdown,
    "labeled_icons": _probe_labeled_icons,
    "info_columns": _probe_info_columns,
    "response": _probe_response,
    "input": _probe_input,
    "multi": _probe_multi,
    "panel": _probe_panel,
    "panel_home": _probe_panel_home,
    "pie": _probe_pie,
}


# --- public runner ---

def run(kind, sim_info=None):
    """Run one probe. Returns a diagnostics dict, or ``None`` for unknown kinds.

    Never raises: a failure is captured as ``{"ok": False, ...}``.
    """
    probe = _PROBES.get(kind)
    if probe is None:
        return None
    try:
        result = probe(sim_info)
    except Exception as exc:
        log_exception("ui_probe.run." + str(kind), exc)
        result = _result(kind, False, "run", exc)
    validation_log("uitest {}: ok={} layer={} err={}".format(
        result.get("kind"), result.get("ok"), result.get("layer"),
        result.get("error") or "-"))
    debug_log("[uitest] {}: ok={} layer={} err={}".format(
        result.get("kind"), result.get("ok"), result.get("layer"),
        result.get("error") or "-"))
    return result


def run_all(sim_info=None):
    """Run every probe in ``KINDS`` order. Never raises."""
    results = []
    for kind in KINDS:
        result = run(kind, sim_info)
        if result is not None:
            results.append(result)
    return results
