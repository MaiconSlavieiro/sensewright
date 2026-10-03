"""World layer — post-climax aftermath processing (P25 / plan task 1.5).

Pure functions for building context, merging zeitgeist shifts, and parsing
LLM/fallback results for the `world.aftermath` purpose.
"""
from __future__ import annotations

from typing import Any, Dict, List


def build_aftermath_context(
    sim: Dict[str, Any],
    category: str,
    impact: float,
    salience: float,
    tick: int,
) -> Dict[str, Any]:
    """Context for the world.aftermath purpose.

    Args:
        sim: Sim dict with at least 'sim_id' and 'name' keys.
        category: Event category string (e.g., "death", "breakup", "promotion").
        impact: Impact magnitude (0.0–1.0+).
        salience: Salience weight (0.0–1.0+).
        tick: Current world simulation tick.

    Returns:
        Dict with keys: sim_id, sim_name, event_category, impact, salience, world_sim_tick.
    """
    sim_id = sim.get("sim_id") if isinstance(sim, dict) else None
    sim_name = sim.get("name") if isinstance(sim, dict) else None

    return {
        "sim_id": int(sim_id) if sim_id is not None else 0,
        "sim_name": str(sim_name) if sim_name is not None else "",
        "event_category": str(category) if category is not None else "",
        "impact": float(impact) if impact is not None else 0.0,
        "salience": float(salience) if salience is not None else 0.0,
        "world_sim_tick": int(tick) if tick is not None else 0,
    }


def merge_zeitgeist(existing: Dict[str, Any], shift: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a zeitgeist_shift into an existing zeitgeist dict.

    - `tags` are unioned (case-insensitive, order-preserving, no duplicates), capped at 12.
    - `preset` / `weather_preference` are overwritten when the shift provides a non-empty value.
    - Returns a NEW dict; never mutates inputs. Missing/invalid types degrade gracefully.

    Args:
        existing: Current zeitgeist dict with keys tags, preset, weather_preference.
        shift: Zeitgeist shift dict with optional tags, preset, weather_preference.

    Returns:
        New merged zeitgeist dict.
    """
    # Start with a deep copy of existing (shallow is fine since values are primitives/lists)
    result: Dict[str, Any] = {}

    # Copy existing tags
    existing_tags: List[str] = []
    if isinstance(existing, dict):
        existing_tags = [str(t) for t in (existing.get("tags") or []) if isinstance(t, str)]

    # Copy existing preset and weather
    result["preset"] = str(existing.get("preset", "drama")) if isinstance(existing, dict) else "drama"
    result["weather_preference"] = (
        str(existing.get("weather_preference", "sunny")) if isinstance(existing, dict) else "sunny"
    )

    # Process shift tags: union case-insensitively, preserve order, cap at 12
    shift_tags: List[str] = []
    if isinstance(shift, dict):
        shift_tags = [str(t) for t in (shift.get("tags") or []) if isinstance(t, str)]

    seen_lower = set()
    merged_tags: List[str] = []

    # First add existing tags in order
    for tag in existing_tags:
        lower = tag.lower()
        if lower not in seen_lower:
            seen_lower.add(lower)
            merged_tags.append(tag)

    # Then add shift tags in order
    for tag in shift_tags:
        lower = tag.lower()
        if lower not in seen_lower:
            seen_lower.add(lower)
            merged_tags.append(tag)

    # Cap at 12
    result["tags"] = merged_tags[:12]

    # Overwrite preset if shift provides non-empty value
    if isinstance(shift, dict):
        shift_preset = shift.get("preset")
        if isinstance(shift_preset, str) and shift_preset.strip():
            result["preset"] = shift_preset.strip()

        shift_weather = shift.get("weather_preference")
        if isinstance(shift_weather, str) and shift_weather.strip():
            result["weather_preference"] = shift_weather.strip()

    return result


def parse_aftermath(data: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a purpose result into {"summary": str, "intents": list, "zeitgeist_shift": dict}.

    Coerces wrong types to safe empties. Drops non-dict intents.

    Args:
        data: Raw result dict from LLM/fallback.

    Returns:
        Normalized dict with guaranteed keys and safe types.
    """
    if not isinstance(data, dict):
        data = {}

    # summary: coerce to string, empty if missing/invalid
    summary = data.get("summary")
    if not isinstance(summary, str):
        summary = str(summary) if summary is not None else ""

    # intents: must be list of dicts; drop non-dict entries
    intents_raw = data.get("intents")
    intents: List[Dict[str, Any]] = []
    if isinstance(intents_raw, list):
        for item in intents_raw:
            if isinstance(item, dict):
                intents.append(item)

    # zeitgeist_shift: must be dict with tags(list), preset(str), weather_preference(str)
    shift_raw = data.get("zeitgeist_shift")
    zeitgeist_shift: Dict[str, Any] = {"tags": [], "preset": "", "weather_preference": ""}
    if isinstance(shift_raw, dict):
        shift_tags = shift_raw.get("tags")
        if isinstance(shift_tags, list):
            zeitgeist_shift["tags"] = [str(t) for t in shift_tags if isinstance(t, str)]

        shift_preset = shift_raw.get("preset")
        if shift_preset is not None:
            zeitgeist_shift["preset"] = str(shift_preset)

        shift_weather = shift_raw.get("weather_preference")
        if shift_weather is not None:
            zeitgeist_shift["weather_preference"] = str(shift_weather)

    return {
        "summary": summary,
        "intents": intents,
        "zeitgeist_shift": zeitgeist_shift,
    }