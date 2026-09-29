"""Tests for the per-Sim initiative scheduler and directive store (A2)."""

from __future__ import annotations

from typing import Any

from sims_sense_sidecar.agent.agency import Agency, ImpulseJob
from sims_sense_sidecar.config import (
    AgentsConfig,
    InitiativeConfig,
    PersonalityConfig,
    Settings,
)
from sims_sense_sidecar.god.budgeter import BackgroundBudgeter
from sims_sense_sidecar.schemas import (
    AutonomySimState,
    AutonomyTickRequest,
    SimRef,
    ZoneContext,
)


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeRunner:
    """Records jobs and returns a fixed number of well-shaped directives."""

    def __init__(self, directives_per_job: int = 1, used_llm: bool = False) -> None:
        self.seen: list[ImpulseJob] = []
        self.directives_per_job = directives_per_job
        self.used_llm = used_llm

    async def __call__(self, job: ImpulseJob) -> dict[str, Any]:
        self.seen.append(job)
        directives = [
            {
                "id": f"d-{job.sim_id}-{index}",
                "sim_id": job.sim_id,
                "name": "spontaneous_line",
                "args": {"text": "hi"},
                "thought": "t",
                "narration": "",
                "priority": 0,
                "source": "agent",
            }
            for index in range(self.directives_per_job)
        ]
        return {"ok": True, "used_llm": self.used_llm, "directives": directives}


def make_settings(**initiative: Any) -> Settings:
    return Settings(
        agents=AgentsConfig(
            initiative=InitiativeConfig(**initiative),
            personality=PersonalityConfig(),
        )
    )


def tick(
    sims: list[tuple[int, str, bool]],
    *,
    sleeping: tuple[int, ...] = (),
    lang: str = "en",
) -> AutonomyTickRequest:
    states = [
        AutonomySimState(
            sim_id=sim_id,
            autonomy=autonomy,
            is_player=is_player,
            sleeping=sim_id in sleeping,
        )
        for sim_id, autonomy, is_player in sims
    ]
    return AutonomyTickRequest(
        sim=SimRef(player_id="local", save_id="save1", sim_id=sims[0][0]),
        zone=ZoneContext(time_of_day="evening", lot_type="residential"),
        sims=states,
        lang=lang,
    )


async def test_ingest_tick_caches_world_and_reports_sleeping():
    clock = FakeClock()
    agency = Agency(make_settings(max_impulses_per_tick=1), clock=clock)

    result = await agency.ingest_tick(
        tick([(10, "semi", True), (11, "full", False)], sleeping=(10,))
    )

    assert result["ok"] is True
    assert result["sleeping"] == [10]
    assert result["scheduled"] == 1

    world = agency.world_context("local", "save1")
    assert world["zone"]["time_of_day"] == "evening"
    assert "11" in world["sims"]
    assert agency.is_player("local", "save1", 10) is True
    assert agency.is_player("local", "save1", 11) is False
    assert agency.snapshot()["by_kind"]["sleep"] == 1


async def test_sleep_job_deduped_across_ticks():
    clock = FakeClock()
    agency = Agency(make_settings(), clock=clock)
    request = tick([(7, "semi", False)], sleeping=(7,))

    await agency.ingest_tick(request)
    await agency.ingest_tick(request)

    assert agency.snapshot()["by_kind"].get("sleep") == 1

    assert agency.enqueue_sleep("local", "save1", 7, "en") is False

    await agency.process_once()
    # Once handled, the next pulse may consolidate the following sleep episode.
    assert agency.enqueue_sleep("local", "save1", 7, "en") is True


async def test_idle_scheduling_respects_max_and_per_sim_cooldown():
    clock = FakeClock()
    agency = Agency(
        make_settings(max_impulses_per_tick=3, cooldown_sim_minutes=8.0),
        clock=clock,
    )
    request = tick([(10, "semi", False), (11, "semi", False), (12, "full", False)])

    first = await agency.ingest_tick(request)
    assert first["scheduled"] == 3
    assert agency.snapshot()["by_kind"].get("idle") == 3

    await agency.process_once()
    assert agency.snapshot()["queued"] == 0

    clock.advance(1.0)  # below the per-Sim cooldown
    second = await agency.ingest_tick(request)
    assert second["scheduled"] == 0

    clock.advance(agency.cooldown_seconds)
    third = await agency.ingest_tick(request)
    assert third["scheduled"] == 3


async def test_idle_scheduling_respects_max_impulses_per_tick():
    clock = FakeClock()
    agency = Agency(make_settings(max_impulses_per_tick=1), clock=clock)

    result = await agency.ingest_tick(
        tick([(10, "semi", False), (11, "semi", False), (12, "semi", False)])
    )

    assert result["scheduled"] == 1
    assert agency.snapshot()["by_kind"].get("idle") == 1


async def test_idle_scheduling_skips_off_and_sleeping_sims():
    clock = FakeClock()
    agency = Agency(make_settings(max_impulses_per_tick=5), clock=clock)

    result = await agency.ingest_tick(
        tick([(10, "off", False), (11, "semi", False)], sleeping=(11,))
    )

    assert result["scheduled"] == 0
    assert result["sleeping"] == [11]


