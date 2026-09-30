"""
Sensewright in-game configuration panel (R7 / P2), built on the new stack base.

The panel is **data-driven**: it reads the declarative ``ControlSpec`` list from
the sidecar (``GET /v1/god/controls``) and groups it into sections, then renders
each section with the best available widget. It prefers S4CL dialogs; when the
library is unavailable it falls back to the cheat console (so the layout is still
testable offline and inspectable in ``sensewright_output.log``).

Nothing here raises; every game/library call is guarded.
"""

from typing import Any, Dict, List, Optional

from . import http_client, i18n, integrations
from .debug_log import debug_log, log_exception


# Section order for the home page (keys are the first dotted segment).
SECTION_ORDER = ("god", "agents", "llm", "memory", "ui", "runtime")

# Human fallback names when the locale has no ``panel.section.<id>`` key.
_SECTION_FALLBACK = {
    "god": "God",
    "agents": "Agents",
    "llm": "LLM",
    "memory": "Memory",
    "ui": "Interface",
    "runtime": "Runtime",
}


def section_of(control: Dict[str, Any]) -> str:
    """Return the section id a control belongs to (the first key segment)."""
    key = str((control or {}).get("key") or "")
    return key.split(".", 1)[0] if "." in key else (key or "general")


def group_sections(controls: Any) -> List[Dict[str, Any]]:
    """Group a ControlSpec list into ordered sections. Pure, never raises."""
    if not isinstance(controls, (list, tuple)):
        return []
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for control in controls:
        if not isinstance(control, dict):
            continue
        buckets.setdefault(section_of(control), []).append(control)

    ordered_ids = [sid for sid in SECTION_ORDER if sid in buckets]
    ordered_ids += [sid for sid in sorted(buckets) if sid not in ordered_ids]

    sections = []
    for section_id in ordered_ids:
        sections.append({
            "id": section_id,
            "label": section_label(section_id),
            "controls": buckets[section_id],
        })
    return sections


def section_label(section_id: str) -> str:
    """Localized section label with an English fallback."""
    key = "panel.section.{}".format(section_id)
    label = i18n.t(key)
    if label == key:
        return _SECTION_FALLBACK.get(section_id, section_id.title())
    return label


def format_home(sections: List[Dict[str, Any]]) -> str:
    """Render the home page (one line per section) as plain text."""
    lines = [i18n.t("panel.title")]
    for section in sections:
        lines.append("- {} ({})".format(section["label"], len(section["controls"])))
    return "\n".join(lines)


def _output(message: str, sim_info=None) -> bool:
    """Fallback renderer: cheat console, then the debug log."""
    try:
        from .chat_ui import output_to_console
        if output_to_console(message):
            return True
    except Exception as exc:
        log_exception("panel_ui._output.console", exc)
    try:
        debug_log("[panel] {}".format(message))
        return True
    except Exception:
        return False


def _show_choice(sim_info, title: str, text: str, options, on_select) -> bool:
    """Show an S4CL choose-option dialog when possible. Best-effort."""
    dialog = integrations.s4cl_choose_option(title, text, options)
    if dialog is None:
        return False
    return integrations.s4cl_show_choose_option(dialog, sim_info, on_select)


def open_panel(sim_info=None) -> bool:
    """Open the configuration panel. Returns True when something was rendered."""
    controls = None
    values = None
    try:
        data = http_client.get_god_controls()
        if isinstance(data, dict):
            controls = data.get("controls")
            values = data.get("values")
    except Exception as exc:
        log_exception("panel_ui.open_panel.controls", exc)

    sections = group_sections(controls)
    if not sections:
        return _output(i18n.t("panel.unavailable"), sim_info)

    # S4CL: pick a section from the home list.
    options = [(section["id"], section["label"]) for section in sections]
    def _pick(section_id):
        for section in sections:
            if section["id"] == section_id:
                _output(_render_section(section, values), sim_info)
                return
    if _show_choice(sim_info, i18n.t("panel.title"),
                    i18n.t("panel.choose_section"), options, _pick):
        return True

    return _output(format_home(sections), sim_info)


def _render_section(section: Dict[str, Any], values: Optional[Dict[str, Any]]) -> str:
    """Render one section's controls as plain text."""
    try:
        from .god_ui import format_controls
        body = format_controls(section.get("controls"), values)
    except Exception as exc:
        log_exception("panel_ui._render_section", exc)
        body = ""
    header = section.get("label") or section.get("id") or ""
    return "{}:\n{}".format(header, body) if body else header


def set_value(key: str, value: Any, persist: bool = True) -> bool:
    """Apply one control value via the sidecar. Best-effort, never raises."""
    if not key:
        return False
    try:
        http_client.set_god_controls(values={key: value}, persist=persist)
        return True
    except Exception as exc:
        log_exception("panel_ui.set_value", exc)
        return False
