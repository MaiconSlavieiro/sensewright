"""Shared-token auth + the ``runtime.json`` file.

The mod reads ``data/runtime.json`` (host/port/token/pid) to talk to the sidecar
without any user configuration. The token is generated on first boot and written
with restricted permissions (0600 where the OS allows).
"""

from __future__ import annotations

import json
import os
import secrets

from fastapi import Header, HTTPException, status

from . import __version__
from .config import Settings

TOKEN_HEADER = "X-SimsSense-Token"


def ensure_data_dir(settings: Settings) -> None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)


def _write_private(path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover - Windows/best-effort
        pass


def ensure_token(settings: Settings) -> str:
    """Return the existing persistent token, creating one if needed."""
    ensure_data_dir(settings)
    if settings.token_path.is_file():
        token = settings.token_path.read_text(encoding="utf-8").strip()
        if token:
            return token
    token = secrets.token_urlsafe(32)
    _write_private(settings.token_path, token)
    return token


def rotate_token(settings: Settings) -> str:
    ensure_data_dir(settings)
    token = secrets.token_urlsafe(32)
    _write_private(settings.token_path, token)
    return token


def write_runtime(settings: Settings, token: str) -> dict[str, object]:
    ensure_data_dir(settings)
    info: dict[str, object] = {
        "host": settings.network.host,
        "port": settings.network.port,
        "token": token,
        "pid": os.getpid(),
        "version": __version__,
        "lang": settings.lang,
    }
    _write_private(settings.runtime_path, json.dumps(info))
    return info


def remove_runtime(settings: Settings) -> None:
    try:
        settings.runtime_path.unlink()
    except OSError:
        pass


def tokens_match(expected: str, provided: str | None) -> bool:
    if not provided:
        return False
    return secrets.compare_digest(expected, provided)


def make_auth_dependency(settings: Settings, token: str):
    """Build the FastAPI dependency that validates the token header."""

    async def _require_token(
        x_simssense_token: str | None = Header(default=None, alias=TOKEN_HEADER),
    ) -> None:
        if not tokens_match(token, x_simssense_token):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing SimsSense token",
            )

    return _require_token
