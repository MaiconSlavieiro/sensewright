# Sensewright v2 — Runtime Reliability & Concurrency Hardening Plan

> **Date:** 2026-10-02
> **Branch:** `v2-remake`
> **Basis:** production audit of the 2026-10-02 18:31–18:37 session (save `1488584711`) — `lastException.txt`, `mod_logs/Sensewright_Worker.log`, `sidecar/data/logs/sensewright-sidecar.log`, `slot_1488584711.*.db`.
> **Goal:** fix the runtime defects, thread-safety gaps and LLM-pressure issues found in the audit, and harden the mod↔sidecar concurrency model without changing the HTTP contract.

This document is the execution roadmap for the hardening work. Each item lists what exists
today (`file:line`), the concrete action, the affected files, and verification. It complements
[`plan.md`](plan.md) (feature gaps); this one is scoped to defects and concurrency.

---

## 1. Principles and constraints

- **Two interpreters.** The Mod runs on **Python 3.7.0**: `walrus (:=)`, `match/case`,
  union `X | Y`, `f-string =`, and `from __future__ import annotations` are forbidden. The
  sidecar is Python 3.10+.
- **Thread model.** In the Mod, `GAME_TICK` only reads state and dispatches events; HTTP lives
  in a dedicated worker thread that never touches the game API. The sidecar serializes state
  behind `AppState._lock`; LLM runs on scheduler workers.
- **Shadow DB.** `working.db`/`committed.db`; a false rewind must never destroy recent
  memories. Session-bound jobs must never write into a newer session's store.
- **Engine facade.** Isolate EA's volatile API in helpers so patches hit a single location.
- **Defensive.** `try/except Exception` + `sims4.log.Logger` in hooks; `trace_id` end to end;
  async callbacks are epoch-guarded.
- **Per-phase delivery:** code → tests → `py -3.7 -m py_compile` (Mod) →
  `python mod/build.py` / `python mod/build_package.py` → `docs/status.md`.
- **Compatible HTTP contract.** New endpoints/intents are additive; the existing contract does
  not break. Intent normalization degrades to `command` safely.

### Status legend

- ⬜ Pending · 🟡 In progress · ✅ Done

---

## 2. Audit findings (evidence base)

| # | Finding | Evidence |
|---|---------|----------|
| A | `_execute_approach` calls a non-existent API (`push_route_to_target`) → NPC routing always fails | `lastException.txt` 18:34:12 |
| B | Custom visit situation crashes (`default_job` missing → `no_show_action` on `None`) → falls back to native | `lastException.txt`; S4CL `common_sim_situation_utils.py:331` |
| C | `HOUSEHOLDS_AND_SIMS_LOADED` re-fires `session-start` + census several times per session | sidecar log 18:33:53 / 18:34:00 |
| D | Save tick read at `GAME_SAVE` (post-serialization) → ~68-tick drift → recurring false rewinds | `save_vault` warnings all day |
| E | ~106 `/events` flooded the single FIFO queue; `session-start` waited ~100 s; `mem.legacy` lost (store None); 108 `sim.reaction` (58 failed) | sidecar log 18:32:16–18:34; only 2 "lifecycle → mem.legacy" lines |
| F | TOCTOU in `god.plan` → 2 duplicate active arcs, stuck at beat 0 | DB `arcs` (2 `active`, beat=0) |
| G | Autonomy-tick state mutations unlocked; store close/replace races bg callbacks | `services.py:218-301`; `save_vault.py:71-121` |
| H | `mem.consolidate` has zero triggers (`silence_consolidate_seconds` is dead config); `consolidated`/`sleep_reflection`/`compact` = 0 in DB | grep: endpoint exists, nothing calls it |
| I | LLM under pressure: 161 impulses, 93 `all routes failed`, 300 s bench cooldown, sync reaction blocking HTTP | sidecar log |

---

## 3. Architecture decisions

- **Session state machine** (Mod): distinguish *new session* from *zone-transition*; reset on
  `CLIENT_DISCONNECT` / `GAME_LOAD`.
- **Mod HTTP queue = two lanes + atomic slot** (verdict: strictly better than `PriorityQueue`
  — drop-oldest in O(1) and isolated backpressure).
- **Session epochs**: mandatory guard against obsolete jobs writing into `working_store`.
- **Strict rewind tolerance** (3–5 sim-min = 3000–5000 ticks), backed by the `GAME_PRE_SAVE` tick.
- **Reaction async in the realtime tier** (not bg), delivered via a light intent pull.
- **Marriage events**: silent snapshot at load/census (no wall-clock window).

