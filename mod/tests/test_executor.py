"""
Tests for the mod-side tool executor and its rails integration.
Fully offline: no game imports, no network. `services` is never available, so
game tools must degrade to not_implemented unless helper functions are faked.

Run with the system Python (3.10+).
"""

import os
import sys
import types

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest
from sensewright_mod import tool_executor as ex


def _fake_module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


@pytest.fixture(autouse=True)
def _reset_rails():
    ex.get_rails().reset()
    yield
    ex.get_rails().reset()


# --- Fakes for the "game present" path ---

class FakeQueue(object):
    def __init__(self):
        self.pushed = []
        self.cancelled = False

    def push_super_affordance(self, affordance, target, target_context):
        self.pushed.append((affordance, target, target_context))

    def cancel_all(self):
        self.cancelled = True


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
        self.traits = []
        self.instance = FakeSimInstance()

    def add_buff(self, name):
        self.buffs.append(name)

    def add_trait(self, trait):
        self.traits.append(trait)

    def get_sim_instance(self):
        return self.instance


def _install_fake(monkeypatch):
    """Make the game look available and return one fake SimInfo."""
    fake = FakeSimInfo()
    monkeypatch.setattr(ex, "_get_services", lambda: object())
    monkeypatch.setattr(ex, "_get_target_sim", lambda sim_id=0: fake)
    return fake


# --- Registry ---

def test_registry_contains_actions():
    assert "add_buff" in ex._TOOL_REGISTRY
    assert "add_trait" in ex._TOOL_REGISTRY
    assert "queue_interaction" in ex._TOOL_REGISTRY
    assert "move_to" in ex._TOOL_REGISTRY
    assert "say_to" in ex._TOOL_REGISTRY
    assert "cancel_current" in ex._TOOL_REGISTRY


def test_get_rails_returns_singleton():
    assert ex.get_rails() is ex._rails


# --- Rails integration ---

def test_rails_denial_short_circuits_execution(monkeypatch):
    calls = []

    def fake_tool(args):
        calls.append(args)
        return {"ok": True, "result": "ran"}

    monkeypatch.setitem(ex._TOOL_REGISTRY, "add_buff", fake_tool)
    monkeypatch.setattr(ex, "post_json", lambda path, payload: {})

    ex.get_rails().record_player_activity(7)
    result = ex.execute({"id": "c1", "name": "add_buff", "args": {"sim_id": 7, "buff_name": "Happy"}})

    assert result == {"ok": False, "error": "player_priority"}
    assert calls == []


def test_never_tool_denied_before_lookup(monkeypatch):
    calls = []

    def fake_tool(args):
        calls.append(args)
        return {"ok": True}

    monkeypatch.setitem(ex._TOOL_REGISTRY, "kill_sim", fake_tool)
    result = ex.execute({"id": "", "name": "kill_sim", "args": {"sim_id": 1}})

    assert result == {"ok": False, "error": "never_tool"}
    assert calls == []


def test_denied_still_posts_result(monkeypatch):
    posts = []
    monkeypatch.setattr(ex, "post_json", lambda path, payload: posts.append((path, payload)))

    ex.get_rails().record_player_activity(8)
    ex.execute({"id": "d1", "name": "add_buff", "args": {"sim_id": 8}})

    assert len(posts) == 1
    assert posts[0][0] == "/v1/tools/result"
    assert posts[0][1]["error"] == "player_priority"


def test_denied_does_not_note_executed(monkeypatch):
    monkeypatch.setattr(ex, "post_json", lambda path, payload: {})
    ex.get_rails().record_player_activity(5)

    ex.execute({"id": "", "name": "add_buff", "args": {"sim_id": 5, "buff_name": "X"}})

    assert ex.get_rails().snapshot()["sims"]["5"]["executed_in_window"] == 0


