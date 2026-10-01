"""Declarative God configuration framework.

A single ``ControlSpec`` registry is the source of truth for the God settings:
it drives the sidecar validation (``/v1/config/god``), the mod UI metadata
(``/v1/god/controls``) and the TOML defaults. Adding a control means adding one
spec entry plus its i18n keys - no router or UI rewrite.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from .. import content_i18n
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

# P1 (docs/ui_panel.md §1.4): promoted mod/global settings + their option sets.
_DECAY_PRESETS = ("fast", "normal", "slow")
_TRAIT_SWAP_MODES = ("off", "propose", "auto")


def _ui_language_options() -> list[ControlOption]:
    """Return the data-driven ``ui.language`` options (``auto`` + every locale)."""
    codes = ("auto", *content_i18n.available_locales())
    return [
        ControlOption(
            value=code,
            label_key=f"god.lang.{code}",
            label=content_i18n.language_name(code),
        )
        for code in codes
    ]

# Settings-path groups consumed by the patch builders below. Specs whose
# ``target`` is not in one of these groups are applied directly to the live
# ``Settings`` object by :func:`apply_values_to_settings`.
_GOD_PATCH_TARGETS = frozenset({"god", "god.settings", "god.powers"})
_AGENT_PATCH_TARGETS = frozenset(
    {"agents", "agents.initiative", "agents.layers", "agents.speech", "agents.presence"}
)
_AGENT_MAP_TARGETS = frozenset({"agents.speech", "agents.presence"})


class ControlOption(BaseModel):
    """A select/tags option, localized through ``label_key``.

    ``label`` optionally carries a ready-to-render human name (used for the
    ``ui.language`` options so the mod needs no per-language keys).
    """

    value: str
    label_key: str
    label: str | None = None


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
    # P1: where the value lives in ``Settings``. ``target`` is a dotted path
    # (e.g. ``agents.personality``) and ``path`` the field within it (defaults
    # to ``key``). Docs only use them; the mod panel renders the label keys.
    target: str | None = None
    path: str | None = None
    # Read once at sidecar startup: never persisted to ``panel.toml`` and hidden
    # from the panel by default.
    restart_only: bool = False

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
        target="god",
        path=key,
    )


def _power(key: str, default: bool) -> ControlSpec:
    return ControlSpec(
        key=f"power_{key}",
        kind="toggle",
        label_key=f"god.control.power_{key}.label",
        description_key=f"god.control.power_{key}.desc",
        default=default,
        target="god.powers",
        path=key,
    )


def _agent_slider(
    key: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
    step: float,
    target: str,
    path: str | None = None,
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
        target=target,
        path=path or key,
    )


def _promoted(
    key: str,
    kind: ControlKind,
    default,
    *,
    target: str,
    path: str | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    step: float | None = None,
    options: tuple[str, ...] = (),
    option_prefix: str = "god.option",
    restart_only: bool = False,
) -> ControlSpec:
    """Build a promoted §1.4 control (``advanced``, with an explicit path)."""
    return ControlSpec(
        key=key,
        kind=kind,
        label_key=f"god.control.{key}.label",
        description_key=f"god.control.{key}.desc",
        default=default,
        min_value=minimum,
        max_value=maximum,
        step=step,
        options=[
            ControlOption(value=value, label_key=f"{option_prefix}.{value}")
            for value in options
        ],
        advanced=True,
        target=target,
        path=path or key,
        restart_only=restart_only,
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
        target="god.settings",
        path="evolution_speed",
    ),
    ControlSpec(
        key="mood_tags",
        kind="tags",
        label_key="god.control.mood_tags.label",
        description_key="god.control.mood_tags.desc",
        default=[],
        options=[ControlOption(value=tag, label_key=f"god.tag.{tag}") for tag in MOOD_TAGS],
        target="god.settings",
        path="mood_tags",
    ),
    _power("spawn_npc", True),
    _power("apply_trait", True),
    _power("force_social", True),
    _power("gossip", True),
    _power("relationship_shift", True),
    _power("extreme_events", False),
    # v0.3 §15.6: agent-roster dials (advanced; routed to ``settings.agents``).
    _agent_slider("agent_seats", 6, minimum=1, maximum=24, step=1, target="agents"),
    _agent_slider(
        "impulse_frequency", 0.2, minimum=0.0, maximum=1.0, step=0.05,
        target="agents.initiative",
    ),
    _agent_slider(
        "player_sim_impulse_frequency", 0.0, minimum=0.0, maximum=1.0, step=0.05,
        target="agents.initiative",
    ),
    ControlSpec(
        key="reactions_enabled",
        kind="toggle",
        label_key="god.control.reactions_enabled.label",
        description_key="god.control.reactions_enabled.desc",
        default=True,
        advanced=True,
        target="agents.initiative",
        path="reactions_enabled",
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
        target="agents.initiative",
        path="reasoning_effort",
    ),
    ControlSpec(
        key="layer_memory",
        kind="toggle",
        label_key="god.control.layer_memory.label",
        description_key="god.control.layer_memory.desc",
        default=True,
        advanced=True,
        target="agents.layers",
        path="memory",
    ),
    ControlSpec(
        key="layer_cognition",
        kind="toggle",
        label_key="god.control.layer_cognition.label",
        description_key="god.control.layer_cognition.desc",
        default=True,
        advanced=True,
        target="agents.layers",
        path="cognition",
    ),
    ControlSpec(
        key="layer_social",
        kind="toggle",
        label_key="god.control.layer_social.label",
        description_key="god.control.layer_social.desc",
        default=True,
        advanced=True,
        target="agents.layers",
        path="social",
    ),
    # ── P1 (docs/ui_panel.md §1.4): promoted mod/global settings ──
    ControlSpec(
        key="ui.language",
        kind="select",
        label_key="god.control.ui.language.label",
        description_key="god.control.ui.language.desc",
        default="auto",
        options=_ui_language_options(),
        advanced=True,
        target="ui",
        path="language",
    ),
    _promoted("llm.temperature", "slider", 0.8, target="llm", path="temperature",
              minimum=0.0, maximum=2.0, step=0.05),
    _promoted("llm.max_tokens", "slider", 700, target="llm", path="max_tokens",
              minimum=128, maximum=4096, step=64),
    _promoted("llm.budget_per_sim_per_day", "slider", 500, target="llm",
              path="budget_per_sim_per_day", minimum=0, maximum=2000, step=50),
    _promoted("memory.consolidation_enabled", "toggle", True, target="memory",
              path="consolidation_enabled"),
    _promoted("memory.decay_preset", "select", "normal", target="memory",
              path="decay_preset", options=_DECAY_PRESETS, option_prefix="god.decay"),
    _promoted("memory.dejavu_chance", "slider", 0.05, target="memory",
              path="dejavu_chance", minimum=0.0, maximum=0.5, step=0.01),
    _promoted("agents.personality.absorption_enabled", "toggle", True,
              target="agents.personality", path="absorption_enabled"),
    _promoted("agents.personality.salience_threshold", "slider", 1.5,
              target="agents.personality", path="salience_threshold",
              minimum=0.0, maximum=5.0, step=0.1),
    _promoted("agents.personality.sleep_consolidation", "toggle", True,
              target="agents.personality", path="sleep_consolidation"),
    _promoted("agents.evolution.enabled", "toggle", True,
              target="agents.evolution", path="enabled"),
    _promoted("agents.evolution.trait_swap", "select", "propose",
              target="agents.evolution", path="trait_swap",
              options=_TRAIT_SWAP_MODES, option_prefix="god.trait_swap"),
    _promoted("agents.evolution.drift_strength", "slider", 0.2,
              target="agents.evolution", path="drift_strength",
              minimum=0.0, maximum=1.0, step=0.05),
    _promoted("agents.social.max_pairs_per_tick", "slider", 1,
              target="agents.social", path="max_pairs_per_tick",
              minimum=0, maximum=4, step=1),
    _promoted("agents.social.pair_cooldown_seconds", "slider", 180,
              target="agents.social", path="pair_cooldown_seconds",
              minimum=30, maximum=600, step=30),
    # ── v0.4 P1/P3: speech + presence dials ──
    _promoted("agents.presence.visitor_agency", "select", "reactive",
              target="agents.presence", path="visitor",
              options=("reactive", "full", "off"), option_prefix="god.visitor"),
    _promoted("agents.speech.hearing_radius", "slider", 20.0,
              target="agents.speech", path="hearing_radius",
              minimum=0.0, maximum=80.0, step=5.0),
    _promoted("agents.speech.ambient_talk_chance", "slider", 0.08,
              target="agents.speech", path="ambient_talk_chance",
              minimum=0.0, maximum=0.5, step=0.01),
    _promoted("agents.speech.notify_thoughts", "toggle", True,
              target="agents.speech", path="notify_thoughts"),
    _promoted("god.backgrounds.enabled", "toggle", True,
              target="god.backgrounds", path="enabled"),
    _promoted("god.backgrounds.batch_size", "slider", 2,
              target="god.backgrounds", path="batch_size",
              minimum=1, maximum=10, step=1),
    _promoted("runtime.expose_roster", "toggle", True,
              target="runtime", path="expose_roster"),
    # Read once at startup → restart_only (hidden from the panel, never persisted).
    _promoted("runtime.shutdown_on_game_exit", "toggle", True,
              target="runtime", path="shutdown_on_game_exit", restart_only=True),
    _promoted("network.host", "select", "127.0.0.1", target="network", path="host",
              options=("127.0.0.1", "0.0.0.0"), option_prefix="god.network",
              restart_only=True),
]

CONTROL_SPEC_BY_KEY: dict[str, ControlSpec] = {spec.key: spec for spec in CONTROL_SPECS}

_POWER_PREFIX = "power_"


_MISSING = object()


def list_controls(
    include_advanced: bool = True, include_restart_only: bool = False
) -> list[ControlSpec]:
    """Return the control specs, optionally hiding advanced/restart-only ones."""
    return [
        spec
        for spec in CONTROL_SPECS
        if (include_advanced or not spec.advanced)
        and (include_restart_only or not spec.restart_only)
    ]


def get_control(key: str) -> ControlSpec | None:
    """Return a spec by key, or None."""
    return CONTROL_SPEC_BY_KEY.get(key)


def _resolve_target(settings: Any, target: str | None) -> Any:
    """Resolve a dotted ``Settings`` path (e.g. ``agents.personality``)."""
    obj = settings
    for part in (target or "").split("."):
        if not part:
            continue
        obj = getattr(obj, part, None)
        if obj is None:
            return None
    return obj


def _read_target(settings: Any, spec: ControlSpec) -> Any:
    """Read a spec's current value from its target/path (``_MISSING`` if absent)."""
    obj = _resolve_target(settings, spec.target)
    if obj is None:
        return _MISSING
    field = spec.path or spec.key
    if isinstance(obj, dict):
        return obj.get(field, _MISSING)
    return getattr(obj, field, _MISSING)


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
    # The active preset has no ControlSpec (it is a separate God field) but the
    # mod panel/commands want to display it, so surface it in the value map.
    preset = getattr(god_config, "preset", None)
    if preset:
        values["preset"] = preset
    powers = getattr(god_config, "powers", {}) or {}
    for power in POWER_KEYS:
        values[f"{_POWER_PREFIX}{power}"] = bool(powers.get(power, values[f"{_POWER_PREFIX}{power}"]))
    return values


