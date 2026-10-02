"""Two-layer configuration for the Sensewright sidecar.

Layer 1 (`llm.providers.*`) holds credentials and technical rate limits only.
Layer 2 (`llm.routes.*`, `llm.tiers.*`) holds purpose routing and generation
budgets only. Gameplay defaults (`gameplay`, `god`) are editable in-game and
persisted separately as overrides (never written back into config.toml).

The loader prefers `sidecar/config.toml` and falls back to built-in defaults so
the sidecar always boots — even with no file present — and operates in 0-key
fallback mode until the player configures a provider.
"""
from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib  # Python 3.11+
except ImportError:  # pragma: no cover - Python 3.10 fallback
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


CONFIG_FILENAME = "config.toml"

#: Built-in defaults mirror config.example.toml (fully nested). Used when no
#: config file exists, so the sidecar always boots into 0-key fallback mode.
DEFAULT_CONFIG: Dict[str, Any] = {
    "server": {"host": "127.0.0.1", "port": 8765, "log_level": "INFO"},
    "llm": {
        "free_only": True,
        "embeddings": "none",
        "providers": {
            "openrouter": {
                "enabled": False, "base_url": "https://openrouter.ai/api/v1",
                "api_key": "", "models": ["openai/gpt-4o-mini"],
                "rpm": 20, "rpd": 200, "tpm": 40000,
            },
            "opencode": {
                "enabled": False, "base_url": "https://opencode.ai/zen/v1",
                "api_key": "", "models": ["space-bunny-free"],
                "rpm": 20, "rpd": 200, "tpm": 0,
            },
            "gemini": {
                "enabled": False, "base_url": "https://generativelanguage.googleapis.com/v1beta",
                "api_key": "", "models": ["gemini-2.0-flash", "gemini-1.5-flash"],
                "rpm": 15, "rpd": 1500, "tpm": 1000000,
            },
            "groq": {
                "enabled": False, "base_url": "https://api.groq.com/openai/v1",
                "api_key": "", "models": ["llama-3.3-70b-versatile"],
                "rpm": 30, "rpd": 14400, "tpm": 6000,
            },
            "ollama": {
                "enabled": False, "base_url": "http://127.0.0.1:11434",
                "api_key": "", "models": ["llama3.1"],
                "rpm": 0, "rpd": 0, "tpm": 0,
            },
            "deepseek": {
                "enabled": False, "base_url": "https://api.deepseek.com",
                "api_key": "", "models": ["deepseek-chat"],
                "rpm": 60, "rpd": 10000, "tpm": 60000,
            },
        },
        "routes": {"default": {"provider": "openrouter", "model": "openai/gpt-4o-mini"}},
        "tiers": {
            "interactive": {"slo_seconds": 3.0, "max_input_tokens": 1500, "max_output_tokens": 250, "concurrency": 4},
            "realtime": {"slo_seconds": 12.0, "max_input_tokens": 700, "max_output_tokens": 220, "concurrency": 2, "thinking_budget": 0},
            "bg": {"slo_seconds": 60.0, "max_input_tokens": 1500, "max_output_tokens": 400, "concurrency": 1},
            "deep": {"slo_seconds": 300.0, "max_input_tokens": 4000, "max_output_tokens": 600, "concurrency": 1},
        },
    },
    "gameplay": {
        "agent_seats": 12,
        "lease_min_sim_minutes": 60,
        "hearing_radius_m": 20.0,
        "max_lines_per_minute": 12,
        "min_interval_between_lines_seconds": 30,
        "player_lock_seconds": 15,
        "short_term_buffer_turns": 8,
        "silence_consolidate_seconds": 300,
    },
    "god": {
        "director_mode": "AUTONOMOUS",
        "preset": "novela",
        "intervention_frequency": 0.5,
        "intensity": 0.5,
        "mood_influence": 0.5,
        "autonomy_degree": 0.5,
        "chaos_degree": 0.5,
    },
}

