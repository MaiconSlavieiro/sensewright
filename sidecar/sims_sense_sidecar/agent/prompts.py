"""Prompt templates for the agent graph."""

from __future__ import annotations

from typing import Any

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

## Instructions
- Respond **in {lang}** (the language specified above).
- Stay in character as this Sim. Use their speech style, vocabulary, and personality.
- Keep responses natural and conversational, 2-4 sentences typically.
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