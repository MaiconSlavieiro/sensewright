"""Regression tests for the weak-point/bug fix wave (docs/operations.md).

Covers: lease tick scaling (S-B01/S-H02), action-context double-encoding (S-B03),
social-close fallback key (S-B04), God autonomy_mode (S-H01), seat lease units +
active_pos distance (S-H02/S-M04), game-budget cap (S-H03), provider reload
cooldown (S-H04), duty-imminent Mod schedule shape (S-H05), defensive save_id
coercion (S-H06).
"""
from __future__ import annotations

import json

from sensewright_sidecar.config import Config, DEFAULT_CONFIG
from sensewright_sidecar.constants import TICKS_PER_SIM_MINUTE
from sensewright_sidecar.god.controls import (
    AUTONOMY_MODES, get_controls, resolve_autonomy_mode, set_control,
)
from sensewright_sidecar.god.coordinator import set_catalyst_lease
from sensewright_sidecar.panel_store import PanelStore
from sensewright_sidecar.state import AppState, reset_state
from sensewright_sidecar.agent.impulse import duty_imminent, physical_actions_allowed
from sensewright_sidecar.agent.seats import SeatManager
from sensewright_sidecar.llm.budgeter import GameBudgeter
from sensewright_sidecar.llm.chain import ProviderChain
from sensewright_sidecar.llm.context import ContextAssembler
from sensewright_sidecar.schemas import to_int

import copy


def _config() -> Config:
    return Config(copy.deepcopy(DEFAULT_CONFIG))


class TestLeaseTickUnits:
    def test_catalyst_lease_uses_ticks_per_sim_minute(self):
        reset_state()
        state = AppState()
        try:
            set_catalyst_lease(state, 1, "objective", 100)
            lease_min = int(state.config.gameplay("lease_min_sim_minutes", 60))
            assert state.catalyst_leases[1]["lease_expires_tick"] == (
                100 + lease_min * TICKS_PER_SIM_MINUTE
            )
        finally:
            reset_state()

    def test_seat_lease_uses_ticks_per_sim_minute(self):
        manager = SeatManager()
        seats = manager.assign(
            sims={1: {"sim_id": 1, "household_id": 1, "species": "HUMAN", "age_stage": "ADULT"}},
            active_household_id=1, active_sim_id=1, catalyst_ids=[],
            active_conversation_ids=[], tick=0, max_seats=4,
            lease_min_sim_minutes=60,
        )
        assert seats[1]["lease_expires_tick"] == 60 * TICKS_PER_SIM_MINUTE

    def test_seat_distance_uses_passed_active_pos(self):
        manager = SeatManager()
        sims = {
            1: {"sim_id": 1, "household_id": 2, "species": "HUMAN", "age_stage": "ADULT",
                "pos": {"x": 0.0, "z": 0.0}},
            2: {"sim_id": 2, "household_id": 2, "species": "HUMAN", "age_stage": "ADULT",
                "pos": {"x": 100.0, "z": 100.0}},
        }
        seats = manager.assign(
            sims=sims, active_household_id=1, active_sim_id=1, catalyst_ids=[],
            active_conversation_ids=[], tick=0, max_seats=1,
            lease_min_sim_minutes=60, active_pos={"x": 0.0, "z": 0.0},
        )
        assert 1 in seats


class TestActionContextEncoding:
    def test_build_payload_returns_dict(self):
        assembler = ContextAssembler(_config())
        payload = assembler._build_payload("sim.impulse", {"mood": "happy"}, "realtime")
        assert isinstance(payload, dict)
        assert payload["purpose"] == "sim.impulse"

    def test_assemble_user_context_is_not_double_encoded(self):
        assembler = ContextAssembler(_config())
        messages = assembler.assemble("sim.impulse", {"mood": "happy"})
        user = messages[1]["content"]
        # Must be a JSON object, not a quoted/escaped JSON string.
        parsed = json.loads(user)
        assert isinstance(parsed, dict)
        assert parsed.get("purpose") == "sim.impulse"


class TestSocialCloseFallbackKey:
    def test_event_summary_is_persisted(self, monkeypatch):
        import sensewright_sidecar.services as services

        recorded = []

        class _FakeStore:
            def add_memory(self, sim_id, kind, content, search_text="", created_sim_tick=0):
                recorded.append((sim_id, kind, content, search_text))

        monkeypatch.setattr(services, "_store", lambda state: _FakeStore())

        class _Result:
            data = {"event_summary": "They gossiped by the pool."}

        callback = services._social_close_callback(AppState(), 1, 2, 100)
        callback(_Result())
        assert recorded and recorded[0][3] == "They gossiped by the pool."


class TestAutonomyMode:
    def test_set_and_resolve(self, tmp_path):
        panel = PanelStore(tmp_path)
        config = _config()
        assert set_control(panel, config, "autonomy_mode", "reactive") is True
        assert resolve_autonomy_mode(panel, config) == "reactive"
        assert set_control(panel, config, "autonomy_mode", "bogus") is False

    def test_control_is_exposed(self, tmp_path):
        panel = PanelStore(tmp_path)
        controls = get_controls(panel, _config())
        keys = {c["key"]: c for c in controls}
        assert keys["autonomy_mode"]["options"] == list(AUTONOMY_MODES)


class TestGameBudgetCap:
    def test_unlimited_by_default(self):
        b = GameBudgeter(0)
        assert b.can_spend(1, 10 ** 9) is True

    def test_cap_enforced(self):
        b = GameBudgeter(150)
        b.spend(1, 100)
        assert b.can_spend(1, 50) is True
        assert b.can_spend(1, 51) is False
        assert b.cap() == 150


class TestProviderReload:
    def test_reload_clears_model_state(self):
        chain = ProviderChain(_config())
        chain._record_failure("fake", "m1")
        chain._record_failure("fake", "m1")
        assert chain._model_cooling("fake", "m1") is True
        chain.reload_provider("fake")
        assert chain._model_cooling("fake", "m1") is False
        assert ("fake", "m1") not in chain._model_failures


class TestDutyImminent:
    def test_start_hour_shape_within_window(self):
        # tick 0 -> minute-of-day 0; 00:30 start is 30 minutes away.
        assert duty_imminent([{"type": "work", "start_hour": 0.5}], 0) is True

    def test_start_hour_shape_outside_window(self):
        assert duty_imminent([{"type": "work", "start_hour": 2.0}], 0) is False

    def test_legacy_start_tick_still_supported(self):
        assert duty_imminent([{"start_tick": 145}], 100) is True

    def test_physical_guard_uses_real_shape(self):
        assert physical_actions_allowed({"fun": -10}, [{"start_hour": 0.5}], 0) is False


class TestSafeInt:
    def test_non_numeric_save_id(self):
        assert to_int("unknown") == 0
        assert to_int(None) == 0
        assert to_int("123") == 123
        assert to_int(4.9) == 4
