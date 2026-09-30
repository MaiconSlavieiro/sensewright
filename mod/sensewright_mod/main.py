"""
Main command bindings for Sensewright.
All @sims4.commands.Command bindings for in-game cheats.
Guarded imports so file can be imported outside the game.
"""

from typing import Any, Callable, Dict

# Try to import sims4.commands, provide no-op fallback
try:
    import sims4.commands  # type: ignore
    _COMMANDS_AVAILABLE = True
except Exception:
    _COMMANDS_AVAILABLE = False

    class _DummyCommands:
        CommandType = type("CommandType", (), {"Live": 0, "Cheat": 1, "Automation": 2})

        @staticmethod
        def Command(name: str, command_type=0):
            def decorator(func: Callable) -> Callable:
                return func
            return decorator

        class CheatOutput:
            def __init__(self, _connection):
                pass

            def __call__(self, msg: str):
                _debug_log(msg)

    sims4 = type("sims4", (), {"commands": _DummyCommands()})  # type: ignore


from . import god_ui, hud, i18n, panel_ui
from .config import (
    get_base_url,
    write_ui_language,
    read_autonomy_level,
    write_autonomy_level,
    sidecar_launch,
    clear_runtime_cache,
)
from .debug_log import (
    debug_log as _debug_log,
    log_exception as _log_exception,
    validation_log as _validation_log,
)
from .http_client import (
    chat,
    hey,
    status,
    health,
    reset,
    set_autonomy,
    set_lang,
    get_god_controls,
    set_god_controls,
    set_zeitgeist,
    suggest_zeitgeist,
    request_profile,
    evolve,
    get_seats,
    assign_seat,
    attach_lifecycle,
    SidecarUnreachable,
    SidecarError,
)
from .sim_context import collect
from .chat_ui import show_simple_notification
from .tool_executor import execute_batch


# Autonomy levels
AUTONOMY_LEVELS = ("off", "observe", "suggest", "semi", "full")
# Data-driven: derived from the locale manifest, so a new language is accepted
# as soon as its ``locales/<code>.json`` + manifest entry exist (no code edit).
VALID_LANGUAGES = tuple(["auto"] + list(i18n.available_locales()))

# Bumped on each in-game behaviour change so the loaded build can be confirmed
# from `sensewright_output.log` (the game only loads script mods at startup).
_BUILD = "2026-09-29.25"


def _join_args(first, rest) -> str:
    """Join a command's free-text tokens (first positional + variadic rest)."""
    parts = []
    if first is not None:
        parts.append(str(first))
    parts.extend(str(part) for part in rest)
    return " ".join(parts).strip()


def _get_sim_info(sim_id: int = 0):
    """Get SimInfo by ID or active Sim."""
    try:
        import services  # type: ignore
        sim_info_manager = services.sim_info_manager()
        if sim_info_manager is None:
            return None
        if sim_id == 0:
            client_manager = services.client_manager()
            if client_manager:
                client = client_manager.get_first_client()
                if client:
                    return client.active_sim_info
            return None
        return sim_info_manager.get(sim_id)
    except Exception:
        return None


def _build_sim_dict(sim_info) -> Dict[str, Any]:
    """Build the sim dict for API calls."""
    if sim_info is None:
        return {"player_id": "local", "save_id": "", "sim_id": 0}
    return {
        "player_id": "local",
        "save_id": collect(sim_info).get("save_id", ""),
        "sim_id": getattr(sim_info, "id", 0) or 0,
    }


def _get_current_lang() -> str:
    """Get the current UI language for API calls (lazy game detection)."""
    try:
        i18n.ensure_locale()
    except Exception:
        pass
    return i18n.current_locale()


def _note_player_active(sim_id: int = 0) -> None:
    """Arm the player-priority lock for the player's active Sim (C1).

    Called at the top of every player-issued ``ai.*`` command so the autonomy
    rails know the player is acting and hold the agent off. Best-effort and
    never raises: the public helper lives in ``tool_executor`` (added by SA2),
    so a missing/older version is tolerated.
    """
    try:
        from . import tool_executor
        tool_executor.record_player_activity(sim_id)
    except Exception as exc:
        _log_exception("main._note_player_active", exc)


