"""Shared mod <-> sidecar wire contract (v1).

These models are the single source of truth for the protocol. The JSON field
names here are mirrored in the mod (``mod/simssense_mod``), which builds the
payloads by hand because it runs on Python 3.7 without pydantic.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AutonomyLevel = Literal["off", "observe", "suggest", "semi", "full"]
ResetScope = Literal["session", "sim", "save", "all"]

# Supported UI/content languages. English is the default and the fallback.
DEFAULT_LANG = "en"
SUPPORTED_LANGS = ("en", "pt-BR")

# Mood tags for the neighborhood zeitgeist (God agent, Phase 5a).
MOOD_TAGS = (
    "novela",
    "sitcom",
    "drama",
    "caos",
    "terror",
    "romance",
    "filme_adolescente",
)


def normalize_lang(value: str | None) -> str:
    """Return a supported BCP-47 tag, falling back to English."""
    if not value:
        return DEFAULT_LANG
    raw = value.strip()
    lowered = raw.lower()
    if lowered == "en" or lowered.startswith("en-"):
        return "en"
    if lowered in ("pt-br", "pt_br", "ptbr", "pt"):
        return "pt-BR"
    return DEFAULT_LANG


class SimRef(BaseModel):
    """Stable identity of a Sim within a save."""

    player_id: str = "local"
    save_id: str = "unknown"
    sim_id: int = 0
    household_id: int | None = None


class ToolCall(BaseModel):
    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    sim: SimRef
    message: str
    context: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    lang: str = DEFAULT_LANG


class HeyRequest(BaseModel):
    sim: SimRef
    context: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    lang: str = DEFAULT_LANG


class ChatResponse(BaseModel):
    """Reply to a chat/hey request.

    ``reply`` is LLM content already produced in the requested ``lang``.
    ``message_key``/``message_args`` carry *system* text for the mod to render
    through its locale table (``i18n.t``) when there is no LLM reply.
    """

    reply: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    in_character_error: bool = False
    message_key: str | None = None
    message_args: dict[str, Any] = Field(default_factory=dict)


class ToolResultRequest(BaseModel):
    tool_call_id: str
    ok: bool
    result: Any = None
    error: str | None = None


class AckResponse(BaseModel):
    ok: bool = True
    detail: str | None = None


class ResetRequest(BaseModel):
    scope: ResetScope = "session"
    sim: SimRef | None = None


class AutonomyConfigRequest(BaseModel):
    sim: SimRef
    level: AutonomyLevel


class LangConfigRequest(BaseModel):
    lang: str = DEFAULT_LANG


class GodConfigRequest(BaseModel):
    preset: str | None = None
    intervention_frequency: float | None = Field(default=None, ge=0.0, le=1.0)
    intensity: float | None = Field(default=None, ge=0.0, le=1.0)
    mood_influence: float | None = Field(default=None, ge=0.0, le=1.0)
    autonomy_degree: float | None = Field(default=None, ge=0.0, le=1.0)
    chaos_degree: float | None = Field(default=None, ge=0.0, le=1.0)
    enabled: bool | None = None
    powers: dict[str, bool] | None = None
    # Free-form ControlSpec-validated overrides (e.g. evolution_speed).
    settings: dict[str, Any] | None = None


class EventRecord(BaseModel):
    sim: SimRef
    type: str
    content: dict[str, Any] = Field(default_factory=dict)
    importance: float = 1.0
    ts: float | None = None
    lang: str = DEFAULT_LANG
    # "agent" for game/Sim-originated events, "god" for world events the God
    # broadcasts (see PLANO.md §14.5). The agents react to God events but the
    # God never reacts to its own events.
    source: str = "agent"


class EventIngestRequest(BaseModel):
    events: list[EventRecord] = Field(default_factory=list)


class PlayerActivityRequest(BaseModel):
    sim: SimRef


# ─── Lifecycle: the sidecar exits with the game ───────────────────────


class LifecycleAttachRequest(BaseModel):
    """Arm the game-process watchdog on the caller's game PID."""

    pid: int


class LifecycleResponse(BaseModel):
    ok: bool = True
    watching: bool = False
    pid: int | None = None


# ─── God agent: zeitgeist, backgrounds, controls, census ──────────────


class Zeitgeist(BaseModel):
    """Neighborhood storytelling/mood layer (first layer of meaning)."""

    mood_tags: list[str] = Field(default_factory=list)
    free_text: str = ""
    rewritten_text: str = ""
    mood_influence: float = Field(default=0.5, ge=0.0, le=1.0)
    configured: bool = False
    updated_at: float | None = None


class ZeitgeistResponse(BaseModel):
    ok: bool = True
    zeitgeist: Zeitgeist = Field(default_factory=Zeitgeist)


class ZeitgeistRequest(BaseModel):
    sim: SimRef
    mood_tags: list[str] = Field(default_factory=list)
    free_text: str = ""
    mood_influence: float = Field(default=0.5, ge=0.0, le=1.0)
    lang: str = DEFAULT_LANG


