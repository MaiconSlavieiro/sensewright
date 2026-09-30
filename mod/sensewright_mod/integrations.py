"""
Sensewright third-party modding-stack integration layer.

This is the single place where Sensewright touches the two community libraries it
is built on:

* **Lot 51 Core Library** (``lot51_core``) - the event bus (zone load/unload, game
  tick, save, build/buy, object added/destroyed), the custom service manager and
  the logger/config helpers. It replaces the fragile native alarm owner +
  ``zone.Zone.update`` heartbeat.
* **Sims 4 Community Library** (``sims4communitylib``, S4CL) - notifications,
  native dialogs (ok/cancel, option/choose dialogs), interaction base classes and
  the vanilla tuning-id enums/utilities used by the collectors.

Every lookup is lazy and guarded: the module imports fine (and every helper is a
no-op returning ``None``/``False``) when the libraries - or the game - are not
present. That keeps the offline test suite running on a plain CPython 3.10 and
keeps the game safe if a library is missing or a patch changes an import path.

Nothing here raises. Call :func:`stack_summary` to see what resolved.
"""

import importlib
from typing import Any, Callable, Dict, List, Optional, Tuple


# --- library detection -------------------------------------------------------

lot51_core = None  # module or None
sims4communitylib = None  # module or None

_resolved: Dict[str, Any] = {}


def _load(module_name: str) -> Optional[Any]:
    """Import ``module_name`` once, tolerating every import failure."""
    try:
        return importlib.import_module(module_name)
    except Exception:
        return None


def _first(*module_names: str) -> Optional[Any]:
    """Return the first importable module from ``module_names`` (cached)."""
    for name in module_names:
        if name in _resolved:
            if _resolved[name] is not None:
                return _resolved[name]
            continue
        module = _load(name)
        _resolved[name] = module
        if module is not None:
            return module
    return None


def _attr(module: Any, *names: str) -> Optional[Any]:
    """Return the first attribute on ``module`` that exists and is non-None."""
    if module is None:
        return None
    for name in names:
        value = getattr(module, name, None)
        if value is not None:
            return value
    return None


def refresh() -> Dict[str, bool]:
    """(Re)resolve the libraries. Safe to call any time."""
    global lot51_core, sims4communitylib
    lot51_core = _load("lot51_core")
    sims4communitylib = _load("sims4communitylib")
    return {"lot51": lot51_core is not None, "s4cl": sims4communitylib is not None}


def has_lot51() -> bool:
    return lot51_core is not None


def has_s4cl() -> bool:
    return sims4communitylib is not None


def stack_summary() -> str:
    """Short human string for ``sw.probe`` / the debug log."""
    return "stack: lot51={} s4cl={}".format(
        "yes" if has_lot51() else "no", "yes" if has_s4cl() else "no")


# --- Lot 51 Core: event bus --------------------------------------------------

def lot51_events() -> Tuple[Optional[Any], Optional[Any]]:
    """Return ``(event_handler, CoreEvent)`` from Lot 51, or ``(None, None)``."""
    module = _first(
        "lot51_core.services.events",
        "lot51_core.services.event_service",
    )
    return _attr(module, "event_handler"), _attr(module, "CoreEvent")


def lot51_event_service() -> Optional[Any]:
    """The singleton event service (for broadcasting custom events)."""
    module = _first("lot51_core.services.events", "lot51_core.services.event_service")
    return _attr(module, "event_service")


def lot51_event_name(core_event: Any, *names: str) -> Optional[Any]:
    """Return the first ``CoreEvent`` member that exists (patch tolerant)."""
    return _attr(core_event, *names)


def lot51_register(event_name: Any, callback: Callable) -> bool:
    """Register ``callback`` on a Lot 51 ``CoreEvent``. True on success.

    ``event_name`` is a ``CoreEvent`` member (from :func:`lot51_event_name`).
    The decorator form is what Lot 51 documents, so this calls it directly.
    """
    handler, _ = lot51_events()
    if handler is None or event_name is None:
        return False
    try:
        handler(event_name)(callback)
        return True
    except Exception:
        return False


