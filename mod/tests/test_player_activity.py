"""
Tests for the mod-side player-activity detector.
Fully offline: fake game modules are injected via sys.modules.
Run with the system Python (3.10+).
"""

import os
import sys
import types

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest
from sensewright_mod import player_activity as pa


def _fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


@pytest.fixture(autouse=True)
def _clean_install():
    pa.reset_for_test()
    yield
    pa.reset_for_test()


# --- classification ---

class _Source(object):
    USER = "user"
    PIE_MENU = "pie"
    GET_TO_WORK = "gtw"
    SCRIPT = "script"


class _Context(object):
    def __init__(self, source):
        self.source = source


def test_is_player_push_true_for_user_source():
    assert pa._is_player_push(_Context("pie"), {"user", "pie"}) is True


def test_is_player_push_false_for_script_source():
    assert pa._is_player_push(_Context("script"), {"user", "pie"}) is False


def test_is_player_push_false_when_source_unknown():
    assert pa._is_player_push(_Context("whatever"), set()) is False


def test_is_player_push_false_without_context():
    assert pa._is_player_push(None, {"user"}) is False


# --- dispatch ---

def test_on_player_action_arms_local_and_sidecar(monkeypatch):
    local = []
    sidecar = []

    from sensewright_mod import tool_executor, state_collector, sim_context

    monkeypatch.setattr(tool_executor, "record_player_activity",
                        lambda sim_id=0: local.append(sim_id))
    monkeypatch.setattr(state_collector, "notify_player_activity",
                        lambda sim: sidecar.append(sim))
    monkeypatch.setattr(sim_context, "_get_save_id", lambda: "save-x")

    class Info(object):
        id = 42

    pa._on_player_action(Info())

    assert local == [42]
    assert sidecar == [{"player_id": "local", "save_id": "save-x", "sim_id": 42}]


def test_on_player_action_skips_without_sim_id(monkeypatch):
    local = []
    from sensewright_mod import tool_executor

    monkeypatch.setattr(tool_executor, "record_player_activity",
                        lambda sim_id=0: local.append(sim_id))

    class Info(object):
        id = 0

    pa._on_player_action(Info())
    assert local == []


def test_on_player_action_never_raises(monkeypatch):
    from sensewright_mod import tool_executor, state_collector

    def boom(sim_id=0):
        raise RuntimeError("rails down")

    monkeypatch.setattr(tool_executor, "record_player_activity", boom)
    monkeypatch.setattr(state_collector, "notify_player_activity", lambda sim: None)
    monkeypatch.setattr(pa, "log_exception", lambda *a, **k: None)

    class Info(object):
        id = 1

    # Must not raise
    pa._on_player_action(Info())


# --- install / hook ---

def _install_fake_game(monkeypatch):
    calls = []

    class Sim(object):
        def push_super_affordance(self, aff, target, context):
            calls.append((aff, target, context))
            return "original-result"

    interactions = _fake_module("interactions")
    context_mod = _fake_module("interactions.context", InteractionSource=_Source)
    sims = _fake_module("sims")
    sim_mod = _fake_module("sims.sim", Sim=Sim)

    monkeypatch.setitem(sys.modules, "interactions", interactions)
    monkeypatch.setitem(sys.modules, "interactions.context", context_mod)
    monkeypatch.setitem(sys.modules, "sims", sims)
    monkeypatch.setitem(sys.modules, "sims.sim", sim_mod)
    return Sim, calls


def test_install_wraps_and_detects_player_push(monkeypatch):
    Sim, calls = _install_fake_game(monkeypatch)
    detected = []
    monkeypatch.setattr(pa, "_on_player_action", lambda info: detected.append(info))

    assert pa.install() is True
    assert pa.is_installed() is True

    sim = Sim()
    sim.sim_info = "INFO"

    result = sim.push_super_affordance("aff", "target", _Context("pie"))

    assert result == "original-result"
    assert len(calls) == 1
    assert detected == ["INFO"]


def test_install_ignores_script_push(monkeypatch):
    Sim, _calls = _install_fake_game(monkeypatch)
    detected = []
    monkeypatch.setattr(pa, "_on_player_action", lambda info: detected.append(info))

    assert pa.install() is True
    sim = Sim()
    sim.sim_info = "INFO"

    sim.push_super_affordance("aff", "target", _Context("script"))

    assert detected == []


def test_install_is_idempotent(monkeypatch):
    Sim, _calls = _install_fake_game(monkeypatch)
    monkeypatch.setattr(pa, "_on_player_action", lambda info: None)

    assert pa.install() is True
    wrapped = Sim.push_super_affordance
    assert pa.install() is True
    assert Sim.push_super_affordance is wrapped


def test_install_false_without_game(monkeypatch):
    monkeypatch.setitem(sys.modules, "sims", _fake_module("sims"))
    monkeypatch.setitem(sys.modules, "sims.sim", _fake_module("sims.sim"))

    assert pa.install() is False
    assert pa.is_installed() is False


def test_hook_swallows_dispatch_errors(monkeypatch):
    Sim, _calls = _install_fake_game(monkeypatch)

    def boom(info):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(pa, "_on_player_action", boom)
    monkeypatch.setattr(pa, "log_exception", lambda *a, **k: None)

    assert pa.install() is True
    sim = Sim()
    sim.sim_info = "INFO"

    # The original push must still run even though dispatch raised.
    assert sim.push_super_affordance("aff", "target", _Context("pie")) == "original-result"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
