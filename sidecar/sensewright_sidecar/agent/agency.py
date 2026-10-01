"""Per-Sim initiative scheduler and pending-directive store (§14.2, A2).

``Agency`` mirrors the God background scheduler (priority heap, dedup by key,
injected async runner) but works per-Sim: zone pulses update a small
world-model cache and schedule reaction/sleep/idle impulses. It owns no memory
or LLM logic — the graph injects a ``runner(job)`` that recalls memories/psyche
and produces ``directives``. The budgeter paces impulses against the provider
free tier so native/template runs never drain the quota.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..god.budgeter import BackgroundBudgeter
from .context_forge import PairContext
from .conversations import ConversationManager
from .initiative import build_impulse
from .intents import IntentBus, intent_from_directive
from .presence import PresencePolicy
from .seats import SeatManager
from .social import SocialLayer
from .speech import SpeechPolicy

logger = logging.getLogger(__name__)

Runner = Callable[["ImpulseJob"], Awaitable[dict[str, Any]]]

# Lower numbers run first: reactions, then sleep consolidation, then idle.
PRIORITY_REACTION = 0
PRIORITY_SLEEP = 1
PRIORITY_IDLE = 2

# A Sims 4 day is roughly 24 real minutes, so 1 sim-minute ≈ 1 wall second.
SIM_MINUTE_SECONDS = 1.0

# Free-tier RPM the quota fraction is applied to (OpenRouter ``:free`` ≈ 20).
AGENCY_BASE_RPM = 20

# The background loop paces itself; the mod pulls directives asynchronously.
AGENCY_INTERVAL_SECONDS = 5.0
AGENCY_IDLE_SECONDS = 15.0
PROCESS_BATCH = 5
MAX_ATTEMPTS = 2


@dataclass(order=True)
class ImpulseJob:
    """One impulse, ordered by ``(priority, seq)``."""

    priority: int
    seq: int
    kind: str = field(compare=False, default="idle")  # reaction | sleep | idle
    player_id: str = field(compare=False, default="local")
    save_id: str = field(compare=False, default="unknown")
    sim_id: int = field(compare=False, default=0)
    lang: str = field(compare=False, default="en")
    event: dict | None = field(compare=False, default=None)
    attempts: int = field(compare=False, default=0)
    enqueued_at: float = field(compare=False, default=0.0)

    @property
    def key(self) -> str:
        return f"{self.player_id}:{self.save_id}:{self.kind}:{self.sim_id}"


def _dump(obj: Any) -> dict[str, Any]:
    """Best-effort dict view of a pydantic model or plain mapping."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return dict(obj)
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump()
    try:
        return dict(obj)
    except (TypeError, ValueError):
        return {}