class ZeitgeistSuggestRequest(BaseModel):
    sim: SimRef
    mood_tags: list[str] = Field(default_factory=list)
    free_text: str = ""
    lang: str = DEFAULT_LANG


class ZeitgeistSuggestResponse(BaseModel):
    ok: bool = True
    suggested_text: str = ""
    mood_tags: list[str] = Field(default_factory=list)
    provider: str | None = None
    message_key: str | None = None


class BackgroundRequest(BaseModel):
    sim: SimRef
    scope: Literal["sim", "household"] = "sim"
    household_id: int | None = None
    player_hints: str = ""
    census: dict[str, Any] | None = None
    force: bool = False
    lang: str = DEFAULT_LANG


class BackgroundResponse(BaseModel):
    ok: bool = True
    scope: str = "sim"
    sim_id: int = 0
    household_id: int | None = None
    background: dict[str, Any] = Field(default_factory=dict)
    cached: bool = False
    provider: str | None = None
    message_key: str | None = None


class CensusSim(BaseModel):
    sim_id: int
    full_name: str = ""
    household_id: int | None = None
    traits: list[str] = Field(default_factory=list)
    age: str = ""
    gender: str = ""
    career: str = ""
    skills: dict[str, Any] = Field(default_factory=dict)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    is_player: bool = False


class CensusHousehold(BaseModel):
    household_id: int
    name: str = ""
    members: list[int] = Field(default_factory=list)
    funds: int = 0


class CensusRequest(BaseModel):
    sim: SimRef
    scope: Literal["active_zone", "full_save"] = "active_zone"
    sims: list[CensusSim] = Field(default_factory=list)
    households: list[CensusHousehold] = Field(default_factory=list)
    lang: str = DEFAULT_LANG


class CensusResponse(BaseModel):
    ok: bool = True
    sims: int = 0
    households: int = 0
    queued: int = 0
    message_key: str | None = None


class ControlsResponse(BaseModel):
    ok: bool = True
    controls: list[dict[str, Any]] = Field(default_factory=list)
    values: dict[str, Any] = Field(default_factory=dict)


class GodTickRequest(BaseModel):
    """One God-orchestration tick for a save (Phase 5c)."""

    sim: SimRef
    time_of_day: str = "unknown"
    lot_type: str = "residential"
    lang: str = DEFAULT_LANG


class GodDirective(BaseModel):
    """A directive produced by the God orchestrator.

    ``tool_call`` is present when the mod can execute the intervention; when it
    is absent the directive is a broadcast world/knowledge event (``source=god``)
    the Sim agents react to.
    """

    id: str
    type: str
    target_sim: int | None = None
    priority: int = 0
    payload: dict[str, Any] = Field(default_factory=dict)
    narration: str = ""
    tool_call: ToolCall | None = None
    source: str = "god"


class GodTickResponse(BaseModel):
    ok: bool = True
    enabled: bool = False
    preset: str = ""
    directives: list[GodDirective] = Field(default_factory=list)
    message_key: str | None = None


# ─── Phase 3/4: profiles, evolution, budget ───────────────────────────


class ProfileRequest(BaseModel):
    """Generate a Sim profile from a one-sentence seed (Phase 3)."""

    sim: SimRef
    seed: str = ""
    hints: str = ""
    native: dict[str, Any] | None = None
    force: bool = False
    lang: str = DEFAULT_LANG


class ProfileResponse(BaseModel):
    ok: bool = True
    sim_id: int = 0
    profile: dict[str, Any] = Field(default_factory=dict)
    provider: str | None = None
    cached: bool = False
    message_key: str | None = None


class Reflection(BaseModel):
    """Output of one reflection pass."""

    text: str = ""
    insights: list[str] = Field(default_factory=list)
    personality: str = ""
    source: str = "template"
    generated_at: float = 0.0


class EvolveRequest(BaseModel):
    """Run the reflection/evolution loop (Phase 4)."""

    sim: SimRef | None = None
    scope: Literal["sim", "save"] = "sim"
    force: bool = False
    lang: str = DEFAULT_LANG


class EvolveResponse(BaseModel):
    ok: bool = True
    scope: str = "sim"
    reflected: int = 0
    skipped: int = 0
    results: list[dict[str, Any]] = Field(default_factory=list)
    message_key: str | None = None


class HealthResponse(BaseModel):
    ok: bool = True
    version: str
    uptime_s: float
    lang: str = DEFAULT_LANG


# ─── v0.2: Autonomous Sim Agents (PLANO.md §14) ───────────────────────

InitiativeLevel = Literal["minimal", "moderate", "full"]
DirectiveSource = Literal["agent", "god"]


class ZoneContext(BaseModel):
    """Coarse zone-level context for the agency loop (§14.2)."""

    time_of_day: str = "unknown"
    lot_type: str = "residential"
    weather: str = ""
    zone_id: str = ""


