"""Tool registry: autonomy level to tool set mapping."""

from __future__ import annotations

from typing import Any

from .schemas import TOOL_SCHEMAS

# Autonomy level to allowed tools mapping (PLANO Appendix B + §14.2)
# minimal ≈ observe/suggest, moderate ≈ semi (+ buffs/spontaneous lines),
# full = full palette (+ automatic traits).
_READ_TOOLS = [
    "get_needs",
    "get_relationships",
    "get_inventory",
    "get_world_time",
    "nearby_sims",
    "world_state",
    "sim_profile",
]

AUTONOMY_TOOLS: dict[str, list[str]] = {
    "off": [],
    "observe": list(_READ_TOOLS),
    "suggest": [*_READ_TOOLS, "propose_action", "spontaneous_line"],
    "semi": [
        *_READ_TOOLS,
        "propose_action",
        "spontaneous_line",
        "queue_interaction",
        "move_to",
        "say_to",
        "socialize",
        "approach",
        "set_mood",
        "add_buff",
        "add_trait",
    ],
    "full": [
        *_READ_TOOLS,
        "propose_action",
        "spontaneous_line",
        "queue_interaction",
        "move_to",
        "say_to",
        "socialize",
        "approach",
        "set_mood",
        "act_out",
        "cancel_current",
        "add_buff",
        "add_trait",
    ],
}


def get_tool_schemas(level: str) -> dict[str, dict[str, Any]]:
    """Get tool schemas for a given autonomy level."""
    allowed = AUTONOMY_TOOLS.get(level, AUTONOMY_TOOLS["observe"])
    return {name: TOOL_SCHEMAS[name] for name in allowed if name in TOOL_SCHEMAS}


def get_allowed_tools(level: str) -> list[str]:
    """Get list of allowed tool names for a given autonomy level."""
    return AUTONOMY_TOOLS.get(level, AUTONOMY_TOOLS["observe"]).copy()


def is_tool_allowed(level: str, tool_name: str) -> bool:
    """Check if a tool is allowed at the given autonomy level."""
    return tool_name in AUTONOMY_TOOLS.get(level, AUTONOMY_TOOLS["observe"])