def _ensure_ready() -> None:
    """
    Best-effort late bootstrap.

    Script mods load before the game services, so the event collector and the
    game-language detection are retried here on the first command (the game is
    fully up by then). Idempotent and silent. Never raises.
    """
    try:
        i18n.ensure_locale()
    except Exception:
        pass
    try:
        from . import state_collector
        state_collector.ensure_started()
    except Exception:
        pass
    try:
        from . import player_activity
        player_activity.install()
    except Exception:
        pass


def _output(_connection, message: str) -> None:
    """Output to the cheat console, trying the native APIs then print.

    ``CheatOutput(connection)`` is the documented API; ``sims4.commands.output``
    and the no-connection form are fallbacks for patch differences.
    """
    _ensure_ready()
    _debug_log("[conn={!r}] {}".format(_connection, message))

    commands = getattr(sims4, "commands", None)
    if commands is not None:
        cheat_cls = getattr(commands, "CheatOutput", None)
        if cheat_cls is not None:
            for conn in (_connection, None):
                try:
                    cheat_cls(conn)(message)
                    return
                except Exception as exc:
                    _debug_log("  CheatOutput({!r}) failed: {!r}".format(conn, exc))

        output = getattr(commands, "output", None)
        if callable(output):
            for args in ((message, _connection), (message,)):
                try:
                    output(*args)
                    return
                except Exception as exc:
                    _debug_log("  output{!r} failed: {!r}".format(args, exc))

    try:
        _debug_log(message)
    except Exception:
        pass


def _format_providers(providers) -> str:
    """Format the /v1/status providers (list of dicts) into a readable string."""
    if not providers:
        return "none"
    if isinstance(providers, dict):
        return ", ".join(str(k) for k in providers)
    if isinstance(providers, (list, tuple)):
        names = []
        for entry in providers:
            if isinstance(entry, dict):
                name = entry.get("name") or entry.get("provider") or "?"
                available = entry.get("available")
                names.append("{} ({})".format(name, "up" if available else "down") if available is not None else str(name))
            else:
                names.append(str(entry))
        return ", ".join(names) if names else "none"
    return str(providers)


def _handle_sidecar_error(e: Exception, _connection=None) -> None:
    """Handle sidecar errors with localized messages."""
    if isinstance(e, SidecarUnreachable):
        _output(_connection, i18n.t("notify.sidecar_unreachable"))
    elif isinstance(e, SidecarError):
        if e.status == 429:
            _output(_connection, i18n.t("error.rate_limited"))
        elif e.status == 400:
            _output(_connection, i18n.t("error.bad_request"))
        elif e.status == 401:
            _output(_connection, i18n.t("notify.sidecar_unreachable"))
            clear_runtime_cache()
        else:
            _output(_connection, i18n.t("error.internal"))
    else:
        _output(_connection, i18n.t("error.internal"))


def _spawn_sidecar():
    """
    Start the packaged ``.exe`` or, until it exists, the bundled source.

    Returns ``(started, command)``. Never raises.
    """
    command, cwd = sidecar_launch()
    if not command:
        return False, []

    try:
        import subprocess
        import os

        # CREATE_NO_WINDOW = 0x08000000
        creation_flags = 0x08000000 if os.name == "nt" else 0
        # Tell the sidecar which game process to watch so it exits with the game.
        env = os.environ.copy()
        env["SENSEWRIGHT_GAME_PID"] = str(os.getpid())
        _debug_log("spawning sidecar: {} (cwd={!r}, game_pid={})".format(
            command, cwd, os.getpid()))
        subprocess.Popen(
            command,
            cwd=cwd or None,
            creationflags=creation_flags,
            close_fds=True,
            start_new_session=True,
            env=env,
        )
        clear_runtime_cache()
        return True, command
    except Exception:
        return False, command


