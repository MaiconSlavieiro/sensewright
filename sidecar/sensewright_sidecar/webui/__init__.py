"""Sensewright Web Studio — local SPA served by the sidecar.

Exports a FastAPI APIRouter that mounts:
- GET /ui        → index.html (SPA shell)
- GET /ui/       → index.html (SPA shell)
- GET /ui/app.js → application JavaScript
- GET /ui/style.css → stylesheet
- GET /ui/locales/{lang}.json → locale strings for the SPA
"""
from .router import router

__all__ = ("router",)