def test_allowed_notes_executed(monkeypatch):
    monkeypatch.setattr(ex, "post_json", lambda path, payload: {})
    _install_fake(monkeypatch)

    ex.execute({"id": "", "name": "add_buff", "args": {"sim_id": 5, "buff_name": "X"}})

    assert ex.get_rails().snapshot()["sims"]["5"]["executed_in_window"] == 1


def test_unknown_tool(monkeypatch):
    monkeypatch.setattr(ex, "post_json", lambda path, payload: {})
    result = ex.execute({"name": "no_such_tool", "args": {"sim_id": 1}})

    assert result == {"ok": False, "error": "unknown_tool"}


# --- Posting and batching ---

def test_execute_posts_result(monkeypatch):
    posts = []
    monkeypatch.setattr(ex, "post_json", lambda path, payload: posts.append((path, payload)))
    _install_fake(monkeypatch)

    result = ex.execute({"id": "c9", "name": "add_buff", "args": {"sim_id": 3, "buff_name": "Happy"}})

    assert result["ok"] is True
    assert len(posts) == 1
    path, payload = posts[0]
    assert path == "/v1/tools/result"
    assert payload["tool_call_id"] == "c9"
    assert payload["ok"] is True
    assert payload["result"] == {"buff": "Happy"}


def test_execute_batch_runs_all(monkeypatch):
    monkeypatch.setattr(ex, "post_json", lambda path, payload: {})
    seen = []

    def make(name):
        def runner(args):
            seen.append(name)
            return {"ok": True, "result": name}
        return runner

    monkeypatch.setitem(ex._TOOL_REGISTRY, "add_buff", make("add_buff"))
    monkeypatch.setitem(ex._TOOL_REGISTRY, "add_trait", make("add_trait"))

    results = ex.execute_batch([
        {"id": "1", "name": "add_buff", "args": {"sim_id": 11}},
        {"id": "2", "name": "add_trait", "args": {"sim_id": 11}},
    ])

    assert len(results) == 2
    assert all(r["ok"] for r in results)
    assert seen == ["add_buff", "add_trait"]


# --- Missing game -> not_implemented ---

def test_game_tools_not_implemented_without_game(monkeypatch):
    monkeypatch.setattr(ex, "_get_services", lambda: None)

    assert ex.tool_add_buff({})["error"] == "not_implemented"
    assert ex.tool_add_trait({})["error"] == "not_implemented"
    assert ex.tool_queue_interaction({})["error"] == "not_implemented"
    assert ex.tool_move_to({})["error"] == "not_implemented"
    assert ex.tool_say_to({})["error"] == "not_implemented"
    assert ex.tool_cancel_current({})["error"] == "not_implemented"


# --- Fake sim -> ok ---

def test_add_buff_ok(monkeypatch):
    fake = _install_fake(monkeypatch)
    result = ex.tool_add_buff({"sim_id": 1, "buff_name": "Happy"})

    assert result == {"ok": True, "result": {"buff": "Happy"}}
    assert fake.buffs == ["Happy"]


def test_add_buff_missing_argument(monkeypatch):
    _install_fake(monkeypatch)
    result = ex.tool_add_buff({"sim_id": 1})

    assert result["ok"] is False
    assert result["error"] == "missing_argument"


def test_add_trait_ok(monkeypatch):
    fake = _install_fake(monkeypatch)
    monkeypatch.setattr(ex, "_resolve_trait", lambda name: "trait:" + name)

    result = ex.tool_add_trait({"sim_id": 1, "trait_name": "Genius"})

    assert result == {"ok": True, "result": {"trait": "Genius"}}
    assert fake.traits == ["trait:Genius"]


def test_queue_interaction_ok(monkeypatch):
    fake = _install_fake(monkeypatch)
    monkeypatch.setattr(ex, "_resolve_affordance", lambda args: "affordance")

    result = ex.tool_queue_interaction({"sim_id": 1, "target_sim_id": 2, "interaction_name": "chat"})

    assert result["ok"] is True
    assert len(fake.instance.queue.pushed) == 1


