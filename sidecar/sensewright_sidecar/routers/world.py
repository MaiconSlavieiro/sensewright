"""World Layer endpoints (neighborhood chronicles + rumors)."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Query

from ..schemas import sanitize_payload
from ..services import handle_neighborhood

router = APIRouter(prefix="/v1/world", tags=["world"])


@router.get("/neighborhood")
def neighborhood_get(
    save_id: int = Query(default=0),
    sim_id: int = Query(default=0),
) -> Dict[str, Any]:
    return handle_neighborhood({"save_id": save_id, "sim_id": sim_id})


@router.post("/neighborhood")
def neighborhood_post(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_neighborhood(sanitize_payload(payload))
