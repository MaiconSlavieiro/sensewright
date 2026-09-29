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