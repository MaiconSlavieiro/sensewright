"""Deterministic 0-key fallbacks for all 33 purposes (Safety Net #4).

All fallback TEXT is data-driven: it is loaded from
``locales/content/<code>.json`` under the ``fallbacks`` section via the
:class:`~sensewright_sidecar.i18n_engine.I18nEngine`. This module only assembles
the structural output shape (which key holds which text) — no localized string
lives in Python code (REQ-I18N-02).

When SQLite fails or no API key is configured, every purpose must still answer
with a deterministic, localized template. ``render_fallback`` returns the same
JSON shape as the corresponding LLM output, so downstream consumers are
unaffected by whether a provider is configured or not.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from .i18n_engine import get_engine

_MISSING = "[missing:"


def _fallback_str(key: str, context: Dict[str, Any], default: str = "") -> str:
    """Resolve a fallback string with list-rotation + gender inflection."""
    engine = get_engine()
    result = engine.t(
        key,
        lang=context.get("lang"),
        gender=context.get("gender"),
        sim_id=context.get("sim_id"),
        world_sim_tick=context.get("world_sim_tick"),
    )
    if not result or result.startswith(_MISSING):
        return default
    return result


def _name(context: Dict[str, Any]) -> str:
    return context.get("sim_name") or context.get("name") or "Sim"


def _player(context: Dict[str, Any]) -> str:
    return context.get("player_name") or context.get("player") or "Friend"


def _fb_chat(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "response": _fallback_str("fallbacks.sim.chat", context, _name(context)),
        "thought": "",
        "intents": [],
        "trust_delta": 0.0,
        "deferred": bool(context.get("deferred", False)),
    }


def _fb_profile(context: Dict[str, Any]) -> Dict[str, Any]:
    from .agent.profile import template_profile
    profile = template_profile(
        _name(context),
        species=context.get("species", "HUMAN"),
        age_stage=context.get("age_stage", "YOUNGADULT"),
        traits=context.get("traits"),
        likes=context.get("likes"),
        dislikes=context.get("dislikes"),
        generated_at_tick=int(context.get("world_sim_tick", 0)),
    )
    profile["backstory"] = _fallback_str("fallbacks.sim.profile.backstory", context)
    return profile


def _fb_impulse(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"thought": _fallback_str("fallbacks.sim.impulse", context), "intents": []}


def _fb_reaction(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"thought": _fallback_str("fallbacks.sim.reaction", context), "intents": []}


def _fb_social(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "a_line": _fallback_str("fallbacks.sim.social.a_line", context),
        "b_line": _fallback_str("fallbacks.sim.social.b_line", context),
        "topic": _fallback_str("fallbacks.sim.social.topic", context),
        "event_summary": _fallback_str("fallbacks.sim.social.close", context),
        "impact": 0.5,
    }


def _fb_social_close(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "event_summary": _fallback_str("fallbacks.sim.social.close", context),
        "impact": 0.3,
        "rumor": None,
    }


def _fb_dream(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "archetype": "surreal",
        "dream_narrative": _fallback_str("fallbacks.sim.dream.narrative", context),
        "wakeup_mood": "dazed",
        "dream_urge": {
            "goal": _fallback_str("fallbacks.sim.dream.urge", context),
            "weight": 0.4,
        },
    }


def _fb_cognition(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "day_focus": _fallback_str("fallbacks.sim.cognition.focus", context),
        "attitude_toward_duty": "compliant",
        "blocks": {
            "morning": {"goal": "", "linked_native": "none", "done": False},
            "afternoon": {"goal": "", "linked_native": "none", "done": False},
            "evening": {"goal": "", "linked_native": "none", "done": False},
        },
        "autonomy_biases": [],
    }


def _fb_sleep(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"reflection": _fallback_str("fallbacks.sim.sleep", context), "psyche_updates": []}


def _fb_diary(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"entry": _fallback_str("fallbacks.sim.diary", context)}


def _fb_lifestory(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"chapter": "", "life_story": _fallback_str("fallbacks.sim.lifestory", context)}


def _fb_aspiration(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"ambition": _fallback_str("fallbacks.sim.aspiration", context)}


def _fb_background_expand(context: Dict[str, Any]) -> Dict[str, Any]:
    # Three backstory lines: resolve the list directly via the engine.
    engine = get_engine()
    raw = engine.lookup("content", "fallbacks.sim.background.expand", engine.resolve_locale(context.get("lang")))
    if isinstance(raw, list) and raw:
        backstory = list(raw[:3])
    else:
        backstory = [_fallback_str("fallbacks.sim.background.expand", context)]
    return {"backstory": backstory}


def _fb_zeitgeist(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"tags": ["calm", "everyday"], "preset": "drama", "weather_preference": "sunny"}


def _fb_plan(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"theme": _fallback_str("fallbacks.god.plan.theme", context), "beats": []}


def _fb_cast(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"cast": []}


def _fb_scene(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "scene_draft": _fallback_str("fallbacks.god.scene.draft", context),
        "scene_subtext": _fallback_str("fallbacks.god.scene.subtext", context),
    }


def _fb_puppeteer(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "objective": _fallback_str("fallbacks.god.puppeteer.objective", context),
        "opening_line": _fallback_str("fallbacks.god.puppeteer.opening", context),
        "scene_subtext": _fallback_str("fallbacks.god.puppeteer.subtext", context),
    }


def _fb_react(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"pivot": _fallback_str("fallbacks.god.react.pivot", context), "next_beat": None}


def _fb_narration(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"narration": _fallback_str("fallbacks.god.narration", context)}


def _fb_background(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"background": _fallback_str("fallbacks.god.background", context)}


def _fb_chronicle(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"chronicle": _fallback_str("fallbacks.world.household.chronicle", context)}


def _fb_gossip(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"rumor": _fallback_str("fallbacks.world.gossip", context), "tags": ["rumor"]}


def _fb_aftermath(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "summary": _fallback_str("fallbacks.world.aftermath", context),
        "intents": [],
        "zeitgeist_shift": {},
    }


def _fb_consolidate(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "consolidated": _fallback_str("fallbacks.mem.consolidate", context),
        "player_facts": [],
    }


def _fb_compact(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"compact": _fallback_str("fallbacks.mem.compact", context)}


def _fb_legacy(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"legacy": _fallback_str("fallbacks.mem.legacy", context)}


def _fb_relationship_review(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"qualitative_note": _fallback_str("fallbacks.mem.relationship.review.note", context)}


def _fb_reflect(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "reflection": _fallback_str("fallbacks.evo.reflect", context),
        "demeanor_drift": None,
        "preference_change": None,
        "trait_proposal": None,
    }


def _fb_trait(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"preference_change": None, "trait_proposal": None}


def _fb_recap(context: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "headline": _fallback_str("fallbacks.ops.recap.headline", context),
        "recap_text": _fallback_str("fallbacks.ops.recap.text", context),
    }


def _fb_summary(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"summary": _fallback_str("fallbacks.ops.panel.summary", context)}


def _fb_npc_backstory(context: Dict[str, Any]) -> Dict[str, Any]:
    return {"background": _fallback_str("fallbacks.world.npc.backstory", context)}


#: Registry of purpose id -> assembly function (structure only, text is data-driven).
_FALLBACK_HANDLERS: Dict[str, Any] = {
    "sim.chat": _fb_chat,
    "sim.profile": _fb_profile,
    "sim.impulse": _fb_impulse,
    "sim.reaction": _fb_reaction,
    "sim.social": _fb_social,
    "sim.social.close": _fb_social_close,
    "sim.dream": _fb_dream,
    "sim.cognition": _fb_cognition,
    "sim.sleep": _fb_sleep,
    "sim.diary": _fb_diary,
    "sim.lifestory": _fb_lifestory,
    "sim.aspiration": _fb_aspiration,
    "sim.background.expand": _fb_background_expand,
    "god.zeitgeist": _fb_zeitgeist,
    "god.plan": _fb_plan,
    "god.cast": _fb_cast,
    "god.scene": _fb_scene,
    "god.puppeteer": _fb_puppeteer,
    "god.react": _fb_react,
    "god.narration": _fb_narration,
    "god.background": _fb_background,
    "world.npc.backstory": _fb_npc_backstory,
    "world.household.chronicle": _fb_chronicle,
    "world.gossip": _fb_gossip,
    "world.aftermath": _fb_aftermath,
    "mem.consolidate": _fb_consolidate,
    "mem.compact": _fb_compact,
    "mem.legacy": _fb_legacy,
    "mem.relationship.review": _fb_relationship_review,
    "evo.reflect": _fb_reflect,
    "evo.trait": _fb_trait,
    "ops.recap": _fb_recap,
    "ops.panel.summary": _fb_summary,
}


def render_fallback(
    purpose_id: str,
    lang: str = "",
    context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Render the deterministic fallback for ``purpose_id``.

    Returns a dict shaped like the corresponding LLM output. Unknown purposes
    return an empty dict. This never raises.
    """
    context = context or {}
    context = dict(context)
    context.setdefault("lang", lang)
    handler = _FALLBACK_HANDLERS.get(purpose_id)
    if handler is None:
        return {}
    try:
        return handler(context)
    except Exception:  # pragma: no cover - safety net must never raise
        return {}
