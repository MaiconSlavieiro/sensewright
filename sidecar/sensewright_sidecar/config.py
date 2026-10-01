"""Sidecar configuration: loads ``config.toml`` + environment expansion.

The sidecar is packaged (PyInstaller) next to ``config.toml``. We resolve the
"home" directory in this order:

1. env ``SENSEWRIGHT_HOME``
2. folder of the frozen executable (``sys.executable``)
3. package root (development)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from . import content_i18n

_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")


def expand_env(value: Any) -> Any:
    """Recursively expand ``${VAR}`` / ``$VAR`` in strings/dicts/lists."""
    if isinstance(value, str):
        def _sub(m: re.Match[str]) -> str:
            name = m.group(1) or m.group(2)
            return os.environ.get(name, "")

        return _ENV_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    return value


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        import tomllib  # py>=3.11
    except ModuleNotFoundError:  # pragma: no cover - py3.10
        import tomli as tomllib  # type: ignore[no-redef]

    with path.open("rb") as fh:
        return tomllib.load(fh)


def resolve_home() -> Path:
    env = os.environ.get("SENSEWRIGHT_HOME")
    if env:
        return Path(env).expanduser().resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


class UiConfig(BaseModel):
    """Player-facing language. ``auto`` follows the game, falling back to en."""

    language: str = "auto"
    # Serve the built-in browser panel at ``/`` (see ``sensewright_sidecar.webui``).
    # It runs in any browser *alongside* the game. Turn it off to hide it, e.g.
    # when ``network.host`` is not loopback.
    web_panel: bool = True


class NetworkConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "data/sidecar.log"
    audit: str = "data/audit.log"


class ProviderConfig(BaseModel):
    enabled: bool = True
    # v0.5 follow-up A5: provider implementation to instantiate. When omitted the
    # block name is used (``openrouter``/``gemini``/...). Set ``type = "openai_compat"``
    # for a config-driven OpenAI-compatible endpoint (Groq, Cerebras, Ollama, ...).
    type: str | None = None
    model: str | None = None
    models: list[str] = Field(default_factory=list)
    api_key: str = ""
    # v0.5 follow-up A6: local endpoints (e.g. Ollama) need no key. When True the
    # provider is considered available with an empty ``api_key`` and no
    # ``Authorization`` header is sent.
    api_key_optional: bool = False
    base_url: str | None = None
    rpm: int | None = None
    rpd: int | None = None
    # v0.5 follow-up A4: allow/disallow dynamic ``GET /models`` discovery for this
    # provider. Zen/OpenCode's free tier returns HTTP 403 outside the OpenCode
    # client, so its discovery is disabled in the example config.
    discover_models: bool = True
    # When True, only models whose id marks them as free are ever used (e.g. an
    # OpenRouter id containing ``:free``). This is a hard billing guard: a
    # non-free model in the list is dropped instead of being called.
    free_only: bool = False
    # When True, the provider accepts the OpenAI-compatible ``reasoning``
    # parameter, so a per-request reasoning effort can be forwarded. Providers
    # that would reject it (or that have their own thinking control) leave this
    # False and only use ``extra``.
    supports_reasoning: bool = False
    # Gemini only (v0.5 follow-up): optional hidden-thinking budget forwarded as
    # ``generationConfig.thinkingConfig.thinkingBudget``. ``None`` (default) sends
    # nothing — required because Gemini 3.x rejects ``thinkingBudget=0`` with a
    # 400. Set 0 only for 2.5-era models that accept it.
    thinking_budget: int | None = None
    # v0.5 R1: a model that returns empty/None content (or a truncated answer
    # with no content) is a retryable failure. After this many consecutive
    # failures a model is temporarily retired (``model_cooldown_seconds``) so the
    # chain stops burning attempts on it. A success resets the counter.
    model_failure_threshold: int = 2
    model_cooldown_seconds: float = 120.0
    # v0.5 R2: models discovered dynamically (``GET /models``). Runtime-only;
    # not meant to be written to ``config.toml``.
    discovered_models: list[str] = Field(default_factory=list)
    extra: dict[str, Any] = Field(default_factory=dict)
    # Extra top-level body fields merged into every request (v0.4 P2). Same as
    # ``extra`` but named to make the passthrough intent explicit; both are
    # merged, with ``extra_body`` winning on conflicts.
    extra_body: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    chain: list[str] = Field(default_factory=lambda: ["openrouter", "opencode", "gemini"])
    budget_per_sim_per_day: int = 500
    temperature: float = 0.8
    max_tokens: int = 700
    # How much hidden reasoning the model may spend before its visible answer:
    # none | minimal | low | medium | high. Defaults to "none": agent impulses
    # are a single short line, and reasoning models otherwise burn the whole
    # output budget on a hidden "thinking process" (truncating the answer).
    reasoning_effort: str = "none"
    # v0.4 P2: post-generation language guard. ``strict`` retries once with a
    # reinforced directive, then falls back to a deterministic localized line;
    # ``off`` records the mismatch but never retries/falls back.
    language_policy: str = "strict"
    # v0.5 R2: dynamic free-model discovery (``GET /models``) that activates the
    # previously-dead ``auto_discover``. ``model_refresh_minutes=0`` disables it;
    # a model in cool-down is swapped for a discovered free model of the same
    # provider when ``auto_swap_models`` is set (never on an auth error).
    model_refresh_minutes: float = 30.0
    auto_swap_models: bool = True
    # v0.5 follow-up A3: minimum seconds between two *on-demand* refreshes
    # triggered by an all-providers failure. Stops a failing chain from
    # hammering ``GET /models`` and retrying on every single request. The
    # periodic refresh (``model_refresh_minutes``) is unaffected. 0 disables
    # the throttle.
    refresh_on_failure_min_seconds: float = 60.0
    # Optional per-purpose model override; when a purpose is present its list
    # wins over the "fast models first" heuristic (v0.5 R2).
    task_models: dict[str, list[str]] = Field(default_factory=dict)
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class MemoryConfig(BaseModel):
    provider: str = "sqlite"
    embedding_provider: str = "none"
    retention_days: int = 180
    # ── v0.2 M1: consolidation of raw chat turns into one memory ──
    # A silence window (seconds) before a dialogue is summarized into a single
    # ``consolidated_memory`` event; raw turns are archived, never deleted.
    consolidation_enabled: bool = True
    dialogue_idle_seconds: float = 300.0
    # ── v0.2 M2: graded forgetting ──
    # ``strength`` decays lazily on read; presets choose the lambda. Used
    # memories are touched back up; forgotten ones can resurface as déjà vu.
    decay_preset: str = "normal"  # fast | normal | slow
    weaken_threshold: float = 0.5
    forget_threshold: float = 0.2
    dejavu_chance: float = 0.05
    # Provider credentials (e.g. Cloudflare account_id/api_token). Kept as a
    # free-form map so new embedding backends need no schema change.
    embedding_provider_config: dict[str, str] = Field(default_factory=dict)


class InitiativeConfig(BaseModel):
    """Per-Sim initiative loop (A2/A3): cadence, triggers and quota pacing."""

    # minimal | moderate | full — how much freedom Sim agents get (see §14.2).
    level: str = "full"
    # The player's own Sim has its own (usually lower) initiative.
    player_sim_level: str = "suggest"
    cooldown_sim_minutes: float = 8.0
    event_react_threshold: float = 1.0
    spontaneous_lines: bool = True
    # Fraction of the provider free-tier RPM the agency scheduler may target.
    quota_fraction: float = 0.8
    max_impulses_per_tick: int = 1
    # ── v0.3 §15.6: impulse/thought frequency dial (0 = sleep-only) ──
    # The agent-roster panel adjusts these live; per-Sim overrides win.
    impulse_frequency: float = 0.2
    # The player's own household Sims are inhabited too (a nonzero default);
    # the player-priority lock in the mod still keeps the player in control.
    player_sim_impulse_frequency: float = 0.2
    # Salient event reactions stay on independently of the impulse dial.
    reactions_enabled: bool = True
    # v0.5 R3: fraction of the shared per-minute budget reserved for social
    # conversation turns. Social may spend the full budget (including the
    # reserve); idle impulses may only use the remainder (``1 - reserve``), so a
    # busy free tier never starves an ongoing conversation.
    social_reserve_fraction: float = 0.4
    # ── reasoning dial (per agent) ──
    # How much hidden reasoning an impulse may spend: none|minimal|low|medium|high.
    # ``None`` inherits ``[llm] reasoning_effort`` (low by default).
    reasoning_effort: str | None = None


class LayersConfig(BaseModel):
    """Per-layer enable toggles (v0.3 §15.11). A disabled layer degrades to the
    native deterministic path instead of running an LLM call."""

    memory: bool = True
    cognition: bool = True
    social: bool = True


class SocialConfig(BaseModel):
    """Sim<->sim dialogue channel (v0.3 R5, PLANO.md §15.3 L6)."""

    # Disjoint pairs that may start a conversation per zone pulse, and how long
    # a given pair is left alone before it can talk again (seconds).
    max_pairs_per_tick: int = 1
    pair_cooldown_seconds: float = 180.0
    # A dialogue now requires the two Sims to be in a *real* native conversation
    # (mutually targeting each other) and physically close, so agents never
    # "talk" telepathically across the lot. ``max_pair_distance`` is the maximum
    # lot-space distance (from the pulse ``location`` "x,y"); when a location is
    # missing the proximity check is skipped (the conversation gate still holds).
    require_conversation: bool = True
    max_pair_distance: float = 4.0
    # v0.4 P6: only pair Sims that share a room (engine room id from the pulse;
    # 0 = outside). When either room is unknown the check degrades to the
    # distance gate. This stops agents from "talking through walls".
    require_same_room: bool = True
    # v0.4 P6: keep a conversation session (and its dialogue) open while the
    # pulse queue still holds an interaction with the same Sim, instead of
    # closing early with a "goodbye" summary.
    keep_open_on_queued: bool = True
    # Output budget for the model-written exchange (two short lines).
    line_max_tokens: int = 200
    # v0.5 R3: a new turn only when the pair's interaction/queue changed since
    # the last turn, or when this many seconds elapsed with the session open.
    # Between beats the session stays open and silent (no repeated line per
    # pulse). 0 disables the interval gate (turn on every change).
    turn_min_interval_seconds: float = 25.0


class SpeechConfig(BaseModel):
    """SpeechPolicy: cadence + surface rules for every vocal output (v0.4 P1).

    ``min_interval_between_lines`` and ``max_lines_per_minute`` cap how often a
    line may reach the player; ``ambient_talk_chance`` is the per-opportunity
    probability of a discreet murmur; ``notify_thoughts`` decides whether
    murmurs are surfaced at all; ``hearing_radius`` is the lot-space distance
    from the active Sim within which a line may notify (0 = always "hear").
    """

    min_interval_between_lines: float = 30.0
    max_lines_per_minute: int = 12
    ambient_talk_chance: float = 0.08
    murmur_cooldown_seconds: float = 120.0
    notify_thoughts: bool = True
    hearing_radius: float = 20.0


class PresenceConfig(BaseModel):
    """PresencePolicy: who is "at home" vs a visitor (v0.4 P3).

    ``visitor`` is the agency tier for anyone outside the player's household:
    ``reactive`` (default: react to events + join an existing conversation, no
    idle impulse or directed speech), ``full`` (same as household) or ``off``
    (never inhabited). ``familiar_friendship`` is the relationship level from
    which a non-household Sim is considered a friend (they may react with
    speech and receive less-sanitized context).
    """

    visitor: str = "reactive"  # reactive | full | off
    familiar_friendship: float = 20.0


class ConversationsConfig(BaseModel):
    """Conversation sessions: multi-turn exchanges + summary (v0.4 P4/P4b)."""

    enabled: bool = True
    # Lines a single session may reach before it is closed naturally.
    max_turns: int = 4
    # Output budget for one session turn (the model writes one exchange).
    max_tokens: int = 220
    summary_enabled: bool = True
    leaving_summary: bool = True
    # A session with no new turn for this long is closed (seconds). Keep this
    # above ``agents.social.pair_cooldown_seconds`` so a session waiting for the
    # pair cooldown is not mistaken for an ended conversation.
    idle_seconds: float = 300.0


class PersonalityConfig(BaseModel):
    """Living personality: psyche blocks + sleep consolidation (P1)."""

    absorption_enabled: bool = True
    salience_threshold: float = 1.5
    max_traumas: int = 5
    max_beliefs: int = 10
    trauma_decay: str = "slow"  # fast | normal | slow
    sleep_consolidation: bool = True


class EvolutionConfig(BaseModel):
    """Batch reflection + personality drift + trait-swap policy (Phase 4)."""

    enabled: bool = True
    min_events: int = 8
    cooldown_seconds: float = 900.0
    max_reflections_per_day: int = 24
    # off = never propose, propose = store a proposal, auto = apply via directive.
    trait_swap: str = "propose"
    drift_strength: float = 0.2


class AgentsConfig(BaseModel):
    # Kept as an alias for installed configs; ``agent_seats`` (v0.3) wins when set.
    # v0.4 P3: the default pool drops to 6 (visitors are reactive, not inhabited).
    max_active: int = 6
    agent_seats: int | None = None
    evolution_speed: str = "normal"
    autonomy_default: str = "semi"
    # Safety rails: max directive tool calls per Sim per minute and how long the
    # player-priority lock holds after a player action (seconds).
    tool_calls_per_minute: int = 10
    player_lock_seconds: float = 10.0
    # Reflection/evolution loop (Phase 4).
    evolution: EvolutionConfig = Field(default_factory=EvolutionConfig)
    # v0.2 A1-A3: per-Sim initiative loop.
    initiative: InitiativeConfig = Field(default_factory=InitiativeConfig)
    # v0.2 P1: living personality (psyche + sleep consolidation).
    personality: PersonalityConfig = Field(default_factory=PersonalityConfig)
    # v0.3 §15.11: per-layer enable toggles.
    layers: LayersConfig = Field(default_factory=LayersConfig)
    # v0.3 R5: sim<->sim dialogue channel cadence.
    social: SocialConfig = Field(default_factory=SocialConfig)
    # v0.4 P1: vocal-output cadence + surface rules.
    speech: SpeechConfig = Field(default_factory=SpeechConfig)
    # v0.4 P3: visitor presence policy.
    presence: PresenceConfig = Field(default_factory=PresenceConfig)
    # v0.4 P4/P4b: conversation sessions + summary.
    conversations: ConversationsConfig = Field(default_factory=ConversationsConfig)

    @property
    def seat_count(self) -> int:
        """The agent-seat pool size (``agent_seats`` overriding ``max_active``)."""
        return int(self.agent_seats if self.agent_seats else self.max_active)


class RuntimeConfig(BaseModel):
    """Runtime-only surfaces exposed to the mod panel (v0.3 §15.11)."""

    expose_roster: bool = True
    # Lifecycle: shut the sidecar down when The Sims 4 exits so it never
    # lingers after the game closes. The mod passes its PID via
    # ``SENSEWRIGHT_GAME_PID`` when it spawns the sidecar; ``game_pid`` is a
    # manual override. ``watch_game_process_name`` watches by exe name instead
    # (a fallback for a sidecar started before the game; off by default because
    # it can false-positive during development).
    shutdown_on_game_exit: bool = True
    game_pid: int | None = None
    watch_game_process_name: bool = False
    game_process_name: str = "TS4_x64.exe"
    game_watch_interval_seconds: float = 2.0
    game_watch_grace_seconds: float = 5.0


class BackgroundsConfig(BaseModel):
    """Progressive batch pipeline that writes backgrounds off the request path.

    Backgrounds are Tier 2 work: they run on the free tier, active-zone Sims
    first, metered by a budgeter that is separate from the chat path.
    """

    enabled: bool = True
    batch_size: int = 2
    interval_seconds: float = 15.0
    idle_seconds: float = 30.0
    per_minute: int = 6
    daily_limit: int = 120
    max_queue: int = 200
    max_attempts: int = 2


class GodConfig(BaseModel):
    enabled: bool = False
    preset: str = "novela"
    intervention_frequency: float = 0.5
    intensity: float = 0.5
    # Neighborhood zeitgeist influence over backgrounds/mood (0..1 thermometer).
    mood_influence: float = 0.5
    # Orchestration dials (ControlSpec-driven; see god/controls.py).
    autonomy_degree: float = 0.5
    chaos_degree: float = 0.3
    # Slowest cadence between two God interventions (seconds); the frequency and
    # autonomy dials shorten it down to a 30 s floor (see god/orchestrator.py).
    base_interval_seconds: float = 600.0
    powers: dict[str, bool] = Field(default_factory=dict)
    # Free-form overrides validated against the ControlSpec registry.
    settings: dict[str, Any] = Field(default_factory=dict)
    # Progressive batch background pipeline (Phase 5b).
    backgrounds: BackgroundsConfig = Field(default_factory=BackgroundsConfig)


class Settings(BaseModel):
    ui: UiConfig = Field(default_factory=UiConfig)
    network: NetworkConfig = Field(default_factory=NetworkConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    memory: MemoryConfig = Field(default_factory=MemoryConfig)
    agents: AgentsConfig = Field(default_factory=AgentsConfig)
    god: GodConfig = Field(default_factory=GodConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)

    home: Path = Field(default_factory=resolve_home)
    config_path: Path | None = None
    lang: str = content_i18n.default_lang()

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def token_path(self) -> Path:
        return self.data_dir / "token"

    @property
    def runtime_path(self) -> Path:
        return self.data_dir / "runtime.json"

    def log_path(self) -> Path:
        return _abs(self.home, self.logging.file)

    def audit_path(self) -> Path:
        return _abs(self.home, self.logging.audit)


def _abs(base: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (base / p)


def load_settings(config_path: str | os.PathLike[str] | None = None) -> Settings:
    home = resolve_home()
    if config_path is not None:
        path = Path(config_path)
    else:
        path = Path(os.environ.get("SENSEWRIGHT_CONFIG", home / "config.toml"))

    raw = expand_env(_load_toml(path))
    settings = Settings(**raw, home=home, config_path=path)

    # Panel overlay (P1): data/panel.toml overrides config.toml for the
    # ControlSpec values changed from the in-game panel. Lazy imports avoid a
    # circular import (controls -> schemas -> ... on startup).
    try:
        from . import panel_store
        from .god.controls import apply_control_values_to_settings

        overrides = panel_store.load_overrides(settings.data_dir)
        if overrides:
            apply_control_values_to_settings(settings, overrides)
    except Exception:
        pass

    if not settings.lang or settings.lang == content_i18n.default_lang():
        # ``lang`` is the *resolved* language; the raw preference lives in ui.language.
        env_lang = os.environ.get("SENSEWRIGHT_LANG")
        if env_lang:
            settings.lang = env_lang
        elif settings.ui.language and settings.ui.language != "auto":
            settings.lang = settings.ui.language
    return settings
