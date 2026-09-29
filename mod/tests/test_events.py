"""
Tests for the validated game event/alarm wiring in events.py (offline).

These lock in the API names verified against the live game (patch 1.113):
- the TestEvent enum lives on ``test_events.TestEvent`` (not the module);
- the manager comes from ``services.get_event_manager()``;
- ``unregister_single_event(handler, event_type)`` needs the event type;
- alarms are the top-level ``alarms`` module (not ``sims4.alarms``);
- time spans come from ``date_and_time.create_time_span``.

Run with system Python (3.10+).
"""

import os
import sys
import types

mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest  # noqa: E402

from sensewright_mod import events  # noqa: E402


def _fake_test_events():
    class TestEvent:
        BuffBeganEvent = "BuffBeganEvent"
        BuffEndedEvent = "BuffEndedEvent"
        RelationshipChanged = "RelationshipChanged"
        HouseholdChanged = "HouseholdChanged"
        InteractionComplete = "InteractionComplete"
        TraitAddEvent = "TraitAddEvent"
        SkillLevelChange = "SkillLevelChange"
        LoadingScreenLifted = "LoadingScreenLifted"

    module = types.SimpleNamespace(TestEvent=TestEvent)
    # A decoy on the module (the old buggy lookup target) must be ignored.
    module.BuffAdded = "module-level-decoy"
    return module


def test_build_event_map_reads_members_off_the_class():
    event_map = events._build_event_map(_fake_test_events())

    assert event_map[events.EVENT_BUFF_ADD] == "BuffBeganEvent"
    assert event_map[events.EVENT_BUFF_REMOVE] == "BuffEndedEvent"
    assert event_map[events.EVENT_RELATIONSHIP_CHANGE] == "RelationshipChanged"
    assert event_map[events.EVENT_HOUSEHOLD_CHANGE] == "HouseholdChanged"
    assert event_map[events.EVENT_ZONE_LOAD] == "LoadingScreenLifted"
    # No native TestEvent for spawn: left unmapped on purpose.
    assert events.EVENT_SIM_SPAWN not in event_map
    # The module-level decoy must never be picked up.
    assert "module-level-decoy" not in event_map.values()


def test_build_event_map_without_test_event_is_empty():
    assert events._build_event_map(None) == {}
    assert events._build_event_map(types.SimpleNamespace()) == {}


def test_register_uses_manager_and_event_type_on_unregister(monkeypatch):
    fake_module = _fake_test_events()

    class FakeManager:
        def __init__(self):
            self.registered = []
            self.unregistered = []

        def register_single_event(self, handler, event_type):
            self.registered.append((handler, event_type))

        def unregister_single_event(self, handler, event_type):
            self.unregistered.append((handler, event_type))

    manager = FakeManager()
    monkeypatch.setattr(events, "_get_event_manager", lambda: (manager, fake_module))
    monkeypatch.setattr(events, "_registered_handlers", {})
    monkeypatch.setattr(events, "_registrations", [])

    def handler(*args, **kwargs):
        pass

    assert events.register({events.EVENT_BUFF_ADD: [handler]}) is True
    assert manager.registered == [(handler, "BuffBeganEvent")]

    events.unregister_all()
    assert manager.unregistered == [(handler, "BuffBeganEvent")]


def test_register_defers_then_flushes_pending(monkeypatch):
    """Handlers queued at import (no manager) must register on a later retry."""
    fake_module = _fake_test_events()

    class FakeManager:
        def __init__(self):
            self.registered = []

        def register_single_event(self, handler, event_type):
            self.registered.append((handler, event_type))

        def unregister_single_event(self, handler, event_type):
            pass

    manager = FakeManager()
    monkeypatch.setattr(events, "_registered_handlers", {})
    monkeypatch.setattr(events, "_registrations", [])
    monkeypatch.setattr(events, "_registered_pairs", set())

    def handler(*args, **kwargs):
        pass

    # Manager not up yet: queued, returns False, nothing registered.
    monkeypatch.setattr(events, "_get_event_manager", lambda: (None, fake_module))
    assert events.register({events.EVENT_BUFF_ADD: [handler]}) is False
    assert manager.registered == []

    # Services ready: flush registers the queued handler exactly once.
    monkeypatch.setattr(events, "_get_event_manager", lambda: (manager, fake_module))
    assert events.flush_pending() is True
    assert manager.registered == [(handler, "BuffBeganEvent")]
    assert events.flush_pending() is True  # idempotent
    assert manager.registered == [(handler, "BuffBeganEvent")]


def test_have_event_manager_reflects_service(monkeypatch):
    monkeypatch.setattr(events, "_get_event_manager", lambda: (None, None))
    assert events.have_event_manager() is False
    monkeypatch.setattr(events, "_get_event_manager", lambda: (object(), None))
    assert events.have_event_manager() is True


def test_add_alarm_requires_game_owner(monkeypatch):
    """alarms.AlarmHandle raises without an owner, so a live owner is required."""
    calls = []

    class FakeHandle:
        pass

    def add_alarm(owner, time_span, callback, repeating=False, **kwargs):
        calls.append(owner)
        return FakeHandle()

    monkeypatch.setitem(sys.modules, "alarms", types.SimpleNamespace(add_alarm=add_alarm))
    monkeypatch.setattr(events, "_make_time_span", lambda minutes: "span")
    monkeypatch.setattr(events, "_alarm_handles", [])

    # No live owner yet: deferred (no call), returns None, retried later.
    monkeypatch.setattr(events, "_resolve_alarm_owner", lambda: None)
    assert events.add_alarm(10.0, lambda: None) is None
    assert calls == []

    # Owner available: it is forwarded to add_alarm.
    monkeypatch.setattr(events, "_resolve_alarm_owner", lambda: "ZONE")
    assert events.add_alarm(10.0, lambda: None) is not None
    assert calls == ["ZONE"]


