"""
Lot 51 custom service: owns the in-game lifecycle of the state collector.

The stack base (Lot 51 Core) ships a supported service manager and calls the
game's service lifecycle hooks on the game thread. This custom service is the
*primary* in-game lifecycle: it makes sure the collector is running when a zone
loads, and stops it on service shutdown.

The pulse cadence is still driven by ``CoreEvent.GAME_TICK``
(:func:`events.register_lot51_tick`), with the native ``zone.Zone.update``
wrapper as fallback when Lot 51 is missing; the collector's game-clock alarms
remain as a safety net. Every helper is guarded, so the module imports and the
``register`` call no-ops on a plain CPython (offline tests) or without the
library.
"""

from . import integrations
from .debug_log import debug_log, log_exception


_REGISTERED = {"done": False, "service": None}


def _make_service_class(base):
    """Build the service class against the game ``Service`` base.

    Defined lazily so the module imports outside the game (the base is only
    available when ``sims4.service_manager`` is importable).
    """

    class _SensewrightService(base):
        """Sensewright service: drives the collector from the game lifecycle."""

        def on_zone_load(self, *args, **kwargs):
            """Start (or retry) the collector once a zone is loaded."""
            try:
                from . import state_collector

                state_collector.ensure_started()
            except Exception as exc:
                log_exception("stack_service.on_zone_load", exc)

        def stop(self, *args, **kwargs):
            """Stop the collector when the service shuts down."""
            try:
                from . import state_collector

                state_collector.stop()
            except Exception as exc:
                log_exception("stack_service.stop", exc)

    return _SensewrightService


def register() -> bool:
    """Register the Sensewright custom service with Lot 51. Best-effort.

    Idempotent and never raises. Returns True when the service was registered
    (Lot 51 present); False offline or without the library.
    """
    if _REGISTERED["done"]:
        return True

    base = integrations.lot51_service_base()
    if base is None:
        debug_log("stack_service: Lot 51 Service base unavailable")
        return False

    try:
        service_cls = _make_service_class(base)
    except Exception as exc:
        log_exception("stack_service.make_class", exc)
        return False

    try:
        registered = integrations.lot51_register_service(service_cls)
    except Exception as exc:
        log_exception("stack_service.register", exc)
        registered = False

    _REGISTERED["done"] = bool(registered)
    _REGISTERED["service"] = service_cls if registered else None
    if registered:
        debug_log("stack_service: custom service registered")
    return bool(registered)


def registered() -> bool:
    """Whether the custom service is registered (introspection for ``sw.probe``)."""
    return bool(_REGISTERED["done"])
