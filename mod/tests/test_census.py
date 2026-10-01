"""
Tests for the God census builder, census send and the zone/household hooks.
Fully offline: sim_context internals are mocked; no game, no network.

Run with the system Python (3.10+).
"""

import os
import sys

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

import pytest

from sensewright_mod import http_client, sim_context, state_collector


SAMPLE_SIM = {"player_id": "local", "save_id": "save1", "sim_id": 123}


class FakeHousehold(object):
    def __init__(self, household_id, name, funds):
        self.id = household_id
        self.name = name
        self.funds = funds


class FakeSimInfo(object):
    def __init__(self, sim_id, household, full_name="", age="adult",
                 gender="female", is_selectable=False):
        self.id = sim_id
        self.household = household
        self.full_name = full_name
        self.age = age
        self.gender = gender
        self.is_selectable = is_selectable


def _install_census_fakes(monkeypatch, sims, active=None):
    """Fake the sim list plus the sim_context internals used by build_census."""
    monkeypatch.setattr(state_collector, "_iter_sim_infos",
                        lambda manager=None: list(sims))
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: active)
    monkeypatch.setattr(sim_context, "_get_traits",
                        lambda sim_info: ["Genius", "Cheerful"])
    monkeypatch.setattr(sim_context, "_get_skills",
                        lambda sim_info: {"cooking": 3})
    monkeypatch.setattr(sim_context, "_get_careers",
                        lambda sim_info: [{"name": "Doctor", "level": 4,
                                           "is_active": True}])
    monkeypatch.setattr(sim_context, "_get_relationships",
                        lambda sim_info: [{"target_id": 999, "target_name": "X",
                                           "depth": 42.5, "track": ""}])
    monkeypatch.setattr(sim_context, "_get_kinship",
                        lambda sim_info: [{"relation": "mother", "target_id": 77,
                                           "name": "Mae"}])
    monkeypatch.setattr(sim_context, "_get_aspiration",
                        lambda sim_info: "Soulmate")


def test_build_census_shapes(monkeypatch):
    home = FakeHousehold(10, "Home", 20000)
    sim_a = FakeSimInfo(1, home, full_name="Alice", is_selectable=True)
    sim_b = FakeSimInfo(2, home, full_name="Bob")
    _install_census_fakes(monkeypatch, [sim_a, sim_b], active=sim_a)

    sims, households = state_collector.build_census("full_save")

    assert len(sims) == 2
    sim = sims[0]
    assert set(sim.keys()) == {
        "sim_id", "full_name", "household_id", "aspiration", "traits", "age",
        "gender", "career", "skills", "relationships", "kinship", "is_player",
    }
    assert sim["sim_id"] == 1
    assert sim["full_name"] == "Alice"
    assert sim["household_id"] == 10
    assert sim["aspiration"] == "Soulmate"
    assert sim["traits"] == ["Genius", "Cheerful"]
    assert sim["age"] == "adult"
    assert sim["gender"] == "female"
    assert sim["career"] == "Doctor"
    assert sim["skills"] == {"cooking": 3}
    assert sim["relationships"] == [{"target_id": 999, "target_name": "X", "depth": 42.5}]
    assert sim["kinship"] == [{"relation": "mother", "target_id": 77, "name": "Mae"}]
    assert sim["is_player"] is True
    assert sims[1]["is_player"] is False

    assert households == [{
        "household_id": 10,
        "name": "Home",
        "members": [1, 2],
        "funds": 20000,
    }]


def test_build_census_player_detection_by_household(monkeypatch):
    home = FakeHousehold(10, "Home", 1000)
    other = FakeHousehold(20, "Other", 500)
    own = FakeSimInfo(1, home)
    # No is_selectable attr: fall back to matching the active household.
    del own.is_selectable
    stranger = FakeSimInfo(2, other)
    del stranger.is_selectable
    _install_census_fakes(monkeypatch, [own, stranger], active=own)

    sims, _ = state_collector.build_census("full_save")

    assert sims[0]["is_player"] is True
    assert sims[1]["is_player"] is False


def test_build_census_empty_outside_game(monkeypatch):
    monkeypatch.setattr(state_collector, "_get_sim_info_manager", lambda: None)
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: None)

    assert state_collector.build_census() == ([], [])


def test_build_census_skips_sims_without_id(monkeypatch):
    home = FakeHousehold(10, "Home", 100)

    class Nameless(object):
        id = None
        household = home

    _install_census_fakes(monkeypatch, [Nameless()], active=None)

    sims, households = state_collector.build_census("full_save")
    assert sims == []
    assert households == []


