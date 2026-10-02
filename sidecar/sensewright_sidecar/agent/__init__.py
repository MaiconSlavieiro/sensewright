"""Agent package for the Sensewright sidecar (sim.* domain)."""
from __future__ import annotations

from .chat import (
    build_chat_context, extract_thought, is_deferred, strip_thought,
    trust_delta, trust_level,
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
from .presence import capabilities, excluded_from_seats, presence_tier, sensory_only
from .profile import normalize_profile, template_profile
from .psyche import (
    block_for_category, compute_salience, decay_blocks, is_salient,
    reinforce_block, strongest_block,
)
from .seats import SeatManager
from .social import build_social_context, has_rumor_to_spread, preflight

__all__ = [
    "build_chat_context", "extract_thought", "is_deferred", "strip_thought",
    "trust_delta", "trust_level",
    "apply_cognition", "build_cognition_context", "extract_autonomy_biases",
    "build_dream_context", "surrealism_index",
    "apply_reflection", "build_reflect_context", "build_trait_context",
    "extract_preference_change", "extract_trait_proposal",
    "build_impulse_context", "build_reaction_context", "physical_actions_allowed",
    "normalize_intent", "validate_intent",
    "capabilities", "excluded_from_seats", "presence_tier", "sensory_only",
    "normalize_profile", "template_profile",
    "block_for_category", "compute_salience", "decay_blocks", "is_salient",
    "reinforce_block", "strongest_block",
    "SeatManager",
    "build_social_context", "has_rumor_to_spread", "preflight",
]
