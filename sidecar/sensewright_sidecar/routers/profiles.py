"""Profile generation and evolution endpoints (Phases 3 & 4).

Both handlers are defensive: the agent graph may be unconfigured, so the HTTP
layer answers with a safe (``ok=False``) default instead of a 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sensewright_sidecar.routers.deps import require_auth
from sensewright_sidecar.schemas import (
    EvolveRequest,
    EvolveResponse,
    ProfileRequest,
    ProfileResponse,
)

router = APIRouter()


def _agent_graph():
    from sensewright_sidecar.agent import graph as agent_graph

    return agent_graph


@router.post("/profile", response_model=ProfileResponse)
async def generate_profile(
    req: ProfileRequest,
    _auth: None = Depends(require_auth),
) -> ProfileResponse:
    """Generate (or return a cached) structured profile for a Sim."""
    try:
        result = await _agent_graph().generate_profile(req)
        if isinstance(result, dict) and result.get("ok", True):
            return ProfileResponse(
                ok=True,
                sim_id=int(result.get("sim_id", req.sim.sim_id)),
                profile=result.get("profile") or {},
                provider=result.get("provider"),
                cached=bool(result.get("cached", False)),
                message_key=result.get("message_key"),
            )
    except Exception:
        pass
    return ProfileResponse(ok=False, sim_id=req.sim.sim_id)


@router.post("/evolve", response_model=EvolveResponse)
async def evolve(
    req: EvolveRequest,
    _auth: None = Depends(require_auth),
) -> EvolveResponse:
    """Run the reflection/evolution loop for a Sim or a whole save."""
    try:
        result = await _agent_graph().evolve(req)
        if isinstance(result, dict):
            return EvolveResponse(
                ok=bool(result.get("ok", True)),
                scope=str(result.get("scope", req.scope)),
                reflected=int(result.get("reflected", 0) or 0),
                skipped=int(result.get("skipped", 0) or 0),
                results=list(result.get("results") or []),
                message_key=result.get("message_key"),
            )
    except Exception:
        pass
    return EvolveResponse(ok=False, scope=req.scope)
