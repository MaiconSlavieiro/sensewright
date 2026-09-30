"""Chat and tool result endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from sensewright_sidecar.routers.deps import require_auth
from sensewright_sidecar.schemas import (
    AckResponse,
    ChatRequest,
    ChatResponse,
    HeyRequest,
    ToolResultRequest,
    normalize_lang,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _error_response(lang: str, detail: str = "") -> ChatResponse:
    """Build a standardized in-character error response."""
    return ChatResponse(
        reply="",
        tool_calls=[],
        provider=None,
        model=None,
        in_character_error=True,
        message_key="error.internal",
        message_args={"detail": detail},
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    _auth: None = Depends(require_auth),
) -> ChatResponse:
    """Handle a chat message from the mod."""
    lang = normalize_lang(req.lang)
    logger.info(
        "chat request lang=%s sim=%s save=%s",
        lang,
        getattr(req.sim, "sim_id", None),
        getattr(req.sim, "save_id", None),
    )

    try:
        from sensewright_sidecar.agent import graph as agent_graph
    except Exception as e:
        return _error_response(lang, f"agent import failed: {e}")

    try:
        return await agent_graph.handle_chat(req)
    except Exception as e:
        return _error_response(lang, str(e))


@router.post("/hey", response_model=ChatResponse)
async def hey(
    req: HeyRequest,
    _auth: None = Depends(require_auth),
) -> ChatResponse:
    """Handle a 'hey' (proactive) request from the mod."""
    lang = normalize_lang(req.lang)
    logger.info(
        "hey request lang=%s sim=%s save=%s",
        lang,
        getattr(req.sim, "sim_id", None),
        getattr(req.sim, "save_id", None),
    )

    try:
        from sensewright_sidecar.agent import graph as agent_graph
    except Exception as e:
        return _error_response(lang, f"agent import failed: {e}")

    try:
        return await agent_graph.handle_hey(req)
    except Exception as e:
        return _error_response(lang, str(e))


@router.post("/tools/result", response_model=AckResponse)
async def tool_result(
    req: ToolResultRequest,
    _auth: None = Depends(require_auth),
) -> AckResponse:
    """Receive a tool execution result from the mod."""
    try:
        from sensewright_sidecar.agent import graph as agent_graph
        await agent_graph.handle_tool_result(req)
    except Exception:
        # Always return ok=true per contract
        pass
    return AckResponse(ok=True)