"""FastAPI dependencies for the sidecar routers."""

from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from sensewright_sidecar.auth import TOKEN_HEADER, tokens_match
from sensewright_sidecar.config import Settings


def get_settings(request: Request) -> Settings:
    """Retrieve the Settings instance from app state."""
    return request.app.state.settings


def get_token(request: Request) -> str:
    """Retrieve the auth token from app state."""
    return request.app.state.token


async def require_auth(
    request: Request,
    x_sensewright_token: str | None = Header(default=None, alias=TOKEN_HEADER),
) -> None:
    """Validate the token header using the token from app state."""
    token: str = request.app.state.token
    if not tokens_match(token, x_sensewright_token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing Sensewright token",
        )