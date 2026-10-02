"""ContextAssembler — slices context to the tier budget and builds prompts.

Implements F16: each tier has an input-token ceiling. Profile fields and
memories are sliced (micro vs deep) so a ``realtime`` impulse never floods the
prompt, while a ``deep`` dream gets the full life-story context. The language
anchor is always the last line; a 1-shot example is included in the target
language (REQ-LLM-04).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from ..config import Config
from ..fallbacks import render_fallback
from ..locales import language_anchor, one_shot_example
from ..purposes import get_purpose
from ..schemas import normalize_lang
from .limits import estimate_tokens

#: How many recent memories to include per tier.
_MEMORY_COUNT_BY_TIER = {
    "interactive": 3,
    "realtime": 2,
    "bg": 8,
    "deep": 20,
}

#: Profile field groups used for micro (compact) vs deep (full) context.
_MICRO_FIELDS = ("speech_style", "current_demeanor")
_DEEP_FIELDS = (
    "core_personality", "current_demeanor", "life_story", "psyche_blocks",
    "dream_residue", "daily_plan", "backstory",
)


class ContextAssembler:
    def __init__(self, config: Config) -> None:
        self._config = config

    def tier_budget(self, tier: str) -> int:
        return int(self._config.tier(tier).get("max_input_tokens", 1500))

    def assemble(
        self,
        purpose_id: str,
        context: Dict[str, Any],
        lang: str = "en",
    ) -> List[Dict[str, str]]:
        """Build the full message list (system + user) for a purpose."""
        lang = normalize_lang(lang)
        purpose = get_purpose(purpose_id)
        tier = purpose.tier if purpose else "bg"

        system = self._build_system(purpose_id, lang)
        user = self._build_user(purpose_id, context, lang, tier)
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _build_system(self, purpose_id: str, lang: str) -> str:
        purpose = get_purpose(purpose_id)
        output_keys = list(render_fallback(purpose_id, lang, {}).keys())
        keys_hint = ", ".join(output_keys) if output_keys else "a JSON object"

        lines = [
            "You are the inner mind of a The Sims 4 character (Sim).",
            "You always respond with a single JSON object and nothing else.",
            "Required JSON keys: {}.".format(keys_hint),
            one_shot_example(lang),
            language_anchor(lang),
        ]
        return "\n".join(lines)

    def _build_user(self, purpose_id: str, context: Dict[str, Any], lang: str, tier: str) -> str:
        budget = self.tier_budget(tier)
        # Build a payload, then trim to budget.
        payload: Dict[str, Any] = {"purpose": purpose_id, "lang": lang}

        profile = context.get("profile") or {}
        if tier == "realtime" or tier == "interactive":
            payload["profile"] = {k: profile.get(k, "") for k in _MICRO_FIELDS}
        else:
            payload["profile"] = {k: profile.get(k, "") for k in _DEEP_FIELDS}

        # Current volatile state (mood, activity, needs).
        for key in ("mood", "activity", "current_needs", "room_id", "is_sleeping", "is_off_lot_duty"):
            if key in context:
                payload[key] = context[key]

        # Memories (already sliced by the agent/god callers, but guard here).
        memories = context.get("memories") or []
        if isinstance(memories, list):
            payload["memories"] = memories[:_MEMORY_COUNT_BY_TIER.get(tier, 8)]

        # Extra free-form context (chat message, event, directives...).
        for key in (
            "message", "event", "target", "directives", "active_arc", "zeitgeist",
            "dream_urge", "schedule_blocks", "obligatory_tasks", "native_wants",
            "relationship", "rumor", "player_facts", "scene_subtext", "puppeteer_objective",
        ):
            if key in context:
                payload[key] = context[key]

        return self._trim_to_budget(json.dumps(payload, ensure_ascii=False), budget)

    def _trim_to_budget(self, text: str, budget: int) -> str:
        """Truncate text so its estimated token count fits ``budget``."""
        if estimate_tokens(text) <= budget:
            return text
        # Crude but safe: cut characters proportionally (4 chars ~ 1 token).
        max_chars = max(200, budget * 4)
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...[truncated]"