def _extract_tool_text(tool_calls):
    """Return the first visible line produced by a text-bearing tool call.

    The model often replies only with a tool call (e.g. ``spontaneous_line``)
    and no text; surfacing that line avoids the "nothing happened" silence.
    """
    if not tool_calls:
        return ""
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        name = call.get("name") or call.get("tool") or ""
        if name not in ("spontaneous_line", "say_to"):
            continue
        args = call.get("args") or call.get("arguments") or {}
        if isinstance(args, dict):
            text = args.get("text") or args.get("line")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def _render_response(response, sim_info, _connection=None) -> None:
    """Execute tool calls and surface the Sim reply/fallback to the player."""
    if not isinstance(response, dict):
        response = {}

    reply = response.get("reply")
    tool_calls = response.get("tool_calls", [])
    message_key = response.get("message_key")
    message_args = response.get("message_args", {}) or {}

    if tool_calls:
        names = [c.get("name", "") for c in tool_calls if isinstance(c, dict)]
        _validation_log("chat tool_calls build={} names={}".format(_BUILD, names))
        execute_batch(tool_calls)

    if reply:
        text = reply
    elif message_key:
        text = i18n.t(message_key, **message_args)
    elif tool_calls:
        # Tool-only reply: surface a text-bearing tool call if there is one,
        # otherwise stay quiet (the tool effect is the response).
        text = _extract_tool_text(tool_calls)
        if not text:
            return
    else:
        text = i18n.t("error.brain_foggy")

    # Always give feedback: dialog first, cheat console as fallback.
    if not show_simple_notification(text, sim_info, _connection):
        _output(_connection, text)


# --- Command implementations ---


def run_chat(text: str, sim_info=None, _connection=None) -> None:
    """Send one chat turn for ``sim_info`` and render the reply.

    Shared by the ``sw.chat`` command and the pie-menu "Chat…" entry. Best-effort:
    never raises.
    """
    if not text:
        _output(_connection, i18n.t("error.bad_request"))
        return
    try:
        if sim_info is None:
            sim_info = _get_sim_info()
        if sim_info is None:
            _output(_connection, i18n.t("error.bad_request"))
            return

        sim_dict = _build_sim_dict(sim_info)
        context = collect(sim_info)
        lang = _get_current_lang()
        response = chat(sim_dict, text, context, lang=lang)
        _render_response(response, sim_info, _connection)
    except (SidecarUnreachable, SidecarError) as e:
        _handle_sidecar_error(e, _connection)
    except Exception as e:
        _log_exception("run_chat", e)
        _output(_connection, i18n.t("error.internal"))


@sims4.commands.Command("sw.help", command_type=sims4.commands.CommandType.Live)
def cmd_help(_connection=None) -> None:
    """Show help for all Sensewright commands."""
    _debug_log("help requested (build {})".format(_BUILD))
    _output(_connection, i18n.t("cmd.help.title"))
    _output(_connection, i18n.t("cmd.help.body"))


@sims4.commands.Command("sw.status", command_type=sims4.commands.CommandType.Live)
def cmd_status(_connection=None) -> None:
    """Show sidecar status and provider health."""
    try:
        # Try health first (no auth)
        health_data = health()
        sidecar_up = health_data.get("ok", False)
        version = health_data.get("version", "unknown")
        uptime = health_data.get("uptime_s", 0.0)
        lang = health_data.get("lang", "en")

        if sidecar_up:
            # Get detailed status (requires auth)
            try:
                status_data = status()
                providers = status_data.get("providers", [])
                autonomy = status_data.get("autonomy", {})
                memory = status_data.get("memory", {})
                god = status_data.get("god", {})

                providers_str = _format_providers(providers)
                autonomy_str = str(autonomy)
                memory_str = str(memory)
                god_str = str(god)

                _output(_connection, i18n.t("cmd.status.title"))
                _output(_connection, i18n.t("cmd.status.body",
                    sidecar_status="Online",
                    version=version,
                    uptime=int(uptime),
                    lang=lang,
                    providers=providers_str,
                    autonomy=autonomy_str,
                    memory=memory_str,
                    god=god_str
                ))
            except (SidecarUnreachable, SidecarError) as e:
                _handle_sidecar_error(e, _connection)
        else:
            _output(_connection, i18n.t("cmd.status.title"))
            _output(_connection, i18n.t("cmd.status.sidecar_down"))

    except SidecarUnreachable:
        _output(_connection, i18n.t("cmd.status.title"))
        _output(_connection, i18n.t("cmd.status.sidecar_down"))
    except Exception:
        _output(_connection, i18n.t("error.internal"))


