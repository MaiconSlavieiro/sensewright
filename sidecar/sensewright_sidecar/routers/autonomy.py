"""Autonomous Sim-agent endpoints (PLANO.md §14.2, v0.2 A2).

The mod pushes a fire-and-forget zone pulse (``/v1/autonomy/tick``) and later
pulls the pending per-Sim directives (``/v1/autonomy/directives``) to execute
them locally. Handlers are defensive: a missing/unconfigured agent graph must
never surface a 500.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sensewright_sidecar.routers.deps import require_auth
from sensewright_sidecar.schemas import (
    AutonomyTickRequest,
    AutonomyTickResponse,
    DirectivesResponse,
    IntentResponse,
    RosterResponse,
    SeatAssignRequest,
    SeatInfo,
    SocialDialogue,
)

router = APIRouter()


def _agent_graph():
    """Import the agent graph lazily so a missing module cannot break startup."""
    from sensewright_sidecar.agent import graph as agent_graph

    return agent_graph


@router.post("/autonomy/tick", response_model=AutonomyTickResponse)
async def autonomy_tick(
    req: AutonomyTickRequest,
    _auth: None = Depends(require_auth),
) -> AutonomyTickResponse:
    """Ingest a zone pulse and schedule zero or more per-Sim impulses."""
    try:
        result = await _agent_graph().ingest_autonomy_tick(req)
        if isinstance(result, dict) and result.get("ok", True):
            social = [
                SocialDialogue(**(dialogue or {}))
                for dialogue in (result.get("social") or [])
                if isinstance(dialogue, dict)
            ]
            return AutonomyTickResponse(
                ok=True,
                scheduled=int(result.get("scheduled", 0) or 0),
                sleeping=list(result.get("sleeping") or []),
                social=social,
                message_key=result.get("message_key"),
            )
    except Exception:
        pass
    return AutonomyTickResponse(ok=False, scheduled=0, sleeping=[])


@router.get("/autonomy/directives", response_model=DirectivesResponse)
async def autonomy_directives(
    save_id: str,
    player_id: str = "local",
    sim_id: int | None = None,
    limit: int = 20,
    _auth: None = Depends(require_auth),
) -> DirectivesResponse:
    """Pull the pending per-Sim directives for the mod to execute (alias)."""
    try:
        result = await _agent_graph().pull_directives(
            player_id=player_id,
            save_id=save_id,
            sim_id=sim_id,
            limit=limit,
        )
        if isinstance(result, dict) and result.get("ok", True):
            return DirectivesResponse(
                ok=True,
                directives=list(result.get("directives") or []),
                message_key=result.get("message_key"),
            )
    except Exception:
        pass
    return DirectivesResponse(ok=False, directives=[])


@router.get("/autonomy/intents", response_model=IntentResponse)
async def autonomy_intents(
    save_id: str,
    player_id: str = "local",
    sim_id: int | None = None,
    limit: int = 20,
    _auth: None = Depends(require_auth),
) -> IntentResponse:
    """Pull the pending per-Sim intents for the mod's GameLever (v0.3 R3)."""
    try:
        result = await _agent_graph().pull_intents(
            player_id=player_id,
            save_id=save_id,
            sim_id=sim_id,
            limit=limit,
        )
        if isinstance(result, dict) and result.get("ok", True):
            return IntentResponse(
                ok=True,
                intents=list(result.get("intents") or []),
                message_key=result.get("message_key"),
            )
    except Exception:
        pass
    return IntentResponse(ok=False, intents=[])


@router.get("/agency/seats", response_model=RosterResponse)
async def agency_seats(
    save_id: str,
    player_id: str = "local",
    _auth: None = Depends(require_auth),
) -> RosterResponse:
    """Return the live agent-roster (seat occupancy) for a save (v0.3 R2)."""
    try:
        result = _agent_graph().seats_roster(save_id, player_id)
        if isinstance(result, dict) and result.get("ok", True):
            agents = [SeatInfo(**(a or {})) for a in (result.get("agents") or [])]
            return RosterResponse(
                ok=True,
                save_id=str(result.get("save_id", save_id)),
                seats=int(result.get("seats", 0) or 0),
                used=int(result.get("used", 0) or 0),
                agents=agents,
            )
    except Exception:
        pass
    return RosterResponse(ok=False, save_id=save_id)


@router.post("/agency/seats", response_model=RosterResponse)
async def assign_agency_seat(
    req: SeatAssignRequest,
    _auth: None = Depends(require_auth),
) -> RosterResponse:
    """Resize the seat pool and/or set a per-Sim impulse frequency (v0.3 R2/R7)."""
    try:
        result = _agent_graph().assign_seat(
            req.sim.save_id,
            req.sim.player_id,
            seats=req.seats,
            sim_id=req.sim_id,
            impulse_frequency=req.impulse_frequency,
        )
        if isinstance(result, dict) and result.get("ok", True):
            agents = [SeatInfo(**(a or {})) for a in (result.get("agents") or [])]
            return RosterResponse(
                ok=True,
                save_id=str(result.get("save_id", req.sim.save_id)),
                seats=int(result.get("seats", 0) or 0),
                used=int(result.get("used", 0) or 0),
                agents=agents,
            )
    except Exception:
        pass
    return RosterResponse(ok=False, save_id=req.sim.save_id)
