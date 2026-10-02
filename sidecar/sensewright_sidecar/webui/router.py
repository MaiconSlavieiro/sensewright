"""FastAPI router for the Sensewright Web Studio (SPA).

Serves the single-page application at /ui and static assets from the package
directory at runtime. Pure stdlib + FastAPI; Python 3.10+ compatible.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# Package directory (where this file lives)
_PKG_DIR = Path(__file__).resolve().parent
_WEBUI_DIR = _PKG_DIR
# SPA's own UI string catalog (webui/locales/<code>.json)
_SPA_LOCALES_DIR = _PKG_DIR / "locales"

router = APIRouter(tags=["webui"])


def _read_text_safe(path: Path) -> Optional[str]:
    """Read a text file, returning None if missing or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def _read_json_safe(path: Path) -> Optional[dict]:
    """Read a JSON file, returning None if missing or invalid."""
    try:
        import json
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _resolve_locale_code(requested: str) -> str:
    """Resolve a locale code via the manifest (zero hardcoded locales)."""
    try:
        from ..i18n_engine import get_engine
        return get_engine().resolve_locale(requested)
    except Exception:
        return requested


@router.get("/ui", response_class=HTMLResponse, include_in_schema=False)
@router.get("/ui/", response_class=HTMLResponse, include_in_schema=False)
async def serve_spa(request: Request) -> HTMLResponse:
    """Serve the SPA shell (index.html)."""
    html = _read_text_safe(_WEBUI_DIR / "index.html")
    if html is None:
        # Fallback minimal HTML if index.html is missing
        html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Sensewright Web Studio</title>
  <link rel="stylesheet" href="/ui/style.css">
</head>
<body>
  <div id="app">Sensewright Web Studio — index.html not found</div>
  <script src="/ui/app.js"></script>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/ui/app.js", include_in_schema=False)
async def serve_app_js() -> FileResponse:
    """Serve the application JavaScript."""
    js_path = _WEBUI_DIR / "app.js"
    if not js_path.is_file():
        raise HTTPException(status_code=404, detail="app.js not found")
    return FileResponse(js_path, media_type="application/javascript")


@router.get("/ui/style.css", include_in_schema=False)
async def serve_style_css() -> FileResponse:
    """Serve the stylesheet."""
    css_path = _WEBUI_DIR / "style.css"
    if not css_path.is_file():
        raise HTTPException(status_code=404, detail="style.css not found")
    return FileResponse(css_path, media_type="text/css")


@router.get("/ui/locales/{code}.json", include_in_schema=False)
async def serve_locale(code: str) -> JSONResponse:
    """Serve the SPA's own UI locale JSON (manifest-driven resolution)."""
    resolved = _resolve_locale_code(code)
    locale_path = _SPA_LOCALES_DIR / "{}.json".format(resolved)
    data = _read_json_safe(locale_path)
    if data is None:
        # Return empty object rather than 404 so the SPA can fall back gracefully
        data = {}
    return JSONResponse(content=data)


@router.get("/ui/manifest.json", include_in_schema=False)
async def serve_manifest() -> JSONResponse:
    """Serve the unified locale manifest (single source of truth)."""
    try:
        from ..i18n_engine import get_engine
        return JSONResponse(content=get_engine().manifest())
    except Exception:
        return JSONResponse(content={})


# Mount static files for any additional assets (images, etc.) if they exist
_static_dir = _WEBUI_DIR / "static"
if _static_dir.is_dir():
    router.mount("/ui/static", StaticFiles(directory=_static_dir), name="webui-static")