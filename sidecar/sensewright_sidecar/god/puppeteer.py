"""God Director — the god.puppeteer flow (F14 §17.2 / P18).

Under a GOD_CATALYST_PUPPET lease, a catalyst NPC approaches a sovereign agent
and drives a dramatic objective while the agent responds freely. The puppeteer
only ever controls NPC catalysts (never household sovereign agents).
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from ..agent.intents import normalize_intent
from ..state import AppState
from .coordinator import set_catalyst_lease


def run_puppeteer(
    state: AppState,
    catalyst_id: int,
    catalyst_name: str,
    target_sim_id: int,
    target_name: str,
    objective: str,
    lang: str,
    tick: int,
) -> Dict[str, Any]:
    """Run the puppeteer for a catalyst -> target approach and return intents."""
    context = {
        "sim_id": int(catalyst_id),
        "sim_name": catalyst_name,
        "target_sim_id": int(target_sim_id),
        "target_name": target_name,
        "puppeteer_objective": objective,
        "catalyst_name": catalyst_name,
        "agent_name": target_name,
        "world_sim_tick": tick,
    }
    result = state.scheduler.run_purpose("god.puppeteer", context, lang)
    data = result.data or {}

    resolved_objective = data.get("objective") or objective
    opening_line = data.get("opening_line", "")
    scene_subtext = data.get("scene_subtext", "")

    # Grant the catalyst lease.
    set_catalyst_lease(state, catalyst_id, resolved_objective, tick)

    intents = []
    if opening_line:
        intents.append(normalize_intent({
            "trace_id": None,
            "sim_id": int(catalyst_id),
            "kind": "speak",
            "target_sim_id": int(target_sim_id),
            "params": {"text": opening_line, "tone": "friendly"},
            "source": "puppeteer",
        }, trace_id=None, default_source="puppeteer"))

    scene_id = uuid.uuid4().hex[:12]
    return {
        "ok": True,
        "scene_id": scene_id,
        "intents": intents,
        "objective": resolved_objective,
        "scene_subtext": scene_subtext,
    }
