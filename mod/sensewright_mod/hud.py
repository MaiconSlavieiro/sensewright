"""
Debug HUD for Sensewright.

The mod runs mostly behind the scenes, so a player cannot tell whether the loop
is actually alive. This module surfaces a compact, opt-in status line in the
game UI: whether the sidecar is reachable, the heartbeat counter, the pulse
size and the intents pulled/executed.

Enable with ``sw.hud on`` (``sw.hud off`` to stop, ``sw.hud now`` for a single
reading, ``sw.hud status`` for the full summary). Everything is best-effort and
never raises; outside the game the lines fall back to the debug log.
"""

from . import i18n
from .debug_log import debug_log, log_exception

# Emit a status line every N heartbeats (1 = every beat, ~15 s) while enabled.
EVERY_BEATS = 1

# Sidecar reachability as seen by the last pulse: unknown / on / off / error.
_UNKNOWN = None
_ON = "on"
_OFF = "off"
_ERROR = "error"

# Canonical tokens for the ``{sidecar}`` placeholder: the ``hud.line`` template
# expects a status token, not a localized word (M7).
_SIDECAR_TOKENS = {
    _ON: "ON",
    _OFF: "OFF",
    _ERROR: "ERROR",
}

_state = {
    "enabled": False,
    "beats": 0,
    "sims": 0,
    "last_pulled": 0,
    "intents_total": 0,
    "intents_ok": 0,
    "sidecar": _UNKNOWN,
}


def is_enabled():
    """True when the debug HUD is on."""
    return bool(_state["enabled"])


def set_enabled(value):
    """Turn the HUD on/off. Returns the new state."""
    _state["enabled"] = bool(value)
    return _state["enabled"]


def toggle():
    """Flip the HUD state. Returns the new state."""
    return set_enabled(not _state["enabled"])


def reset():
    """Reset the counters (keeps the enabled flag)."""
    _state["beats"] = 0
    _state["sims"] = 0
    _state["last_pulled"] = 0
    _state["intents_total"] = 0
    _state["intents_ok"] = 0
    _state["sidecar"] = _UNKNOWN


def _state_from_results(tick_result, pull_result):
    """Infer reachability: on when the sidecar answered the tick or the pull."""
    if isinstance(tick_result, dict) or isinstance(pull_result, dict):
        return _ON
    return _OFF


def _normalize(state):
    return state if state in (_ON, _OFF, _ERROR) else _OFF


def note_heartbeat(tick_result=None, pull_result=None, sims=0, sidecar_state=None):
    """Record one zone heartbeat (called every pulse). Never raises.

    ``sidecar_state`` ("on"/"off"/"error") is authoritative when given (the
    caller can probe `/v1/health` to tell "down" from "up but failing"); when
    omitted it is inferred from the tick/pull results.
    """
    _state["beats"] += 1
    try:
        if sims:
            _state["sims"] = int(sims)
    except (TypeError, ValueError):
        pass

    if sidecar_state is None:
        sidecar_state = _state_from_results(tick_result, pull_result)
    sidecar_state = _normalize(sidecar_state)

    previous = _state["sidecar"]
    _state["sidecar"] = sidecar_state

    if isinstance(pull_result, dict):
        intents = pull_result.get("intents")
        if isinstance(intents, list):
            _state["last_pulled"] = len(intents)

    if not _state["enabled"]:
        return

    flipped = previous is not None and previous != sidecar_state
    if flipped:
        _notify("hud.sidecar." + sidecar_state)
    # The periodic status line is log-only (a notification every beat is noisy);
    # ``sw.hud now`` still surfaces it on demand.
    _log_line()


def note_intent(intent, result):
    """Record one executed intent and trace it while the HUD is on. Never raises."""
    _state["intents_total"] += 1
    ok = bool(isinstance(result, dict) and result.get("ok"))
    if ok:
        _state["intents_ok"] += 1
    if not _state["enabled"]:
        return

    intent = intent if isinstance(intent, dict) else {}
    kind = str(intent.get("kind") or "?")
    name = str(intent.get("name") or kind)
    error = result.get("error") if isinstance(result, dict) else None
    status = "OK" if ok else (error or "FAIL")
    _log("hud.intent", kind=kind, name=name, status=status)


def _line_message():
    """The compact localized status line."""
    state = _state["sidecar"]
    key = {
        _ON: "hud.line",
        _ERROR: "hud.line.error",
    }.get(state, "hud.line.native")
    return _t(
        key,
        sidecar=_SIDECAR_TOKENS.get(state, "OFF"),
        beats=_state["beats"],
        sims=_state["sims"],
        pulled=_state["last_pulled"],
        ok=_state["intents_ok"],
        total=_state["intents_total"],
    )


def _log_line():
    """Write the compact status line to the log only (no notification)."""
    try:
        from .debug_log import validation_log

        validation_log("hud: {}".format(_line_message()))
    except Exception as exc:
        log_exception("hud._log_line", exc)


def emit_line():
    """Emit the compact status line as a notification. Never raises."""
    return _notify_message(_line_message())


def render_status():
    """Return the full localized HUD summary (for ``sw.hud``)."""
    state = _t("hud.on") if _state["enabled"] else _t("hud.off")
    sidecar = _SIDECAR_TOKENS.get(_state["sidecar"], "?")
    return _t(
        "cmd.hud.status",
        state=state,
        sidecar=sidecar,
        beats=_state["beats"],
        sims=_state["sims"],
        pulled=_state["last_pulled"],
        ok=_state["intents_ok"],
        total=_state["intents_total"],
    )


# --- rendering helpers -------------------------------------------------------


def _t(key, **args):
    try:
        return i18n.t(key, **args)
    except Exception as exc:
        log_exception("hud._t", exc)
        return key


def _log(key, **args):
    """Localize a HUD line and write it to the log only (no notification)."""
    try:
        message = i18n.t(key, **args)
    except Exception as exc:
        log_exception("hud._log", exc)
        message = key
    try:
        from .debug_log import validation_log

        validation_log("hud: {}".format(message))
    except Exception:
        pass


def _notify_message(message):
    """Log a HUD line and surface it as an in-game notification."""
    try:
        from .debug_log import validation_log

        validation_log("hud: {}".format(message))
    except Exception:
        pass
    return notify(message)


def _notify(key, **args):
    try:
        message = i18n.t(key, **args)
    except Exception as exc:
        log_exception("hud._notify", exc)
        message = key
    return _notify_message(message)


def notify(message):
    """Best-effort in-game notification. Tests monkeypatch this helper."""
    try:
        from . import chat_ui, sim_context

        sim_info = None
        try:
            sim_info = sim_context._get_active_sim_info()
        except Exception as exc:
            log_exception("hud.notify.sim_info", exc)
            sim_info = None
        if chat_ui.show_simple_notification(message, sim_info):
            return True
    except Exception as exc:
        log_exception("hud.notify", exc)
    try:
        debug_log("[Sensewright HUD] {}".format(message))
    except Exception as exc:
        log_exception("hud.notify.log", exc)
    return False
