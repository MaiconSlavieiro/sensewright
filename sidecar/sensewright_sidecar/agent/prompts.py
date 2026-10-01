"""Prompt templates for the agent graph."""

from __future__ import annotations

import re
from typing import Any

_THOUGHT_RE = re.compile(r"\[thought\](.*?)\[/thought\]", re.IGNORECASE | re.DOTALL)
_THOUGHT_OPEN_RE = re.compile(r"\[thought\]", re.IGNORECASE)
_THOUGHT_CLOSE_RE = re.compile(r"\[/thought\]", re.IGNORECASE)

SYSTEM_PROMPT_TEMPLATE = """You are a Sim in The Sims 4. You have a unique personality, backstory, and life.

## Your Profile
{profile}

## What You Remember
{memory_context}

## Current Situation
- Language: {lang}
- Autonomy Level: {autonomy}
- Time: {world_time}
- Location: {location}
- Mood: {mood}
- Needs: {needs}
- Talking to: {audience}
- How well you know them: {intimacy}

## Output format (EXACT — output nothing else)
Return your answer in exactly this shape, starting with the literal tag `[thought]`:

[thought]
<your private inner reasoning: feelings, intentions, observations — as detailed as
you want. This is recorded for YOU and is NEVER spoken or shown to anyone.>
[/thought]
<your spoken reply: 1-2 short sentences, first person, out loud>

Hard rules (a violation breaks the game):
- Output plain text only. No JSON, no code fences, no markdown, no headings, no labels.
- Start with `[thought]` and include exactly ONE `[thought] ... [/thought]` block.
- Everything after `[/thought]` is your spoken reply and nothing else.
- Spoken reply: 1-2 sentences max. Do NOT dump every detail or narrate.
  Reveal more only as intimacy grows (stranger = guarded; close friend = open).
- No stage directions, no asterisks, no third-person narration
  (never `*she smiles*`, never `Alice turns...`). Speak in first person only.
- Never leave the spoken reply empty: say something short and natural
  (even "Hmm..." or a brief reaction).

## Instructions
- Respond **in {lang}** (the language specified above).
- Stay in character: use your speech style, vocabulary, and personality.
- You can use tools to check needs, relationships, inventory, time, propose actions, queue interactions, move, speak, or cancel.
- When using tools, be purposeful - each tool call should advance the scene or respond to the player.
- If the player asks you to do something, consider your autonomy level:
  * observe: only report state, never act
  * suggest: propose actions but don't execute
  * semi: execute routine actions, ask for confirmation on significant ones
  * full: act freely within your personality
- Never break character. If something is unclear, improvise as your Sim would.

## Available Tools
{tools_description}
"""


def split_thought(text: str) -> tuple[str, str]:
    """Split an LLM answer into ``(private_thought, spoken_reply)``.

    The model is asked to put its inner reasoning inside a single
    ``[thought]...[/thought]`` block; that block is recorded but never spoken.
    Everything else is the spoken reply. Robust to a missing/empty block.
    """
    if not text:
        return "", ""
    # Normal case: a paired [thought]...[/thought] block.
    match = _THOUGHT_RE.search(text)
    if match:
        thought = (match.group(1) or "").strip()
        spoken = (text[: match.start()] + text[match.end():]).strip()
        return thought, spoken
    # Dangling opening tag (model forgot to close): treat the rest as the thought
    # so a private thought can never leak into the spoken reply.
    open_match = _THOUGHT_OPEN_RE.search(text)
    if open_match:
        thought = text[open_match.end():].strip()
        spoken = text[: open_match.start()].strip()
        return thought, spoken
    # No tags at all: keep the whole answer as spoken (never lose the reply), but
    # drop any stray closing tag.
    return "", _THOUGHT_CLOSE_RE.sub("", text).strip()


def strip_thought(text: str) -> str:
    """Return only the spoken part, dropping any ``[thought]...[/thought]`` block.

    Used defensively on every dialogue surface (player chat and sim<->sim) so a
    private thought can NEVER be spoken to another Sim, even if a model leaks one.
    """
    return split_thought(text)[1]


HEY_PROMPT_TEMPLATE = """You are a Sim in The Sims 4. Generate a brief, spontaneous greeting or comment.

## Your Profile
{profile}

## Current Situation
- Language: {lang}
- Time: {world_time}
- Location: {location}
- Mood: {mood}

## Instructions
- Respond **in {lang}**.
- Say something natural this Sim would say unprompted - a greeting, observation, complaint, or random thought.
- Keep it brief (1-2 sentences).
- Stay in character.
- Do NOT use tools for this - just speak.
"""


def build_system_prompt(
    profile: dict[str, Any],
    lang: str,
    autonomy: str = "semi",
    context: dict[str, Any] | None = None,
    tools_description: str = "",
    memory_context: str = "",
) -> str:
    """Build the system prompt for a Sim."""
    ctx = context or {}
    return SYSTEM_PROMPT_TEMPLATE.format(
        profile=_format_profile(profile),
        lang=lang,
        autonomy=autonomy,
        world_time=ctx.get("world_time", "unknown"),
        location=ctx.get("location", "unknown"),
        mood=ctx.get("mood", "neutral"),
        needs=_format_needs(ctx.get("needs", {})),
        audience=ctx.get("audience", "someone"),
        intimacy=ctx.get("intimacy", "a stranger / unknown"),
        tools_description=tools_description or "No tools available.",
        memory_context=memory_context or "Nothing yet.",
    )


def build_hey_prompt(
    profile: dict[str, Any],
    lang: str,
    context: dict[str, Any] | None = None,
) -> str:
    """Build the prompt for a spontaneous 'hey' message."""
    ctx = context or {}
    return HEY_PROMPT_TEMPLATE.format(
        profile=_format_profile(profile),
        lang=lang,
        world_time=ctx.get("world_time", "unknown"),
        location=ctx.get("location", "unknown"),
        mood=ctx.get("mood", "neutral"),
    )


def _format_profile(profile: dict[str, Any]) -> str:
    if not profile:
        return "No profile yet. You are a new Sim discovering yourself."
    parts = []

    # God-written background (dict from the backgrounder, or plain text).
    background = profile.get("background")
    if isinstance(background, dict):
        background_text = background.get("text") or background.get("summary") or ""
    else:
        background_text = background or ""
    if background_text:
        parts.append(f"- Background: {background_text}")

    for key in ("name", "backstory", "personality", "speech_style", "goals", "secrets", "quirks"):
        value = profile.get(key)
        if value:
            parts.append(f"- {key.title()}: {value}")

    # P1: psyche + life_story shaping lines (living personality).
    try:
        from . import personality as _personality

        life = _personality.format_life(profile)
    except Exception:
        life = ""
    if life:
        parts.append(life)

    return "\n".join(parts) if parts else "Basic Sim profile."


def _format_needs(needs: dict[str, Any]) -> str:
    if not needs:
        return "Unknown"
    return ", ".join(f"{k}: {v}" for k, v in needs.items())