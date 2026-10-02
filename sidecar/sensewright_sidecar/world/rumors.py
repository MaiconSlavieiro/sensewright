"""World layer — rumor epidemiology (F22 / REQ-WLD-*).

Rumors carry a ``known_by_sim_ids`` list; a sim can only comment or forward a
rumor if its id is in that list (REQ-WLD-01). Rumors live in the neighborhoods
table and are cached in memory per save.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from ..memory.sqlite_store import SqliteStore
from ..observability.logging import get_logger

logger = get_logger("world.rumors")


def create_rumor(
    text: str,
    tags: List[str],
    source_sim_id: int,
    tick: int,
) -> Dict[str, Any]:
    """Create a RumorNode seeded by one sim."""
    return {
        "id": uuid.uuid4().hex[:12],
        "text": text,
        "tags": tags or [],
        "known_by_sim_ids": [int(source_sim_id)],
        "created_sim_tick": int(tick),
        "source_sim_id": int(source_sim_id),
    }


def can_comment(rumor: Dict[str, Any], sim_id: int) -> bool:
    known = rumor.get("known_by_sim_ids", []) or []
    return int(sim_id) in [int(s) for s in known]


def spread(rumor: Dict[str, Any], sim_id: int) -> Dict[str, Any]:
    """Mark a sim as a knower of a rumor (contagion)."""
    rumor = dict(rumor)
    known = [int(s) for s in (rumor.get("known_by_sim_ids", []) or [])]
    if int(sim_id) not in known:
        known.append(int(sim_id))
    rumor["known_by_sim_ids"] = known
    return rumor


def get_rumors(store: SqliteStore, save_id: int) -> List[Dict[str, Any]]:
    return list(store.get_neighborhood(save_id).get("rumors", []) or [])


def save_rumors(store: SqliteStore, save_id: int, rumors: List[Dict[str, Any]], tick: int) -> None:
    store.set_neighborhood(save_id, rumors=rumors, tick=tick)


def rumors_known_by(rumors: List[Dict[str, Any]], sim_id: int) -> List[Dict[str, Any]]:
    return [r for r in rumors if can_comment(r, sim_id)]