---

## Phase 0 — Schema verification (prerequisite for the XML fix)

### 0.1 Verify situation tuning schema ⬜

- **Exists:** `scripts/decompile-scripts.ps1`; no local decompiled situation tunings.
- **Action:** decompile and inspect `situations/situation.py` (`_default_job`, `duration`),
  `situations/situation_job.py` (`no_show_action`), `situation_guest_list.py:79`
  (`construct_from_purpose`).
- **Verify:** exact tunable names + the situation-job instance id to reference.

---

## Phase 1 — Mod: lifecycle and save clock

### 1.1 Session state machine ✅

- **Exists:** `main.py:197-226` sends `session-start` + census on every
  `HOUSEHOLDS_AND_SIMS_LOADED`; no distinction from `ZONE_LOAD`.
- **Action:** track `_in_active_session: bool` + `_last_zone_id: int`.
  - `CLIENT_DISCONNECT` (main menu) and `GAME_LOAD` → `_in_active_session = False`.
  - `HOUSEHOLDS_AND_SIMS_LOADED`: `False` → `session-start` + census, set `True`;
    `True` → treat as zone-transition only (or skip if `ZONE_LOAD` already covered).
  - `ZONE_UNLOAD` → keep the session; clear zone intents.
- **Verify:** one `session-start` per session; reloading the *same* save via the main menu
  produces a clean session-start.
- **Done:** `_in_active_session` + `_last_session_save_id` + `_last_session_tick`; a repeat
  firing is ignored and a same-save reload that rolls the clock back starts a fresh session.
  Optional `CLIENT_DISCONNECT`/`GAME_LOAD` handlers are registered only when the CoreEvent
  member exists (guarded via `getattr`), so a missing enum member cannot abort the import.

### 1.2 Pre-save tick with monotonic guard ✅

- **Exists:** `main.py:254-270` reads the tick in `GAME_SAVE` (post-serialization).
- **Action:** `GAME_PRE_SAVE` stores `_pending_save_tick` + `time.monotonic()`; `GAME_SAVE`
  consumes it only if age < 30 s (covers a cancelled "Save As…" or a failed save), otherwise
  reads the current tick; clear the variable right after posting.
- **Verify:** no `rewind requested` on the next load of the same save.
- **Done:** pre-save captures the clock; `GAME_SAVE` consumes it when fresh (< 30 s) and falls
  back to the post-serialization tick otherwise.

---

## Phase 2 — Sidecar: rewind, idempotency and epochs

### 2.1 Strict rewind tolerance ✅

- **Exists:** `save_vault.py:97-103` compares `world_sim_tick < committed_tick` strictly;
  `_rewind_to_tick` at `:203-230`.
- **Action:** add `REWIND_TOLERANCE_TICKS = 3000` (3 sim-min; configurable). Only a negative
  delta larger than tolerance counts as an intentional reload → restore committed/ring buffer.
  Log the decision (skip/restore/surgical).
- **Verify:** unit test — drift < 3 min skips rewind; a 2 h rollback restores the snapshot.
- **Done:** `REWIND_TOLERANCE_TICKS` default 3000, overridable via
  `gameplay.rewind_tolerance_ticks`; drift ≤ tolerance is logged and skipped, a larger rollback
  restores the nearest ring snapshot (or surgical) and reports `rewound=True`.

### 2.2 `last_processed_tick` bound to rewind ✅

- **Exists:** no `last_processed_tick` yet (introduced in 2.3).
- **Action:** on `session-start` and any real rewind, set
  `state.last_processed_tick = restored_tick` under the same lock — never silently drop
  autonomy ticks for hours after a rollback.
- **Done:** `handle_session_start` seeds `last_processed_tick` from the restored tick (or the
  current tick on a clean/new session) under the state lock.

### 2.3 Tick idempotency ✅

- **Exists:** `services.py:527` `handle_autonomy_tick` has no tick guard.
- **Action:** ignore ticks `<= state.last_processed_tick` (locked), honoring the reset from 2.2.
- **Done:** `AppState.accept_tick` atomically rejects stale/duplicate ticks; the handler returns
  `duplicate_tick=True` while still draining already-ready intents.

### 2.4 Mandatory session epoch ✅

