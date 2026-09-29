"""God-agent endpoints: zeitgeist, backgrounds, controls, census.

Every handler is defensive: the ``agent_graph`` functions are implemented by a
separate workstream, and the HTTP layer must never surface a 500 when that
subsystem is missing or unconfigured. On failure each endpoint answers with a
safe (``ok=False``/empty) default.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sensewright_sidecar.god.controls import controls_payload, merge_with_defaults
from sensewright_sidecar.routers.deps import require_auth
from sensewright_sidecar.schemas import (
    AggregatesResponse,
    BackgroundRequest,
    BackgroundResponse,
    CensusRequest,
    CensusResponse,
    ControlsResponse,
    GodTickRequest,
    GodTickResponse,
    NeighborhoodAggregates,
    Zeitgeist,
    ZeitgeistRequest,
    ZeitgeistResponse,
    ZeitgeistSuggestRequest,
    ZeitgeistSuggestResponse,
)

router = APIRouter()

_ZEITGEIST_FIELDS = (
    "mood_tags",
    "free_text",
    "rewritten_text",
    "mood_influence",
    "configured",
    "updated_at",
)


def _agent_graph():
    """Import the agent graph lazily so a missing module cannot break startup."""
    from sensewright_sidecar.agent import graph as agent_graph

    return agent_graph


def _coerce_zeitgeist(value: object) -> Zeitgeist:
    """Best-effort conversion of an agent payload into a ``Zeitgeist``."""
    if isinstance(value, Zeitgeist):
        return value
    if isinstance(value, dict):
        data = {key: value[key] for key in _ZEITGEIST_FIELDS if key in value}
        try:
            return Zeitgeist(**data)
        except Exception:
            return Zeitgeist(configured=False)
    return Zeitgeist(configured=False)


@router.get("/god/zeitgeist", response_model=ZeitgeistResponse)
async def get_god_zeitgeist(
    save_id: str,
    player_id: str = "local",
    _auth: None = Depends(require_auth),
) -> ZeitgeistResponse:
    """Return the neighborhood zeitgeist for a save."""
    try:
        result = await _agent_graph().get_zeitgeist(save_id, player_id)
        if isinstance(result, dict):
            zeitgeist = _coerce_zeitgeist(result.get("zeitgeist"))
            return ZeitgeistResponse(ok=bool(result.get("ok", True)), zeitgeist=zeitgeist)
    except Exception:
        pass
    return ZeitgeistResponse(ok=False, zeitgeist=Zeitgeist(configured=False))


@router.post("/god/zeitgeist", response_model=ZeitgeistResponse)
async def set_god_zeitgeist(
    req: ZeitgeistRequest,
    _auth: None = Depends(require_auth),
) -> ZeitgeistResponse:
    """Persist the neighborhood zeitgeist."""
    try:
        result = await _agent_graph().set_zeitgeist(
            req.sim,
            req.mood_tags,
            req.free_text,
            req.mood_influence,
            req.lang,
        )
        if isinstance(result, dict) and result.get("ok", True):
            if result.get("zeitgeist") is not None:
                zeitgeist = _coerce_zeitgeist(result.get("zeitgeist"))
            else:
                zeitgeist = Zeitgeist(
                    mood_tags=req.mood_tags,
                    free_text=req.free_text,
                    mood_influence=req.mood_influence,
                    configured=True,
                )
            return ZeitgeistResponse(ok=True, zeitgeist=zeitgeist)
    except Exception:
        pass
    return ZeitgeistResponse(ok=False, zeitgeist=Zeitgeist(configured=False))


@router.post("/god/zeitgeist/suggest", response_model=ZeitgeistSuggestResponse)
async def suggest_god_zeitgeist(
    req: ZeitgeistSuggestRequest,
    _auth: None = Depends(require_auth),
) -> ZeitgeistSuggestResponse:
    """Ask the LLM to propose a zeitgeist rewrite."""
    try:
        result = await _agent_graph().suggest_zeitgeist(
            req.sim,
            req.mood_tags,
            req.free_text,
            req.lang,
        )
        if isinstance(result, dict) and result.get("ok", True):
            return ZeitgeistSuggestResponse(
                ok=True,
                suggested_text=str(result.get("suggested_text", "") or ""),
                mood_tags=list(result.get("mood_tags") or []),
                provider=result.get("provider"),
                message_key=result.get("message_key"),
            )
    except Exception:
        pass
    return ZeitgeistSuggestResponse(ok=False, suggested_text="", mood_tags=[])


@router.post("/god/background", response_model=BackgroundResponse)
async def god_background(
    req: BackgroundRequest,
    _auth: None = Depends(require_auth),
) -> BackgroundResponse:
    """Generate a background story for a sim or household."""
    try:
        result = await _agent_graph().generate_background(req)
        if isinstance(result, dict) and result.get("ok", True):
            background = result.get("background")
            return BackgroundResponse(
                ok=True,
                scope=str(result.get("scope", req.scope)),
                sim_id=int(result.get("sim_id", req.sim.sim_id)),
                household_id=result.get("household_id", req.household_id),
                background=background if isinstance(background, dict) else {},
                cached=bool(result.get("cached", False)),
                provider=result.get("provider"),
                message_key=result.get("message_key"),
            )
    except Exception:
        pass
    return BackgroundResponse(
        ok=False,
        scope=req.scope,
        sim_id=req.sim.sim_id,
        household_id=req.household_id,
    )


@router.get("/god/controls", response_model=ControlsResponse)
async def god_controls(
    include_advanced: bool = True,
    _auth: None = Depends(require_auth),
) -> ControlsResponse:
    """Return the ControlSpec registry and current values.

    Falls back to the local registry (which needs no agent) when the agent
    graph is unconfigured.
    """
    try:
        result = _agent_graph().god_controls()
        if isinstance(result, dict) and result.get("controls"):
            values = result.get("values") or merge_with_defaults(None)
            return ControlsResponse(
                ok=bool(result.get("ok", True)),
                controls=list(result["controls"]),
                values=values,
            )
    except Exception:
        pass
    return ControlsResponse(
        ok=True,
        controls=controls_payload(include_advanced),
        values=merge_with_defaults(None),
    )


@router.post("/census", response_model=CensusResponse)
async def god_census(
    req: CensusRequest,
    _auth: None = Depends(require_auth),
) -> CensusResponse:
    """Ingest a sim/household census snapshot."""
    try:
        result = await _agent_graph().ingest_census(req)
        if isinstance(result, dict) and result.get("ok", True):
            return CensusResponse(
                ok=True,
                sims=int(result.get("sims", 0) or 0),
                households=int(result.get("households", 0) or 0),
                queued=int(result.get("queued", 0) or 0),
                message_key=result.get("message_key"),
            )
    except Exception:
        pass
    return CensusResponse(ok=False, sims=0, households=0)


@router.post("/god/tick", response_model=GodTickResponse)
async def god_tick(
    req: GodTickRequest,
    _auth: None = Depends(require_auth),
) -> GodTickResponse:
    """Run one God-orchestration tick and return the issued directives."""
    try:
        result = await _agent_graph().god_tick(req)
        if isinstance(result, dict) and result.get("ok", True):
            return GodTickResponse(
                ok=True,
                enabled=bool(result.get("enabled", False)),
                preset=str(result.get("preset", "")),
                directives=list(result.get("directives") or []),
                message_key=result.get("message_key"),
            )
    except Exception:
        pass
    return GodTickResponse(ok=False, enabled=False, preset="", directives=[])


@router.get("/god/aggregates", response_model=AggregatesResponse)
async def god_aggregates(
    save_id: str,
    player_id: str = "local",
    _auth: None = Depends(require_auth),
) -> AggregatesResponse:
    """Return the aggregated neighborhood state the God may read (v0.2 G1).

    Deliberately excludes any played Sim's psyche/secrets: only public
    aggregates (population, mood distribution, tension, funds).
    """
    try:
        result = _agent_graph().god_aggregates(save_id, player_id)
        if isinstance(result, dict) and result.get("ok", True):
            neighborhood = result.get("neighborhood")
            return AggregatesResponse(
                ok=True,
                save_id=str(result.get("save_id", save_id)),
                neighborhood=NeighborhoodAggregates(**(neighborhood or {})),
            )
    except Exception:
        pass
    return AggregatesResponse(ok=False, save_id=save_id)
