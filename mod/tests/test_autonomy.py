"""
Tests for the v0.2 agency layer (PLANO §14.2): zone pulse, sleep detection,
directive pull loop and the new autonomy HTTP endpoints. Fully offline: game
internals and the sidecar are faked; no game import, no network.

Run with the system Python (3.10+).
"""

import os
import sys

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest

from sensewright_mod import events, http_client, sim_context, state_collector
from sensewright_mod.state_collector import StateCollector


# --- Fakes for the game path ---

class FakeBuffType(object):
    def __init__(self, name):
        self.__name__ = name


class FakeBuff(object):
    def __init__(self, name):
        self.buff_type = FakeBuffType(name)


class FakeBuffComponent(object):
    def __init__(self, names):
        self._active_buffs = {i: FakeBuff(name) for i, name in enumerate(names)}


class FakeHousehold(object):
    def __init__(self, household_id):
        self.id = household_id


class FakeSimInfo(object):
    def __init__(self, sim_id, name, buffs=(), household_id=10, is_selectable=False):
        self.id = sim_id
        self.full_name = name
        self.household = FakeHousehold(household_id)
        self.is_selectable = is_selectable
        self.Buffs = FakeBuffComponent(buffs)

    def get_sim_instance(self):
        return None


def _install_zone_fakes(monkeypatch):
    active = FakeSimInfo(1, "Ana", buffs=("Sleeping",), household_id=10,
                         is_selectable=True)
    other = FakeSimInfo(2, "Bob", buffs=("Happy", "Cheerful"), household_id=20)

    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: active)
    monkeypatch.setattr(sim_context, "_get_save_id", lambda: "save-1")
    monkeypatch.setattr(sim_context, "_get_time_string", lambda: "08:00")
    monkeypatch.setattr(sim_context, "_get_mood", lambda sim_info: "happy")
    monkeypatch.setattr(sim_context, "_get_needs", lambda sim_info: {"hunger": 42.0})
    monkeypatch.setattr(
        sim_context, "_get_relationships",
        lambda sim_info: [{"target_id": 99, "target_name": "X",
                           "depth": 12.0, "track": ""}])
    monkeypatch.setattr(
        sim_context, "_get_location", lambda sim_info: {"x": 1.5, "y": 2.5})
    monkeypatch.setattr(
        state_collector, "_iter_instanced_sim_infos",
        lambda manager=None: [active, other])
    monkeypatch.setattr(state_collector, "_lot_type", lambda: "residential")
    monkeypatch.setattr(state_collector, "_weather", lambda: "")
    return active, other


# --- Sleep detection ---

def test_is_sleeping_matches_exact_tuning_ids():
    assert state_collector._is_sleeping(["Happy", "Sleeping"]) is True
    assert state_collector._is_sleeping(["asleep"]) is True
    assert state_collector._is_sleeping(["buff_SLeeping"]) is True
    assert state_collector._is_sleeping(["moodlet_sleeping"]) is True


def test_is_sleeping_false_without_sleep_buff():
    assert state_collector._is_sleeping(["Happy", "Cheerful"]) is False
    assert state_collector._is_sleeping([]) is False
    assert state_collector._is_sleeping(None) is False


def test_is_sleeping_rejects_substring_false_positives():
    """Whole-id matching must not trip on buffs that merely mention sleep."""
    assert state_collector._is_sleeping(["Not sleeping well"]) is False
    assert state_collector._is_sleeping(["Dreaming of sleeping"]) is False
    assert state_collector._is_sleeping(["asleep_at_work"]) is False


# --- Zone pulse sampling ---

def test_sample_zone_shapes(monkeypatch):
    active, other = _install_zone_fakes(monkeypatch)

    zone, sims = state_collector.sample_zone()

    assert zone == {
        "time_of_day": "08:00",
        "lot_type": "residential",
        "weather": "",
        "zone_id": "save-1",
    }

    assert len(sims) == 2
    state = sims[0]
    assert set(state.keys()) == {
        "sim_id", "full_name", "household_id", "aspiration", "mood", "needs",
        "location", "current_interaction", "interaction_target_sim_id",
        "sleeping", "is_player", "autonomy", "relationships",
    }
    assert state["sim_id"] == 1
    assert state["full_name"] == "Ana"
    assert state["household_id"] == 10
    assert state["mood"] == "happy"
    assert state["needs"] == {"hunger": 42.0}
    assert state["location"] == "1.5,2.5"
    assert state["sleeping"] is True
    assert state["is_player"] is True
    assert state["autonomy"] == state_collector.DEFAULT_AUTONOMY
    assert state["relationships"] == [{"target_id": 99, "target_name": "X", "depth": 12.0}]

    assert sims[1]["sim_id"] == 2
    assert sims[1]["sleeping"] is False
    assert sims[1]["is_player"] is False


