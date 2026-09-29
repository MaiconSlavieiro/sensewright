"""
Configuration utilities for Sensewright.
Locates install directory, reads runtime.json, handles sensewright.toml for UI language.
All path operations are exception-safe.
"""


import io
import json
import os
from typing import Optional

# Cache for runtime.json
_runtime_cache: Optional[dict] = None
_runtime_path_cache: Optional[str] = None


def _log(where: str, exc=None) -> None:
    """Best-effort diagnostic log for config failures (code review H4).

    Imported lazily because ``debug_log`` imports ``config.mod_root``; a
    module-level import here would create a cycle. Guarded so a logging failure
    can never recurse or raise. Never raises.
    """
    try:
        from .debug_log import debug_log, log_exception
        if exc is None:
            debug_log("config: " + str(where))
        else:
            log_exception(where, exc)
    except Exception:
        pass


def _safe_join(*parts: str) -> str:
    """Safely join path parts, returning empty string on error."""
    try:
        return os.path.join(*parts)
    except Exception:
        return ""


def _safe_dirname(path: str) -> str:
    """Safely get dirname, returning empty string on error."""
    try:
        return os.path.dirname(path)
    except Exception:
        return ""


def _safe_abspath(path: str) -> str:
    """Safely get absolute path, returning empty string on error."""
    try:
        return os.path.abspath(path)
    except Exception:
        return ""


def _safe_exists(path: str) -> bool:
    """Safely check if path exists."""
    try:
        return os.path.exists(path)
    except Exception:
        return False


def _safe_isdir(path: str) -> bool:
    """Safely check if path is a directory."""
    try:
        return os.path.isdir(path)
    except Exception:
        return False


def _find_mod_root() -> str:
    """
    Locate the mod root directory.
    Strategy:
    1. SENSEWRIGHT_HOME env var wins
    2. Derive from __file__ by splitting on .ts4script path segment
    3. Walk parent dirs looking for a 'sidecar' folder
    """
    # 1. Environment variable
    env_home = os.environ.get("SENSEWRIGHT_HOME")
    if env_home and _safe_isdir(env_home):
        return _safe_abspath(env_home)

    # 2. Derive from __file__
    try:
        file_path = _safe_abspath(__file__)
        # Look for .ts4script in the path
        parts = file_path.split(os.sep)
        for i, part in enumerate(parts):
            if part.endswith(".ts4script"):
                # Mod root is the parent of the .ts4script file
                candidate = os.sep.join(parts[:i])
                if _safe_isdir(candidate):
                    return candidate
    except Exception as exc:
        _log("config._find_mod_root.derive", exc)

    # 3. Walk up from __file__ looking for sidecar folder
    try:
        current = _safe_dirname(_safe_abspath(__file__))
        for _ in range(10):  # Limit depth
            if not current:
                break
            sidecar_candidate = _safe_join(current, "sidecar")
            if _safe_isdir(sidecar_candidate):
                return current
            parent = _safe_dirname(current)
            if parent == current:
                break
            current = parent
    except Exception as exc:
        _log("config._find_mod_root.walk", exc)

    # Fallback: return empty string (caller must handle)
    return ""


def mod_root() -> str:
    """Return the mod root directory (where sidecar/ and sensewright_mod/ live)."""
    return _find_mod_root()


def sidecar_dir() -> str:
    """Return the sidecar directory path."""
    root = mod_root()
    if not root:
        return ""
    return _safe_join(root, "sidecar")


def runtime_path() -> str:
    """
    Return the path to runtime.json.
    Primary: <sidecar>/data/runtime.json
    Fallback: <user Documents>/Electronic Arts/The Sims 4/Mods/Sensewright/sidecar/data/runtime.json
    """
    global _runtime_path_cache

    if _runtime_path_cache:
        return _runtime_path_cache

    # Primary candidate
    sidecar = sidecar_dir()
    if sidecar:
        primary = _safe_join(sidecar, "data", "runtime.json")
        if _safe_exists(primary):
            _runtime_path_cache = primary
            return primary

    # Fallback: Documents path
    try:
        # Try to get Documents folder
        docs = os.environ.get("USERPROFILE")
        if docs:
            fallback = _safe_join(
                docs,
                "Documents",
                "Electronic Arts",
                "The Sims 4",
                "Mods",
                "Sensewright",
                "sidecar",
                "data",
                "runtime.json"
            )
            if _safe_exists(fallback):
                _runtime_path_cache = fallback
                return fallback
    except Exception as exc:
        _log("config.runtime_path.fallback", exc)

    # Return primary even if it doesn't exist yet (for writing)
    if sidecar:
        _runtime_path_cache = _safe_join(sidecar, "data", "runtime.json")
        return _runtime_path_cache

    return ""


def sidecar_exe() -> str:
    """Return the path to the sidecar executable."""
    sidecar = sidecar_dir()
    if not sidecar:
        return ""
    return _safe_join(sidecar, "Sensewright-sidecar.exe")