@sims4.commands.Command("sw.chat", command_type=sims4.commands.CommandType.Live)
def cmd_chat(message=None, *args, _connection=None) -> None:
    """Chat with the selected Sim: sw.chat <free text>.

    ``message`` + ``*args`` (both unannotated) accept either a single token or a
    split sentence. An annotated positional ``message`` breaks the TS4 command
    parser (annotations must be real types), and a lone ``*args`` can be rejected;
    this hybrid is safe for both shapes.
    """
    _note_player_active()
    text = _join_args(message, args)
    _debug_log("sw.chat invoked build={} args={!r} -> {!r}".format(_BUILD, args, text))
    run_chat(text, None, _connection)


@sims4.commands.Command("sw.hey", command_type=sims4.commands.CommandType.Live)
def cmd_hey(_connection=None) -> None:
    """Trigger a spontaneous greeting from the Sim."""
    _note_player_active()
    try:
        sim_info = _get_sim_info()
        if sim_info is None:
            _output(_connection, i18n.t("error.bad_request"))
            return

        sim_dict = _build_sim_dict(sim_info)
        context = collect(sim_info)
        lang = _get_current_lang()

        response = hey(sim_dict, context, lang=lang)
        _render_response(response, sim_info, _connection)

    except (SidecarUnreachable, SidecarError) as e:
        _handle_sidecar_error(e, _connection)
    except Exception as e:
        _log_exception("sw.hey", e)
        _output(_connection, i18n.t("error.internal"))


@sims4.commands.Command("sw.reset", command_type=sims4.commands.CommandType.Live)
def cmd_reset(scope: str = "session", _connection=None) -> None:
    """Clear conversation/memory scope: session|sim|save|all."""
    _note_player_active()
    valid_scopes = ("session", "sim", "save", "all")
    if scope not in valid_scopes:
        _output(_connection, i18n.t("error.bad_request"))
        return

    sim_info = _get_sim_info()
    sim_dict = _build_sim_dict(sim_info)

    try:
        reset(scope, sim_dict)
        _output(_connection, i18n.t("cmd.reset.done", scope=scope))
    except (SidecarUnreachable, SidecarError) as e:
        _handle_sidecar_error(e, _connection)
    except Exception:
        _output(_connection, i18n.t("error.internal"))


@sims4.commands.Command("sw.forget", command_type=sims4.commands.CommandType.Live)
def cmd_forget(scope: str = "sim", _connection=None) -> None:
    """Wipe memory for scope: sim|save|all."""
    # This is an alias for reset with different default
    _note_player_active()
    valid_scopes = ("sim", "save", "all")
    if scope not in valid_scopes:
        _output(_connection, i18n.t("error.bad_request"))
        return

    sim_info = _get_sim_info()
    sim_dict = _build_sim_dict(sim_info)

    try:
        reset(scope, sim_dict)
        _output(_connection, i18n.t("cmd.forget.done", scope=scope))
    except (SidecarUnreachable, SidecarError) as e:
        _handle_sidecar_error(e, _connection)
    except Exception:
        _output(_connection, i18n.t("error.internal"))