def test_sample_zone_tolerates_broken_sim(monkeypatch):
    active, other = _install_zone_fakes(monkeypatch)

    class ExplodingSim(object):
        id = 3

    monkeypatch.setattr(
        state_collector, "_iter_instanced_sim_infos",
        lambda manager=None: [active, ExplodingSim(), other])

    def fake_state(sim_info, player_household_id=None):
        if sim_info is not other:
            raise RuntimeError("boom")
        return {"sim_id": 2}

    monkeypatch.setattr(state_collector, "_autonomy_sim_state", fake_state)

    _zone, sims = state_collector.sample_zone()
    assert sims == [{"sim_id": 2}]


# --- HTTP client endpoints ---

def _fake_post_json(captured):
    def fake(path, payload, timeout=http_client.DEFAULT_TIMEOUT):
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True}
    return fake


def test_autonomy_tick_payload(monkeypatch):
    captured = {}
    monkeypatch.setattr(http_client, "post_json", _fake_post_json(captured))

    sim = {"player_id": "local", "save_id": "s", "sim_id": 1}
    zone = {"zone_id": "s", "lot_type": "residential"}
    sims = [{"sim_id": 1, "sleeping": True}]

    result = http_client.autonomy_tick(sim, zone, sims, "en")

    assert result == {"ok": True}
    assert captured["path"] == "/v1/autonomy/tick"
    assert captured["payload"] == {
        "sim": sim,
        "zone": zone,
        "sims": sims,
        "lang": "en",
    }


def test_get_directives_url_omits_sim_id(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        http_client, "get_json",
        lambda path, timeout=http_client.DEFAULT_TIMEOUT:
        captured.__setitem__("path", path) or {"ok": True})

    result = http_client.get_directives("save-1")

    assert result == {"ok": True}
    assert captured["path"].startswith("/v1/autonomy/directives?")
    assert "save_id=save-1" in captured["path"]
    assert "player_id=local" in captured["path"]
    assert "limit=20" in captured["path"]
    assert "sim_id" not in captured["path"]


def test_get_directives_url_includes_sim_id(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        http_client, "get_json",
        lambda path, timeout=http_client.DEFAULT_TIMEOUT:
        captured.__setitem__("path", path) or {"ok": True})

    http_client.get_directives("save-1", sim_id=5, limit=3)

    assert "sim_id=5" in captured["path"]
    assert "limit=3" in captured["path"]


def test_get_intents_url_and_seats(monkeypatch):
    captured = {}

    def fake_get_json(path, timeout=http_client.DEFAULT_TIMEOUT):
        captured["path"] = path
        return {"ok": True}

    monkeypatch.setattr(http_client, "get_json", fake_get_json)

    http_client.get_intents("save-1", sim_id=5, limit=3)
    assert captured["path"].startswith("/v1/autonomy/intents?")
    assert "sim_id=5" in captured["path"]
    assert "limit=3" in captured["path"]

    http_client.get_seats("save-1")
    assert captured["path"].startswith("/v1/agency/seats?")
    assert "save_id=save-1" in captured["path"]


def test_assign_seat_posts_pool_and_frequency(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        http_client, "post_json",
        lambda path, payload, timeout=http_client.DEFAULT_TIMEOUT:
        captured.update(path=path, payload=payload) or {"ok": True})

    http_client.assign_seat({"player_id": "local", "save_id": "s1", "sim_id": 1},
                            sim_id=2, impulse_frequency=0.5)

    assert captured["path"] == "/v1/agency/seats"
    assert captured["payload"]["sim_id"] == 2
    assert captured["payload"]["impulse_frequency"] == 0.5


def test_attach_lifecycle_posts_game_pid(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        http_client, "post_json",
        lambda path, payload, timeout=http_client.DEFAULT_TIMEOUT:
        captured.update(path=path, payload=payload) or {"ok": True})

    http_client.attach_lifecycle(4321)

    assert captured["path"] == "/v1/lifecycle/attach"
    assert captured["payload"] == {"pid": 4321}


