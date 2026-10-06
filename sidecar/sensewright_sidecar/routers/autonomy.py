"""Autonomy + census endpoints."""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict

from fastapi import APIRouter, Body, Request
from fastapi.responses import StreamingResponse

from ..schemas import sanitize_payload
from ..services import handle_action_outcomes, handle_autonomy_tick, handle_census
from ..state import get_state

router = APIRouter(prefix="/v1", tags=["autonomy"])

#: Poll interval for the SSE intent stream (seconds).
_STREAM_POLL_S = 0.5
#: Emit a keepalive comment every N idle polls (~5 s) so the mod's 15 s socket
#: timeout never fires on a healthy-but-idle stream.
_STREAM_KEEPALIVE_EVERY = 10


@router.post("/census")
def census(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_census(sanitize_payload(payload))


@router.post("/autonomy/tick")
def autonomy_tick(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_autonomy_tick(sanitize_payload(payload))


@router.post("/actions/outcomes")
def action_outcomes(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_action_outcomes(sanitize_payload(payload))


@router.get("/autonomy/intents")
def autonomy_intents() -> Dict[str, Any]:
    """Legacy pull transport — kept as the mod's fallback when SSE fails."""
    return {"intents": get_state().drain_intents()}


@router.get("/autonomy/stream")
async def autonomy_stream(request: Request) -> StreamingResponse:
    """Server-Sent Events intent stream (P1 — replaces idle polling).

    Emits ``data: {"intents": [...]}`` frames as soon as intents are queued and a
    ``: keepalive`` comment every ~5 s while idle. The disconnect check runs
    *before* draining so intents are never consumed by a dead connection.
    """

    async def event_generator() -> AsyncIterator[str]:
        state = get_state()
        idle_polls = 0
        while True:
            if await request.is_disconnected():
                break
            intents = state.drain_intents()
            if intents:
                idle_polls = 0
                yield "data: {}\n\n".format(json.dumps({"intents": intents}, ensure_ascii=False))
            else:
                idle_polls += 1
                if idle_polls >= _STREAM_KEEPALIVE_EVERY:
                    idle_polls = 0
                    yield ": keepalive\n\n"
            await asyncio.sleep(_STREAM_POLL_S)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )
