"""Localized prompt anchors and 1-shot examples (structural language prevention).

Implements REQ-LLM-04: language adherence is guaranteed at the input by (1)
translating enum-like state before building the prompt, (2) including one short
1-shot example already in the target language, and (3) injecting an imperative
localized directive as the absolute LAST line of the prompt. There is no
post-generation lexical detector — ``lexicon.json`` is eliminated.
"""
from __future__ import annotations

from typing import Dict, Optional

#: Enum-like state values that must be translated before the prompt (subset).
_MOODS: Dict[str, Dict[str, str]] = {
    "happy": {"en": "happy", "pt-BR": "feliz"},
    "sad": {"en": "sad", "pt-BR": "triste"},
    "angry": {"en": "angry", "pt-BR": "irritado"},
    "tense": {"en": "tense", "pt-BR": "tenso"},
    "flirty": {"en": "flirty", "pt-BR": "paquerador"},
    "inspired": {"en": "inspired", "pt-BR": "inspirado"},
    "focused": {"en": "focused", "pt-BR": "concentrado"},
    "dazed": {"en": "dazed", "pt-BR": "confuso"},
    "bored": {"en": "bored", "pt-BR": "entediado"},
    "sleepy": {"en": "sleepy", "pt-BR": "sonolento"},
    "uncomfortable": {"en": "uncomfortable", "pt-BR": "desconfortável"},
    "fine": {"en": "fine", "pt-BR": "bem"},
    "confident": {"en": "confident", "pt-BR": "confiante"},
    "energized": {"en": "energized", "pt-BR": "energizado"},
}

_ACTIVITIES: Dict[str, Dict[str, str]] = {
    "idle": {"en": "idle", "pt-BR": "à toa"},
    "painting": {"en": "painting", "pt-BR": "pintando"},
    "cooking": {"en": "cooking", "pt-BR": "cozinhando"},
    "gardening": {"en": "gardening", "pt-BR": "cuidando do jardim"},
    "working": {"en": "working", "pt-BR": "trabalhando"},
    "sleeping": {"en": "sleeping", "pt-BR": "dormindo"},
    "socializing": {"en": "socializing", "pt-BR": "socializando"},
    "exercising": {"en": "exercising", "pt-BR": "se exercitando"},
    "reading": {"en": "reading", "pt-BR": "lendo"},
    "writing": {"en": "writing", "pt-BR": "escrevendo"},
}


def translate_enum(category: str, value: Optional[str], lang: str) -> str:
    """Translate an enum-like value (mood/activity) to ``lang``; pass-through if unknown."""
    if value is None:
        return ""
    table = _MOODS if category == "mood" else _ACTIVITIES if category == "activity" else None
    if table is None:
        return value
    entry = table.get(value)
    if entry is None:
        return value
    return entry.get(lang, entry.get("en", value))


def language_anchor(lang: str) -> str:
    """The imperative directive injected as the ABSOLUTE last line of the prompt."""
    if lang == "pt-BR":
        return (
            "IMPORTANTE: responda exclusivamente em português do Brasil (pt-BR), "
            "com a mesma naturalidade de um falante nativo."
        )
    return "IMPORTANT: respond exclusively in English (en), with native fluency."


def one_shot_example(lang: str) -> str:
    """A single short 1-shot example of JSON output already in ``lang``."""
    if lang == "pt-BR":
        return 'Exemplo de saída (JSON): {"response": "Oi! Como você está hoje?"}'
    return 'Output example (JSON): {"response": "Hi! How are you today?"}'
