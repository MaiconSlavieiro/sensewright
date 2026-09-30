"""
HTTP client for Sensewright mod.
Communicates with the sidecar via urllib (stdlib only).
Typed exceptions for different failure modes.
"""


import json
import math
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from .config import get_base_url, get_auth_header, clear_runtime_cache


class SidecarError(Exception):
    """Raised when sidecar returns an error HTTP status."""

    def __init__(self, status: int, body: str, message: str = ""):
        self.status = status
        self.body = body
        super().__init__(message or "Sidecar error: {} - {}".format(status, body))


class SidecarUnreachable(Exception):
    """Raised when sidecar cannot be reached (connection error, timeout)."""

    def __init__(self, message: str = "Sidecar unreachable"):
        super().__init__(message)


# Default timeout in seconds
DEFAULT_TIMEOUT = 5.0

# Sentinel for values dropped during payload sanitization.
_DROP = object()


def _sanitize_payload(value: Any) -> Any:
    """Recursively reduce a payload to JSON-safe primitives.

    Only ``None``/``bool``/``int``/``float``/``str`` survive; dicts, lists and
    tuples are rebuilt recursively. Non-finite floats become ``None`` and any
    other object (game ``SimInfo``/tracker/enum instances that leaked from the
    context collectors) is dropped. This keeps request bodies predictable and
    stops huge object ``repr``s from reaching the sidecar (code review item 5).
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (int, str)):
        return value
    if isinstance(value, dict):
        clean = {}
        for key, item in value.items():
            sanitized = _sanitize_payload(item)
            if sanitized is _DROP:
                continue
            clean[str(key)] = sanitized
        return clean
    if isinstance(value, (list, tuple, set, frozenset)):
        clean_list = []
        for item in value:
            sanitized = _sanitize_payload(item)
            if sanitized is _DROP:
                continue
            clean_list.append(sanitized)
        return clean_list
    return _DROP


def _make_request(
    path: str,
    method: str = "GET",
    payload: Optional[Dict[str, Any]] = None,
    timeout: float = DEFAULT_TIMEOUT,
    no_auth: bool = False
) -> Dict[str, Any]:
    """
    Make an HTTP request to the sidecar.
    Returns parsed JSON response.
    Raises SidecarUnreachable on connection errors.
    Raises SidecarError on HTTP error status.

    ``no_auth=True`` omits the auth header (used by the unauthenticated
    ``/v1/health`` probe); every other call sends it.
    """
    try:
        url = get_base_url() + path
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if not no_auth:
            headers.update(get_auth_header())

        data = None
        if payload is not None:
            # Sanitize first so only primitives travel: game objects
            # (LocalizedString, trackers, enums) are dropped instead of being
            # stringified into a bloated payload, and a stray object can no
            # longer break serialization. json.dumps stays inside the try so a
            # serialization failure cannot escape before handling (review M2).
            sanitized = _sanitize_payload(payload)
            if sanitized is _DROP:
                sanitized = {}
            data = json.dumps(sanitized).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=headers, method=method)

        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_data = response.read().decode("utf-8")
            return json.loads(response_data) if response_data else {}
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            pass
        # Clear cache on auth errors so we re-read runtime.json
        if e.code == 401:
            clear_runtime_cache()
        raise SidecarError(e.code, body, "HTTP {}: {}".format(e.code, e.reason))
    except urllib.error.URLError as e:
        clear_runtime_cache()
        raise SidecarUnreachable("Connection failed: {}".format(e.reason))
    except Exception as e:
        clear_runtime_cache()
        raise SidecarUnreachable("Request failed: {}".format(e))


def post_json(path: str, payload: Dict[str, Any], timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """POST JSON to the sidecar."""
    return _make_request(path, method="POST", payload=payload, timeout=timeout)


def get_json(path: str, timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """GET JSON from the sidecar."""
    return _make_request(path, method="GET", timeout=timeout)


# Convenience methods for specific endpoints

def chat(sim: Dict[str, Any], message: str, context: Dict[str, Any],
         session_id: Optional[str] = None, lang: str = "en") -> Dict[str, Any]:
    """POST /v1/chat"""
    payload = {
        "sim": sim,
        "message": message,
        "context": context,
        "session_id": session_id,
        "lang": lang,
    }
    return post_json("/v1/chat", payload)


def hey(sim: Dict[str, Any], context: Dict[str, Any],
        session_id: Optional[str] = None, lang: str = "en") -> Dict[str, Any]:
    """POST /v1/hey"""
    payload = {
        "sim": sim,
        "context": context,
        "session_id": session_id,
        "lang": lang,
    }
    return post_json("/v1/hey", payload)


def tool_result(tool_call_id: str, ok: bool, result: Any = None, error: Optional[str] = None) -> Dict[str, Any]:
    """POST /v1/tools/result"""
    payload = {
        "tool_call_id": tool_call_id,
        "ok": ok,
        "result": result,
        "error": error,
    }
    return post_json("/v1/tools/result", payload)


def reset(scope: str, sim: Dict[str, Any]) -> Dict[str, Any]:
    """POST /v1/reset"""
    payload = {
        "scope": scope,
        "sim": sim,
    }
    return post_json("/v1/reset", payload)


def set_autonomy(sim: Dict[str, Any], level: str) -> Dict[str, Any]:
    """POST /v1/config/autonomy"""
    payload = {
        "sim": sim,
        "level": level,
    }
    return post_json("/v1/config/autonomy", payload)


def set_lang(lang: str) -> Dict[str, Any]:
    """POST /v1/config/lang"""
    payload = {"lang": lang}
    return post_json("/v1/config/lang", payload)


def health() -> Dict[str, Any]:
    """GET /v1/health (no auth)."""
    return _make_request("/v1/health", method="GET", no_auth=True)


def status() -> Dict[str, Any]:
    """GET /v1/status"""
    return get_json("/v1/status")


# --- Event ingestion ---

def send_events(events: List[Dict[str, Any]], timeout: float = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    """POST /v1/events with a batch of event items."""
    return post_json("/v1/events", {"events": events}, timeout=timeout)


def send_event(sim: Dict[str, Any], type: str, content: Optional[Dict[str, Any]] = None,
               importance: float = 1.0, lang: str = "en") -> Dict[str, Any]:
    """POST /v1/events with a single event item."""
    event = {
        "sim": sim,
        "type": type,
        "content": content if content is not None else {},
        "importance": importance,
        "lang": lang,
    }
    return send_events([event])


def send_player_activity(sim: Dict[str, Any]) -> Dict[str, Any]:
    """POST /v1/config/player-activity to arm the player-priority lock."""
    return post_json("/v1/config/player-activity", {"sim": sim})


# --- God agent ---

def get_zeitgeist(save_id: str, player_id: str = "local") -> Dict[str, Any]:
    """GET /v1/god/zeitgeist with save/player query string."""
    query = urllib.parse.urlencode({
        "save_id": save_id,
        "player_id": player_id,
    })
    return get_json("/v1/god/zeitgeist?" + query)


def set_zeitgeist(sim: Dict[str, Any], mood_tags: List[str], free_text: str,
                  mood_influence: float = 0.5, lang: str = "en") -> Dict[str, Any]:
    """POST /v1/god/zeitgeist to configure the neighborhood zeitgeist."""
    payload = {
        "sim": sim,
        "mood_tags": mood_tags,
        "free_text": free_text,
        "mood_influence": mood_influence,
        "lang": lang,
    }
    return post_json("/v1/god/zeitgeist", payload)


def suggest_zeitgeist(sim: Dict[str, Any], mood_tags: List[str], free_text: str,
                      lang: str = "en") -> Dict[str, Any]:
    """POST /v1/god/zeitgeist/suggest to get an LLM-written zeitgeist draft."""
    payload = {
        "sim": sim,
        "mood_tags": mood_tags,
        "free_text": free_text,
        "lang": lang,
    }
    return post_json("/v1/god/zeitgeist/suggest", payload)


def request_background(sim: Dict[str, Any], scope: str = "sim",
                       household_id: Optional[int] = None, player_hints: str = "",
                       census: Optional[Dict[str, Any]] = None, force: bool = False,
                       lang: str = "en") -> Dict[str, Any]:
    """POST /v1/god/background to generate a Sim/household background."""
    payload = {
        "sim": sim,
        "scope": scope,
        "household_id": household_id,
        "player_hints": player_hints,
        "census": census,
        "force": force,
        "lang": lang,
    }
    return post_json("/v1/god/background", payload)


def get_god_controls() -> Dict[str, Any]:
    """GET /v1/god/controls for the God panel metadata and current values."""
    return get_json("/v1/god/controls")


def set_god_controls(preset: Optional[str] = None, enabled: Optional[bool] = None,
                     powers: Optional[Dict[str, bool]] = None,
                     values: Optional[Dict[str, Any]] = None,
                     persist: bool = False) -> Dict[str, Any]:
    """POST /v1/config/god to change the God preset, toggle or dials.

    ``values`` holds ControlSpec keys (e.g. ``autonomy_degree``,
    ``intervention_frequency``, ``agent_seats``); the sidecar validates them,
    applies them to the live settings and re-applies them to the orchestrator.
    """
    payload: Dict[str, Any] = {"persist": bool(persist)}
    if preset is not None:
        payload["preset"] = preset
    if enabled is not None:
        payload["enabled"] = bool(enabled)
    if powers:
        payload["powers"] = dict(powers)
    if values:
        payload["settings"] = dict(values)
    return post_json("/v1/config/god", payload)


def god_tick(sim: Dict[str, Any], time_of_day: str = "unknown",
             lot_type: str = "residential", lang: str = "en") -> Dict[str, Any]:
    """POST /v1/god/tick — run one God-orchestration tick for a save.

    Returns the issued directives (each carrying an optional ``tool_call`` the
    mod executes and a ``narration`` it surfaces).
    """
    payload = {
        "sim": sim,
        "time_of_day": time_of_day,
        "lot_type": lot_type,
        "lang": lang,
    }
    return post_json("/v1/god/tick", payload)


def send_census(sim: Dict[str, Any], sims: List[Dict[str, Any]],
                households: List[Dict[str, Any]], scope: str = "active_zone",
                lang: str = "en") -> Dict[str, Any]:
    """POST /v1/census with the active-zone Sim and household census."""
    payload = {
        "sim": sim,
        "scope": scope,
        "sims": sims,
        "households": households,
        "lang": lang,
    }
    return post_json("/v1/census", payload)


# --- Phase 3/4: profiles and evolution ---

def request_profile(sim: Dict[str, Any], seed: str = "", hints: str = "",
                    native: Optional[Dict[str, Any]] = None, force: bool = False,
                    lang: str = "en") -> Dict[str, Any]:
    """POST /v1/profile to generate a Sim character profile from a seed."""
    payload = {
        "sim": sim,
        "seed": seed,
        "hints": hints,
        "native": native,
        "force": force,
        "lang": lang,
    }
    return post_json("/v1/profile", payload)


def evolve(sim: Dict[str, Any], scope: str = "sim", force: bool = False,
           lang: str = "en") -> Dict[str, Any]:
    """POST /v1/evolve to run the reflection/evolution loop."""
    payload = {
        "sim": sim,
        "scope": scope,
        "force": force,
        "lang": lang,
    }
    return post_json("/v1/evolve", payload)


# --- v0.2: autonomous Sim agents (PLANO §14.2) ---

def autonomy_tick(sim: Dict[str, Any], zone: Dict[str, Any],
                  sims: List[Dict[str, Any]], lang: str = "en") -> Dict[str, Any]:
    """POST /v1/autonomy/tick with the fire-and-forget zone pulse."""
    payload = {
        "sim": sim,
        "zone": zone,
        "sims": sims,
        "lang": lang,
    }
    return post_json("/v1/autonomy/tick", payload)


def get_directives(save_id: str, player_id: str = "local",
                   sim_id: Optional[int] = None, limit: int = 20) -> Dict[str, Any]:
    """GET /v1/autonomy/directives; ``sim_id`` is omitted when None."""
    params = {
        "save_id": save_id,
        "player_id": player_id,
        "limit": limit,
    }
    if sim_id is not None:
        params["sim_id"] = sim_id
    query = urllib.parse.urlencode(params)
    return get_json("/v1/autonomy/directives?" + query)


# --- v0.3: intents + agent seats (PLANO §15) ---

def get_intents(save_id: str, player_id: str = "local",
                sim_id: Optional[int] = None, limit: int = 20) -> Dict[str, Any]:
    """GET /v1/autonomy/intents; ``sim_id`` is omitted when None."""
    params = {
        "save_id": save_id,
        "player_id": player_id,
        "limit": limit,
    }
    if sim_id is not None:
        params["sim_id"] = sim_id
    query = urllib.parse.urlencode(params)
    return get_json("/v1/autonomy/intents?" + query)


def get_seats(save_id: str, player_id: str = "local") -> Dict[str, Any]:
    """GET /v1/agency/seats — the live agent roster for a save."""
    query = urllib.parse.urlencode({"save_id": save_id, "player_id": player_id})
    return get_json("/v1/agency/seats?" + query)


def assign_seat(sim: Dict[str, Any], seats: Optional[int] = None,
                sim_id: Optional[int] = None,
                impulse_frequency: Optional[float] = None) -> Dict[str, Any]:
    """POST /v1/agency/seats — resize the pool / set a per-Sim frequency dial."""
    payload = {
        "sim": sim,
        "seats": seats,
        "sim_id": sim_id,
        "impulse_frequency": impulse_frequency,
    }
    return post_json("/v1/agency/seats", payload)


# --- Lifecycle: the sidecar exits with the game ---

def attach_lifecycle(pid: int) -> Dict[str, Any]:
    """POST /v1/lifecycle/attach — arm the sidecar's game-process watchdog.

    Retries once on a 401: the first attach after boot can race a stale
    ``runtime.json``/token, so the runtime cache is cleared and re-read.
    """
    payload = {"pid": int(pid)}
    try:
        return post_json("/v1/lifecycle/attach", payload)
    except SidecarError as exc:
        if exc.status == 401:
            clear_runtime_cache()
            return post_json("/v1/lifecycle/attach", payload)
        raise