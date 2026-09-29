"""Living personality: psyche blocks, life story and sleep absorption (P1).

This module owns the agent-side layers of a Sim that the God background never
touches: ``profile["psyche"]`` and ``profile["life_story"]`` (PLANO.md §14.4).
Salient events are absorbed into durable psychological blocks, the blocks fade
unless reinforced, and the whole thing is rendered as shaping lines the prompt
can show the model.

Design rules (shared with the rest of the sidecar):

- Every public function is deterministic when no LLM is available.
- ``now``/``registry`` are injectable; no public function ever raises.
- ``agent.graph`` is never imported here (the graph wires us in, not the reverse).
"""

from __future__ import annotations

import json
import logging
import math
import time
from typing import Any

from ..config import PersonalityConfig
from ..schemas import normalize_lang

logger = logging.getLogger(__name__)

# ─── Emotion table ────────────────────────────────────────────────────
# Documented keyword -> weight. The highest matching keyword wins; content
# without a match keeps the neutral weight of 1.0. Keys are matched as
# case-insensitive substrings, so "death" also fires on "death of a loved one".
_NEGATIVE_WEIGHTS: dict[str, float] = {
    "death": 2.5,
    "died": 2.5,
    "betray": 2.2,
    "betrayal": 2.2,
    "trauma": 2.2,
    "grief": 2.0,
    "loss": 2.0,
    "lost": 2.0,
    "divorce": 2.0,
    "fire": 2.0,
    "funeral": 2.0,
    "evicted": 2.0,
    "furious": 1.9,
    "fear": 1.8,
    "afraid": 1.8,
    "scared": 1.7,
    "terror": 1.8,
    "panic": 1.8,
    "rage": 1.8,
    "heartbreak": 1.8,
    "anger": 1.7,
    "angry": 1.7,
    "hate": 1.7,
    "bankrupt": 1.7,
    "fight": 1.6,
    "humiliat": 1.6,
    "jealous": 1.5,
    "broke": 1.5,
    "sad": 1.4,
    "cry": 1.4,
    "embarrass": 1.4,
}
_POSITIVE_WEIGHTS: dict[str, float] = {
    "wedding": 1.6,
    "birth": 1.6,
    "love": 1.6,
    "joy": 1.5,
    "married": 1.5,
    "promotion": 1.4,
    "happy": 1.3,
    "celebration": 1.3,
    "proud": 1.3,
    "romance": 1.3,
    "exciting": 1.3,
    "friend": 1.2,
}
EMOTION_WEIGHTS: dict[str, float] = {**_NEGATIVE_WEIGHTS, **_POSITIVE_WEIGHTS}

# ─── Decay / caps ─────────────────────────────────────────────────────
# lambda per day: intensity *= exp(-lambda * dt_days). Half-lives ≈ 5/10/23 days.
_DECAY_LAMBDAS: dict[str, float] = {"fast": 0.15, "normal": 0.07, "slow": 0.03}
# A block reinforced within this many days does not decay at all.
_REINFORCE_WINDOW_DAYS: dict[str, float] = {"fast": 1.0, "normal": 2.0, "slow": 3.0}
_DEFAULT_DECAY_LAMBDA = _DECAY_LAMBDAS["normal"]
_DEFAULT_REINFORCE_WINDOW = _REINFORCE_WINDOW_DAYS["normal"]
_INTENSITY_FLOOR = 0.05
_SALIENCE_FULL = 2.5  # salience that maps to a full-strength block
_DEFAULT_MAX_TRAUMAS = PersonalityConfig().max_traumas
_DEFAULT_MAX_BELIEFS = PersonalityConfig().max_beliefs
_MAX_TAGS = 20
_MAX_DRIFT = 0.1
_LIFE_STORY_MAX_LINES = 20
_LIFE_STORY_MAX_CHARS = 2000
_FORMAT_LIFE_STORY_LINES = 5

