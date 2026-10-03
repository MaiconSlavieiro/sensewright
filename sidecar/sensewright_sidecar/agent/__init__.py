"""Agent package for the Sensewright sidecar (sim.* domain)."""
from __future__ import annotations

from .chat import (
    build_chat_context, extract_thought, family_relation_label, is_deferred,
    strip_thought, trust_delta, trust_level,
)
from .cognition import apply_cognition, build_cognition_context, extract_autonomy_biases
from .dreams import build_dream_context, surrealism_index
from .evolution import (
    apply_reflection, build_reflect_context, build_trait_context,
    extract_preference_change, extract_trait_proposal,
)
from .impulse import (
    build_impulse_context, build_reaction_context, physical_actions_allowed,
)
from .intents import normalize_intent, validate_intent
from .presence import (
    capabilities, excluded_from_seats, hard_blocked_social, presence_tier,
    sensory_only,
)
from .profile import enforce_life_story, normalize_profile, template_profile
from .psyche import (
    block_for_category, compute_salience, decay_blocks, is_salient,
    reinforce_block, strongest_block,
)
from .seats import SeatManager
from .sleep import sleep_transition
from .social import (
    action_context, are_family, build_social_context, coerce_float,
    has_rumor_to_spread, location_context, preflight, relationship_context,
    relationship_tier, relationship_value,
)
from .speech import record_speech, resolve_limits, speech_allowed

__all__ = [
    "build_chat_context", "extract_thought", "family_relation_label",
    "is_deferred", "strip_thought", "trust_delta", "trust_level",
    "apply_cognition", "build_cognition_context", "extract_autonomy_biases",
    "build_dream_context", "surrealism_index",
    "apply_reflection", "build_reflect_context", "build_trait_context",
    "extract_preference_change", "extract_trait_proposal",
    "build_impulse_context", "build_reaction_context", "physical_actions_allowed",
    "normalize_intent", "validate_intent",
    "capabilities", "excluded_from_seats", "presence_tier", "sensory_only",
    "enforce_life_story", "normalize_profile", "template_profile",
    "block_for_category", "compute_salience", "decay_blocks", "is_salient",
    "reinforce_block", "strongest_block",
    "SeatManager",
    "sleep_transition",
    "action_context", "are_family", "build_social_context", "coerce_float",
    "hard_blocked_social", "has_rumor_to_spread", "location_context", "preflight",
    "relationship_context", "relationship_tier", "relationship_value",
    "record_speech", "resolve_limits", "speech_allowed",
]
