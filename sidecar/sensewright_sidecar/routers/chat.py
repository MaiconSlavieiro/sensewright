"""Chat endpoints (chat + hey alias)."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body

from ..schemas import sanitize_payload
from ..services import handle_chat

router = APIRouter(prefix="/v1", tags=["chat"])


@router.post("/chat")
def chat(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_chat(sanitize_payload(payload))


@router.post("/hey")
def hey(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    payload = sanitize_payload(payload)
    payload.setdefault("channel", "phone_sms")
    return handle_chat(payload)
