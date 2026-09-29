"""
Tests for state_collector and event ingestion (offline).
Run with system Python (3.10+).
"""

import os
import sys

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest

from sensewright_mod import events, http_client, state_collector
from sensewright_mod.state_collector import StateCollector


SAMPLE_SIM = {"player_id": "local", "save_id": "save1", "sim_id": 123}


def _fake_post_json(captured):
    def fake(path, payload, timeout=http_client.DEFAULT_TIMEOUT):
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True}
    return fake


def test_imports_cleanly_outside_game():
    assert hasattr(state_collector, "StateCollector")
    assert callable(state_collector.start)
    assert callable(state_collector.stop)
    assert callable(state_collector.get_collector)
    assert callable(state_collector.notify_player_activity)
    assert callable(state_collector.last_snapshot)


def test_start_stop_do_not_raise():
    collector = StateCollector()
    collector.start()
    collector.start()  # idempotent
    collector.stop()
    collector.stop()  # idempotent
    state_collector.start()
    state_collector.stop()


def test_start_schedules_game_clock_alarm(monkeypatch):
    calls = []
    cancelled = []
    handles = iter(["handle-1", "handle-2", "handle-3"])

    def fake_add_alarm(minutes, callback, repeating=False):
        calls.append((minutes, callback, repeating))
        return next(handles)

    monkeypatch.setattr(events, "add_alarm", fake_add_alarm)
    monkeypatch.setattr(events, "cancel_alarm", lambda handle: cancelled.append(handle) or True)
    monkeypatch.setattr(events, "register", lambda handlers: True)
    monkeypatch.setattr(events, "unregister_all", lambda: None)

    collector = StateCollector(interval_minutes=15.0)
    assert collector.start() is True
    # Snapshot (30 min) + zone pulse + directive pull => three repeating alarms.
    snapshot_calls = [call for call in calls if call[1] == collector._on_snapshot_alarm]
    assert len(snapshot_calls) == 1
    assert snapshot_calls[0][0] == 15.0
    assert snapshot_calls[0][2] is True  # repeating
    assert len(calls) == 3

    assert collector.start() is False  # idempotent
    assert len(calls) == 3  # no new alarms on restart

    assert collector.stop() is True
    assert sorted(cancelled) == ["handle-1", "handle-2", "handle-3"]
    assert collector.stop() is False


def test_send_event_wire_payload(monkeypatch):
    captured = {}
    monkeypatch.setattr(http_client, "post_json", _fake_post_json(captured))

    result = http_client.send_event(SAMPLE_SIM, "snapshot", {"mood": "happy"},
                                    importance=1.0, lang="en")

    assert result == {"ok": True}
    assert captured["path"] == "/v1/events"
    assert captured["payload"] == {
        "events": [
            {
                "sim": {"player_id": "local", "save_id": "save1", "sim_id": 123},
                "type": "snapshot",
                "content": {"mood": "happy"},
                "importance": 1.0,
                "lang": "en",
            }
        ]
    }


def test_send_event_defaults(monkeypatch):
    captured = {}
    monkeypatch.setattr(http_client, "post_json", _fake_post_json(captured))

    http_client.send_event(SAMPLE_SIM, "social")

    event = captured["payload"]["events"][0]
    assert event["content"] == {}
    assert event["importance"] == 1.0
    assert event["lang"] == "en"


def test_send_events_batch_payload(monkeypatch):
    captured = {}
    monkeypatch.setattr(http_client, "post_json", _fake_post_json(captured))

    items = [{
        "sim": SAMPLE_SIM,
        "type": "buff_add",
        "content": {"buff": "Happy"},
        "importance": 0.7,
        "lang": "en",
    }]
    http_client.send_events(items)

    assert captured["path"] == "/v1/events"
    assert captured["payload"] == {"events": items}


def test_state_collector_snapshot_shape(monkeypatch):
    fake_context = {
        "source": "native",
        "sim_id": 123,
        "save_id": "save1",
        "mood": "happy",
        "needs": {"hunger": 50.0},
    }
    monkeypatch.setattr(state_collector.sim_context, "collect",
                        lambda *args, **kwargs: dict(fake_context))

    captured = []

    def fake_send_events(event_list, timeout=http_client.DEFAULT_TIMEOUT):
        captured.append(event_list)
        return {}

    monkeypatch.setattr(http_client, "send_events", fake_send_events)

    collector = StateCollector()
    result = collector.sample_and_send()

    assert result == fake_context
    assert collector.last_snapshot() == fake_context
    assert len(captured) == 1
    assert isinstance(captured[0], list)
    assert len(captured[0]) == 1

    event = captured[0][0]
    assert event["type"] == "snapshot"
    assert event["importance"] == 1.0
    assert event["content"] == fake_context
    assert event["sim"] == {"player_id": "local", "save_id": "save1", "sim_id": 123}
    assert isinstance(event["lang"], str) and event["lang"]