- **Exists:** `state.py:153-172` `reset_ram`; no epoch concept.
- **Action:** add `state.session_epoch`, incremented in `reset_ram()` and on any rewind. Every
  scheduled job captures the epoch; **every async callback validates
  `job.epoch == state.session_epoch` before touching `working_store()`** — mismatch logs
  `stale_epoch_dropped` and returns.
- **Verify:** unit test — a job from session A never writes into session B's store.
- **Done:** `session_epoch` bumps in `reset_ram` and on a real rewind; `state.guard_callback`
  wraps every async callback (cognition/dream/sleep/reflect/diary/chronicle/impulse/social/
  reaction and all god callbacks) and drops stale ones with a `stale_epoch_dropped` counter.

---

## Phase 3 — Concurrency

### 3.1 God TOCTOU → single active arc ✅

- **Exists:** `god/orchestrator.py:117-131` schedules `god.plan` while `active_arc is None`;
  `_plan_callback` at `:46` sets it only asynchronously.
- **Action:** set an `arc_planning` flag synchronously (under lock) when scheduling; clear it in
  the callback (success/failure); `god_tick` checks `active_arc or arc_planning`; epoch-guard the
  callback.
- **Verify:** one active arc; test — a burst of two ticks yields exactly one `god.plan`.
- **Done:** `try_begin_arc_plan`/`end_arc_plan` claim the slot atomically under `_lock`;
  `_plan_callback` releases it in a `finally`, and the callback is epoch-guarded.

### 3.2 Single-flight without losing edges ⬜

- **Exists:** `services.py:527-642` does edge detection and LLM dispatch in one path.
- **Action:** split `handle_autonomy_tick` into (a) **mandatory ingestion** (always, locked):
  delta merge, sleep transitions (`is_sleeping` → `sim.dream`/`sim.sleep`), end-of-day, seats,
  intent drain; (b) **optional LLM dispatch** guarded by a non-blocking single-flight flag
  (impulses/social/god). Sleep/wake triggers are never lost.
- **Verify:** a busy tick still records sleep transitions.

### 3.3 Mod HTTP queue — two lanes + atomic slot ✅

- **Exists:** `http_client.py:190-222` single FIFO `_outbound_queue`, `sleep(0.01)` polling,
  one request at a time, global 60 s timeout.
- **Action:**
  - `_realtime_q` (`queue.Queue(maxsize=64)`): attach/session-start/census/save/zone-transition/
    chat/hey/events/beat-ended; on overflow drop only stale `events`, never lifecycle/chat.
  - `_latest_tick` (`collections.deque(maxlen=1)`): autonomy/tick with **producer-side
    coalescing** — merge `sims_delta` by `sim_id` (last value per field) before replacing the
    slot; `player-activity` the same.
  - Wake-up via `threading.Event` (`.set()` on every write; `wait(timeout=0.5)`); drain
    `_realtime_q` first, then the slot; per-endpoint timeouts (chat/hey 20 s, lifecycle 10 s,
    autonomy 15 s).
- **Verify:** `session-start` processed < 5 s even under an event burst; no busy polling.
- **Done:** bounded realtime deque (drops events only, cap 48) + per-endpoint coalescing slots
  (sims_delta merged by `sim_id`), `threading.Event` wake-up, per-endpoint timeouts, and a
  read-only `qsize()` view for the panel. Lifecycle/chat are never silently dropped.

### 3.4 Marriage spam — snapshot, not timer ✅

- **Exists:** `lifecycle_hooks.py:100-116` emits a `marriage` event for every relationship bit
  matching the markers, including the rehydration burst at load.
- **Action:** during census/`HOUSEHOLDS_AND_SIMS_LOADED`, build a silent snapshot of existing
  `(sim_a, sim_b, bit_id)` pairs into `_known_marriage_pairs` (no events). Only emit `marriage`
  for new transitions not in the snapshot, and only when `clock_speed > 0`.
- **Verify:** event count on load < ~10; no wall-clock window.
- **Done:** `begin_marriage_snapshot`/`end_marriage_snapshot` bracket the census; the handler
  records pairs silently and emits only for unseen pairs while the clock runs.

### 3.5 Store race hardening 🟡

- **Exists:** callbacks hold stale `SqliteStore` references across `save_vault._close_working`
  (`save_vault.py:71-121`).
- **Action:** resolve the store via `state.working_store()` at use time; catch
  `sqlite3.ProgrammingError` ("closed database") with a `store_closed` log; rely on the epoch
  guard (2.4) for cross-session safety.
