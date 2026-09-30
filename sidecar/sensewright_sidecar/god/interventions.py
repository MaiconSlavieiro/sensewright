"""God agent intervention deck and presets."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Intervention:
    """A single intervention the God agent can perform."""

    id: str
    name: str
    description: str
    type: str  # spawn_npc, apply_trait, force_social, gossip, relationship_shift, extreme_event
    weight: float = 1.0
    min_intensity: float = 0.0
    max_intensity: float = 1.0
    cooldown_seconds: float = 300.0
    payload_template: dict[str, Any] = None

    def __post_init__(self):
        if self.payload_template is None:
            self.payload_template = {}


# Preset decks
PRESETS: dict[str, dict[str, Any]] = {
    "novela": {
        "name": "Soap Opera",
        "description": "Dramatic relationships, secrets, betrayals, and emotional confrontations.",
        "intervention_frequency": 0.5,
        "intensity": 0.6,
        "powers": {
            "spawn_npc": True,
            "apply_trait": True,
            "force_social": True,
            "gossip": True,
            "relationship_shift": True,
            "extreme_events": False,
        },
        "interventions": [
            Intervention(
                id="novela_secret_revealed",
                name="Secret Revealed",
                description="A Sim's secret is exposed to another Sim.",
                type="gossip",
                weight=1.5,
                min_intensity=0.4,
                payload_template={"topic": "secret", "spread": True},
            ),
            Intervention(
                id="novela_affair_discovered",
                name="Affair Discovered",
                description="A romantic betrayal comes to light.",
                type="relationship_shift",
                weight=1.0,
                min_intensity=0.6,
                payload_template={"delta": -50, "reason": "betrayal"},
            ),
            Intervention(
                id="novela_dramatic_confrontation",
                name="Dramatic Confrontation",
                description="Force a heated argument between two Sims.",
                type="force_social",
                weight=1.2,
                min_intensity=0.5,
                payload_template={"interaction": "argue", "intensity": "high"},
            ),
            Intervention(
                id="novela_new_rival",
                name="New Rival Arrives",
                description="Spawn an NPC rival for a Sim.",
                type="spawn_npc",
                weight=0.8,
                min_intensity=0.5,
                payload_template={"role": "rival", "traits": ["jealous", "ambitious"]},
            ),
            Intervention(
                id="novela_pregnancy_scare",
                name="Pregnancy Scare",
                description="A Sim thinks they might be pregnant.",
                type="apply_trait",
                weight=0.5,
                min_intensity=0.7,
                payload_template={"trait": "pregnant_scare", "duration": "temporary"},
            ),
        ],
    },
    "sitcom": {
        "name": "Sitcom",
        "description": "Light-hearted misunderstandings, comedic situations, and happy endings.",
        "intervention_frequency": 0.4,
        "intensity": 0.4,
        "powers": {
            "spawn_npc": True,
            "apply_trait": True,
            "force_social": True,
            "gossip": True,
            "relationship_shift": True,
            "extreme_events": False,
        },
        "interventions": [
            Intervention(
                id="sitcom_misunderstanding",
                name="Comedic Misunderstanding",
                description="A harmless misunderstanding creates awkward comedy.",
                type="force_social",
                weight=1.5,
                min_intensity=0.2,
                payload_template={"interaction": "awkward_chat", "tone": "funny"},
            ),
            Intervention(
                id="sitcom_wacky_neighbor",
                name="Wacky Neighbor Visits",
                description="An eccentric neighbor drops by unannounced.",
                type="spawn_npc",
                weight=1.0,
                min_intensity=0.3,
                payload_template={"role": "neighbor", "traits": ["goofball", "outgoing"]},
            ),
            Intervention(
                id="sitcom_cooking_disaster",
                name="Cooking Disaster",
                description="A Sim's cooking attempt goes hilariously wrong.",
                type="apply_trait",
                weight=0.8,
                min_intensity=0.3,
                payload_template={"trait": "bad_cook", "duration": "scene"},
            ),
            Intervention(
                id="sitcom_lost_item",
                name="Lost Item Panic",
                description="A Sim frantically searches for something trivial.",
                type="force_social",
                weight=0.7,
                min_intensity=0.2,
                payload_template={"interaction": "search_help", "item": "random"},
            ),
        ],
    },
    "drama": {
        "name": "Slow Drama",
        "description": "Realistic life struggles, gradual relationship changes, and character growth.",
        "intervention_frequency": 0.3,
        "intensity": 0.5,
        "powers": {
            "spawn_npc": True,
            "apply_trait": True,
            "force_social": True,
            "gossip": True,
            "relationship_shift": True,
            "extreme_events": False,
        },
        "interventions": [
            Intervention(
                id="drama_career_crisis",
                name="Career Crisis",
                description="A Sim faces a difficult career decision.",
                type="apply_trait",
                weight=1.0,
                min_intensity=0.4,
                payload_template={"trait": "career_uncertainty", "duration": "long"},
            ),
            Intervention(
                id="drama_friendship_drift",
                name="Friendship Drifting Apart",
                description="Two close friends slowly grow distant.",
                type="relationship_shift",
                weight=1.2,
                min_intensity=0.3,
                payload_template={"delta": -10, "reason": "drift", "gradual": True},
            ),
            Intervention(
                id="drama_health_scare",
                name="Health Scare",
                description="A Sim receives concerning medical news.",
                type="apply_trait",
                weight=0.6,
                min_intensity=0.5,
                payload_template={"trait": "health_worry", "duration": "medium"},
            ),
        ],
    },
    "caos": {
        "name": "Total Chaos",
        "description": "Maximum unpredictability - fires, aliens, random traits, total mayhem.",
        "intervention_frequency": 0.8,
        "intensity": 0.9,
        "powers": {
            "spawn_npc": True,
            "apply_trait": True,
            "force_social": True,
            "gossip": True,
            "relationship_shift": True,
            "extreme_events": True,
        },
        "interventions": [
            Intervention(
                id="chaos_fire",
                name="House Fire",
                description="A fire breaks out on the lot.",
                type="extreme_event",
                weight=1.0,
                min_intensity=0.7,
                payload_template={"event": "fire", "severity": "major"},
            ),
            Intervention(
                id="chaos_alien_abduction",
                name="Alien Abduction",
                description="A Sim is abducted by aliens.",
                type="extreme_event",
                weight=0.5,
                min_intensity=0.8,
                payload_template={"event": "alien_abduction"},
            ),
            Intervention(
                id="chaos_random_trait",
                name="Random Trait Swap",
                description="A Sim gains a completely random trait.",
                type="apply_trait",
                weight=1.5,
                min_intensity=0.5,
                payload_template={"trait": "random", "duration": "permanent"},
            ),
            Intervention(
                id="chaos_mass_fight",
                name="Mass Brawl",
                description="Everyone on the lot starts fighting.",
                type="force_social",
                weight=1.0,
                min_intensity=0.8,
                payload_template={"interaction": "fight", "target": "all"},
            ),
        ],
    },
    "terror": {
        "name": "Light Horror",
        "description": "Spooky atmosphere, ghostly encounters, and eerie events (no graphic content).",
        "intervention_frequency": 0.35,
        "intensity": 0.55,
        "powers": {
            "spawn_npc": True,
            "apply_trait": True,
            "force_social": True,
            "gossip": True,
            "relationship_shift": True,
            "extreme_events": False,
        },
        "interventions": [
            Intervention(
                id="terror_ghost_sighting",
                name="Ghost Sighting",
                description="A Sim sees a ghostly figure.",
                type="spawn_npc",
                weight=1.0,
                min_intensity=0.4,
                payload_template={"role": "ghost", "traits": ["paranormal", "mysterious"]},
            ),
            Intervention(
                id="terror_strange_noises",
                name="Strange Noises at Night",
                description="Unexplained sounds disturb a Sim's sleep.",
                type="apply_trait",
                weight=1.2,
                min_intensity=0.3,
                payload_template={"trait": "spooked", "duration": "night"},
            ),
            Intervention(
                id="terror_cursed_object",
                name="Cursed Object Found",
                description="A Sim finds an object with a dark history.",
                type="apply_trait",
                weight=0.8,
                min_intensity=0.5,
                payload_template={"trait": "cursed", "duration": "long"},
            ),
        ],
    },
}


def get_preset(name: str) -> dict[str, Any] | None:
    """Get a preset by name."""
    return PRESETS.get(name.lower())


def list_presets() -> list[str]:
    """List available preset names."""
    return list(PRESETS.keys())


def get_interventions_for_preset(preset_name: str, intensity: float) -> list[Intervention]:
    """Get filtered interventions for a preset at given intensity."""
    preset = get_preset(preset_name)
    if not preset:
        return []

    interventions = preset.get("interventions", [])
    return [
        i for i in interventions
        if i.min_intensity <= intensity <= i.max_intensity
    ]