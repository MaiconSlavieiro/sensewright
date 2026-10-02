"""Dream engine (F07 / REQ-DRM-*).

Combines four inputs weighted by a Surrealism index: day residue (0.40),
deja-vu/shadow memory (0.25), god whisper (0.20) and zeitgeist (0.15). The
surrealism index is clamped to [0, 1] and scales with the god chaos dial,
psyche trauma and mood stress. The engine builds the context for the
``sim.dream`` purpose; the LLM (or 0-key fallback) fills the narrative.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..constants import DREAM_WEIGHTS
from ..memory.sqlite_store import SqliteStore
from .psyche import strongest_block


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def surrealism_index(
    traits: List[str],
    god_chaos: float,
    psyche_blocks: Dict[str, float],
    mood: Optional[str],
) -> float:
    """Compute the dream surrealism index (clamped 0..1)."""
    # Base from traits that suggest an imaginative mind.
    imaginative = {"creative", "genius", "erratic", "insane", "paranoid"}
    base = 0.2
    for trait in traits or []:
        if trait.lower() in imaginative:
            base = 0.45
            break
    _, trauma = strongest_block(psyche_blocks)
    stress = 0.4 if (mood or "").lower() in ("tense", "sad", "angry", "uncomfortable") else 0.15
    value = base + (float(god_chaos) * 0.4) + (float(trauma) * 0.3) + (float(stress) * 0.25)
    return clamp(value)


def build_dream_context(
    sim_id: int,
    store: SqliteStore,
    sim_name: str,
    traits: List[str],
    psyche_blocks: Dict[str, float],
    mood: Optional[str],
    god_chaos: float,
    god_whisper: Optional[str],
    zeitgeist_tags: List[str],
    tick: int,
) -> Dict[str, Any]:
    """Assemble the context for the ``sim.dream`` purpose."""
    # Day residue: recent salient memories.
    recent = store.recent_memories(sim_id, limit=6)
    day_residue = [m.get("search_text", "") for m in recent if m.get("search_text")][:3]

    # Deja-vu / shadow: forgotten memories (strength < 0.2).
    shadow = [m.get("search_text", "") for m in recent if float(m.get("strength", 1.0)) < 0.2][:2]

    surrealism = surrealism_index(traits, god_chaos, psyche_blocks, mood)

    return {
        "sim_id": sim_id,
        "sim_name": sim_name,
        "surrealism_index": round(surrealism, 3),
        "day_residue": day_residue,
        "shadow_memories": shadow,
        "god_whisper": god_whisper or "",
        "zeitgeist_tags": zeitgeist_tags,
        "dream_weights": DREAM_WEIGHTS,
        "world_sim_tick": tick,
    }
