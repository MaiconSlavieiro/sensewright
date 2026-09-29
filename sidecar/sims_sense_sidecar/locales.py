"""Tiny locale helper for sidecar-internal diagnostic text.

This is NOT for player-facing text (that uses message_key/message_args via the mod).
This is only for sidecar logs, CLI output, and internal diagnostics.
"""

from __future__ import annotations

_EN = {
    "error.internal": "Internal error: {detail}",
    "error.agent_unavailable": "Agent module not available",
    "error.config_invalid": "Invalid configuration: {detail}",
    "startup.banner": "SimsSense sidecar v{version} starting on {host}:{port}",
    "startup.token": "Token written to {path}",
    "shutdown.banner": "SimsSense sidecar shutting down",
    "health.ok": "OK",
}

_PT_BR = {
    "error.internal": "Erro interno: {detail}",
    "error.agent_unavailable": "Módulo do agente não disponível",
    "error.config_invalid": "Configuração inválida: {detail}",
    "startup.banner": "SimsSense sidecar v{version} iniciando em {host}:{port}",
    "startup.token": "Token salvo em {path}",
    "shutdown.banner": "SimsSense sidecar desligando",
    "health.ok": "OK",
}

_LOCALES = {
    "en": _EN,
    "pt-BR": _PT_BR,
}


def t(lang: str, key: str, **args: object) -> str:
    """Translate a key for the given language with EN fallback.

    Unknown keys return the key itself. Formatting errors return the raw template.
    """
    locale = _LOCALES.get(lang) or _LOCALES["en"]
    template = locale.get(key, _LOCALES["en"].get(key, key))
    try:
        return template.format(**args)
    except Exception:
        return template