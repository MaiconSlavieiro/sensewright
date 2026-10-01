"""God agent background generation for Sims and households.

Backgrounds are the first layer of meaning the God agent stores per Sim or
household. Native game data (traits, age, career, skills, relationships,
kinship) is always ground truth; the neighborhood zeitgeist only colors the
writing. Every public coroutine degrades gracefully to a deterministic
template when no LLM provider is available.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from .. import content_i18n
from ..llm import langguard
from ..schemas import normalize_lang
from .zeitgeist import clamp01, normalize_zeitgeist, zeitgeist_to_prompt_block

logger = logging.getLogger(__name__)

# Free reasoning models spend part of the completion budget on hidden reasoning;
# at 500 tokens the JSON answer was routinely truncated mid-object (a live run
# stored a background that was literally "{"). A larger budget lets the 2-4
# sentence answer and its JSON envelope finish.
BACKGROUND_MAX_TOKENS = 900

# Below this many characters a "background" is not real prose (e.g. a stray "{"
# from a truncated response); the deterministic template is preferable.
_MIN_BACKGROUND_CHARS = 20

# Canonical shape of a generated background. All generators return exactly
# these keys so the mod and the memory store can rely on a stable contract.
BACKGROUND_SHAPE: dict[str, Any] = {
    "text": "",
    "summary": "",
    "traits": [],
    "source": "template",
    "mood_tags": [],
    "mood_influence": 0.5,
    "generated_at": 0.0,
    "stale": False,
}


def _lang_from_data(data: dict) -> str:
    """Pick a language from a data dict (``lang``/``language``), defaulting to en."""
    if not isinstance(data, dict):
        return "en"
    return normalize_lang(str(data.get("lang") or data.get("language") or ""))


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


# Native game traits include a large amount of non-personality plumbing (gender
# options, relationship expectations, species, occult, life stage, likes/dislikes
# preferences, S4CL markers). Dumped raw into a prompt they bury the handful of
# traits that actually describe who the Sim is, so the background reads generic.
# These helpers keep the personality traits and render them readable.
_LIFE_STAGE_TRAITS = frozenset(
    (
        "adult",
        "youngadult",
        "yadult",
        "teen",
        "child",
        "toddler",
        "infant",
        "baby",
        "elder",
    )
)

_TECHNICAL_TRAIT_PREFIXES = (
    "gender",
    "genderoptions",
    "sexualorientation",
    "sextrait",
    "relexpectations",
    "species",
    "occult",
    "walkstyle",
    "handedness",
    "umbrella",
    "civicpolicy",
    "hidden",
    "s4cl",
    "main_trait",
    "simpreference",
    "statistic",
    "commodity",
    "buff",
)

# Splits camel-case tuning names into words (``FamilyOriented`` -> ``Family
# Oriented``).
_RE_TRAIT_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _strip_trait_prefix(name: str) -> str:
    """Drop the ``trait_``/``Trait`` tuning prefix from a native trait name."""
    text = name.strip()
    lowered = text.lower()
    for prefix in ("trait_", "trait"):
        if lowered.startswith(prefix):
            text = text[len(prefix) :]
            break
    return text.strip(" _")


def _is_technical_trait(name: str) -> bool:
    """True when a native trait is plumbing, not personality."""
    core = _strip_trait_prefix(name).lower().replace(" ", "").replace("_", "")
    if not core:
        return True
    if core in _LIFE_STAGE_TRAITS:
        return True
    return core.startswith(_TECHNICAL_TRAIT_PREFIXES)


def _pretty_trait(name: str) -> str:
    """Render a native trait as readable words (``trait_FamilyOriented``)."""
    text = _strip_trait_prefix(name).replace("_", " ").strip()
    text = _RE_TRAIT_CAMEL.sub(" ", text)
    return " ".join(text.split())


def clean_traits(traits: Any) -> list[str]:
    """Filter native traits to personality ones and make them readable.

    Technical traits are dropped, the ``trait_`` prefix is stripped and camel
    case split into words (``trait_FamilyOriented`` -> ``Family Oriented``).
    Already-readable names are preserved; duplicates are removed. Never raises.
    """
    result: list[str] = []
    seen: set[str] = set()
    for raw in _string_list(traits):
        if _is_technical_trait(raw):
            continue
        pretty = _pretty_trait(raw)
        key = pretty.lower()
        if not pretty or key in seen:
            continue
        seen.add(key)
        result.append(pretty)
    return result



def _native_view(data: dict) -> dict:
    """Merge a profile's nested ``native`` block over the top-level data.

    A stored profile keeps the native facts under ``native`` (traits/age/career/
    skills/relationships/kinship/aspiration); a census entry keeps them at the
    top level. This returns one flat view so facts resolve either way.
    """
    data = _as_dict(data)
    native = data.get("native")
    if isinstance(native, dict):
        merged = dict(native)
        for key, value in data.items():
            merged.setdefault(key, value)
        return merged
    return data


def _format_skills(skills: Any) -> list[str]:
    if isinstance(skills, dict):
        result: list[str] = []
        for name, level in skills.items():
            if level in (None, ""):
                result.append(str(name))
            else:
                result.append(f"{name} Lv{level}")
        return result
    return _string_list(skills)


def _format_relationships(relationships: Any) -> list[str]:
    if not isinstance(relationships, (list, tuple)):
        return []
    result: list[str] = []
    for rel in list(relationships)[:8]:
        if isinstance(rel, dict):
            partner = ""
            for key in ("name", "full_name", "target_name", "target", "other", "sim", "sim_name"):
                value = rel.get(key)
                if value:
                    partner = str(value)
                    break
            label = ""
            for key in ("relation", "relationship", "type", "status", "label", "track"):
                value = rel.get(key)
                if value:
                    label = str(value)
                    break
            if partner and label:
                result.append(f"{partner} ({label})")
            elif partner:
                result.append(partner)
            elif label:
                result.append(label)
            # else: unlabeled numeric-only relationship -> skip (never leak ids)
        else:
            text = str(rel).strip()
            if text:
                result.append(text)
    return result


def _format_kinship(kinship: Any) -> list[str]:
    """Render native family relations as ``"<relation>: <name>"`` lines."""
    if not isinstance(kinship, (list, tuple)):
        return []
    result: list[str] = []
    for rel in list(kinship)[:12]:
        if not isinstance(rel, dict):
            continue
        label = str(rel.get("relation") or "").strip()
        name = str(rel.get("name") or "").strip()
        target = rel.get("target_id")
        if label and name:
            result.append(f"{label}: {name}")
        elif label and target not in (None, ""):
            result.append(f"{label}: {target}")
        elif label:
            result.append(label)
    return result


def _summarize(text: str, limit: int = 160) -> str:
    """Return the first sentence of ``text``, capped at ``limit`` characters."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    for marker in (". ", "! ", "? ", "\n"):
        index = cleaned.find(marker)
        if index != -1:
            cleaned = cleaned[: index + 1].strip()
            break
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3].rstrip() + "..."
    return cleaned