@sims4.commands.Command("sw.autonomy", command_type=sims4.commands.CommandType.Live)
def cmd_autonomy(level: str = "", _connection=None) -> None:
    """Set autonomy level for the Sim: off|observe|suggest|semi|full.

    With no argument, re-applies the level persisted locally ([agents] autonomy,
    code review L4); with no persisted level it is a bad request.
    """
    _note_player_active()
    if not level:
        level = read_autonomy_level()
    if level not in AUTONOMY_LEVELS:
        _output(_connection, i18n.t("error.bad_request"))
        return

    sim_info = _get_sim_info()
    if sim_info is None:
        _output(_connection, i18n.t("error.bad_request"))
        return

    sim_dict = _build_sim_dict(sim_info)

    try:
        set_autonomy(sim_dict, level)
    except (SidecarUnreachable, SidecarError) as e:
        _handle_sidecar_error(e, _connection)
        return
    except Exception as e:
        _log_exception("sw.autonomy", e)
        _output(_connection, i18n.t("error.internal"))
        return

    # Persist the chosen level locally (code review L4), best-effort: the set
    # already succeeded, so a write failure is logged but still reported.
    if not write_autonomy_level(level):
        _debug_log("sw.autonomy: failed to persist level={!r}".format(level))

    _output(_connection, i18n.t("cmd.autonomy.set", level=level, sim_id=sim_dict["sim_id"]))


@sims4.commands.Command("sw.lang", command_type=sims4.commands.CommandType.Live)
def cmd_lang(lang: str = "", _connection=None) -> None:
    """Set UI language: auto|<locale> (persists to config)."""
    _note_player_active()
    if lang not in VALID_LANGUAGES:
        _output(_connection, i18n.t("cmd.lang.invalid", lang=lang or "empty"))
        return

    # Update i18n
    i18n.set_locale(lang)

    # Persist to config
    if write_ui_language(lang):
        _output(_connection, i18n.t("cmd.lang.set", lang=lang))
    else:
        _output(_connection, i18n.t("error.internal"))

    # Notify sidecar
    try:
        set_lang(lang)
    except (SidecarUnreachable, SidecarError):
        pass  # Best effort


@sims4.commands.Command("sw.hud", command_type=sims4.commands.CommandType.Live)
def cmd_hud(action: str = "", _connection=None) -> None:
    """Debug HUD: live in-game proof the loop is running (on|off|now|status)."""
    _note_player_active()
    action = (action or "").strip().lower()
    if action == "on":
        hud.set_enabled(True)
        _output(_connection, i18n.t("cmd.hud.on"))
        hud.emit_line()
    elif action == "off":
        hud.set_enabled(False)
        _output(_connection, i18n.t("cmd.hud.off"))
    elif action == "now":
        hud.emit_line()
        _output(_connection, hud.render_status())
    elif action in ("", "status", "toggle"):
        if action == "toggle" or action == "":
            hud.toggle()
        _output(_connection, hud.render_status())
    else:
        _output(_connection, i18n.t("cmd.hud.usage"))


@sims4.commands.Command("sw.panel", command_type=sims4.commands.CommandType.Live)
def cmd_panel(_connection=None) -> None:
    """Open the Sensewright configuration panel (stack base: S4CL dialogs)."""
    _note_player_active()
    try:
        sim_info = _get_sim_info()
    except Exception:
        sim_info = None
    try:
        shown = panel_ui.open_panel(sim_info)
    except Exception:
        shown = False
    if not shown:
        _output(_connection, i18n.t("panel.unavailable"))


def _god_controls_snapshot():
    """Return ``(controls, values)`` from ``GET /v1/god/controls`` (or empty)."""
    data = get_god_controls()
    controls = []
    values = {}
    if isinstance(data, dict):
        controls = data.get("controls") or []
        values = data.get("values") or {}
    return controls, values


def _show_god_summary(_connection) -> None:
    """Print the current God preset, the controls and the command help."""
    controls, values = _god_controls_snapshot()
    summary = god_ui.format_controls(controls, values)
    if not summary:
        summary = i18n.t("god.panel.unavailable")
    _output(_connection, i18n.t("god.panel.title"))
    preset = values.get("preset") if isinstance(values, dict) else None
    if preset:
        _output(_connection, i18n.t("cmd.god.preset_current", preset=preset))
    _output(_connection, i18n.t("god.panel.body", controls=summary))
    _output(_connection, i18n.t("cmd.god.help", presets=", ".join(god_ui.GOD_PRESETS)))