def test_move_to_ok(monkeypatch):
    fake = _install_fake(monkeypatch)
    result = ex.tool_move_to({"sim_id": 1, "x": 5.0, "y": 6.0, "z": 0.0})

    assert result["ok"] is True
    assert fake.instance.routed == [(5.0, 6.0, 0.0)]


def test_say_to_ok(monkeypatch):
    fake = _install_fake(monkeypatch)
    monkeypatch.setattr(ex, "_resolve_affordance", lambda args: "social")

    result = ex.tool_say_to({"sim_id": 1, "target_sim_id": 2, "interaction_name": "chat"})

    assert result["ok"] is True
    assert len(fake.instance.queue.pushed) == 1


def test_cancel_current_ok(monkeypatch):
    fake = _install_fake(monkeypatch)
    result = ex.tool_cancel_current({"sim_id": 1})

    assert result["ok"] is True
    assert fake.instance.queue.cancelled is True


def test_get_world_time_ok_outside_game():
    result = ex.tool_get_world_time({})

    assert result["ok"] is True
    assert "clock" in result["result"]


# --- get_inventory tests ---

class FakeItemDefinition(object):
    __name__ = "object_Apple"


class FakeItem(object):
    definition = FakeItemDefinition()


class FakeInventory(object):
    def get_items(self):
        return [FakeItem()]


class FakeSimInstanceWithInventory(FakeSimInstance):
    def __init__(self):
        super(FakeSimInstanceWithInventory, self).__init__()
        self.inventory = FakeInventory()


class FakeSimInfoWithInventory(FakeSimInfo):
    def __init__(self):
        super(FakeSimInfoWithInventory, self).__init__()
        self.instance = FakeSimInstanceWithInventory()

    def get_sim_instance(self):
        return self.instance


def _install_fake_with_inventory(monkeypatch):
    fake = FakeSimInfoWithInventory()
    monkeypatch.setattr(ex, "_get_services", lambda: object())
    monkeypatch.setattr(ex, "_get_target_sim", lambda sim_id=0: fake)
    return fake


def test_get_inventory_not_implemented_without_game(monkeypatch):
    monkeypatch.setattr(ex, "_get_services", lambda: None)
    result = ex.tool_get_inventory({"sim_id": 1})
    assert result["ok"] is False
    assert result["error"] == "sim_not_found"


def test_get_inventory_empty_when_no_instance(monkeypatch):
    class FakeSimInfoNoInstance(FakeSimInfo):
        def get_sim_instance(self):
            return None

    fake = FakeSimInfoNoInstance()
    monkeypatch.setattr(ex, "_get_services", lambda: object())
    monkeypatch.setattr(ex, "_get_target_sim", lambda sim_id=0: fake)

    result = ex.tool_get_inventory({"sim_id": 1})
    assert result["ok"] is True
    assert result["result"] == {"items": []}


def test_get_inventory_reads_items_from_inventory_component(monkeypatch):
    _install_fake_with_inventory(monkeypatch)
    result = ex.tool_get_inventory({"sim_id": 1})
    assert result["ok"] is True
    assert result["result"]["items"] == ["object_Apple"]


def test_get_inventory_falls_back_to_get_inventory_method(monkeypatch):
    class FakeItem2(object):
        __name__ = "object_Book"

    class FakeSimInstanceWithGetInventory(FakeSimInstance):
        def get_inventory(self):
            return [FakeItem2()]

    class FakeSimInfoWithGetInventory(FakeSimInfo):
        def __init__(self):
            super(FakeSimInfoWithGetInventory, self).__init__()
            self.instance = FakeSimInstanceWithGetInventory()

        def get_sim_instance(self):
            return self.instance

    fake = FakeSimInfoWithGetInventory()
    monkeypatch.setattr(ex, "_get_services", lambda: object())
    monkeypatch.setattr(ex, "_get_target_sim", lambda sim_id=0: fake)

    result = ex.tool_get_inventory({"sim_id": 1})
    assert result["ok"] is True
    assert result["result"]["items"] == ["object_Book"]


