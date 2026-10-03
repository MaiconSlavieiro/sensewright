"""God Director endpoints."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body

from ..schemas import sanitize_payload
from ..services import (
    handle_arc_steer, handle_beat_ended, handle_controls_get, handle_controls_post,
    handle_direct_scene, handle_get_arc, handle_get_cast, handle_god_tick,
    handle_zeitgeist,
)

router = APIRouter(prefix="/v1/god", tags=["god"])


@router.post("/tick")
def god_tick(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_god_tick(sanitize_payload(payload))


@router.post("/direct-scene")
def direct_scene(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_direct_scene(sanitize_payload(payload))


@router.post("/arc/steer")
def arc_steer(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_arc_steer(sanitize_payload(payload))


@router.post("/beat-ended")
def beat_ended(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_beat_ended(sanitize_payload(payload))


@router.get("/controls")
def controls_get() -> Dict[str, Any]:
    return handle_controls_get()


@router.post("/controls")
def controls_post(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_controls_post(sanitize_payload(payload))


@router.post("/zeitgeist")
def zeitgeist(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_zeitgeist(sanitize_payload(payload))


@router.get("/arc")
def get_arc() -> Dict[str, Any]:
    return handle_get_arc()


@router.get("/cast")
def get_cast() -> Dict[str, Any]:
    return handle_get_cast()
