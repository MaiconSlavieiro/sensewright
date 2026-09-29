"""Admin/config endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from sensewright_sidecar.config import Settings
from sensewright_sidecar.god.controls import (
    apply_values_to_agents_config,
    apply_values_to_god_config,
)
from sensewright_sidecar.routers.deps import get_settings, require_auth
from sensewright_sidecar.schemas import (
    AckResponse,
    AutonomyConfigRequest,
    GodConfigRequest,
    LangConfigRequest,
    PlayerActivityRequest,
    ResetRequest,
    normalize_lang,
)

router = APIRouter()


@router.post("/reset", response_model=AckResponse)
async def reset(
    req: ResetRequest,
    request: Request,
    _auth: None = Depends(require_auth),
) -> AckResponse:
    """Reset agent state for a scope."""
    try:
        from sensewright_sidecar.agent import graph as agent_graph
        await agent_graph.reset(req.scope, req.sim)
    except Exception:
        # Best effort, still return ok
        pass
    return AckResponse(ok=True)


@router.post("/config/autonomy", response_model=AckResponse)
async def config_autonomy(
    req: AutonomyConfigRequest,
    request: Request,
    _auth: None = Depends(require_auth),
) -> AckResponse:
    """Set autonomy level for a sim."""
    try:
        from sensewright_sidecar.agent import graph as agent_graph
        await agent_graph.set_autonomy(req.sim, req.level)
    except Exception:
        pass
    return AckResponse(ok=True)


@router.post("/config/lang", response_model=AckResponse)
async def config_lang(
    req: LangConfigRequest,
    request: Request,
    _auth: None = Depends(require_auth),
) -> AckResponse:
    """Update the active language."""
    settings: Settings = get_settings(request)
    lang = normalize_lang(req.lang)
    settings.lang = lang

    try:
        from sensewright_sidecar.agent import graph as agent_graph
        agent_graph.set_lang(lang)  # synchronous by contract
    except Exception:
        pass
    return AckResponse(ok=True)


@router.post("/config/player-activity", response_model=AckResponse)
async def player_activity(
    req: PlayerActivityRequest,
    _auth: None = Depends(require_auth),
) -> AckResponse:
    """Record player activity for a sim."""
    try:
        from sensewright_sidecar.agent import graph as agent_graph
        agent_graph.record_player_activity(req.sim)
    except Exception:
        # Best effort, still return ok
        pass
    return AckResponse(ok=True)


@router.post("/config/god", response_model=AckResponse)
async def config_god(
    req: GodConfigRequest,
    request: Request,
    _auth: None = Depends(require_auth),
) -> AckResponse:
    """Update god-mode configuration."""
    settings: Settings = get_settings(request)
    god = settings.god

    # Backward-compatible top-level fields.
    if req.preset is not None:
        god.preset = req.preset
    if req.enabled is not None:
        god.enabled = req.enabled
    if req.powers is not None:
        god.powers.update(req.powers)

    # ControlSpec-validated overrides: sliders plus free-form ``settings``.
    values: dict[str, Any] = {}
    for key in (
        "intervention_frequency",
        "intensity",
        "mood_influence",
        "autonomy_degree",
        "chaos_degree",
    ):
        value = getattr(req, key)
        if value is not None:
            values[key] = value
    if req.settings:
        values.update(req.settings)

    if values:
        try:
            patch = apply_values_to_god_config(values)
            agent_patch = apply_values_to_agents_config(values)
        except ValueError as exc:
            return AckResponse(ok=False, detail=str(exc))
        for key, value in patch.items():
            if key == "powers":
                god.powers.update(value)
            elif key == "settings":
                god.settings.update(value)
            else:
                setattr(god, key, value)
        _apply_agents_patch(settings.agents, agent_patch)
        if agent_patch:
            try:
                from sensewright_sidecar.agent import graph as agent_graph

                agent_graph.update_agents()
            except Exception:
                pass

    # Push the new dials to the live orchestrator (best effort).
    try:
        from sensewright_sidecar.agent import graph as agent_graph
        agent_graph.update_god()
    except Exception:
        pass

    return AckResponse(ok=True)


def _apply_agents_patch(agents, patch: dict[str, Any]) -> None:
    """Shallow-merge a validated agent-control patch into ``AgentsConfig``."""
    if not patch:
        return
    if "agent_seats" in patch:
        agents.agent_seats = int(patch["agent_seats"])
    initiative = patch.get("initiative") or {}
    for key, value in initiative.items():
        if hasattr(agents.initiative, key):
            setattr(agents.initiative, key, value)
    layers = patch.get("layers") or {}
    for key, value in layers.items():
        if hasattr(agents.layers, key):
            setattr(agents.layers, key, value)