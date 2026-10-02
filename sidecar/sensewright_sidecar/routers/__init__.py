"""Routers package — aggregates all /v1 API routers."""
from __future__ import annotations

from fastapi import APIRouter

from .autonomy import router as autonomy_router
from .chat import router as chat_router
from .events import router as events_router
from .god import router as god_router
from .health import router as health_router
from .i18n import router as i18n_router
from .lifecycle import router as lifecycle_router
from .memory import router as memory_router

api_router = APIRouter()
api_router.include_router(lifecycle_router)
api_router.include_router(autonomy_router)
api_router.include_router(chat_router)
api_router.include_router(events_router)
api_router.include_router(god_router)
api_router.include_router(memory_router)
api_router.include_router(health_router)
api_router.include_router(i18n_router)
