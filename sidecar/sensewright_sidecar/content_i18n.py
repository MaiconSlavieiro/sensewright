"""Data-driven content localization for deterministic (non-LLM) text.

English-only code. Locale tables live as flat JSON files under
``locales_content/`` and the supported set is described by
``locales_content/manifest.json``. Adding a language means dropping a
``<code>.json`` file next to the manifest and adding a manifest entry - no code
change is required.

The module is import-light and side-effect-free: JSON files are read lazily on
first use and cached afterwards.
"""

from __future__ import annotations

import json
import os
from typing import Any

_CONTENT_DIR = os.path.join(os.path.dirname(__file__), "locales_content")
_MANIFEST_PATH = os.path.join(_CONTENT_DIR, "manifest.json")

_manifest_cache: dict[str, Any] | None = None
_table_cache: dict[str, dict[str, str]] = {}
_lexicon_cache: dict[str, Any] | None = None
_locale_lexicon_cache: dict[str, dict[str, Any]] = {}


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _manifest() -> dict[str, Any]:
    global _manifest_cache
    if _manifest_cache is None:
        data = _read_json(_MANIFEST_PATH)
        _manifest_cache = data if isinstance(data, dict) else {}
    return _manifest_cache


def default_lang() -> str:
    """Return the manifest's default locale code (or its first locale)."""
    manifest = _manifest()
    code = str(manifest.get("default") or "").strip()
    if code:
        return code
    entries = manifest.get("locales")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, dict) and str(entry.get("code") or "").strip():
                return str(entry["code"]).strip()
    return ""


def locale_entries() -> list[dict]:
    """Return normalized manifest entries with ``code``/``name``/``match``."""
    entries = _manifest().get("locales")
    if not isinstance(entries, list):
        return []
    result: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip()
        if not code:
            continue
        match = entry.get("match")
        result.append(
            {
                "code": code,
                "name": str(entry.get("name") or code),
                "match": [str(token) for token in match] if isinstance(match, list) else [],
            }
        )
    return result


def available_locales() -> list[str]:
    """Return every supported locale code, in manifest order."""
    return [entry["code"] for entry in locale_entries()]


def language_name(lang: str) -> str:
    """Return the human-readable name for ``lang``, else the tag itself."""
    entry = _match_entry(str(lang or ""))
    if entry is not None:
        return entry["name"]
    return str(lang)


def _normalize_token(value: str) -> str:
    return str(value or "").strip().lower().replace("_", "-")


def _token_matches(token: str, normalized: str) -> bool:
    """True when ``token`` matches ``normalized`` (BCP-47 boundary aware).

    Short tokens (<= 3 chars, e.g. ``en``/``pt``) must sit on a boundary so an
    unrelated word like ``french`` never matches the ``en`` token; longer tokens
    are substrings so enum reprs like ``Language.BrazilianPortuguese`` resolve.
    """
    token = _normalize_token(token)
    if not token:
        return False
    if token == normalized:
        return True
    if len(token) >= 4:
        return token in normalized
    return (
        normalized.startswith(token + "-")
        or normalized.endswith("-" + token)
        or ("-" + token + "-") in normalized
    )


def _match_entry(value: str) -> dict | None:
    """Return the manifest entry matching ``value`` (code or match tokens)."""
    normalized = _normalize_token(value)
    if not normalized:
        return None
    for entry in locale_entries():
        code = _normalize_token(entry["code"])
        if normalized == code or normalized.startswith(code + "-"):
            return entry
        for token in entry["match"]:
            if _token_matches(token, normalized):
                return entry
    return None


def normalize_lang(value: str | None) -> str:
    """Resolve ``value`` to a supported locale code, else the default locale."""
    entry = _match_entry("" if value is None else str(value))
    if entry is not None:
        return entry["code"]
    return default_lang()


def lexicon() -> dict[str, Any]:
    """Return the cross-locale lexical data (emotions/names/shared stopwords).

    Data lives in ``locales_content/lexicon.json``. Per-locale stopwords and
    language-detection hints live in ``lexicon.<code>.json`` and are reached
    through :func:`locale_lexicon` (manifest-driven, so adding a language needs
    no code change). Never raises (an empty dict when the file is missing).
    """
    global _lexicon_cache
    if _lexicon_cache is None:
        data = _read_json(os.path.join(_CONTENT_DIR, "lexicon.json"))
        _lexicon_cache = data if isinstance(data, dict) else {}
    return _lexicon_cache


def locale_lexicon(lang: str) -> dict[str, Any]:
    """Return the per-locale lexical hints (``lexicon.<code>.json``).

    The file name is derived from the *resolved* locale code, never a hardcoded
    language: drop ``lexicon.<code>.json`` next to the locale table and it is
    picked up automatically. Returns ``{}`` when the locale has no hints.
    """
    code = normalize_lang(lang)
    if not code:
        return {}
    if code in _locale_lexicon_cache:
        return _locale_lexicon_cache[code]
    data = _read_json(os.path.join(_CONTENT_DIR, f"lexicon.{code}.json"))
    entry = data if isinstance(data, dict) else {}
    _locale_lexicon_cache[code] = entry
    return entry


def locale_stopwords(lang: str) -> list[str]:
    """Per-locale stopword list (empty when the locale defines none)."""
    words = locale_lexicon(lang).get("stopwords")
    return [str(word) for word in words] if isinstance(words, list) else []


def locale_lang_hints(lang: str) -> dict[str, Any]:
    """Per-locale language-detection hints: ``{markers, chars}``."""
    entry = locale_lexicon(lang)
    markers = entry.get("markers")
    chars = entry.get("chars")
    return {
        "markers": [str(item) for item in markers] if isinstance(markers, list) else [],
        "chars": [str(item) for item in chars] if isinstance(chars, list) else [],
    }


def _table(code: str) -> dict[str, str]:
    if code in _table_cache:
        return _table_cache[code]
    data = _read_json(os.path.join(_CONTENT_DIR, f"{code}.json"))
    table: dict[str, str] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                table[str(key)] = value
    _table_cache[code] = table
    return table


def _lookup(lang: str, key: str) -> str | None:
    code = normalize_lang(lang)
    table = _table(code)
    if key in table:
        return table[key]
    default = default_lang()
    if code != default:
        fallback = _table(default)
        if key in fallback:
            return fallback[key]
    return None


def t(lang: str, key: str, **args: object) -> str:
    """Translate ``key`` for ``lang`` with default-locale fallback.

    Unknown keys return the key itself and a formatting error returns the raw
    template - this function never raises.
    """
    template = _lookup(lang, key)
    if template is None:
        return key
    try:
        return template.format(**args)
    except Exception:
        return template
