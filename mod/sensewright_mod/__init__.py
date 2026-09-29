"""
Sensewright - AI-driven autonomy for The Sims 4.
Package entry point. Registers commands and starts autoboot.
"""


__version__ = "0.1.0"

# Resolve the active locale before commands/LLM calls run
# (config [ui].language override -> game language -> en).
try:
    from . import i18n
    from .config import read_ui_language
    i18n.init_locale(read_ui_language())
except Exception:
    pass

# Import main to register commands (guarded)
try:
    from . import main  # noqa: F401
    # Trigger autoboot after commands are registered
    main.autoboot()
except Exception:
    # Silent fail - mod stays functional in native mode
    pass

# Start the event-driven state collector (guarded, best-effort).
# Services are often not up yet at import, so start() retries from the command
# paths via ensure_started(), AND from a Zone.update hook installed below so it
# comes up automatically at zone load without any cheat command.
try:
    from . import state_collector
    state_collector.start()
    state_collector.install_zone_hook()
except Exception:
    # No game/alarms available or collector unavailable - keep running
    pass

# Expose key functions for external access
from .i18n import t, set_locale, current_locale, detect_game_language  # noqa: F401
from .config import mod_root, sidecar_dir, runtime_path, read_ui_language, write_ui_language  # noqa: F401
from .http_client import chat, hey, status, health, reset, set_autonomy, set_lang, send_event, send_events  # noqa: F401
from .sim_context import collect  # noqa: F401
from .tool_executor import execute, execute_batch  # noqa: F401