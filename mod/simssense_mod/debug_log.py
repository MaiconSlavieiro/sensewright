"""
Shared best-effort diagnostic logging for SimsSense.

Writes to ``simssense_output.log`` next to the mod (the same file the command
layer uses). Never raises, never blocks and stays silent outside the game.

The ``_safe_call``/``_safe_getattr`` guards swallow game-API exceptions to keep
The Sims 4 stable (best-effort contract); ``log_exception`` records the real
exception with its traceback so those failures remain diagnosable (code review
items 1 and 5).

``validation_log`` writes the semantic decisions that are otherwise invisible
(which intent/tool ran, seat sync, etc.) so an in-game session can be validated
from the log alone. It is gated by ``VALIDATION_MODE`` (``SIMS_SENSE_VALIDATION``,
on by default) and can be muted without touching the error logging.
"""


import io
import os
import traceback
from typing import Set

from .config import mod_root

# Cap the debug log so long play sessions cannot grow it without bound. When the
# file exceeds the cap it is rotated (the tail is kept), instead of silently
# stopping, so a late ``ai.probe`` dump is never lost.
DEBUG_LOG_MAX_BYTES = 1048576  # 1 MB

# Exception logging is on by default so swallowed game-API errors are diagnosable.
# Override with SIMS_SENSE_DEBUG=0/false/no/off to mute it.
DEBUG_MODE = True
try:
    _env = os.environ.get("SIMS_SENSE_DEBUG")
    if _env is not None:
        DEBUG_MODE = _env.strip().lower() not in ("", "0", "false", "no", "off")
except Exception:
    pass

# Validation logging records the semantic decisions (intent/tool execution, seat
# sync, …). On by default for the live-validation pass; mute with
# SIMS_SENSE_VALIDATION=0/false/no/off once the mod is trusted.
VALIDATION_MODE = True
try:
    _env = os.environ.get("SIMS_SENSE_VALIDATION")
    if _env is not None:
        VALIDATION_MODE = _env.strip().lower() not in ("", "0", "false", "no", "off")
except Exception:
    pass

# Signatures already logged this session (de-duplication).
_seen_signatures: Set[str] = set()


def _rotate_if_needed(path: str) -> None:
    """Keep the log bounded: when over the cap, retain only the tail."""
    try:
        if not os.path.exists(path):
            return
        if os.path.getsize(path) <= DEBUG_LOG_MAX_BYTES:
            return
        with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
            data = fh.read()
        keep = data[-(DEBUG_LOG_MAX_BYTES // 2):]
        with io.open(path, "w", encoding="utf-8") as fh:
            fh.write("... [log truncated] ...\n" + keep)
    except Exception:
        pass


def debug_log(message) -> None:
    """Append a diagnostic line to ``simssense_output.log``. Never raises."""
    try:
        root = mod_root()
        if not root:
            return
        path = os.path.join(root, "simssense_output.log")
        _rotate_if_needed(path)
        with io.open(path, "a", encoding="utf-8") as fh:
            fh.write(str(message) + "\n")
    except Exception:
        pass


def validation_log(message) -> None:
    """Log a semantic validation line (gated by ``VALIDATION_MODE``). Never raises."""
    if not VALIDATION_MODE:
        return
    debug_log("[validate] " + str(message))


def log_exception(where, exc) -> None:
    """Record the real exception (type + traceback) to the debug log.

    Gated by ``DEBUG_MODE`` and logged once per unique ``(where, exc)``
    signature. Never raises.
    """
    if not DEBUG_MODE:
        return
    try:
        signature = "{}|{}|{}".format(where, type(exc).__name__, exc)
        if signature in _seen_signatures:
            return
        _seen_signatures.add(signature)
    except Exception:
        pass
    try:
        debug_log("{} exception: {!r}\n{}".format(where, exc, traceback.format_exc()))
    except Exception:
        pass


def safe_getattr(obj, attr, default=None):
    """Best-effort ``getattr`` that logs (once) instead of swallowing.

    The shared guard for game-API reads: returns ``default`` on any exception
    and records the real error via :func:`log_exception` (code review item H5).
    Never raises.
    """
    try:
        return getattr(obj, attr, default)
    except Exception as exc:
        log_exception("safe_getattr({!r})".format(attr), exc)
        return default


def safe_call(func, *args, **kwargs):
    """Best-effort ``func(*args, **kwargs)`` that logs (once) on failure.

    Returns ``None`` when the call raises; the real exception is recorded via
    :func:`log_exception`. Never raises (code review items H5/L2).
    """
    try:
        return func(*args, **kwargs)
    except Exception as exc:
        log_exception(
            "safe_call({!r})".format(getattr(func, "__name__", func)), exc)
        return None
