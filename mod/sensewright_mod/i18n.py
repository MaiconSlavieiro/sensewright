# Sensewright v2 — i18n Engine (Python 3.7 compatible)
# Zero locale literals in code: all language codes, STBL bytes, client tokens
# come from manifest.json. 4-layer cascade: overlay -> exact locale -> base subtag -> default.

import json
import os
import re
import threading
import zipfile
import hashlib

from sensewright_mod.debug_log import log_error, log_exception, log_debug


# Regex for gender inflection macro {g:masc|fem|neutral}
_GENDER_RE = re.compile(r"\{g:([^|{}]+)\|([^|{}]+)(?:\|([^|{}]+))?\}")


_MISSING_PREFIX = "[missing:"


def _safe_format(template, values):
    """Format template using values, leaving unknown keys as empty braces."""
    if not template:
        return template

    class _SafeDict(dict):
        def __missing__(self, key):
            return "{" + str(key) + "}"

    try:
        return template.format_map(_SafeDict(values))
    except (ValueError, KeyError):
        return template


def _resolve_dotted(data, key):
    """Resolve a dotted key in a nested dict, supporting dot-containing keys.

    Uses greedy longest-prefix match at each level so that keys like
    'stbl.pie_menu.root' resolve correctly whether stored as nested dicts
    or as literal keys containing dots.
    """
    current = data
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


def _deterministic_seed(seed, key):
    """Hash a seed + key into a stable non-negative integer."""
    raw = "{}:{}".format(seed, key).encode("utf-8", errors="replace")
    return int(hashlib.md5(raw).hexdigest(), 16)


def fnv1_32(text):
    """FNV-1 32-bit hash (offset basis 0x811C9DC5, prime 0x01000193)."""
    hash_val = 0x811C9DC5
    for byte in text.encode("utf-8"):
        hash_val = (hash_val * 0x01000193) & 0xFFFFFFFF
        hash_val ^= byte
    return hash_val