def apply_values_to_god_config(values: dict[str, Any] | None) -> dict[str, Any]:
    """Map validated God control values into a ``GodConfig`` patch dict.

    Only specs whose ``target`` is a God path are consumed (promoted
    ``god.backgrounds`` etc. are applied by :func:`apply_values_to_settings`).
    """
    validated = validate_values(values)
    patch: dict[str, Any] = {}
    powers_patch: dict[str, bool] = {}
    settings_patch: dict[str, Any] = {}

    for key, value in validated.items():
        spec = CONTROL_SPEC_BY_KEY.get(key)
        target = spec.target if spec else None
        if target not in _GOD_PATCH_TARGETS:
            continue
        field = spec.path or key
        if target == "god.powers":
            powers_patch[field] = bool(value)
        elif target == "god.settings":
            settings_patch[field] = value
        else:
            patch[field] = value

    if powers_patch:
        patch["powers"] = powers_patch
    if settings_patch:
        patch["settings"] = settings_patch
    return patch


def values_from_settings(settings: Any) -> dict[str, Any]:
    """Full control-value map: God dials, agent-roster dials and §1.4 specs."""
    values = values_from_god_config(settings.god)
    agents = getattr(settings, "agents", None)
    if agents is not None:
        values["agent_seats"] = agents.seat_count
        values["impulse_frequency"] = agents.initiative.impulse_frequency
        values["player_sim_impulse_frequency"] = (
            agents.initiative.player_sim_impulse_frequency
        )
        values["reactions_enabled"] = bool(agents.initiative.reactions_enabled)
        values["reasoning_effort"] = (
            getattr(agents.initiative, "reasoning_effort", None)
            or getattr(settings.llm, "reasoning_effort", "none")
        )
        layers = getattr(agents, "layers", None)
        for key, attr in _LAYER_KEYS.items():
            values[key] = (
                bool(getattr(layers, attr, True)) if layers is not None else True
            )
        speech = getattr(agents, "speech", None)
        if speech is not None:
            values["agents.speech.hearing_radius"] = float(
                getattr(speech, "hearing_radius", 20.0)
            )
            values["agents.speech.ambient_talk_chance"] = float(
                getattr(speech, "ambient_talk_chance", 0.08)
            )
            values["agents.speech.notify_thoughts"] = bool(
                getattr(speech, "notify_thoughts", True)
            )
        presence = getattr(agents, "presence", None)
        if presence is not None:
            values["agents.presence.visitor_agency"] = str(
                getattr(presence, "visitor", "reactive")
            )
    # Promoted §1.4 specs: read directly from their target/path.
    for spec in CONTROL_SPECS:
        if spec.target in _GOD_PATCH_TARGETS or spec.target in _AGENT_PATCH_TARGETS:
            continue
        current = _read_target(settings, spec)
        if current is not _MISSING:
            values[spec.key] = current
    return values


