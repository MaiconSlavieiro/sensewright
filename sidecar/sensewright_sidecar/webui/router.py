"""HTTP routes for the built-in web panel (``/`` + ``/ui/*``).

The panel is a static, dependency-free page (vanilla HTML/CSS/JS) that talks to
the sidecar's own ``/v1/*`` API. It runs in any browser *parallel* to the game.

Security model
--------------
The served assets carry no secrets. Authenticated ``/v1/*`` calls need the
shared token, which ``GET /ui/session`` discloses **only to a loopback client**
(the browser on the same machine). A remote client (``network.host = 0.0.0.0``)
receives ``token: null`` and must paste the token from ``data/token``. CORS is
not enabled, so a cross-origin page cannot read the session response.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from sensewright_sidecar import __version__, content_i18n

router = APIRouter(tags=["webui"])

_ASSETS = Path(__file__).resolve().parent

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost", "testclient"})

_MEDIA_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
}


def _web_enabled(request: Request) -> bool:
    settings = getattr(request.app.state, "settings", None)
    ui = getattr(settings, "ui", None)
    return bool(getattr(ui, "web_panel", True))


def _is_loopback(request: Request) -> bool:
    """True when the caller is the local machine (token may be disclosed)."""
    client = request.client
    if client is None:  # in-process ASGI transport / unix socket
        return True
    return client.host in _LOOPBACK_HOSTS


def _asset(name: str) -> FileResponse:
    path = (_ASSETS / name).resolve()
    if _ASSETS not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix, "application/octet-stream"))


@router.get("/", include_in_schema=False)
async def index(request: Request) -> FileResponse:
    """Serve the single-page panel (or 404 when disabled in config)."""
    if not _web_enabled(request):
        raise HTTPException(status_code=404, detail="web panel disabled")
    return _asset("index.html")


@router.get("/ui/session", include_in_schema=False)
async def session(request: Request) -> JSONResponse:
    """Bootstrap data: token (loopback only), resolved language and string tables."""
    if not _web_enabled(request):
        raise HTTPException(status_code=404, detail="web panel disabled")
    settings = request.app.state.settings
    lang = content_i18n.normalize_lang(getattr(settings, "lang", None))
    token = request.app.state.token if _is_loopback(request) else None
    return JSONResponse(
        {
            "ok": True,
            "version": __version__,
            "token": token,
            "lang": lang,
            "locales": [
                {"code": entry["code"], "name": entry["name"]}
                for entry in content_i18n.locale_entries()
            ],
        }
    )


@router.get("/ui/app.js", include_in_schema=False)
async def app_js() -> FileResponse:
    return _asset("app.js")


@router.get("/ui/style.css", include_in_schema=False)
async def style_css() -> FileResponse:
    return _asset("style.css")


@router.get("/ui/locales/{code}.json", include_in_schema=False)
async def locale(code: str) -> FileResponse:
    """Serve a panel UI-locale table (allow-listed to the manifest locales)."""
    if code not in content_i18n.available_locales():
        raise HTTPException(status_code=404, detail="unknown locale")
    return _asset(f"locales/{code}.json")
