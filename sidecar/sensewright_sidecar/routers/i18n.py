"""i18n endpoints (config/lang, reload, compile-addon)."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body

from ..schemas import sanitize_payload
from ..services import handle_compile_addon, handle_config_lang

router = APIRouter(prefix="/v1", tags=["i18n"])


@router.post("/config/lang")
def config_lang(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_config_lang(sanitize_payload(payload))


@router.post("/i18n/reload")
def i18n_reload() -> Dict[str, Any]:
    from ..i18n_engine import get_engine
    get_engine().reload()
    return {"ok": True}


@router.post("/i18n/compile-addon")
def i18n_compile_addon(payload: Dict[str, Any] = Body(default={})) -> Dict[str, Any]:
    return handle_compile_addon(sanitize_payload(payload))