#: Provider rate limits that may be absent and default to 0 (unlimited).
_LIMIT_FIELDS = ("rpm", "rpd", "tpm")


def _deep_merge(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge ``overlay`` onto a copy of ``base``."""
    result = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _normalize_provider_limits(providers: Dict[str, Any]) -> Dict[str, Any]:
    for cfg in providers.values():
        if isinstance(cfg, dict):
            for field in _LIMIT_FIELDS:
                cfg.setdefault(field, 0)
    return providers


class Config:
    """Immutable-ish view over the merged configuration."""

    def __init__(self, raw: Dict[str, Any]) -> None:
        self._raw = raw

    # ── Layer 1: providers ──────────────────────────────────────────────
    def providers(self) -> Dict[str, Dict[str, Any]]:
        return self._raw.get("llm", {}).get("providers", {})

    def enabled_providers(self) -> List[str]:
        return [name for name, cfg in self.providers().items() if cfg.get("enabled")]

    def provider(self, name: str) -> Dict[str, Any]:
        return self.providers().get(name, {})

    # ── Layer 2: routes & tiers ─────────────────────────────────────────
    def route_for(self, purpose_id: str) -> Dict[str, Any]:
        routes = self._raw.get("llm", {}).get("routes", {})
        return routes.get(purpose_id, routes.get("default", {}))

    def tier(self, name: str) -> Dict[str, Any]:
        return self._raw.get("llm", {}).get("tiers", {}).get(name, {})

    # ── Flags ───────────────────────────────────────────────────────────
    @property
    def free_only(self) -> bool:
        return bool(self._raw.get("llm", {}).get("free_only", True))

    @property
    def embeddings(self) -> str:
        return self._raw.get("llm", {}).get("embeddings", "none")

    @property
    def server_host(self) -> str:
        return self._raw.get("server", {}).get("host", "127.0.0.1")

    @property
    def server_port(self) -> int:
        return int(self._raw.get("server", {}).get("port", 8765))

    @property
    def log_level(self) -> str:
        return self._raw.get("server", {}).get("log_level", "INFO")

    def gameplay(self, key: str, default: Any = None) -> Any:
        return self._raw.get("gameplay", {}).get(key, default)

    def god(self, key: str, default: Any = None) -> Any:
        return self._raw.get("god", {}).get(key, default)

    def raw(self) -> Dict[str, Any]:
        return self._raw


def load_config(path: Optional[str] = None) -> Config:
    """Load config from ``path`` (or the default location) merged onto defaults.

    ``path`` may point to config.toml. If it is None, we search for the file in
    ``sidecar/config.toml`` relative to the package, then the current directory.
    The parsed TOML is already nested (dotted tables merge automatically).
    """
    candidates: List[str] = []
    if path:
        candidates.append(path)
    else:
        env_path = os.environ.get("SENSEWRIGHT_CONFIG")
        if env_path:
            candidates.append(env_path)
        candidates.append(str(Path(__file__).resolve().parent.parent / CONFIG_FILENAME))
        candidates.append(CONFIG_FILENAME)

    merged = copy.deepcopy(DEFAULT_CONFIG)
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            data: Dict[str, Any] = {}
            if tomllib is not None:
                with open(candidate, "rb") as handle:
                    data = dict(tomllib.load(handle))
            merged = _deep_merge(merged, data)
            break

    merged.setdefault("llm", {}).setdefault("providers", {})
    merged["llm"]["providers"] = _normalize_provider_limits(merged["llm"]["providers"])
    return Config(merged)


_config_singleton: Optional[Config] = None


def get_config() -> Config:
    """Return the process-wide Config, loading lazily on first access."""
    global _config_singleton
    if _config_singleton is None:
        _config_singleton = load_config()
    return _config_singleton


def reset_config() -> None:
    """Reset the cached config (used by tests)."""
    global _config_singleton
    _config_singleton = None