- **Partial:** `SaveVault.save` now drops `_working_store` to `None` before the copy/reopen
  window, so concurrent callbacks resolve `None` instead of a closed handle; callbacks already
  resolve the store at use time and the epoch guard drops cross-session writes. An explicit
  `sqlite3.ProgrammingError`/`store_closed` log is still pending.

### 3.6 Atomic rate limiter ✅

- **Exists:** `llm/limits.py:54-69` — `can_accept` and `record_request` are separate locks
  (check-then-act overshoot).
- **Action:** single `try_accept_and_record()` under one lock.
- **Done:** `ProviderRateLimiter.try_accept_and_record` performs the capacity check and records
  the dispatch atomically; `ProviderChain.run` uses it.

---

## Phase 4 — LLM pressure and memory

### 4.1 Impulse throttle + backpressure ✅

- **Exists:** `services.py:583-604` schedules up to `MAX_IMPULSES_PER_TICK = 3` per tick.
- **Action:** per-sim cooldown (`last_impulse_tick`, 60 sim-min, configurable); reduce
  `MAX_IMPULSES_PER_TICK` when `scheduler.status()['queue_depth']` exceeds a threshold.
- **Done:** `gameplay.impulse_cooldown_sim_minutes` (default 60) gates each sim and
  `gameplay.impulse_backpressure_queue_depth` (default 6) drops the per-tick budget to 1.

### 4.2 `sim.reaction` realtime-async ✅

- **Exists:** `services.py:880` runs `sim.reaction` synchronously on the HTTP thread.
- **Action:** add `submit_async` with a dedicated realtime worker (semaphore 2), dedup by
  `(sim, category, tick)`, epoch-guarded callback. Intents are enqueued in state as today.
- **Verify:** `/v1/events` returns without blocking on provider latency.
- **Done:** `LLMScheduler.submit_async` runs on a `ThreadPoolExecutor(max_workers=2)`;
  `handle_event` schedules the reaction with a `sim:category:tick` dedup key and an
  epoch-guarded callback that enqueues intents.

### 4.3 Light intent pull ✅

- **Exists:** intents are only drained by the next `/v1/autonomy/tick` response
  (`services.py:635`) or `GET /v1/autonomy/intents` (`routers/autonomy.py:25-27`).
- **Action:** the Mod worker does a light `GET /v1/autonomy/intents` when both lanes are empty,
  with exponential backoff 2 s→10 s (reset on intents). Reactions/narration reach the game in
  seconds, not up to 15 s.
- **Done:** the worker pulls when idle (gated on session-start), backs off 2 s→10 s, and hands
  the response to the main thread so the IntentBus is only touched there.

### 4.4 Chain health ✅

- **Exists:** `llm/chain.py:33` `INVALID_OUTPUT_COOLDOWN_SECONDS = 300`; no purpose-level breaker.
- **Action:** make the bench cooldown configurable (120 s default); add a per-purpose breaker
  after `all routes failed` (direct fallback for N min); expose state in `/v1/status`.
- **Done:** `llm.invalid_output_cooldown_seconds` (default 120) and
  `llm.purpose_cooldown_seconds` (default 120); a purpose whose routes all failed is
  short-circuited to the fallback and reported by `ProviderChain.status` → `/v1/status`.

### 4.5 Close the `mem.consolidate` black hole ✅

- **Exists:** `routers/memory.py:27` endpoint; `services.py:989-1004` `handle_consolidate`;
  `silence_consolidate_seconds=300` never read; no caller anywhere.
- **Action:** trigger consolidation on (a) `zone-transition` (consolidate before clearing),
  (b) `lifecycle/save` **before** the working→committed backup, (c) silence check in the
  autonomy tick (`chat_last_tick` vs wall-clock). Revisit the `salient_since_sleep`/
  `evo.reflect` gates so `sleep_reflection` actually persists.
- **Done:** consolidation runs on zone-transition and save (bounded batches), a silence trigger
  runs one quiet chat thread per autonomy tick using `silence_consolidate_seconds`, and the
  wake reflection (`sim.sleep`) is no longer gated behind a salient event.

---

## Phase 5 — Observability and tests

### 5.1 Metrics ✅

- **Exists:** `services.py:1136-1158` `status()`; no runtime counters.
- **Action:** add counters to `/v1/status` and the worker log: intents per kind (ok/fail),
  LLM failures per purpose, session resets, rewinds, `stale_epoch_dropped`, `store_closed`,
  lane depths, current epoch.
