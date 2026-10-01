"""LanguagePolicy: one reinforced directive + a post-generation guard (v0.4 P2).

Every LLM surface that produces player- or Sim-facing prose must (a) state the
target language explicitly and (b) be checked afterwards. ``language_directive``
centralizes (a); ``check``/``detect_lang`` implement (b) using data-driven
lexical hints (per-locale ``locales_content/lexicon.<code>.json``: ``stopwords``
+ ``markers``/``chars``) so adding a language needs no code change: drop the
locale's lexical file and its manifest entry and detection picks it up.

The guard is deliberately conservative: it only flags a mismatch when another
supported locale scores clearly better than the requested one, so a short line
("Olá!") is never rejected for having too few markers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .. import content_i18n

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# How much better another locale must score before the text is flagged.
_DETECT_MARGIN = 1


def _tokens(text: Any) -> list[str]:
    return [match.group(0).lower() for match in _WORD_RE.finditer(str(text or ""))]


def _stopwords(lang: str) -> set[str]:
    """Return the per-locale stopword set (manifest-driven, never raises)."""
    return {str(word).lower() for word in content_i18n.locale_stopwords(lang)}


def _hints(lang: str) -> dict[str, Any]:
    return content_i18n.locale_lang_hints(lang)


def language_name(lang: str) -> str:
    """Human-readable name for ``lang`` (delegates to the content manifest)."""
    return content_i18n.language_name(lang)


def language_directive(lang: str, *, reinforced: bool = False) -> str:
    """The single language line every prompt must include (v0.4 P2).

    ``reinforced`` produces a stricter wording used on the one retry after a
    detected mismatch.
    """
    code = content_i18n.normalize_lang(lang)
    name = language_name(code)
    base = f"Write ONLY in {name} ({code}). Never use any other language."
    if reinforced:
        base += (
            f" The previous answer was not in {name}; rewrite it entirely in "
            f"{name}, not a single word of English or any other language."
        )
    return base


def looks_like_json_or_template(text: Any) -> bool:
    """True for raw JSON/template output that must never reach the player."""
    cleaned = str(text or "").strip()
    if not cleaned:
        return False
    if cleaned[0] in "{[" and cleaned[-1] in "}]":
        return True
    lowered = cleaned.lower()
    return '":' in cleaned or lowered.startswith(('"summary"', "summary:"))


@dataclass(frozen=True)
class LanguageCheck:
    """Result of a post-generation language guard."""

    ok: bool
    detected: str
    target: str
    reason: str = ""

    def as_log(self) -> str:
        return (
            f"target={self.target} detected={self.detected} ok={self.ok}"
            + (f" reason={self.reason}" if self.reason else "")
        )


def detect_lang(text: Any, candidates: list[str] | None = None) -> str | None:
    """Return the best-matching supported locale for ``text``, or ``None``.

    Scores each candidate by stopword hits plus lexicon marker/char hints and
    returns the top scorer. ``None`` means "no confident signal" (never pick a
    language from noise).
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    if looks_like_json_or_template(raw):
        return None

    codes = candidates or content_i18n.available_locales()
    if not codes:
        return None

    tokens = _tokens(raw)
    lowered = raw.lower()
    scored: list[tuple[int, str]] = []
    for code in codes:
        score = 0
        stop = _stopwords(code)
        for token in tokens:
            if token in stop:
                score += 1
        hints = _hints(code)
        markers = hints.get("markers")
        if isinstance(markers, list):
            for marker in markers:
                if str(marker).lower() in lowered:
                    score += 1
        chars = hints.get("chars")
        if isinstance(chars, list):
            for char in chars:
                if str(char) and str(char) in lowered:
                    score += 1
        scored.append((score, code))

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score, best_code = scored[0]
    if best_score <= 0:
        return None
    # A tie is not confident; return None so the guard never guesses.
    if len(scored) > 1 and scored[1][0] == best_score:
        return None
    return best_code


def check(text: Any, lang: str) -> LanguageCheck:
    """Check whether ``text`` is written in ``lang`` (never raises)."""
    target = content_i18n.normalize_lang(lang)
    raw = str(text or "").strip()
    if not raw:
        # Nothing generated cannot be wrong; the deterministic fallback decides.
        return LanguageCheck(True, target, target, "empty")
    if looks_like_json_or_template(raw):
        return LanguageCheck(False, target, target, "json")
    detected = detect_lang(raw)
    if detected is None:
        return LanguageCheck(True, target, target, "unknown")
    if detected == target:
        return LanguageCheck(True, detected, target)
    # Only flag when the other locale is clearly ahead (see detect_lang ties).
    return LanguageCheck(False, detected, target, "mismatch")


def is_wrong_lang(text: Any, lang: str) -> bool:
    """Convenience wrapper around :func:`check`."""
    return not check(text, lang).ok
