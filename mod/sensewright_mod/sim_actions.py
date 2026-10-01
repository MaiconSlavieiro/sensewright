"""
Per-Sim pie-menu actions: view / regenerate a Sim's background and consolidate
its memory into one event.

All network and game access is best-effort: every public function catches its
exceptions, surfaces a localized notification and never raises. The sidecar is
reached through ``http_client`` (``request_background`` / ``request_consolidate``).
"""

from . import chat_ui, dialogs, god_ui, http_client, i18n
from .debug_log import log_exception, validation_log


def _lang() -> str:
    """Current UI language for outgoing calls."""
    try:
        return god_ui._current_lang() or "en"
    except Exception:
        return "en"


def _display_name(sim_info) -> str:
    """Best-effort name for notifications (falls back to a localized 'this Sim')."""
    try:
        name = getattr(sim_info, "full_name", None)
        if name:
            return str(name)
    except Exception:
        pass
    return i18n.t("cmd.pie.background.this_sim")


def _background_text(background) -> str:
    """Extract the readable body from a ``background`` payload."""
    if isinstance(background, str):
        return background.strip()
    if isinstance(background, dict):
        for key in ("text", "summary", "background", "description"):
            value = background.get(key)
            if value:
                return str(value).strip()
    return ""


def _ok(response) -> bool:
    return isinstance(response, dict) and bool(response.get("ok"))


def view_background(sim_info) -> None:
    """Fetch and show the clicked Sim's background, generating it if absent."""
    try:
        sim_ref = god_ui._sim_ref(sim_info)
        response = http_client.request_background(
            sim_ref, scope="sim", force=False, queue=True, lang=_lang()
        )
        if not _ok(response):
            chat_ui.show_simple_notification(
                i18n.t("notify.background.unavailable"), sim_info
            )
            return
        if response.get("queued"):
            chat_ui.show_simple_notification(
                i18n.t("notify.background.queued", name=_display_name(sim_info)),
                sim_info,
            )
            return
        text = _background_text(response.get("background"))
        if not text:
            chat_ui.show_simple_notification(
                i18n.t("notify.background.empty"), sim_info
            )
            return
        chat_ui.show_notification(
            i18n.t("notify.background.title", name=_display_name(sim_info)),
            text,
            sim_info,
        )
        validation_log("background: viewed sim={}".format(sim_ref.get("sim_id")))
    except Exception as exc:
        log_exception("sim_actions.view_background", exc)
        chat_ui.show_error(i18n.t("notify.background.unavailable"), sim_info)


def regenerate_background(sim_info) -> None:
    """Ask for confirmation, then force-regenerate the clicked Sim's background."""
    def _run() -> None:
        try:
            sim_ref = god_ui._sim_ref(sim_info)
            response = http_client.request_background(
                sim_ref, scope="sim", force=True, queue=True, lang=_lang()
            )
            if not _ok(response):
                chat_ui.show_error(i18n.t("notify.background.unavailable"), sim_info)
                return
            if response.get("queued"):
                chat_ui.show_simple_notification(
                    i18n.t("notify.background.regenerating", name=_display_name(sim_info)),
                    sim_info,
                )
                return
            text = _background_text(response.get("background"))
            chat_ui.show_notification(
                i18n.t("notify.background.regenerated", name=_display_name(sim_info)),
                text or i18n.t("notify.background.empty"),
                sim_info,
            )
            validation_log("background: regenerated sim={}".format(sim_ref.get("sim_id")))
        except Exception as exc:
            log_exception("sim_actions.regenerate_background.run", exc)
            chat_ui.show_error(i18n.t("notify.background.unavailable"), sim_info)

    try:
        dialogs.confirm(
            sim_info,
            i18n.t("cmd.pie.regen_background.title"),
            i18n.t("cmd.pie.regen_background.body", name=_display_name(sim_info)),
            on_ok=_run,
        )
    except Exception as exc:
        log_exception("sim_actions.regenerate_background", exc)


def consolidate_memory(sim_info) -> None:
    """Ask for confirmation, then fold the clicked Sim's dialogue into one memory."""
    def _run() -> None:
        try:
            sim_ref = god_ui._sim_ref(sim_info)
            response = http_client.request_consolidate(sim_ref, lang=_lang(), queue=True)
            if not _ok(response):
                chat_ui.show_error(i18n.t("notify.consolidate.error"), sim_info)
                return
            if response.get("queued"):
                chat_ui.show_simple_notification(i18n.t("notify.consolidate.queued"), sim_info)
                return
            count = int(response.get("consolidated", 0) or 0)
            key = response.get("message_key")
            message = i18n.t(key, count=count) if key else i18n.t(
                "notify.consolidate.done", count=count
            )
            chat_ui.show_simple_notification(message, sim_info)
            validation_log(
                "consolidate: sim={} count={}".format(sim_ref.get("sim_id"), count)
            )
        except Exception as exc:
            log_exception("sim_actions.consolidate_memory.run", exc)
            chat_ui.show_error(i18n.t("notify.consolidate.error"), sim_info)

    try:
        dialogs.confirm(
            sim_info,
            i18n.t("cmd.pie.consolidate.title"),
            i18n.t("cmd.pie.consolidate.body", name=_display_name(sim_info)),
            on_ok=_run,
        )
    except Exception as exc:
        log_exception("sim_actions.consolidate_memory", exc)