class I18nEngine:
    """Thread-safe translation engine with overlay + 4-layer cascade."""

    def __init__(self):
        self._lock = threading.RLock()
        self._manifest = {}
        self._file_cache = {}  # (kind, code) -> dict
        self._current_lang = None
        self._overlay_dir = None
        self._bundle_dir = None
        self._zip_path = None
        self._load_paths()
        self.reload()

    def _load_paths(self):
        """Determine bundle dir (inside .ts4script), overlay dir (data/locales), and zip path."""
        mod_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        # Bundle dir: inside the .ts4script zip at locales/
        # We'll read from zip directly, but also support filesystem fallback for dev
        self._bundle_dir = os.path.join(mod_dir, "locales")

        # Overlay dir: data/locales/ relative to TS4 user data dir
        self._overlay_dir = self._get_overlay_dir()

        # Find .ts4script zip
        self._zip_path = self._find_mod_zip()

    def _find_mod_zip(self):
        """Find the Sensewright.ts4script zip file."""
        mod_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for root, dirs, files in os.walk(os.path.dirname(mod_dir)):
            for f in files:
                if f.lower().startswith("sensewright") and f.endswith(".ts4script"):
                    return os.path.join(root, f)
        return None

    def _get_overlay_dir(self):
        """Get the overlay directory path (data/locales/ in user data)."""
        try:
            from sims4communitylib.utils.common_log_utils import CommonLogUtils
            mod_data = CommonLogUtils.get_mod_data_location_path()
            if mod_data:
                overlay = os.path.join(mod_data, "data", "locales")
                try:
                    os.makedirs(overlay, exist_ok=True)
                except Exception:
                    pass
                return overlay
        except Exception:
            pass
        # Best-effort fallback next to mod (dev only)
        mod_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fallback = os.path.join(mod_dir, "data", "locales")
        log_debug("i18n: using fallback overlay dir: {}".format(fallback))
        return fallback

    def get_overlay_dir(self):
        """Public accessor for overlay directory."""
        return self._overlay_dir

    # ── manifest ─────────────────────────────────────────────────────────
    def reload(self):
        """Re-read manifest + overlay, clearing cached files (hot-reload)."""
        with self._lock:
            self._manifest = {}
            self._file_cache.clear()
            self._load_manifest()

    def _load_manifest(self):
        base = {}
        # 1. Load from .ts4script zip (primary)
        if self._zip_path:
            try:
                with zipfile.ZipFile(self._zip_path, "r") as zf:
                    if "locales/manifest.json" in zf.namelist():
                        with zf.open("locales/manifest.json") as f:
                            base = json.load(f)
            except Exception as e:
                log_exception("Failed to load manifest from zip: {}".format(e))

        # 2. Fallback to filesystem (dev)
        if not base:
            manifest_path = os.path.join(self._bundle_dir, "manifest.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        base = json.load(f)
                except Exception as e:
                    log_exception("Failed to load manifest from filesystem: {}".format(e))

        # 3. Merge overlay manifest.override.json if present
        overlay_manifest_path = os.path.join(self._overlay_dir, "manifest.override.json")
        overlay = {}
        if os.path.exists(overlay_manifest_path):
            try:
                with open(overlay_manifest_path, "r", encoding="utf-8") as f:
                    overlay = json.load(f)
            except Exception as e:
                log_exception("Failed to load overlay manifest: {}".format(e))

        # Merge: overlay locales append/override bundle locales by code
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

    def manifest(self):
        return self._manifest

    def locales(self):
        return list(self._manifest.get("locales", []))

    def default_locale(self):
        return self._manifest.get("default_locale", "")

    def locale_by_code(self, code):
        for loc in self.locales():
            if loc.get("code") == code:
                return loc
        return None

    def llm_language_name(self, code):
        loc = self.locale_by_code(code)
        if loc:
            return loc.get("llm_language_name", code)
        return code

    def stbl_byte(self, code):
        loc = self.locale_by_code(code)
        if loc:
            return loc.get("ts4_stbl_byte")
        return None

    def resolve_locale(self, requested):
        """Map an arbitrary language code/client token to a registered locale code.

        Order: exact code -> base_subtag prefix -> client tokens (word boundary)
        -> default locale. Never returns empty string unless no locales exist.
        """
        if not requested:
            return self.default_locale()
        wanted = str(requested).strip().lower()

        # Exact code match
        for loc in self.locales():
            code = loc.get("code", "")
            if code.lower() == wanted:
                return code

        # Base subtag prefix match (e.g., base subtag matches locale code prefix)
        for loc in self.locales():
            base = loc.get("base_subtag", "")
            if base and (wanted == base.lower() or wanted.startswith(base.lower() + "-")):
                return loc.get("code", "")

        # Client token match with word boundary
        for loc in self.locales():
            for token in loc.get("ts4_client_tokens", []):
                if re.search(r"\b" + re.escape(str(token).lower()) + r"\b", wanted):
                    return loc.get("code", "")

        return self.default_locale()

    def detect_client_locale(self, client_language_string):
        """Detect locale from TS4 client language string using ts4_client_tokens."""
        return self.resolve_locale(client_language_string)

    # ── file loading + cascade ───────────────────────────────────────────
    def _load_file(self, kind, code):
        """Load a locale JSON file (kind in ui/content), caching by (kind, code)."""
        key = (kind, code)
        with self._lock:
            if key in self._file_cache:
                return self._file_cache[key]

            data = {}
            candidates = []

            # 1. Overlay (highest priority)
            overlay_path = os.path.join(self._overlay_dir, kind, "{}.json".format(code))
            candidates.append(overlay_path)

            # 2. Bundle from .ts4script zip
            if self._zip_path:
                zip_path = "locales/{}/{}.json".format(kind, code)
                try:
                    with zipfile.ZipFile(self._zip_path, "r") as zf:
                        if zip_path in zf.namelist():
                            with zf.open(zip_path) as f:
                                loaded = json.load(f)
                                if loaded:
                                    data = {**data, **loaded}
                except Exception:
                    pass

            # 3. Bundle from filesystem (dev fallback)
            bundle_path = os.path.join(self._bundle_dir, kind, "{}.json".format(code))
            candidates.append(bundle_path)

            for path in candidates:
                if os.path.exists(path):
                    try:
                        with open(path, "r", encoding="utf-8") as f:
                            loaded = json.load(f)
                            if loaded:
                                data = {**data, **loaded}
                    except Exception:
                        pass

            self._file_cache[key] = data
            return data

    def _cascade_files(self, kind, code):
        """Return candidate dicts (highest priority first) for a key lookup."""
        result = []
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

    def lookup(self, kind, key, code):
        """Resolve a dotted key through the cascade, returning the raw value."""
        for data in self._cascade_files(kind, code):
            value = _resolve_dotted(data, key)
            if value is not None:
                return value
        return None

    # ── public translation API ───────────────────────────────────────────
    def t(self, key, lang=None, gender=None, seed=None, **kwargs):
        """Translate a key with list-rotation + gender inflection + formatting."""
        code = self.resolve_locale(lang)
        raw = self.lookup("ui", key, code)
        if raw is None:
            raw = self.lookup("content", key, code)
        if raw is None:
            return _MISSING_PREFIX + key + "]"

        value = raw
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

    def _apply_gender(self, text, gender):
        def repl(match):
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

    def enum(self, category, value, lang=None, gender=None):
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

    def content(self, lang=None):
        """Return the merged content catalog for a locale code."""
        code = self.resolve_locale(lang)
        merged = {}
        for data in reversed(self._cascade_files("content", code)):
            merged = {**merged, **data}
        return merged

    def ui(self, lang=None):
        """Return the merged UI catalog for a locale code."""
        code = self.resolve_locale(lang)
        merged = {}
        for data in reversed(self._cascade_files("ui", code)):
            merged = {**merged, **data}
        return merged

    # ── helper functions used by other modules ───────────────────────────
    def t_stbl(self, key, lang=None):
        """Translate an STBL key (stbl.* namespace)."""
        return self.t("stbl.{}".format(key), lang)

    def t_pie_menu(self, key, lang=None):
        """Translate a pie menu key (pie_menu.* namespace)."""
        return self.t("pie_menu.{}".format(key), lang)

    def get_manifest(self):
        return self._manifest

    def get_current_language(self):
        if self._current_lang is None:
            self._current_lang = self.default_locale()
        return self._current_lang

    def set_language(self, code):
        if self.locale_by_code(code):
            self._current_lang = code
            return True
        return False

    def load_locales(self):
        """Trigger manifest load and cache warm-up."""
        self.reload()
        # Pre-load default locale files
        default = self.default_locale()
        self._load_file("ui", default)
        self._load_file("content", default)
        return True

    def add_overlay_path(self, path):
        """Add an additional overlay directory (not used in current design)."""
        pass


# Module-level singleton
_engine = None
_engine_lock = threading.Lock()


def get_engine():
    """Return the process-wide I18nEngine singleton."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = I18nEngine()
    return _engine


# ── Public API (backward compatible) ─────────────────────────────────────
def load_locales():
    return get_engine().load_locales()


def get_locale(lang=None):
    engine = get_engine()
    code = engine.resolve_locale(lang)
    return engine.ui(code)


def set_language(lang):
    return get_engine().set_language(lang)


def get_current_language():
    return get_engine().get_current_language()


def t(key, lang=None, **kwargs):
    return get_engine().t(key, lang, **kwargs)


def t_stbl(key, lang=None):
    return get_engine().t_stbl(key, lang)


def t_pie_menu(key, lang=None):
    return get_engine().t_pie_menu(key, lang)


def get_manifest():
    return get_engine().get_manifest()


def get_stbl_keys():
    """Get all STBL keys from the default locale's ui catalog."""
    engine = get_engine()
    default = engine.default_locale()
    data = engine._load_file("ui", default)
    stbl = data.get("stbl", {})
    keys = []

    def extract(d, prefix=""):
        for k, v in d.items():
            new_prefix = "{}.{}".format(prefix, k) if prefix else k
            if isinstance(v, dict):
                extract(v, new_prefix)
            else:
                keys.append(new_prefix)

    extract(stbl)
    return keys


def get_pie_menu_keys():
    """Get all pie_menu keys from the default locale's ui catalog."""
    engine = get_engine()
    default = engine.default_locale()
    data = engine._load_file("ui", default)
    pie = data.get("stbl", {}).get("pie_menu", {})
    return list(pie.keys())


def get_overlay_dir():
    return get_engine().get_overlay_dir()