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

from sensewright_mod import integrations, sim_context


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


def test_get_traits_prefers_s4cl(monkeypatch):
    class FakeTrait(object):
        __name__ = "trait_Foodie"

    class FakeTraitUtils(object):
        @staticmethod
        def get_traits(sim_info):
            return [FakeTrait()]

        @staticmethod
        def get_trait_name(trait):
            return trait.__name__

    monkeypatch.setattr(integrations, "s4cl_trait_utils", lambda: FakeTraitUtils())

    class FakeInfo(object):
        def get_traits(self):
            return ["native_should_not_be_used"]

    assert sim_context._get_traits(FakeInfo()) == ["trait_Foodie"]


def test_get_traits_falls_back_when_s4cl_raises(monkeypatch):
    class BrokenUtils(object):
        @staticmethod
        def get_traits(sim_info):
            raise RuntimeError("boom")

    monkeypatch.setattr(integrations, "s4cl_trait_utils", lambda: BrokenUtils())

    class FakeInfo(object):
        def get_traits(self):
            return ["trait_Native"]

    assert sim_context._get_traits(FakeInfo()) == ["trait_Native"]


def test_get_careers_prefers_s4cl(monkeypatch):
    class FakeCareer(object):
        __name__ = "career_Astronaut"
        level = 3
        is_active_career = True

    class FakeCareerUtils(object):
        @staticmethod
        def get_all_careers_for_sim_gen(sim_info):
            return iter([FakeCareer()])

    monkeypatch.setattr(integrations, "s4cl_sim_career_utils",
                        lambda: FakeCareerUtils())

    class FakeInfo(object):
        career_tracker = None

    assert sim_context._get_careers(FakeInfo()) == [
        {"name": "career_Astronaut", "level": 3, "is_active": True}
    ]


def test_get_careers_falls_back_when_s4cl_missing(monkeypatch):
    monkeypatch.setattr(integrations, "s4cl_sim_career_utils", lambda: None)

    class FakeTracker(object):
        def careers(self):
            return [_FakeCareer()]

    class FakeInfo(object):
        career_tracker = FakeTracker()

    assert sim_context._get_careers(FakeInfo()) == [
        {"name": "career_TechGuru", "level": 5, "is_active": True}
    ]


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


class _RelMember(object):
    def __init__(self, name):
        self.name = name


_MOTHER = _RelMember("MOTHER")
_FATHER = _RelMember("FATHER")


class _FakeIndex(object):
    def __iter__(self):
        return iter((_MOTHER, _FATHER))


class _FakeManager(object):
    def get(self, sim_id):
        if sim_id == 20:
            return type("Info", (), {"full_name": "Mortimer Goth"})()
        return None


def test_get_kinship_labels_from_enum(monkeypatch):
    monkeypatch.setattr(sim_context, "_genealogy_index_enum", lambda: _FakeIndex())
    monkeypatch.setattr(sim_context, "_get_sim_info_manager", lambda: _FakeManager())

    class FakeInfo(object):
        id = 10

        def get_relations(self, member):
            return {20} if member is _MOTHER else set()

    assert sim_context._get_kinship(FakeInfo()) == [
        {"relation": "mother", "target_id": 20, "name": "Mortimer Goth"}
    ]


def test_get_kinship_prefers_genealogy_tracker(monkeypatch):
    monkeypatch.setattr(sim_context, "_genealogy_index_enum", lambda: _FakeIndex())
    monkeypatch.setattr(sim_context, "_get_sim_info_manager", lambda: None)

    class Genealogy(object):
        def get_relations(self, member):
            return {20} if member is _FATHER else set()

    class FakeInfo(object):
        id = 10
        genealogy = Genealogy()

    assert sim_context._get_kinship(FakeInfo()) == [
        {"relation": "father", "target_id": 20, "name": ""}
    ]


def test_get_kinship_falls_back_to_family_ids(monkeypatch):
    monkeypatch.setattr(sim_context, "_genealogy_index_enum", lambda: None)
    monkeypatch.setattr(sim_context, "_get_sim_info_manager", lambda: None)

    class FakeInfo(object):
        id = 10

        def get_family_sim_ids_gen(self, include_self=False):
            return iter([11, 10])

    assert sim_context._get_kinship(FakeInfo()) == [
        {"relation": "family", "target_id": 11, "name": ""}
    ]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
