"""Memory maintenance endpoints (manual consolidation from the pie menu).

The handler is defensive: the agent graph may be unconfigured, so the HTTP layer
answers with a safe (``ok=False``) default instead of a 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sensewright_sidecar.routers.deps import require_auth
from sensewright_sidecar.schemas import (
    MemoryConsolidateRequest,
    MemoryConsolidateResponse,
)

router = APIRouter()


def _agent_graph():
    from sensewright_sidecar.agent import graph as agent_graph

    return agent_graph


@router.post("/memory/consolidate", response_model=MemoryConsolidateResponse)
async def memory_consolidate(
    req: MemoryConsolidateRequest,
    _auth: None = Depends(require_auth),
) -> MemoryConsolidateResponse:
    """Fold a Sim's pending dialogue into one memory on demand.

    With ``queue=true`` the work is enqueued at top priority and the request
    returns immediately (``queued=true``); otherwise it runs synchronously.
    """
    try:
        graph = _agent_graph()
        if req.queue:
            result = await graph.enqueue_consolidate(req.sim, req.lang)
        else:
            result = await graph.consolidate_now(req.sim, req.lang)
        if isinstance(result, dict):
            return MemoryConsolidateResponse(
                ok=bool(result.get("ok", True)),
                consolidated=int(result.get("consolidated", 0) or 0),
                queued=bool(result.get("queued", False)),
                provider=result.get("provider"),
                message_key=result.get("message_key"),
                message_args=result.get("message_args") or {},
            )
    except Exception:
        pass
    return MemoryConsolidateResponse(ok=False)