async def test_process_once_stores_directives_and_pull_drains_with_limit():
    clock = FakeClock()
    runner = FakeRunner(directives_per_job=2)
    agency = Agency(make_settings(max_impulses_per_tick=2), runner=runner, clock=clock)

    await agency.ingest_tick(tick([(10, "semi", False), (11, "semi", False)]))
    processed = await agency.process_once()

    assert processed == 2
    assert agency.pending_count("local", "save1") == 4

    first = agency.pull("local", "save1", limit=1)
    assert len(first) == 1
    assert set(first[0]) >= {
        "id",
        "sim_id",
        "name",
        "args",
        "thought",
        "narration",
        "priority",
        "source",
    }

    rest = agency.pull("local", "save1", limit=10)
    assert len(rest) == 3
    assert agency.pending_count() == 0


async def test_pull_filters_by_sim():
    clock = FakeClock()
    agency = Agency(
        make_settings(max_impulses_per_tick=2),
        runner=FakeRunner(directives_per_job=1),
        clock=clock,
    )

    await agency.ingest_tick(tick([(10, "semi", False), (11, "semi", False)]))
    await agency.process_once()

    only_10 = agency.pull("local", "save1", sim_id=10)

    assert [directive["sim_id"] for directive in only_10] == [10]
    assert agency.pending_count() == 1


async def test_budget_refunded_when_no_llm_used():
    clock = FakeClock()
    budgeter = BackgroundBudgeter(per_minute=1, daily=0, monotonic=clock, wall_clock=clock)
    agency = Agency(
        make_settings(max_impulses_per_tick=2),
        runner=FakeRunner(used_llm=False),
        budgeter=budgeter,
        clock=clock,
    )

    await agency.ingest_tick(tick([(10, "semi", False), (11, "semi", False)]))
    processed = await agency.process_once()

    assert processed == 2
    assert agency.snapshot()["budget"]["minute_used"] == 0


async def test_budget_blocks_llm_jobs():
    clock = FakeClock()
    budgeter = BackgroundBudgeter(per_minute=1, daily=0, monotonic=clock, wall_clock=clock)
    agency = Agency(
        make_settings(max_impulses_per_tick=2),
        runner=FakeRunner(used_llm=True),
        budgeter=budgeter,
        clock=clock,
    )

    await agency.ingest_tick(tick([(10, "semi", False), (11, "semi", False)]))
    processed = await agency.process_once()

    assert processed == 1
    assert agency.snapshot()["queued"] == 1
    assert agency.snapshot()["budget"]["minute_used"] == 1


async def test_enqueue_reaction_respects_threshold_and_dedups():
    clock = FakeClock()
    agency = Agency(make_settings(event_react_threshold=2.0), clock=clock)

    assert agency.enqueue_reaction("local", "save1", 10, {"type": "fire", "importance": 1.0}) is False
    assert agency.enqueue_reaction("local", "save1", 10, {"type": "fire", "importance": 3.0}) is True
    assert agency.enqueue_reaction("local", "save1", 10, {"type": "fire", "importance": 3.0}) is False
    assert agency.snapshot()["by_kind"].get("reaction") == 1


async def test_snapshot_has_expected_keys():
    agency = Agency(make_settings(), clock=FakeClock())

    snap = agency.snapshot()

    for key in (
        "running",
        "queued",
        "by_kind",
        "pending_directives",
        "level",
        "player_sim_level",
        "processed",
        "failed",
        "budget",
    ):
        assert key in snap


async def test_clear_drops_state_for_key():
    clock = FakeClock()
    agency = Agency(make_settings(), runner=FakeRunner(), clock=clock)
    await agency.ingest_tick(tick([(10, "semi", False)]))
    await agency.process_once()

    agency.clear("local", "save1")

    assert agency.pending_count() == 0
    assert agency.world_context("local", "save1") == {}
    assert agency.snapshot()["queued"] == 0


class FakeChain:
    def __init__(self, rpm: int | None) -> None:
        self._rpm = rpm

    def primary_rpm(self) -> int | None:
        return self._rpm


class FakeRegistry:
    def __init__(self, rpm: int | None) -> None:
        self.chain = FakeChain(rpm)


def test_budgeter_uses_registry_rpm():
    agency = Agency(make_settings(quota_fraction=0.5), clock=FakeClock())

    agency.set_registry(FakeRegistry(40))

    assert agency.snapshot()["budget"]["per_minute"] == 20


def test_budgeter_falls_back_to_default_rpm():
    agency = Agency(make_settings(quota_fraction=0.5), clock=FakeClock())

    agency.set_registry(FakeRegistry(None))

    assert agency.snapshot()["budget"]["per_minute"] == 10


async def test_ingest_tick_logs_pulse(caplog):
    import logging

    agency = Agency(make_settings(max_impulses_per_tick=1), clock=FakeClock())

    with caplog.at_level(logging.INFO, logger="sims_sense_sidecar.agent.agency"):
        await agency.ingest_tick(tick([(10, "semi", False)]))

    assert any("pulse save=" in record.getMessage() for record in caplog.records)


async def test_process_once_logs_stored_intents(caplog):
    import logging

    agency = Agency(
        make_settings(max_impulses_per_tick=1),
        runner=FakeRunner(directives_per_job=1),
        clock=FakeClock(),
    )
    await agency.ingest_tick(tick([(10, "semi", False)]))

    with caplog.at_level(logging.INFO, logger="sims_sense_sidecar.agent.agency"):
        await agency.process_once()

    assert any("intent(s) stored" in record.getMessage() for record in caplog.records)
