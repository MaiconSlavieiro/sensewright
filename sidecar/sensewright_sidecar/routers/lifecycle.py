"""Lifecycle endpoints (attach, session-start, zone-transition, save)."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body

from ..schemas import sanitize_payload
from ..services import (
    handle_attach, handle_save, handle_session_start, handle_zone_transition,
)

router = APIRouter(prefix="/v1/lifecycle", tags=["lifecycle"])


@router.post("/attach")
def attach(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_attach(sanitize_payload(payload))


@router.post("/session-start")
def session_start(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_session_start(sanitize_payload(payload))


@router.post("/zone-transition")
def zone_transition(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_zone_transition(sanitize_payload(payload))


@router.post("/save")
def save(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_save(sanitize_payload(payload))