class Agency:
    """Priority queue + async loop that drains per-Sim impulses within budget."""

    def __init__(
        self,
        settings: Any,
        *,
        runner: Runner | None = None,
        registry: Any = None,
        budgeter: BackgroundBudgeter | None = None,
        rng: random.Random | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._runner_override = runner
        self._registry = registry
        self._rng = rng or random.Random()
        self._clock = clock or time.monotonic
        self._budgeter_injected = budgeter is not None
        self._budgeter = budgeter

        self._heap: list[ImpulseJob] = []
        self._queued: dict[str, ImpulseJob] = {}
        self._intents = IntentBus()
        self.seats = SeatManager(self._initial_seats(settings), clock=self._clock)
        self.social = SocialLayer(settings, registry=registry, rng=self._rng, clock=self._clock)
        # v0.4: speech/presence policies + conversation sessions.
        self.speech = SpeechPolicy(settings, clock=self._clock, rng=self._rng)
        self.presence = PresencePolicy(settings)
        self.conversations = ConversationManager(
            settings, registry=registry, clock=self._clock
        )
        self._context_forge: Any = None
        self._world: dict[tuple[str, str], dict[str, Any]] = {}
        # v0.4 P4 / v0.5 R4: (player, save, sim_id) ->
        # (target_id, interaction_raw, interaction_text, ts).
        self._interaction_seeds: dict[tuple[str, str, int], tuple[int, str, str, float]] = {}
        self._sleeping: set[tuple[str, str, int]] = set()
        self._last_impulse: dict[tuple[tuple[str, str], int], float] = {}
        self._rr: dict[tuple[str, str], int] = {}
        self._seq = 0
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._stats = {"submitted": 0, "processed": 0, "failed": 0, "dropped": 0}
        self.configure(settings)

    # ── configuration ─────────────────────────────────────────────────
    @staticmethod
    def _initial_seats(settings: Any) -> int:
        try:
            return int(settings.agents.seat_count)
        except Exception:
            return 12

    def configure(self, settings: Any) -> None:
        """(Re)apply initiative/sleep config; never leaks a running loop."""
        self._settings = settings
        config = settings.agents.initiative
        self.level = config.level
        self.player_sim_level = config.player_sim_level
        self.cooldown_sim_minutes = float(config.cooldown_sim_minutes)
        self.event_react_threshold = float(config.event_react_threshold)
        self.spontaneous_lines = bool(config.spontaneous_lines)
        self.quota_fraction = float(config.quota_fraction)
        self.max_impulses_per_tick = max(0, int(config.max_impulses_per_tick))
        # v0.3 §15.6: impulse frequency dials + reaction toggle.
        self.impulse_frequency = max(0.0, min(1.0, float(config.impulse_frequency)))
        self.player_sim_impulse_frequency = max(
            0.0, min(1.0, float(config.player_sim_impulse_frequency))
        )
        self.reactions_enabled = bool(config.reactions_enabled)
        # v0.5 R3: shared budget reserve for social conversation turns.
        self.social_reserve_fraction = max(
            0.0, min(0.9, float(getattr(config, "social_reserve_fraction", 0.4) or 0.0))
        )
        self.sleep_consolidation = bool(settings.agents.personality.sleep_consolidation)
        self.default_autonomy = settings.agents.autonomy_default

        self.seats.configure(self._initial_seats(settings))
        self.social.configure(settings)
        self.social.set_registry(self._registry)
        self.speech.configure(settings)
        self.presence.configure(settings)
        self.conversations.configure(settings)
        self.conversations.set_registry(self._registry)

        if not self._budgeter_injected:
            self._rebuild_budgeter()
        self.stop_now()

    def set_context_forge(self, forge: Any) -> None:
        """Attach the shared ``ContextForge`` used by the social layer."""
        self._context_forge = forge

    def _resolve_base_rpm(self) -> int:
        """Base free-tier RPM: the chain's primary provider RPM, else the default."""
        registry = self._registry
        if registry is not None:
            try:
                rpm = registry.chain.primary_rpm()
                if rpm:
                    return int(rpm)
            except Exception:
                pass
        return AGENCY_BASE_RPM

    def _rebuild_budgeter(self) -> None:
        per_minute = max(1, round(self.quota_fraction * self._resolve_base_rpm()))
        self._budgeter = BackgroundBudgeter(
            per_minute=per_minute,
            daily=0,
            reserve_fraction=float(getattr(self, "social_reserve_fraction", 0.0) or 0.0),
            monotonic=self._clock,
            wall_clock=self._clock,
        )

    def set_registry(self, registry: Any) -> None:
        """Attach (or clear) the LLM registry used by the default runner.

        The registry also provides the real free-tier RPM that paces impulses,
        so the budgeter is rebuilt when it changes.
        """
        self._registry = registry
        self.social.set_registry(registry)
        self.conversations.set_registry(registry)
        if not self._budgeter_injected:
            self._rebuild_budgeter()

    @property
    def cooldown_seconds(self) -> float:
        """Per-Sim cooldown in wall-clock seconds (1 sim-minute ≈ 1 s)."""
        return max(0.0, self.cooldown_sim_minutes) * SIM_MINUTE_SECONDS

    # ── queue ─────────────────────────────────────────────────────────
    def _submit(self, job: ImpulseJob) -> bool:
        """Enqueue a job, deduplicating by key and preferring higher priority."""
        if job.enqueued_at <= 0:
            job.enqueued_at = self._clock()

        existing = self._queued.get(job.key)
        if existing is not None and existing.priority <= job.priority:
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

    def _next(self) -> ImpulseJob | None:
        while self._heap:
            job = heapq.heappop(self._heap)
            # Skip entries superseded by a higher-priority job with the same key.
            if self._queued.get(job.key) is job:
                del self._queued[job.key]
                return job
        return None

    def _push_back(self, job: ImpulseJob) -> None:
        self._queued[job.key] = job
        heapq.heappush(self._heap, job)

    def enqueue_reaction(
        self,
        player_id: str,
        save_id: str,
        sim_id: int,
        event: dict[str, Any],
        lang: str = "en",
    ) -> bool:
        """Queue a prioritized reaction to a salient game event."""
        if not getattr(self, "reactions_enabled", True):
            return False
        event = event or {}
        if self._event_salience(event) < self.event_react_threshold:
            return False
        job = ImpulseJob(
            PRIORITY_REACTION,
            0,
            kind="reaction",
            player_id=player_id,
            save_id=save_id,
            sim_id=int(sim_id),
            lang=lang,
            event=dict(event),
        )
        return self._submit(job)

    def enqueue_sleep(self, player_id: str, save_id: str, sim_id: int, lang: str = "en") -> bool:
        """Queue one sleep-consolidation job per sleeping Sim episode."""
        job = ImpulseJob(
            PRIORITY_SLEEP,
            0,
            kind="sleep",
            player_id=player_id,
            save_id=save_id,
            sim_id=int(sim_id),
            lang=lang,
        )
        accepted = self._submit(job)
        if accepted:
            self._sleeping.add((player_id, save_id, int(sim_id)))
        return accepted

    def _enqueue_idle(self, player_id: str, save_id: str, sim_id: int, lang: str = "en") -> bool:
        job = ImpulseJob(
            PRIORITY_IDLE,
            0,
            kind="idle",
            player_id=player_id,
            save_id=save_id,
            sim_id=int(sim_id),
            lang=lang,
        )
        return self._submit(job)

    @staticmethod
    def _event_salience(event: dict[str, Any]) -> float:
        raw = event.get("salience", event.get("importance", 1.0))
        try:
            return float(raw)
        except (TypeError, ValueError):
            return 1.0

    # ── tick ingestion ────────────────────────────────────────────────
    async def ingest_tick(self, req: Any) -> dict[str, Any]:
        """Cache the zone pulse and schedule sleep/idle impulses for it."""
        sim_ref = getattr(req, "sim", None)
        player_id = getattr(sim_ref, "player_id", "local")
        save_id = getattr(sim_ref, "save_id", "unknown")
        key = (player_id, save_id)
        now = self._clock()
        lang = getattr(req, "lang", None) or self._settings.lang or "en"

        zone = _dump(getattr(req, "zone", None))
        sims = [_dump(sim) for sim in (getattr(req, "sims", None) or [])]
        # v0.4 P3: the player's household id grounds presence tiers.
        player_household_id = None
        for sim in sims:
            if sim.get("is_player") and sim.get("household_id") is not None:
                player_household_id = sim.get("household_id")
                break
        self._world[key] = {
            "zone": zone,
            "sims": {str(sim.get("sim_id", 0)): sim for sim in sims},
            "player_household_id": player_household_id,
            "active_sim_id": getattr(sim_ref, "sim_id", None),
            "updated_at": now,
            "lang": lang,
        }

        # v0.3 R2: reconcile the agent-seat pool against the pulse.
        seat_report = self.seats.sync(
            player_id,
            save_id,
            sims,
            active_sim_id=getattr(sim_ref, "sim_id", None),
        )

        sleeping: list[int] = []
        for sim in sorted(sims, key=lambda item: int(item.get("sim_id", 0))):
            sim_id = int(sim.get("sim_id", 0))
            marker = (player_id, save_id, sim_id)
            if sim.get("sleeping"):
                sleeping.append(sim_id)
                if self.sleep_consolidation and marker not in self._sleeping:
                    self.enqueue_sleep(player_id, save_id, sim_id, lang)
            else:
                # Waking ends the episode so the next sleep can re-enqueue.
                self._sleeping.discard(marker)

        scheduled = self._schedule_idle(player_id, save_id, sims, lang)

        # v0.3 R5 / v0.4 P4: let two seated agent Sims hold a conversation session.
        dialogues, social_intents, conversations = await self._plan_social(
            player_id, save_id, sims, lang
        )

        logger.info(
            "pulse save=%s/%s sims=%d sleeping=%s scheduled=%d seats=%s social=%d conversations=%d",
            player_id,
            save_id,
            len(sims),
            sleeping,
            scheduled,
            seat_report,
            len(dialogues),
            len(conversations),
        )
        return {
            "ok": True,
            "scheduled": scheduled,
            "sleeping": sleeping,
            "seats": seat_report,
            "social": [dialogue.to_dict() for dialogue in dialogues],
            "social_intents": social_intents,
            "conversations": conversations,
        }

    async def _plan_social(
        self,
        player_id: str,
        save_id: str,
        sims: list[dict[str, Any]],
        lang: str,
    ) -> tuple[list[Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Plan sim<->sim conversation sessions; never raises.

        Returns ``(dialogues, intents, conversation_summaries)``. The sessions
        are tracked by ``self.conversations``; a session that reaches
        ``max_turns`` or whose pair stops conversing closes with a summary.
        """
        if not getattr(self.social, "enabled", True):
            return [], [], []
        try:
            seated_ids = [
                int(seat["sim_id"]) for seat in self.seats.seats_for(player_id, save_id)
            ]
            # v0.4 P4 live fix: seed conversations from the pairs *actually*
            # interacting (A targets B), not only mutually-targeting pairs — a
            # player-initiated social is usually unilateral in the pulse.
            candidates = self.social.candidate_pairs(sims)
            # v0.4 P4: merge player-interaction seeds (reliable target from the
            # player hook) with the pairs the pulse happens to show.
            by_id: dict[int, dict[str, Any]] = {}
            for sim in sims:
                try:
                    by_id[int(sim.get("sim_id"))] = sim
                except (TypeError, ValueError):
                    continue
            existing = {
                frozenset({int(x.get("sim_id")), int(y.get("sim_id"))})
                for x, y in candidates
            }
            for seed_sim, seed_target, seed_text, seed_label in self.interaction_seeds(
                player_id, save_id
            ):
                a_sim, b_sim = by_id.get(seed_sim), by_id.get(seed_target)
                key = frozenset({seed_sim, seed_target})
                if a_sim is None or b_sim is None or key in existing:
                    continue
                # v0.5 R4: a sleeping Sim is never paired, even via a player seed.
                if a_sim.get("sleeping") or b_sim.get("sleeping"):
                    logger.info(
                        "social skip reason=sleeping a=%s b=%s (seed)", seed_sim, seed_target
                    )
                    continue
                seeded = dict(a_sim)
                if seed_text or seed_label:
                    # The player's specific interaction must drive classification
                    # too (not only the label), so a joke/flirt dialogue matches
                    # even when the pulse's raw current_interaction is a generic
                    # base like ``sim_Chat`` (v0.5 R4 live fix).
                    seeded["current_interaction"] = seed_text or seed_label
                    seeded["current_interaction_text"] = seed_label or seed_text
                candidates.insert(0, (seeded, b_sim))
                existing.add(key)
            active_pairs = {
                frozenset({int(a.get("sim_id")), int(b.get("sim_id"))})
                for a, b in candidates
            }

            dialogues: list[Any] = []
            summaries: list[dict[str, Any]] = []
            if self.conversations.enabled:
                forge = PairContext(self._context_forge)
                started = 0
                for a, b in candidates:
                    a_id = int(a.get("sim_id"))
                    b_id = int(b.get("sim_id"))
                    key = frozenset({a_id, b_id})
                    active = self.conversations.is_active(a_id, b_id)
                    signature = self._pair_signature(a, b)
                    # A new session waits for the pair cooldown; an open session
                    # continues only when the interaction/queue changed or the
                    # turn interval elapsed (v0.5 R3) — never once per pulse.
                    if not active and (
                        started >= self.social.max_pairs or not self.social.pair_ready(key)
                    ):
                        continue
                    if active:
                        allowed, reason = self.conversations.should_turn(
                            a_id, b_id, signature
                        )
                        if not allowed:
                            logger.info(
                                "social skip reason=%s a=%s b=%s", reason, a_id, b_id
                            )
                            continue

                    # v0.5 R3: social draws on the shared budget *with* its
                    # reserve; without budget it still renders the template so
                    # the interaction never dies.
                    budget_ok = True
                    if self._budgeter is not None:
                        budget_ok = self._budgeter.try_acquire(allow_reserve=True)
                    try:
                        dlg = await self.social._dialogue_for_pair(
                            a,
                            b,
                            player_id=player_id,
                            save_id=save_id,
                            lang=lang,
                            forge=forge,
                            use_llm=budget_ok,
                            variant=self.conversations.turns_for(a_id, b_id),
                        )
                    except Exception as exc:
                        logger.warning("social dialogue failed: %s", exc)
                        if self._budgeter is not None and budget_ok:
                            self._budgeter.refund()
                        continue
                    if dlg is None:
                        if self._budgeter is not None and budget_ok:
                            self._budgeter.refund()
                        continue
                    # Only a real LLM call consumes the slot.
                    if self._budgeter is not None and budget_ok and dlg.source != "llm":
                        self._budgeter.refund()
                    if not active:
                        self.social.note_pair(key)
                        started += 1
                    self.consume_interaction_seed(player_id, save_id, a_id, b_id)
                    interaction_text = str(
                        a.get("current_interaction_text")
                        or b.get("current_interaction_text")
                        or ""
                    ).strip()
                    closed = self.conversations.record(
                        dlg,
                        a_name=str(a.get("full_name") or ""),
                        b_name=str(b.get("full_name") or ""),
                        interaction_text=interaction_text,
                        signature=signature,
                    )
                    dialogues.append(dlg)
                    if closed is not None:
                        summaries.append(
                            await self._summarize_session(closed, lang=lang, leaving=False)
                        )
                # Close sessions whose pair stopped conversing (a "goodbye").
                for closed in self.conversations.sweep(active_pairs):
                    summaries.append(
                        await self._summarize_session(closed, lang=lang, leaving=True)
                    )
            else:
                # Legacy v0.3 behavior: one isolated exchange per pair per pulse.
                conversing = self.social.filter_conversing(sims)
                if len(conversing) >= 2:
                    forge = PairContext(self._context_forge)
                    dialogues = await self.social.plan(
                        player_id=player_id,
                        save_id=save_id,
                        sims=conversing,
                        seated_ids=seated_ids,
                        lang=lang,
                        forge=forge,
                    )
        except Exception as exc:
            logger.warning("social plan failed: %s", exc)
            return [], [], []

        intents: list[dict[str, Any]] = []
        for dialogue in dialogues:
            intents.extend(dialogue.intents())
        return dialogues, intents, summaries

    @staticmethod
    def _pair_signature(a: dict[str, Any], b: dict[str, Any]) -> str:
        """A stable signature of a pair's current interaction + queued sequence.

        Used by turn pacing (v0.5 R3): a new dialogue turn is produced only when
        this changes (or the turn interval elapses), so a static conversation
        does not repeat a line once per zone pulse.
        """
        parts: list[str] = []
        for sim in (a, b):
            interaction = str(sim.get("current_interaction") or "").strip()
            queued: list[str] = []
            for entry in sim.get("queued_interactions") or []:
                if isinstance(entry, dict) and entry.get("name"):
                    queued.append(str(entry["name"]))
            parts.append(interaction + "|" + ",".join(queued))
        return " // ".join(parts)

    async def _summarize_session(
        self, session: Any, *, lang: str, leaving: bool
    ) -> dict[str, Any]:
        """Build the summary event dict for a closed session (never raises)."""
        try:
            text = await self.conversations.summarize(session, lang=lang, leaving=leaving)
        except Exception as exc:
            logger.warning("conversation summary failed: %s", exc)
            text = self.conversations.summary_line(session, lang=lang, leaving=leaving)
        return {
            "a": session.a,
            "b": session.b,
            "topic": session.topic,
            "tone": session.tone,
            "text": text,
            "leaving": bool(leaving),
            # v0.4 P4: a proposal the graph may apply when the God allows it.
            "relationship_shift": _relationship_delta(session),
        }

    def _schedule_idle(
        self,
        player_id: str,
        save_id: str,
        sims: list[dict[str, Any]],
        lang: str,
    ) -> int:
        max_n = self.max_impulses_per_tick
        # v0.5 R3: backpressure — idle impulses scale with chain health so a
        # cool/rate-limited free tier is not hammered. Social keeps its reserve.
        if self._registry is not None and max_n > 0:
            try:
                factor = self._registry.chain.backpressure_factor()
            except Exception:
                factor = 1.0
            if factor <= 0.0:
                logger.info("idle backpressure: no warm provider, skipping idle impulses")
                return 0
            if factor < 1.0 and max_n > 1:
                max_n = max(1, round(max_n * factor))
        if max_n <= 0:
            return 0
        key = (player_id, save_id)
        player_household_id = self._world.get(key, {}).get("player_household_id")
        eligible = [
            sim
            for sim in sims
            if str(sim.get("autonomy", "off")) != "off"
            and not sim.get("sleeping")
            # v0.4 P3: only `full` presence Sims (the player's household by
            # default) get idle impulses; visitors are reactive. When the pulse
            # does not identify a player household, fall back to the legacy
            # behavior (cannot classify visitors without a household).
            and (
                player_household_id is None
                or self.presence.allows_idle(sim, player_household_id=player_household_id)
            )
        ]
        if not eligible:
            return 0
        eligible.sort(key=lambda item: int(item.get("sim_id", 0)))

        now = self._clock()
        cooldown = self.cooldown_seconds
        start = self._rr.get(key, 0) % len(eligible)
        scheduled = 0
        index = start
        for _ in range(len(eligible)):
            if scheduled >= max_n:
                break
            sim_id = int(eligible[index].get("sim_id", 0))
            # v0.3: seats decide who may act; frequency 0 makes a Sim sleep-only.
            if not self.seats.occupies(player_id, save_id, sim_id):
                index = (index + 1) % len(eligible)
                continue
            if self._frequency_for(player_id, save_id, sim_id) <= 0.0:
                index = (index + 1) % len(eligible)
                continue
            last = self._last_impulse.get((key, sim_id))
            cooling = last is not None and (now - last) < cooldown
            if not cooling and self._enqueue_idle(player_id, save_id, sim_id, lang):
                self._last_impulse[(key, sim_id)] = now
                scheduled += 1
            index = (index + 1) % len(eligible)
        self._rr[key] = index
        return scheduled

    def _frequency_for(self, player_id: str, save_id: str, sim_id: int) -> float:
        """Effective impulse frequency: per-Sim override > player default > global."""
        override = self.seats.frequency_for(player_id, save_id, sim_id)
        if override is not None:
            return float(override)
        if self.seats.occupies(player_id, save_id, sim_id) and self.is_player(
            player_id, save_id, sim_id
        ):
            return float(self.player_sim_impulse_frequency)
        return float(self.impulse_frequency)

    # ── processing ────────────────────────────────────────────────────
    async def process_once(self) -> int:
        """Run up to ``PROCESS_BATCH`` impulses; return how many were processed."""
        processed = 0
        while processed < PROCESS_BATCH:
            job = self._next()
            if job is None:
                break
            if self._budgeter is not None and not self._budgeter.try_acquire():
                self._push_back(job)
                break
            result = await self._process(job)
            # Native/template runs (and any runner that omits ``used_llm``) are
            # refunded so only real provider calls count against the quota.
            if self._budgeter is not None and not result.get("used_llm"):
                self._budgeter.refund()
            processed += 1
        return processed

    async def _process(self, job: ImpulseJob) -> dict[str, Any]:
        try:
            result = await self._runner(job)
        except Exception as exc:
            logger.warning("agency impulse failed: %s", exc)
            result = {"ok": False, "error": str(exc)}
        if not isinstance(result, dict):
            result = {"ok": False}

        if result.get("ok", True) is not False:
            self._stats["processed"] += 1
            self._store_outcome(job, result)
            if job.kind == "sleep":
                self._sleeping.discard((job.player_id, job.save_id, job.sim_id))
                # v0.3 R3: sleeping invalidates the Sim's pending "next_sleep" intents.
                self._intents.note_sleep(job.player_id, job.save_id, job.sim_id)
            return result

        job.attempts += 1
        if job.attempts < MAX_ATTEMPTS:
            self._push_back(job)
            return result
        self._stats["failed"] += 1
        return result

    async def _runner(self, job: ImpulseJob) -> dict[str, Any]:
        if self._runner_override is not None:
            return await self._runner_override(job)
        return await self._default_runner(job)

    async def _default_runner(self, job: ImpulseJob) -> dict[str, Any]:
        """Standalone runner: rule-based unless a registry is attached."""
        world = self.world_context(job.player_id, job.save_id)
        return await build_impulse(
            job=job,
            profile={},
            world=world,
            memories=[],
            registry=self._registry,
            lang=job.lang,
            autonomy=self._autonomy_for(job),
        )

    def _autonomy_for(self, job: ImpulseJob) -> str:
        state = (self._world.get((job.player_id, job.save_id), {}).get("sims", {}) or {}).get(
            str(job.sim_id)
        )
        if state and state.get("autonomy"):
            return str(state["autonomy"])
        return self.default_autonomy or "semi"

    def _store_outcome(self, job: ImpulseJob, result: dict[str, Any]) -> None:
        """Store the runner's intents (or derive them from legacy directives)."""
        raw_intents = result.get("intents") or []
        stored: list[dict[str, Any]] = []
        if raw_intents:
            for raw in raw_intents:
                intent = self._coerce_intent(job, raw)
                if intent is not None:
                    self._intents.store(job.player_id, job.save_id, intent)
                    stored.append(intent)
        else:
            for raw in result.get("directives") or []:
                intent = intent_from_directive(
                    job.sim_id, raw, priority=job.priority, source="agent"
                )
                if intent is not None:
                    self._intents.store(job.player_id, job.save_id, intent)
                    stored.append(intent)
        if stored:
            logger.info(
                "intent(s) stored sim=%s job=%s kinds=%s",
                job.sim_id,
                job.kind,
                [intent.get("kind") for intent in stored],
            )

    @staticmethod
    def _coerce_intent(job: ImpulseJob, raw: Any) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        # Normalise through the directive converter when the raw shape is a tool call.
        if raw.get("name") and not raw.get("kind"):
            return intent_from_directive(job.sim_id, raw, priority=job.priority)
        from .intents import normalize_intent

        return normalize_intent(raw, default_sim_id=job.sim_id)

    # ── intent store ──────────────────────────────────────────────────
    def pull(
        self,
        player_id: str,
        save_id: str,
        *,
        sim_id: int | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Drain pending intents, optionally filtered by Sim, honoring ``limit``."""
        return self._intents.pull(player_id, save_id, sim_id=sim_id, limit=limit)

    def store_intents(
        self, player_id: str, save_id: str, intents: list[dict[str, Any]]
    ) -> int:
        """Store pre-validated intents (e.g. the sim<->sim dialogue channel)."""
        count = self._intents.extend(player_id, save_id, list(intents or []))
        if count:
            logger.info(
                "social intent(s) stored save=%s/%s kinds=%s",
                player_id,
                save_id,
                [intent.get("kind") for intent in intents or []],
            )
        return count

    def pending_count(self, player_id: str | None = None, save_id: str | None = None) -> int:
        return self._intents.pending_count(player_id, save_id)

    def world_context(self, player_id: str, save_id: str) -> dict[str, Any]:
        """Return the cached zone snapshot for a save (``{}`` if unknown)."""
        return self._world.get((player_id, save_id), {})

    def is_player(self, player_id: str, save_id: str, sim_id: int) -> bool:
        """True when the cached pulse marked the Sim as the player's own."""
        sims = self._world.get((player_id, save_id), {}).get("sims", {}) or {}
        state = sims.get(str(sim_id)) or {}
        return bool(state.get("is_player"))

    def note_interaction_seed(
        self,
        player_id: str,
        save_id: str,
        sim_id: int,
        target_id: int,
        *,
        interaction: str = "",
        interaction_text: str = "",
    ) -> None:
        """Remember that the player started a social interaction (v0.4 P4).

        The pulse often lacks the interaction target; the mod's player hook sees
        it directly and forwards it as a ``player_interaction`` event. The seed
        lets the next pulse open/continue a conversation session for the pair.
        ``interaction`` is the raw tuning name (may be a generic base like
        ``sim_Chat``); ``interaction_text`` is the localized label ("Contar
        piada"), which classifies more specifically (v0.5 R4 live fix).
        """
        try:
            sim = int(sim_id)
            target = int(target_id)
        except (TypeError, ValueError):
            return
        if sim == target or not sim:
            return
        self._interaction_seeds[(player_id, save_id, sim)] = (
            target,
            str(interaction or ""),
            str(interaction_text or ""),
            self._clock(),
        )

    def interaction_seeds(
        self, player_id: str, save_id: str, *, ttl: float = 180.0
    ) -> list[tuple[int, int, str, str]]:
        """Non-expired ``(sim_id, target_id, interaction, interaction_text)`` seeds."""
        now = self._clock()
        out: list[tuple[int, int, str, str]] = []
        for key, (target, interaction, text, ts) in list(self._interaction_seeds.items()):
            if key[0] != player_id or key[1] != save_id:
                continue
            if now - ts > ttl:
                self._interaction_seeds.pop(key, None)
                continue
            out.append((key[2], target, interaction, text))
        return out

    def consume_interaction_seed(
        self, player_id: str, save_id: str, sim_id: int, target_id: int
    ) -> None:
        """Drop a seed once its session has started (either direction)."""
        for sid in (sim_id, target_id):
            key = (player_id, save_id, int(sid))
            seed = self._interaction_seeds.get(key)
            if seed is not None and int(seed[0]) in (int(sim_id), int(target_id)):
                self._interaction_seeds.pop(key, None)

    def clear(self, player_id: str | None = None, save_id: str | None = None) -> None:
        """Drop queued/pending state for one save key, or everything."""
        if player_id is None or save_id is None:
            self._heap.clear()
            self._queued.clear()
            self._intents.clear()
            self.seats.clear()
            self._world.clear()
            self._sleeping.clear()
            self._last_impulse.clear()
            self._rr.clear()
            self.social._last_pair_at.clear()
            self.conversations._sessions.clear()
            self._interaction_seeds.clear()
            return

        key = (player_id, save_id)
        self._queued = {
            k: v for k, v in self._queued.items() if (v.player_id, v.save_id) != key
        }
        self._heap = [
            job for job in self._heap if (job.player_id, job.save_id) != key
        ]
        heapq.heapify(self._heap)
        self._intents.clear(player_id, save_id)
        self.seats.clear(player_id, save_id)
        self._world.pop(key, None)
        self._sleeping = {marker for marker in self._sleeping if (marker[0], marker[1]) != key}
        self._last_impulse = {k: v for k, v in self._last_impulse.items() if k[0] != key}
        self._rr.pop(key, None)
        self._interaction_seeds = {
            k: v for k, v in self._interaction_seeds.items() if (k[0], k[1]) != key
        }
        # Pair cooldowns are keyed by Sim ids only (no save context), so a
        # per-save clear leaves them alone rather than wiping other saves.

    # ── lifecycle ─────────────────────────────────────────────────────
    async def start(self) -> bool:
        """Start the async loop; no-op and False when already running."""
        if self.running():
            return False
        self._stopping = False
        self._task = asyncio.create_task(self._run(), name="sensewright-agency")
        return True

    async def _run(self) -> None:
        try:
            while not self._stopping:
                processed = await self.process_once()
                await asyncio.sleep(
                    AGENCY_INTERVAL_SECONDS if processed else AGENCY_IDLE_SECONDS
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("agency scheduler crashed: %s", exc)

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
        by_kind: dict[str, int] = {}
        for job in self._queued.values():
            by_kind[job.kind] = by_kind.get(job.kind, 0) + 1

        snap: dict[str, Any] = {
            "running": self.running(),
            "queued": len(self._queued),
            "by_kind": by_kind,
            "pending_directives": self.pending_count(),
            "pending_intents": self.pending_count(),
            "intents": self._intents.snapshot(),
            "level": self.level,
            "player_sim_level": self.player_sim_level,
            "cooldown_sim_minutes": self.cooldown_sim_minutes,
            "max_impulses_per_tick": self.max_impulses_per_tick,
            "impulse_frequency": self.impulse_frequency,
            "player_sim_impulse_frequency": self.player_sim_impulse_frequency,
            "reactions_enabled": self.reactions_enabled,
            "sleep_consolidation": self.sleep_consolidation,
            "seats": self.seats.snapshot(),
            "social": self.social.snapshot(),
            "speech": self.speech.snapshot(),
            "presence": self.presence.snapshot(),
            "conversations": self.conversations.snapshot(),
            "world_contexts": len(self._world),
            "processed": self._stats["processed"],
            "failed": self._stats["failed"],
            "submitted": self._stats["submitted"],
            "dropped": self._stats["dropped"],
        }
        if self._budgeter is not None:
            snap["budget"] = self._budgeter.snapshot()
        return snap


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _relationship_delta(session: Any) -> float:
    """A small relationship nudge proposed by a conversation's tone."""
    tone = str(getattr(session, "tone", "") or "").lower()
    if tone in ("tense",):
        return -0.2
    if tone in ("flirty", "romantic"):
        return 0.15
    if tone in ("funny", "warm", "friendly"):
        return 0.1
    return 0.05