def test_get_inventory_handles_items_without_definition(monkeypatch):
    class FakeItemNoDef(object):
        __name__ = "object_Cookie"

    class FakeInventoryNoDef(object):
        def get_items(self):
            return [FakeItemNoDef()]

    class FakeSimInstanceNoDef(FakeSimInstance):
        def __init__(self):
            super(FakeSimInstanceNoDef, self).__init__()
            self.inventory = FakeInventoryNoDef()

    class FakeSimInfoNoDef(FakeSimInfo):
        def __init__(self):
            super(FakeSimInfoNoDef, self).__init__()
            self.instance = FakeSimInstanceNoDef()

        def get_sim_instance(self):
            return self.instance

    fake = FakeSimInfoNoDef()
    monkeypatch.setattr(ex, "_get_services", lambda: object())
    monkeypatch.setattr(ex, "_get_target_sim", lambda sim_id=0: fake)

    result = ex.tool_get_inventory({"sim_id": 1})
    assert result["ok"] is True
    assert result["result"]["items"] == ["object_Cookie"]


# --- H6: per-key argument type validation ---

def test_invalid_sim_id_returns_invalid_argument():
    result = ex.tool_get_needs({"sim_id": "abc"})

    assert result == {"ok": False, "error": "invalid_argument", "detail": "sim_id"}


def test_numeric_string_sim_id_still_works(monkeypatch):
    fake = _install_fake(monkeypatch)

    result = ex.tool_add_buff({"sim_id": "1", "buff_name": "Happy"})

    assert result == {"ok": True, "result": {"buff": "Happy"}}
    assert fake.buffs == ["Happy"]


def test_invalid_target_sim_id_returns_invalid_argument(monkeypatch):
    _install_fake(monkeypatch)

    result = ex.tool_say_to({"sim_id": 1, "target_sim_id": "nope"})

    assert result == {"ok": False, "error": "invalid_argument", "detail": "target_sim_id"}


def test_invalid_target_object_id_returns_invalid_argument(monkeypatch):
    _install_fake(monkeypatch)
    monkeypatch.setattr(ex, "_resolve_affordance", lambda args: "affordance")

    result = ex.tool_queue_interaction({"sim_id": 1, "target_object_id": [1]})

    assert result == {"ok": False, "error": "invalid_argument", "detail": "target_object_id"}


def test_non_string_tone_returns_invalid_argument(monkeypatch):
    _install_fake(monkeypatch)
    monkeypatch.setattr(ex, "_resolve_affordance", lambda args: "affordance")

    result = ex.tool_say_to({"sim_id": 1, "target_sim_id": 2, "tone": 123})

    assert result == {"ok": False, "error": "invalid_argument", "detail": "tone"}


def test_as_int_accepts_int_and_numeric_str():
    assert ex._as_int(5) == 5
    assert ex._as_int("5") == 5
    assert ex._as_int("  7 ") == 7
    assert ex._as_int("abc") is None
    assert ex._as_int(1.0) == 1  # integral float from JSON round-trip
    assert ex._as_int(1.5) is None
    assert ex._as_int(True) is None
    assert ex._as_int(None) is None


def test_as_str_accepts_only_real_strings():
    assert ex._as_str("hi") == "hi"
    assert ex._as_str(5) is None
    assert ex._as_str(None) is None


def test_validated_id_defaults_for_absent_key():
    assert ex._validated_id({}, "sim_id", 0) == (0, None)
    assert ex._validated_id({"sim_id": None}, "sim_id", 0) == (0, None)
    assert ex._validated_id({"sim_id": 3}, "sim_id", 0) == (3, None)
    value, error = ex._validated_id({"sim_id": "x"}, "sim_id", 0)
    assert value is None
    assert error == {"ok": False, "error": "invalid_argument", "detail": "sim_id"}


