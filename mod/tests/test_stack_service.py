"""
Tests for the Lot 51 custom service (``stack_service``) and the CoreEvent
member mapping used by the stack base. Fully offline - Lot 51 is absent, so the
checks stub the integration seam.

Run with the system Python (3.10+).
"""

import os
import sys

mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

from sensewright_mod import events, integrations, stack_service, state_collector  # noqa: E402


def _reset():
    stack_service._REGISTERED["done"] = False
    stack_service._REGISTERED["service"] = None


def test_register_returns_false_without_lot51(monkeypatch):
    _reset()
    monkeypatch.setattr(integrations, "lot51_service_base", lambda: None)
    assert stack_service.register() is False
    assert stack_service.registered() is False


def test_register_builds_service_and_wires_lifecycle(monkeypatch):
    _reset()
    base = type("FakeServiceBase", (object,), {})
    captured = {}

    monkeypatch.setattr(integrations, "lot51_service_base", lambda: base)

    def fake_register(service_cls):
        captured["cls"] = service_cls
        return True

    monkeypatch.setattr(integrations, "lot51_register_service", fake_register)

    calls = {"started": 0, "stopped": 0}
    monkeypatch.setattr(
        state_collector, "ensure_started",
        lambda: calls.__setitem__("started", calls["started"] + 1))
    monkeypatch.setattr(
        state_collector, "stop",
        lambda: calls.__setitem__("stopped", calls["stopped"] + 1))

    assert stack_service.register() is True
    assert stack_service.registered() is True
    service = captured["cls"]()
    service.on_zone_load()
    service.stop()
    assert calls == {"started": 1, "stopped": 1}
    _reset()


def test_register_is_idempotent(monkeypatch):
    _reset()
    base = type("FakeServiceBase", (object,), {})
    calls = {"count": 0}

    monkeypatch.setattr(integrations, "lot51_service_base", lambda: base)

    def fake_register(service_cls):
        calls["count"] += 1
        return True

    monkeypatch.setattr(integrations, "lot51_register_service", fake_register)

    assert stack_service.register() is True
    assert stack_service.register() is True
    assert calls["count"] == 1
    _reset()


def test_lot51_member_uses_verified_core_event_names():
    """The mapping must use the member names verified against the library."""

    class FakeCoreEvent(object):
        ZONE_LOAD = "zone.load"
        LOADING_SCREEN_LIFTED = "zone.loading_screen_lifted"
        OBJECT_ADDED = "game_object.added"
        OBJECT_DESTROYED = "game_object.destroyed"
        GAME_TICK = "game.update"

    core_event = FakeCoreEvent()
    assert events._lot51_member(core_event, "zone_load") == "zone.load"
    assert events._lot51_member(core_event, "zone_late_load") == \
        "zone.loading_screen_lifted"
    assert events._lot51_member(core_event, "object_added") == "game_object.added"
    assert events._lot51_member(core_event, "object_destroyed") == \
        "game_object.destroyed"
    assert events._lot51_member(core_event, "tick") == "game.update"
    assert events._lot51_member(core_event, "missing_concept") is None


def test_lot51_tick_callback_swallows_user_errors(monkeypatch):
    """A raising tick callback must not escape the Lot 51 handler."""

    class FakeCoreEvent(object):
        GAME_TICK = "game.update"

    captured = {}

    def fake_events():
        def handler(name):
            def wrapper(func):
                captured["callback"] = func
                return func
            return wrapper

        return handler, FakeCoreEvent()

    monkeypatch.setattr(integrations, "lot51_events", fake_events)
    events._LOT51_STATE["tick"] = False
    events._LOT51_STATE["registered"] = []

    def boom():
        raise RuntimeError("kaboom")

    try:
        assert events.register_lot51_tick(boom) is True
        # EventService.process_event: callback(event_service, context=...).
        captured["callback"](object(), context=None)
    finally:
        events._LOT51_STATE["tick"] = False
        events._LOT51_STATE["registered"] = []