# --- Sending the pulse ---

def test_send_autonomy_tick_payload(monkeypatch):
    monkeypatch.setattr(
        state_collector, "sample_zone",
        lambda: ({"zone_id": "z"}, [{"sim_id": 1}]))
    monkeypatch.setattr(state_collector, "_active_sim_ref", lambda: {"sim_id": 1})
    captured = {}

    def fake_tick(sim, zone, sims, lang):
        captured["args"] = (sim, zone, sims, lang)
        return {"ok": True, "scheduled": 2}

    monkeypatch.setattr(http_client, "autonomy_tick", fake_tick)

    result = state_collector.send_autonomy_tick()

    assert result == {"ok": True, "scheduled": 2}
    assert captured["args"][1] == {"zone_id": "z"}
    assert captured["args"][2] == [{"sim_id": 1}]
    assert isinstance(captured["args"][3], str)


def test_send_autonomy_tick_swallows_sidecar_errors(monkeypatch):
    monkeypatch.setattr(
        state_collector, "sample_zone", lambda: ({}, []))

    def boom(*args, **kwargs):
        raise http_client.SidecarUnreachable()

    monkeypatch.setattr(http_client, "autonomy_tick", boom)

    assert state_collector.send_autonomy_tick() is None


# --- Pull and execute directives ---

def test_pull_and_execute_translates_intents(monkeypatch):
    responses = {
        "ok": True,
        "intents": [
            {"id": "c1", "sim_id": 1, "kind": "set_mood", "name": "set_mood",
             "args": {"sim_id": 1, "mood": "happy"}, "params": {"sim_id": 1, "mood": "happy"},
             "thought": "I feel good", "narration": "Ana hums a tune.",
             "priority": 1, "source": "agent"},
            {"id": "c2", "sim_id": 2, "kind": "speak", "name": "",
             "args": {}, "params": {"text": "Hi"}, "thought": "", "narration": ""},
            {"id": "c3", "sim_id": 3, "kind": "speak", "name": "",
             "args": {}, "params": {"text": "Hello"}, "thought": "", "narration": ""},
        ],
    }
    monkeypatch.setattr(http_client, "get_intents",
                        lambda *args, **kwargs: responses)
    monkeypatch.setattr(sim_context, "_get_save_id", lambda: "save-1")

    calls = []

    def fake_execute_intent(intent):
        calls.append(intent)
        if intent["id"] == "c2":
            raise RuntimeError("sidecar blew up")
        if intent["id"] == "c3":
            return {"ok": True, "text": "Hello there"}
        return {"ok": True}

    monkeypatch.setattr(state_collector.tool_executor, "execute_intent", fake_execute_intent)

    shown = []
    monkeypatch.setattr(
        state_collector.chat_ui, "show_simple_notification",
        lambda message, sim_info=None: shown.append(message) or True)

    result = state_collector.pull_and_execute_directives()

    assert result == responses
    assert [intent["id"] for intent in calls] == ["c1", "c2", "c3"]
    assert any("Ana hums a tune." in message for message in shown)
    assert any("I feel good" in message for message in shown)
    assert any("Hello there" in message for message in shown)


def test_pull_and_execute_tolerates_sidecar_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise http_client.SidecarError(500, "boom")

    monkeypatch.setattr(http_client, "get_intents", boom)

    assert state_collector.pull_and_execute_directives() is None


