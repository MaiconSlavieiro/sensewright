"""
Tests for sim_context primitive coercion (review item 5 support).
Fully offline: no game imports, no network.

Run with the system Python (3.10+).
"""

import os
import sys

# Add mod directory to path
mod_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, mod_dir)

from sensewright_mod import sim_context


class _LocalizedLike(object):
    """Stands in for a LocalizedString: no ``__name__``, meaningful ``str``."""

    def __str__(self):
        return "Bella Goth"


class _TuningLike(object):
    __name__ = "buff_Sleeping"


def test_as_str_prefers_tuning_name():
    assert sim_context._as_str(_TuningLike()) == "buff_Sleeping"
    assert sim_context._as_str("plain") == "plain"
    assert sim_context._as_str(None) == ""


def test_as_str_falls_back_to_str():
    assert sim_context._as_str(_LocalizedLike()) == "Bella Goth"


def test_collect_coerces_full_name_to_primitive():
    class FakeInfo(object):
        id = 7
        full_name = _LocalizedLike()

    context = sim_context.collect(FakeInfo())

    assert context["full_name"] == "Bella Goth"
    assert context["sim_id"] == 7
    assert isinstance(context["full_name"], str)


def test_get_traits_prefers_siminfo_get_traits():
    class FakeInfo(object):
        def get_traits(self):
            return ["trait_Foodie"]

    assert sim_context._get_traits(FakeInfo()) == ["trait_Foodie"]


def test_get_traits_reads_equipped_traits():
    class FakeTrait(object):
        __name__ = "trait_Ambitious"

    class FakeTracker(object):
        equipped_traits = [FakeTrait(), FakeTrait()]

    class FakeInfo(object):
        trait_tracker = FakeTracker()

    assert sim_context._get_traits(FakeInfo()) == ["trait_Ambitious", "trait_Ambitious"]


def test_get_relationships_uses_target_infos():
    class FakeTarget(object):
        sim_id = 42
        full_name = "Bella Goth"

    class FakeTracker(object):
        def get_target_sim_infos(self):
            return [FakeTarget()]

        def get_relationship_depth(self, sim_id):
            return 0.75

    class FakeInfo(object):
        relationship_tracker = FakeTracker()

    assert sim_context._get_relationships(FakeInfo()) == [
        {"target_id": 42, "target_name": "Bella Goth", "depth": 0.75, "track": ""}
    ]


def test_get_time_string_calls_clock_accessor(monkeypatch):
    import types

    class FakeClock(object):
        def now(self):
            return "day-1-8am"

    fake_services = types.SimpleNamespace(game_clock_service=lambda: FakeClock())
    monkeypatch.setattr(sim_context, "_get_services", lambda: fake_services)

    assert sim_context._get_time_string() == "day-1-8am"


def test_get_mood_calls_get_mood():
    class FakeInfo(object):
        def get_mood(self):
            return "Happy"

    assert sim_context._get_mood(FakeInfo()) == "Happy"


def test_get_active_sim_info_calls_accessor(monkeypatch):
    import types

    class FakeClient(object):
        active_sim_info = "SIM"

    class FakeManager(object):
        def get_first_client(self):
            return FakeClient()

    fake_services = types.SimpleNamespace(client_manager=lambda: FakeManager())
    monkeypatch.setattr(sim_context, "_get_services", lambda: fake_services)

    assert sim_context._get_active_sim_info() == "SIM"


def test_get_save_id_prefers_persistence_guid(monkeypatch):
    import types

    class FakePersistence(object):
        def get_save_slot_proto_guid(self):
            return 123456

    fake_services = types.SimpleNamespace(get_persistence_service=lambda: FakePersistence())
    monkeypatch.setattr(sim_context, "_get_services", lambda: fake_services)

    assert sim_context._get_save_id() == "123456"


def test_get_save_id_skips_zero(monkeypatch):
    import types

    class FakePersistence(object):
        def get_save_slot_proto_guid(self):
            return 0

    class FakeZone(object):
        save_slot_data_id = 999

    fake_services = types.SimpleNamespace(
        get_persistence_service=lambda: FakePersistence(),
        current_zone=lambda: FakeZone(),
    )
    monkeypatch.setattr(sim_context, "_get_services", lambda: fake_services)

    assert sim_context._get_save_id() == "999"


class _FakeCareerType(object):
    __name__ = "career_Astronaut"


class _FakeCareer(object):
    __name__ = "career_TechGuru"
    level = 5
    is_active_career = True


class _NumericCareer(object):
    career_type = _FakeCareerType()

    def __str__(self):
        return "12345"


def test_career_display_name_prefers_tuning_name():
    assert sim_context._career_display_name(_FakeCareer()) == "career_TechGuru"


def test_career_display_name_falls_back_to_career_type():
    assert sim_context._career_display_name(_NumericCareer()) == "career_Astronaut"


def test_get_careers_is_primitive_only():
    class FakeTracker(object):
        def careers(self):
            return [_FakeCareer()]

    class FakeInfo(object):
        career_tracker = FakeTracker()

    careers = sim_context._get_careers(FakeInfo())
    assert careers == [{"name": "career_TechGuru", "level": 5, "is_active": True}]
    for entry in careers:
        for value in entry.values():
            assert isinstance(value, (str, int, float, bool))


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
