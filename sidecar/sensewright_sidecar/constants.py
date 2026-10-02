"""Domain constants shared across the Sensewright sidecar.

These encode the deterministic, language-independent weights and capability
rules that the spec mandates (event salience by structured metadata, capability
matrix by species/age, God presets, etc.). They are pure data and must never
depend on the web framework or on the game.
"""
from __future__ import annotations

from typing import Dict, Tuple

# ── Event salience weights (REQ-PSY-01) ────────────────────────────────────
# Salience = base weight of event_category + emitted `impact` (0..2).
# Events with salience >= 1.5 generate or reinforce Psyche Blocks.
EVENT_CATEGORY_WEIGHTS: Dict[str, float] = {
    "death": 2.5,
    "betrayal": 2.2,
    "fire": 2.0,
    "marriage": 1.9,
    "birth": 1.9,
    "romance": 1.6,
    "promotion": 1.4,
    "fight": 1.3,
    "friendship": 1.1,
    "gift": 1.0,
    "mundane": 0.5,
}

#: Lifecycle event categories that produce a decay-immune legacy memory (P28).
LEGACY_CATEGORIES: Tuple[str, ...] = ("death", "marriage", "birth")

SALIENCE_THRESHOLD = 1.5
AFTERMATH_SALIENCE_THRESHOLD = 2.0
PSYCHE_PRUNE_THRESHOLD = 0.05
PSYCHE_TRAIT_SWAP_INTENSITY = 0.85
PSYCHE_TRAIT_SWAP_DAYS = 3

# ── Capability Matrix (REQ-PRE-02) ─────────────────────────────────────────
# Species excluded from SeatManager entirely.
EXCLUDED_FROM_SEATS = ("BABY",)

# Species/age that only produce instinctual thought + set_mood (no verbal social,
# no career). Blocked from F04 verbal social and F07 career.
SENSORY_ONLY = ("INFANT", "TODDLER", "DOG", "CAT", "HORSE")

# Social categories hard-blocked for CHILD sims.
CHILD_HARD_BLOCKED_CATEGORIES = ("flirty", "intimate")

# ── Presence tiers ─────────────────────────────────────────────────────────
PRESENCE_FULL = "full"
PRESENCE_REACTIVE = "reactive"
PRESENCE_OFF = "off"

# Friendship threshold to promote a visitor from reactive -> full.
FULL_PRESENCE_FRIENDSHIP = 20.0

# ── God Director ───────────────────────────────────────────────────────────
GOD_PRESETS: Tuple[str, ...] = (
    "novela", "sitcom", "drama", "caos", "terror", "romance", "filme_adolescente",
)

GOD_DIALS: Tuple[str, ...] = (
    "intervention_frequency", "intensity", "mood_influence", "autonomy_degree", "chaos_degree",
)

GOD_MODES: Tuple[str, ...] = ("AUTONOMOUS", "CO_DIRECTOR", "SANDBOX")

# ── Control lease priority (REQ-COORD-*) ───────────────────────────────────
LEASE_PLAYER_MANUAL = "PLAYER_MANUAL"
LEASE_GOD_CATALYST_PUPPET = "GOD_CATALYST_PUPPET"
LEASE_SOVEREIGN_AGENT = "SOVEREIGN_AGENT"
LEASE_SANDBOX_OVERRIDE = "SANDBOX_OVERRIDE"

# Priority order: 1 = highest. PLAYER_MANUAL always wins.
LEASE_PRIORITY: Dict[str, int] = {
    LEASE_PLAYER_MANUAL: 1,
    LEASE_GOD_CATALYST_PUPPET: 2,
    LEASE_SOVEREIGN_AGENT: 3,
    LEASE_SANDBOX_OVERRIDE: 4,
}

# ── Dream engine weights ───────────────────────────────────────────────────
DREAM_WEIGHTS: Dict[str, float] = {
    "day_residue": 0.40,
    "deja_vu_shadow": 0.25,
    "god_whisper": 0.20,
    "zeitgeist": 0.15,
}

DREAM_ARCHETYPES: Tuple[str, ...] = ("epiphany", "surreal", "omen", "nightmare")

# ── Social layer ───────────────────────────────────────────────────────────
SOCIAL_MAX_DISTANCE_M = 4.0
# Speech policy defaults (overridable via config.toml gameplay section).
SPEECH_DEFAULTS = {
    "hearing_radius_m": 20.0,
    "max_lines_per_minute": 12,
    "min_interval_between_lines_seconds": 30,
}

# ── Memory retention ───────────────────────────────────────────────────────
MEMORY_PRUNE_DAYS = 180
LIFE_STORY_MAX_LINES = 20
LIFE_STORY_MAX_CHARS = 2000
LIFE_STORY_CONTEXT_LINES = 5
#: Consolidated memories required before a mem.compact run (P27).
CONSOLIDATED_COMPACT_THRESHOLD = 20
#: Oldest consolidated memories archived per compaction.
COMPACT_ARCHIVE_COUNT = 15

# ── Dual-clock conversion ──────────────────────────────────────────────────
#: The mod's autonomy pulse reports 1000 ticks per sim-minute (see
#: ``mod/sensewright_mod/main.py``). Used to convert sim-clock spans to days.
TICKS_PER_SIM_MINUTE = 1000
TICKS_PER_SIM_SECOND = TICKS_PER_SIM_MINUTE / 60.0
#: Sim-minutes in one in-game day (used for psyche decay / reflect cadence).
SIM_MINUTES_PER_DAY = 1440
TICKS_PER_SIM_DAY = SIM_MINUTES_PER_DAY * TICKS_PER_SIM_MINUTE

#: God Director intervention roll cadence (one rolled plan per sim-day window).
GOD_PLAN_WINDOW_TICKS = TICKS_PER_SIM_DAY
