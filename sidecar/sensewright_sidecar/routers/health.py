"""Health, status and player-activity endpoints."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body

from ..schemas import sanitize_payload
from ..services import (
    handle_config_panic, handle_config_resume, handle_panel_summary,
    handle_player_activity, handle_provider_config, handle_recap_get, health, status,
)

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


@router.get("/recap")
def recap() -> Dict[str, Any]:
    return handle_recap_get()


@router.get("/panel/summary")
def panel_summary() -> Dict[str, Any]:
    return handle_panel_summary()


@router.post("/config/provider")
def config_provider(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_provider_config(sanitize_payload(payload))


@router.post("/config/panic")
def config_panic(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_config_panic(sanitize_payload(payload))


@router.post("/config/resume")
def config_resume(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_config_resume(sanitize_payload(payload))