def _background(
    text: str,
    summary: str,
    traits: list[str],
    source: str,
    mood_tags: list[str],
    mood_influence: float,
) -> dict:
    return {
        "text": text,
        "summary": summary,
        "traits": list(traits),
        "source": source,
        "mood_tags": list(mood_tags),
        "mood_influence": clamp01(mood_influence),
        "generated_at": time.time(),
        "stale": False,
    }


def _influence_label(lang: str, mood_influence: float) -> str:
    value = clamp01(mood_influence)
    if value <= 0.15:
        return content_i18n.t(lang, "background.influence.neutral")
    if value <= 0.4:
        return content_i18n.t(lang, "background.influence.light")
    if value <= 0.7:
        return content_i18n.t(lang, "background.influence.clear")
    return content_i18n.t(lang, "background.influence.strong")


def _mood_instruction(mood_influence: float) -> str:
    """English sentence telling the model how strongly the mood should show."""
    value = clamp01(mood_influence)
    if value <= 0.15:
        detail = (
            "Keep the writing realistic and character-driven; the neighborhood mood "
            "should barely color it."
        )
    elif value <= 0.4:
        detail = "Let the neighborhood mood gently color tone, word choice and small details."
    elif value <= 0.7:
        detail = "Let the neighborhood mood clearly shape tone, conflicts and how events are framed."
    else:
        detail = (
            "Make the writing strongly mood-driven; the zeitgeist should dominate tone, "
            "imagery and story beats."
        )
    return f"Mood influence {value:.2f}/1.00: {detail}"


