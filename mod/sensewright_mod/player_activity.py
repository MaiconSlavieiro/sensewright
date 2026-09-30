"""
Player-activity detector (injection over the interaction API).

Wraps ``Sim.push_super_affordance`` so that whenever the **player** queues an
interaction (pie menu, a click, "Get to work"), the player-priority lock is
armed both locally (mod rails) and on the sidecar
(``POST /v1/config/player-activity``). This closes the
"player-activity detection signal" spike item (PLANO §2.3/§13): until now the
lock was only armed when the player typed a ``sw.*`` command, never when the
player clicked an interaction in the world.

Agent-issued pushes go through ``tool_executor._build_interaction_context``,
which sets the interaction source to ``SOURCE_SCRIPT``. Those are *not* player
actions and must not lock the agent out of its own Sim; the classifier below
only fires for the real player sources. When the source cannot be classified
the hook deliberately does **not** fire (safer than firing on every unknown
push, which would throttle the agent against itself).

Best-effort and never raises; a no-op outside The Sims 4. Adapted from
``dnavaria/sims4ai`` ``ai_sim_mod/interaction_subscriber.py`` (MIT).
"""


import threading

from .debug_log import debug_log, log_exception, safe_getattr


# InteractionSource members that represent a player-originated push. The names
# are stable across patches; missing members are simply skipped.
_USER_SOURCE_NAMES = ("USER", "PIE_MENU", "GET_TO_WORK")

_INSTALLED = {"value": False}
_LOCK = threading.Lock()


def _user_sources():
    """Return the set of player-originated ``InteractionSource`` members.

    Returns an empty set when the module/members are unavailable so callers can
    treat "unknown" as "do not fire".
    """
    try:
        from interactions.context import InteractionSource  # type: ignore
    except Exception:
        return set()
    sources = set()
    for name in _USER_SOURCE_NAMES:
        member = safe_getattr(InteractionSource, name, None)
        if member is not None:
            sources.add(member)
    return sources


def _is_player_push(context, user_sources):
    """Classify a push as player-originated.

    Unknown sources (no ``context``/``source`` or an empty ``user_sources``)
    return ``False``: the agent's own ``SOURCE_SCRIPT`` pushes must not arm the
    lock.
    """
    if not user_sources:
        return False
    source = safe_getattr(context, "source", None) if context is not None else None
    if source is None:
        return False
    try:
        return source in user_sources
    except Exception:
        return False


def _sim_ref(sim_info):
    """Build the wire ``SimRef`` for a SimInfo (matches the census keying)."""
    sim_id = 0
    try:
        sim_id = int(safe_getattr(sim_info, "id", 0) or 0)
    except (TypeError, ValueError):
        sim_id = 0
    save_id = ""
    try:
        from . import sim_context
        save_id = sim_context._get_save_id() or ""
    except Exception:
        save_id = ""
    if not isinstance(save_id, str):
        save_id = str(save_id)
    return {"player_id": "local", "save_id": save_id, "sim_id": sim_id}


def _on_player_action(sim_info):
    """Arm the player-priority lock locally and on the sidecar. Never raises."""
    sim_ref = _sim_ref(sim_info)
    if not sim_ref["sim_id"]:
        return
    try:
        from . import tool_executor
        tool_executor.record_player_activity(sim_ref["sim_id"])
    except Exception as exc:
        log_exception("player_activity.local_lock", exc)
    try:
        from . import state_collector
        state_collector.notify_player_activity(sim_ref)
    except Exception as exc:
        log_exception("player_activity.sidecar", exc)


def install():
    """Wrap ``Sim.push_super_affordance`` to detect player actions.

    Idempotent. Returns ``True`` when the hook is installed (or was already),
    ``False`` when the game API is unavailable. Never raises.
    """
    with _LOCK:
        if _INSTALLED["value"]:
            return True
        try:
            from sims.sim import Sim  # type: ignore
        except Exception:
            return False

        original = safe_getattr(Sim, "push_super_affordance", None)
        if original is None:
            debug_log("player_activity: Sim.push_super_affordance not found")
            return False
        if getattr(original, "_sensewright_player_hook", False):
            _INSTALLED["value"] = True
            return True

        user_sources = _user_sources()

        def _wrapped(self_sim, *args, **kwargs):
            try:
                context = args[2] if len(args) >= 3 else kwargs.get("context")
                if _is_player_push(context, user_sources):
                    sim_info = safe_getattr(self_sim, "sim_info", None)
                    if sim_info is not None:
                        _on_player_action(sim_info)
            except Exception as exc:
                log_exception("player_activity.hook", exc)
            return original(self_sim, *args, **kwargs)

        try:
            _wrapped._sensewright_player_hook = True
            Sim.push_super_affordance = _wrapped
            _INSTALLED["value"] = True
            debug_log("player_activity: player-activity hook installed")
            return True
        except Exception as exc:
            log_exception("player_activity.install", exc)
            return False


def is_installed():
    """Return whether the hook is currently installed."""
    return _INSTALLED["value"]


def reset_for_test():
    """Test-only helper: clear the installed flag so ``install()`` can rerun."""
    with _LOCK:
        _INSTALLED["value"] = False
