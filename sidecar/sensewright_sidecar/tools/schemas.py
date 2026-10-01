"""Tool JSONSchema definitions (shared with the mod)."""

from __future__ import annotations

from typing import Any

# Tool schemas matching PLANO Appendix B
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "get_needs": {
        "type": "function",
        "function": {
            "name": "get_needs",
            "description": "Get the current Sim's motive levels (hunger, energy, bladder, hygiene, fun, social).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    "get_relationships": {
        "type": "function",
        "function": {
            "name": "get_relationships",
            "description": "Get the current Sim's relationships with other Sims.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_sim_id": {
                        "type": "integer",
                        "description": "Optional specific Sim to check relationship with.",
                    }
                },
                "required": [],
            },
        },
    },
    "get_inventory": {
        "type": "function",
        "function": {
            "name": "get_inventory",
            "description": "Get the current Sim's inventory contents.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    "get_world_time": {
        "type": "function",
        "function": {
            "name": "get_world_time",
            "description": "Get the current in-game time and date.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    "propose_action": {
        "type": "function",
        "function": {
            "name": "propose_action",
            "description": "Propose an action for the player to approve (suggest autonomy level).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Human-readable description of the proposed action.",
                    },
                    "interaction_name": {
                        "type": "string",
                        "description": "The interaction/affordance name to queue if approved.",
                    },
                    "target_sim_id": {
                        "type": "integer",
                        "description": "Optional target Sim ID.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this action fits the Sim's personality/situation.",
                    },
                },
                "required": ["action", "interaction_name", "reason"],
            },
        },
    },
    "queue_interaction": {
        "type": "function",
        "function": {
            "name": "queue_interaction",
            "description": "Queue an interaction for the Sim to perform (semi/full autonomy).",
            "parameters": {
                "type": "object",
                "properties": {
                    "interaction_name": {
                        "type": "string",
                        "description": "The interaction/affordance name to queue.",
                    },
                    "target_sim_id": {
                        "type": "integer",
                        "description": "Optional target Sim ID.",
                    },
                    "target_object_id": {
                        "type": "integer",
                        "description": "Optional target object ID.",
                    },
                    "priority": {
                        "type": "integer",
                        "description": "Queue priority (higher = more urgent).",
                        "default": 0,
                    },
                },
                "required": ["interaction_name"],
            },
        },
    },
    "move_to": {
        "type": "function",
        "function": {
            "name": "move_to",
            "description": "Make the Sim walk to a location or near another Sim/object.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "number", "description": "World X coordinate."},
                    "y": {"type": "number", "description": "World Y coordinate."},
                    "z": {"type": "number", "description": "World Z coordinate."},
                    "target_sim_id": {
                        "type": "integer",
                        "description": "Optional: move near this Sim instead of coordinates.",
                    },
                    "target_object_id": {
                        "type": "integer",
                        "description": "Optional: move near this object instead of coordinates.",
                    },
                    "routing_surface": {
                        "type": "integer",
                        "description": "Routing surface ID (floor level).",
                        "default": 0,
                    },
                },
                "required": [],
            },
        },
    },
    "say_to": {
        "type": "function",
        "function": {
            "name": "say_to",
            "description": "Make the Sim say something to another Sim (social interaction).",
            "parameters": {
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "What the Sim says.",
                    },
                    "target_sim_id": {
                        "type": "integer",
                        "description": "Target Sim ID.",
                    },
                    "tone": {
                        "type": "string",
                        "enum": ["friendly", "romantic", "funny", "mean", "awkward", "serious"],
                        "description": "Tone of the interaction.",
                        "default": "friendly",
                    },
                },
                "required": ["message", "target_sim_id"],
            },
        },
    },
    "cancel_current": {
        "type": "function",
        "function": {
            "name": "cancel_current",
            "description": "Cancel the Sim's current interaction (full autonomy only).",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Why the interaction is being cancelled.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
    "add_buff": {
        "type": "function",
        "function": {
            "name": "add_buff",
            "description": "Add a buff/moodlet to the Sim to color its emotional state.",
            "parameters": {
                "type": "object",
                "properties": {
                    "buff_name": {
                        "type": "string",
                        "description": "The buff/moodlet name to add.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this buff fits the Sim's situation.",
                    },
                },
                "required": ["buff_name", "reason"],
            },
        },
    },
    "add_trait": {
        "type": "function",
        "function": {
            "name": "add_trait",
            "description": "Add a trait to the Sim (long-term personality change).",
            "parameters": {
                "type": "object",
                "properties": {
                    "trait_name": {
                        "type": "string",
                        "description": "The trait name to add.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this trait fits the Sim's long-term story.",
                    },
                },
                "required": ["trait_name", "reason"],
            },
        },
    },
    # ─── v0.2: autonomous Sim-agent tools (§14.2) ─────────────────────
    "spontaneous_line": {
        "type": "function",
        "function": {
            "name": "spontaneous_line",
            "description": "Surface an unprompted thought or line from the Sim as a notification.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "What the Sim thinks or says unprompted.",
                    },
                    "audience": {
                        "type": "string",
                        "description": "Who hears it: self, nearby, or a target Sim ID as text.",
                        "default": "self",
                    },
                    "tone": {
                        "type": "string",
                        "enum": ["neutral", "happy", "sad", "angry", "flirty", "worried"],
                        "description": "Emotional color of the line.",
                        "default": "neutral",
                    },
                },
                "required": ["text"],
            },
        },
    },
    "set_mood": {
        "type": "function",
        "function": {
            "name": "set_mood",
            "description": "Color the Sim's mood by applying a buff/moodlet (short-term emotion).",
            "parameters": {
                "type": "object",
                "properties": {
                    "mood": {
                        "type": "string",
                        "description": "Desired mood label (mapped to a buff by the mod).",
                    },
                    "buff_name": {
                        "type": "string",
                        "description": "Optional explicit buff/moodlet name.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this mood fits the moment.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
    "act_out": {
        "type": "function",
        "function": {
            "name": "act_out",
            "description": "Perform an autonomous action driven by the Sim's own agenda (full initiative).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "description": "Human-readable action the Sim wants to take.",
                    },
                    "interaction_name": {
                        "type": "string",
                        "description": "Optional affordance to queue for the action.",
                    },
                    "target_sim_id": {
                        "type": "integer",
                        "description": "Optional target Sim.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why the Sim acts on its own.",
                    },
                },
                "required": ["action", "reason"],
            },
        },
    },
    "socialize": {
        "type": "function",
        "function": {
            "name": "socialize",
            "description": "Initiate a social interaction with another Sim on the Sim's own initiative.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_sim_id": {
                        "type": "integer",
                        "description": "The Sim to socialize with.",
                    },
                    "tone": {
                        "type": "string",
                        "enum": ["friendly", "romantic", "funny", "mean", "awkward", "serious"],
                        "description": "Tone of the interaction.",
                        "default": "friendly",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why the Sim seeks this interaction.",
                    },
                },
                "required": ["target_sim_id", "reason"],
            },
        },
    },
    "approach": {
        "type": "function",
        "function": {
            "name": "approach",
            "description": "Walk the Sim toward another Sim or object on the Sim's own initiative.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_sim_id": {
                        "type": "integer",
                        "description": "The Sim to approach.",
                    },
                    "target_object_id": {
                        "type": "integer",
                        "description": "Optional object to approach instead.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why the Sim approaches.",
                    },
                },
                "required": ["reason"],
            },
        },
    },
    "nearby_sims": {
        "type": "function",
        "function": {
            "name": "nearby_sims",
            "description": "List the Sims currently instanced near the Sim (read-only).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    "world_state": {
        "type": "function",
        "function": {
            "name": "world_state",
            "description": "Read the zone context: time, lot type, weather and occupancy (read-only).",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    "sim_profile": {
        "type": "function",
        "function": {
            "name": "sim_profile",
            "description": "Read another Sim's public state (profile, mood, relationships).",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_sim_id": {
                        "type": "integer",
                        "description": "The Sim whose public profile to read.",
                    },
                },
                "required": ["target_sim_id"],
            },
        },
    },
}


