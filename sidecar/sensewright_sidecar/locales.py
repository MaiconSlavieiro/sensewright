"""Tiny locale helper for sidecar-internal diagnostic text.

This is NOT for player-facing text (that uses message_key/message_args via the
mod). This is only for sidecar logs, CLI output, and internal diagnostics. All
diagnostic strings live in the ``sys.*`` keys of :mod:`content_i18n`.
"""

from __future__ import annotations

from . import content_i18n


def t(lang: str, key: str, **args: object) -> str:
    """Translate a ``sys.*`` diagnostic key with default-locale fallback.

    Unknown keys return the key itself. Formatting errors return the raw
    template. Never raises.
    """
    if not key.startswith("sys."):
        key = f"sys.{key}"
    return content_i18n.t(lang, key, **args)