def apply_values_to_agents_config(values: dict[str, Any] | None) -> dict[str, Any]:
    """Map validated agent-control values into an ``AgentsConfig`` patch dict.

    Returns ``{"agent_seats": int, "initiative": {...}, "layers": {...}}`` suitable
    for a shallow merge by the caller. Only agent-roster keys are consumed.
    """
    validated = validate_values(values)
    patch: dict[str, Any] = {}
    initiative: dict[str, Any] = {}
    layers: dict[str, Any] = {}
    maps: dict[str, dict[str, Any]] = {}
    for key, value in validated.items():
        spec = CONTROL_SPEC_BY_KEY.get(key)
        target = spec.target if spec else None
        if target not in _AGENT_PATCH_TARGETS:
            continue
        field = spec.path or key
        if target == "agents":
            patch[field] = int(value)
        elif target == "agents.initiative":
            if field in ("impulse_frequency", "player_sim_impulse_frequency"):
                initiative[field] = float(value)
            elif field == "reactions_enabled":
                initiative[field] = bool(value)
            elif field == "reasoning_effort":
                initiative[field] = str(value)
        elif target == "agents.layers":
            layers[field] = bool(value)
        elif target in _AGENT_MAP_TARGETS:
            group = target.split(".")[-1]
            maps.setdefault(group, {})[field] = value
    if initiative:
        patch["initiative"] = initiative
    if layers:
        patch["layers"] = layers
    patch.update(maps)
    return patch