def test_pull_and_execute_tolerates_generic_failure(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(http_client, "get_intents", boom)

    assert state_collector.pull_and_execute_directives() is None


def test_pull_intents_falls_back_to_directives_on_404(monkeypatch):
    def not_found(*args, **kwargs):
        raise http_client.SidecarError(404, "not found")

    legacy = {
        "ok": True,
        "directives": [{"id": "d1", "sim_id": 1, "name": "add_buff", "args": {}}],
    }
    monkeypatch.setattr(http_client, "get_intents", not_found)
    monkeypatch.setattr(http_client, "get_directives", lambda *a, **k: legacy)
    monkeypatch.setattr(sim_context, "_get_save_id", lambda: "save-1")

    calls = []
    monkeypatch.setattr(state_collector.tool_executor, "execute_intent",
                        lambda intent: calls.append(intent) or {"ok": True})

    result = state_collector.pull_and_execute_directives()

    assert result["intents"] == legacy["directives"]
    assert calls[0]["name"] == "add_buff"


# --- Alarm lifecycle ---

def test_start_registers_pulse_and_pull_alarms(monkeypatch):
    calls = []
    cancelled = []
    handles = iter(["h1", "h2", "h3"])

    def fake_add_alarm(minutes, callback, repeating=False):
        calls.append((minutes, callback, repeating))
        return next(handles)

    monkeypatch.setattr(events, "add_alarm", fake_add_alarm)
    monkeypatch.setattr(events, "cancel_alarm",
                        lambda handle: cancelled.append(handle) or True)
    monkeypatch.setattr(events, "register", lambda handlers: True)
    monkeypatch.setattr(events, "unregister_all", lambda: None)

    collector = StateCollector()
    assert collector.start() is True

    intervals = {call[1]: call[0] for call in calls}
    assert intervals[collector._on_autonomy_alarm] == state_collector.AUTONOMY_INTERVAL_MINUTES
    assert intervals[collector._on_directive_alarm] == state_collector.DIRECTIVE_PULL_INTERVAL_MINUTES

    assert collector.stop() is True
    assert sorted(cancelled) == ["h1", "h2", "h3"]
    assert collector.stop() is False


def test_pulse_alarm_swallows_errors(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(state_collector, "send_autonomy_tick", boom)
    monkeypatch.setattr(state_collector, "pull_and_execute_directives", boom)

    collector = StateCollector()
    collector._on_autonomy_alarm()  # must not raise
    collector._on_directive_alarm()  # must not raise


def test_buff_names_reads_buff_component_active_buffs(monkeypatch):
    class BuffType(object):
        def __init__(self, name):
            self.__name__ = name

    class Buff(object):
        def __init__(self, name):
            self.buff_type = BuffType(name)

    class Component(object):
        def __init__(self, names):
            self._active_buffs = {i: Buff(name) for i, name in enumerate(names)}

    class SimInfo(object):
        Buffs = Component(["buff_Sleeping", "buff_Happy"])

    names = state_collector._buff_names_of(SimInfo())

    assert "buff_Sleeping" in names
    assert state_collector._is_sleeping(names) is True


def test_buff_names_falls_back_to_sim_instance(monkeypatch):
    class BuffType(object):
        def __init__(self, name):
            self.__name__ = name

    class Buff(object):
        def __init__(self, name):
            self.buff_type = BuffType(name)

    class Component(object):
        def __init__(self):
            self._active_buffs = {0: Buff("moodlet_sleeping")}

    class Instance(object):
        Buffs = Component()

    class SimInfo(object):
        Buffs = None

    monkeypatch.setattr(sim_context, "_get_sim_instance", lambda sim_info: Instance())

    names = state_collector._buff_names_of(SimInfo())

    assert names == ["moodlet_sleeping"]


def test_event_pulse_fires_when_started_and_throttles(monkeypatch):
    calls = {"tick": 0, "pull": 0}
    monkeypatch.setattr(state_collector, "send_autonomy_tick",
                        lambda *a, **k: calls.__setitem__("tick", calls["tick"] + 1))
    monkeypatch.setattr(state_collector, "pull_and_execute_directives",
                        lambda *a, **k: calls.__setitem__("pull", calls["pull"] + 1))

    collector = StateCollector()
    collector._started = True
    collector._last_pulse = 0.0

    collector._maybe_pulse()
    assert calls == {"tick": 1, "pull": 1}

    # Wall-clock throttled: an immediate second call is skipped.
    collector._maybe_pulse()
    assert calls == {"tick": 1, "pull": 1}


def test_event_pulse_skipped_when_not_started(monkeypatch):
    calls = []
    monkeypatch.setattr(state_collector, "send_autonomy_tick",
                        lambda *a, **k: calls.append("tick"))

    collector = StateCollector()
    collector._started = False

    collector._maybe_pulse()

    assert calls == []


def test_install_zone_hook_starts_collector_and_drives_pulse(monkeypatch):
    import types

    monkeypatch.setattr(state_collector, "_ZONE_HOOK",
                        {"installed": False, "started": False, "last_pulse": 0.0})
    ensure_calls = []
    pulse = {"tick": 0, "pull": 0}
    monkeypatch.setattr(state_collector, "ensure_started",
                        lambda: ensure_calls.append("ensure") or True)
    monkeypatch.setattr(state_collector, "send_autonomy_tick",
                        lambda *a, **k: pulse.__setitem__("tick", pulse["tick"] + 1))
    monkeypatch.setattr(state_collector, "pull_and_execute_directives",
                        lambda *a, **k: pulse.__setitem__("pull", pulse["pull"] + 1))
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: object())
    monkeypatch.setattr(sim_context, "_get_sim_instance", lambda sim_info: object())

    class Zone(object):
        def update(self, *args, **kwargs):
            return "orig"

    original = Zone.update
    monkeypatch.setitem(sys.modules, "zone", types.SimpleNamespace(Zone=Zone))

    assert state_collector.install_zone_hook() is True
    zone = Zone()
    assert zone.update() == "orig"
    assert ensure_calls == ["ensure"]
    assert pulse == {"tick": 1, "pull": 1}

    # Heartbeat stays installed but is throttled within the interval.
    assert Zone.update is not original
    zone.update()
    assert ensure_calls == ["ensure"]
    assert pulse == {"tick": 1, "pull": 1}


def test_install_zone_hook_noop_without_zone_module(monkeypatch):
    import types

    monkeypatch.setattr(state_collector, "_ZONE_HOOK",
                        {"installed": False, "started": False, "last_pulse": 0.0})
    monkeypatch.setitem(sys.modules, "zone", types.SimpleNamespace())

    assert state_collector.install_zone_hook() is False


def test_install_zone_hook_waits_for_active_sim(monkeypatch):
    import types

    monkeypatch.setattr(state_collector, "_ZONE_HOOK",
                        {"installed": False, "started": False, "last_pulse": 0.0})
    calls = []
    monkeypatch.setattr(state_collector, "ensure_started",
                        lambda: calls.append("ensure") or True)
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: None)

    class Zone(object):
        def update(self, *args, **kwargs):
            return "orig"

    original = Zone.update
    monkeypatch.setitem(sys.modules, "zone", types.SimpleNamespace(Zone=Zone))

    assert state_collector.install_zone_hook() is True
    Zone().update()

    assert calls == []  # no active Sim yet -> keep waiting
    assert Zone.update is not original  # still wrapped for the next tick