def test_snapshot_send_swallows_sidecar_errors(monkeypatch):
    monkeypatch.setattr(state_collector.sim_context, "collect",
                        lambda *args, **kwargs: {"sim_id": 1, "save_id": "s"})

    def boom(*args, **kwargs):
        raise http_client.SidecarUnreachable()

    monkeypatch.setattr(http_client, "send_events", boom)

    collector = StateCollector()
    collector.sample_and_send()  # must not raise
    assert collector.last_snapshot() == {"sim_id": 1, "save_id": "s"}


def test_notify_player_activity_calls_endpoint(monkeypatch):
    captured = {}
    monkeypatch.setattr(http_client, "post_json", _fake_post_json(captured))

    result = state_collector.notify_player_activity(SAMPLE_SIM)

    assert result == {"ok": True}
    assert captured["path"] == "/v1/config/player-activity"
    assert captured["payload"] == {"sim": SAMPLE_SIM}


def test_notify_player_activity_swallows_errors(monkeypatch):
    def boom(path, payload, timeout=http_client.DEFAULT_TIMEOUT):
        raise http_client.SidecarError(500, "boom")

    monkeypatch.setattr(http_client, "post_json", boom)

    assert state_collector.notify_player_activity(SAMPLE_SIM) is None


def test_ensure_started_bootstraps_census_once(monkeypatch):
    monkeypatch.setattr(events, "add_alarm", lambda *a, **k: object())
    monkeypatch.setattr(events, "register", lambda handlers: True)
    calls = {"census": 0}
    monkeypatch.setattr(state_collector, "send_census",
                        lambda *a, **k: calls.__setitem__("census", calls["census"] + 1))

    collector = StateCollector()
    assert collector.ensure_started() is True
    assert collector.ensure_started() is True
    assert calls["census"] == 1  # bootstrapped only once


def test_no_threading_timer_usage():
    for filename in ("state_collector.py", "events.py"):
        path = os.path.join(mod_dir, "sensewright_mod", filename)
        with open(path, "r", encoding="utf-8") as handle:
            source = handle.read()
        assert "threading" not in source
        assert "Timer" not in source


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_sidecar_state_on_when_tick_or_pull_answered():
    assert state_collector._sidecar_state({"ok": True}, None) == "on"
    assert state_collector._sidecar_state(None, {"intents": []}) == "on"


def test_sidecar_state_off_when_unreachable(monkeypatch):
    def _boom():
        raise http_client.SidecarUnreachable("down")

    monkeypatch.setattr(http_client, "health", _boom)
    assert state_collector._sidecar_state(None, None) == "off"


def test_sidecar_state_error_when_health_ok_but_pulse_failed(monkeypatch):
    monkeypatch.setattr(http_client, "health", lambda: {"ok": True})
    assert state_collector._sidecar_state(None, None) == "error"


class _LocalizedLike(object):
    """Stands in for a LocalizedString: no ``__name__``, meaningful ``str``."""

    def __str__(self):
        return "Bella Goth"


class _TuningLike(object):
    __name__ = "buff_Sleeping"


def test_full_name_of_prefers_plain_string():
    class FakeInfo(object):
        full_name = "Plain Name"

    assert state_collector._full_name_of(FakeInfo()) == "Plain Name"


def test_full_name_of_handles_localized_string():
    class FakeInfo(object):
        full_name = _LocalizedLike()

    assert state_collector._full_name_of(FakeInfo()) == "Bella Goth"


def test_full_name_of_prefers_tuning_name():
    class FakeInfo(object):
        full_name = _TuningLike()

    assert state_collector._full_name_of(FakeInfo()) == "buff_Sleeping"


def test_full_name_of_returns_empty_for_none():
    class FakeInfo(object):
        full_name = None

    assert state_collector._full_name_of(FakeInfo()) == ""


def test_full_name_of_returns_empty_for_missing_attr():
    class FakeInfo(object):
        pass

    assert state_collector._full_name_of(FakeInfo()) == ""


