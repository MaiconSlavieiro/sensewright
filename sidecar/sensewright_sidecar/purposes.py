"""Canonical registry of the 33 Sensewright purposes.

Every purpose has: a stable id, a tier (driving SLO + token budget + concurrency),
an input/output token budget, a trigger description, the SQLite artifact it
produces and the in-game consumer/vehicle. No purpose produces orphan data: each
has a 0-key deterministic fallback registered in :mod:`sensewright_sidecar.fallbacks`.

This module is pure data — it must import nothing from the game and nothing from
the web framework so it can be reused by tests and by the Web Studio.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# Tier names. Budgets come from config.toml `[llm.tiers.*]`.
TIER_INTERACTIVE = "interactive"
TIER_REALTIME = "realtime"
TIER_BG = "bg"
TIER_DEEP = "deep"

# Purpose families (used for dedup keys and routing).
DOMAIN_SIM = "sim"
DOMAIN_GOD = "god"
DOMAIN_WORLD = "world"
DOMAIN_MEM = "mem"
DOMAIN_EVO = "evo"
DOMAIN_OPS = "ops"


@dataclass(frozen=True)
class Purpose:
    """A single LLM purpose with its routing contract."""

    id: str
    domain: str
    tier: str
    in_tokens: int
    out_tokens: int
    trigger: str
    artifact: str
    consumer: str
    # Fire-and-forget tools may be emitted by this purpose.
    may_emit_intents: bool = True
    # 0-key fallback key in the locale content table.
    fallback_key: Optional[str] = None


PURPOSES: List[Purpose] = [
    # ── Domain 1: sim.* (13) ────────────────────────────────────────────────
    Purpose("sim.chat", DOMAIN_SIM, TIER_INTERACTIVE, 1500, 250,
            "Phone / PC (sw.chat)", "memory thought + speech + intents",
            "Chat card + Hidden SimInfo", fallback_key="sim.chat"),
    Purpose("sim.profile", DOMAIN_SIM, TIER_BG, 600, 400,
            "New seat (bg) / chat (int)", "sims.profile (PROFILE_SHAPE)",
            "All sim prompts + GetToKnow", fallback_key="sim.profile"),
    Purpose("sim.impulse", DOMAIN_SIM, TIER_REALTIME, 700, 200,
            "Zone pulse (full tier)", "memory thought + 1 non-verbal intent",
            "Sim mood/action on lot", fallback_key="sim.impulse"),
    Purpose("sim.reaction", DOMAIN_SIM, TIER_REALTIME, 700, 200,
            "Event with salience >= 1.5", "memory thought + speak intent",
            "Immediate reaction to causer", fallback_key="sim.reaction"),
    Purpose("sim.social", DOMAIN_SIM, TIER_REALTIME, 800, 220,
            "Pair in conversation (pre-flight ok)", "{a_line, b_line, topic, impact}",
            "Compact dialogue card", fallback_key="sim.social"),
    Purpose("sim.social.close", DOMAIN_SIM, TIER_BG, 500, 120,
            "End of ConversationSession", "social memory + rumor contagion",
            "Social history + world.gossip", fallback_key="sim.social.close"),
    Purpose("sim.dream", DOMAIN_SIM, TIER_DEEP, 900, 250,
            "Start of sleep (1x/night)", "dream memory + dream_urge",
            "Sleep balloons + morning moodlet tooltip", fallback_key="sim.dream"),
    Purpose("sim.cognition", DOMAIN_SIM, TIER_DEEP, 1000, 300,
            "Post-dream / bootstrap", "profile.daily_plan + biases",
            "Commodity buffs + Web Studio", fallback_key="sim.cognition"),
    Purpose("sim.sleep", DOMAIN_SIM, TIER_DEEP, 1200, 350,
            "Sleep (if salient event)", "profile.psyche_blocks",
            "Sim prompts + evo.trait trigger", fallback_key="sim.sleep"),
    Purpose("sim.diary", DOMAIN_SIM, TIER_BG, 800, 200,
            "Write diary / end of day", "diary memory (1st person)",
            "Diary tooltip + Snoop", fallback_key="sim.diary"),
    Purpose("sim.lifestory", DOMAIN_SIM, TIER_DEEP, 1800, 400,
            "Every 7 sim days / mem.legacy", "profile.life_story",
            "ContextAssembler + physical book", fallback_key="sim.lifestory"),
    Purpose("sim.aspiration", DOMAIN_SIM, TIER_DEEP, 900, 250,
            "Aspiration change/milestone", "profile.ambition",
            "Mid-term goals in cognition", fallback_key="sim.aspiration"),
    Purpose("sim.background.expand", DOMAIN_SIM, TIER_BG, 1000, 400,
            "1x for family/close friends", "3 backstory memories",
            "Revealed via GetToKnow", fallback_key="sim.background.expand"),

    # ── Domain 2: god.* (8) ────────────────────────────────────────────────
    Purpose("god.zeitgeist", DOMAIN_GOD, TIER_BG, 600, 200,
            "Onboarding / panel edit", "neighborhoods.zeitgeist",
            "Dreams, weather, god.plan", fallback_key="god.zeitgeist"),
    Purpose("god.plan", DOMAIN_GOD, TIER_DEEP, 2500, 600,
            "No arc / end of arc", "arcs (beats + god_whisper_hint)",
            "god.scene + dream whispers", fallback_key="god.plan"),
    Purpose("god.cast", DOMAIN_GOD, TIER_BG, 800, 300,
            "Beat needs catalyst NPC", "arcs.cast (NpcSheet)",
            "spawn_npc lever (VisitSituation)", fallback_key="god.cast"),
    Purpose("god.scene", DOMAIN_GOD, TIER_BG, 1000, 350,
            "Beat enters armed", "beat.scene_draft + scene_subtext",
            "Prep catalyst objective for P18", fallback_key="god.scene"),
    Purpose("god.puppeteer", DOMAIN_GOD, TIER_REALTIME, 1200, 400,
            "Catalyst NPC + target on lot", "lease + approach + objective",
            "Controls catalyst + subtext", fallback_key="god.puppeteer"),
    Purpose("god.react", DOMAIN_GOD, TIER_REALTIME, 900, 250,
            "End of beat interaction", "branched next beat (pivot)",
            "Adapt arc to agent's choice", fallback_key="god.react"),
    Purpose("god.narration", DOMAIN_GOD, TIER_REALTIME, 400, 80,
            "Beat start / intervention", "1 atmospheric line (<=80 tok)",
            "SPECIAL_MOMENT banner", fallback_key="god.narration"),
    Purpose("god.background", DOMAIN_GOD, TIER_BG, 800, 300,
            "BackgroundScheduler queue", "sims.background",
            "Scene context + chronicles", fallback_key="god.background"),

    # ── Domain 3: world.* (4) ──────────────────────────────────────────────
    Purpose("world.npc.backstory", DOMAIN_WORLD, TIER_BG, 600, 250,
            "Recurring townie without story", "sims.background (NPC)",
            "Seed for profile + god.cast", fallback_key="world.npc.backstory"),
    Purpose("world.household.chronicle", DOMAIN_WORLD, TIER_BG, 1200, 300,
            "End of in-game day", "neighborhoods.chronicles",
            "Mailbox + ops.recap + god.plan", fallback_key="world.household.chronicle"),
    Purpose("world.gossip", DOMAIN_WORLD, TIER_BG, 700, 200,
            "Public salient event / snoop", "RumorNode in neighborhoods",
            "Social dialogues + phone SMS", fallback_key="world.gossip"),
    Purpose("world.aftermath", DOMAIN_WORLD, TIER_BG, 1000, 300,
            "Post-climax (salience >= 2.0)", "durable intents + zeitgeist shift",
            "Alters relations and weather", fallback_key="world.aftermath"),

    # ── Domain 4: mem.* (4) ────────────────────────────────────────────────
    Purpose("mem.consolidate", DOMAIN_MEM, TIER_BG, 1200, 300,
            "300s chat silence / zone change", "consolidated memory + player_facts",
            "FTS5 index + player bond", fallback_key="mem.consolidate"),
    Purpose("mem.compact", DOMAIN_MEM, TIER_DEEP, 2000, 400,
            ">= 20 consolidated memories", "compact memory (archive 15)",
            "Keeps context window lean", fallback_key="mem.compact"),
    Purpose("mem.legacy", DOMAIN_MEM, TIER_DEEP, 1200, 300,
            "Death, marriage, birth", "legacy memory (immune to decay)",
            "sim.lifestory + epitaph", fallback_key="mem.legacy"),
    Purpose("mem.relationship.review", DOMAIN_MEM, TIER_DEEP, 1000, 250,
            "Deep window (active edges)", "relationships.qualitative_note",
            "Native sentiments + chat/social", fallback_key="mem.relationship.review"),

    # ── Domain 5: evo.* (2) ────────────────────────────────────────────────
    Purpose("evo.reflect", DOMAIN_EVO, TIER_DEEP, 1200, 300,
            "Sleep (>=8 ev) / mirror", "updates current_demeanor",
            "Phase shift preserving core_personality", fallback_key="evo.reflect"),
    Purpose("evo.trait", DOMAIN_EVO, TIER_DEEP, 1000, 250,
            "Trauma/belief > 0.85 / habit", "likes/dislikes / trait swap",
            "trait_tracker + Accept banner", fallback_key="evo.trait"),

    # ── Domain 6: ops.* (2) ────────────────────────────────────────────────
    Purpose("ops.recap", DOMAIN_OPS, TIER_BG, 1000, 200,
            "lifecycle/session-start", "{headline, recap_text}",
            "\"Previously on...\" banner", fallback_key="ops.recap"),
    Purpose("ops.panel.summary", DOMAIN_OPS, TIER_BG, 600, 120,
            "State change / panel open", "2-line diagnostic summary",
            "Quick Menu header + Web Studio", fallback_key="ops.panel.summary"),
]


PURPOSE_BY_ID = {p.id: p for p in PURPOSES}


def get_purpose(purpose_id: str) -> Optional[Purpose]:
    """Return the purpose definition, or None for unknown ids."""
    return PURPOSE_BY_ID.get(purpose_id)


def purposes_in_domain(domain: str) -> List[Purpose]:
    """All purposes belonging to a given domain."""
    return [p for p in PURPOSES if p.domain == domain]


def purposes_in_tier(tier: str) -> List[Purpose]:
    """All purposes routed to a given tier."""
    return [p for p in PURPOSES if p.tier == tier]
