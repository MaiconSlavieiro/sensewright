# Sensewright v2 — Debug Logging with Rotation
# Python 3.7 compatible

import os
import logging
import logging.handlers
import sims4.log

from sensewright_mod.config import get_config

# Mod logger using sims4.log (writes to TS4's Logs folder)
_logger = sims4.log.Logger('Sensewright', default_owner='sensewright')

# Worker thread logger (plain Python logging with rotation)
_worker_logger = None
_worker_log_path = None


def get_mod_logger():
    """Return the main thread sims4.log logger."""
    return _logger


def _get_logs_dir():
    """Get the mod_logs directory path (S4CL convention)."""
    try:
        from sims4communitylib.utils.common_log_utils import CommonLogUtils
        return CommonLogUtils.get_mod_logs_location_path()
    except Exception:
        # Fallback to Documents/Electronic Arts/The Sims 4/mod_logs
        docs = os.path.expanduser('~/Documents/Electronic Arts/The Sims 4')
        return os.path.join(docs, 'mod_logs')


def init_worker_logger():
    """Initialize the rotating file logger for the worker thread."""
    global _worker_logger, _worker_log_path

    if _worker_logger is not None:
        return _worker_logger

    log_dir = _get_logs_dir()
    if not log_dir:
        # Last resort: current working directory
        log_dir = os.getcwd()

    try:
        os.makedirs(log_dir, exist_ok=True)
    except Exception:
        pass

    _worker_log_path = os.path.join(log_dir, 'Sensewright_Worker.log')

    _worker_logger = logging.getLogger('Sensewright.Worker')
    _worker_logger.setLevel(logging.DEBUG)
    _worker_logger.propagate = False

    # Clear any existing handlers
    for h in list(_worker_logger.handlers):
        _worker_logger.removeHandler(h)

    # RotatingFileHandler: 10MB max, 3 backups
    handler = logging.handlers.RotatingFileHandler(
        _worker_log_path,
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8'
    )
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)
    _worker_logger.addHandler(handler)

    return _worker_logger


def get_worker_logger():
    """Return the worker thread logger, initializing if needed."""
    if _worker_logger is None:
        return init_worker_logger()
    return _worker_logger


def log_info(msg, *args, **kwargs):
    """Log info on main thread."""
    try:
        _logger.info(msg, *args, **kwargs)
    except Exception:
        pass


def log_warn(msg, *args, **kwargs):
    """Log warning on main thread."""
    try:
        _logger.warn(msg, *args, **kwargs)
    except Exception:
        pass


def log_error(msg, *args, **kwargs):
    """Log error on main thread."""
    try:
        _logger.error(msg, *args, **kwargs)
    except Exception:
        pass


def log_exception(msg, *args, **kwargs):
    """Log exception with traceback on main thread."""
    try:
        _logger.exception(msg, *args, **kwargs)
    except Exception:
        pass


def worker_log_info(msg, *args, **kwargs):
    """Log info on worker thread."""
    try:
        get_worker_logger().info(msg, *args, **kwargs)
    except Exception:
        pass


def worker_log_warn(msg, *args, **kwargs):
    """Log warning on worker thread."""
    try:
        get_worker_logger().warning(msg, *args, **kwargs)
    except Exception:
        pass


def worker_log_error(msg, *args, **kwargs):
    """Log error on worker thread."""
    try:
        get_worker_logger().error(msg, *args, **kwargs)
    except Exception:
        pass


def worker_log_exception(msg, *args, **kwargs):
    """Log exception with traceback on worker thread."""
    try:
        get_worker_logger().exception(msg, *args, **kwargs)
    except Exception:
        pass


def safe_call(logger_func, msg, *args, **kwargs):
    """Safely call a logger function, never raising."""
    try:
        logger_func(msg, *args, **kwargs)
    except Exception:
        pass