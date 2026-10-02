"""Data-driven i18n engine for the Sensewright sidecar (REQ-I18N-01..07).

Zero locale literals in code: every language code, STBL byte, display name and
client token is discovered from ``manifest.json``. Prompts and fallbacks live in
``locales/content/<code>.json``; UI strings and STBL keys in
``locales/ui/<code>.json``. A community/user overlay in ``data/locales/`` takes
precedence over the official bundle and supports hot-reload.

Resolution cascade for a key (REQ-I18N-04):
    User overlay -> exact locale -> base subtag -> default locale -> [missing:key]

Values may be a plain string or a list of strings (deterministic rotation via a
seed, REQ-I18N-05) and may contain gender-inflection macros ``{g:m|f|n}``.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

#: Bracket formatter that tolerates missing keys (no KeyError at runtime).
try:
    from string import Formatter as _StringFormatter
except ImportError:  # pragma: no cover
    _StringFormatter = None

_PACKAGE_DIR = Path(__file__).resolve().parent
_SIDECAR_DIR = _PACKAGE_DIR.parent

#: Official bundle: <sidecar>/locales
BUNDLE_DIR = _SIDECAR_DIR / "locales"
#: User/community overlay: <sidecar>/data/locales
OVERLAY_DIR = _SIDECAR_DIR / "data" / "locales"

_MISSING_PREFIX = "[missing:"

#: Gender inflection micro-grammar: {g:masc|fem|neutral}
_GENDER_RE = re.compile(r"\{g:([^|{}]+)\|([^|{}]+)(?:\|([^|{}]+))?\}")


class _SafeFormatter:
    """str.format variant that substitutes empty string for unknown keys."""

    def __init__(self, **defaults: Any) -> None:
        self._defaults = defaults

    def format(self, template: str, **kwargs: Any) -> str:
        merged = dict(self._defaults)
        merged.update(kwargs)
        return _safe_format(template, merged)


def _safe_format(template: str, values: Dict[str, Any]) -> str:
    """Format ``template`` using ``values``, leaving unknown keys as empty."""
    if not template:
        return template

    class _Dict(dict):
        def __missing__(self, key):
            return "{" + str(key) + "}"

    try:
        return template.format_map(_Dict(values))
    except (ValueError, KeyError):
        return template


def _resolve_dotted(data: Dict[str, Any], key: str) -> Optional[Any]:
    """Resolve a dotted key in a nested dict, supporting dot-containing keys.

    Purpose ids (``sim.chat``, ``sim.social.close``) are stored as literal keys
    that themselves contain dots (e.g. ``fallbacks["sim.chat"]``). This uses a
    greedy longest-prefix match at each level so ``fallbacks.sim.chat`` resolves
    to ``data["fallbacks"]["sim.chat"]`` while ``enums.mood.tense`` resolves to
    ``data["enums"]["mood"]["tense"]``.
    """
    current: Any = data
    remaining = key
    while remaining:
        parts = remaining.split(".")
        matched = False
        for length in range(len(parts), 0, -1):
            candidate = ".".join(parts[:length])
            if isinstance(current, dict) and candidate in current:
                current = current[candidate]
                remaining = ".".join(parts[length:])
                matched = True
                break
        if not matched:
            return None
    return current


def _deterministic_seed(seed: Any, key: str) -> int:
    """Hash a seed + key into a stable non-negative integer."""
    raw = "{}:{}".format(seed, key).encode("utf-8", errors="replace")
    return int(hashlib.md5(raw).hexdigest(), 16)


class I18nEngine:
    """Thread-safe translation engine with overlay + 4-layer cascade."""

    def __init__(self, bundle_dir: Optional[Path] = None, overlay_dir: Optional[Path] = None) -> None:
        self._bundle_dir = Path(bundle_dir) if bundle_dir else BUNDLE_DIR
        self._overlay_dir = Path(overlay_dir) if overlay_dir else OVERLAY_DIR
        self._lock = threading.RLock()
        self._manifest: Dict[str, Any] = {}
        self._file_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self.reload()

    # ── manifest ─────────────────────────────────────────────────────────
    def reload(self) -> None:
        """Re-read manifest + overlay, clearing cached files (hot-reload)."""
        with self._lock:
            self._manifest = {}
            self._file_cache.clear()
            self._load_manifest()

    def _load_manifest(self) -> None:
        base: Dict[str, Any] = {}
        bundle_manifest = self._bundle_dir / "manifest.json"
        if bundle_manifest.is_file():
            base = self._read_json(bundle_manifest) or {}

        overlay_manifest = self._overlay_dir / "manifest.override.json"
        overlay: Dict[str, Any] = {}
        if overlay_manifest.is_file():
            overlay = self._read_json(overlay_manifest) or {}

        # Merge: overlay locales append/override bundle locales by code.
        merged = dict(base)
        overlay_locales = overlay.get("locales", [])
        if overlay_locales:
            merged_locales = list(base.get("locales", []))
            index = {l.get("code"): i for i, l in enumerate(merged_locales)}
            for loc in overlay_locales:
                code = loc.get("code")
                if code in index:
                    merged_locales[index[code]] = loc
                else:
                    merged_locales.append(loc)
                    index[code] = len(merged_locales) - 1
            merged["locales"] = merged_locales
        if overlay.get("default_locale"):
            merged["default_locale"] = overlay["default_locale"]
        self._manifest = merged

    @staticmethod
    def _read_json(path: Path) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return None

    def manifest(self) -> Dict[str, Any]:
        return self._manifest

    def locales(self) -> List[Dict[str, Any]]:
        return list(self._manifest.get("locales", []))

    def default_locale(self) -> str:
        return self._manifest.get("default_locale", "")

    def locale_by_code(self, code: str) -> Optional[Dict[str, Any]]:
        for loc in self.locales():
            if loc.get("code") == code:
                return loc
        return None

    def llm_language_name(self, code: str) -> str:
        loc = self.locale_by_code(code)
        if loc:
            return loc.get("llm_language_name", code)
        return code

    def stbl_byte(self, code: str) -> Optional[str]:
        loc = self.locale_by_code(code)
        if loc:
            return loc.get("ts4_stbl_byte")
        return None

    def resolve_locale(self, requested: Optional[str]) -> str:
        """Map an arbitrary language code/client token to a registered locale code.

        Order: exact code -> base_subtag prefix -> client tokens (word boundary)
        -> default locale. Never returns an empty string unless no locales exist.
        """
        if not requested:
            return self.default_locale()
        wanted = str(requested).strip().lower()

        for loc in self.locales():
            code = loc.get("code", "")
            if code.lower() == wanted:
                return code
        for loc in self.locales():
            base = loc.get("base_subtag", "")
            if base and (wanted == base.lower() or wanted.startswith(base.lower() + "-")):
                return loc.get("code", "")
        for loc in self.locales():
            for token in loc.get("ts4_client_tokens", []):
                if re.search(r"\b" + re.escape(str(token).lower()) + r"\b", wanted):
                    return loc.get("code", "")
        return self.default_locale()

    # ── file loading + cascade ───────────────────────────────────────────
    def _load_file(self, kind: str, code: str) -> Dict[str, Any]:
        """Load a locale JSON file (kind in ui/content), caching by (kind, code)."""
        key = (kind, code)
        with self._lock:
            if key in self._file_cache:
                return self._file_cache[key]
            data: Dict[str, Any] = {}
            candidates = [
                self._overlay_dir / kind / "{}.json".format(code),
                self._bundle_dir / kind / "{}.json".format(code),
            ]
            for path in candidates:
                loaded = self._read_json(path)
                if loaded:
                    # Merge overlay over bundle (overlay is listed first).
                    data = {**loaded, **data}
            self._file_cache[key] = data
            return data

    def _cascade_files(self, kind: str, code: str) -> List[Dict[str, Any]]:
        """Return candidate dicts (highest priority first) for a key lookup."""
        result: List[Dict[str, Any]] = []
        exact = self._load_file(kind, code)
        if exact:
            result.append(exact)
        loc = self.locale_by_code(code)
        base = loc.get("base_subtag") if loc else None
        if base and base != code:
            base_data = self._load_file(kind, base)
            if base_data:
                result.append(base_data)
        default = self.default_locale()
        if default and default != code and default != base:
            default_data = self._load_file(kind, default)
            if default_data:
                result.append(default_data)
        return result

    def lookup(self, kind: str, key: str, code: str) -> Optional[Any]:
        """Resolve a dotted key through the cascade, returning the raw value."""
        for data in self._cascade_files(kind, code):
            value = _resolve_dotted(data, key)
            if value is not None:
                return value
        return None

    # ── public translation API ───────────────────────────────────────────
    def t(
        self,
        key: str,
        lang: Optional[str] = None,
        gender: Optional[str] = None,
        seed: Any = None,
        **kwargs: Any,
    ) -> str:
        """Translate a key with list-rotation + gender inflection + formatting."""
        code = self.resolve_locale(lang)
        raw = self.lookup("ui", key, code)
        if raw is None:
            raw = self.lookup("content", key, code)
        if raw is None:
            return _MISSING_PREFIX + key + "]"

        value: Any = raw
        if isinstance(value, list):
            if not value:
                return ""
            effective_seed = seed
            if effective_seed is None:
                sim_id = kwargs.get("sim_id")
                tick = kwargs.get("world_sim_tick")
                if sim_id is not None and tick is not None:
                    effective_seed = "{}:{}".format(sim_id, int(tick) // 60 if isinstance(tick, (int, float)) else tick)
            if effective_seed is None:
                effective_seed = 0
            index = _deterministic_seed(effective_seed, key) % len(value)
            value = value[index]

        if not isinstance(value, str):
            return str(value)

        text = self._apply_gender(value, gender)
        if kwargs:
            text = _safe_format(text, kwargs)
        return text

    def _apply_gender(self, text: str, gender: Optional[str]) -> str:
        def repl(match: "re.Match") -> str:
            masculine = match.group(1)
            feminine = match.group(2)
            neutral = match.group(3)
            g = (gender or "").upper()
            if g == "F":
                return feminine
            if g == "N" and neutral is not None:
                return neutral
            return neutral if (neutral is not None and g == "N") else masculine

        return _GENDER_RE.sub(repl, text)

    def enum(self, category: str, value: Optional[str], lang: Optional[str] = None, gender: Optional[str] = None) -> str:
        """Translate an enum-like value (mood/activity/trait/age) via enums.<category>."""
        if value is None:
            return ""
        code = self.resolve_locale(lang)
        translated = self.lookup("content", "enums.{}.{}".format(category, value), code)
        if translated is None:
            return value
        if isinstance(translated, list):
            translated = translated[0] if translated else value
        if isinstance(translated, str) and "{g:" in translated:
            translated = self._apply_gender(translated, gender)
        return str(translated)

    def enum_keys(self, category: str, lang: Optional[str] = None) -> List[str]:
        """Return the canonical keys of an enum category (e.g. ``mood``)."""
        enums = self.content(lang).get("enums", {})
        values = enums.get(category, {})
        if not isinstance(values, dict):
            return []
        return sorted(str(key) for key in values.keys())

    def content(self, lang: Optional[str] = None) -> Dict[str, Any]:
        """Return the merged content catalog for a locale code."""
        code = self.resolve_locale(lang)
        merged: Dict[str, Any] = {}
        for data in reversed(self._cascade_files("content", code)):
            merged = {**merged, **data}
        return merged

    def ui(self, lang: Optional[str] = None) -> Dict[str, Any]:
        """Return the merged UI catalog for a locale code."""
        code = self.resolve_locale(lang)
        merged: Dict[str, Any] = {}
        for data in reversed(self._cascade_files("ui", code)):
            merged = {**merged, **data}
        return merged

    def render_prompt(self, purpose_id: str, section: str, lang: Optional[str], ctx: Dict[str, Any]) -> str:
        """Render a data-driven prompt template for a purpose + section.

        ``section`` is a key under ``content.<code>.prompts.<purpose_id>`` (e.g.
        ``system``, ``user_phone_sms``). Anchor placeholders are expanded first,
        then the template is formatted with ``ctx`` + anchor values.
        """
        code = self.resolve_locale(lang)
        content = self.content(code)
        anchors = content.get("anchors", {}) or {}

        strict = _safe_format(str(anchors.get("strict_language", "")), {
            "llm_language_name": self.llm_language_name(code),
        })
        json_only = str(anchors.get("json_only", ""))
        one_shot_block = str((anchors.get("one_shot", {}) or {}).get(purpose_id, ""))

        prompts = content.get("prompts", {}) or {}
        purpose_prompts = prompts.get(purpose_id, {}) or {}
        if not isinstance(purpose_prompts, dict):
            purpose_prompts = {}
        template = purpose_prompts.get(section, "")
        if not template:
            default_prompts = prompts.get("_default", {}) or {}
            if isinstance(default_prompts, dict):
                template = default_prompts.get(section, "")

        base_vars = {
            "strict_language_anchor": strict,
            "strict_language": strict,
            "json_only": json_only,
            "one_shot_block": one_shot_block,
            "llm_language_name": self.llm_language_name(code),
        }
        merged = dict(base_vars)
        merged.update(ctx)
        return _safe_format(template, merged)


_engine_singleton: Optional[I18nEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> I18nEngine:
    """Return the process-wide I18nEngine singleton."""
    global _engine_singleton
    if _engine_singleton is None:
        with _engine_lock:
            if _engine_singleton is None:
                _engine_singleton = I18nEngine()
    return _engine_singleton


def reset_engine() -> None:
    """Reset the singleton (used by tests)."""
    global _engine_singleton
    _engine_singleton = None
