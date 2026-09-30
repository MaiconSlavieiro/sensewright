"""
Localization (i18n) system for Sensewright.

Locale tables live as flat JSON files under ``sensewright_mod/locales/`` and the
supported set is described by ``locales/manifest.json``. The set of languages is
**data-driven**: adding a language means dropping ``<code>.json`` next to the
manifest and appending a manifest entry - no code change and no fixed locale
reference anywhere in this module.

Provides: locale discovery, language resolution (manifest -> game language ->
default), and :func:`t(key, **args)` with default-locale fallback.
"""


import io
import json
import os
from typing import Any, Dict, List, Optional

# Cache for loaded locale tables
_locale_cache: Dict[str, Dict[str, str]] = {}
_manifest_cache: Optional[Dict[str, Any]] = None
_current_locale: str = ""
_locale_override: Optional[str] = None  # explicit override from config
# True once the locale is settled (explicit override, or a game API answered).
_auto_detected: bool = False

_LOCALES_SUBDIR = "locales"
_MANIFEST_NAME = "manifest.json"


def _get_package_dir() -> str:
    """Return the directory containing this module (sensewright_mod)."""
    return os.path.dirname(os.path.abspath(__file__))


def _read_json_file(path: str) -> Dict[str, Any]:
    """Read a JSON object from the filesystem; {} on any failure."""
    try:
        with io.open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
            return data if isinstance(data, dict) else {}
    except (IOError, ValueError, OSError):
        return {}


def _read_json_from_zip(entry: str) -> Dict[str, Any]:
    """Read a JSON entry from inside the ``.ts4script`` (zipimport case)."""
    try:
        import zipfile

        module_path = os.path.abspath(__file__)
        marker = ".ts4script"
        index = module_path.lower().find(marker)
        if index == -1:
            return {}
        archive_path = module_path[: index + len(marker)]
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open(entry) as handle:
                data = json.loads(handle.read().decode("utf-8"))
                return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _read_locales_json(filename: str) -> Dict[str, Any]:
    """Read ``locales/<filename>`` from disk or from the archive."""
    package_dir = _get_package_dir()
    path = os.path.join(package_dir, _LOCALES_SUBDIR, filename)
    data = _read_json_file(path)
    if data:
        return data
    return _read_json_from_zip("sensewright_mod/locales/{}".format(filename))


# --- manifest / discovery (no fixed locale references) ---

def _manifest() -> Dict[str, Any]:
    """Return the cached locale manifest (data-driven registry)."""
    global _manifest_cache
    if _manifest_cache is None:
        _manifest_cache = _read_locales_json(_MANIFEST_NAME)
    return _manifest_cache