- **Done:** `/v1/status` exposes `metrics` (session resets, rewinds, duplicate ticks,
  intents emitted/drained, stale-epoch drops), `session_epoch`, `last_processed_tick` and
  `arc_planning`; `LLMScheduler.status`/`ProviderChain.status` expose purpose cooldowns.

### 5.2 Regression tests ✅

- **Action:** extend `sidecar/tests`: rewind tolerance (drift→skip; 2 h rollback→restore +
  `last_processed_tick`); god single-flight; epoch guard; slot coalescing (merge by sim_id);
  impulse throttle; worker lanes; marriage snapshot; tick idempotency.
- **Done:** `sidecar/tests/test_hardening.py` covers rewind tolerance (skip/restore), tick
  idempotency, epoch guard, god single-flight, atomic rate limiter and the purpose breaker.
  Mod lane coalescing/marriage snapshot are validated by the `py -3.7` compile + manual
  playtest (Phase 6.2).

---

## Phase 6 — Build, deploy and playtest

### 6.1 Build & test ✅

- **Action:** `pytest` (sidecar) + `make test` (`py -3.7` syntax) + `make install`.
- **Done:** `pytest` 535 green; `py -3.7 -m py_compile` clean; `build_package.py` (42 tunings)
  and `build.py` (88,405 bytes) rebuilt. `make install` pending the in-game pass.

### 6.2 In-game validation ⬜

| Scenario | Expected | Status |
|---|---|---|
| Load `1488584711` | clean load; no new `lastException.txt` | ⬜ |
| `spawn_npc` | `situation: custom`; NPC routes to the target | ⬜ |
| Chat | reply < 10 s; "…" balloon closes on timeout | ⬜ |
| Reload same save (main menu) | clean session-start; no false rewind | ⬜ |
| Real rollback (> 5 sim-min) | rewind triggers; `last_processed_tick` reset | ⬜ |
| Impulses | spaced, not bursty | ⬜ |
| God Director | exactly 1 active arc | ⬜ |
| Memory | `consolidated`/`sleep_reflection` present after sleep/consolidate | ⬜ |

> **Deploy note (2026-10-03):** the hardening build was installed and playtested. The runtime
> fixes held (`rewind` 18 → 0, `all routes failed` 146 → 2, `stale_epoch_dropped` active), but
> the playtest surfaced **new, previously unmapped bugs** (dialogue never triggers, stale
> duplicate arcs, beats without a liveness timeout). They are catalogued in
> [`bugs.md`](bugs.md) and must be fixed before the Phase 6.2 table can pass.
>
> **Update (2026-10-03, second pass):** BUG-01/02/03 are **fixed** with regression tests
> (`sidecar/tests/test_bugs.py`) and the build was regenerated. The Phase 6.2 table below is
> now ready to run in-game; only the manual playtest remains.

### 6.3 Post-session audit ⬜

- **Action:** re-inspect `lastException.txt`, `Sensewright_Worker.log`, sidecar log and DB
  (memory types, active arcs, rewinds) — the same protocol as the original audit.

---

## 3. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Marriage snapshot depends on the relationship-tracker API | Medium | Validate in playtest; fallback = per-pair dedup with a sim-clock window |
| Slot coalescing loses sub-pulse sleep edges | Low | Last-value-per-sim merge; already a pre-existing limitation |
| XML tunables differ across game builds | Medium (Phase 0/1) | Decompile first; native fallback stays intact |
| New realtime-async worker adds threads | Low | Semaphore 2; epoch-guarded callbacks |
| Intent pull adds localhost traffic | Low | Exponential backoff 2 s→10 s |

---

## 4. Plan completion criteria

1. Phases 0–5 items ✅ with green tests (`pytest` + `py_compile` 3.7 + builds).
2. Phase 6.2 executed in-game with the table filled in.
3. `docs/status.md` updated with the hardening outcomes.
4. No new `lastException.txt` entries and no false rewinds in the post-session audit.

---

## 5. Progress

- [ ] Phase 0 — schema verification
- [x] Phase 1 — Mod: lifecycle & save clock
- [x] Phase 2 — Sidecar: rewind, idempotency, epochs
- [ ] Phase 3 — concurrency (3.2 pending, 3.5 partial)
- [x] Phase 4 — LLM pressure & memory
- [x] Phase 5 — observability & tests
- [ ] Phase 6 — build, deploy & playtest (code done; in-game pending)
