"""Progressive batch scheduler for God-agent background generation.

Backgrounds are written off the request path on the free tier (Tier 2): the
active-zone households and Sims come first, then related NPCs discovered
through the census. Jobs are deduplicated, ordered by priority and metered by
a dedicated budgeter so the pipeline never competes with real-time chat.

The scheduler owns no LLM or memory logic: callers inject an async
``runner(job)`` that performs the actual generation and returns a dict with
``ok``/``cached`` flags. This keeps it decoupled and deterministic to test.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .budgeter import BackgroundBudgeter

logger = logging.getLogger(__name__)

Runner = Callable[["BackgroundJob"], Awaitable[dict[str, Any]]]

# Lower numbers run first: active-zone households, then active-zone Sims,
# then related NPCs discovered through census relationships.
PRIORITY_HOUSEHOLD_ACTIVE = 0
PRIORITY_SIM_ACTIVE = 1
PRIORITY_RELATED = 2


@dataclass(order=True)
class BackgroundJob:
    """One unit of background work, ordered by ``(priority, seq)``."""

    priority: int
    seq: int
    player_id: str = field(compare=False, default="local")
    save_id: str = field(compare=False, default="unknown")
    scope: str = field(compare=False, default="sim")
    sim_id: int = field(compare=False, default=0)
    household_id: int | None = field(compare=False, default=None)
    lang: str = field(compare=False, default="en")
    player_hints: str = field(compare=False, default="")
    source: str = field(compare=False, default="batch")
    attempts: int = field(compare=False, default=0)
    enqueued_at: float = field(compare=False, default=0.0)

    @property
    def key(self) -> str:
        if self.scope == "household":
            return f"{self.player_id}:{self.save_id}:household:{self.household_id}"
        return f"{self.player_id}:{self.save_id}:sim:{self.sim_id}"


def _used_llm(result: dict[str, Any]) -> bool:
    """True when a job actually called a provider (uncached, provider named)."""
    return bool(result.get("provider")) and not result.get("cached")


class BackgroundScheduler:
    """Priority queue + async loop that drains background jobs within budget."""

    def __init__(
        self,
        runner: Runner,
        *,
        budgeter: BackgroundBudgeter | None = None,
        batch_size: int = 2,
        interval_seconds: float = 15.0,
        idle_seconds: float = 30.0,
        max_queue: int = 200,
        max_attempts: int = 2,
    ) -> None:
        self._runner = runner
        self._budgeter = budgeter
        self._batch_size = max(1, int(batch_size))
        self._interval = max(0.0, float(interval_seconds))
        self._idle = max(0.0, float(idle_seconds))
        self._max_queue = max(0, int(max_queue))
        self._max_attempts = max(1, int(max_attempts))
        self._heap: list[BackgroundJob] = []
        self._queued: dict[str, BackgroundJob] = {}
        self._seq = 0
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._stats = {
            "submitted": 0,
            "processed": 0,
            "generated": 0,
            "cached": 0,
            "failed": 0,
            "dropped": 0,
        }

    # ── queue ─────────────────────────────────────────────────────────
    def submit(self, job: BackgroundJob) -> bool:
        """Enqueue a job, deduplicating by key and preferring higher priority."""
        if job.enqueued_at <= 0:
            job.enqueued_at = time.time()

        existing = self._queued.get(job.key)
        if existing is not None and existing.priority <= job.priority:
            return False
        if existing is None and self._max_queue > 0 and len(self._queued) >= self._max_queue:
            self._stats["dropped"] += 1
            return False

        if existing is None:
            self._seq += 1
            job.seq = self._seq
        else:
            job.seq = existing.seq

        self._queued[job.key] = job
        heapq.heappush(self._heap, job)
        self._stats["submitted"] += 1
        return True

    def submit_many(self, jobs: list[BackgroundJob]) -> int:
        """Enqueue several jobs; return how many were accepted."""
        return sum(1 for job in jobs if self.submit(job))

    def clear(self) -> int:
        """Drop every queued job; return how many were discarded."""
        count = len(self._queued)
        self._heap.clear()
        self._queued.clear()
        return count

    def pending(self) -> int:
        return len(self._queued)

    def _next(self) -> BackgroundJob | None:
        while self._heap:
            job = heapq.heappop(self._heap)
            # Skip entries superseded by a higher-priority job with the same key.
            if self._queued.get(job.key) is job:
                del self._queued[job.key]
                return job
        return None

    def _push_back(self, job: BackgroundJob) -> None:
        self._queued[job.key] = job
        heapq.heappush(self._heap, job)

    # ── processing ────────────────────────────────────────────────────
    async def process_once(self) -> int:
        """Run up to ``batch_size`` jobs; return how many were processed."""
        processed = 0
        while processed < self._batch_size:
            job = self._next()
            if job is None:
                break
            if self._budgeter is not None and not self._budgeter.try_acquire():
                self._push_back(job)
                break
            result = await self._process(job)
            # Only real provider calls count against the budget; templates and
            # cache hits are refunded so native mode never exhausts the quota.
            if self._budgeter is not None and not _used_llm(result):
                self._budgeter.refund()
            processed += 1
        return processed

    async def _process(self, job: BackgroundJob) -> dict[str, Any]:
        try:
            result = await self._runner(job)
        except Exception as exc:
            logger.warning("background job failed: %s", exc)
            result = {"ok": False, "error": str(exc)}

        if not isinstance(result, dict):
            result = {"ok": False}

        if result.get("ok"):
            self._stats["processed"] += 1
            if result.get("cached"):
                self._stats["cached"] += 1
            else:
                self._stats["generated"] += 1
            return result

        job.attempts += 1
        if job.attempts < self._max_attempts:
            self._push_back(job)
            return result
        self._stats["failed"] += 1
        return result

    # ── lifecycle ─────────────────────────────────────────────────────
    def start(self) -> bool:
        """Start the async loop; no-op and False when already running."""
        if self.running():
            return False
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="simssense-backgrounds")
        return True

    async def _run(self) -> None:
        try:
            while not self._stopping:
                processed = await self.process_once()
                await asyncio.sleep(self._interval if processed else self._idle)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("background scheduler crashed: %s", exc)

    async def stop(self) -> None:
        """Cancel and await the loop."""
        self._stopping = True
        task = self._task
        self._task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    def stop_now(self) -> None:
        """Cancel the loop without awaiting (safe from sync ``configure``)."""
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable view for ``/v1/status``."""
        by_scope: dict[str, int] = {}
        for job in self._queued.values():
            by_scope[job.scope] = by_scope.get(job.scope, 0) + 1

        snap: dict[str, Any] = {
            "running": self.running(),
            "queued": len(self._queued),
            "by_scope": by_scope,
            "batch_size": self._batch_size,
            "interval_seconds": self._interval,
            "max_attempts": self._max_attempts,
            **self._stats,
        }
        if self._budgeter is not None:
            snap["budget"] = self._budgeter.snapshot()
        return snap