def _run_neighborhood_scan(_connection) -> None:
    """Force a full-save neighborhood census (maps + backgrounds every Sim)."""
    from . import state_collector

    response = state_collector.scan_neighborhood(force=True)
    if not isinstance(response, dict):
        _output(_connection, i18n.t("cmd.god.unavailable"))
        return
    _output(_connection, i18n.t(
        "cmd.god.scan",
        sims=response.get("sims", 0),
        households=response.get("households", 0),
        queued=response.get("queued", 0),
    ))


def _run_god_tick_now(_connection) -> None:
    """Force one God-orchestration tick now and report the issued directives."""
    from . import state_collector

    response = state_collector.maybe_god_tick(force=True)
    if not isinstance(response, dict) or response.get("ok") is False:
        _output(_connection, i18n.t("cmd.god.unavailable"))
        return
    directives = response.get("directives") or []
    if directives:
        _output(_connection, i18n.t(
            "cmd.god.tick",
            count=len(directives),
            preset=response.get("preset", "") or "",
        ))
    else:
        _output(_connection, i18n.t("cmd.god.tick_empty"))


@sims4.commands.Command("sw.god", command_type=sims4.commands.CommandType.Live)
def cmd_god(first=None, *rest, _connection=None) -> None:
    """God panel/summary and control.

    Usage: ``sw.god`` (summary) · ``sw.god on|off`` · ``sw.god tick`` ·
    ``sw.god preset <name>`` · ``sw.god <preset>`` · ``sw.god set <key> <value>``.
    """
    _note_player_active()
    tokens = []
    for part in (first,) + rest:
        if part is None:
            continue
        text = str(part).strip()
        if text:
            tokens.append(text)
    action = tokens[0].lower() if tokens else ""

    try:
        if not action or action == "panel":
            _show_god_summary(_connection)
            return

        if action in ("on", "off"):
            set_god_controls(enabled=(action == "on"))
            _output(_connection, i18n.t("cmd.god.on" if action == "on" else "cmd.god.off"))
            return

        if action == "tick":
            _run_god_tick_now(_connection)
            return

        if action == "scan":
            _run_neighborhood_scan(_connection)
            return

        if action in god_ui.GOD_PRESETS:
            set_god_controls(preset=action, enabled=True)
            _output(_connection, i18n.t("cmd.god.preset", preset=action))
            return

        if action == "preset":
            name = tokens[1].lower() if len(tokens) > 1 else ""
            if name not in god_ui.GOD_PRESETS:
                _output(_connection, i18n.t(
                    "cmd.god.bad_preset",
                    preset=name,
                    presets=", ".join(god_ui.GOD_PRESETS),
                ))
                return
            set_god_controls(preset=name, enabled=True)
            _output(_connection, i18n.t("cmd.god.preset", preset=name))
            return

        if action == "set":
            if len(tokens) < 3:
                _output(_connection, i18n.t(
                    "cmd.god.help", presets=", ".join(god_ui.GOD_PRESETS)))
                return
            key = tokens[1]
            value = " ".join(tokens[2:])
            response = set_god_controls(values={key: value})
            if isinstance(response, dict) and response.get("ok") is False:
                _output(_connection, i18n.t(
                    "cmd.god.bad_control",
                    name=key,
                    detail=response.get("detail") or "",
                ))
                return
            _output(_connection, i18n.t("cmd.god.set_done", name=key, value=value))
            return

        _output(_connection, i18n.t(
            "cmd.god.help", presets=", ".join(god_ui.GOD_PRESETS)))
    except (SidecarUnreachable, SidecarError):
        _output(_connection, i18n.t("cmd.god.unavailable"))
    except Exception:
        _output(_connection, i18n.t("error.internal"))