def test_build_census_default_uses_instanced_zone(monkeypatch):
    home = FakeHousehold(10, "Home", 100)
    sim_a = FakeSimInfo(1, home, full_name="Alice", is_selectable=True)
    monkeypatch.setattr(state_collector, "_iter_sim_infos", lambda manager=None: [])
    monkeypatch.setattr(state_collector, "_iter_instanced_sim_infos",
                        lambda manager=None: [sim_a])
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: sim_a)
    monkeypatch.setattr(sim_context, "_get_traits", lambda sim_info: [])
    monkeypatch.setattr(sim_context, "_get_skills", lambda sim_info: {})
    monkeypatch.setattr(sim_context, "_get_careers", lambda sim_info: [])
    monkeypatch.setattr(sim_context, "_get_relationships", lambda sim_info: [])

    sims, households = state_collector.build_census()

    assert [sim["sim_id"] for sim in sims] == [1]
    assert households[0]["members"] == [1]


def test_send_census_payload(monkeypatch):
    captured = {}

    def fake_post(path, payload, timeout=http_client.DEFAULT_TIMEOUT):
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True}

    monkeypatch.setattr(http_client, "post_json", fake_post)

    sims = [{"sim_id": 1}]
    households = [{"household_id": 10}]
    result = state_collector.send_census(
        sim=SAMPLE_SIM, sims=sims, households=households,
        scope="active_zone", lang="en",
    )

    assert result == {"ok": True}
    assert captured["path"] == "/v1/census"
    assert captured["payload"] == {
        "sim": SAMPLE_SIM,
        "scope": "active_zone",
        "sims": sims,
        "households": households,
        "lang": "en",
    }


def test_send_census_builds_when_missing(monkeypatch):
    captured = {}

    def fake_post(path, payload, timeout=http_client.DEFAULT_TIMEOUT):
        captured["path"] = path
        captured["payload"] = payload
        return {"ok": True}

    monkeypatch.setattr(http_client, "post_json", fake_post)
    monkeypatch.setattr(state_collector, "build_census",
                        lambda scope="active_zone": ([{"sim_id": 1}], [{"household_id": 10}]))
    monkeypatch.setattr(state_collector, "_active_sim_ref", lambda: SAMPLE_SIM)

    state_collector.send_census()

    assert captured["payload"]["sim"] == SAMPLE_SIM
    assert captured["payload"]["sims"] == [{"sim_id": 1}]
    assert captured["payload"]["households"] == [{"household_id": 10}]
    assert captured["payload"]["lang"]


def test_send_census_swallows_errors(monkeypatch):
    def boom(path, payload, timeout=http_client.DEFAULT_TIMEOUT):
        raise http_client.SidecarError(500, "boom")

    monkeypatch.setattr(http_client, "post_json", boom)

    assert state_collector.send_census(
        sim=SAMPLE_SIM, sims=[], households=[]) is None


def test_zone_load_triggers_god_and_census(monkeypatch):
    calls = {"god": 0, "census": 0, "scan": 0}
    monkeypatch.setattr(http_client, "send_events", lambda *a, **k: {})
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: object())
    monkeypatch.setattr(state_collector, "_census_ready", lambda: True)
    monkeypatch.setattr(state_collector, "send_autonomy_tick", lambda *a, **k: None)
    monkeypatch.setattr(
        state_collector.god_ui, "maybe_show_zeitgeist_onboarding",
        lambda sim_info: calls.__setitem__("god", calls["god"] + 1) or True,
    )
    monkeypatch.setattr(
        state_collector, "send_census",
        lambda *a, **k: calls.__setitem__("census", calls["census"] + 1),
    )
    monkeypatch.setattr(
        state_collector, "scan_neighborhood",
        lambda *a, **k: calls.__setitem__("scan", calls["scan"] + 1),
    )

    collector = state_collector.StateCollector()
    collector._on_zone_load(zone_id=5)

    assert calls["god"] == 1
    assert calls["census"] == 1
    assert calls["scan"] == 1


def test_zone_load_defers_census_without_live_sim(monkeypatch):
    """A zone-load before any Sim is instanced must not push an empty census."""
    calls = {"census": 0}
    monkeypatch.setattr(http_client, "send_events", lambda *a, **k: {})
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: None)
    monkeypatch.setattr(state_collector, "_census_ready", lambda: False)
    monkeypatch.setattr(state_collector, "send_autonomy_tick", lambda *a, **k: None)
    monkeypatch.setattr(
        state_collector.god_ui, "maybe_show_zeitgeist_onboarding", lambda sim_info: False
    )
    monkeypatch.setattr(state_collector, "scan_neighborhood", lambda *a, **k: None)
    monkeypatch.setattr(
        state_collector, "send_census",
        lambda *a, **k: calls.__setitem__("census", calls["census"] + 1),
    )

    state_collector.StateCollector()._on_zone_load(zone_id=5)

    assert calls["census"] == 0