def apply_agents_patch(agents: Any, patch: dict[str, Any]) -> None:
    """Shallow-merge a validated agent-control patch into ``AgentsConfig``."""
    if not patch:
        return
    if "agent_seats" in patch:
        agents.agent_seats = int(patch["agent_seats"])
    initiative = patch.get("initiative") or {}
    for key, value in initiative.items():
        if hasattr(agents.initiative, key):
            setattr(agents.initiative, key, value)
    layers = patch.get("layers") or {}
    for key, value in layers.items():
        if hasattr(agents.layers, key):
            setattr(agents.layers, key, value)
    for group in ("speech", "presence"):
        section = getattr(agents, group, None)
        if section is None:
            continue
        for key, value in (patch.get(group) or {}).items():
            if hasattr(section, key):
                setattr(section, key, value)


def apply_values_to_settings(
    settings: Any, values: dict[str, Any] | None
) -> dict[str, Any]:
    """Apply the promoted (target/path) control values to a live ``Settings``.

    God and agent-roster keys are ignored here; use
    :func:`apply_control_values_to_settings` for a full map. Returns the applied
    values. Unknown/invalid keys raise ``ValueError``.
    """
    validated = validate_values(values)
    applied: dict[str, Any] = {}
    for key, value in validated.items():
        spec = CONTROL_SPEC_BY_KEY[key]
        if (
            not spec.target
            or spec.target in _GOD_PATCH_TARGETS
            or spec.target in _AGENT_PATCH_TARGETS
        ):
            continue
        obj = _resolve_target(settings, spec.target)
        if obj is None:
            continue
        field = spec.path or key
        if isinstance(obj, dict):
            obj[field] = value
        else:
            setattr(obj, field, value)
        applied[key] = value
    return applied


def apply_control_values_to_settings(
    settings: Any, values: dict[str, Any] | None
) -> dict[str, Any]:
    """Validate and apply a flat control-value map to a live ``Settings``.

    Covers God dials/powers, agent-roster dials and the promoted §1.4 specs.
    Returns the validated values that were applied. Unknown/invalid keys raise
    ``ValueError``.
    """
    validated = validate_values(values)
    if not validated:
        return {}

    god = getattr(settings, "god", None)
    if god is not None:
        for key, value in apply_values_to_god_config(validated).items():
            if key == "powers":
                god.powers.update(value)
            elif key == "settings":
                god.settings.update(value)
            else:
                setattr(god, key, value)

    agents = getattr(settings, "agents", None)
    if agents is not None:
        apply_agents_patch(agents, apply_values_to_agents_config(validated))

    apply_values_to_settings(settings, validated)
    return validated


def controls_payload(
    include_advanced: bool = True, include_restart_only: bool = False
) -> list[dict[str, Any]]:
    """JSON-serializable spec list for ``GET /v1/god/controls``."""
    return [
        spec.model_dump()
        for spec in list_controls(include_advanced, include_restart_only)
    ]
