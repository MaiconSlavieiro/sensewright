"""
God agent UI for Sensewright.

Renders the vanilla TS4 dialogs used to configure the neighborhood zeitgeist
and to collect household background hints. Every game import is lazy and
guarded, so the module imports (and its helpers run) outside the game. Public
functions are best-effort: they never block and never raise.
"""


from typing import Any, Dict, Optional

from . import http_client, i18n, sim_context
from .debug_log import (
    debug_log,
    log_exception,
    safe_call as _safe_call,
    safe_getattr as _safe_getattr,
)


# Mood tags mirrored from the sidecar wire contract (schemas.MOOD_TAGS).
MOOD_TAGS = (
    "novela",
    "sitcom",
    "drama",
    "caos",
    "terror",
    "romance",
    "filme_adolescente",
)

# God intervention presets mirrored from the sidecar deck (interventions.PRESETS).
GOD_PRESETS = (
    "novela",
    "sitcom",
    "drama",
    "caos",
    "terror",
)

# Module-level guard so onboarding is offered at most once per session.
_onboarding_shown = False


def _current_lang() -> str:
    """Current UI language for outgoing calls."""
    try:
        lang = i18n.current_locale()
        if lang:
            return lang
    except Exception as exc:
        log_exception("god_ui._current_lang", exc)
    return "en"


def reset_onboarding_guard() -> None:
    """Allow onboarding to be offered again (mainly for tests)."""
    global _onboarding_shown
    _onboarding_shown = False


# --- pure helpers (testable without the game) ---

def build_onboarding_request(zeitgeist: Optional[Dict[str, Any]],
                             suggested_text: str = "") -> Dict[str, Any]:
    """
    Build the onboarding dialog content and default set_zeitgeist values.

    Returns a dict with localized strings plus ``mood_tags``, ``free_text`` and
    ``mood_influence``. Pure: never touches the game or the network.
    """
    data = zeitgeist if isinstance(zeitgeist, dict) else {}

    raw_tags = data.get("mood_tags")
    if not isinstance(raw_tags, (list, tuple)):
        raw_tags = []
    mood_tags = [tag for tag in raw_tags if tag in MOOD_TAGS]

    stored_text = data.get("free_text")
    if not isinstance(stored_text, str):
        stored_text = ""
    free_text = suggested_text if suggested_text else stored_text

    try:
        influence = float(data.get("mood_influence", 0.5))
    except (TypeError, ValueError):
        influence = 0.5
    influence = max(0.0, min(1.0, influence))

    return {
        "title": i18n.t("god.zeitgeist.title"),
        "body": i18n.t("god.zeitgeist.body"),
        "placeholder": i18n.t("god.zeitgeist.prompt_placeholder"),
        "ok": i18n.t("god.zeitgeist.button.ok"),
        "cancel": i18n.t("god.zeitgeist.button.cancel"),
        "mood_tags": mood_tags,
        "free_text": free_text,
        "mood_influence": influence,
    }