def test_ensure_started_defers_bootstrap_until_a_sim_is_live(monkeypatch):
    sent = []
    monkeypatch.setattr(state_collector, "send_census", lambda *a, **k: sent.append(1))
    monkeypatch.setattr(state_collector, "_census_ready", lambda: False)

    collector = state_collector.StateCollector()
    collector.start = lambda: True
    collector.is_ready = lambda: True

    assert collector.ensure_started() is True
    assert collector._bootstrapped is False
    assert sent == []


def test_ensure_started_bootstraps_census_when_sim_is_live(monkeypatch):
    sent = []
    monkeypatch.setattr(state_collector, "send_census", lambda *a, **k: sent.append(1))
    monkeypatch.setattr(state_collector, "_census_ready", lambda: True)

    collector = state_collector.StateCollector()
    collector.start = lambda: True
    collector.is_ready = lambda: True

    assert collector.ensure_started() is True
    assert collector._bootstrapped is True
    assert sent == [1]


def test_census_ready_requires_a_live_sim(monkeypatch):
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: None)
    monkeypatch.setattr(state_collector, "_iter_instanced_sim_infos", lambda manager=None: [])
    assert state_collector._census_ready() is False

    monkeypatch.setattr(state_collector, "_iter_instanced_sim_infos",
                        lambda manager=None: [object()])
    assert state_collector._census_ready() is True


def test_scan_neighborhood_sends_full_save_once(monkeypatch):
    captured = []
    monkeypatch.setattr(
        state_collector, "send_census",
        lambda *a, **k: captured.append(k.get("scope")) or {"ok": True, "sims": 3},
    )
    monkeypatch.setattr(state_collector, "_NEIGHBORHOOD_SCAN", {"done": False})

    state_collector.scan_neighborhood()
    state_collector.scan_neighborhood()  # throttled: already scanned this session
    state_collector.scan_neighborhood(force=True)

    assert captured == ["full_save", "full_save"]


def test_household_change_triggers_background(monkeypatch):
    calls = []
    monkeypatch.setattr(http_client, "send_events", lambda *a, **k: {})
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: object())
    monkeypatch.setattr(state_collector, "_census_ready", lambda: True)
    monkeypatch.setattr(state_collector, "build_census", lambda: ([], []))
    monkeypatch.setattr(
        state_collector.god_ui, "prompt_household_background",
        lambda sim_info, household_id=None, census=None:
        calls.append((household_id, census)) or True,
    )

    collector = state_collector.StateCollector()
    collector._on_household_change(household_id=7)

    assert calls
    assert calls[0][0] == 7
    assert calls[0][1] == {"sims": [], "households": []}


def test_household_change_skips_census_without_live_sim(monkeypatch):
    calls = []
    monkeypatch.setattr(http_client, "send_events", lambda *a, **k: {})
    monkeypatch.setattr(sim_context, "_get_active_sim_info", lambda: None)
    monkeypatch.setattr(state_collector, "_census_ready", lambda: False)
    monkeypatch.setattr(
        state_collector.god_ui, "prompt_household_background",
        lambda sim_info, household_id=None, census=None:
        calls.append((household_id, census)) or True,
    )

    state_collector.StateCollector()._on_household_change(household_id=7)

    assert calls[0][1] is None


def test_send_census_logs_generic_failure(monkeypatch):
    """H2: the final generic except is logged, not swallowed."""
    logged = []
    monkeypatch.setattr(state_collector, "log_exception",
                        lambda where, exc: logged.append(where))
    monkeypatch.setattr(state_collector, "build_census",
                        lambda scope="active_zone": ([], []))
    monkeypatch.setattr(state_collector, "_active_sim_ref", lambda: SAMPLE_SIM)

    def boom(*args, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(http_client, "send_census", boom)

    assert state_collector.send_census() is None
    assert logged == ["state_collector.send_census"]


def test_relationships_of_carries_track_progression_and_known_traits(monkeypatch):
    """Phase 2b: track/progression/known traits survive the census compaction."""
    rich = [{
        "target_id": 7,
        "target_name": "Bella",
        "depth": 12.5,
        "track": "Friendship",
        "friendship": 30.0,
        "romance": None,
        "known_traits": ["trait_Cheerful", "trait_Bookworm"],
    }]
    monkeypatch.setattr(sim_context, "_get_relationships", lambda sim_info: rich)

    result = state_collector._relationships_of(object())

    assert result[0]["target_id"] == 7
    assert result[0]["track"] == "Friendship"
    assert result[0]["friendship"] == 30.0
    assert result[0]["known_traits"] == ["trait_Cheerful", "trait_Bookworm"]
    assert "romance" not in result[0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
