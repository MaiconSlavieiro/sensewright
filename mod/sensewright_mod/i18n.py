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
import sys
from typing import Any, Dict, List, Optional

# Cache for loaded locale tables
_locale_cache: Dict[str, Dict[str, str]] = {}
_manifest_cache: Optional[Dict[str, Any]] = None
_current_locale: str = ""
_locale_override: Optional[str] = None  # explicit override from config
# True once the locale is settled (explicit override, or a game API answered).
_auto_detected: bool = False
# Human-readable trail of the last detection attempt (see ``detection_report``).
_last_detection: str = ""

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


def _safe_str(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return "<unprintable>"


def _match_value(value: Any, source: str, attempts: List[str]) -> Optional[str]:
    """Match a game locale value against the manifest, recording the attempt.

    Returns the matched locale code, or None when the value is missing or does
    not match any manifest entry. Unknown values are deliberately NOT coerced to
    the default here: a non-match means "keep retrying", never "lock English".
    """
    if value is None:
        attempts.append("{}:none".format(source))
        return None
    for candidate in _locale_candidates(value):
        entry = _match_entry(candidate)
        if entry is not None:
            attempts.append("{}:{}->{}".format(source, candidate, entry["code"]))
            return entry["code"]
    attempts.append("{}:{}->nomatch".format(source, _safe_str(value)))
    return None


def _detect_game_locale():
    """
    Detect the game language, returning ``(locale, available, report)``.

    ``available`` is True only when a source returned a value that *matched* a
    manifest locale. A source that answered but did not match (e.g. the English
    default before the account loads) does NOT lock a language: the caller keeps
    retrying until a real match appears. This is what keeps the running game's
    language (pt_BR) from being silently replaced by the ``en`` fallback.
    """
    attempts: List[str] = []

    # 1. services.get_locale() (the account locale once the client is up).
    try:
        import services  # type: ignore
        getter = getattr(services, "get_locale", None)
        if callable(getter):
            code = _match_value(getter(), "services.get_locale", attempts)
            if code:
                return code, True, "; ".join(attempts)
        else:
            attempts.append("services.get_locale:absent")
    except Exception as exc:
        attempts.append("services.get_locale:err={}".format(_safe_str(exc)))

    # 2. client.account.locale (the authoritative running-game locale).
    try:
        import services  # type: ignore
        manager = services.client_manager()
        client = manager.get_first_client() if manager is not None else None
        account = getattr(client, "account", None) if client is not None else None
        if account is not None:
            for attr in ("locale", "language", "game_locale"):
                code = _match_value(
                    getattr(account, attr, None), "account.{}".format(attr), attempts
                )
                if code:
                    return code, True, "; ".join(attempts)
        else:
            attempts.append("account:absent")
    except Exception as exc:
        attempts.append("account:err={}".format(_safe_str(exc)))

    # 3. common.locales.get_current_locale()
    try:
        from sims4 import common  # type: ignore
        locales = getattr(common, "locales", None)
        if locales is not None:
            code = _match_value(
                locales.get_current_locale(), "common.locales", attempts
            )
            if code:
                return code, True, "; ".join(attempts)
        else:
            attempts.append("common.locales:absent")
    except Exception as exc:
        attempts.append("common.locales:err={}".format(_safe_str(exc)))

    # 4. sims4.locale.get_locale()
    try:
        from sims4 import locale as sims4_locale  # type: ignore
        getter = getattr(sims4_locale, "get_locale", None)
        if callable(getter):
            code = _match_value(getter(), "sims4.locale", attempts)
            if code:
                return code, True, "; ".join(attempts)
        else:
            attempts.append("sims4.locale:absent")
    except Exception as exc:
        attempts.append("sims4.locale:err={}".format(_safe_str(exc)))

    # 5. localization.get_locale()
    try:
        import localization  # type: ignore
        getter = getattr(localization, "get_locale", None)
        if callable(getter):
            code = _match_value(getter(), "localization", attempts)
            if code:
                return code, True, "; ".join(attempts)
        else:
            attempts.append("localization:absent")
    except Exception as exc:
        attempts.append("localization:err={}".format(_safe_str(exc)))

    # 6. Windows registry install locale (last resort; still manifest-matched, so
    #    it stays inside the data-driven locale framework - no hardcoded code).
    #    Only consulted when the Sims engine is actually loaded (``sims4`` import),
    #    so offline tests and tools are not affected by the host registry.
    if "sims4" in sys.modules:
        try:
            import winreg  # type: ignore
            for path in (
                r"SOFTWARE\Maxis\The Sims 4",
                r"SOFTWARE\WOW6432Node\Maxis\The Sims 4",
            ):
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                        value, _ = winreg.QueryValueEx(key, "Locale")
                except OSError:
                    attempts.append("registry:{}:absent".format(path))
                    continue
                code = _match_value(value, "registry:{}".format(path), attempts)
                if code:
                    return code, True, "; ".join(attempts)
        except Exception as exc:
            attempts.append("registry:err={}".format(_safe_str(exc)))

    return _default_locale(), False, "; ".join(attempts)


def detection_report() -> str:
    """Last detection attempt trail (for the ``[validate] locale:`` log line)."""
    return _last_detection


def detect_game_language() -> str:
    """
    Detect the current game language, fully defensive (never raises).

    Normalizes values like pt_BR/pt-BR/pt using the manifest, falling back to
    the manifest default.
    """
    global _last_detection
    normalized, _available, report = _detect_game_locale()
    _last_detection = report
    return normalized


def init_locale(config_locale: str = "auto") -> str:
    """
    Resolve AND set the active locale at boot (config override, else game language).

    An explicit ``[ui] language`` override wins immediately. In ``auto`` mode the
    game language is NOT probed at import: the game services are not ready yet and
    a pre-account source can return the English default, which would lock the
    wrong language. ``ensure_locale`` detects the real running language once the
    game is up. Returns the effective (possibly provisional) locale. Never raises.
    """
    global _current_locale, _locale_override, _auto_detected, _last_detection

    if config_locale and config_locale != "auto":
        normalized = _normalize_locale(config_locale)
        _locale_override = normalized
        _current_locale = normalized
        _auto_detected = True
        return normalized

    _locale_override = None
    _current_locale = _default_locale()
    _auto_detected = False
    _last_detection = "init:deferred"
    return _current_locale


def ensure_locale() -> str:
    """
    Retry game-language detection while running in ``auto`` mode.

    Detection only locks a locale once a source returns a value that *matches* a
    manifest locale (never on a non-matching fallback). An explicit ``sw.lang``
    override is never changed. Never raises.
    """
    global _current_locale, _auto_detected, _last_detection

    if _locale_override is not None or _auto_detected:
        return current_locale()
    try:
        normalized, available, report = _detect_game_locale()
    except Exception:
        return current_locale()
    _last_detection = report
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