@sims4.commands.Command("sw.zeitgeist", command_type=sims4.commands.CommandType.Live)
def cmd_zeitgeist(message=None, *args, _connection=None) -> None:
    """Set the neighborhood zeitgeist: sw.zeitgeist <tags_csv|auto|empty>."""
    _note_player_active()
    raw = _join_args(message, args)

    # No arg: offer the onboarding dialog.
    if not raw:
        god_ui.maybe_show_zeitgeist_onboarding(_get_sim_info())
        return

    sim_info = _get_sim_info()
    if sim_info is None:
        _output(_connection, i18n.t("error.bad_request"))
        return

    sim_dict = _build_sim_dict(sim_info)
    lang = _get_current_lang()

    if raw.lower() == "auto":
        try:
            response = suggest_zeitgeist(sim_dict, [], "", lang=lang)
            suggested = ""
            if isinstance(response, dict):
                suggested = response.get("suggested_text", "") or ""
            _output(_connection, i18n.t("god.zeitgeist.suggested", text=suggested))
        except (SidecarUnreachable, SidecarError):
            _output(_connection, i18n.t("cmd.zeitgeist.unavailable"))
        except Exception:
            _output(_connection, i18n.t("cmd.zeitgeist.unavailable"))
        return

    tags = [tag.strip() for tag in raw.split(",") if tag.strip()]
    valid_tags = [tag for tag in tags if tag in god_ui.MOOD_TAGS]
    if tags and not valid_tags:
        _output(_connection, i18n.t("god.zeitgeist.invalid"))
        return

    try:
        set_zeitgeist(sim_dict, valid_tags, "", 0.5, lang)
        _output(_connection, i18n.t("cmd.zeitgeist.set"))
    except (SidecarUnreachable, SidecarError):
        _output(_connection, i18n.t("cmd.zeitgeist.unavailable"))
    except Exception:
        _output(_connection, i18n.t("cmd.zeitgeist.unavailable"))


@sims4.commands.Command("sw.profile", command_type=sims4.commands.CommandType.Live)
def cmd_profile(message=None, *args, _connection=None) -> None:
    """Generate this Sim's character profile: sw.profile <one sentence>."""
    _note_player_active()
    seed = _join_args(message, args)

    sim_info = _get_sim_info()
    if sim_info is None:
        _output(_connection, i18n.t("error.bad_request"))
        return

    sim_dict = _build_sim_dict(sim_info)

    try:
        response = request_profile(sim_dict, seed=seed, lang=_get_current_lang())
        profile = {}
        if isinstance(response, dict):
            profile = response.get("profile") or {}
        if not profile:
            _output(_connection, i18n.t("cmd.profile.unavailable"))
            return
        _output(
            _connection,
            i18n.t(
                "cmd.profile.done",
                name=profile.get("name") or "Sim",
                backstory=profile.get("backstory") or "",
            ),
        )
    except (SidecarUnreachable, SidecarError):
        _output(_connection, i18n.t("cmd.profile.unavailable"))
    except Exception:
        _output(_connection, i18n.t("cmd.profile.unavailable"))


@sims4.commands.Command("sw.evolve", command_type=sims4.commands.CommandType.Live)
def cmd_evolve(args: str = "", _connection=None) -> None:
    """Run the reflection/evolution loop: sw.evolve [save]."""
    _note_player_active()
    sim_info = _get_sim_info()
    if sim_info is None:
        _output(_connection, i18n.t("error.bad_request"))
        return

    scope = "save" if (args or "").strip().lower() in ("save", "all") else "sim"
    sim_dict = _build_sim_dict(sim_info)

    try:
        response = evolve(sim_dict, scope=scope, force=True, lang=_get_current_lang())
        reflected = 0
        skipped = 0
        if isinstance(response, dict):
            reflected = int(response.get("reflected", 0) or 0)
            skipped = int(response.get("skipped", 0) or 0)
        _output(_connection, i18n.t("cmd.evolve.done", reflected=reflected, skipped=skipped))
    except (SidecarUnreachable, SidecarError):
        _output(_connection, i18n.t("error.internal"))
    except Exception:
        _output(_connection, i18n.t("error.internal"))


