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
import re
from collections import namedtuple
from typing import Any
from uuid import uuid4

from .. import content_i18n
from ..llm import langguard
from ..tools.registry import get_allowed_tools
from ..tools.schemas import TOOL_SCHEMAS
from .intents import intent_from_directive

logger = logging.getLogger(__name__)

# Output budget: impulses are one short line plus at most one tool call, but
# reasoning models spend part of the budget on hidden reasoning before the
# visible answer, so this must leave headroom (250/600 truncated the line and
# silenced the agent; several hundred reasoning tokens are not unusual).
IMPULSE_MAX_TOKENS = 900

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

# v0.4 P1: idle impulses never *speak*. Speech comes from a conversation session
# (P4), a reaction with a target, or player chat — never an idle monologue.
_SPEECH_TOOLS = frozenset({"spontaneous_line", "say_to", "socialize"})
# Movement levers are not reliable enough yet; keep them out of the idle palette
# so the single idle impulse is not wasted on a ``not_implemented`` command.
_MOVEMENT_TOOLS = frozenset({"approach", "move_to"})

# An idle impulse may take at most one modest action.
_IDLE_LIMIT = 1

_SYSTEM = (
    "You are {name}, a Sim in The Sims 4. Everything you write is {name}'s own "
    "inner voice, in {lang}, in the first person.\n"
    "Decide what {name} does RIGHT NOW and express it with a tool call:\n"
    "- If {name} speaks to someone, changes mood, goes somewhere, or takes any "
    "action, call exactly one tool to do it.\n"
    "- Only if {name} would do nothing at all, reply with one short in-character "
    "thought as plain text (no tool).\n"
    "Never explain your reasoning, never restate these instructions, and never "
    "output a thinking process."
)

