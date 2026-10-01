"""Cognition layer (L5, v0.3 R4): daily plan + goals at sleep.

Absorbs the Phase 4 reflection into the sleep cycle: one budgeted call turns the
Sim's recent events and profile into a compact **daily plan** (a focus plus a
couple of goals) stored on the profile. Awake impulses read the plan, so the Sim
"thinks" at sleep and adjusts the next day. A deterministic template fallback
keeps native (0-key) mode alive. Disabled via ``[agents.layers] cognition = false``.
"""

from __future__ import annotations

from typing import Any

DAILY_PLAN_MAX_GOALS = 3

_SYSTEM = (
    "You are {name}, a Sim in The Sims 4. Stay in character and reply in {lang} "
    "with strict JSON only."
)
_USER = (
    "Recent events:\n{events}\n\n"
    "About you: {about}\n\n"
    "Write a short plan for the coming day as JSON: "
    '{{"day_focus": "...", "goals": ["...", "..."]}}. '
    "Keep the focus to one short sentence and at most {max_goals} goals."
)


def _clean_goals(value: Any, limit: int = DAILY_PLAN_MAX_GOALS) -> list[str]:
    if isinstance(value, str):
        value = [part for part in value.split(";")]
    if not isinstance(value, (list, tuple)):
        return []
    goals: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            goals.append(text)
        if len(goals) >= limit:
            break
    return goals


def _about(profile: dict[str, Any] | None) -> str:
    if not profile:
        return ""
    for key in ("personality", "backstory", "speech_style", "goals", "quirks"):
        value = profile.get(key)
        if value:
            return str(value)
    return ""


def _events_text(events: list[Any] | None) -> str:
    lines: list[str] = []
    for event in (events or [])[:8]:
        if isinstance(event, dict):
            text = (
                event.get("text")
                or event.get("summary")
                or event.get("content")
                or event.get("type")
                or ""
            )
        else:
            text = getattr(event, "text", "") or ""
        text = str(text).strip()
        if text:
            lines.append(f"- {text}")
    return "\n".join(lines) if lines else "- (a quiet stretch)"


def template_plan(profile: dict[str, Any] | None, events: list[Any] | None = None) -> dict[str, Any]:
    """Deterministic fallback plan (native mode or LLM failure)."""
    profile = profile or {}
    goals: list[str] = []
    existing = _clean_goals(profile.get("goals"))
    goals.extend(existing)
    if not goals:
        career = profile.get("career") or ""
        if career:
            goals.append(f"Make progress as {career}")
        goals.append("Reach out to someone I care about")
        goals.append("Take care of myself")
    focus = profile.get("day_focus") or "Take the day as it comes."
    return {
        "day_focus": str(focus),
        "goals": goals[:DAILY_PLAN_MAX_GOALS],
        "source": "template",
    }


async def make_daily_plan(
    profile: dict[str, Any] | None,
    events: list[Any] | None,
    registry: Any,
    lang: str,
) -> dict[str, Any]:
    """Build the daily plan, falling back to the template on any error."""
    if registry is None:
        return template_plan(profile, events)

    name = str((profile or {}).get("name") or "Sim")
    messages = [
        {"role": "system", "content": _SYSTEM.format(name=name, lang=lang)},
        {
            "role": "user",
            "content": _USER.format(
                events=_events_text(events),
                about=_about(profile),
                max_goals=DAILY_PLAN_MAX_GOALS,
            ),
        },
    ]
    try:
        response = await registry.complete(messages, lang=lang, max_tokens=200, purpose="cognition")
    except Exception:
        return template_plan(profile, events)

    import json

    raw = str(getattr(response, "text", "") or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return template_plan(profile, events)
    if not isinstance(data, dict):
        return template_plan(profile, events)

    focus = str(data.get("day_focus") or "").strip()
    goals = _clean_goals(data.get("goals"))
    if not focus and not goals:
        return template_plan(profile, events)
    fallback = template_plan(profile, events)
    return {
        "day_focus": focus or fallback["day_focus"],
        "goals": goals or fallback["goals"],
        "source": "llm",
    }


def render_plan(profile: dict[str, Any] | None) -> str:
    """Render the stored plan as prompt shaping lines ('' when unknown)."""
    if not profile:
        return ""
    plan = profile.get("daily_plan")
    if not isinstance(plan, dict):
        plan = {}
    focus = str(plan.get("day_focus") or profile.get("day_focus") or "").strip()
    goals = _clean_goals(plan.get("goals") or profile.get("goals"))
    parts: list[str] = []
    if focus:
        parts.append(f"Today's focus: {focus}")
    if goals:
        parts.append("Goals for today: {}".format("; ".join(goals)))
    return ". ".join(parts)


class CognitionLayer:
    """The sleep-time cognition layer (daily plan + goals)."""

    name = "cognition"

    def __init__(self, settings: Any) -> None:
        self.configure(settings)

    def configure(self, settings: Any) -> None:
        layers = getattr(getattr(settings, "agents", None), "layers", None)
        self.enabled = bool(getattr(layers, "cognition", True)) if layers is not None else True

    async def think(
        self,
        profile: dict[str, Any] | None,
        events: list[Any] | None,
        registry: Any,
        lang: str,
    ) -> dict[str, Any] | None:
        """Return a daily plan (``None`` when the layer is disabled)."""
        if not self.enabled:
            return None
        return await make_daily_plan(profile, events, registry, lang)
