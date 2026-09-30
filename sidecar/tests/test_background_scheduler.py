"""Tests for the background batch scheduler and its dedicated budgeter."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from sensewright_sidecar.agent import graph
from sensewright_sidecar.config import (
    AgentsConfig,
    BackgroundsConfig,
    GodConfig,
    LLMConfig,
    MemoryConfig,
    Settings,
)
from sensewright_sidecar.god.budgeter import BackgroundBudgeter
from sensewright_sidecar.god.scheduler import (
    PRIORITY_HOUSEHOLD_ACTIVE,
    PRIORITY_RELATED,
    PRIORITY_SIM_ACTIVE,
    BackgroundJob,
    BackgroundScheduler,
)
from sensewright_sidecar.schemas import (
    BackgroundRequest,
    CensusHousehold,
    CensusRequest,
    CensusSim,
    SimRef,
)

SIM = SimRef(player_id="local", save_id="save1", sim_id=10, household_id=5)


# ─── Budgeter ─────────────────────────────────────────────────────────


class FakeClock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_budgeter_per_minute_limit():
    clock = FakeClock()
    budgeter = BackgroundBudgeter(per_minute=2, daily=0, monotonic=clock, wall_clock=clock)

    assert budgeter.try_acquire() is True
    assert budgeter.try_acquire() is True
    assert budgeter.try_acquire() is False

    clock.now += 61.0
    assert budgeter.try_acquire() is True


def test_budgeter_daily_limit():
    clock = FakeClock()
    budgeter = BackgroundBudgeter(per_minute=0, daily=2, monotonic=clock, wall_clock=clock)

    assert budgeter.try_acquire() is True
    assert budgeter.try_acquire() is True
    assert budgeter.try_acquire() is False

    clock.now += 86400.0
    assert budgeter.try_acquire() is True


def test_budgeter_zero_means_unlimited():
    clock = FakeClock()
    budgeter = BackgroundBudgeter(per_minute=0, daily=0, monotonic=clock, wall_clock=clock)

    for _ in range(50):
        assert budgeter.try_acquire() is True

    snap = budgeter.snapshot()
    assert snap["day_remaining"] is None
    assert snap["total_used"] == 50


# ─── Scheduler ────────────────────────────────────────────────────────


def _job(sim_id: int, priority: int, scope: str = "sim", household_id: int | None = None):
    return BackgroundJob(
        priority=priority,
        seq=0,
        player_id="local",
        save_id="save1",
        scope=scope,
        sim_id=sim_id,
        household_id=household_id,
    )


class RecordingRunner:
    def __init__(self, results: dict[str, dict] | None = None) -> None:
        self.seen: list[BackgroundJob] = []
        self.results = results or {}

    async def __call__(self, job: BackgroundJob) -> dict:
        self.seen.append(job)
        return self.results.get(job.key, {"ok": True})


async def test_scheduler_processes_in_priority_order():
    runner = RecordingRunner()
    scheduler = BackgroundScheduler(runner, batch_size=10)

    scheduler.submit(_job(99, PRIORITY_RELATED))
    scheduler.submit(_job(1, PRIORITY_SIM_ACTIVE))
    scheduler.submit(_job(0, PRIORITY_HOUSEHOLD_ACTIVE, scope="household", household_id=5))

    processed = await scheduler.process_once()

    assert processed == 3
    assert [job.priority for job in runner.seen] == [
        PRIORITY_HOUSEHOLD_ACTIVE,
        PRIORITY_SIM_ACTIVE,
        PRIORITY_RELATED,
    ]


async def test_scheduler_dedupes_and_prefers_higher_priority():
    runner = RecordingRunner()
    scheduler = BackgroundScheduler(runner, batch_size=10)

    assert scheduler.submit(_job(1, PRIORITY_RELATED)) is True
    assert scheduler.submit(_job(1, PRIORITY_SIM_ACTIVE)) is True
    assert scheduler.submit(_job(1, PRIORITY_RELATED)) is False
    assert scheduler.pending() == 1

    await scheduler.process_once()

    assert len(runner.seen) == 1
    assert runner.seen[0].priority == PRIORITY_SIM_ACTIVE


async def test_scheduler_retries_then_fails():
    runner = RecordingRunner(results={"local:save1:sim:1": {"ok": False}})
    scheduler = BackgroundScheduler(runner, batch_size=10, max_attempts=2)

    scheduler.submit(_job(1, PRIORITY_SIM_ACTIVE))
    # First pass performs the first attempt and requeues; the second attempt
    # is consumed within the same ``process_once`` and counted as failed.
    await scheduler.process_once()

    assert len(runner.seen) == 2
    assert scheduler.pending() == 0
    assert scheduler.snapshot()["failed"] == 1


async def test_scheduler_respects_budget():
    runner = RecordingRunner(
        results={
            "local:save1:sim:1": {"ok": True, "provider": "fake"},
            "local:save1:sim:2": {"ok": True, "provider": "fake"},
        }
    )
    budgeter = BackgroundBudgeter(per_minute=1, daily=0)
    scheduler = BackgroundScheduler(runner, budgeter=budgeter, batch_size=10)

    scheduler.submit(_job(1, PRIORITY_SIM_ACTIVE))
    scheduler.submit(_job(2, PRIORITY_SIM_ACTIVE))

    processed = await scheduler.process_once()

    assert processed == 1
    assert scheduler.pending() == 1
    assert scheduler.snapshot()["budget"]["minute_used"] == 1


async def test_scheduler_refunds_non_llm_jobs():
    # Templates (no provider) must not consume the budget.
    runner = RecordingRunner()
    budgeter = BackgroundBudgeter(per_minute=1, daily=0)
    scheduler = BackgroundScheduler(runner, budgeter=budgeter, batch_size=10)

    scheduler.submit(_job(1, PRIORITY_SIM_ACTIVE))
    scheduler.submit(_job(2, PRIORITY_SIM_ACTIVE))

    processed = await scheduler.process_once()

    assert processed == 2
    assert scheduler.pending() == 0
    assert scheduler.snapshot()["budget"]["minute_used"] == 0


async def test_scheduler_start_and_stop():
    runner = RecordingRunner()
    scheduler = BackgroundScheduler(runner, interval_seconds=0.01, idle_seconds=0.01)

    assert scheduler.start() is True
    assert scheduler.running() is True
    assert scheduler.start() is False  # already running

    await scheduler.stop()
    assert scheduler.running() is False


# ─── Graph integration ────────────────────────────────────────────────


@pytest.fixture
async def bg_settings():
    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            home=Path(tmp),
            llm=LLMConfig(chain=[], providers={}),
            memory=MemoryConfig(provider="sqlite", embedding_provider="none"),
            agents=AgentsConfig(autonomy_default="semi"),
            god=GodConfig(
                backgrounds=BackgroundsConfig(batch_size=10, interval_seconds=0.01, idle_seconds=0.01)
            ),
            lang="en",
        )
        graph.configure(settings)
        # Keep the scheduler object without running its loop, so the test can
        # drive ``process_backgrounds_once`` deterministically.
        await graph.start_backgrounds()
        await graph.stop_backgrounds()
        yield settings
        try:
            await graph.shutdown()
        except Exception:
            pass


def _census_request() -> CensusRequest:
    return CensusRequest(
        sim=SIM,
        scope="active_zone",
        sims=[
            CensusSim(
                sim_id=10,
                full_name="Ana",
                household_id=5,
                traits=["ambitious"],
                age="adult",
                career="Chef",
                relationships=[{"target_id": 11, "depth": 30.0}],
                is_player=True,
            )
        ],
        households=[CensusHousehold(household_id=5, name="Silva", members=[10], funds=20000)],
    )


async def test_census_enqueues_backgrounds(bg_settings):
    result = await graph.ingest_census(_census_request())

    assert result["ok"] is True
    assert result["queued"] >= 2  # household + active sim (+ related target)

    status = graph.status()["backgrounds"]
    assert status["running"] is False
    assert status["queued"] >= 2
    assert status["budget"]["per_minute"] > 0


async def test_batch_writes_backgrounds(bg_settings):
    await graph.ingest_census(_census_request())
    processed = await graph.process_backgrounds_once()
    assert processed >= 2

    sim_bg = await graph.generate_background(
        BackgroundRequest(sim=SIM, scope="sim", census={"full_name": "Ana"}, lang="en")
    )
    assert sim_bg["ok"] is True
    assert sim_bg["cached"] is True

    household_bg = await graph.generate_background(
        BackgroundRequest(sim=SIM, scope="household", household_id=5, lang="en")
    )
    assert household_bg["ok"] is True
    assert household_bg["cached"] is True


async def test_native_mode_does_not_consume_budget(bg_settings):
    await graph.ingest_census(_census_request())
    await graph.process_backgrounds_once()

    status = graph.status()["backgrounds"]
    assert status["generated"] >= 2
    assert status["budget"]["total_used"] == 0


async def test_zeitgeist_change_requeues_backgrounds(bg_settings):
    await graph.ingest_census(_census_request())
    await graph.process_backgrounds_once()
    assert graph.status()["backgrounds"]["queued"] == 0

    await graph.set_zeitgeist(SIM, ["romance"], "", 0.9, "en")

    assert graph.status()["backgrounds"]["queued"] > 0
