"""Event ingestion endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sensewright_sidecar.routers.deps import require_auth
from sensewright_sidecar.schemas import AckResponse, EventIngestRequest

router = APIRouter()


@router.post("/events", response_model=AckResponse)
async def ingest_events(
    req: EventIngestRequest,
    _auth: None = Depends(require_auth),
) -> AckResponse:
    """Receive a batch of events from the mod."""
    try:
        from sensewright_sidecar.agent import graph as agent_graph
        await agent_graph.ingest_events(req.events)
    except Exception:
        # Best effort, still return ok
        pass
    return AckResponse(ok=True)