def _mood_clause(lang: str, mood_tags: list[str], mood_influence: float) -> str:
    label = _influence_label(lang, mood_influence)
    tags = ", ".join(mood_tags)
    value = clamp01(mood_influence)
    if tags:
        return content_i18n.t(lang, "background.mood.with_tags", tags=tags, label=label, value=value)
    return content_i18n.t(lang, "background.mood.no_tags", label=label, value=value)


def _sim_facts(sim_data: dict) -> str:
    data = _native_view(sim_data)
    lines = [
        f"Name: {data.get('full_name') or data.get('name') or 'unknown'}",
        f"Age: {data.get('age') or 'unknown'}",
        f"Gender: {data.get('gender') or 'unknown'}",
        f"Aspiration: {data.get('aspiration') or 'unknown'}",
        f"Career: {data.get('career') or 'none'}",
        f"Native traits: {', '.join(clean_traits(data.get('traits'))) or 'none'}",
        f"Skills: {', '.join(_format_skills(data.get('skills'))) or 'none'}",
        f"Relationships: {', '.join(_format_relationships(data.get('relationships'))) or 'none'}",
        f"Family (kinship): {', '.join(_format_kinship(data.get('kinship'))) or 'none'}",
    ]
    return "\n".join(lines)


def fallback_sim_background(
    sim_data: dict, mood_tags: list[str], mood_influence: float = 0.5
) -> dict:
    """Deterministic Sim background in the requested language (via ``sim_data``)."""
    data = _native_view(sim_data)
    lang = _lang_from_data(data)
    tags = normalize_zeitgeist({"mood_tags": mood_tags})["mood_tags"]
    influence = clamp01(mood_influence)

    name = str(data.get("full_name") or data.get("name") or "This Sim").strip() or "This Sim"
    age = str(data.get("age") or "").strip()
    career = str(data.get("career") or "").strip()
    aspiration = str(data.get("aspiration") or "").strip()
    traits = clean_traits(data.get("traits"))[:6]
    skills = _format_skills(data.get("skills"))[:6]
    relationships = _format_relationships(data.get("relationships"))[:8]
    kinship = _format_kinship(data.get("kinship"))[:8]
    hints = str(data.get("player_hints") or "").strip()

    if age:
        head = content_i18n.t(lang, "background.sim.head_age", name=name, age=age)
    else:
        head = content_i18n.t(lang, "background.sim.head", name=name)
    parts = [head]
    if traits:
        parts.append(content_i18n.t(lang, "background.sim.traits", traits=", ".join(traits)))
    else:
        parts.append(content_i18n.t(lang, "background.sim.no_traits"))
    if career:
        parts.append(content_i18n.t(lang, "background.sim.career", career=career))
    if aspiration:
        parts.append(content_i18n.t(lang, "background.sim.aspiration", aspiration=aspiration))
    if skills:
        parts.append(content_i18n.t(lang, "background.sim.skills", skills=", ".join(skills)))
    if relationships:
        parts.append(
            content_i18n.t(
                lang, "background.sim.relationships", relationships="; ".join(relationships)
            )
        )
    if kinship:
        parts.append(content_i18n.t(lang, "background.sim.family", family="; ".join(kinship)))
    parts.append(_mood_clause(lang, tags, influence))
    if hints:
        parts.append(content_i18n.t(lang, "background.sim.hints", hints=hints))

    text = " ".join(parts)
    return _background(text, _summarize(text), traits, "template", tags, influence)


