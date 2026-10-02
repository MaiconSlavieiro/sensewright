"""Deterministic 0-key fallbacks for all 33 purposes (Safety Net #4).

When SQLite fails or no API key is configured, every purpose must still answer
with a deterministic, localized template. This module provides that safety net:
each handler returns the same JSON shape as the corresponding LLM output, so
downstream consumers (routers, agent, god, world, Web Studio) are unaffected by
whether a provider is configured or not.

Language adherence is structural: templates exist for ``en`` and ``pt-BR`` and
are selected by the ``lang`` argument. Enum-like fields (moods, archetypes,
activities) are returned as canonical ASCII identifiers that the mod's
``ArchetypeResolver`` translates to game tuning IDs — never raw localized text.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from .schemas import normalize_lang


def _t(lang: str, en: str, pt: str) -> str:
    """Pick the localized string for ``lang``."""
    return pt if lang == "pt-BR" else en


def _name(context: Dict[str, Any]) -> str:
    return context.get("sim_name") or context.get("name") or "Sim"


def _player(context: Dict[str, Any]) -> str:
    return context.get("player_name") or context.get("player") or "Friend"


def _mood(context: Dict[str, Any]) -> str:
    return context.get("mood") or "fine"


def _activity(context: Dict[str, Any]) -> str:
    return context.get("activity") or "idle"


# ── individual handlers ─────────────────────────────────────────────────────
def _fb_chat(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "response": _t(
            lang,
            "Hey! Sorry, I'm a bit distracted right now. Let's talk more in a moment.",
            "Oi! Desculpa, estou meio distraído agora. Vamos conversar daqui a pouco.",
        ),
        "thought": _t(
            lang, "I want to answer but my mind is elsewhere.", "Quero responder, mas minha mente está longe.",
        ),
        "intents": [],
        "trust_delta": 0.0,
        "deferred": bool(ctx.get("deferred", False)),
    }


def _fb_profile(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    from .agent.profile import template_profile
    return template_profile(
        _name(ctx),
        species=ctx.get("species", "HUMAN"),
        age_stage=ctx.get("age_stage", "YOUNGADULT"),
        traits=ctx.get("traits"),
        likes=ctx.get("likes"),
        dislikes=ctx.get("dislikes"),
        generated_at_tick=int(ctx.get("world_sim_tick", 0)),
    )


def _fb_impulse(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "thought": _t(
            lang,
            "Just taking in the day. Nothing pressing on my mind.",
            "Só absorvendo o dia. Nada urgente na minha mente.",
        ),
        "intents": [],
    }


def _fb_reaction(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    target = ctx.get("target_name") or "them"
    return {
        "thought": _t(
            lang,
            "I can't believe that just happened.",
            "Não acredito que isso acabou de acontecer.",
        ),
        "intents": [],
    }


def _fb_social(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "a_line": _t(lang, "So, how's your day going?", "Então, como está seu dia?"),
        "b_line": _t(lang, "Same as always, I suppose.", "O mesmo de sempre, eu acho."),
        "topic": _t(lang, "small talk", "conversa fiada"),
        "event_summary": _t(lang, "a light exchange", "uma troca leve"),
        "impact": 0.5,
    }


def _fb_social_close(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "event_summary": _t(lang, "a brief conversation", "uma conversa breve"),
        "impact": 0.3,
        "rumor": None,
    }


def _fb_dream(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "archetype": "surreal",
        "dream_narrative": _t(
            lang,
            "I dreamed I was walking through a house that kept rearranging its rooms.",
            "Sonhei que andava por uma casa que não parava de reorganizar seus cômodos.",
        ),
        "wakeup_mood": "dazed",
        "dream_urge": {
            "goal": _t(lang, "Explore somewhere unfamiliar today", "Explorar algum lugar desconhecido hoje"),
            "weight": 0.4,
        },
    }


def _fb_cognition(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "day_focus": _t(lang, "Get through the day at my own pace.", "Levar o dia no meu próprio ritmo."),
        "attitude_toward_duty": "compliant",
        "blocks": {
            "morning": {"goal": _t(lang, "Start the day calmly", "Começar o dia com calma"), "linked_native": "none", "done": False},
            "afternoon": {"goal": _t(lang, "Handle the day's duties", "Cuidar das tarefas do dia"), "linked_native": "none", "done": False},
            "evening": {"goal": _t(lang, "Wind down and relax", "Desacelerar e relaxar"), "linked_native": "none", "done": False},
        },
        "autonomy_biases": [],
    }


def _fb_sleep(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "reflection": _t(
            lang, "A quiet night. My thoughts settle as I drift off.", "Uma noite tranquila. Meus pensamentos se acalmam.",
        ),
        "psyche_updates": [],
    }


def _fb_diary(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "entry": _t(
            lang,
            "Dear diary, today was ordinary, but I'm grateful for the little moments.",
            "Querido diário, hoje foi comum, mas sou grato pelos pequenos momentos.",
        ),
    }


def _fb_lifestory(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "chapter": _t(lang, "A new chapter", "Um novo capítulo"),
        "life_story": _t(
            lang,
            "Life keeps unfolding, one quiet day after another.",
            "A vida segue se desdobrando, um dia tranquilo após o outro.",
        ),
    }


def _fb_aspiration(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "ambition": _t(lang, "Live a meaningful life", "Viver uma vida com significado"),
    }


def _fb_background_expand(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "backstory": [
            _t(lang, "I grew up in a modest neighborhood.", "Cresci em um bairro modesto."),
            _t(lang, "I had a childhood friend who moved away.", "Tive um amigo de infância que se mudou."),
            _t(lang, "I always dreamed of something more.", "Sempre sonhei com algo mais."),
        ],
    }


def _fb_zeitgeist(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {"tags": ["calm", "everyday"], "preset": "drama", "weather_preference": "sunny"}


def _fb_plan(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "theme": _t(lang, "The quiet rhythm of the neighborhood", "O ritmo tranquilo da vizinhança"),
        "beats": [],
    }


def _fb_cast(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {"cast": []}


def _fb_scene(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "scene_draft": _t(lang, "A chance encounter.", "Um encontro ao acaso."),
        "scene_subtext": _t(lang, "Something feels different today.", "Algo parece diferente hoje."),
    }


def _fb_puppeteer(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "objective": _t(lang, "Strike up a conversation.", "Puxar conversa."),
        "opening_line": _t(lang, "Hey, do you have a moment?", "Ei, você tem um minuto?"),
        "scene_subtext": _t(lang, "You sense someone watching.", "Você sente alguém observando."),
    }


def _fb_react(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "pivot": _t(lang, "The story continues on its own.", "A história continua por si só."),
        "next_beat": None,
    }


def _fb_narration(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "narration": _t(lang, "And so the day unfolds...", "E assim o dia se desenrola..."),
    }


def _fb_background(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "background": _t(lang, "A familiar, lived-in place.", "Um lugar familiar e cheio de vida."),
    }


def _fb_chronicle(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "chronicle": _t(lang, "The household went about its usual day.", "A família seguiu seu dia de sempre."),
    }


def _fb_gossip(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "rumor": _t(lang, "Word around town is that something interesting happened.", "Dizem pela cidade que algo interessante aconteceu."),
        "tags": ["rumor"],
    }


def _fb_aftermath(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "summary": _t(lang, "The neighborhood slowly returns to normal.", "A vizinhança volta lentamente ao normal."),
        "intents": [],
        "zeitgeist_shift": {},
    }


def _fb_consolidate(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "consolidated": _t(lang, "We talked and I felt understood.", "Conversamos e me senti compreendido."),
        "player_facts": [],
    }


def _fb_compact(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "compact": _t(lang, "The past fades into a few vivid memories.", "O passado se resume a algumas memórias vivas."),
    }


def _fb_legacy(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "legacy": _t(lang, "A life remembered.", "Uma vida lembrada."),
    }


def _fb_relationship_review(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "qualitative_note": _t(lang, "We get along well enough.", "Nos damos bem o suficiente."),
    }


def _fb_reflect(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "reflection": _t(lang, "I look at myself and see someone still growing.", "Olho para mim e vejo alguém ainda crescendo."),
        "demeanor_drift": None,
        "preference_change": None,
        "trait_proposal": None,
    }


def _fb_trait(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {"preference_change": None, "trait_proposal": None}


def _fb_recap(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "headline": _t(lang, "Previously...", "Anteriormente..."),
        "recap_text": _t(lang, "Life continues in this little world.", "A vida continua neste pequeno mundo."),
    }


def _fb_summary(lang: str, ctx: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "summary": _t(lang, "Sensewright is running quietly.", "O Sensewright está rodando em silêncio."),
    }


#: Registry of purpose id -> fallback handler.
_FALLBACK_HANDLERS: Dict[str, Callable[[str, Dict[str, Any]], Dict[str, Any]]] = {
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
    "world.npc.backstory": _fb_background,
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
    lang: str = "en",
    context: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """Render the deterministic fallback for ``purpose_id``.

    Returns a dict shaped like the corresponding LLM output. Unknown purposes
    return an empty dict. This never raises.
    """
    lang = normalize_lang(lang)
    ctx = context or {}
    handler = _FALLBACK_HANDLERS.get(purpose_id)
    if handler is None:
        return {}
    try:
        return handler(lang, ctx)
    except Exception:  # pragma: no cover - safety net must never raise
        return {}
