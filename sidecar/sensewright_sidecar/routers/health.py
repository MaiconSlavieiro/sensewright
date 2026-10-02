"""Health, status and player-activity endpoints."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body

from ..schemas import sanitize_payload
from ..services import handle_player_activity, health, status

router = APIRouter(prefix="/v1", tags=["health"])


@router.get("/health")
def health_endpoint() -> Dict[str, Any]:
    return health()


@router.get("/status")
def status_endpoint() -> Dict[str, Any]:
    return status()


@router.post("/config/player-activity")
def player_activity(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_player_activity(sanitize_payload(payload))
