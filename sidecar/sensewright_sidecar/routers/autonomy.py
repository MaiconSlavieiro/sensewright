"""Autonomy + census endpoints."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body

from ..schemas import sanitize_payload
from ..services import handle_autonomy_tick, handle_census
from ..state import get_state

router = APIRouter(prefix="/v1", tags=["autonomy"])


@router.post("/census")
def census(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_census(sanitize_payload(payload))


@router.post("/autonomy/tick")
def autonomy_tick(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_autonomy_tick(sanitize_payload(payload))


@router.get("/autonomy/intents")
def autonomy_intents() -> Dict[str, Any]:
    return {"intents": get_state().drain_intents()}