class AutonomySimState(BaseModel):
    """Lightweight per-Sim state sampled by the zone pulse."""

    sim_id: int
    full_name: str = ""
    household_id: int | None = None
    mood: str = "neutral"
    needs: dict[str, Any] = Field(default_factory=dict)
    location: str = ""
    current_interaction: str = ""
    sleeping: bool = False
    is_player: bool = False
    autonomy: str = "semi"
    relationships: list[dict[str, Any]] = Field(default_factory=list)


class AutonomyTickRequest(BaseModel):
    """Fire-and-forget zone pulse; updates the cache and schedules impulses."""

    sim: SimRef
    zone: ZoneContext = Field(default_factory=ZoneContext)
    sims: list[AutonomySimState] = Field(default_factory=list)
    lang: str = DEFAULT_LANG


class SocialLine(BaseModel):
    """One spoken line of a sim<->sim dialogue (v0.3 R5)."""

    speaker: Literal["a", "b"] = "a"
    text: str = ""
    tone: str = "friendly"


class SocialDialogue(BaseModel):
    """A short exchange between two seated agent Sims (v0.3 R5)."""

    a: int = 0
    b: int = 0
    lines: list[SocialLine] = Field(default_factory=list)
    topic: str = ""
    source: str = "template"  # template | llm


class AutonomyTickResponse(BaseModel):
    ok: bool = True
    scheduled: int = 0
    sleeping: list[int] = Field(default_factory=list)
    social: list[SocialDialogue] = Field(default_factory=list)
    message_key: str | None = None


class DirectiveItem(BaseModel):
    """A pending per-Sim directive the mod pulls and executes (§14.2)."""

    id: str
    sim_id: int
    name: str  # mod tool name to execute
    args: dict[str, Any] = Field(default_factory=dict)
    thought: str = ""
    narration: str = ""
    priority: int = 0
    source: DirectiveSource = "agent"


class DirectivesResponse(BaseModel):
    ok: bool = True
    directives: list[DirectiveItem] = Field(default_factory=list)
    message_key: str | None = None


# ─── v0.3: Inhabited Agents (PLANO.md §15) — seats + intents ──────────


class SeatInfo(BaseModel):
    """One occupied agent seat (inhabitation layer L2)."""

    sim_id: int
    tier: str = "visitor"  # household | visitor
    household_id: int | None = None
    is_player: bool = False
    since: float = 0.0
    impulse_frequency: float | None = None


class RosterResponse(BaseModel):
    """Live seat occupancy exposed to the agent-roster panel."""

    ok: bool = True
    save_id: str = "unknown"
    seats: int = 0
    used: int = 0
    agents: list[SeatInfo] = Field(default_factory=list)


class SeatAssignRequest(BaseModel):
    """Manually adjust the seat pool and/or a per-Sim impulse frequency."""

    sim: SimRef
    seats: int | None = None
    sim_id: int | None = None
    impulse_frequency: float | None = Field(default=None, ge=0.0, le=1.0)


class IntentItem(BaseModel):
    """A pending intent the mod's ``GameLever`` adapter translates (§15.5).

    Legacy directive keys (``name``/``args``/``thought``/``narration``) are kept
    so the command escape hatch and the ``/v1/autonomy/directives`` alias work.
    """

    id: str
    sim_id: int
    kind: str = "command"
    target_sim_id: int | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""
    expires_at: Any = "next_sleep"
    priority: int = 0
    source: DirectiveSource = "agent"
    name: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    thought: str = ""
    narration: str = ""


class IntentResponse(BaseModel):
    ok: bool = True
    intents: list[IntentItem] = Field(default_factory=list)
    message_key: str | None = None


class NeighborhoodAggregates(BaseModel):
    """Aggregated neighborhood state the God may read (never psyches/secrets)."""

    population: int = 0
    household_count: int = 0
    households: dict[str, int] = Field(default_factory=dict)
    mood_distribution: dict[str, int] = Field(default_factory=dict)
    mood: str = "neutral"
    tension: float = 0.0
    funds: int = 0


class AggregatesResponse(BaseModel):
    ok: bool = True
    save_id: str = "unknown"
    neighborhood: NeighborhoodAggregates = Field(default_factory=NeighborhoodAggregates)


class StatusResponse(BaseModel):
    ok: bool = True
    sidecar_version: str
    uptime_s: float
    lang: str = DEFAULT_LANG
    providers: list[dict[str, Any]] = Field(default_factory=list)
    chain_health: dict[str, Any] = Field(default_factory=dict)
    autonomy: dict[str, Any] = Field(default_factory=dict)
    memory: dict[str, Any] = Field(default_factory=dict)
    god: dict[str, Any] = Field(default_factory=dict)
    rails: dict[str, Any] = Field(default_factory=dict)
    backgrounds: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    agency: dict[str, Any] = Field(default_factory=dict)
    personality: dict[str, Any] = Field(default_factory=dict)
