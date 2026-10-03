"""Tests for sensewright_sidecar.god.background_scheduler."""
from __future__ import annotations

import pytest

from sensewright_sidecar.god.background_scheduler import (
    PRIORITY_ORDER,
    priority_class,
    select_targets,
)


class FakeState:
    """Lightweight fake state exposing census_items()."""

    def __init__(self, census: list[tuple[int, dict]]):
        self._census = census

    def census_items(self) -> list[tuple[int, dict]]:
        return [(sid, dict(sim)) for sid, sim in self._census]


def test_priority_order_constant():
    assert PRIORITY_ORDER == ("PLAYER", "HOUSEHOLD", "ACTIVE", "RELATED", "OTHER")


def test_priority_class_player_beats_all():
    """PLAYER priority beats everything else."""
    census = [
        (1, {"sim_id": 1, "is_player": True, "household_id": 10}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 10}),
    ]
    state = FakeState(census)

    player_sim = {"sim_id": 1, "is_player": True, "household_id": 10}
    assert priority_class(state, player_sim, active_sim_id=2) == "PLAYER"


def test_priority_class_active_above_related():
    """ACTIVE sim is ranked above RELATED."""
    census = [
        (1, {"sim_id": 1, "is_player": False, "household_id": 10, "family_links": [2]}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 20, "family_links": [1]}),
    ]
    state = FakeState(census)

    # Sim 2 is the active sim
    active_sim = {"sim_id": 2, "is_player": False, "household_id": 20, "family_links": [1]}
    assert priority_class(state, active_sim, active_sim_id=2) == "ACTIVE"

    # Sim 1 is related to active sim (family_links contains 2)
    related_sim = {"sim_id": 1, "is_player": False, "household_id": 10, "family_links": [2]}
    assert priority_class(state, related_sim, active_sim_id=2) == "RELATED"


def test_priority_class_household_via_active():
    """HOUSEHOLD via shared household with active sim."""
    census = [
        (1, {"sim_id": 1, "is_player": False, "household_id": 10}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 10}),
    ]
    state = FakeState(census)

    # Sim 1 shares household with active sim (2)
    sim1 = {"sim_id": 1, "is_player": False, "household_id": 10}
    assert priority_class(state, sim1, active_sim_id=2) == "HOUSEHOLD"


def test_priority_class_household_via_player():
    """HOUSEHOLD via shared household with any player sim."""
    census = [
        (1, {"sim_id": 1, "is_player": True, "household_id": 10}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 10}),
        (3, {"sim_id": 3, "is_player": False, "household_id": 20}),
    ]
    state = FakeState(census)

    # Sim 2 shares household with player sim 1
    sim2 = {"sim_id": 2, "is_player": False, "household_id": 10}
    assert priority_class(state, sim2, active_sim_id=3) == "HOUSEHOLD"

    # Sim 3 has different household, no player link
    sim3 = {"sim_id": 3, "is_player": False, "household_id": 20}
    assert priority_class(state, sim3, active_sim_id=3) == "ACTIVE"  # sim3 IS active


def test_priority_class_related_via_family_links():
    """RELATED via family_links intersection with player/active."""
    census = [
        (1, {"sim_id": 1, "is_player": True, "household_id": 10, "family_links": [2]}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 20, "family_links": [1]}),
        (3, {"sim_id": 3, "is_player": False, "household_id": 30, "family_links": []}),
    ]
    state = FakeState(census)

    # Sim 2 has family_links to player sim 1
    sim2 = {"sim_id": 2, "is_player": False, "household_id": 20, "family_links": [1]}
    assert priority_class(state, sim2, active_sim_id=3) == "RELATED"

    # Sim 3 has no family links to player/active
    sim3 = {"sim_id": 3, "is_player": False, "household_id": 30, "family_links": []}
    assert priority_class(state, sim3, active_sim_id=3) == "ACTIVE"


def test_priority_class_related_reverse_lookup():
    """RELATED when player/active sim has this sim in their family_links."""
    census = [
        (1, {"sim_id": 1, "is_player": True, "household_id": 10, "family_links": [2]}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 20, "family_links": []}),
    ]
    state = FakeState(census)

    # Sim 2 has no family_links, but player sim 1 has 2 in their family_links
    sim2 = {"sim_id": 2, "is_player": False, "household_id": 20, "family_links": []}
    assert priority_class(state, sim2, active_sim_id=None) == "RELATED"


def test_priority_class_other_default():
    """OTHER when no other criteria match."""
    census = [
        (1, {"sim_id": 1, "is_player": True, "household_id": 10}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 20, "family_links": []}),
    ]
    state = FakeState(census)

    sim2 = {"sim_id": 2, "is_player": False, "household_id": 20, "family_links": []}
    assert priority_class(state, sim2, active_sim_id=None) == "OTHER"