def _household_members(household_data: dict) -> list[str]:
    data = _as_dict(household_data)
    names: list[str] = []
    for key in ("member_names", "members"):
        value = data.get(key)
        if not isinstance(value, (list, tuple)):
            continue
        for item in value:
            if isinstance(item, dict):
                name = str(
                    item.get("full_name") or item.get("name") or item.get("sim_name") or ""
                ).strip()
            else:
                name = str(item).strip()
            if name and name not in names:
                names.append(name)
    return names[:12]


def fallback_household_background(
    household_data: dict, mood_tags: list[str], mood_influence: float = 0.5
) -> dict:
    """Deterministic household background in the requested language (via data)."""
    data = _as_dict(household_data)
    lang = _lang_from_data(data)
    tags = normalize_zeitgeist({"mood_tags": mood_tags})["mood_tags"]
    influence = clamp01(mood_influence)

    name = str(data.get("name") or data.get("household_name") or "This household").strip()
    name = name or "This household"
    members = _household_members(data)
    funds = data.get("funds")
    hints = str(data.get("player_hints") or "").strip()

    member_count = len(members)
    if members:
        head = content_i18n.t(
            lang,
            "background.household.head_members",
            name=name,
            count=member_count,
            members=", ".join(members),
        )
    else:
        head = content_i18n.t(lang, "background.household.head", name=name, count=member_count)
    parts = [head]
    if funds not in (None, ""):
        parts.append(content_i18n.t(lang, "background.household.funds", funds=funds))
    parts.append(_mood_clause(lang, tags, influence))
    if hints:
        parts.append(content_i18n.t(lang, "background.household.hints", hints=hints))

    text = " ".join(parts)
    return _background(text, _summarize(text), [], "template", tags, influence)