def lot51_register_custom(name: str, callback: Callable) -> bool:
    """Register ``callback`` on a custom (namespaced) Lot 51 event name."""
    handler, _ = lot51_events()
    if handler is None:
        return False
    try:
        handler(name)(callback)
        return True
    except Exception:
        return False


# --- Lot 51 Core: services ---------------------------------------------------

def lot51_service_base() -> Optional[Any]:
    """Return the game ``Service`` base class used for custom services."""
    module = _first("sims4.service_manager")
    return _attr(module, "Service")


def lot51_service_manager() -> Optional[Any]:
    """Return ``service_manager`` (register custom services)."""
    module = _first("lot51_core.services.service_manager")
    return _attr(module, "service_manager")


def lot51_register_service(service_cls: Any) -> bool:
    manager = lot51_service_manager()
    if manager is None or service_cls is None:
        return False
    register = _attr(manager, "register_service")
    if register is None:
        return False
    try:
        register(service_cls)
        return True
    except Exception:
        return False


# --- Lot 51 Core: logger / config -------------------------------------------

def lot51_logger(name: str, mod_root: Any = None, log_name: str = None,
                 version: str = None) -> Optional[Any]:
    """Create a Lot 51 ``Logger`` (best-effort). ``mod_root`` may be a path."""
    module = _first("lot51_core.utils.log", "lot51_core")
    logger_cls = _attr(module, "Logger")
    if logger_cls is None:
        return None
    try:
        kwargs: Dict[str, Any] = {}
        if mod_root is not None:
            kwargs["mod_root"] = mod_root
        if log_name is not None:
            kwargs["log_name"] = log_name
        if version is not None:
            kwargs["version"] = version
        return logger_cls(name, **kwargs)
    except Exception:
        return None


def lot51_config(mod_root: Any, name: str, logger: Any = None,
                 default_data: Dict[str, Any] = None) -> Optional[Any]:
    """Create a Lot 51 JSON ``Config`` (best-effort)."""
    module = _first("lot51_core.utils.config", "lot51_core")
    config_cls = _attr(module, "Config")
    if config_cls is None:
        return None
    try:
        return config_cls(mod_root, name, logger, default_data=default_data or {})
    except Exception:
        return None


# --- S4CL: notifications -----------------------------------------------------

def s4cl_notification(title: str, text: str) -> Optional[Any]:
    """Return a built S4CL ``CommonBasicNotification`` (or ``None``).

    The object is shown by the caller via :func:`s4cl_show_notification` so the
    two steps fail independently.
    """
    module = _first(
        "sims4communitylib.notifications.common_basic_notification",
        "sims4communitylib.notifications.basic_notification",
        "sims4communitylib.notifications",
    )
    notification_cls = _attr(module, "CommonBasicNotification", "BasicNotification")
    if notification_cls is None:
        return None
    try:
        return notification_cls(title, text)
    except Exception:
        return None


def s4cl_show_notification(notification: Any, sim_info: Any = None) -> bool:
    """Show a built S4CL notification to ``sim_info`` (or the active client)."""
    if notification is None:
        return False
    for method_name in ("show", "show_dialog"):
        method = getattr(notification, method_name, None)
        if not callable(method):
            continue
        for args in ((sim_info,), (), (None,)):
            try:
                method(*args)
                return True
            except Exception:
                continue
    return False


# --- S4CL: dialogs -----------------------------------------------------------

def s4cl_ok_cancel(title: str, text: str) -> Optional[Any]:
    """Build an S4CL ok/cancel dialog (or ``None``)."""
    module = _first(
        "sims4communitylib.dialogs.ok_cancel_dialog",
        "sims4communitylib.dialogs",
    )
    dialog_cls = _attr(module, "CommonOkCancelDialog")
    if dialog_cls is None:
        return None
    try:
        return dialog_cls(title, text)
    except Exception:
        return None


