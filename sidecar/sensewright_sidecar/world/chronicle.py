"""World layer — household chronicles & post-climax aftermath (F22)."""
from __future__ import annotations

from typing import Any, Dict, List

from ..memory.sqlite_store import SqliteStore


def get_chronicles(store: SqliteStore, save_id: int) -> List[Any]:
    return list(store.get_neighborhood(save_id).get("chronicles", []) or [])


def append_chronicle(store: SqliteStore, save_id: int, chronicle: str, tick: int) -> None:
    chronicles = get_chronicles(store, save_id)
    chronicles.append({"text": chronicle, "tick": int(tick)})
    if len(chronicles) > 50:
        chronicles = chronicles[-50:]
    store.set_neighborhood(save_id, chronicles=chronicles, tick=tick)


def get_zeitgeist(store: SqliteStore, save_id: int) -> Dict[str, Any]:
    return store.get_neighborhood(save_id).get("zeitgeist", {}) or {}


def set_zeitgeist(
    store: SqliteStore,
    save_id: int,
    tags: List[str],
    preset: str,
    weather_preference: str,
    tick: int,
) -> None:
    store.set_neighborhood(
        save_id,
        zeitgeist={"tags": tags, "preset": preset, "weather_preference": weather_preference},
        tick=tick,
    )