# --- Interaction target signal (v0.3 R5 anti-telepathy gate) ---

class FakeInteraction(object):
    def __init__(self, target=None, name="social_Chat"):
        self.target = target
        self.name = name


class FakeQueue(object):
    def __init__(self, current=None):
        self._current = current

    def get_current_interaction(self):
        return self._current


class FakeSimInstance(object):
    def __init__(self, queue=None):
        self.queue = queue


class FakeSimInfoWithInstance(FakeSimInfo):
    def __init__(self, *args, **kwargs):
        instance = kwargs.pop("instance", None)
        FakeSimInfo.__init__(self, *args, **kwargs)
        self._instance = instance

    def get_sim_instance(self):
        return self._instance


def test_sim_id_of_target_accepts_sim_info():
    assert state_collector._sim_id_of_target(FakeSimInfo(42, "Bea")) == 42


def test_sim_id_of_target_accepts_sim_instance():
    target_instance = FakeSimInstance()
    target_instance.sim_info = FakeSimInfo(42, "Bea")
    assert state_collector._sim_id_of_target(target_instance) == 42


def test_sim_id_of_target_accepts_tuple():
    assert state_collector._sim_id_of_target((FakeSimInfo(42, "Bea"), None)) == 42


def test_sim_id_of_target_rejects_objects_and_none():
    class FakeObject(object):
        id = 7

    assert state_collector._sim_id_of_target(FakeObject()) is None
    assert state_collector._sim_id_of_target(None) is None


def test_interaction_target_id_of_reads_current_interaction():
    interaction = FakeInteraction(target=FakeSimInfo(42, "Bea"))
    sim_info = FakeSimInfoWithInstance(
        1, "Ana", instance=FakeSimInstance(FakeQueue(interaction))
    )
    assert state_collector._interaction_target_id_of(sim_info) == 42


def test_interaction_target_id_of_none_without_queue_or_target():
    no_queue = FakeSimInfoWithInstance(1, "Ana", instance=FakeSimInstance(None))
    assert state_collector._interaction_target_id_of(no_queue) is None
    object_target = FakeInteraction(target=None)
    with_object = FakeSimInfoWithInstance(
        1, "Ana", instance=FakeSimInstance(FakeQueue(object_target))
    )
    assert state_collector._interaction_target_id_of(with_object) is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