def test_select_targets_player_beats_household():
    """Player sims are selected before household sims."""
    census = [
        (1, {"sim_id": 1, "is_player": True, "household_id": 10}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 10}),
        (3, {"sim_id": 3, "is_player": False, "household_id": 20}),
    ]
    state = FakeState(census)

    targets = select_targets(state, active_sim_id=3, cap=2)
    assert len(targets) == 2
    assert targets[0]["sim_id"] == 1  # Player first
    assert targets[0]["priority"] == "PLAYER"
    assert targets[1]["sim_id"] == 2  # Household second
    assert targets[1]["priority"] == "HOUSEHOLD"


def test_select_targets_active_above_related():
    """Active sim ranked above related."""
    census = [
        (1, {"sim_id": 1, "is_player": False, "household_id": 10, "family_links": [2]}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 20, "family_links": [1]}),
        (3, {"sim_id": 3, "is_player": False, "household_id": 30}),
    ]
    state = FakeState(census)

    targets = select_targets(state, active_sim_id=2, cap=2)
    assert len(targets) == 2
    assert targets[0]["sim_id"] == 2  # Active first
    assert targets[0]["priority"] == "ACTIVE"
    assert targets[1]["sim_id"] == 1  # Related second
    assert targets[1]["priority"] == "RELATED"


def test_select_targets_excludes_sleeping():
    """Sleeping sims are excluded."""
    census = [
        (1, {"sim_id": 1, "is_player": False, "is_sleeping": True}),
        (2, {"sim_id": 2, "is_player": False, "is_sleeping": False}),
    ]
    state = FakeState(census)

    targets = select_targets(state, cap=2)
    assert len(targets) == 1
    assert targets[0]["sim_id"] == 2


def test_select_targets_excludes_off_lot():
    """Off-lot duty sims are excluded."""
    census = [
        (1, {"sim_id": 1, "is_player": False, "is_off_lot_duty": True}),
        (2, {"sim_id": 2, "is_player": False, "is_off_lot_duty": False}),
    ]
    state = FakeState(census)

    targets = select_targets(state, cap=2)
    assert len(targets) == 1
    assert targets[0]["sim_id"] == 2


def test_select_targets_exclude_ids():
    """exclude_ids filters out specified sims."""
    census = [
        (1, {"sim_id": 1, "is_player": True}),
        (2, {"sim_id": 2, "is_player": False}),
        (3, {"sim_id": 3, "is_player": False}),
    ]
    state = FakeState(census)

    targets = select_targets(state, cap=2, exclude_ids={1})
    assert len(targets) == 2
    assert all(t["sim_id"] != 1 for t in targets)
    assert targets[0]["sim_id"] == 2
    assert targets[1]["sim_id"] == 3


def test_select_targets_cap_limits_results():
    """cap limits the number of returned targets."""
    census = [
        (1, {"sim_id": 1, "is_player": True}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 10}),
        (3, {"sim_id": 3, "is_player": False, "household_id": 10}),
        (4, {"sim_id": 4, "is_player": False}),
    ]
    state = FakeState(census)

    targets = select_targets(state, cap=2)
    assert len(targets) == 2

    targets = select_targets(state, cap=10)
    assert len(targets) == 4


def test_select_targets_deterministic_order_by_sim_id():
    """Same priority sorts by sim_id for deterministic ordering."""
    census = [
        (3, {"sim_id": 3, "is_player": False, "household_id": 10}),
        (1, {"sim_id": 1, "is_player": False, "household_id": 10}),
        (2, {"sim_id": 2, "is_player": False, "household_id": 10}),
    ]
    state = FakeState(census)

    targets = select_targets(state, cap=3)
    assert [t["sim_id"] for t in targets] == [1, 2, 3]


def test_select_targets_returns_sim_id_and_priority():
    """Each returned dict includes sim_id and priority."""
    census = [
        (1, {"sim_id": 1, "is_player": True}),
    ]
    state = FakeState(census)

    targets = select_targets(state, cap=1)
    assert len(targets) == 1
    assert "sim_id" in targets[0]
    assert "priority" in targets[0]
    assert targets[0]["sim_id"] == 1
    assert targets[0]["priority"] == "PLAYER"


def test_select_targets_empty_census():
    """Empty census returns empty list."""
    state = FakeState([])
    targets = select_targets(state, cap=2)
    assert targets == []


def test_select_targets_all_excluded():
    """All sims excluded returns empty list."""
    census = [
        (1, {"sim_id": 1, "is_player": True}),
    ]
    state = FakeState(census)

    targets = select_targets(state, cap=2, exclude_ids={1})
    assert targets == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])