# --- L2: note_executed failures are logged ---

def test_note_executed_error_is_logged(monkeypatch):
    logged = []
    monkeypatch.setattr(ex, "post_json", lambda *a, **k: {})
    monkeypatch.setattr(ex, "log_exception", lambda where, exc: logged.append(where))
    _install_fake(monkeypatch)

    def boom(sim_id, tool_name):
        raise RuntimeError("rails down")

    monkeypatch.setattr(ex._rails, "note_executed", boom)

    result = ex.execute({"id": "x", "name": "add_buff",
                         "args": {"sim_id": 1, "buff_name": "Happy"}})

    assert result["ok"] is True
    assert any("execute.note_executed" in where for where in logged)


def test_execute_intent_note_executed_error_is_logged(monkeypatch):
    logged = []
    monkeypatch.setattr(ex, "post_json", lambda *a, **k: {})
    monkeypatch.setattr(ex, "log_exception", lambda where, exc: logged.append(where))

    def boom(sim_id, tool_name):
        raise RuntimeError("rails down")

    monkeypatch.setattr(ex._rails, "note_executed", boom)

    result = ex.execute_intent({"sim_id": 1, "kind": "prefer_target"})

    assert result["ok"] is True
    assert any("execute_intent.note_executed" in where for where in logged)


# --- record_player_activity (SA4 helper) ---

def test_record_player_activity_arms_lock(monkeypatch):
    class Info(object):
        id = 42

    monkeypatch.setattr(ex, "_get_target_sim", lambda sim_id=0: Info())
    ex.get_rails().reset()

    resolved = ex.record_player_activity(42)

    assert resolved == 42
    assert ex.get_rails().check(42, "add_buff").reason == "player_priority"


def test_record_player_activity_falls_back_to_sim_id(monkeypatch):
    monkeypatch.setattr(ex, "_get_target_sim", lambda sim_id=0: None)
    ex.get_rails().reset()

    assert ex.record_player_activity(7) == 7
    assert ex.get_rails().check(7, "add_buff").reason == "player_priority"


def test_record_player_activity_never_raises(monkeypatch):
    def boom(sim_id=0):
        raise RuntimeError("no services")

    monkeypatch.setattr(ex, "_get_target_sim", boom)

    assert ex.record_player_activity(1) == 0


# --- R1: multi-path native interaction API hardening ---

def test_build_interaction_context_three_arg_signature(monkeypatch):
    calls = []

    class InteractionContext(object):
        SOURCE_SCRIPT = "source_script"

        def __init__(self, *args):
            calls.append(args)

    class Priority(object):
        High = "high"

    monkeypatch.setitem(sys.modules, "interactions", _fake_module("interactions"))
    monkeypatch.setitem(sys.modules, "interactions.context",
                        _fake_module("interactions.context",
                                     InteractionContext=InteractionContext))
    monkeypatch.setitem(sys.modules, "interactions.priority",
                        _fake_module("interactions.priority", Priority=Priority))

    sim = object()
    result = ex._build_interaction_context(sim)

    assert isinstance(result, InteractionContext)
    assert calls == [(sim, "source_script", "high")]


def test_build_interaction_context_two_arg_fallback(monkeypatch):
    calls = []

    class InteractionContext(object):
        SOURCE_SCRIPT = "source_script"

        def __init__(self, *args):
            if len(args) == 3:
                raise TypeError("three-arg unsupported")
            calls.append(args)

    class Priority(object):
        High = "high"

    monkeypatch.setitem(sys.modules, "interactions", _fake_module("interactions"))
    monkeypatch.setitem(sys.modules, "interactions.context",
                        _fake_module("interactions.context",
                                     InteractionContext=InteractionContext))
    monkeypatch.setitem(sys.modules, "interactions.priority",
                        _fake_module("interactions.priority", Priority=Priority))

    sim = object()
    result = ex._build_interaction_context(sim)

    assert isinstance(result, InteractionContext)
    assert calls == [(sim, "high")]


