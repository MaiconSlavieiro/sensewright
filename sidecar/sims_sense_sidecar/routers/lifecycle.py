"""Lifecycle endpoints: arm the game-process watchdog at runtime.

The sidecar normally learns the game PID through ``SIMS_SENSE_GAME_PID`` when the
mod spawns it. When a sidecar is already running (started manually or by a
previous session), the mod calls ``POST /v1/lifecycle/attach`` so the sidecar
still exits when the game closes. Best-effort: a missing watchdog never 500s.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from sims_sense_sidecar.routers.deps import require_auth
from sims_sense_sidecar.schemas import LifecycleAttachRequest, LifecycleResponse

router = APIRouter()


@router.post("/lifecycle/attach", response_model=LifecycleResponse)
async def lifecycle_attach(
    req: LifecycleAttachRequest,
    request: Request,
    _auth: None = Depends(require_auth),
) -> LifecycleResponse:
    """Arm the watchdog on the caller's game PID so the sidecar exits with it."""
    watcher = getattr(request.app.state, "game_watcher", None)
    if watcher is None:
        return LifecycleResponse(ok=False, watching=False)
    try:
        attached = watcher.attach(req.pid)
    except Exception:
        return LifecycleResponse(ok=False, watching=False)
    snap = watcher.snapshot()
    return LifecycleResponse(ok=bool(attached), watching=bool(snap.get("running")), pid=snap.get("pid"))