def get_all_tool_schemas() -> dict[str, dict[str, Any]]:
    """Get all tool schemas."""
    return TOOL_SCHEMAS.copy()


# ─── v0.3 R3: intent schemas (PLANO.md §15.5/§15.9 row 5) ─────────────
# The agent emits *intents* (a bias toward an action) instead of imperative
# commands. These OpenAI-style schemas let the impulse LLM express an intent
# directly; the command palette in ``TOOL_SCHEMAS`` stays as the escape hatch.
INTENT_KINDS: tuple[str, ...] = (
    "bias_interaction",
    "prefer_target",
    "set_mood",
    "set_goal",
    "approach",
    "speak",
    "remember",
    "forget",
)

INTENT_SCHEMAS: dict[str, dict[str, Any]] = {
    "bias_interaction": {
        "type": "function",
        "function": {
            "name": "bias_interaction",
            "description": "Bias the Sim toward a kind of interaction (a nudge, not a command).",
            "parameters": {
                "type": "object",
                "properties": {
                    "interaction_kind": {
                        "type": "string",
                        "description": "The flavor of interaction to favor (e.g. friendly, romantic, playful).",
                    },
                    "target_sim_id": {"type": "integer", "description": "Optional target Sim."},
                    "strength": {
                        "type": "number",
                        "description": "How strong the bias is (0..1).",
                        "default": 0.4,
                    },
                },
                "required": ["interaction_kind"],
            },
        },
    },
    "prefer_target": {
        "type": "function",
        "function": {
            "name": "prefer_target",
            "description": "Favor another Sim as the target of the Sim's actions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_sim_id": {"type": "integer", "description": "The Sim to favor."},
                    "reason": {"type": "string", "description": "Why this Sim matters now."},
                },
                "required": ["target_sim_id", "reason"],
            },
        },
    },
    "set_mood": {
        "type": "function",
        "function": {
            "name": "set_mood",
            "description": "Color the Sim's mood by applying a buff (short-term emotion).",
            "parameters": {
                "type": "object",
                "properties": {
                    "mood": {"type": "string", "description": "Desired mood label."},
                    "buff_name": {"type": "string", "description": "Optional explicit buff name."},
                    "reason": {"type": "string", "description": "Why this mood fits the moment."},
                },
                "required": ["reason"],
            },
        },
    },
    "set_goal": {
        "type": "function",
        "function": {
            "name": "set_goal",
            "description": "Adopt a goal or long-term intention that shapes the Sim's day.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {"type": "string", "description": "The goal to pursue."},
                    "reason": {"type": "string", "description": "Why this goal matters."},
                },
                "required": ["goal", "reason"],
            },
        },
    },
    "approach": {
        "type": "function",
        "function": {
            "name": "approach",
            "description": "Walk the Sim toward another Sim or object.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_sim_id": {"type": "integer", "description": "The Sim to approach."},
                    "target_object_id": {"type": "integer", "description": "Optional object to approach."},
                    "reason": {"type": "string", "description": "Why the Sim approaches."},
                },
                "required": ["reason"],
            },
        },
    },
    "speak": {
        "type": "function",
        "function": {
            "name": "speak",
            "description": "Have the Sim say a short line to another Sim (or aloud).",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What the Sim says."},
                    "target_sim_id": {"type": "integer", "description": "Optional target Sim."},
                    "tone": {
                        "type": "string",
                        "enum": ["friendly", "romantic", "funny", "mean", "awkward", "serious"],
                        "default": "friendly",
                    },
                },
                "required": ["text"],
            },
        },
    },
    "remember": {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Record something the Sim wants to hold on to.",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "What to remember."},
                    "importance": {
                        "type": "number",
                        "description": "How important it is (0..2).",
                        "default": 1.0,
                    },
                },
                "required": ["text"],
            },
        },
    },
    "forget": {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Let go of a memory the Sim no longer wants to hold.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to forget (a short description)."},
                    "target_sim_id": {"type": "integer", "description": "Optional Sim to forget about."},
                },
                "required": ["query"],
            },
        },
    },
}


def get_intent_schemas(kinds: tuple[str, ...] | list[str] | None = None) -> dict[str, dict[str, Any]]:
    """Return the intent schemas, optionally restricted to ``kinds``."""
    if kinds is None:
        return INTENT_SCHEMAS.copy()
    return {kind: INTENT_SCHEMAS[kind] for kind in kinds if kind in INTENT_SCHEMAS}


def get_all_intent_schemas() -> list[dict[str, Any]]:
    """Return the intent schemas as a list (OpenAI ``tools`` payload)."""
    return [INTENT_SCHEMAS[kind] for kind in INTENT_KINDS]