def _format_value(value: Any) -> str:
    """Render a control value compactly."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float):
        if not value:
            return "0"
        return ("%.2f" % value).rstrip("0").rstrip(".")
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item) for item in value)
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _control_label(spec: Dict[str, Any]) -> str:
    """Localized label for a control spec (falls back to its key)."""
    label_key = spec.get("label_key")
    if not label_key:
        key = spec.get("key") or ""
        label_key = "god.control.{}.label".format(key) if key else ""
    if label_key:
        return i18n.t(label_key)
    return str(spec.get("key") or "")


def _control_desc(spec: Dict[str, Any]) -> str:
    """Localized description for a control spec (may be empty)."""
    desc_key = spec.get("description_key")
    if not desc_key:
        key = spec.get("key") or ""
        desc_key = "god.control.{}.desc".format(key) if key else ""
    if desc_key:
        return i18n.t(desc_key)
    return ""


def _control_options(spec: Dict[str, Any]) -> str:
    """Render the option labels of a select/tags control."""
    options = spec.get("options")
    if not isinstance(options, (list, tuple)) or not options:
        return ""
    names = []
    for option in options:
        if isinstance(option, dict):
            # A literal label (e.g. a language name from the sidecar manifest)
            # wins over a label_key, so new languages need no per-language keys.
            label = option.get("label")
            if isinstance(label, str) and label:
                names.append(label)
                continue
            label_key = option.get("label_key")
            if label_key:
                names.append(i18n.t(label_key))
            else:
                names.append(str(option.get("value", "")))
        else:
            names.append(str(option))
    return ", ".join(name for name in names if name)


def format_controls(controls: Any, values: Optional[Dict[str, Any]] = None) -> str:
    """
    Render a human-readable summary of ``GET /v1/god/controls`` controls.

    ``controls`` is the list of control specs; ``values`` is the optional
    current-value map. Malformed input is skipped rather than raising.
    """
    if not isinstance(controls, (list, tuple)) or not controls:
        return ""
    current = values if isinstance(values, dict) else {}

    lines = []
    for spec in controls:
        if not isinstance(spec, dict):
            continue
        key = spec.get("key") or ""
        label = _control_label(spec)
        desc = _control_desc(spec)
        kind = spec.get("kind") or ""

        line = "- {} [{}]: {}".format(label, kind, desc)
        options = _control_options(spec)
        if options:
            line += " ({})".format(options)
        if key:
            value = current.get(key, spec.get("default"))
            line += " = {}".format(_format_value(value))
        lines.append(line)

    return "\n".join(lines)


def format_roster(roster: Any) -> str:
    """Render a human-readable agent roster (``GET /v1/agency/seats``).

    Shows one line per seated Sim with its tier, player flag and impulse
    frequency dial. Malformed input is skipped rather than raising.
    """
    if not isinstance(roster, dict):
        return ""
    agents = roster.get("agents")
    if not isinstance(agents, (list, tuple)) or not agents:
        return ""

    lines = []
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        sim_id = agent.get("sim_id", "?")
        tier = agent.get("tier") or "visitor"
        player = agent.get("is_player")
        freq = agent.get("impulse_frequency")
        line = "- {} [{}]".format(sim_id, tier)
        if player:
            line += " *"
        line += " freq={}".format(_format_value(freq) if freq is not None else "default")
        lines.append(line)
    return "\n".join(lines)

def _output_hint(message: str) -> bool:
    """Fall back to the cheat console / debug log when no dialog is available."""
    try:
        from .chat_ui import output_to_console
        if output_to_console(message):
            return True
    except Exception as exc:
        log_exception("god_ui._output_hint.console", exc)
    try:
        debug_log("[Sensewright] {}".format(message))
        return True
    except Exception as exc:
        log_exception("god_ui._output_hint.log", exc)
        return False


def _try_import_dialog_class():
    """Try to import a vanilla ok/cancel dialog class."""
    for module_name, class_name in (
        ("ui.ui_dialog", "UiDialogOkCancel"),
        ("ui.ui_dialog_ok_cancel", "UiDialogOkCancel"),
        ("sims4.ui", "UiDialogOkCancel"),
    ):
        try:
            module = __import__(module_name, fromlist=[class_name])
            dialog_class = getattr(module, class_name, None)
            if dialog_class is not None:
                return dialog_class
        except Exception as exc:
            log_exception("god_ui._try_import_dialog_class", exc)
            continue
    return None


def _localize(text: str) -> Any:
    """Wrap a plain string in a game localized string when possible."""
    try:
        from sims4.localization import LocalizationHelperTuning  # type: ignore
    except Exception:
        return text
    for method_name in (
        "get_localized_string",
        "get_localized_string_from_string",
        "to_localized_string",
    ):
        method = getattr(LocalizationHelperTuning, method_name, None)
        if not callable(method):
            continue
        try:
            return method(text)
        except Exception as exc:
            log_exception("god_ui._localize", exc)
            continue
    return text


def _show_ok_cancel(sim_info, title: str, text: str, on_ok) -> bool:
    """
    Best-effort vanilla ok/cancel dialog. Returns True when a dialog was shown,
    False when the UI is unavailable (caller should fall back to console).
    """
    dialog_class = _try_import_dialog_class()
    if dialog_class is None:
        return False
    try:
        localized_title = _localize(title)
        localized_text = _localize(text)
        factory = dialog_class.TunableFactory()
        if sim_info is not None:
            dialog = factory.default(sim_info, title=localized_title, text=localized_text)
        else:
            dialog = factory.default(title=localized_title, text=localized_text)

        for callback_name in ("add_callback", "set_callback"):
            callback = getattr(dialog, callback_name, None)
            if callable(callback):
                try:
                    callback(on_ok)
                except Exception:
                    pass
                break

        dialog.show_dialog()
        return True
    except Exception as exc:
        log_exception("god_ui._show_ok_cancel", exc)
        return False


# --- sim reference ---

def _sim_ref(sim_info, household_id: Optional[int] = None) -> Dict[str, Any]:
    """Build a wire SimRef from a SimInfo (or an already-built dict)."""
    ref = {
        "player_id": "local",
        "save_id": "",
        "sim_id": 0,
        "household_id": household_id,
    }

    if isinstance(sim_info, dict):
        ref["player_id"] = sim_info.get("player_id", "local")
        ref["save_id"] = sim_info.get("save_id", "") or ""
        try:
            ref["sim_id"] = int(sim_info.get("sim_id", 0) or 0)
        except (TypeError, ValueError):
            ref["sim_id"] = 0
        if household_id is None:
            ref["household_id"] = sim_info.get("household_id")
        return ref

    try:
        ref["sim_id"] = int(_safe_getattr(sim_info, "id", 0) or 0)
    except (TypeError, ValueError):
        ref["sim_id"] = 0

    try:
        ref["save_id"] = sim_context._get_save_id() or ""
    except Exception:
        ref["save_id"] = ""
    if not isinstance(ref["save_id"], str):
        ref["save_id"] = str(ref["save_id"])

    if household_id is None and sim_info is not None:
        household = _safe_getattr(sim_info, "household", None)
        if household is not None:
            ref["household_id"] = _safe_getattr(household, "id", None)

    return ref


# --- public flow ---

def maybe_show_zeitgeist_onboarding(sim_info=None) -> Any:
    """
    Query the current zeitgeist and offer onboarding when it is unconfigured.

    Returns "dialog" when a vanilla dialog was shown, "console" when it fell
    back to a console hint, False when nothing was needed/possible. Never
    raises and never blocks.
    """
    global _onboarding_shown
    if _onboarding_shown:
        return False
    _onboarding_shown = True

    try:
        sim_ref = _sim_ref(sim_info)
        save_id = sim_ref.get("save_id", "")
        player_id = sim_ref.get("player_id", "local")

        data = None
        try:
            data = http_client.get_zeitgeist(save_id, player_id)
        except Exception as exc:
            log_exception(
                "god_ui.maybe_show_zeitgeist_onboarding.get_zeitgeist", exc)
            data = None

        zeitgeist = {}
        if isinstance(data, dict):
            candidate = data.get("zeitgeist")
            if isinstance(candidate, dict):
                zeitgeist = candidate

        if zeitgeist.get("configured"):
            return False

        request = build_onboarding_request(zeitgeist, "")

        def _apply():
            try:
                http_client.set_zeitgeist(
                    sim_ref,
                    request.get("mood_tags", []),
                    request.get("free_text", ""),
                    request.get("mood_influence", 0.5),
                    _current_lang(),
                )
            except Exception as exc:
                log_exception(
                    "god_ui.maybe_show_zeitgeist_onboarding.apply", exc)

        if _show_ok_cancel(sim_info, request["title"], request["body"], _apply):
            return "dialog"

        _output_hint(
            i18n.t(
                "god.zeitgeist.hint",
                title=request["title"],
                body=request["body"],
                placeholder=request["placeholder"],
                command="sw.zeitgeist",
            )
        )
        return "console"
    except Exception as exc:
        log_exception("god_ui.maybe_show_zeitgeist_onboarding", exc)
        return False


def prompt_household_background(sim_info=None,
                                household_id: Optional[int] = None,
                                census: Optional[Dict[str, Any]] = None) -> Any:
    """
    Prompt the player for household background hints and request a background.

    Returns "dialog" when a vanilla dialog was shown, "console" when it fell
    back to a console hint, False when it could not be attempted. Never raises.
    """
    try:
        sim_ref = _sim_ref(sim_info, household_id)
        scope = "household" if household_id is not None else "sim"
        title = i18n.t("god.background.title")
        body = i18n.t("god.background.body")

        def _apply(text=""):
            try:
                http_client.request_background(
                    sim_ref,
                    scope=scope,
                    household_id=household_id,
                    player_hints=text or "",
                    census=census,
                    force=False,
                    lang=_current_lang(),
                )
                _output_hint(i18n.t("god.background.done"))
            except Exception as exc:
                log_exception(
                    "god_ui.prompt_household_background.apply", exc)

        if _show_ok_cancel(sim_info, title, body, _apply):
            return "dialog"

        _output_hint(
            i18n.t(
                "god.background.hint",
                title=title,
                body=body,
                placeholder=i18n.t("god.background.prompt_placeholder"),
                unavailable=i18n.t("god.background.unavailable"),
            )
        )
        return "console"
    except Exception as exc:
        log_exception("god_ui.prompt_household_background", exc)
        return False
