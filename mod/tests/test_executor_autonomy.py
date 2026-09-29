"""
Tests for the v0.2 autonomy tools in the mod-side tool executor (PLANO §14.2).
Fully offline: the game is faked and no network call is made.

Run with the system Python (3.10+).
"""

import os
import sys

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest

from simssense_mod import state_collector
from simssense_mod import tool_executor as ex


@pytest.fixture(autouse=True)
def _reset_rails():
    ex.get_rails().reset()
    yield
    ex.get_rails().reset()


# --- Fakes for the "game present" path ---

class FakeQueue(object):
    def __init__(self):
        self.pushed = []

    def push_super_affordance(self, affordance, target, target_context):
        self.pushed.append((affordance, target, target_context))


class FakeSimInstance(object):
    def __init__(self):
        self.queue = FakeQueue()
        self.position = (1.0, 2.0, 0.0)
        self.routed = []

    def route_to(self, position):
        self.routed.append(position)


class FakeSimInfo(object):
    def __init__(self):
        self.buffs = []
        self.instance = FakeSimInstance()

    def add_buff(self, name):
        self.buffs.append(name)

    def get_sim_instance(self):
        return self.instance


def _install_fake(monkeypatch):
    fake = FakeSimInfo()
    monkeypatch.setattr(ex, "_get_services", lambda: object())
    monkeypatch.setattr(ex, "_get_target_sim", lambda sim_id=0: fake)
    return fake


# --- Registry ---

def test_registry_contains_autonomy_tools():
    for name in ("nearby_sims", "world_state", "sim_profile",
                 "spontaneous_line", "set_mood", "socialize",
                 "approach", "act_out"):
        assert name in ex._TOOL_REGISTRY


# --- Read-only tools ---

def test_nearby_sims_ok(monkeypatch):
    monkeypatch.setattr(
        state_collector, "sample_zone",
        lambda: ({"zone_id": "z"}, [{"sim_id": 1}, {"sim_id": 2}]))

    result = ex.tool_nearby_sims({})

    assert result == {"ok": True, "sims": [{"sim_id": 1}, {"sim_id": 2}]}


def test_world_state_ok(monkeypatch):
    monkeypatch.setattr(
        state_collector, "sample_zone",
        lambda: ({"zone_id": "z", "lot_type": "residential"}, []))

    result = ex.tool_world_state({})

    assert result == {"ok": True, "zone": {"zone_id": "z", "lot_type": "residential"}}


def test_sim_profile_ok(monkeypatch):
    _install_fake(monkeypatch)
    monkeypatch.setattr(ex, "collect", lambda sim_info: {
        "sim_id": 7,
        "full_name": "Bob",
        "mood": "happy",
        "needs": {"hunger": 1.0},
        "traits": ["Genius"],
        "relationships": [{"target_id": 1}],
    })

    result = ex.tool_sim_profile({"target_sim_id": 7})

    assert result == {"ok": True, "result": {
        "sim_id": 7,
        "full_name": "Bob",
        "mood": "happy",
        "needs": {"hunger": 1.0},
        "traits": ["Genius"],
        "relationships": [{"target_id": 1}],
    }}


def test_sim_profile_missing_argument(monkeypatch):
    _install_fake(monkeypatch)

    result = ex.tool_sim_profile({})

    assert result["ok"] is False
    assert result["error"] == "missing_argument"


def test_sim_profile_target_not_found(monkeypatch):
    monkeypatch.setattr(ex, "_get_services", lambda: object())
    monkeypatch.setattr(ex, "_get_target_sim", lambda sim_id=0: None)

    result = ex.tool_sim_profile({"target_sim_id": 999})

    assert result["ok"] is False
    assert result["error"] == "target_not_found"


def test_sim_profile_not_implemented_without_game(monkeypatch):
    monkeypatch.setattr(ex, "_get_services", lambda: None)

    assert ex.tool_sim_profile({"target_sim_id": 1})["error"] == "not_implemented"


# --- Spontaneous line ---

def test_spontaneous_line_ok():
    result = ex.tool_spontaneous_line({"text": "What a day!",
                                       "audience": "nearby", "tone": "happy"})

    assert result == {"ok": True, "text": "What a day!",
                      "audience": "nearby", "tone": "happy"}