def s4cl_show_ok_cancel(dialog: Any, sim_info: Any = None,
                        on_confirm: Callable = None,
                        on_cancel: Callable = None) -> bool:
    """Show a built S4CL ok/cancel dialog. Best-effort, never raises."""
    if dialog is None:
        return False
    show = getattr(dialog, "show", None)
    if not callable(show):
        return False
    callbacks = {"on_confirm": on_confirm, "on_cancel": on_cancel}
    # Try progressively leaner signatures.
    attempts = (
        lambda: show(sim_info, **callbacks),
        lambda: show(sim_info, on_confirm=on_confirm),
        lambda: show(sim_info),
        lambda: show(**callbacks),
        lambda: show(),
    )
    for attempt in attempts:
        try:
            attempt()
            return True
        except Exception:
            continue
    return False


def s4cl_choose_option(title: str, text: str, options: List[Any]) -> Optional[Any]:
    """Build an S4CL option dialog (or ``None``) for a list of (value, label)."""
    module = _first(
        "sims4communitylib.dialogs.option_dialogs.common_choose_option_dialog",
        "sims4communitylib.dialogs.option_dialogs",
    )
    dialog_cls = _attr(module, "CommonChooseOptionDialog")
    if dialog_cls is None:
        return None
    try:
        return dialog_cls(title, text, tuple(options))
    except Exception:
        return None


# --- S4CL: interactions ------------------------------------------------------

def s4cl_interaction_base() -> Optional[Any]:
    """Return the S4CL immediate-super-interaction base class (or ``None``)."""
    module = _first(
        "sims4communitylib.classes.interactions.common_immediate_super_interaction",
        "sims4communitylib.classes.interactions",
    )
    return _attr(module,
                 "CommonImmediateSuperInteraction",
                 "CommonInteraction")


def s4cl_register_interaction(interaction_cls: Any) -> bool:
    """Register an S4CL interaction class so it appears in the pie menu.

    S4CL injects registered interactions itself (no XmlInjector, no .package).
    The registry class name/location has changed across S4CL versions, so every
    known path is tried defensively.
    """
    if interaction_cls is None:
        return False
    registry = _first(
        "sims4communitylib.classes.interactions.common_interaction_registry",
        "sims4communitylib.classes.interactions",
    )
    if registry is None:
        return False
    for cls_name in ("CommonInteractionRegistry", "InteractionRegistry",
                     "CommonInteractionUtils"):
        registry_cls = getattr(registry, cls_name, None)
        if registry_cls is None:
            continue
        for method_name in ("register_interaction", "register_interaction_source",
                            "register"):
            method = getattr(registry_cls, method_name, None)
            if not callable(method):
                continue
            try:
                method(interaction_cls)
                return True
            except Exception:
                continue
    return False


# --- S4CL: sim utilities (used by the collectors) ---------------------------

def s4cl_utils(dotted_module: str, *class_names: str) -> Optional[Any]:
    """Return an S4CL utility class, e.g. ``s4cl_utils('...common_trait_utils',
    'CommonTraitUtils')``."""
    module = _first(dotted_module)
    return _attr(module, *class_names)


# --- native fallbacks that must exist when a lib is missing ------------------
# These mirror the previously valid-free native module paths, so a missing lib
# degrades to the raw game API rather than breaking the module.

def native_notification_owner(sim_info: Any = None) -> Any:
    """Resolve the owner a native notification should be shown to."""
    if sim_info is not None:
        try:
            getter = getattr(sim_info, "get_sim_instance", None)
            instance = getter() if callable(getter) else None
            if instance is not None:
                return instance
        except Exception:
            pass
        return sim_info
    try:
        import services  # type: ignore

        manager = services.client_manager()
        client = manager.get_first_client() if manager else None
        if client is not None:
            return getattr(client, "active_sim", None) or getattr(
                client, "active_sim_info", None)
    except Exception:
        return None
    return None


def native_localized_string(text: str) -> Any:
    """Wrap ``text`` in a game LocalizedString when possible (else the string)."""
    try:
        from sims4.localization import LocalizationHelperTuning  # type: ignore

        return LocalizationHelperTuning.get_raw_text(text)
    except Exception:
        return text