# Written by install-mod.ps1: a single line pointing at the interpreter that has
# the sidecar's dependencies (the dev machine's venv). Lets autoboot find it.
INTERPRETER_HINT_FILENAME = "python.txt"


def read_interpreter_hint() -> str:
    """Read the interpreter path install-mod.ps1 wrote into ``sidecar/python.txt``.

    Returns "" when the file is missing or unreadable. The first non-empty line
    that points at an existing file wins.
    """
    sidecar = sidecar_dir()
    if not sidecar:
        return ""
    hint_path = _safe_join(sidecar, INTERPRETER_HINT_FILENAME)
    if not hint_path or not _safe_exists(hint_path):
        return ""
    try:
        # utf-8-sig strips a UTF-8 BOM (PowerShell's Set-Content -Encoding UTF8
        # writes one); lstrip("\ufeff") is a belt-and-suspenders guard.
        with io.open(hint_path, "r", encoding="utf-8-sig") as handle:
            for line in handle:
                candidate = line.strip().lstrip("\ufeff")
                if candidate and _safe_exists(candidate):
                    return candidate
    except Exception as exc:
        _log("config.read_interpreter_hint", exc)
        return ""
    return ""


def find_python() -> str:
    """
    Best-effort interpreter to run the sidecar from source.

    PyInstaller packaging is a later phase, so until ``Sensewright-sidecar.exe``
    exists the mod can still auto-start the bundled source. Order:
    ``SENSEWRIGHT_PYTHON`` env override → the sidecar's own ``.venv`` →
    ``sidecar/python.txt`` (written by the installer) → a
    ``python``/``python3``/``py`` launcher on PATH. Returns "" if none is found.
    """
    env_python = os.environ.get("SENSEWRIGHT_PYTHON")
    if env_python and _safe_exists(env_python):
        return env_python

    sidecar = sidecar_dir()
    if sidecar:
        for parts in (("Scripts", "python.exe"), ("bin", "python"), ("bin", "python3")):
            candidate = _safe_join(sidecar, ".venv", *parts)
            if candidate and _safe_exists(candidate):
                return candidate

    hint = read_interpreter_hint()
    if hint:
        return hint

    try:
        import shutil
        for name in ("python", "python3", "py"):
            found = shutil.which(name)
            if found:
                return found
    except Exception as exc:
        _log("config.find_python.which", exc)

    return ""


def sidecar_launch():
    """
    Return ``(command_list, cwd)`` to start the sidecar, or ``([], "")``.

    Prefers the packaged ``.exe``; otherwise falls back to running the bundled
    source (``python -m sensewright_sidecar``) with the discovered interpreter.
    """
    exe = sidecar_exe()
    if exe and _safe_exists(exe):
        return [exe], (_safe_dirname(exe) or sidecar_dir())

    python = find_python()
    sidecar = sidecar_dir()
    if python and sidecar and _safe_isdir(sidecar):
        return [python, "-m", "sensewright_sidecar"], sidecar

    return [], ""


def read_runtime() -> Optional[dict]:
    """Read and parse runtime.json, with caching. Re-reads on failure."""
    global _runtime_cache

    path = runtime_path()
    if not path or not _safe_exists(path):
        _runtime_cache = None
        return None

    try:
        with io.open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _runtime_cache = data
        return data
    except (IOError, ValueError, OSError) as exc:
        _log("config.read_runtime", exc)
        _runtime_cache = None
        return None


def get_runtime_value(key: str, default=None):
    """Get a value from runtime.json, reading if needed."""
    data = read_runtime()
    if data is None:
        return default
    return data.get(key, default)


def get_host() -> str:
    """Get the sidecar host from runtime.json or default."""
    return get_runtime_value("host", "127.0.0.1")


def get_port() -> int:
    """Get the sidecar port from runtime.json or default."""
    try:
        return int(get_runtime_value("port", 8765))
    except (TypeError, ValueError):
        return 8765


def get_token() -> str:
    """Get the auth token from runtime.json."""
    return get_runtime_value("token", "")


def get_base_url() -> str:
    """Get the server root URL (http://host:port).

    Endpoint paths already include the `/v1` prefix (see http_client), so this
    must NOT append it or every request would become `/v1/v1/...`.
    """
    host = get_host()
    port = get_port()
    return "http://{}:{}".format(host, port)


def get_auth_header() -> dict:
    """Get the authorization header dict."""
    token = get_token()
    return {"X-Sensewright-Token": token} if token else {}