# ─── Localized deterministic templates ────────────────────────────────
_DEFAULT_SUBJECT = {"en": "someone close", "pt-BR": "alguém próximo"}
_TRAUMA_BELIEF = {
    "en": "brace yourself whenever {trigger} comes up",
    "pt-BR": "se encolhe sempre que {trigger} surge",
}
_BAGGAGE_BELIEF = {
    "en": "carry lingering feelings about {trigger}",
    "pt-BR": "carrega sentimentos persistentes sobre {trigger}",
}
_LIFE_LINE = {
    "en": "You lived through something involving {trigger}.",
    "pt-BR": "Você viveu algo envolvendo {trigger}.",
}
_LIFE_LINE_MANY = {
    "en": "You lived through {triggers}.",
    "pt-BR": "Você viveu {triggers}.",
}
_LANG_NAMES = {"en": "English", "pt-BR": "Brazilian Portuguese"}


# ─── Small coercion helpers ───────────────────────────────────────────
def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _as_list(value: Any) -> list:
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _unique_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = str(item).strip()
        key = text.lower()
        if text and key not in seen:
            out.append(text)
            seen.add(key)
    return out


def _positive_int(value: Any, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= 0 else default


def _now(value: float | None) -> float:
    if value is None:
        return time.time()
    return _as_float(value, time.time())


def _normalize_preset(preset: Any) -> str:
    value = str(preset or "").strip().lower()
    return value if value in _DECAY_LAMBDAS else "slow"


def _coerce_config(config: Any) -> PersonalityConfig:
    """Return a usable PersonalityConfig for ``None``/duck-typed inputs."""
    if isinstance(config, PersonalityConfig):
        return config
    if isinstance(config, dict):
        default = PersonalityConfig()
        data = {k: v for k, v in config.items() if k in PersonalityConfig.model_fields}
        try:
            return PersonalityConfig(**data)
        except Exception:
            return default
    return PersonalityConfig()


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


# ─── Salience ─────────────────────────────────────────────────────────
def _event_strings(event: dict) -> list[str]:
    """Collect every candidate text field from an event for emotion matching."""
    parts: list[str] = []
    if not isinstance(event, dict):
        return parts

    content = event.get("content")
    sources: list[Any] = []
    if isinstance(content, dict):
        sources.append(content)
        takeaways = content.get("emotional_takeaways")
        if isinstance(takeaways, (list, tuple)):
            parts.extend(str(item) for item in takeaways)
        elif isinstance(takeaways, str):
            parts.append(takeaways)
    elif isinstance(content, str):
        parts.append(content)
    sources.append(event)

    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in (
            "emotion",
            "buff",
            "buff_name",
            "mood",
            "message",
            "action",
            "topic",
            "text",
            "target",
            "target_name",
            "other_sim",
            "type",
        ):
            value = source.get(key)
            if isinstance(value, str):
                parts.append(value)
            elif isinstance(value, (list, tuple)):
                parts.extend(str(item) for item in value)
    return parts


def _emotion_weight(event: dict) -> float:
    text = " ".join(_event_strings(event)).lower()
    weight = 1.0
    for keyword, value in EMOTION_WEIGHTS.items():
        if keyword in text and value > weight:
            weight = value
    return weight


def salience(event: dict) -> float:
    """Importance × emotion weight for one event (default 1.0 when neutral)."""
    if not isinstance(event, dict):
        return 1.0
    importance = _as_float(event.get("importance"), 1.0)
    if importance < 0:
        importance = 0.0
    return importance * _emotion_weight(event)


def should_absorb(event: dict, threshold: float) -> bool:
    """True when an event is salient enough to enter the absorption queue."""
    return salience(event) >= _as_float(threshold, 0.0)


def _matched_keywords(event: dict, table: dict[str, float]) -> list[str]:
    text = " ".join(_event_strings(event)).lower()
    matched = [key for key in table if key in text]
    matched.sort(key=lambda key: table[key], reverse=True)
    return matched


def _event_trigger(event: dict) -> str:
    """Best-effort human-readable subject of the event."""
    content = event.get("content") if isinstance(event, dict) else None
    candidates: list[str] = []
    if isinstance(content, dict):
        for key in ("target", "target_name", "other_sim", "buff_name", "buff", "action", "topic"):
            value = content.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
    if isinstance(event, dict):
        for key in ("target", "name", "buff", "buff_name", "action", "topic", "message"):
            value = event.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        if not candidates:
            event_type = str(event.get("type") or "").strip()
            if event_type:
                candidates.append(event_type)
    return candidates[0] if candidates else ""


def _event_ids(events: list[dict]) -> list[str]:
    ids: list[str] = []
    for event in events:
        if isinstance(event, dict):
            event_id = event.get("id")
            if event_id not in (None, ""):
                ids.append(str(event_id))
    return ids


def _intensity_from_salience(value: Any) -> float:
    return max(_INTENSITY_FLOOR, min(1.0, _as_float(value, 1.0) / _SALIENCE_FULL))


# ─── Psyche normalization ─────────────────────────────────────────────
def _normalize_trauma(raw: Any, now: float, event_ids: list[str] | None = None) -> dict | None:
    if not isinstance(raw, dict):
        return None
    trigger = str(raw.get("trigger") or "").strip()
    belief = str(raw.get("belief") or "").strip()
    if not trigger and not belief:
        return None
    intensity = max(0.0, min(1.0, _as_float(raw.get("intensity"), 1.0)))
    first_seen = _as_float(raw.get("first_seen"), now)
    last_reinforced = _as_float(raw.get("last_reinforced"), first_seen)
    ids = _string_list(raw.get("source_event_ids"))
    if not ids and event_ids:
        ids = list(event_ids)
    return {
        "trigger": trigger,
        "belief": belief,
        "intensity": intensity,
        "first_seen": first_seen,
        "last_reinforced": last_reinforced,
        "source_event_ids": ids,
    }


def _normalize_baggage(raw: Any, now: float) -> dict | None:
    if not isinstance(raw, dict):
        return None
    belief = str(raw.get("belief") or "").strip()
    if not belief:
        return None
    source = str(raw.get("source") or "").strip()
    intensity = max(0.0, min(1.0, _as_float(raw.get("intensity"), 1.0)))
    last_reinforced = _as_float(raw.get("last_reinforced"), now)
    return {
        "belief": belief,
        "source": source,
        "intensity": intensity,
        "last_reinforced": last_reinforced,
    }


def _empty_psyche() -> dict:
    return {"traumas": [], "baggage": [], "aversions": [], "attachments": []}


def normalize_psyche(profile: dict) -> dict:
    """Return a copy of ``profile`` with well-typed ``psyche``/``life_story``.

    Malformed blocks are coerced or dropped; the input is never mutated.
    """
    source = profile if isinstance(profile, dict) else {}
    result = dict(source)

    raw_psyche = source.get("psyche")
    raw_psyche = raw_psyche if isinstance(raw_psyche, dict) else {}

    traumas: list[dict] = []
    for item in _as_list(raw_psyche.get("traumas")):
        block = _normalize_trauma(item, 0.0)
        if block is not None:
            traumas.append(block)

    baggage: list[dict] = []
    for item in _as_list(raw_psyche.get("baggage")):
        block = _normalize_baggage(item, 0.0)
        if block is not None:
            baggage.append(block)

    result["psyche"] = {
        "traumas": traumas,
        "baggage": baggage,
        "aversions": _string_list(raw_psyche.get("aversions")),
        "attachments": _string_list(raw_psyche.get("attachments")),
    }

    life = source.get("life_story")
    if isinstance(life, (list, tuple)):
        result["life_story"] = "\n".join(str(line) for line in life)
    elif life is None:
        result["life_story"] = ""
    else:
        result["life_story"] = str(life)
    return result


# ─── Decay ────────────────────────────────────────────────────────────
def _cap_blocks(blocks: list[dict], max_items: int) -> list[dict]:
    ordered = sorted(blocks, key=lambda block: _as_float(block.get("intensity"), 0.0), reverse=True)
    return ordered[: max_items]


def _decay_blocks(
    blocks: list[dict],
    now: float,
    lam: float,
    window_days: float,
) -> list[dict]:
    kept: list[dict] = []
    for block in blocks:
        reference = _as_float(block.get("last_reinforced"), 0.0)
        if reference <= 0:
            reference = _as_float(block.get("first_seen"), 0.0)
        if reference <= 0:
            kept.append(block)
            continue
        dt_days = max(0.0, (now - reference) / 86400.0)
        if dt_days <= window_days:
            kept.append(block)  # reinforced recently -> no decay
            continue
        intensity = _as_float(block.get("intensity"), 0.0) * math.exp(-lam * dt_days)
        if intensity < _INTENSITY_FLOOR:
            continue
        block = dict(block)
        block["intensity"] = round(intensity, 6)
        kept.append(block)
    return kept


def decay_psyche(
    profile: dict,
    now: float,
    preset: str = "slow",
    *,
    max_traumas: int | None = None,
    max_beliefs: int | None = None,
) -> dict:
    """Fade psyche block intensities; drop blocks below the floor and cap sizes.

    Traumas and beliefs decay from ``last_reinforced`` unless that timestamp is
    within the preset's reinforcement window. Returns a new profile dict.
    """
    result = normalize_psyche(profile)
    name = _normalize_preset(preset)
    lam = _DECAY_LAMBDAS[name]
    window = _REINFORCE_WINDOW_DAYS[name]
    current = _now(now)

    psyche = result["psyche"]
    trauma_limit = (
        _DEFAULT_MAX_TRAUMAS if max_traumas is None else _positive_int(max_traumas, _DEFAULT_MAX_TRAUMAS)
    )
    belief_limit = (
        _DEFAULT_MAX_BELIEFS if max_beliefs is None else _positive_int(max_beliefs, _DEFAULT_MAX_BELIEFS)
    )

    psyche["traumas"] = _cap_blocks(
        _decay_blocks(psyche["traumas"], current, lam, window), trauma_limit
    )
    psyche["baggage"] = _cap_blocks(
        _decay_blocks(psyche["baggage"], current, lam, window), belief_limit
    )
    return result


# ─── Merging ──────────────────────────────────────────────────────────
def _merge_block_values(old: dict, new: dict) -> dict:
    merged = dict(old)
    for key, value in new.items():
        if key == "intensity":
            merged[key] = min(
                1.0, max(_as_float(old.get(key), 0.0), _as_float(value, 0.0))
            )
        elif key == "source_event_ids":
            merged[key] = _unique_strings(_string_list(old.get(key)) + _string_list(value))
        elif key == "first_seen":
            old_ts = _as_float(old.get(key), 0.0)
            new_ts = _as_float(value, 0.0)
            candidates = [ts for ts in (old_ts, new_ts) if ts > 0]
            merged[key] = min(candidates) if candidates else 0.0
        elif key == "last_reinforced":
            merged[key] = max(_as_float(old.get(key), 0.0), _as_float(value, 0.0))
        elif value not in (None, ""):
            merged[key] = value
    return merged


def merge_block(blocks: list, new_block: dict, *, max_items: int, key: str) -> list:
    """Merge ``new_block`` into ``blocks`` by ``key`` and cap the list size.

    A matching key reinforces the existing block (intensity takes the max);
    otherwise the new block is appended. The result is sorted by intensity so
    the weakest blocks are the first to be dropped when ``max_items`` is hit.
    """
    existing = [block for block in _as_list(blocks) if isinstance(block, dict)]
    new_block = new_block if isinstance(new_block, dict) else {}
    new_key = str(new_block.get(key) or "").strip().lower()

    merged: list[dict] = []
    replaced = False
    for block in existing:
        block_key = str(block.get(key) or "").strip().lower()
        if new_key and block_key == new_key:
            merged.append(_merge_block_values(block, new_block))
            replaced = True
        else:
            merged.append(dict(block))
    if not replaced and new_block:
        merged.append(dict(new_block))

    limit = _positive_int(max_items, len(merged))
    return _cap_blocks(merged, limit)


def _merge_strings(existing: Any, new_items: list[str], limit: int) -> list[str]:
    merged = _unique_strings(_string_list(existing) + list(new_items))
    if limit and len(merged) > limit:
        return merged[-limit:]
    return merged


# ─── Absorption ───────────────────────────────────────────────────────
def _append_life_line(existing: Any, new_line: str) -> str:
    lines = [line.strip() for line in str(existing or "").splitlines() if line.strip()]
    if new_line and new_line.strip():
        lines.append(new_line.strip())
    if len(lines) > _LIFE_STORY_MAX_LINES:
        lines = lines[-_LIFE_STORY_MAX_LINES:]
    text = "\n".join(lines)
    if len(text) > _LIFE_STORY_MAX_CHARS:
        text = text[-_LIFE_STORY_MAX_CHARS:]
        newline = text.find("\n")
        if newline != -1:
            text = text[newline + 1 :]
    return text


def _merge_drift(personality: dict, drift: dict) -> dict:
    merged = dict(personality)
    for key, value in drift.items():
        delta = _as_float(value, float("nan"))
        if math.isnan(delta):
            continue
        delta = max(-_MAX_DRIFT, min(_MAX_DRIFT, delta))
        base = _as_float(merged.get(key), 0.0)
        merged[key] = max(0.0, min(1.0, base + delta))
    return merged


def _fallback_life_line(triggers: list[str], lang: str) -> str:
    subjects = _unique_strings(triggers)
    if not subjects:
        return _LIFE_LINE[lang].format(trigger=_DEFAULT_SUBJECT[lang])
    if len(subjects) == 1:
        return _LIFE_LINE[lang].format(trigger=subjects[0])
    joined = ", ".join(subjects[:3])
    return _LIFE_LINE_MANY[lang].format(triggers=joined)


def _fallback_payload(profile: dict, events: list[dict], now: float, lang: str) -> dict:
    """Derive psyche blocks from raw event content (no LLM)."""
    target = normalize_lang(lang)
    traumas: list[dict] = []
    baggage: list[dict] = []
    aversions: list[str] = []
    attachments: list[str] = []
    triggers: list[str] = []

    for event in events:
        if not isinstance(event, dict):
            continue
        trigger = _event_trigger(event)
        if trigger:
            triggers.append(trigger)
        subject = trigger or _DEFAULT_SUBJECT[target]
        intensity = _intensity_from_salience(salience(event))
        event_ids = _event_ids([event])

        negatives = _matched_keywords(event, _NEGATIVE_WEIGHTS)
        positives = _matched_keywords(event, _POSITIVE_WEIGHTS)

        if negatives:
            traumas.append(
                {
                    "trigger": subject,
                    "belief": _TRAUMA_BELIEF[target].format(trigger=subject),
                    "intensity": intensity,
                    "first_seen": now,
                    "last_reinforced": now,
                    "source_event_ids": event_ids,
                }
            )
            aversions.extend(negatives[:2])
        elif positives:
            baggage.append(
                {
                    "belief": _BAGGAGE_BELIEF[target].format(trigger=subject),
                    "source": subject,
                    "intensity": intensity,
                    "last_reinforced": now,
                }
            )
            attachments.append(subject)

    return {
        "life_story_line": _fallback_life_line(triggers, target),
        "traumas": traumas,
        "baggage": baggage,
        "aversions": aversions,
        "attachments": attachments,
        "personality_drift": {},
    }


def _apply_absorption(
    profile: dict,
    payload: dict,
    events: list[dict],
    now: float,
    config: PersonalityConfig,
    source: str,
) -> dict:
    data = normalize_psyche(profile)
    psyche = data["psyche"]
    event_ids = _event_ids(events)
    trauma_limit = _positive_int(getattr(config, "max_traumas", _DEFAULT_MAX_TRAUMAS), _DEFAULT_MAX_TRAUMAS)
    belief_limit = _positive_int(getattr(config, "max_beliefs", _DEFAULT_MAX_BELIEFS), _DEFAULT_MAX_BELIEFS)

    for raw in _as_list(payload.get("traumas")):
        block = _normalize_trauma(raw, now, event_ids=event_ids)
        if block is not None:
            psyche["traumas"] = merge_block(
                psyche["traumas"], block, max_items=trauma_limit, key="trigger"
            )
    for raw in _as_list(payload.get("baggage")):
        block = _normalize_baggage(raw, now)
        if block is not None:
            psyche["baggage"] = merge_block(
                psyche["baggage"], block, max_items=belief_limit, key="belief"
            )

    psyche["aversions"] = _merge_strings(
        psyche["aversions"], _string_list(payload.get("aversions")), _MAX_TAGS
    )
    psyche["attachments"] = _merge_strings(
        psyche["attachments"], _string_list(payload.get("attachments")), _MAX_TAGS
    )

    line = str(payload.get("life_story_line") or "").strip()
    if line:
        data["life_story"] = _append_life_line(data.get("life_story"), line)

    drift = payload.get("personality_drift")
    if isinstance(drift, dict) and drift and isinstance(data.get("personality"), dict):
        data["personality"] = _merge_drift(data["personality"], drift)

    data["psyche_source"] = source
    return data


def absorb(
    profile: dict,
    event: dict,
    config: PersonalityConfig | None = None,
    *,
    now: float | None = None,
    lang: str = "en",
) -> dict:
    """Deterministically absorb a single event (no LLM). Never raises."""
    try:
        cfg = _coerce_config(config)
        current = _now(now)
        result = normalize_psyche(profile)
        if not bool(getattr(cfg, "absorption_enabled", True)):
            return result
        if not isinstance(event, dict) or not should_absorb(
            event, getattr(cfg, "salience_threshold", 1.5)
        ):
            return result
        payload = _fallback_payload(result, [event], current, lang)
        return _apply_absorption(result, payload, [event], current, cfg, source="template")
    except Exception as exc:  # pragma: no cover - safety net
        logger.warning("absorb failed: %s", exc)
        try:
            return normalize_psyche(profile)
        except Exception:
            return {}


# ─── LLM absorption ───────────────────────────────────────────────────
def _lang_name(lang: str) -> str:
    return _LANG_NAMES.get(normalize_lang(lang), "English")


def _events_summary(events: list[dict]) -> str:
    lines: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "event").strip()
        trigger = _event_trigger(event)
        text = " ".join(_event_strings(event)).strip()
        if len(text) > 160:
            text = text[:160] + "..."
        line = f"- [{event_type}]"
        if trigger:
            line += f" {trigger}:"
        if text:
            line += f" {text}"
        lines.append(line)
    return "\n".join(lines) if lines else "- (no salient events)"


