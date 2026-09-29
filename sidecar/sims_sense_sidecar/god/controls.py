"""Declarative God configuration framework.

A single ``ControlSpec`` registry is the source of truth for the God settings:
it drives the sidecar validation (``/v1/config/god``), the mod UI metadata
(``/v1/god/controls``) and the TOML defaults. Adding a control means adding one
spec entry plus its i18n keys - no router or UI rewrite.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from ..schemas import MOOD_TAGS

ControlKind = Literal["slider", "toggle", "select", "tags"]

# God power toggles exposed as ``power_<name>`` controls.
POWER_KEYS = (
    "spawn_npc",
    "apply_trait",
    "force_social",
    "gossip",
    "relationship_shift",
    "extreme_events",
)

# v0.3 §15.6: agent-roster dials + layer toggles (routed to ``[agents]``).
AGENT_CONTROL_KEYS = (
    "agent_seats",
    "impulse_frequency",
    "player_sim_impulse_frequency",
    "reactions_enabled",
    "reasoning_effort",
    "layer_memory",
    "layer_cognition",
    "layer_social",
)

_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high")

_LAYER_KEYS = {
    "layer_memory": "memory",
    "layer_cognition": "cognition",
    "layer_social": "social",
}

_EVOLUTION_SPEEDS = ("slow", "normal", "fast")


class ControlOption(BaseModel):
    """A select/tags option, localized through ``label_key``."""

    value: str
    label_key: str


class ControlSpec(BaseModel):
    """Metadata + validation for one God control."""

    key: str
    kind: ControlKind
    label_key: str
    description_key: str = ""
    default: Any = 0.5
    min_value: float | None = None
    max_value: float | None = None
    step: float | None = None
    options: list[ControlOption] = Field(default_factory=list)
    requires_power: str | None = None
    advanced: bool = False

    def validate(self, value: Any) -> Any:
        """Coerce/validate a single value; raise ``ValueError`` when invalid."""
        if self.kind == "slider":
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{self.key}: not a number: {value!r}") from exc
            if self.min_value is not None:
                number = max(self.min_value, number)
            if self.max_value is not None:
                number = min(self.max_value, number)
            if self.step:
                number = round(number / self.step) * self.step
            return round(number, 6)

        if self.kind == "toggle":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)

        if self.kind in ("select", "tags"):
            allowed = {opt.value for opt in self.options}
            if self.kind == "select":
                if value not in allowed:
                    raise ValueError(f"{self.key}: invalid option {value!r}")
                return value
            if isinstance(value, str):
                values = [part.strip() for part in value.split(",") if part.strip()]
            elif isinstance(value, (list, tuple)):
                values = [str(part) for part in value]
            else:
                raise ValueError(f"{self.key}: expected a list of tags")
            return [tag for tag in values if tag in allowed]

        raise ValueError(f"{self.key}: unknown control kind {self.kind!r}")


def _slider(key: str, default: float, description_key: str) -> ControlSpec:
    return ControlSpec(
        key=key,
        kind="slider",
        label_key=f"god.control.{key}.label",
        description_key=description_key,
        default=default,
        min_value=0.0,
        max_value=1.0,
        step=0.05,
    )


def _power(key: str, default: bool) -> ControlSpec:
    return ControlSpec(
        key=f"power_{key}",
        kind="toggle",
        label_key=f"god.control.power_{key}.label",
        description_key=f"god.control.power_{key}.desc",
        default=default,
    )


def _agent_slider(
    key: str, default: float, *, minimum: float, maximum: float, step: float
) -> ControlSpec:
    return ControlSpec(
        key=key,
        kind="slider",
        label_key=f"god.control.{key}.label",
        description_key=f"god.control.{key}.desc",
        default=default,
        min_value=minimum,
        max_value=maximum,
        step=step,
        advanced=True,
    )


CONTROL_SPECS: list[ControlSpec] = [
    _slider("autonomy_degree", 0.5, "god.control.autonomy_degree.desc"),
    _slider("chaos_degree", 0.3, "god.control.chaos_degree.desc"),
    _slider("mood_influence", 0.5, "god.control.mood_influence.desc"),
    _slider("intervention_frequency", 0.5, "god.control.intervention_frequency.desc"),
    _slider("intensity", 0.5, "god.control.intensity.desc"),
    ControlSpec(
        key="evolution_speed",
        kind="select",
        label_key="god.control.evolution_speed.label",
        description_key="god.control.evolution_speed.desc",
        default="normal",
        options=[ControlOption(value=v, label_key=f"god.speed.{v}") for v in _EVOLUTION_SPEEDS],
    ),
    ControlSpec(
        key="mood_tags",
        kind="tags",
        label_key="god.control.mood_tags.label",
        description_key="god.control.mood_tags.desc",
        default=[],
        options=[ControlOption(value=tag, label_key=f"god.tag.{tag}") for tag in MOOD_TAGS],
    ),
    _power("spawn_npc", True),
    _power("apply_trait", True),
    _power("force_social", True),
    _power("gossip", True),
    _power("relationship_shift", True),
    _power("extreme_events", False),
    # v0.3 §15.6: agent-roster dials (advanced; routed to ``settings.agents``).
    _agent_slider("agent_seats", 12, minimum=1, maximum=24, step=1),
    _agent_slider("impulse_frequency", 0.2, minimum=0.0, maximum=1.0, step=0.05),
    _agent_slider(
        "player_sim_impulse_frequency", 0.0, minimum=0.0, maximum=1.0, step=0.05
    ),
    ControlSpec(
        key="reactions_enabled",
        kind="toggle",
        label_key="god.control.reactions_enabled.label",
        description_key="god.control.reactions_enabled.desc",
        default=True,
        advanced=True,
    ),
    ControlSpec(
        key="reasoning_effort",
        kind="select",
        label_key="god.control.reasoning_effort.label",
        description_key="god.control.reasoning_effort.desc",
        default="none",
        options=[
            ControlOption(value=v, label_key=f"god.reasoning.{v}")
            for v in _REASONING_EFFORTS
        ],
        advanced=True,
    ),
    ControlSpec(
        key="layer_memory",
        kind="toggle",
        label_key="god.control.layer_memory.label",
        description_key="god.control.layer_memory.desc",
        default=True,
        advanced=True,
    ),
    ControlSpec(
        key="layer_cognition",
        kind="toggle",
        label_key="god.control.layer_cognition.label",
        description_key="god.control.layer_cognition.desc",
        default=True,
        advanced=True,
    ),
    ControlSpec(
        key="layer_social",
        kind="toggle",
        label_key="god.control.layer_social.label",
        description_key="god.control.layer_social.desc",
        default=True,
        advanced=True,
    ),
]

CONTROL_SPEC_BY_KEY: dict[str, ControlSpec] = {spec.key: spec for spec in CONTROL_SPECS}

_POWER_PREFIX = "power_"


def list_controls(include_advanced: bool = True) -> list[ControlSpec]:
    """Return the control specs, optionally hiding advanced ones."""
    return [spec for spec in CONTROL_SPECS if include_advanced or not spec.advanced]


def get_control(key: str) -> ControlSpec | None:
    """Return a spec by key, or None."""
    return CONTROL_SPEC_BY_KEY.get(key)


def default_values() -> dict[str, Any]:
    """Return ``{key: default}`` for every control."""
    return {spec.key: spec.default for spec in CONTROL_SPECS}


def validate_values(values: dict[str, Any] | None) -> dict[str, Any]:
    """Validate a partial values map against the registry.

    Unknown keys raise ``ValueError``; known keys are coerced/clamped.
    """
    if not values:
        return {}
    validated: dict[str, Any] = {}
    for key, value in values.items():
        spec = CONTROL_SPEC_BY_KEY.get(key)
        if spec is None:
            raise ValueError(f"unknown control: {key}")
        validated[key] = spec.validate(value)
    return validated


def merge_with_defaults(values: dict[str, Any] | None) -> dict[str, Any]:
    """Return defaults overlaid with validated values."""
    merged = default_values()
    merged.update(validate_values(values))
    return merged


def values_from_god_config(god_config: Any) -> dict[str, Any]:
    """Project a ``GodConfig`` into the flat control-value map."""
    values = default_values()
    values.update(
        {
            "autonomy_degree": god_config.autonomy_degree,
            "chaos_degree": god_config.chaos_degree,
            "mood_influence": god_config.mood_influence,
            "intervention_frequency": god_config.intervention_frequency,
            "intensity": god_config.intensity,
        }
    )
    settings = getattr(god_config, "settings", {}) or {}
    if settings.get("evolution_speed") in _EVOLUTION_SPEEDS:
        values["evolution_speed"] = settings["evolution_speed"]
    if isinstance(settings.get("mood_tags"), list):
        values["mood_tags"] = settings["mood_tags"]
    powers = getattr(god_config, "powers", {}) or {}
    for power in POWER_KEYS:
        values[f"{_POWER_PREFIX}{power}"] = bool(powers.get(power, values[f"{_POWER_PREFIX}{power}"]))
    return values


def apply_values_to_god_config(values: dict[str, Any] | None) -> dict[str, Any]:
    """Map validated control values into a ``GodConfig`` patch dict."""
    validated = validate_values(values)
    patch: dict[str, Any] = {}
    powers_patch: dict[str, bool] = {}
    settings_patch: dict[str, Any] = {}

    for key, value in validated.items():
        if key.startswith(_POWER_PREFIX):
            powers_patch[key[len(_POWER_PREFIX):]] = bool(value)
        elif key == "evolution_speed":
            settings_patch["evolution_speed"] = value
        elif key == "mood_tags":
            settings_patch["mood_tags"] = value
        else:
            patch[key] = value

    if powers_patch:
        patch["powers"] = powers_patch
    if settings_patch:
        patch["settings"] = settings_patch
    return patch


def values_from_settings(settings: Any) -> dict[str, Any]:
    """Full control-value map: God dials plus the v0.3 agent-roster dials."""
    values = values_from_god_config(settings.god)
    agents = getattr(settings, "agents", None)
    if agents is None:
        return values
    values["agent_seats"] = agents.seat_count
    values["impulse_frequency"] = agents.initiative.impulse_frequency
    values["player_sim_impulse_frequency"] = agents.initiative.player_sim_impulse_frequency
    values["reactions_enabled"] = bool(agents.initiative.reactions_enabled)
    values["reasoning_effort"] = (
        getattr(agents.initiative, "reasoning_effort", None)
        or getattr(settings.llm, "reasoning_effort", "none")
    )
    layers = getattr(agents, "layers", None)
    for key, attr in _LAYER_KEYS.items():
        values[key] = bool(getattr(layers, attr, True)) if layers is not None else True
    return values


def apply_values_to_agents_config(values: dict[str, Any] | None) -> dict[str, Any]:
    """Map validated agent-control values into an ``AgentsConfig`` patch dict.

    Returns ``{"agent_seats": int, "initiative": {...}, "layers": {...}}`` suitable
    for a shallow merge by the caller. Only agent-control keys are consumed.
    """
    validated = validate_values(values)
    patch: dict[str, Any] = {}
    initiative: dict[str, Any] = {}
    layers: dict[str, Any] = {}
    for key, value in validated.items():
        if key == "agent_seats":
            patch["agent_seats"] = int(value)
        elif key in ("impulse_frequency", "player_sim_impulse_frequency"):
            initiative[key] = float(value)
        elif key == "reactions_enabled":
            initiative["reactions_enabled"] = bool(value)
        elif key == "reasoning_effort":
            initiative["reasoning_effort"] = str(value)
        elif key in _LAYER_KEYS:
            layers[_LAYER_KEYS[key]] = bool(value)
    if initiative:
        patch["initiative"] = initiative
    if layers:
        patch["layers"] = layers
    return patch


def controls_payload(include_advanced: bool = True) -> list[dict[str, Any]]:
    """JSON-serializable spec list for ``GET /v1/god/controls``."""
    return [spec.model_dump() for spec in list_controls(include_advanced)]
