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
        anchors = engine.content(lang).get("anchors") or {}
        bias_archetypes = anchors.get("bias_archetypes") or []

        family_text = self._family_text(context.get("family"))
        history_text = self._history_text(context.get("history"))
        family_hint = ""
        if family_text:
            family_hint = str(anchors.get("family_hint", "")).replace("{family_text}", family_text)
        history_hint = ""
        if history_text:
            history_hint = str(anchors.get("history_hint", "")).replace("{history_text}", history_text)

        location_text = self._location_text(context.get("location"), lang, engine)
        relationship_text = self._relationship_text(context.get("relationship"), lang, engine)
        action_text = self._action_text(context.get("action"), lang, engine)
        location_hint = ""
        if location_text:
            location_hint = str(anchors.get("location_hint", "")).replace("{location_text}", location_text)
        relationship_hint = ""
        if relationship_text:
            relationship_hint = str(anchors.get("relationship_hint", "")).replace("{relationship_text}", relationship_text)
        action_hint = ""
        if action_text:
            action_hint = str(anchors.get("action_hint", "")).replace("{action_text}", action_text)

        # Asymmetric directive: when a catalyst lease is in play, inject the
        # god.puppeteer objective into the sim.social prompt so the puppet NPC
        # drives the scene while the agent answers freely.
        asymmetric_directive = ""
        puppeteer_objective = context.get("puppeteer_objective", "")
        if puppeteer_objective:
            asymmetric_directive = engine.render_prompt(
                "god.puppeteer", "asymmetric_directive", lang,
                {
                    "catalyst_name": context.get("catalyst_name", ""),
                    "puppeteer_objective": puppeteer_objective,
                    "agent_name": context.get("agent_name", ""),
                },
            ).strip()

        return {
            "sim_name": sim_name,
            "player_name": context.get("player_name", ""),
            "core_personality": profile.get("core_personality", ""),
            "current_demeanor": profile.get("current_demeanor", ""),
            "speech_style": profile.get("speech_style", ""),
            "backstory": profile.get("backstory", ""),
            "age_label": engine.enum("age_stage", profile.get("age_stage") or context.get("age_stage"), lang, gender),
            "career_label": context.get("career_label", ""),
            "mood_label": engine.enum("mood", context.get("mood"), lang, gender),
            "activity_label": engine.enum("activity", context.get("activity"), lang, gender),
            "trust_label": str(trust),
            "message": context.get("message", ""),
            "memories_text": self._memories_text(context.get("memories"), lang),
            "history_text": history_text,
            "family_text": family_text,
            "family_hint": family_hint,
            "history_hint": history_hint,
            "location_hint": location_hint,
            "relationship_hint": relationship_hint,
            "action_hint": action_hint,
            "asymmetric_directive": asymmetric_directive,
            "surrealism_index": str(context.get("surrealism_index", "0.5")),
            "zeitgeist_tags": ", ".join(zeitgeist),
            "target_name": context.get("target_name", ""),
            "catalyst_name": context.get("catalyst_name", ""),
            "agent_name": context.get("agent_name", ""),
            "puppeteer_objective": context.get("puppeteer_objective", ""),
            "mood_options": ", ".join(engine.enum_keys("mood", lang)),
            "bias_options": ", ".join(str(a) for a in bias_archetypes),
        }

    def _location_text(self, location: Any, lang: str, engine: Any) -> str:
        """Render the setting (venue, indoor/outdoor, home/away) as text."""
        if not isinstance(location, dict) or not location:
            return ""
        parts = []
        is_outside = location.get("is_outside")
        if is_outside is not None:
            parts.append(engine.enum("inside_outside", "outside" if is_outside else "inside", lang))
        is_at_home = location.get("is_at_home")
        if is_at_home is not None:
            parts.append(engine.enum("home_away", "home" if is_at_home else "away", lang))
        venue = location.get("venue")
        if venue:
            parts.append(engine.enum("venue", str(venue), lang))
        return ", ".join(parts)

    def _relationship_text(self, relationship: Any, lang: str, engine: Any) -> str:
        """Render the pair relationship (tier + friendship/romance + native delta)."""
        if not isinstance(relationship, dict) or not relationship:
            return ""
        anchors = engine.content(lang).get("anchors") or {}
        parts = []
        tier = relationship.get("tier", "")
        if tier:
            label = engine.enum("relationship", str(tier), lang)
            if label:
                parts.append(str(label))
        friendship = relationship.get("friendship")
        if friendship is not None:
            friendship_hint = anchors.get("relationship_friendship_hint", "friendship {value}")
            text = str(friendship_hint).replace("{value}", str(int(round(float(friendship)))))
            delta = relationship.get("friendship_delta")
            if delta not in (None, 0, 0.0):
                delta_hint = anchors.get("relationship_delta_hint", " ({value})")
                sign = "+" if float(delta) > 0 else "-"
                text += str(delta_hint).replace("{value}", "{}{}".format(sign, abs(int(round(float(delta))))))
            parts.append(text)
        romance = relationship.get("romance")
        if romance not in (None, 0, 0.0):
            romance_hint = anchors.get("relationship_romance_hint", "romance {value}")
            text = str(romance_hint).replace("{value}", str(int(round(float(romance)))))
            rdelta = relationship.get("romance_delta")
            if rdelta not in (None, 0, 0.0):
                delta_hint = anchors.get("relationship_delta_hint", " ({value})")
                sign = "+" if float(rdelta) > 0 else "-"
                text += str(delta_hint).replace("{value}", "{}{}".format(sign, abs(int(round(float(rdelta))))))
            parts.append(text)
        return ", ".join(parts)

    def _action_text(self, action: Any, lang: str, engine: Any) -> str:
        """Render the selected/queued interaction menu text for the actor(s)."""
        if not isinstance(action, dict) or not action:
            return ""
        next_anchor = (engine.content(lang).get("anchors") or {}).get("action_next_hint", "next: {value}")
        parts = []
        for prefix in ("a", "b"):
            name = action.get("{}_name".format(prefix), "")
            current = action.get("{}_current".format(prefix), "")
            if current:
                parts.append("{}: {}".format(name or "Sim", current))
            for queued in action.get("{}_queued".format(prefix)) or []:
                if queued:
                    parts.append(str(next_anchor).replace("{value}", str(queued)))
        return "; ".join(parts)

    def _history_text(self, history: Any) -> str:
        """Render the short-term chat buffer as a readable transcript."""
        if not isinstance(history, list) or not history:
            return ""
        parts = []
        for turn in history[-6:]:
            if not isinstance(turn, dict):
                continue
            role = turn.get("role", "")
            content = turn.get("content", "")
            if not content:
                continue
            if role == "assistant":
                parts.append("You: {}".format(content))
            else:
                parts.append("Player: {}".format(content))
        return "\n".join(parts)

    def _family_text(self, family: Any) -> str:
        """Render resolved family edges as ``name (relation)`` pairs."""
        if not isinstance(family, list) or not family:
            return ""
        parts = []
        for member in family:
            if not isinstance(member, dict):
                continue
            name = member.get("name", "")
            if not name:
                continue
            relation = member.get("relation", "")
            parts.append("{} ({})".format(name, relation) if relation else str(name))
        return ", ".join(parts)

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
            "location", "action", "family", "history",
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
