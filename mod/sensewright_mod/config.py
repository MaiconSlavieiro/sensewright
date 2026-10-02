# Sensewright v2 — Configuration
# Python 3.7 compatible

import os
import json

from sensewright_mod.i18n import get_engine


# Default configuration values (locale settings now come from manifest)
DEFAULT_CONFIG = {
    "sidecar": {
        "host": "127.0.0.1",
        "port": 8765,
        "health_timeout": 0.5,
        "request_timeout": 10.0,
    },
    "mod": {
        "agent_seats": 12,
        "player_lock_seconds": 15,
        "autonomy_pulse_interval_sim_minutes": 15,
        "chat_buffer_max_turns": 8,
        "chat_buffer_ttl_seconds": 300,
    },
    "intent_bus": {
        "default_ttl_sim_minutes": 15.0,
        "cognitive_ttl_expires_on": "next_sleep",
        "physical_ttl_expires_on": "ttl",
        "max_retries": 2,
    },
    "debug": {
        "log_level": "INFO",
        "trace_enabled": True,
    }
}

_config = None
_config_path = None


def _get_mod_data_dir():
    """Get the mod_data directory path."""
    try:
        from sims4communitylib.utils.common_log_utils import CommonLogUtils
        return CommonLogUtils.get_mod_data_location_path()
    except Exception:
        docs = os.path.expanduser("~/Documents/Electronic Arts/The Sims 4/Mods/mod_data")
        return docs


def _get_config_path():
    """Get the config file path."""
    global _config_path
    if _config_path is None:
        mod_data_dir = _get_mod_data_dir()
        if mod_data_dir:
            try:
                os.makedirs(mod_data_dir, exist_ok=True)
            except Exception:
                pass
            _config_path = os.path.join(mod_data_dir, "sensewright_config.json")
        else:
            _config_path = os.path.join(os.getcwd(), "sensewright_config.json")
    return _config_path


def load_config():
    """Load configuration from file, merging with defaults."""
    global _config
    if _config is not None:
        return _config

    _config = dict(DEFAULT_CONFIG)
    config_path = _get_config_path()

    try:
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                user_config = json.load(f)
            _deep_merge(_config, user_config)
    except Exception:
        pass

    return _config


def _deep_merge(base, override):
    """Recursively merge override dict into base dict."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def get_config():
    """Get the current configuration (loads if not loaded)."""
    if _config is None:
        return load_config()
    return _config


def get_sidecar_url():
    """Get the sidecar base URL."""
    cfg = get_config()
    host = cfg["sidecar"]["host"]
    port = cfg["sidecar"]["port"]
    return "http://{}:{}".format(host, port)


def get_sidecar_health_url():
    """Get the sidecar health check URL."""
    return "{}/v1/health".format(get_sidecar_url())


def get_sidecar_api_url(endpoint):
    """Get a full sidecar API URL for an endpoint."""
    return "{}/v1{}".format(get_sidecar_url(), endpoint)


def get_agent_seats():
    return get_config()["mod"]["agent_seats"]


def get_player_lock_seconds():
    return get_config()["mod"]["player_lock_seconds"]


def get_autonomy_pulse_interval():
    return get_config()["mod"]["autonomy_pulse_interval_sim_minutes"]


def get_default_lang():
    """Get default language from manifest."""
    engine = get_engine()
    return engine.default_locale()


def get_supported_langs():
    """Get supported languages from manifest."""
    engine = get_engine()
    return [loc.get("code") for loc in engine.locales()]


def get_request_timeout():
    return get_config()["sidecar"]["request_timeout"]


def get_health_timeout():
    return get_config()["sidecar"]["health_timeout"]


def get_intent_default_ttl():
    return get_config()["intent_bus"]["default_ttl_sim_minutes"]


def get_intent_max_retries():
    return get_config()["intent_bus"]["max_retries"]