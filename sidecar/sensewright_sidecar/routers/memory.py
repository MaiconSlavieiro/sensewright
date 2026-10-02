"""Memory / profile / seats endpoints."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Query

from ..schemas import sanitize_payload
from ..services import (
    handle_consolidate, handle_diary_get, handle_evolve, handle_profile,
    handle_seats_get, handle_seats_post,
)

router = APIRouter(prefix="/v1", tags=["memory"])


@router.post("/profile")
def profile(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_profile(sanitize_payload(payload))


@router.post("/evolve")
def evolve(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_evolve(sanitize_payload(payload))


@router.post("/memory/consolidate")
def memory_consolidate(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_consolidate(sanitize_payload(payload))


@router.get("/memory/diary")
def memory_diary_get(sim_id: int = Query(default=0)) -> Dict[str, Any]:
    return handle_diary_get({"sim_id": sim_id})


@router.post("/memory/diary")
def memory_diary_post(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_diary_get(sanitize_payload(payload))


@router.get("/agency/seats")
def seats_get() -> Dict[str, Any]:
    return handle_seats_get()


@router.post("/agency/seats")
def seats_post(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_seats_post(sanitize_payload(payload))