def read_ui_language() -> str:
    """
    Read the UI language from sensewright.toml next to the mod.
    Returns "auto", "en", or "pt-BR". Defaults to "auto".
    """
    root = mod_root()
    if not root:
        return "auto"

    toml_path = _safe_join(root, "sensewright.toml")
    if not _safe_exists(toml_path):
        return "auto"

    try:
        with io.open(toml_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Simple TOML parsing for [ui] language = "value"
        # We only need this one key, so a lightweight parser is fine
        in_ui_section = False
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("["):
                in_ui_section = line.lower() == "[ui]"
                continue
            if in_ui_section and line.startswith("language"):
                # Parse: language = "value"
                parts = line.split("=", 1)
                if len(parts) == 2:
                    value = parts[1].strip().strip('"\'')
                    if value in ("auto", "en", "pt-BR"):
                        return value
    except Exception as exc:
        _log("config.read_ui_language", exc)

    return "auto"


def read_autonomy_level() -> str:
    """
    Read the persisted autonomy level from sensewright.toml ([agents] autonomy).

    Symmetric reader for :func:`write_autonomy_level` (code review L4). Returns
    "" when unset. Note the sidecar already persists the per-Sim level in its
    SQLite profile; this is the mod-local mirror (like ``read_ui_language``).
    """
    root = mod_root()
    if not root:
        return ""

    toml_path = _safe_join(root, "sensewright.toml")
    if not _safe_exists(toml_path):
        return ""

    try:
        with io.open(toml_path, "r", encoding="utf-8") as f:
            content = f.read()

        in_agents_section = False
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("["):
                in_agents_section = line.lower() == "[agents]"
                continue
            if in_agents_section and line.split("=", 1)[0].strip() == "autonomy":
                parts = line.split("=", 1)
                if len(parts) == 2:
                    return parts[1].strip().strip('"\'')
    except Exception as exc:
        _log("config.read_autonomy_level", exc)

    return ""


def write_ui_language(lang: str) -> bool:
    """
    Write the UI language to sensewright.toml next to the mod.
    Creates the file if it doesn't exist.
    """
    root = mod_root()
    if not root:
        return False

    toml_path = _safe_join(root, "sensewright.toml")

    try:
        # Read existing content
        content = ""
        if _safe_exists(toml_path):
            with io.open(toml_path, "r", encoding="utf-8") as f:
                content = f.read()

        lines = content.splitlines()
        new_lines = []
        in_ui_section = False
        ui_section_found = False
        language_written = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("["):
                if in_ui_section and not language_written:
                    new_lines.append('language = "{}"'.format(lang))
                    language_written = True
                in_ui_section = stripped.lower() == "[ui]"
                if in_ui_section:
                    ui_section_found = True
                new_lines.append(line)
                continue

            if in_ui_section and stripped.startswith("language"):
                new_lines.append('language = "{}"'.format(lang))
                language_written = True
                continue

            new_lines.append(line)

        # If no [ui] section existed, add it
        if not ui_section_found:
            new_lines.append("")
            new_lines.append("[ui]")
            new_lines.append('language = "{}"'.format(lang))
        elif not language_written:
            # [ui] section existed but no language key
            new_lines.append('language = "{}"'.format(lang))

        with io.open(toml_path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        return True
    except Exception as exc:
        _log("config.write_ui_language", exc)
        return False


def write_autonomy_level(level: str) -> bool:
    """
    Persist the autonomy level under ``[agents] autonomy`` in sensewright.toml
    next to the mod (code review L4). Mirrors :func:`write_ui_language`:
    creates the file/section as needed. Best-effort; never raises.
    """
    root = mod_root()
    if not root:
        return False

    toml_path = _safe_join(root, "sensewright.toml")

    try:
        # Read existing content
        content = ""
        if _safe_exists(toml_path):
            with io.open(toml_path, "r", encoding="utf-8") as f:
                content = f.read()

        lines = content.splitlines()
        new_lines = []
        in_agents_section = False
        agents_section_found = False
        autonomy_written = False

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("["):
                if in_agents_section and not autonomy_written:
                    new_lines.append('autonomy = "{}"'.format(level))
                    autonomy_written = True
                in_agents_section = stripped.lower() == "[agents]"
                if in_agents_section:
                    agents_section_found = True
                new_lines.append(line)
                continue

            if in_agents_section and stripped.split("=", 1)[0].strip() == "autonomy":
                new_lines.append('autonomy = "{}"'.format(level))
                autonomy_written = True
                continue

            new_lines.append(line)

        # If no [agents] section existed, add it
        if not agents_section_found:
            new_lines.append("")
            new_lines.append("[agents]")
            new_lines.append('autonomy = "{}"'.format(level))
        elif not autonomy_written:
            # [agents] section existed but no autonomy key
            new_lines.append('autonomy = "{}"'.format(level))

        with io.open(toml_path, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines))

        return True
    except Exception as exc:
        _log("config.write_autonomy_level", exc)
        return False


def clear_runtime_cache() -> None:
    """Clear the runtime.json cache (call after sidecar starts)."""
    global _runtime_cache, _runtime_path_cache
    _runtime_cache = None
    _runtime_path_cache = None