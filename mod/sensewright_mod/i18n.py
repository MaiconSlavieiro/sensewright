"""
Localization (i18n) system for Sensewright.
Loads locale JSON files, resolves language, provides t(key, **args) with EN fallback.
"""


import io
import json
import os
from typing import Dict, Optional

# Cache for loaded locale tables
_locale_cache: Dict[str, Dict[str, str]] = {}
_current_locale: str = "en"
_locale_override: Optional[str] = None  # explicit override from config
# True once the locale is settled (explicit override, or a game API answered).
_auto_detected: bool = False


def _get_package_dir() -> str:
    """Return the directory containing this module (sensewright_mod)."""
    return os.path.dirname(os.path.abspath(__file__))


def _load_locale_from_zip(locale: str) -> Dict[str, str]:
    """Read a locale JSON from inside the ``.ts4script`` (zipimport case).

    When the game loads the mod straight from the archive, ``__file__`` points
    inside the zip and a normal ``open`` fails. This reads the entry directly.
    """
    try:
        import zipfile

        module_path = os.path.abspath(__file__)
        marker = ".ts4script"
        index = module_path.lower().find(marker)
        if index == -1:
            return {}
        archive_path = module_path[: index + len(marker)]
        entry = "sensewright_mod/locales/{}.json".format(locale)
        with zipfile.ZipFile(archive_path) as archive:
            with archive.open(entry) as handle:
                return json.loads(handle.read().decode("utf-8"))
    except Exception:
        return {}


def _load_locale(locale: str) -> Dict[str, str]:
    """Load a locale JSON file from the package (filesystem or .ts4script zip)."""
    if locale in _locale_cache:
        return _locale_cache[locale]

    package_dir = _get_package_dir()
    locale_path = os.path.join(package_dir, "locales", "{}.json".format(locale))

    data: Dict[str, str] = {}
    try:
        with io.open(locale_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (IOError, ValueError, OSError):
        data = _load_locale_from_zip(locale)

    _locale_cache[locale] = data
    return data


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
    lets callers retry instead of locking in the ``en`` fallback.
    """
    # Method 1: services.get_locale() -> client.account.locale (a Locale enum)
    try:
        import services  # type: ignore
        locale_obj = services.get_locale()
        if locale_obj is not None:
            for candidate in _locale_candidates(locale_obj):
                normalized = _normalize_locale(candidate)
                if normalized == "pt-BR":
                    return normalized, True
                low = candidate.lower()
                if "english" in low or low == "en" or low.startswith("en-"):
                    return "en", True
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

    return "en", False


def detect_game_language() -> str:
    """
    Detect the current game language, fully defensive (never raises).
    Tries several game APIs, normalizes values like pt_BR/pt-BR/pt -> pt-BR.
    Falls back to "en".
    """
    return _detect_game_locale()[0]


def _normalize_locale(locale_str: str) -> str:
    """
    Normalize locale strings/enums to our supported locales (en, pt-BR).

    Uses substring matching so enum reprs like ``Locale.PORTUGUESE_BRAZIL`` or
    ``Language.PORTUGUESE`` resolve correctly, not just bare ``pt-BR`` codes.
    """
    if not locale_str:
        return "en"

    lower = str(locale_str).lower().replace("_", "-")

    if "portug" in lower or "brazil" in lower or lower == "pt" or lower.startswith("pt-"):
        return "pt-BR"
    if "english" in lower or lower == "en" or lower.startswith("en-"):
        return "en"

    return "en"


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

    At import the services are usually not ready, so ``auto`` falls back to
    ``en``. This re-detects on the first command (when the game is up) and locks
    the result. An explicit ``sw.lang`` override is never changed. Never raises.
    """
    global _current_locale, _auto_detected

    if _locale_override is not None or _auto_detected:
        return _current_locale
    try:
        normalized, available = _detect_game_locale()
    except Exception:
        return _current_locale
    if available:
        _current_locale = normalized
        _auto_detected = True
    return _current_locale


def resolve_locale(config_locale: str = "auto") -> str:
    """
    Resolve the effective locale based on config override -> game detection -> EN fallback.
    config_locale: "auto", "en", or "pt-BR"
    """
    return init_locale(config_locale)


def set_locale(locale: str) -> None:
    """Explicitly set the current locale (used by sw.lang cheat)."""
    global _current_locale, _locale_override, _auto_detected
    normalized = _normalize_locale(locale)
    if normalized not in ("en", "pt-BR"):
        normalized = "en"
    _current_locale = normalized
    _locale_override = normalized
    _auto_detected = True


def current_locale() -> str:
    """Return the currently active locale."""
    return _current_locale


def t(key: str, **args) -> str:
    """
    Translate a key with optional formatting args.
    Falls back to EN if key missing in current locale, returns key itself if missing in both.
    """
    global _current_locale

    # Try current locale
    locale_data = _load_locale(_current_locale)
    value = locale_data.get(key)

    # Fallback to EN
    if value is None and _current_locale != "en":
        en_data = _load_locale("en")
        value = en_data.get(key)

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
    """Clear cache and reload locales (call after language change)."""
    global _locale_cache
    _locale_cache.clear()