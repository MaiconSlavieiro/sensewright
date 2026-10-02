"""God Director controls, presets and dials (F14 / REQ-GOD-01)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..config import Config
from ..constants import GOD_DIALS, GOD_MODES, GOD_PRESETS
from ..panel_store import PanelStore

#: Default dial values per genre preset (7 presets + off).
PRESET_DIALS: Dict[str, Dict[str, float]] = {
    "off": {"intervention_frequency": 0.0, "intensity": 0.0, "mood_influence": 0.0, "autonomy_degree": 1.0, "chaos_degree": 0.0},
    "novela": {"intervention_frequency": 0.6, "intensity": 0.7, "mood_influence": 0.6, "autonomy_degree": 0.5, "chaos_degree": 0.5},
    "sitcom": {"intervention_frequency": 0.4, "intensity": 0.4, "mood_influence": 0.4, "autonomy_degree": 0.7, "chaos_degree": 0.4},
    "drama": {"intervention_frequency": 0.5, "intensity": 0.7, "mood_influence": 0.6, "autonomy_degree": 0.5, "chaos_degree": 0.3},
    "caos": {"intervention_frequency": 0.8, "intensity": 0.9, "mood_influence": 0.7, "autonomy_degree": 0.3, "chaos_degree": 1.0},
    "terror": {"intervention_frequency": 0.5, "intensity": 0.8, "mood_influence": 0.5, "autonomy_degree": 0.4, "chaos_degree": 0.6},
    "romance": {"intervention_frequency": 0.5, "intensity": 0.6, "mood_influence": 0.7, "autonomy_degree": 0.6, "chaos_degree": 0.2},
    "filme_adolescente": {"intervention_frequency": 0.5, "intensity": 0.6, "mood_influence": 0.5, "autonomy_degree": 0.6, "chaos_degree": 0.5},
}

#: Powers (feature flags) toggled from the Director's Room.
POWERS = (
    "dream_whispers", "spatial_gravity", "scene_subtext", "world_pressure",
    "catalyst_npcs", "aftermath",
)


def current_preset(panel: PanelStore, config: Config) -> str:
    preset = panel.get("preset")
    if preset in GOD_PRESETS or preset == "off":
        return preset
    return str(config.god("preset", "novela"))


def resolve_dial(panel: PanelStore, config: Config, key: str) -> float:
    """Effective dial value: explicit override, else preset default, else config."""
    override = panel.get(key)
    if override is not None:
        try:
            return float(override)
        except (TypeError, ValueError):
            pass
    preset = current_preset(panel, config)
    preset_dials = PRESET_DIALS.get(preset, PRESET_DIALS["novela"])
    if key in preset_dials:
        return float(preset_dials[key])
    return float(config.god(key, 0.5))


def resolve_mode(panel: PanelStore, config: Config) -> str:
    mode = panel.get("director_mode")
    if mode in GOD_MODES:
        return mode
    return str(config.god("director_mode", "AUTONOMOUS"))


def resolve_powers(panel: PanelStore) -> Dict[str, bool]:
    powers = panel.get("powers") or {}
    result: Dict[str, bool] = {}
    for power in POWERS:
        result[power] = bool(powers.get(power, True))
    return result


def get_controls(panel: PanelStore, config: Config) -> List[Dict[str, Any]]:
    """Return the full controls list for the Web Studio / Quick Menu."""
    controls: List[Dict[str, Any]] = []

    for dial in GOD_DIALS:
        controls.append({
            "key": dial,
            "category": "dial",
            "type": "float",
            "value": resolve_dial(panel, config, dial),
            "options": [0.0, 1.0],
            "label": dial,
            "description": "",
        })

    controls.append({
        "key": "preset",
        "category": "director",
        "type": "enum",
        "value": current_preset(panel, config),
        "options": list(GOD_PRESETS) + ["off"],
        "label": "preset",
        "description": "",
    })
    controls.append({
        "key": "director_mode",
        "category": "director",
        "type": "enum",
        "value": resolve_mode(panel, config),
        "options": list(GOD_MODES),
        "label": "director_mode",
        "description": "",
    })
    controls.append({
        "key": "spoiler_shield",
        "category": "director",
        "type": "bool",
        "value": bool(panel.get("spoiler_shield", True)),
        "options": [],
        "label": "spoiler_shield",
        "description": "",
    })
    controls.append({
        "key": "free_only",
        "category": "llm",
        "type": "bool",
        "value": bool(panel.get("free_only", config.free_only)),
        "options": [],
        "label": "free_only",
        "description": "",
    })
    powers = resolve_powers(panel)
    for power in POWERS:
        controls.append({
            "key": "power." + power,
            "category": "powers",
            "type": "bool",
            "value": powers[power],
            "options": [],
            "label": power,
            "description": "",
        })
    return controls


def set_control(panel: PanelStore, config: Config, key: str, value: Any) -> bool:
    """Persist a control override; returns True if the key is known."""
    if key in GOD_DIALS:
        try:
            panel.set(key, max(0.0, min(1.0, float(value))))
        except (TypeError, ValueError):
            return False
        return True
    if key == "preset" and (value in GOD_PRESETS or value == "off"):
        panel.set(key, value)
        return True
    if key == "director_mode" and value in GOD_MODES:
        panel.set(key, value)
        return True
    if key == "spoiler_shield":
        panel.set(key, bool(value))
        return True
    if key == "free_only":
        panel.set(key, bool(value))
        return True
    if key.startswith("power."):
        power = key[len("power."):]
        if power in POWERS:
            powers = panel.get("powers") or {}
            powers = dict(powers)
            powers[power] = bool(value)
            panel.set("powers", powers)
            return True
    return False
