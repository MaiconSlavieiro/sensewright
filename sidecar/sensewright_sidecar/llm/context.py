"""ContextAssembler — slices context to the tier budget and renders prompts.

Implements F16: each tier has an input-token ceiling. Profile fields and
memories are sliced (micro vs deep) so a ``realtime`` impulse never floods the
prompt, while a ``deep`` dream gets the full life-story context.

Prompts are 100% data-driven (REQ-I18N-02): they are rendered from
``locales/content/<code>.json`` via the I18nEngine, with enum state translated
before assembly and the language anchor injected as the last line.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from ..config import Config
from ..i18n_engine import get_engine
from ..purposes import get_purpose
from ..schemas import CHANNELS, normalize_lang
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
        lang: str = "",
    ) -> List[Dict[str, str]]:
        """Build the full message list (system + user) for a purpose."""
        lang = normalize_lang(lang)
        engine = get_engine()
        purpose = get_purpose(purpose_id)
        tier = purpose.tier if purpose else "bg"

        ctx = self._render_ctx(context, lang)
        system = engine.render_prompt(purpose_id, "system", lang, ctx).strip()

        channel = context.get("channel")
        section = ("user_" + channel) if channel in CHANNELS else "user"
        payload = self._build_payload(purpose_id, context, tier)
        user_ctx = dict(ctx)
        user_ctx["context_json"] = json.dumps(payload, ensure_ascii=False)
        user = engine.render_prompt(purpose_id, section, lang, user_ctx).strip()
        if not user:
            user = user_ctx["context_json"]

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def _render_ctx(self, context: Dict[str, Any], lang: str) -> Dict[str, Any]:
        """Translate enum state and lift context fields into prompt variables."""
        engine = get_engine()
        profile = context.get("profile") or {}
        gender = context.get("gender")
        sim_name = context.get("sim_name") or profile.get("name") or ""
        trust = context.get("trust")
        if trust is None:
            trust = context.get("friendship", "")
        zeitgeist = context.get("zeitgeist_tags") or []
        if isinstance(zeitgeist, str):
            zeitgeist = [zeitgeist]
        bias_archetypes = (engine.content(lang).get("anchors") or {}).get("bias_archetypes") or []

        return {
            "sim_name": sim_name,
            "player_name": context.get("player_name", ""),
            "core_personality": profile.get("core_personality", ""),
            "current_demeanor": profile.get("current_demeanor", ""),
            "speech_style": profile.get("speech_style", ""),
            "age_label": engine.enum("age_stage", profile.get("age_stage") or context.get("age_stage"), lang, gender),
            "career_label": context.get("career_label", ""),
            "mood_label": engine.enum("mood", context.get("mood"), lang, gender),
            "activity_label": engine.enum("activity", context.get("activity"), lang, gender),
            "trust_label": str(trust),
            "message": context.get("message", ""),
            "memories_text": self._memories_text(context.get("memories"), lang),
            "surrealism_index": str(context.get("surrealism_index", "0.5")),
            "zeitgeist_tags": ", ".join(zeitgeist),
            "target_name": context.get("target_name", ""),
            "catalyst_name": context.get("catalyst_name", ""),
            "agent_name": context.get("agent_name", ""),
            "puppeteer_objective": context.get("puppeteer_objective", ""),
            "mood_options": ", ".join(engine.enum_keys("mood", lang)),
            "bias_options": ", ".join(str(a) for a in bias_archetypes),
        }

    def _memories_text(self, memories: Any, lang: str) -> str:
        if not isinstance(memories, list) or not memories:
            return ""
        parts = []
        for memory in memories[:5]:
            if isinstance(memory, dict):
                search = memory.get("search_text") or memory.get("content")
                if isinstance(search, str):
                    parts.append(search)
                else:
                    parts.append(json.dumps(search, ensure_ascii=False))
        return " | ".join(parts)

    def _build_payload(self, purpose_id: str, context: Dict[str, Any], tier: str) -> Dict[str, Any]:
        """Slice context into a JSON payload bounded by the tier budget."""
        budget = self.tier_budget(tier)
        payload: Dict[str, Any] = {"purpose": purpose_id}

        profile = context.get("profile") or {}
        if tier in ("realtime", "interactive"):
            payload["profile"] = {k: profile.get(k, "") for k in _MICRO_FIELDS}
        else:
            payload["profile"] = {k: profile.get(k, "") for k in _DEEP_FIELDS}

        for key in ("mood", "activity", "current_needs", "room_id", "is_sleeping", "is_off_lot_duty"):
            if key in context:
                payload[key] = context[key]

        memories = context.get("memories") or []
        if isinstance(memories, list):
            payload["memories"] = memories[:_MEMORY_COUNT_BY_TIER.get(tier, 8)]

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
        max_chars = max(200, budget * 4)
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...[truncated]"
