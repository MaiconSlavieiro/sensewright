"""Tests for the v0.4 P3 PresencePolicy (``agent.presence``)."""

from __future__ import annotations

from sensewright_sidecar.agent.presence import (
    TIER_FULL,
    TIER_OFF,
    TIER_REACTIVE,
    PresencePolicy,
    distance_between,
    location_xy,
)
from sensewright_sidecar.config import AgentsConfig, PresenceConfig, Settings


def _sim(sim_id, *, is_player=False, household_id=None, location="", rels=None):
    return {
        "sim_id": sim_id,
        "is_player": is_player,
        "household_id": household_id,
        "location": location,
        "relationships": rels or [],
    }


def test_household_is_full_and_visitor_reactive():
    policy = PresencePolicy()
    home = _sim(1, is_player=True, household_id=100)
    visitor = _sim(2, household_id=200)
    assert policy.tier(home, player_household_id=100) == TIER_FULL
    assert policy.tier(visitor, player_household_id=100) == TIER_REACTIVE
    assert policy.allows_idle(home, player_household_id=100) is True
    assert policy.allows_idle(visitor, player_household_id=100) is False


def test_household_member_by_household_id_is_full():
    policy = PresencePolicy()
    member = _sim(3, household_id=100)
    assert policy.tier(member, player_household_id=100) == TIER_FULL


def test_visitor_off_and_full_config():
    off = PresencePolicy(Settings(agents=AgentsConfig(presence=PresenceConfig(visitor="off"))))
    assert off.tier(_sim(2, household_id=200), player_household_id=100) == TIER_OFF

    full = PresencePolicy(Settings(agents=AgentsConfig(presence=PresenceConfig(visitor="full"))))
    assert full.tier(_sim(2, household_id=200), player_household_id=100) == TIER_FULL


def test_familiar_from_relationship_type_and_friendship():
    policy = PresencePolicy(
        Settings(agents=AgentsConfig(presence=PresenceConfig(familiar_friendship=20.0)))
    )
    assert policy.is_familiar(_sim(2, rels=[{"type": "friend"}])) is True
    assert policy.is_familiar(_sim(2, rels=[{"friendship": 30.0}])) is True
    assert policy.is_familiar(_sim(2, rels=[{"friendship": 1.0}])) is False
    assert policy.is_familiar(_sim(2)) is False


def test_context_line_home_vs_visiting():
    policy = PresencePolicy()
    home = _sim(1, is_player=True, household_id=100)
    line_home = policy.context_line(
        home, lang="pt-BR", player_household_id=100, household_name="Silva"
    )
    assert "Silva" in line_home

    visitor = _sim(2, household_id=200, location="1.0,2.0")
    line_visit = policy.context_line(visitor, lang="pt-BR", player_household_id=100)
    assert "visitando" in line_visit


def test_location_and_distance_helpers():
    a = _sim(1, location="0.0,0.0")
    b = _sim(2, location="3.0,4.0")
    assert location_xy(a) == (0.0, 0.0)
    assert location_xy(_sim(3, location="")) is None
    assert distance_between(a, b) == 5.0
    assert distance_between(a, _sim(4, location="")) is None


def test_nearby_filters_by_radius():
    center = _sim(1, location="0.0,0.0")
    near = _sim(2, location="1.0,1.0")
    far = _sim(3, location="50.0,50.0")
    result = PresencePolicy.nearby(center, [center, near, far], radius=5.0)
    assert [s["sim_id"] for s in result] == [2]
    assert len(PresencePolicy.nearby(center, [center, near, far])) == 2