def test_career_name_of_returns_tuning_name():
    class FakeInfo(object):
        pass

    careers = [{"name": "career_TechGuru", "level": 5, "is_active": True}]

    import sensewright_mod.sim_context as sim_context

    original_get_careers = sim_context._get_careers
    try:
        sim_context._get_careers = lambda sim_info: careers
        assert state_collector._career_name_of(FakeInfo()) == "career_TechGuru"
    finally:
        sim_context._get_careers = original_get_careers


def test_career_name_of_skips_numeric_names():
    class FakeInfo(object):
        pass

    careers = [{"name": "12345", "level": 5, "is_active": True}]

    import sensewright_mod.sim_context as sim_context

    original_get_careers = sim_context._get_careers
    try:
        sim_context._get_careers = lambda sim_info: careers
        assert state_collector._career_name_of(FakeInfo()) == ""
    finally:
        sim_context._get_careers = original_get_careers


def test_career_name_of_returns_empty_when_no_careers():
    class FakeInfo(object):
        pass

    import sensewright_mod.sim_context as sim_context
    original_get_careers = sim_context._get_careers
    try:
        sim_context._get_careers = lambda sim_info: []
        assert state_collector._career_name_of(FakeInfo()) == ""
    finally:
        sim_context._get_careers = original_get_careers


class _NestedTuning(object):
    __name__ = "buff_Nested"


class _NestedBuffType(object):
    buff_type = _NestedTuning()


def test_buff_type_name_uses_exact_tuning_id():
    class BuffType(object):
        __name__ = "buff_Sleeping"

    class Buff(object):
        buff_type = BuffType()

    assert state_collector._buff_type_name(Buff()) == "buff_Sleeping"


def test_buff_type_name_uses_nested_tuning_id():
    class Buff(object):
        buff_type = _NestedBuffType()

    assert state_collector._buff_type_name(Buff()) == "buff_Nested"


def test_buff_type_name_accepts_bare_tuning():
    class Tuning(object):
        __name__ = "buff_Bare"

    assert state_collector._buff_type_name(Tuning()) == "buff_Bare"


def test_buff_type_name_never_returns_localized_name():
    """M5: a display name must never leak in as a tuning id."""
    class BuffType(object):
        name = "Dorminhoco"

    class Buff(object):
        buff_type = BuffType()
        name = "Dorminhoco"

    class Localized(object):
        name = "Dorminhoco"

        def __str__(self):
            return "Dorminhoco"

    assert state_collector._buff_type_name(Buff()) == ""
    assert state_collector._buff_type_name(Localized()) == ""
    assert state_collector._buff_type_name(None) == ""


def test_send_logs_sidecar_failure(monkeypatch):
    """H1: dropped event batches are logged, not swallowed."""
    logged = []
    monkeypatch.setattr(state_collector, "log_exception",
                        lambda where, exc: logged.append(where))

    def boom(*args, **kwargs):
        raise http_client.SidecarUnreachable()

    monkeypatch.setattr(http_client, "send_events", boom)

    collector = StateCollector()
    collector._send([{"type": "buff_add"}])
    assert logged == ["state_collector._send"]


def test_send_autonomy_tick_logs_generic_failure(monkeypatch):
    """H2: the final generic except is logged."""
    logged = []
    monkeypatch.setattr(state_collector, "log_exception",
                        lambda where, exc: logged.append(where))
    monkeypatch.setattr(state_collector, "sample_zone", lambda: ({}, []))

    def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(http_client, "autonomy_tick", boom)

    assert state_collector.send_autonomy_tick() is None
    assert logged == ["state_collector.send_autonomy_tick"]


def test_show_autonomy_text_falls_back_to_debug_log(monkeypatch):
    """L8: the console fallback uses debug_log, not print()."""
    import sensewright_mod.sim_context as sim_context

    messages = []
    monkeypatch.setattr(state_collector.chat_ui, "show_simple_notification",
                        lambda message, sim_info=None: False)
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: None)
    monkeypatch.setattr(state_collector, "debug_log",
                        lambda message: messages.append(message))

    state_collector._show_autonomy_text("notify.autonomy.directive", "hello")

    assert any("hello" in message for message in messages)


def test_no_print_statements_in_state_collector():
    path = os.path.join(mod_dir, "sensewright_mod", "state_collector.py")
    with open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    assert "print(" not in source
