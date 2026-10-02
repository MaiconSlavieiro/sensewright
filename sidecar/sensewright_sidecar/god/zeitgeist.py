"""God Director — zeitgeist (neighborhood mood)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..state import AppState
from ..world.chronicle import get_zeitgeist, set_zeitgeist


def run_zeitgeist(state: AppState, save_id: int, zeitgeist_text: str, lang: str) -> Dict[str, Any]:
    """Generate (or derive) the neighborhood zeitgeist and persist it."""
    store = state.working_store()
    if store is None:
        return {"tags": [], "preset": "drama", "weather_preference": "sunny"}

    context = {
        "save_id": save_id,
        "zeitgeist_text": zeitgeist_text,
    }
    result = state.scheduler.run_purpose("god.zeitgeist", context, lang)
    data = result.data or {}

    tags = data.get("tags", []) or []
    preset = data.get("preset", "drama") or "drama"
    weather = data.get("weather_preference", "sunny") or "sunny"

    if zeitgeist_text:
        # If the player typed tags directly, prefer them over the LLM guess.
        typed = [t.strip() for t in zeitgeist_text.split(",") if t.strip()]
        if typed:
            tags = typed

    set_zeitgeist(store, save_id, tags, preset, weather, store.get_tick())
    return {"tags": tags, "preset": preset, "weather_preference": weather}


def current_zeitgeist(state: AppState, save_id: int) -> Dict[str, Any]:
    store = state.working_store()
    if store is None:
        return {}
    return get_zeitgeist(store, save_id)