def test_build_interaction_context_one_arg_fallback(monkeypatch):
    calls = []

    class InteractionContext(object):
        SOURCE_SCRIPT = "source_script"

        def __init__(self, *args):
            calls.append(args)

    monkeypatch.setitem(sys.modules, "interactions", _fake_module("interactions"))
    monkeypatch.setitem(sys.modules, "interactions.context",
                        _fake_module("interactions.context",
                                     InteractionContext=InteractionContext))
    monkeypatch.setattr(ex, "_PRIORITY_MODULES", ("sensewright_nope.priority",))

    sim = object()
    result = ex._build_interaction_context(sim)

    assert isinstance(result, InteractionContext)
    assert calls == [(sim,)]


def test_build_interaction_context_uses_interaction_priority_module(monkeypatch):
    calls = []

    class InteractionContext(object):
        SOURCE_SCRIPT = "src"

        def __init__(self, *args):
            calls.append(args)

    class Priority(object):
        High = "high"

    monkeypatch.setitem(sys.modules, "interactions", _fake_module("interactions"))
    monkeypatch.setitem(sys.modules, "interactions.context",
                        _fake_module("interactions.context",
                                     InteractionContext=InteractionContext))
    monkeypatch.setitem(sys.modules, "interactions.interaction_priority",
                        _fake_module("interactions.interaction_priority",
                                     Priority=Priority))
    monkeypatch.setattr(ex, "_PRIORITY_MODULES", ("interactions.interaction_priority",))

    sim = object()
    ex._build_interaction_context(sim)

    assert calls == [(sim, "src", "high")]


def test_build_interaction_context_returns_none_without_module(monkeypatch):
    monkeypatch.setattr(ex, "_INTERACTION_CONTEXT_MODULES",
                        ("sensewright_nope.interactions.context",))

    assert ex._build_interaction_context(object()) is None


def test_build_interaction_context_passthrough():
    sentinel = object()
    assert ex._build_interaction_context(object(), target_context=sentinel) is sentinel


def test_social_affordance_candidates_present():
    assert "sim-chat" in ex._SOCIAL_AFFORDANCE_CANDIDATES
    assert "Chat" in ex._SOCIAL_AFFORDANCE_CANDIDATES


def test_say_to_tries_social_candidates(monkeypatch):
    _install_fake(monkeypatch)
    tried = []

    def fake_resolve(args):
        name = args.get("interaction_name")
        tried.append(name)
        return "affordance" if name == "social-chat" else None

    monkeypatch.setattr(ex, "_resolve_affordance", fake_resolve)

    result = ex.tool_say_to({"sim_id": 1, "target_sim_id": 2, "tone": "friendly"})

    assert result["ok"] is True
    assert "sim-chat" in tried
    assert "social-chat" in tried


def test_resolve_affordance_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(ex, "_get_services", lambda: object())

    assert ex._resolve_affordance({}) is None
    assert ex._resolve_affordance({"interaction_name": None}) is None


def test_resolve_affordance_uses_canonical_key(monkeypatch):
    got = []

    class Manager(object):
        def get(self, key):
            got.append(key)
            return "aff:" + str(key)

    services = types.SimpleNamespace(get_instance_manager=lambda types_arg: Manager())
    monkeypatch.setattr(ex, "_get_services", lambda: services)
    resources_mod = _fake_module(
        "sims4.resources", Types=types.SimpleNamespace(INTERACTION="interaction"))
    monkeypatch.setitem(sys.modules, "sims4",
                        _fake_module("sims4", resources=resources_mod))
    monkeypatch.setitem(sys.modules, "sims4.resources", resources_mod)

    assert ex._resolve_affordance({"interaction_name": "sim-chat"}) == "aff:sim-chat"
    assert got == ["sim-chat"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