def locale_entries() -> List[Dict[str, Any]]:
    """Return normalized manifest entries (``code``/``name``/``match``)."""
    entries = _manifest().get("locales")
    if not isinstance(entries, list):
        return []
    result: List[Dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        code = entry.get("code")
        if not isinstance(code, str) or not code.strip():
            continue
        raw_match = entry.get("match")
        result.append({
            "code": code.strip(),
            "name": str(entry.get("name") or code).strip(),
            "match": [str(token) for token in raw_match] if isinstance(raw_match, list) else [],
        })
    return result


def available_locales() -> List[str]:
    """Return every supported locale code, in manifest order."""
    return [entry["code"] for entry in locale_entries()]


def language_name(code: str) -> str:
    """Return the display name for a locale code, else the code itself."""
    for entry in locale_entries():
        if entry["code"] == code:
            return entry["name"]
    return str(code)


def _default_locale() -> str:
    """Return the manifest default locale (or its first entry)."""
    default = _manifest().get("default")
    if isinstance(default, str) and default.strip():
        return default.strip()
    locales = available_locales()
    return locales[0] if locales else ""


def _load_locale(locale: str) -> Dict[str, str]:
    """Load a locale JSON table from the package (filesystem or zip)."""
    if not locale:
        return {}
    if locale in _locale_cache:
        return _locale_cache[locale]

    data = _read_locales_json("{}.json".format(locale))
    _locale_cache[locale] = data
    return data


# --- language resolution ---

def _normalize_token(value: Any) -> str:
    """Lowercase and unify separators for matching."""
    return str(value or "").strip().lower().replace("_", "-")


def _token_matches(token: str, normalized: str) -> bool:
    """True when ``token`` matches ``normalized`` (BCP-47 boundary aware).

    Short tokens (<= 3 chars, e.g. ``en``/``pt``) must sit on a boundary so
    ``"fr"`` never matches the ``"en"`` token; longer tokens are substrings so
    enum reprs like ``Language.BrazilianPortuguese`` still resolve.
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


def _match_entry(value: Any) -> Optional[Dict[str, Any]]:
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


def _normalize_locale(locale_str: Any) -> str:
    """Resolve an arbitrary locale string/enum to a manifest locale code.

    Uses substring matching so enum reprs like ``Locale.PORTUGUESE_BRAZIL`` or
    ``Language.Portuguese`` resolve correctly, not just bare BCP-47 codes.
    Unknown/unavailable languages resolve to the manifest default.
    """
    entry = _match_entry(locale_str)
    if entry is not None:
        return entry["code"]
    return _default_locale()


def _locale_candidates(locale_obj):
    """Yield name/value/str representations of a game Locale enum object."""
    candidates = []
    for attr in ("name", "value"):
        try:
            val = getattr(locale_obj, attr, None)
        except Exception:
            val = None
        if val is not None:
            candidates.append(str(val))
    try:
        candidates.append(str(locale_obj))
    except Exception:
        pass

    # The game maps a Locale to a Language enum (SimSpawner.LOCALE_MAPPING);
    # the Language member name is the cleanest signal.
    try:
        from sims.sim_spawner import SimSpawner  # type: ignore
        language = SimSpawner.LOCALE_MAPPING.get(locale_obj)
        if language is not None:
            name = getattr(language, "name", None)
            candidates.append(str(name) if name is not None else str(language))
    except Exception:
        pass
    return candidates


def _detect_game_locale():
    """
    Detect the game language, returning ``(locale, available)``.

    ``available`` is True when a game locale API actually answered; it is False
    when the game services were not ready (script mods load before them), which
    lets callers retry instead of locking in the default fallback.
    """
    # Method 1: services.get_locale() -> client.account.locale (a Locale enum)
    try:
        import services  # type: ignore
        locale_obj = services.get_locale()
        if locale_obj is not None:
            for candidate in _locale_candidates(locale_obj):
                entry = _match_entry(candidate)
                if entry is not None:
                    return entry["code"], True
            return _normalize_locale(str(locale_obj)), True
    except Exception:
        pass

    try:
        # Method 2: common.locales
        from sims4 import common  # type: ignore
        if hasattr(common, "locales"):
            locale_obj = common.locales.get_current_locale()
            if locale_obj:
                return _normalize_locale(str(locale_obj)), True
    except Exception:
        pass

    try:
        # Method 3: sims4.locale
        from sims4 import locale as sims4_locale  # type: ignore
        if hasattr(sims4_locale, "get_locale"):
            lang = sims4_locale.get_locale()
            if lang:
                return _normalize_locale(str(lang)), True
    except Exception:
        pass

    try:
        # Method 4: localization module
        import localization  # type: ignore
        if hasattr(localization, "get_locale"):
            lang = localization.get_locale()
            if lang:
                return _normalize_locale(str(lang)), True
    except Exception:
        pass

    return _default_locale(), False


def detect_game_language() -> str:
    """
    Detect the current game language, fully defensive (never raises).

    Normalizes values like pt_BR/pt-BR/pt using the manifest, falling back to
    the manifest default.
    """
    return _detect_game_locale()[0]


def init_locale(config_locale: str = "auto") -> str:
    """
    Resolve AND set the active locale at boot (config override, else game language).

    Script mods load before the game services, so ``auto`` detection may not be
    possible yet; ``ensure_locale`` retries later. Returns the effective locale.
    Never raises.
    """
    global _current_locale, _locale_override, _auto_detected

    if config_locale and config_locale != "auto":
        normalized = _normalize_locale(config_locale)
        _locale_override = normalized
        _current_locale = normalized
        _auto_detected = True
        return normalized

    _locale_override = None
    normalized, available = _detect_game_locale()
    _current_locale = normalized
    _auto_detected = bool(available)
    return normalized


def ensure_locale() -> str:
    """
    Retry game-language detection while running in ``auto`` mode.

    At import the services are usually not ready, so ``auto`` falls back to the
    default. This re-detects on the first command (when the game is up) and locks
    the result. An explicit ``sw.lang`` override is never changed. Never raises.
    """
    global _current_locale, _auto_detected

    if _locale_override is not None or _auto_detected:
        return current_locale()
    try:
        normalized, available = _detect_game_locale()
    except Exception:
        return current_locale()
    if available:
        _current_locale = normalized
        _auto_detected = True
    return current_locale()


def resolve_locale(config_locale: str = "auto") -> str:
    """
    Resolve the effective locale: config override -> game detection -> default.
    config_locale: "auto" or any locale code present in the manifest.
    """
    return init_locale(config_locale)


def set_locale(locale: str) -> None:
    """Explicitly set the current locale (used by sw.lang cheat).

    Accepts any locale code present in the manifest; an unknown code resolves
    to the manifest default. No fixed locale list is referenced here.
    """
    global _current_locale, _locale_override, _auto_detected
    normalized = _normalize_locale(locale)
    _current_locale = normalized
    _locale_override = normalized
    _auto_detected = True


def current_locale() -> str:
    """Return the currently active locale (manifest default before init)."""
    return _current_locale or _default_locale()


def t(key: str, **args) -> str:
    """
    Translate a key with optional formatting args.

    Falls back to the manifest default locale when the key is missing in the
    active locale, and returns the key itself when missing in both.
    """
    code = current_locale()
    value = _load_locale(code).get(key)

    default = _default_locale()
    if value is None and code != default:
        value = _load_locale(default).get(key)

    # Ultimate fallback: return the key itself
    if value is None:
        return key

    # Safe formatting
    if args:
        try:
            # A malformed locale value (non-string) would otherwise raise
            # AttributeError from ``str.format`` and break the UI (M8).
            if not isinstance(value, str):
                value = str(value)
            return value.format(**args)
        except (KeyError, ValueError, IndexError, AttributeError):
            # Formatting failed, return raw value
            return value

    return value


def reload_locales() -> None:
    """Clear the table + manifest caches (call after a language file change)."""
    global _locale_cache, _manifest_cache
    _locale_cache = {}
    _manifest_cache = None
