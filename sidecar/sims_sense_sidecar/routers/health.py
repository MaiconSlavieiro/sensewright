"""Health and status endpoints."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, Request

from sims_sense_sidecar import __version__
from sims_sense_sidecar.config import Settings
from sims_sense_sidecar.routers.deps import get_settings, require_auth
from sims_sense_sidecar.schemas import HealthResponse, StatusResponse, normalize_lang

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health(request: Request) -> HealthResponse:
    """Public health check — no auth required."""
    settings: Settings = get_settings(request)
    start_time: float = request.app.state.start_time
    uptime = time.time() - start_time
    return HealthResponse(
        ok=True,
        version=__version__,
        uptime_s=uptime,
        lang=normalize_lang(settings.lang),
    )


@router.get("/status", response_model=StatusResponse)
async def status(
    request: Request,
    _auth: None = Depends(require_auth),
) -> StatusResponse:
    """Authenticated status with component health — never 500."""
    settings: Settings = get_settings(request)
    start_time: float = request.app.state.start_time
    uptime = time.time() - start_time

    # Lazy imports with graceful degradation (each subsystem is optional).
    agent_status: dict[str, Any] = {}
    try:
        from sims_sense_sidecar.agent import graph as agent_graph
        agent_status = agent_graph.status() or {}
    except Exception:
        pass

    # Flatten the registry/chain snapshot into a provider list + chain health.
    registry_status = agent_status.get("providers") or {}
    chain_health: dict[str, Any] = {}
    providers: list[dict[str, Any]] = []
    if isinstance(registry_status, dict):
        chain_health = registry_status.get("chain") or {}
        provider_map = chain_health.get("providers") if isinstance(chain_health, dict) else {}
        if isinstance(provider_map, dict):
            for name, info in provider_map.items():
                entry: dict[str, Any] = {"name": name}
                if isinstance(info, dict):
                    entry.update(info)
                else:
                    entry["info"] = info
                providers.append(entry)

    autonomy: dict[str, Any] = {}
    if agent_status:
        autonomy = {"default": agent_status.get("autonomy_default")}
    memory = agent_status.get("memory") or {}
    rails = agent_status.get("rails") or {}
    backgrounds = agent_status.get("backgrounds") or {}
    budget = agent_status.get("budget") or {}

    # God orchestrator status
    god: dict[str, Any] = {}
    try:
        from sims_sense_sidecar.god import orchestrator as god_orchestrator
        god = god_orchestrator.status()
    except Exception:
        pass

    return StatusResponse(
        ok=True,
        sidecar_version=__version__,
        uptime_s=uptime,
        lang=normalize_lang(settings.lang),
        providers=providers,
        chain_health=chain_health,
        autonomy=autonomy,
        memory=memory,
        god=god,
        rails=rails,
        backgrounds=backgrounds,
        budget=budget,
    )