def _extract_json_object(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _looks_like_json(text: str) -> bool:
    """True when a string is (part of) a JSON object rather than prose."""
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        return True
    return '"text"' in text or "'text'" in text


def _extract_json_text_field(raw: str) -> str:
    """Pull the ``"text"`` value out of a possibly *truncated* JSON answer.

    ``json.loads`` fails on a truncated object, which used to leak the raw JSON
    (or a lone ``{``) into the Sim's stored background. This scans the ``"text"``
    string value to its closing quote â€” or to the end of the text when the
    response was cut off â€” and unescapes the common JSON escapes. Never raises.
    """
    key = raw.find('"text"')
    if key == -1:
        return ""
    colon = raw.find(":", key + len('"text"'))
    if colon == -1:
        return ""
    start = raw.find('"', colon + 1)
    if start == -1:
        return ""

    escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
    chars: list[str] = []
    index = start + 1
    while index < len(raw):
        char = raw[index]
        if char == "\\" and index + 1 < len(raw):
            nxt = raw[index + 1]
            chars.append(escapes.get(nxt, nxt))
            index += 2
            continue
        if char == '"':
            break
        chars.append(char)
        index += 1
    return "".join(chars).strip()


def _background_from_response(
    text: str,
    native_traits: list[str],
    mood_tags: list[str],
    mood_influence: float,
) -> dict | None:
    raw = (text or "").strip()
    if not raw:
        return None

    parsed = _extract_json_object(raw)
    if parsed is not None:
        body = str(parsed.get("text") or parsed.get("background") or parsed.get("description") or "")
        summary = str(parsed.get("summary") or parsed.get("short_summary") or "")
        traits = clean_traits(parsed.get("traits")) or native_traits
    else:
        # Invalid/truncated JSON: salvage the prose field, never the raw object.
        salvaged = _extract_json_text_field(raw)
        if not salvaged and _looks_like_json(raw):
            return None
        body = salvaged or raw
        summary = ""
        traits = native_traits

    body = body.strip()
    if not body or _looks_like_json(body) or len(body) < _MIN_BACKGROUND_CHARS:
        return None
    if not summary.strip():
        summary = _summarize(body)
    return _background(body, summary.strip(), traits, "llm", mood_tags, mood_influence)


def _build_sim_messages(
    sim_data: dict,
    zeitgeist: dict,
    player_hints: str,
    lang: str,
    mood_influence: float,
) -> list[dict[str, str]]:
    data = _native_view(sim_data)
    name = str(data.get("full_name") or data.get("name") or "the Sim").strip()
    system = (
        "You are the God agent's biographer for a Sims 4 save. You write backgrounds "
        "that fit the neighborhood zeitgeist. The native Sim data is ground truth: "
        "never contradict aspiration, traits, age, career, skills, relationships or kinship."
    )
    user = (
        f"Native Sim data (ground truth):\n{_sim_facts(sim_data)}\n\n"
        f"{zeitgeist_to_prompt_block(zeitgeist)}\n\n"
        f"{_mood_instruction(mood_influence)}\n"
        f"Player hints: {str(player_hints or '').strip() or 'none'}\n\n"
        "Instructions:\n"
        f"- Write a 2-4 sentence background for {name}.\n"
        f"- Write only in {content_i18n.language_name(lang)}.\n"
        "- Ground the story in the native facts: the aspiration should drive the "
        "Sim's goals, and the personality traits should shape their behavior.\n"
        "- Name concrete people from the relationships/family data. If the Sim has "
        "family or relationships, do NOT describe them as lonely, isolated or alone.\n"
        "- Never contradict the native aspiration, traits, age, career, skills, "
        "relationships or kinship.\n"
        '- Return ONLY a JSON object with keys "text" (string), "summary" '
        '(one sentence) and "traits" (array of native trait strings).'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _build_household_messages(
    household_data: dict,
    zeitgeist: dict,
    player_hints: str,
    lang: str,
    mood_influence: float,
) -> list[dict[str, str]]:
    name = str(household_data.get("name") or household_data.get("household_name") or "")
    name = name or "the household"
    members = _household_members(household_data)
    facts = [
        f"Household: {name}",
        f"Members: {', '.join(members) or 'unknown'}",
        f"Funds: {household_data.get('funds', 'unknown')}",
    ]
    system = (
        "You are the God agent's biographer for a Sims 4 save. You write household "
        "backgrounds that fit the neighborhood zeitgeist. The native household data "
        "is ground truth: never contradict names, membership or kinship."
    )
    user = (
        "Native household data (ground truth):\n" + "\n".join(facts) + "\n\n"
        f"{zeitgeist_to_prompt_block(zeitgeist)}\n\n"
        f"{_mood_instruction(mood_influence)}\n"
        f"Player hints: {str(player_hints or '').strip() or 'none'}\n\n"
        "Instructions:\n"
        f"- Write a 2-4 sentence background for {name}.\n"
        f"- Write only in {content_i18n.language_name(lang)}.\n"
        "- Never contradict the native names, membership or kinship.\n"
        '- Return ONLY a JSON object with keys "text" (string), "summary" '
        '(one sentence) and "traits" (array of strings).'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


async def _complete_guarded(
    messages: list[dict[str, str]],
    registry: Any,
    target_lang: str,
    *,
    build: Any,
) -> tuple[dict | None, str | None]:
    """Call the model, then retry once if the prose is in the wrong language.

    ``build`` maps the raw response text to a background dict (or None when the
    answer was JSON/incomplete). A wrong-language answer is retried once with a
    reinforced directive and a larger token budget; when it is still wrong or
    empty, ``(None, None)`` lets the caller fall back to the localized template.
    Never raises.
    """
    for attempt in range(2):
        try:
            if attempt == 0:
                response = await registry.complete(
                    messages, lang=target_lang, temperature=0.8,
                    max_tokens=BACKGROUND_MAX_TOKENS, purpose="background",
                )
            else:
                retry_messages = list(messages) + [
                    {"role": "system", "content": langguard.language_directive(target_lang, reinforced=True)}
                ]
                response = await registry.complete(
                    retry_messages, lang=target_lang, temperature=0.6,
                    max_tokens=int(BACKGROUND_MAX_TOKENS * 1.5), purpose="background",
                )
        except Exception as exc:
            logger.warning("background generation failed: %s", exc)
            return None, None
        background = build(getattr(response, "text", ""))
        if background is None:
            continue
        if langguard.is_wrong_lang(background.get("text", ""), target_lang):
            logger.info("langguard rejected background attempt %d (target=%s)", attempt + 1, target_lang)
            continue
        return background, getattr(response, "provider", None)
    return None, None


async def generate_sim_background(
    sim_data: dict,
    zeitgeist: dict,
    player_hints: str,
    lang: str,
    registry: Any,
    mood_influence: float,
) -> dict:
    """Generate a Sim background, falling back to a deterministic template.

    Returns ``{"background": <BACKGROUND_SHAPE>, "provider": str|None}``.
    Never raises.
    """
    data = _as_dict(sim_data)
    tags = normalize_zeitgeist(zeitgeist)["mood_tags"]
    influence = clamp01(mood_influence)
    target_lang = normalize_lang(lang)

    fallback = fallback_sim_background(
        {**data, "lang": target_lang, "player_hints": player_hints}, tags, influence
    )
    if registry is None:
        return {"background": fallback, "provider": None}

    try:
        messages = _build_sim_messages(data, zeitgeist, player_hints, target_lang, influence)
        traits = clean_traits(_native_view(data).get("traits"))
        background, provider = await _complete_guarded(
            messages,
            registry,
            target_lang,
            build=lambda text: _background_from_response(text, traits, tags, influence),
        )
        if background is None:
            return {"background": fallback, "provider": None}
        return {"background": background, "provider": provider}
    except Exception as exc:
        logger.warning("sim background generation failed: %s", exc)
        return {"background": fallback, "provider": None}

async def generate_household_background(
    household_data: dict,
    zeitgeist: dict,
    player_hints: str,
    lang: str,
    registry: Any,
    mood_influence: float,
) -> dict:
    """Generate a household background, falling back to a deterministic template.

    Returns ``{"background": <BACKGROUND_SHAPE>, "provider": str|None}``.
    Never raises.
    """
    data = _as_dict(household_data)
    tags = normalize_zeitgeist(zeitgeist)["mood_tags"]
    influence = clamp01(mood_influence)
    target_lang = normalize_lang(lang)

    fallback = fallback_household_background(
        {**data, "lang": target_lang, "player_hints": player_hints}, tags, influence
    )
    if registry is None:
        return {"background": fallback, "provider": None}

    try:
        messages = _build_household_messages(data, zeitgeist, player_hints, target_lang, influence)
        background, provider = await _complete_guarded(
            messages,
            registry,
            target_lang,
            build=lambda text: _background_from_response(
                text, clean_traits(data.get("traits")), tags, influence
            ),
        )
        if background is None:
            return {"background": fallback, "provider": None}
        return {"background": background, "provider": provider}
    except Exception as exc:
        logger.warning("household background generation failed: %s", exc)
        return {"background": fallback, "provider": None}


def is_stale(background: dict | None, mood_influence: float, mood_tags: list[str]) -> bool:
    """Return True when a cached background must be regenerated.

    A background is stale when it is missing, was already flagged stale, or its
    recorded ``mood_influence``/``mood_tags`` differ from the requested values.
    """
    if not isinstance(background, dict) or not background:
        return True
    if background.get("stale"):
        return True

    try:
        stored_influence = float(background.get("mood_influence"))
    except (TypeError, ValueError):
        return True
    if abs(stored_influence - clamp01(mood_influence)) > 0.001:
        return True

    stored_tags = background.get("mood_tags")
    if not isinstance(stored_tags, list):
        return True
    requested = normalize_zeitgeist({"mood_tags": mood_tags})["mood_tags"]
    return [str(tag) for tag in stored_tags] != requested