def test_spontaneous_line_defaults_and_missing():
    assert ex.tool_spontaneous_line({"text": "Hi"}) == {
        "ok": True, "text": "Hi", "audience": "self", "tone": "neutral"}
    assert ex.tool_spontaneous_line({})["error"] == "missing_argument"


# --- set_mood ---

def test_set_mood_maps_label_to_buff(monkeypatch):
    fake = _install_fake(monkeypatch)

    result = ex.tool_set_mood({"mood": "happy"})

    assert result == {"ok": True, "result": {"mood": "happy", "buff": "Happy"}}
    assert fake.buffs == ["Happy"]


def test_set_mood_accepts_explicit_buff(monkeypatch):
    fake = _install_fake(monkeypatch)

    result = ex.tool_set_mood({"mood": "happy", "buff_name": "Custom"})

    assert result == {"ok": True, "result": {"mood": "happy", "buff": "Custom"}}
    assert fake.buffs == ["Custom"]


def test_set_mood_missing_argument(monkeypatch):
    _install_fake(monkeypatch)

    assert ex.tool_set_mood({})["error"] == "missing_argument"


def test_set_mood_not_implemented_without_game(monkeypatch):
    monkeypatch.setattr(ex, "_get_services", lambda: None)

    assert ex.tool_set_mood({"mood": "happy"})["error"] == "not_implemented"


# --- socialize ---

def test_socialize_ok(monkeypatch):
    fake = _install_fake(monkeypatch)
    monkeypatch.setattr(ex, "_resolve_affordance", lambda args: "social")

    result = ex.tool_socialize({"target_sim_id": 2, "tone": "friendly"})

    assert result["ok"] is True
    assert result["result"]["interaction"] == "sim-chat"
    assert result["result"]["target_sim_id"] == 2
    assert len(fake.instance.queue.pushed) == 1


def test_socialize_missing_target(monkeypatch):
    _install_fake(monkeypatch)

    assert ex.tool_socialize({})["error"] == "missing_argument"


def test_socialize_target_not_found(monkeypatch):
    fake = FakeSimInfo()
    monkeypatch.setattr(ex, "_get_services", lambda: object())
    monkeypatch.setattr(ex, "_get_target_sim",
                        lambda sim_id=0: fake if sim_id in (0, 1) else None)

    assert ex.tool_socialize({"sim_id": 1, "target_sim_id": 999})["error"] == "target_not_found"


def test_socialize_not_implemented_without_game(monkeypatch):
    monkeypatch.setattr(ex, "_get_services", lambda: None)

    assert ex.tool_socialize({"target_sim_id": 2})["error"] == "not_implemented"


# --- approach ---

def test_approach_ok(monkeypatch):
    fake = _install_fake(monkeypatch)

    result = ex.tool_approach({"target_sim_id": 2})

    assert result["ok"] is True
    assert fake.instance.routed == [(1.0, 2.0, 0.0)]


def test_approach_missing_target(monkeypatch):
    _install_fake(monkeypatch)

    assert ex.tool_approach({})["error"] == "missing_argument"


def test_approach_not_implemented_without_game(monkeypatch):
    monkeypatch.setattr(ex, "_get_services", lambda: None)

    assert ex.tool_approach({"target_sim_id": 2})["error"] == "not_implemented"


# --- act_out ---

def test_act_out_acknowledges_intention():
    result = ex.tool_act_out({"action": "dance in the rain"})

    assert result == {"ok": True, "action": "dance in the rain"}


def test_act_out_missing_action():
    assert ex.tool_act_out({})["error"] == "missing_argument"


def test_act_out_queues_named_interaction(monkeypatch):
    fake = _install_fake(monkeypatch)
    monkeypatch.setattr(ex, "_resolve_affordance", lambda args: "affordance")

    result = ex.tool_act_out({"action": "chat", "interaction_name": "chat",
                              "target_sim_id": 2})

    assert result["ok"] is True
    assert len(fake.instance.queue.pushed) == 1


# --- execute posts top-level payloads ---

def test_execute_posts_top_level_result(monkeypatch):
    posts = []
    monkeypatch.setattr(ex, "post_json",
                        lambda path, payload: posts.append((path, payload)))

    result = ex.execute({"id": "r1", "name": "nearby_sims", "args": {}})

    assert result["ok"] is True
    assert result["sims"] == []  # no game: empty pulse
    assert len(posts) == 1
    assert posts[0][0] == "/v1/tools/result"
    assert posts[0][1]["result"] == {"sims": []}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
