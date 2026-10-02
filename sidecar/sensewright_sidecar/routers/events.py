"""Events endpoint."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body

from ..schemas import sanitize_payload
from ..services import handle_event

router = APIRouter(prefix="/v1", tags=["events"])


@router.post("/events")
def events(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_event(sanitize_payload(payload))