@sims4.commands.Command("sw.agents", command_type=sims4.commands.CommandType.Live)
def cmd_agents(first=None, second=None, _connection=None) -> None:
    """Agent roster + impulse dial: sw.agents [<seats> | <sim_id> <freq>]."""
    _note_player_active()
    sim_info = _get_sim_info()
    sim_dict = _build_sim_dict(sim_info)
    save_id = sim_dict.get("save_id", "") or ""

    try:
        if first is None:
            data = get_seats(save_id)
            roster = god_ui.format_roster(data) if isinstance(data, dict) else ""
            seats = data.get("seats", 0) if isinstance(data, dict) else 0
            used = data.get("used", 0) if isinstance(data, dict) else 0
            _validation_log(
                "agents roster: seats={} used={} agents={}".format(
                    seats,
                    used,
                    [
                        (a.get("sim_id"), a.get("tier"))
                        for a in (data.get("agents") or [])
                        if isinstance(a, dict)
                    ],
                )
            )
            _output(_connection, i18n.t("cmd.agents.title"))
            _output(_connection, i18n.t("cmd.agents.body",
                seats=seats, used=used, roster=roster or i18n.t("cmd.agents.empty")))
            return

        if second is not None:
            sim_id = int(str(first).strip())
            freq = float(str(second).strip())
            assign_seat(sim_dict, sim_id=sim_id, impulse_frequency=freq)
            _output(_connection, i18n.t("cmd.agents.freq", sim_id=sim_id, freq=freq))
        else:
            seats = int(str(first).strip())
            assign_seat(sim_dict, seats=seats)
            _output(_connection, i18n.t("cmd.agents.seats", seats=seats))
    except (SidecarUnreachable, SidecarError):
        _output(_connection, i18n.t("cmd.agents.unavailable"))
    except (TypeError, ValueError):
        _output(_connection, i18n.t("error.bad_request"))
    except Exception:
        _output(_connection, i18n.t("error.internal"))


@sims4.commands.Command("sw.probe", command_type=sims4.commands.CommandType.Live)
def cmd_probe(_connection=None) -> None:
    """Dump the active Sim's autonomy surface to sensewright_output.log (dev)."""
    _note_player_active()
    try:
        from . import probe

        sim_info = _get_sim_info()
        data = probe.dump_probe(sim_info)
        sim_id = (data.get("sim") or {}).get("sim_id")
        _output(_connection, i18n.t("cmd.probe.done", sim_id=sim_id if sim_id is not None else "?"))
    except Exception as e:
        _log_exception("sw.probe", e)
        _output(_connection, i18n.t("error.internal"))


@sims4.commands.Command("sw.start", command_type=sims4.commands.CommandType.Live)
def cmd_start(_connection=None) -> None:
    """Manually start the sidecar (packaged exe, or source as a fallback)."""
    _note_player_active()
    started, _ = _spawn_sidecar()
    if started:
        _output(_connection, i18n.t("notify.sidecar_starting"))
    else:
        _output(_connection, i18n.t("notify.sidecar_unreachable"))


# Auto-boot function (called from __init__.py)
def autoboot() -> None:
    """
    Best-effort sidecar autoboot.
    Pings health endpoint; if unreachable, spawns the sidecar exe.
    Never blocks, never raises.
    """
    try:
        # Quick health check
        health_data = health()
        if health_data.get("ok", False):
            # Sidecar already running (spawned earlier/manually): arm its
            # game-process watchdog so it still exits when this game session ends.
            try:
                import os

                attach_lifecycle(os.getpid())
            except Exception:
                pass
            show_simple_notification(i18n.t("notify.sidecar_ready", url=get_base_url()))
            return
    except (SidecarUnreachable, SidecarError):
        pass
    except Exception:
        pass

    # Try to spawn: packaged exe first, bundled source otherwise.
    started, _ = _spawn_sidecar()
    if started:
        show_simple_notification(i18n.t("notify.sidecar_starting"))
    else:
        show_simple_notification(i18n.t("notify.sidecar_unreachable"))