def test_make_time_span_prefers_date_and_time(monkeypatch):
    sentinel = object()
    captured = {}

    def create_time_span(**kwargs):
        captured.update(kwargs)
        return sentinel

    fake = types.SimpleNamespace(create_time_span=create_time_span)
    monkeypatch.setitem(sys.modules, "date_and_time", fake)

    assert events._make_time_span(30.0) is sentinel
    assert captured == {"minutes": 30.0}


def test_try_add_alarm_uses_top_level_alarms_module(monkeypatch):
    calls = []

    class FakeHandle:
        pass

    handle = FakeHandle()

    def add_alarm(owner, time_span, callback, repeating=False, **kwargs):
        calls.append((owner, time_span, callback, repeating))
        return handle

    fake = types.SimpleNamespace(add_alarm=add_alarm)
    monkeypatch.setitem(sys.modules, "alarms", fake)

    cb = lambda: None  # noqa: E731
    result = events._try_add_alarm("span", cb, True)

    assert result is handle
    assert calls == [(None, "span", cb, True)]


def test_cancel_alarm_uses_top_level_alarms_module(monkeypatch):
    cancelled = []
    fake = types.SimpleNamespace(cancel_alarm=lambda handle: cancelled.append(handle))
    monkeypatch.setitem(sys.modules, "alarms", fake)
    monkeypatch.setattr(events, "_alarm_handles", ["h1"])

    assert events.cancel_alarm("h1") is True
    assert cancelled == ["h1"]
    assert events.cancel_alarm(None) is False


def test_resolve_alarm_owner_prefers_active_sim_instance(monkeypatch):
    sim = types.SimpleNamespace(queue=object())

    class Client:
        active_sim = sim
        active_sim_info = None

    class ClientManager:
        def get_first_client(self):
            return Client()

    fake_services = types.SimpleNamespace(
        client_manager=lambda: ClientManager(),
        current_zone=lambda: "ZONE",
    )
    monkeypatch.setitem(sys.modules, "services", fake_services)

    assert events._resolve_alarm_owner() is sim


def test_resolve_alarm_owner_returns_none_without_live_instance(monkeypatch):
    """M3: no live Sim instance -> None, never a non-ticking zone/household owner."""
    class Client:
        active_sim = None
        active_sim_info = None

    class ClientManager:
        def get_first_client(self):
            return Client()

    def _must_not_be_used():
        raise AssertionError("a non-ticking fallback owner must never be returned")

    fake_services = types.SimpleNamespace(
        client_manager=lambda: ClientManager(),
        current_zone=_must_not_be_used,
        active_household=_must_not_be_used,
    )
    monkeypatch.setitem(sys.modules, "services", fake_services)

    assert events._resolve_alarm_owner() is None


def test_shared_safe_helpers_are_the_debug_log_ones():
    """H5: events uses the shared, logging helpers (no local duplicates)."""
    from sensewright_mod import debug_log

    assert events._safe_getattr is debug_log.safe_getattr
    assert events._safe_call is debug_log.safe_call


def test_flush_logs_registration_failure(monkeypatch):
    """H3: a failed event registration is logged, not swallowed."""
    fake_module = _fake_test_events()
    logged = []
    monkeypatch.setattr(events, "log_exception",
                        lambda where, exc: logged.append(where))

    class BadManager:
        def register_single_event(self, handler, event_type):
            raise RuntimeError("registration failed")

    def handler(*args, **kwargs):
        pass

    monkeypatch.setattr(events, "_registered_handlers",
                        {events.EVENT_BUFF_ADD: [handler]})
    monkeypatch.setattr(events, "_registrations", [])
    monkeypatch.setattr(events, "_registered_pairs", set())

    assert events._flush(BadManager(), fake_module) is False
    assert logged == ["events._flush.register"]


def test_unregister_all_logs_failure(monkeypatch):
    """H3: a failed event unregistration is logged, not swallowed."""
    fake_module = _fake_test_events()
    logged = []
    monkeypatch.setattr(events, "log_exception",
                        lambda where, exc: logged.append(where))

    class BadManager:
        def unregister_single_event(self, handler, event_type):
            raise RuntimeError("unregistration failed")

    def handler(*args, **kwargs):
        pass

    monkeypatch.setattr(events, "_get_event_manager",
                        lambda: (BadManager(), fake_module))
    monkeypatch.setattr(events, "_registered_handlers",
                        {events.EVENT_BUFF_ADD: [handler]})
    monkeypatch.setattr(events, "_registrations", [(handler, "BuffBeganEvent")])
    monkeypatch.setattr(events, "_registered_pairs", set())

    events.unregister_all()
    assert logged == ["events.unregister_all"]


def test_try_add_alarm_logs_each_failed_attempt(monkeypatch):
    """M4: every failed add_alarm attempt is logged (not just the last)."""
    logged = []
    monkeypatch.setattr(events, "log_exception",
                        lambda where, exc: logged.append(where))
    monkeypatch.setattr(events, "debug_log", lambda *args, **kwargs: None)

    def add_alarm(*args, **kwargs):
        raise RuntimeError("bad signature")

    monkeypatch.setitem(sys.modules, "alarms",
                        types.SimpleNamespace(add_alarm=add_alarm))

    assert events._try_add_alarm("span", lambda: None, True) is None
    assert len(logged) == 5
    assert all(where.startswith("events._try_add_alarm") for where in logged)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
