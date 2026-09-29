"""LLM impulse builder and deterministic fallback for the initiative loop.

The agency scheduler injects a runner that recalls memories/psyche; this module
turns a single impulse job into zero or more agent directives. The model may
emit tool calls and/or an internal thought (stored as an event by the runner,
so life evolves even when nothing visible happens). When no provider is
available, or it errors, a deterministic rule-based impulse keeps the loop
alive in native (0-key) mode.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4

from ..tools.registry import get_allowed_tools
from ..tools.schemas import TOOL_SCHEMAS
from .intents import intent_from_directive

logger = logging.getLogger(__name__)

# Output budget: impulses are one short line plus at most one tool call, but
# reasoning models spend part of the budget on hidden reasoning before the
# visible answer, so this must leave headroom (250 truncated the line).
IMPULSE_MAX_TOKENS = 600

# Tools the initiative loop may emit (beyond plain read tools). Filtered by the
# per-Sim autonomy mapping so minimal Sims can never act.
_INITIATIVE_TOOLS = (
    "spontaneous_line",
    "say_to",
    "socialize",
    "act_out",
    "set_mood",
    "approach",
    "queue_interaction",
    "move_to",
    "add_buff",
    "add_trait",
)

# An idle impulse may take at most one modest action.
_IDLE_LIMIT = 1

_SYSTEM = (
    "You are {name}, a Sim in The Sims 4. Everything you write is {name}'s own "
    "inner voice, in {lang}, in the first person.\n"
    "Write ONLY the sentence itself: no preamble, no headings, no labels, and "
    "never explain or restate these instructions or the scene.\n"
    "You may also call at most one tool if {name} would genuinely act right now."
)

_KIND_TASK = {
    "reaction": (
        "Something just happened around you. React as {name} right now: speak to "
        "the other Sim, shift your mood, take one action, or simply think."
    ),
    "idle": (
        "This is an ordinary moment in your day. Share one passing thought as "
        "{name}."
    ),
    "sleep": "You are drifting off to sleep. Do not call any tool.",
}

# Meta prefixes a model may prepend; dropped from the start, keeping the rest.
_LEADING_PREFIXES = (
    "here's a thought:",
    "here is a thought:",
    "here's a thinking process:",
    "here is a thinking process:",
    "thinking process:",
    "thought:",
    "private thought:",
    "my thought:",
)

# Fragments that betray a reasoning-trace dump or task narration instead of
# role-playing. Such thoughts are discarded (see ``_clean_thought``).
_META_MARKERS = (
    "the user",
    "as an ai",
    "language model",
    "the scenario",
    "the instructions",
    "the prompt",
    "i need to respond",
    "respond as sim",
    "i am sim ",
    "i am sim,",
    "i am sim.",
    "optionally take",
    "thinking process",
    "analyze user input",
    "chain of thought",
    "o usuario",
    "o usuário",
    "o cenário",
    "as instruções",
    "processo de pensamento",
)


def impulse_tools(autonomy: str) -> list[str]:
    """Return the initiative-friendly tool names allowed at ``autonomy``."""
    allowed = set(get_allowed_tools(autonomy))
    return [name for name in _INITIATIVE_TOOLS if name in allowed]


def _tool_schemas(autonomy: str) -> list[dict[str, Any]]:
    """Return OpenAI-style schemas for the initiative tools at ``autonomy``."""
    schemas: list[dict[str, Any]] = []
    for name in impulse_tools(autonomy):
        schema = TOOL_SCHEMAS.get(name)
        if schema:
            schemas.append(schema)
    return schemas


def build_impulse_prompt(
    *,
    job: Any,
    profile: dict[str, Any] | None,
    world: dict[str, Any] | None,
    memories: list[Any] | None,
    lang: str,
) -> list[dict[str, Any]]:
    """Build a compact OpenAI-style prompt for one impulse."""
    name = str((profile or {}).get("name") or f"Sim {job.sim_id}")
    lines = [f"Where you are right now: {_describe_world(world, job)}"]
    profile_text = _describe_profile(profile)
    if profile_text:
        lines.append(f"Who you are: {profile_text}")
    memory_text = _describe_memories(memories)
    if memory_text:
        lines.append(f"Recent memories: {memory_text}")
    lines.append(_KIND_TASK.get(job.kind, _KIND_TASK["idle"]))
    if job.kind == "reaction" and job.event:
        lines.append(f"What just happened: {json.dumps(job.event, ensure_ascii=False)}")
    lines.append(
        f"Now write only {name}'s thought itself (first person, 1-2 sentences). "
        "No preamble, no headings, no labels."
    )
    return [
        {"role": "system", "content": _SYSTEM.format(name=name, lang=lang)},
        {"role": "user", "content": "\n".join(lines)},
    ]


def rule_based_impulse(
    *,
    job: Any,
    profile: dict[str, Any] | None,
    world: dict[str, Any] | None,
    lang: str,
) -> dict[str, Any]:
    """Deterministic impulse used in native mode or when the LLM fails."""
    if job.kind == "sleep":
        # The graph runner owns sleep consolidation; the impulse itself is empty.
        return _with_intents(
            {"directives": [], "thought": "", "provider": None, "used_llm": False}, job
        )
    if job.kind == "reaction" and job.event:
        return _with_intents(_reaction_impulse(job, profile), job)
    thought = _idle_thought(job, profile)
    return _with_intents(
        {"directives": [], "thought": thought, "provider": None, "used_llm": False}, job
    )


def _with_intents(result: dict[str, Any], job: Any) -> dict[str, Any]:
    """Attach v0.3 §15.5 intents derived from the legacy directive list."""
    if result.get("intents"):
        return result
    intents: list[dict[str, Any]] = []
    for directive in result.get("directives") or []:
        intent = intent_from_directive(job.sim_id, directive)
        if intent is not None:
            intents.append(intent)
    result["intents"] = intents
    return result


# A reasoning model occasionally leaks its "thinking process" into the content
# (losing the actual line). Retry once before falling back to the deterministic
# impulse so a single bad sample does not silence the Sim.
_MAX_LLM_ATTEMPTS = 2


def _parse_impulse_response(job: Any, response: Any, allowed: set, limit: int):
    """Extract ``(directives, thought)`` from one LLM response."""
    directives: list[dict[str, Any]] = []
    for call in getattr(response, "tool_calls", ()) or ():
        name = str(getattr(call, "name", "") or "")
        if name not in allowed:
            continue
        directives.append(_directive_from_call(job, call))
        if len(directives) >= limit:
            break
    thought = _clean_thought(getattr(response, "text", ""))
    return directives, thought


async def build_impulse(
    *,
    job: Any,
    profile: dict[str, Any] | None,
    world: dict[str, Any] | None,
    memories: list[Any] | None,
    registry: Any,
    lang: str,
    autonomy: str,
    reasoning_effort: str | None = None,
) -> dict[str, Any]:
    """Build one impulse, falling back to the deterministic rules on any error."""
    if job.kind == "sleep":
        return _with_intents(
            {"directives": [], "thought": "", "provider": None, "used_llm": False}, job
        )
    if registry is None:
        return rule_based_impulse(job=job, profile=profile, world=world, lang=lang)

    messages = build_impulse_prompt(
        job=job, profile=profile, world=world, memories=memories, lang=lang
    )
    schemas = _tool_schemas(autonomy)
    allowed = set(impulse_tools(autonomy))
    limit = _IDLE_LIMIT if job.kind == "idle" else max(1, len(allowed))

    for attempt in range(_MAX_LLM_ATTEMPTS):
        try:
            response = await registry.complete(
                messages,
                lang=lang,
                tools=schemas or None,
                max_tokens=IMPULSE_MAX_TOKENS,
                reasoning_effort=reasoning_effort,
            )
        except Exception as exc:
            logger.warning("impulse LLM call failed (attempt %d): %s", attempt + 1, exc)
            break

        directives, thought = _parse_impulse_response(job, response, allowed, limit)
        if directives or thought:
            return _with_intents(
                {
                    "directives": directives,
                    "thought": thought,
                    "provider": getattr(response, "provider", None),
                    "used_llm": True,
                },
                job,
            )
        logger.info("impulse attempt %d produced no usable output; retrying", attempt + 1)

    return rule_based_impulse(job=job, profile=profile, world=world, lang=lang)


# ─── helpers ──────────────────────────────────────────────────────────


def _clean_thought(text: Any) -> str:
    """Return a usable in-character thought, or ``""`` for junk output.

    Reasoning models often prepend a meta prefix ("Here's a thought:"), leak
    their "thinking process", or return punctuation-only fragments ("", ")", ".")
    and meta narration ("The user gives a situation…"). A leading prefix is
    stripped and the rest kept; reasoning/meta content is dropped so the caller
    falls back to the deterministic impulse instead of storing junk.
    """
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    for prefix in _LEADING_PREFIXES:
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            lowered = cleaned.lower()
            break
    if not any(ch.isalnum() for ch in cleaned):
        return ""
    if any(marker in lowered for marker in _META_MARKERS):
        return ""
    return cleaned


def _directive_from_call(job: Any, call: Any) -> dict[str, Any]:
    args = getattr(call, "arguments", None)
    if not isinstance(args, dict):
        try:
            args = json.loads(args) if args else {}
        except (TypeError, ValueError):
            args = {}
    return {
        "id": str(getattr(call, "id", "") or uuid4().hex),
        "sim_id": job.sim_id,
        "name": str(getattr(call, "name", "")),
        "args": args,
        "thought": "",
        "narration": "",
        "priority": 0,
        "source": "agent",
    }


def _reaction_impulse(job: Any, profile: dict[str, Any] | None) -> dict[str, Any]:
    event = dict(job.event or {})
    event_type = str(event.get("type", "")).lower()
    target = event.get("target_sim_id") or event.get("target")
    name = str((profile or {}).get("name") or f"Sim {job.sim_id}")

    if target is not None and event_type in {"social", "chat", "interaction", "gossip"}:
        tool = "say_to"
        args: dict[str, Any] = {
            "message": f"{name} reacts to what just happened.",
            "target_sim_id": _as_int(target),
        }
        thought = "I have something to say about this."
    elif event_type in {"fire", "death", "disaster", "fight", "accident", "divorce"}:
        tool = "set_mood"
        args = {"mood": "tense", "reason": f"{name} reacts to a {event_type}."}
        thought = f"That {event_type} shakes me."
    else:
        tool = "spontaneous_line"
        args = {
            "text": f"{name} can't stop thinking about what just happened.",
            "audience": "self",
        }
        thought = "Something just happened; I have to react."

    directive = {
        "id": uuid4().hex,
        "sim_id": job.sim_id,
        "name": tool,
        "args": args,
        "thought": thought,
        "narration": "",
        "priority": 0,
        "source": "agent",
    }
    return {"directives": [directive], "thought": thought, "provider": None, "used_llm": False}


def _idle_thought(job: Any, profile: dict[str, Any] | None) -> str:
    name = str((profile or {}).get("name") or f"Sim {job.sim_id}")
    return f"{name} takes in the moment."


def _describe_profile(profile: dict[str, Any] | None) -> str:
    if not profile:
        return ""
    parts: list[str] = []
    for key in ("personality", "backstory", "speech_style", "goals", "quirks"):
        value = profile.get(key)
        if value:
            parts.append(str(value))
    # R4: the sleep-written daily plan shapes the awake impulses.
    from .cognition import render_plan

    plan = render_plan(profile)
    if plan:
        parts.append(plan)
    return " | ".join(parts)


def _describe_memories(memories: list[Any] | None) -> str:
    if not memories:
        return ""
    texts: list[str] = []
    for memory in memories[:5]:
        if isinstance(memory, dict):
            text = memory.get("text") or memory.get("content") or memory.get("summary") or ""
        else:
            text = getattr(memory, "text", "") or ""
        text = str(text).strip()
        if text:
            texts.append(text)
    return " | ".join(texts)


def _describe_world(world: dict[str, Any] | None, job: Any) -> str:
    world = world or {}
    zone = world.get("zone") or {}
    sims = world.get("sims") or {}

    others: list[str] = []
    for key, state in sims.items():
        if _as_int(state.get("sim_id", key)) == _as_int(job.sim_id):
            continue
        label = state.get("full_name") or str(key)
        mood = state.get("mood") or "neutral"
        others.append(f"{label} ({mood})")

    parts: list[str] = []
    if zone.get("time_of_day"):
        parts.append(f"time={zone['time_of_day']}")
    if zone.get("lot_type"):
        parts.append(f"lot={zone['lot_type']}")
    if zone.get("weather"):
        parts.append(f"weather={zone['weather']}")
    text = ", ".join(parts) if parts else "unknown place"
    if others:
        text += "; nearby: " + ", ".join(others[:6])
    return text


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