def _build_absorption_messages(profile: dict, events: list[dict], lang: str) -> list[dict[str, str]]:
    data = normalize_psyche(profile)
    name = str(data.get("name") or data.get("full_name") or "the Sim").strip() or "the Sim"
    existing = data["psyche"]
    summary = _events_summary(events)
    system = (
        "You are the subconscious of a character in The Sims 4. You compress "
        "raw experiences into compact, durable psychological blocks that shape "
        "how the character speaks and decides from now on."
    )
    user = (
        f"Sim: {name}\n"
        f"Existing psyche: {json.dumps(existing, ensure_ascii=False)}\n"
        f"Salient events:\n{summary}\n\n"
        "Instructions:\n"
        f"- Write only in {_lang_name(lang)}.\n"
        "- Write ONE short first-person life-story line in past tense.\n"
        "- Derive at most 2 traumas and 2 baggage beliefs from the events.\n"
        "- A trauma belief is a verb phrase, e.g. \"brace yourself whenever evil sims show up\".\n"
        "- intensity is a number between 0 and 1.\n"
        "- aversions/attachments are short noun phrases (may be empty).\n"
        "- personality_drift is a tiny dict of numeric deltas in [-0.1, 0.1] (may be empty).\n"
        '- Return ONLY a JSON object with keys "life_story_line" (string), '
        '"traumas" (array of {trigger, belief, intensity}), '
        '"baggage" (array of {belief, source, intensity}), '
        '"aversions" (array of strings), "attachments" (array of strings), '
        '"personality_drift" (object).'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _payload_is_useful(payload: dict) -> bool:
    if str(payload.get("life_story_line") or "").strip():
        return True
    for key in ("traumas", "baggage", "aversions", "attachments"):
        if _as_list(payload.get(key)):
            return True
    return isinstance(payload.get("personality_drift"), dict) and bool(payload["personality_drift"])


async def absorb_events(
    profile: dict,
    events: list,
    config: PersonalityConfig | None = None,
    *,
    lang: str = "en",
    registry: Any = None,
    now: float | None = None,
) -> dict:
    """Absorb salient events into psyche/life_story (sleep consolidation).

    Filters to salient events, decays the existing psyche, then asks the LLM
    (when a registry is given) for compact blocks. Any error degrades to the
    deterministic fallback. Returns the updated profile. Never raises.
    """
    try:
        cfg = _coerce_config(config)
        current = _now(now)
        result = normalize_psyche(profile)
        if not bool(getattr(cfg, "absorption_enabled", True)):
            return result

        threshold = _as_float(getattr(cfg, "salience_threshold", 1.5), 1.5)
        preset = str(getattr(cfg, "trauma_decay", "slow") or "slow")
        result = decay_psyche(
            result,
            current,
            preset=preset,
            max_traumas=getattr(cfg, "max_traumas", _DEFAULT_MAX_TRAUMAS),
            max_beliefs=getattr(cfg, "max_beliefs", _DEFAULT_MAX_BELIEFS),
        )

        salient = [event for event in _as_list(events) if should_absorb(event, threshold)]
        if not salient:
            return result

        if registry is not None:
            try:
                messages = _build_absorption_messages(result, salient, lang)
                response = await registry.complete(
                    messages,
                    lang=normalize_lang(lang),
                    temperature=0.6,
                    max_tokens=700,
                )
                raw_text = getattr(response, "text", "")
                parsed = _extract_json_object(raw_text)
                if isinstance(parsed, dict) and _payload_is_useful(parsed):
                    return _apply_absorption(result, parsed, salient, current, cfg, source="llm")
            except Exception as exc:
                logger.warning("personality absorption failed, using fallback: %s", exc)

        payload = _fallback_payload(result, salient, current, lang)
        return _apply_absorption(result, payload, salient, current, cfg, source="template")
    except Exception as exc:  # pragma: no cover - safety net
        logger.warning("absorb_events failed: %s", exc)
        try:
            return normalize_psyche(profile)
        except Exception:
            return {}


# ─── Prompt shaping ───────────────────────────────────────────────────
def format_life(profile: dict) -> str:
    """Render psyche + recent life_story as shaping lines for the prompt.

    Pure and safe with missing keys; returns "" when there is nothing to say.
    """
    try:
        data = profile if isinstance(profile, dict) else {}
        normalized = normalize_psyche(data)
        psyche = normalized.get("psyche") or {}
        lines: list[str] = []

        for block in psyche.get("traumas") or []:
            trigger = str(block.get("trigger") or "").strip() or "someone"
            belief = str(block.get("belief") or "").strip()
            if belief:
                lines.append(f"Because of what happened with {trigger}, you now {belief}.")
            else:
                lines.append(f"Because of what happened with {trigger}, you are guarded.")

        for block in psyche.get("baggage") or []:
            belief = str(block.get("belief") or "").strip()
            if not belief:
                continue
            source = str(block.get("source") or "").strip()
            if source:
                lines.append(f"You carry unresolved feelings about {source}: {belief}.")
            else:
                lines.append(f"You carry unresolved feelings: {belief}.")

        for item in psyche.get("aversions") or []:
            text = str(item).strip()
            if text:
                lines.append(f"You avoid {text}.")
        for item in psyche.get("attachments") or []:
            text = str(item).strip()
            if text:
                lines.append(f"You are attached to {text}.")

        life = str(normalized.get("life_story") or "")
        story_lines = [line.strip() for line in life.splitlines() if line.strip()]
        for line in story_lines[-_FORMAT_LIFE_STORY_LINES:]:
            lines.append(f"Your life story: {line}")

        return "\n".join(lines)
    except Exception:
        return ""