_KIND_TASK = {
    "reaction": (
        "Something just happened around you. React as {name} right now: if "
        "{name} would speak, move, change mood or act, call exactly one tool; "
        "otherwise write one short thought as {name}."
    ),
    "idle": (
        "This is an ordinary moment in your day. {name} does NOT start talking "
        "here. If {name} would take a concrete action (change mood, do "
        "something), call exactly one tool now; otherwise stay quiet and share "
        "one passing inner thought as {name}."
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
# role-playing. Such thoughts are discarded (see ``_clean_thought``). The tokens
# live in the ``sys.meta_markers`` content-locale key of every locale and are
# unioned here, so adding a language also extends the meta filter.
_META_MARKERS_CACHE: tuple[str, ...] | None = None

# v0.4 P5: strip stage directions / *actions* from an impulse thought so it reads
# as a private inner line, never as narrated role-play.
_STAGE_DIRECTION_RE = re.compile(r"\*[^*\n]{0,120}\*")


def _meta_markers() -> tuple[str, ...]:
    global _META_MARKERS_CACHE
    if _META_MARKERS_CACHE is None:
        markers: list[str] = []
        for code in content_i18n.available_locales():
            value = content_i18n.t(code, "sys.meta_markers")
            if value == "sys.meta_markers":
                continue
            for line in value.split("\n"):
                if line:
                    markers.append(line.lower())
        _META_MARKERS_CACHE = tuple(markers)
    return _META_MARKERS_CACHE


def impulse_tools(autonomy: str, kind: str | None = None) -> list[str]:
    """Return the initiative-friendly tool names allowed at ``autonomy``.

    ``kind`` narrows the palette per impulse: idle impulses never get speech or
    unreliable movement tools (v0.4 P1); sleep gets none.
    """
    if kind == "sleep":
        return []
    blocked: frozenset[str] = frozenset()
    if kind == "idle":
        blocked = _SPEECH_TOOLS | _MOVEMENT_TOOLS
    allowed = set(get_allowed_tools(autonomy))
    return [name for name in _INITIATIVE_TOOLS if name in allowed and name not in blocked]


def _tool_schemas(autonomy: str, kind: str | None = None) -> list[dict[str, Any]]:
    """Return OpenAI-style schemas for the initiative tools at ``autonomy``."""
    schemas: list[dict[str, Any]] = []
    for name in impulse_tools(autonomy, kind):
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
    lines.append(_KIND_TASK.get(job.kind, _KIND_TASK["idle"]).format(name=name))
    if job.kind == "reaction" and job.event:
        lines.append(f"What just happened: {json.dumps(job.event, ensure_ascii=False)}")
    lines.append(
        f"Now choose: call one tool if {name} acts right now, or reply with one "
        f"short first-person thought as {name} (no preamble, no labels)."
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
        return _with_intents(_reaction_impulse(job, profile, lang), job)
    thought = _idle_thought(job, profile, lang)
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


# A tool call recovered from free text (models that cannot emit native
# ``tool_calls``). Shaped like ``LLMToolCall`` so ``_directive_from_call`` reads
# it identically via ``getattr``.
_TextCall = namedtuple("_TextCall", "id name arguments")


def _iter_balanced_json(text: str):
    """Yield substrings of ``text`` that parse as JSON (arrays or objects)."""
    for start, ch in enumerate(text):
        if ch not in "[{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for end in range(start, len(text)):
            current = text[end]
            if in_string:
                if escaped:
                    escaped = False
                elif current == "\\":
                    escaped = True
                elif current == '"':
                    in_string = False
                continue
            if current == '"':
                in_string = True
            elif current in "[{":
                depth += 1
            elif current in "]}":
                depth -= 1
                if depth == 0:
                    yield text[start : end + 1]
                    break


def _json_tool_dicts(value: Any):
    """Recursively yield tool-call dicts (those carrying a ``name``)."""
    if isinstance(value, dict):
        if value.get("name") and not isinstance(value.get("name"), dict):
            yield value
            return
        for item in value.values():
            yield from _json_tool_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _json_tool_dicts(item)


def _text_tool_calls(text: Any, allowed: set) -> list[Any]:
    """Best-effort tool calls embedded in an LLM text response."""
    raw = str(text or "")
    if not raw or "name" not in raw:
        return []
    calls: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for span in _iter_balanced_json(raw):
        try:
            parsed = json.loads(span)
        except (TypeError, ValueError):
            continue
        for item in _json_tool_dicts(parsed):
            name = str(item.get("name") or "")
            if name not in allowed:
                continue
            arguments = (
                item.get("arguments")
                or item.get("parameters")
                or item.get("args")
                or item.get("input")
                or {}
            )
            # Nested balanced spans repeat the same call; keep it once. (Also
            # avoids rescuing the same JSON printed inside an outer array.)
            try:
                signature = (name, json.dumps(arguments, sort_keys=True, default=str))
            except (TypeError, ValueError):
                signature = (name, str(arguments))
            if signature in seen:
                break
            seen.add(signature)
            calls.append(_TextCall(str(item.get("id") or uuid4().hex), name, arguments))
            break
    return calls


def _parse_impulse_response(job: Any, response: Any, allowed: set, limit: int):
    """Extract ``(directives, thought)`` from one LLM response.

    Native OpenAI ``tool_calls`` are preferred. Some free models cannot emit
    them and instead print a JSON call inside ``content`` (e.g.
    ``[[{"name": "say_to", "parameters": {...}}]]``); that text is parsed as a
    best-effort fallback so an acting Sim is never silenced by a provider
    limitation. When a call is recovered from the text it is not stored as a
    thought.
    """
    calls = list(getattr(response, "tool_calls", ()) or ())
    from_text = False
    if not calls:
        calls = _text_tool_calls(getattr(response, "text", ""), allowed)
        from_text = bool(calls)

    directives: list[dict[str, Any]] = []
    for call in calls:
        name = str(getattr(call, "name", "") or "")
        if name not in allowed:
            continue
        directives.append(_directive_from_call(job, call))
        if len(directives) >= limit:
            break
    thought = "" if directives and from_text else _clean_thought(getattr(response, "text", ""))
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
    schemas = _tool_schemas(autonomy, job.kind)
    allowed = set(impulse_tools(autonomy, job.kind))
    limit = _IDLE_LIMIT if job.kind == "idle" else max(1, len(allowed))

    for attempt in range(_MAX_LLM_ATTEMPTS):
        if attempt > 0:
            # Reinforce the language on the retry so an English slip is corrected.
            messages = messages + [
                {"role": "system", "content": langguard.language_directive(lang, reinforced=True)}
            ]
        try:
            response = await registry.complete(
                messages,
                lang=lang,
                tools=schemas or None,
                max_tokens=IMPULSE_MAX_TOKENS,
                reasoning_effort=reasoning_effort,
                purpose="impulse",
            )
        except Exception as exc:
            logger.warning("impulse LLM call failed (attempt %d): %s", attempt + 1, exc)
            break

        directives, thought = _parse_impulse_response(job, response, allowed, limit)
        # v0.4 P2: an inner thought becomes a memory; it must be in the game
        # language. A wrong-language thought is dropped (and the loop retries).
        if thought and langguard.is_wrong_lang(thought, lang):
            logger.info(
                "impulse thought rejected (wrong language) attempt %d lang=%s",
                attempt + 1,
                lang,
            )
            thought = ""
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
    # v0.4 P5: drop *stage directions* / *actions*; a thought is first-person.
    cleaned = _STAGE_DIRECTION_RE.sub("", cleaned).strip()
    if not any(ch.isalnum() for ch in cleaned):
        return ""
    if any(marker in lowered for marker in _meta_markers()):
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


def _reaction_impulse(
    job: Any, profile: dict[str, Any] | None, lang: str = "en"
) -> dict[str, Any]:
    event = dict(job.event or {})
    event_type = str(event.get("type", "")).lower()
    target = event.get("target_sim_id") or event.get("target")
    name = str((profile or {}).get("name") or f"Sim {job.sim_id}")

    if target is not None and event_type in {"social", "chat", "interaction", "gossip"}:
        tool = "say_to"
        args: dict[str, Any] = {
            "message": content_i18n.t(lang, "initiative.reaction.social_message", name=name),
            "target_sim_id": _as_int(target),
        }
        thought = content_i18n.t(lang, "initiative.reaction.social_thought")
    elif event_type in {"fire", "death", "disaster", "fight", "accident", "divorce"}:
        tool = "set_mood"
        args = {
            "mood": "tense",
            "reason": content_i18n.t(
                lang, "initiative.reaction.disaster_reason", name=name, event_type=event_type
            ),
        }
        thought = content_i18n.t(
            lang, "initiative.reaction.disaster_thought", event_type=event_type
        )
    else:
        tool = "spontaneous_line"
        args = {
            "text": content_i18n.t(
                lang, "initiative.reaction.spontaneous_text", name=name
            ),
            "audience": "self",
        }
        thought = content_i18n.t(lang, "initiative.reaction.spontaneous_thought")

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


def _idle_thought(job: Any, profile: dict[str, Any] | None, lang: str = "en") -> str:
    name = str((profile or {}).get("name") or f"Sim {job.sim_id}")
    return content_i18n.t(lang, "initiative.idle_thought", name=name)


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
        other_id = _as_int(state.get("sim_id", key))
        if other_id == _as_int(job.sim_id):
            continue
        label = state.get("full_name") or str(key)
        mood = state.get("mood") or "neutral"
        others.append(f"{label} (id={other_id}, mood={mood})")

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
        text += ". Use only these exact id values when acting on another Sim."
    return text


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
