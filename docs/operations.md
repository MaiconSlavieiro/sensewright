# Operations & Reliability

Runtime reliability material: the architectural review and evolution plan, the concurrency/thread-safety hardening plan, the catalog of bugs found in deploy/playtest, and the weak-point remediation wave.

> ⚠️ **CRITICAL ARCHITECTURAL IMPERATIVE:** The "Architectural Review & Evolution Plan" and the "Hardening" tickets (P1, P2, P17, P20) described below are NOT secondary technical debt. Because TS4 is strictly single-threaded, any latency or IPC flaw breaks the core gameplay loops. Agents MUST treat these items as primary blockers that halt feature development until resolved.

**On this page**

- [Architectural Review & Evolution Plan](#architectural-review--evolution-plan)
- [Runtime Reliability and Hardening](#runtime-reliability-and-hardening)
- [Bugs and Playtest Findings](#bugs-and-playtest-findings)
- [Weak-Point Remediation](#weak-point-remediation)

---

## Architectural Review & Evolution Plan

> **2026-10-03.** Critical audit of the specification, the operational state, the concurrency
> model and the MCP/Rules expansion. Focus: implicit contradictions, second-order bottlenecks,
> EA/TS4 coupling failures, and lean evolution — not cosmetic validation.

### Diagnosis — operational truth vs. documentation

The foundation (Mod Python 3.7 ↔ Sidecar Python 3.10+, Shadow DB ring buffer, manifest-driven
i18n, ProviderChain with RPM/RPD/TPM) is of very high quality. Cross-document analysis exposes
four structural pathologies that must be stopped before any expansion.

**D1. Documentation drift [RESOLVED].** The static sections previously contradicted the changelogs, but this has been fixed in the latest documentation pass. The tests now count 763, and all implemented purposes like `god.cast`, `god.react`, and `mem.legacy` are correctly marked as Full.

**D2. The "coding blind" trap (reliability asymmetry).** The Sidecar has 689 automated tests;
the Mod layer was extensively coded "blind" against reference clones. 100% of the severe
production blockers came from false assumptions about Maxis/S4CL internals:
`from sims4.sim import Sim` aborting boot; `mood_type` needing `<E>` not `<T>` (UI crash
`BuffInfo/MoodKey()`); `Sim.social_group` not existing on `Sim` (it lives on interactions in
`si_state`); `Relationship.target_sim_id` not existing (`sim_id_a`/`sim_id_b`);
`definition.name` returning `None` on native objects. The bottleneck is not Sidecar cognition
but the fragility of reflection/introspection inside TS4's Python 3.7 runtime. **Resolution:** We have instituted [Spike-Driven Development](spike-strategy.md) using an in-game `sw.spike` / `sw.smoke_test` harness to test isolated API calls before wiring them to production logic.

**D3. False sense of control (open-loop actuation).** The `IntentBus` is fire-and-forget. When
the Sidecar emits `approach`/`spawn_npc`/`interact` it assumes success once the HTTP payload
reaches the Mod. If physical routing fails in the engine (locked door, pool in the way, tuning
collision, native-autonomy cancellation) the Sidecar never learns of the failure, corrupting
the God Director's narrative coherence.

**D4. Strategic priority inversion with the MCP layer.** Building 3 MCP servers + a rules DSL
before closing Phase 5 in-game validation violates substrate stability. The MCP servers are
facades over the Mod levers; if the native levers (VisitSituation, `queue_interaction`,
TooltipComponent, physical books) have not passed the in-game checklist, MCP only gives external
agents a standardized interface to broken or silent functions.

### Critical problems & second-order impacts

**PC-01 — The outcomes paradox (semi-open loop).** [`mcp.md`](mcp.md) proposes an Action Gateway
with an `outcome` ledger (`applied|failed|expired`), but the described flow enqueues the intent
in `AppState.enqueue_intents` and records the result **in the Sidecar**. The Sidecar does not
know whether the intent actually ran; `tool_executor.execute(intent)` runs on the TS4 main
thread several ticks later, and **no** `POST /v1/autonomy/outcomes` channel exists today. An MCP
agent would receive `"applied"` when the intent only entered the Sidecar's RAM queue — false
success telemetry perpetuating the operational blindness (C2 of the MCP doc).

**PC-02 — Network thread proliferation in the game process (Python 3.7).** Originally
`REQ-ARCH-01` required a single daemon worker thread for all HTTP I/O. Hardening + the MCP plan
add three concurrent threads: the outbound worker, the intent-pull loop (2–10 s), and the SSE
streaming thread (`urlopen(..., timeout=None)`). `timeout=None` blocks `recv()` indefinitely on
Windows; if the Sidecar hangs without closing the socket, the thread never wakes on
`_shutdown_event.set()` and can hang `TS4_x64.exe` shutdown. If the SSE thread and the pull
thread drain the Sidecar queue concurrently without strict transactional coordination, there is
a race on `_pending_intents` consumption or duplication in `_inbound_intents_queue`.

**PC-03 — Async event-loop blocking (FastAPI/uvicorn).** The Sidecar runs on a single-threaded
asyncio loop, but much of `services.py`/`ProviderChain`/`SqliteStore` uses synchronous primitives
(`threading.Lock` in `AppState._lock`, `ThreadPoolExecutor`, SQLite). Mounting 3 FastMCP ASGI
apps plus persistent `EventSourceResponse` connections means any direct `AppState._lock`
acquisition or synchronous DB call on a FastAPI coroutine blocks the whole loop — stalling SSE
chunks (the <1 s Phase 0a requirement) and the Mod health check.

**PC-04 — Sovereignty conflict (rules × agency × SOVEREIGN_AGENT).** The MCP doc gives `agency`
and the internal engine (`sim.impulse`/`sim.social`) the same priority-3 `SOVEREIGN_AGENT` lease
while `rules` fires actions every tick with `authority="rules"`. If an external client drives a
Sim via `/mcp/agency` while `handle_autonomy_tick` fires an impulse and a user rule triggers in
the same minute, all share the same lease priority: the Sim's queue thrashes (walks to an object
for MCP, changes mood/target for the impulse, talks to itself for the rule).

**PC-05 — Context saturation & semantic drift (33 purposes).** Many purposes accumulate into
`PROFILE_SHAPE` and the DB (`psyche_blocks`, `daily_plan`, `dream_urge`, `life_story`,
`qualitative_note`, `ambition`, `scene_subtext`, `known_secrets`, rumors). On 30+ Sim-day saves
the `ContextAssembler` (hard 700-token realtime / 1500 interactive ceiling) suffers destructive
compression or silent truncation: the format anchors (`one_shot` + `strict_language_anchor`) get
crushed, or the scene hints added in Playtests #3/#4 (`location_hint`, `relationship_hint`,
`action_hint`, `family_hint`) consume the whole realtime budget, leaving nothing for FTS5
memories and personality.

**PC-06 — Free-model fragility with strict JSON schemas (NOTE-01/02).** Dozens of `all routes
failed`/`unusable output` failures came from free/reasoning models emitting `<think>` blocks,
markdown fences around JSON, or slightly-off keys. The current mitigation (bench the model 120 s
+ per-purpose circuit breaker) protects latency but silently downgrades play to static 0-key
templates for much of the session — the user believes the LLM is generating dynamic content
while it is reading static fallbacks because the validator rejected the reply over syntactic
rigidity.

**PC-07 — TS4 save corruption/bloat via Sim/object creation.** The spec creates the hidden
Confidant SimInfo, catalyst Sims in `god.cast` when no townie matches, physical autobiography
books (P11), and `god.spawn_object`. Playtest #4 already proved the danger: a small hidden-household
search bug produced 21 duplicate "Confidente Sensewright" Sims in the player's real `.save`.
Unlike the Sidecar SQLite (Shadow DB, clean rollback), objects/SimInfo instantiated in the TS4
zone are serialized permanently into EA's binary `.save`. On uninstall or error, the player's
save is polluted with ghost Sims or orphan objects.

**PC-08 — Boot-time load event storm.** Lifecycle events (death, marriage, relationship-bit
rehydration) fire before `session-start` is processed. They arrive at `epoch=0`, fill the Mod's
48-slot realtime lane (`Realtime lane saturated; dropping event`), and are discarded when
`session-start` bumps to `epoch=1` (`stale_epoch_dropped`). A real event in the first seconds of
loading is lost.

### Recommendations & best practices

**R1. Close the control loop (closed-loop intent telemetry).** Do not treat an intent as done
when it leaves the Sidecar; confirm execution in batch:

- Mod (`intent_bus.py`/`tool_executor.py`): when an intent finishes (or expires by TTL / fails
  after `max_retries`), append a light record to `_completed_outcomes`:
  `{intent_id, action_id?, status: "applied"|"failed"|"expired"|"preempted_by_player", reason,
  sim_tick}`.
- Transport: do **not** issue one HTTP request per intent. Attach `outcomes: [...]` to the
  existing `POST /v1/autonomy/tick` payload (and allow immediate `POST /v1/actions/outcomes`
  only when an MCP call awaits a synchronous/SSE response).
- Gain: the Action Gateway, `god.puppeteer` and `LLMScheduler` know with certainty whether the
  NPC reached the target or failed (`routing_failed`), enabling real adaptive reaction.

**R2. Unify the sidecar→mod transport (SSE + heartbeat + short socket timeout).** Eliminate the
pull/stream thread competition: keep only **2 threads** in the Mod — the outbound worker and a
single inbound delivery thread with a state machine:

- Connect to `GET /v1/autonomy/stream` with `timeout=15.0` (**never** `timeout=None`).
- The Sidecar sends `: keepalive` every 5 s; if the Mod sees 15 s of silence, `socket.timeout`
  fires, allowing a safe `_shutdown_event.is_set()` check each cycle (instant, non-hanging exit).
- Integrated fallback in the same thread: only after 2 failed SSE connections, the same thread
  degrades to `GET /v1/autonomy/intents` (3 s→10 s) until the SSE reconnects. Zero race between
  pull and stream.

**R3. Game Engine Facade + in-game introspection harness (`sw.smoke_test`).** Stop discovering
TS4/S4CL API differences by 15-minute playtest trial-and-error:

- Total isolation (`engine_facade.py`): no feature file (`object_interactions.py`,
  `visit_situation.py`, `lifecycle_hooks.py`, `native_hooks.py`) imports EA (`sims4.*`,
  `services`, `objects.*`, `situations.*`) or S4CL directly; all go through typed, defensive
  functions in `mod/sensewright_mod/engine_facade.py` (populated via [Spike-Driven Development](spike-strategy.md)).
- Diagnostics (`sw.smoke_test` / `sw.spike`): a console/Quick Menu command that runs a deterministic
  self-test on the active lot in ~2 s (no LLM) and writes `mod_logs/Sensewright_SmokeTest.json`:
  the 46 tuning resources are loaded in `InstanceManager`; the active Sim's `age`/`gender`/
  `family_links`/`social_group`/`room_id`/`mood`/`relationships` return valid types; mirror/
  mailbox/diary resolution works on the current lot; one emotion buff applies and removes
  silently. Collapses BUG-01..17 discovery from hours to ~3 s after loading a save.

**R4. Dynamic ContextAssembler budget (token priority packing).** Prevent the scene hints from
overflowing the 700-token realtime tier with a knapsack packer:

- **P0 (inviolable, ~220 tok):** lean system persona (`core_personality`+`current_demeanor`+
  `speech_style`) + immediate state (`mood`, `action_hint`, `location_hint`) + `one_shot` +
  `strict_language_anchor`.
- **P1 (contextual, ~200 tok):** `relationship_hint` (with delta) + `puppeteer_objective`/
  `scene_subtext` (when active) + last 2 history turns.
- **P2 (elastic, fills the remainder):** `family_hint` (only when relevant), `memories_fts`
  (K=5→2 on realtime), `dream_residue`.
- Add a parameterized unit test asserting all 33 purposes, filled with maximal realistic
  pt-BR data, respect `in_tokens`.

**R5. Tolerant LLM output parser (structured output repair).** Eradicate the fallback cascade on
free models (NOTE-01/02) with a zero-latency local repair layer (`llm/json_repair.py`) run
**before** declaring `unusable output`:

- Strip `<think>…</think>` / `<reasoning>…</reasoning>` blocks and markdown ``` fences.
- Fix trailing commas before `}`/`]`.
- Coerce equivalent near-miss keys / fill missing optional fields from that purpose's schema
  defaults (don't discard a whole generation because `"impact": 0.5` was omitted).
- Use native `response_format: {"type":"json_object"}` automatically on all `{json_only}`
  purposes for providers that support it (openrouter, gemini, groq, ollama).

This keeps dynamic generation alive instead of silently degrading to static templates.

**R6. Decoupled, lease-aware rules subsystem.** Keep the `rules` facade concept but separate
event triggers from per-tick evaluation with an explicit lease so it cannot fight the engine:

- Add a **`RULE_AUTOMATION`** lease to the Coordinator matrix, below `GOD_CATALYST_PUPPET`,
  allowed to emit **Soft Influence only** (or act only when the Sim is `idle`, honoring the
  Survival & Punctuality Guard of REQ-IMP-03).
- **Trigger indexing:** the `ConditionEngine` must not scan all 32 rules linearly every
  `autonomy_tick`. Maintain in-memory indexes in `AppState`: `rules_by_trigger["tick"]`,
  `rules_by_trigger["event:<category>"]`, `rules_by_trigger["need"]`.

**R7. Pre-session event buffer (load-time gate).** Fix the boot ordering:

- In the Mod (`main.py`/`lifecycle_hooks.py`), while `_in_active_session == False` (until the
  `POST /v1/lifecycle/session-start` returns `ok: true`), **block** hydration-event emission and
  hold only genuine events in a local buffer (max 8 items), dispatching them only after
  `session-start` confirms the active `session_epoch`.

**R8. Zero-save-pollution policy for Sims/objects.** Golden rule: the Mod must never create new
persistent `SimInfo` for `god.cast` when the world has **>5 available townies** — force `god.cast`
to reuse census townies in ~99% of cases. For the Hidden Confidant SimInfo: beyond the
last-name search, persist `player_confidant_sim_id` in the `metadata` table of
`slot_<save_id>.committed.db`; on `session-start` the Sidecar returns that save's exact
`player_confidant_sim_id` to the Mod, removing string-search heuristics, plus a one-shot GC
routine to purge the 20 orphan confidants created in earlier tests.

### Restructured execution roadmap

> **Superseded in detail (2026-10-05):** Stage 1 is done; the revalidated order is in
> [Recommended execution order](#recommended-execution-order-2026-10-05).

The previous plan advanced hooks P2, UI P4 and the MCP layer in parallel. Reordered by the
stability critical path — each layer lands on a 100%-validated base.

**Stage 1 — Spike-Driven Development (SDD) & State Sanitation.**
1. **Spike Harness**: Implement the `sw.smoke_test` / `sw.spike` command (R3).
2. **Execute Observability Probes**: Run the 4 centralized Data Probes (`spike_interaction_probe`, `spike_ui_injection_probe`, `spike_routing_probe`, `spike_relationship_probe`) to dump ground-truth engine data to logs and in-game UI. See [`spike-strategy.md`](spike-strategy.md).
3. Persist `player_confidant_sim_id` in the SQLite `metadata` + a cleanup script (purge the duplicated confidants from test save `1488584711`).
4. Pre-session event gate (R7).
5. `outcomes[]` on `/v1/autonomy/tick` (R1).

**Stage 2 — Facade Integration & Native Hook Stabilization.**
Move the validated spikes from Stage 1 into `engine_facade.py`. With the spikes confirmed, run Playtest #5 against the newly integrated items: object interactions (Mirror Reflect, Diary Read/Snoop, Mailbox Neighborhood Stories), and God Director arc advancement only on catalyst conversations (BUG-14). Cut low-return P2 hooks: keep `sim_GetToKnow` (S4CL interaction-completed listener); **defer** the physical Autobiography book (3.5) and Tombstone epitaph (3.7) to post-v2.0, replacing P11 reading with a Computer/Diary/Web Studio option.

**Stage 3 — LLM robustness, context packing, Web Studio (P4).**
`llm/json_repair.py` + `response_format: json_object` (R5); Token Priority Packing (R4); Web
Studio auto-refresh (or SSE consumption) on Sim Mind, `director_mode` selector in Director's
Room, `spoiler_shield` (4.4), Sim export/import (4.6 / FC2).

**Stage 4 — Reactive substrate + MCP layer (mcp.md phases 0a→4).**
Only after Stages 1–3: revised 0a (unified transport + new kinds integrated with `outcomes[]`),
0b (async Action Gateway + indexed ConditionEngine, awaiting the real outcome via
`asyncio.Event` with a 3 s timeout before returning `tools/call` for `intent` tools), then the
three facades validated with contract tests + one external agent script.

### Immediate action matrix

| Priority | Component | Action | Resolves |
|---|---|---|---|
| ~~P0~~ | `main.py`/`sqlite_store.py` | ~~Save `player_confidant_sim_id` in the save's `metadata` table; purge old duplicates~~ (✅ DONE) | BUG-12 / `.save` pollution |
| ~~P0~~ | `lifecycle_hooks.py` | ~~Buffer/block events until `session-start` responds~~ (✅ DONE) | realtime-lane saturation / epoch=0 drops |
| ~~P0~~ | `mod/` + `services.py` | ~~Add `outcomes[]` (`applied/failed/expired`) to the autonomy pulse~~ (✅ DONE) | blind fire-and-forget (God/MCP) |
| ~~P1~~ | `http_client.py` | ~~Merge SSE (timeout=15 + keepalive) and pull into one inbound thread~~ (✅ DONE) | TS4 shutdown hang + intent-consume race |
| ~~P1~~ | `engine_facade.py` | ~~`sw.smoke_test` to validate tunings/objects/S4CL attrs in ~2 s~~ (✅ DONE) | slow EA-API bug discovery |
| ~~P1~~ | `llm/json_repair.py` | ~~Repair malformed JSON / `<think>` tags + native `response_format`~~ (✅ DONE) | false `unusable output` / fallback cascade |
| ~~P2~~ | `llm/context.py` | ~~Priority packing (P0/P1/P2) in the ContextAssembler~~ (✅ DONE) | realtime 700-token overflow |
| ~~P2~~ | P2 scope (M5/M6) | ~~Replace physical book (3.5) + epitaph (3.7) with Diary/PC/Web reading~~ (✅ DONE) | fragile XML tuning complexity |
| ~~P2~~ | `docs/` | ~~Update `project-status.md`/`architecture.md` tables to post-Playtest #4 state~~ (✅ DONE) | documentation drift |

---

## Runtime Reliability and Hardening

> **Date:** 2026-10-02
> **Branch:** `v2-remake`
> **Basis:** production audit of the 2026-10-02 18:31–18:37 session (save `1488584711`) — `lastException.txt`, `mod_logs/Sensewright_Worker.log`, `sidecar/data/logs/sensewright-sidecar.log`, `slot_1488584711.*.db`.
> **Goal:** fix the runtime defects, thread-safety gaps and LLM-pressure issues found in the audit, and harden the mod↔sidecar concurrency model without changing the HTTP contract.

This document is the execution roadmap for the hardening work. Each item lists what exists
today (`file:line`), the concrete action, the affected files, and verification. It complements
[`project-status.md`](project-status.md) (feature gaps); this one is scoped to defects and concurrency.

---

### 1. Principles and constraints

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
  `python mod/build.py` / `python mod/build_package.py` → `docs/project-status.md`.
- **Compatible HTTP contract.** New endpoints/intents are additive; the existing contract does
  not break. Intent normalization degrades to `command` safely.

#### Status legend

- ⬜ Pending · 🟡 In progress · ✅ Done

---

### 2. Audit findings (evidence base)

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

### 3. Architecture decisions

- **Session state machine** (Mod): distinguish *new session* from *zone-transition*; reset on
  `CLIENT_DISCONNECT` / `GAME_LOAD`.
- **Mod HTTP queue = two lanes + atomic slot** (verdict: strictly better than `PriorityQueue`
  — drop-oldest in O(1) and isolated backpressure).
- **Session epochs**: mandatory guard against obsolete jobs writing into `working_store`.
- **Strict rewind tolerance** (3–5 sim-min = 3000–5000 ticks), backed by the `GAME_PRE_SAVE` tick.
- **Reaction async in the realtime tier** (not bg), delivered via a light intent pull.
- **Marriage events**: silent snapshot at load/census (no wall-clock window).

---

### Phase 0 — Schema verification (prerequisite for the XML fix)

#### 0.1 Verify situation tuning schema ⬜

- **Exists:** `scripts/decompile-scripts.ps1`; no local decompiled situation tunings.
- **Action:** decompile and inspect `situations/situation.py` (`_default_job`, `duration`),
  `situations/situation_job.py` (`no_show_action`), `situation_guest_list.py:79`
  (`construct_from_purpose`).
- **Verify:** exact tunable names + the situation-job instance id to reference.

---

### Phase 1 — Mod: lifecycle and save clock

#### 1.1 Session state machine ✅

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

#### 1.2 Pre-save tick with monotonic guard ✅

- **Exists:** `main.py:254-270` reads the tick in `GAME_SAVE` (post-serialization).
- **Action:** `GAME_PRE_SAVE` stores `_pending_save_tick` + `time.monotonic()`; `GAME_SAVE`
  consumes it only if age < 30 s (covers a cancelled "Save As…" or a failed save), otherwise
  reads the current tick; clear the variable right after posting.
- **Verify:** no `rewind requested` on the next load of the same save.
- **Done:** pre-save captures the clock; `GAME_SAVE` consumes it when fresh (< 30 s) and falls
  back to the post-serialization tick otherwise.

---

### Phase 2 — Sidecar: rewind, idempotency and epochs

#### 2.1 Strict rewind tolerance ✅

- **Exists:** `save_vault.py:97-103` compares `world_sim_tick < committed_tick` strictly;
  `_rewind_to_tick` at `:203-230`.
- **Action:** add `REWIND_TOLERANCE_TICKS = 3000` (3 sim-min; configurable). Only a negative
  delta larger than tolerance counts as an intentional reload → restore committed/ring buffer.
  Log the decision (skip/restore/surgical).
- **Verify:** unit test — drift < 3 min skips rewind; a 2 h rollback restores the snapshot.
- **Done:** `REWIND_TOLERANCE_TICKS` default 3000, overridable via
  `gameplay.rewind_tolerance_ticks`; drift ≤ tolerance is logged and skipped, a larger rollback
  restores the nearest ring snapshot (or surgical) and reports `rewound=True`.

#### 2.2 `last_processed_tick` bound to rewind ✅

- **Exists:** no `last_processed_tick` yet (introduced in 2.3).
- **Action:** on `session-start` and any real rewind, set
  `state.last_processed_tick = restored_tick` under the same lock — never silently drop
  autonomy ticks for hours after a rollback.
- **Done:** `handle_session_start` seeds `last_processed_tick` from the restored tick (or the
  current tick on a clean/new session) under the state lock.

#### 2.3 Tick idempotency ✅

- **Exists:** `services.py:527` `handle_autonomy_tick` has no tick guard.
- **Action:** ignore ticks `<= state.last_processed_tick` (locked), honoring the reset from 2.2.
- **Done:** `AppState.accept_tick` atomically rejects stale/duplicate ticks; the handler returns
  `duplicate_tick=True` while still draining already-ready intents.

#### 2.4 Mandatory session epoch ✅

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

### Phase 3 — Concurrency

#### 3.1 God TOCTOU → single active arc ✅

- **Exists:** `god/orchestrator.py:117-131` schedules `god.plan` while `active_arc is None`;
  `_plan_callback` at `:46` sets it only asynchronously.
- **Action:** set an `arc_planning` flag synchronously (under lock) when scheduling; clear it in
  the callback (success/failure); `god_tick` checks `active_arc or arc_planning`; epoch-guard the
  callback.
- **Verify:** one active arc; test — a burst of two ticks yields exactly one `god.plan`.
- **Done:** `try_begin_arc_plan`/`end_arc_plan` claim the slot atomically under `_lock`;
  `_plan_callback` releases it in a `finally`, and the callback is epoch-guarded.

#### 3.2 Single-flight without losing edges ⬜

- **Exists:** `services.py:527-642` does edge detection and LLM dispatch in one path.
- **Action:** split `handle_autonomy_tick` into (a) **mandatory ingestion** (always, locked):
  delta merge, sleep transitions (`is_sleeping` → `sim.dream`/`sim.sleep`), end-of-day, seats,
  intent drain; (b) **optional LLM dispatch** guarded by a non-blocking single-flight flag
  (impulses/social/god). Sleep/wake triggers are never lost.
- **Verify:** a busy tick still records sleep transitions.

#### 3.3 Mod HTTP queue — two lanes + atomic slot ✅

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

#### 3.4 Marriage spam — snapshot, not timer ✅

- **Exists:** `lifecycle_hooks.py:100-116` emits a `marriage` event for every relationship bit
  matching the markers, including the rehydration burst at load.
- **Action:** during census/`HOUSEHOLDS_AND_SIMS_LOADED`, build a silent snapshot of existing
  `(sim_a, sim_b, bit_id)` pairs into `_known_marriage_pairs` (no events). Only emit `marriage`
  for new transitions not in the snapshot, and only when `clock_speed > 0`.
- **Verify:** event count on load < ~10; no wall-clock window.
- **Done:** `begin_marriage_snapshot`/`end_marriage_snapshot` bracket the census; the handler
  records pairs silently and emits only for unseen pairs while the clock runs.

#### 3.5 Store race hardening 🟡

- **Exists:** callbacks hold stale `SqliteStore` references across `save_vault._close_working`
  (`save_vault.py:71-121`).
- **Action:** resolve the store via `state.working_store()` at use time; catch
  `sqlite3.ProgrammingError` ("closed database") with a `store_closed` log; rely on the epoch
  guard (2.4) for cross-session safety.
- **Partial:** `SaveVault.save` now drops `_working_store` to `None` before the copy/reopen
  window, so concurrent callbacks resolve `None` instead of a closed handle; callbacks already
  resolve the store at use time and the epoch guard drops cross-session writes. An explicit
  `sqlite3.ProgrammingError`/`store_closed` log is still pending.

#### 3.6 Atomic rate limiter ✅

- **Exists:** `llm/limits.py:54-69` — `can_accept` and `record_request` are separate locks
  (check-then-act overshoot).
- **Action:** single `try_accept_and_record()` under one lock.
- **Done:** `ProviderRateLimiter.try_accept_and_record` performs the capacity check and records
  the dispatch atomically; `ProviderChain.run` uses it.

---

### Phase 4 — LLM pressure and memory

#### 4.1 Impulse throttle + backpressure ✅

- **Exists:** `services.py:583-604` schedules up to `MAX_IMPULSES_PER_TICK = 3` per tick.
- **Action:** per-sim cooldown (`last_impulse_tick`, 60 sim-min, configurable); reduce
  `MAX_IMPULSES_PER_TICK` when `scheduler.status()['queue_depth']` exceeds a threshold.
- **Done:** `gameplay.impulse_cooldown_sim_minutes` (default 60) gates each sim and
  `gameplay.impulse_backpressure_queue_depth` (default 6) drops the per-tick budget to 1.

#### 4.2 `sim.reaction` realtime-async ✅

- **Exists:** `services.py:880` runs `sim.reaction` synchronously on the HTTP thread.
- **Action:** add `submit_async` with a dedicated realtime worker (semaphore 2), dedup by
  `(sim, category, tick)`, epoch-guarded callback. Intents are enqueued in state as today.
- **Verify:** `/v1/events` returns without blocking on provider latency.
- **Done:** `LLMScheduler.submit_async` runs on a `ThreadPoolExecutor(max_workers=2)`;
  `handle_event` schedules the reaction with a `sim:category:tick` dedup key and an
  epoch-guarded callback that enqueues intents.

#### 4.3 Light intent pull ✅

- **Exists:** intents are only drained by the next `/v1/autonomy/tick` response
  (`services.py:635`) or `GET /v1/autonomy/intents` (`routers/autonomy.py:25-27`).
- **Action:** the Mod worker does a light `GET /v1/autonomy/intents` when both lanes are empty,
  with exponential backoff 2 s→10 s (reset on intents). Reactions/narration reach the game in
  seconds, not up to 15 s.
- **Done:** the worker pulls when idle (gated on session-start), backs off 2 s→10 s, and hands
  the response to the main thread so the IntentBus is only touched there.

#### 4.4 Chain health ✅

- **Exists:** `llm/chain.py:33` `INVALID_OUTPUT_COOLDOWN_SECONDS = 300`; no purpose-level breaker.
- **Action:** make the bench cooldown configurable (120 s default); add a per-purpose breaker
  after `all routes failed` (direct fallback for N min); expose state in `/v1/status`.
- **Done:** `llm.invalid_output_cooldown_seconds` (default 120) and
  `llm.purpose_cooldown_seconds` (default 120); a purpose whose routes all failed is
  short-circuited to the fallback and reported by `ProviderChain.status` → `/v1/status`.

#### 4.5 Close the `mem.consolidate` black hole ✅

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

### Phase 5 — Observability and tests

#### 5.1 Metrics ✅

- **Exists:** `services.py:1136-1158` `status()`; no runtime counters.
- **Action:** add counters to `/v1/status` and the worker log: intents per kind (ok/fail),
  LLM failures per purpose, session resets, rewinds, `stale_epoch_dropped`, `store_closed`,
  lane depths, current epoch.
- **Done:** `/v1/status` exposes `metrics` (session resets, rewinds, duplicate ticks,
  intents emitted/drained, stale-epoch drops), `session_epoch`, `last_processed_tick` and
  `arc_planning`; `LLMScheduler.status`/`ProviderChain.status` expose purpose cooldowns.

#### 5.2 Regression tests ✅

- **Action:** extend `sidecar/tests`: rewind tolerance (drift→skip; 2 h rollback→restore +
  `last_processed_tick`); god single-flight; epoch guard; slot coalescing (merge by sim_id);
  impulse throttle; worker lanes; marriage snapshot; tick idempotency.
- **Done:** `sidecar/tests/test_hardening.py` covers rewind tolerance (skip/restore), tick
  idempotency, epoch guard, god single-flight, atomic rate limiter and the purpose breaker.
  Mod lane coalescing/marriage snapshot are validated by the `py -3.7` compile + manual
  playtest (Phase 6.2).

---

### Phase 6 — Build, deploy and playtest

#### 6.1 Build & test ✅

- **Action:** `pytest` (sidecar) + `make test` (`py -3.7` syntax) + `make install`.
- **Done:** `pytest` 535 green; `py -3.7 -m py_compile` clean; `build_package.py` (42 tunings)
  and `build.py` (88,405 bytes) rebuilt. `make install` pending the in-game pass.

#### 6.2 In-game validation ⬜

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
> [`operations.md`](operations.md) and must be fixed before the Phase 6.2 table can pass.
>
> **Update (2026-10-03, second pass):** BUG-01/02/03 are **fixed** with regression tests
> (`sidecar/tests/test_bugs.py`) and the build was regenerated. The Phase 6.2 table below is
> now ready to run in-game; only the manual playtest remains.

#### 6.3 Post-session audit ⬜

- **Action:** re-inspect `lastException.txt`, `Sensewright_Worker.log`, sidecar log and DB
  (memory types, active arcs, rewinds) — the same protocol as the original audit.

---

### 3. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Marriage snapshot depends on the relationship-tracker API | Medium | Validate in playtest; fallback = per-pair dedup with a sim-clock window |
| Slot coalescing loses sub-pulse sleep edges | Low | Last-value-per-sim merge; already a pre-existing limitation |
| XML tunables differ across game builds | Medium (Phase 0/1) | Decompile first; native fallback stays intact |
| New realtime-async worker adds threads | Low | Semaphore 2; epoch-guarded callbacks |
| Intent pull adds localhost traffic | Low | Exponential backoff 2 s→10 s |

---

### 4. Plan completion criteria

1. Phases 0–5 items ✅ with green tests (`pytest` + `py_compile` 3.7 + builds).
2. Phase 6.2 executed in-game with the table filled in.
3. `docs/project-status.md` updated with the hardening outcomes.
4. No new `lastException.txt` entries and no false rewinds in the post-session audit.

---

### 5. Progress

- [ ] Phase 0 — schema verification
- [x] Phase 1 — Mod: lifecycle & save clock
- [x] Phase 2 — Sidecar: rewind, idempotency, epochs
- [ ] Phase 3 — concurrency (3.2 pending, 3.5 partial)
- [x] Phase 4 — LLM pressure & memory
- [x] Phase 5 — observability & tests
- [ ] Phase 6 — build, deploy & playtest (code done; in-game pending)


---

## Bugs and Playtest Findings

> **Status:** ✅ CLOSED (2026-10-03) — BUG-01/02/03 fixed with regression tests
> (`sidecar/tests/test_bugs.py`, 11 tests); NOTE-01 addressed in config/docs.
> **Branch:** `v2-remake`
> **Build analysed:** hardening build installed 2026-10-03 02:19 (`.ts4script` 88,405 B).
> **Basis:** in-game session 2026-10-03 02:20–02:32 (`save 1488584711`):
> `Mods/Sensewright/sidecar/data/logs/sensewright-sidecar.log`,
> `mod_logs/Sensewright_Worker.log`, `Mods/Sensewright/sidecar/data/saves/slot_1488584711.committed.db`.

These are defects found **after** the hardening pass that were **not previously catalogued** in
[`project-status.md`](project-status.md) or this document. They explain
why the visible gameplay features (dialogue, God Director) appear dead even though the agent
pipeline runs.

Status legend: ⬜ Pending · 🟡 In progress · ✅ Done

---

### Summary

| ID | Bug | Severity | Mapped before? | Status |
|----|-----|----------|----------------|--------|
| BUG-01 | `sim.social` never triggers — activity-based pair detection never matches | High | No (docs assumed `activity` was usable) | ✅ Fixed |
| BUG-02 | Stale duplicate `active` arcs are never cleaned; both stay at beat 0 | High | No (3.1 only prevents **new** duplicates) | ✅ Fixed |
| BUG-03 | Armed beats have no liveness/timeout — an arc stalls forever | Medium | No | ✅ Fixed |
| NOTE-01 | `sim.reaction` route points at a reasoning model (`deepseek-v4-pro`) | Low (ops) | No (config, not code) | ✅ Documented |

#### Fix summary

- **BUG-01** — The Mod now reports a reliable `is_conversing` boolean and
  `social_target_sim_id` resolved from the interaction's Sim target
  (`state_collector._resolve_interaction_target_sim_id`). The sidecar prefers that
  signal, keeps the class-name markers as a fallback, and adds a conservative
  same-room/within-distance fallback (`services._find_conversational_pair` /
  `_proximity_pair`). Asymmetric routing is now wired too (`_puppeteer_context`).
- **BUG-02** — `SqliteStore.deactivate_stale_arcs(keep_id)` plus
  `god.arcs.load_active_arc` self-healing; `handle_session_start` now keeps the
  newest `active` arc and aborts the rest (`stale_arcs_deactivated` metric).
- **BUG-03** — Armed beats record `beat_armed_tick`; `god_tick` advances a beat
  older than `god.beat_timeout_sim_days` (default 1 in-game day) and marks the arc
  `ARC_DONE` when exhausted (`god_beat_timeouts` metric). Legacy armed beats
  without a stamp get a fresh window.
- **NOTE-01** — `sidecar/config.example.toml` documents per-purpose routing and
  now ships `[god] beat_timeout_sim_days`.

---

### BUG-01 — `sim.social` never triggers (pair detection never matches) ✅ FIXED

**Symptom.** No dialogues between Sims. `sim.social` = **0** in the entire sidecar log; the
worker only applied `bias_interaction` (42), `set_mood` (21) and `speak` (2, from
`sim.reaction`).

**Evidence.**
- Sidecar log: `grep -c 'sim.social'` → 0 (all sessions).
- Worker log (`02:20–02:32`): intents = `bias_interaction`, `set_mood`, `speak` only.

**Root cause.** `services._find_conversational_pair` (`services.py:648-662`) selects a pair
only when **≥2** census Sims have `activity` containing one of the markers
`("social","talk","chat","convers")` (`_CONVERSATION_MARKERS`, `_is_conversing`). The Mod
reports `activity = current_interaction.__name__` (`state_collector.py:191-199`), and EA's
social interaction classes are commonly named `MixerInteraction`, `GetToKnow`, `TellJoke`,
`ChatInteraction`… — most do **not** contain the markers. The pair is therefore never formed.

**Why it slipped through.** The gap-closing plan explicitly assumes *"`activity` is already
reported"*, and the status catalog marks purpose P05 `sim.social` as **Full**. No document lists
"activity string may not match the markers".

**Impact.** No `a_line`/`b_line`, no Compact Dialogue Card, no rumor contagion via social, and
— critically — no catalyst conversation, so `/v1/god/beat-ended` never fires and God arcs never
advance (see BUG-03).

**Proposed fix (choose and validate in-game).**
- Mod side: report a robust signal, e.g. `is_conversing: bool` and `social_target_sim_id`,
  computed from the current interaction's target (social interactions have a target) rather
  than its class name.
- Or sidecar side: relax `_is_conversing` to accept a target + proximity + matching `room_id`
  (REQ-SOC-01: same room, ≤ 4.0 m) instead of substring matching.

**Acceptance.** During an in-game conversation the sidecar logs `sim.social`; `speak` intents
are delivered; `social_sessions` becomes non-empty (after P06/`sim.social.close`).

**Files.** `mod/sensewright_mod/state_collector.py`, `sidecar/sensewright_sidecar/services.py`,
`sidecar/sensewright_sidecar/agent/social.py`.

---

### BUG-02 — Stale duplicate `active` arcs are never cleaned (both at beat 0) ✅ FIXED

**Symptom.** `arcs` table holds **2 rows, both `status=active`, both `current_beat_idx=0`**,
same theme ("O ritmo tranquilo da vizinhança"). The God Director never produces a single,
progressing narrative.

**Evidence.** `slot_1488584711.committed.db`:
```
arcs = 2
select id,status,current_beat_idx,theme from arcs
  -> ('635c25ca9ae9','active',0,'O ritmo tranquilo da vizinhanca')
  -> ('e2d57f292cee','active',0,'O ritmo tranquilo da vizinhanca')
```

**Root cause.** Hardening item 3.1 added the `arc_planning` single-flight claim, which stops
**new** duplicate `god.plan` submissions, but nothing deactivates arcs that were already
`active` in the store. `load_active_arc`/`god_tick` then operate on an orphaned duplicate.

**Impact.** The hardening Phase 6.2 acceptance "exactly 1 active arc" cannot pass; beat
progression is ambiguous; narratives stall.

**Proposed fix.** Add an idempotent cleanup on `handle_session_start` (or bootstrap
`ops.recap`), under the state lock: keep the most recent `active` arc, mark the others
`abandoned`. Prefer a store method (e.g. `deactivate_stale_arcs(save_id, keep_id)`) so it is
unit-testable. Consider doing the same on `/v1/god/direct-scene` when it replaces the arc.

**Acceptance.** After `session-start`, the store has ≤ 1 `active` arc; unit test covers two
pre-existing actives → one remains.

**Files.** `sidecar/sensewright_sidecar/services.py` (`handle_session_start`),
`sidecar/sensewright_sidecar/god/arcs.py`, `sidecar/sensewright_sidecar/memory/sqlite_store.py`.

---

### BUG-03 — Armed beats have no liveness/timeout (arcs stall at beat 0) ✅ FIXED

**Symptom.** Arcs remain at beat 0 indefinitely; `god.plan created` = 0 in the new run; no
`beat-ended` ever arrives.

**Root cause.** A beat only advances via `/v1/god/beat-ended`, fed by `catalyst_tracker` when a
catalyst conversation ends. If the catalyst never spawns/converses (blocked by BUG-01 and the
known `spawn_npc`/VisitSituation gaps), nothing ever advances or completes the arc, and no
timeout exists.

**Impact.** God Director silently stalls forever; no narration visible to the player.

**Proposed fix.** Record `beat_armed_tick` when a beat is armed; in `god_tick`, if the beat has
been armed longer than a configurable window (e.g. `god.beat_timeout_sim_days`, default 1), call
`advance_arc` (or mark `ARC_DONE`) and log the decision. This makes arcs self-healing even when
the catalyst path fails.

**Acceptance.** Unit test: an armed beat older than the timeout advances; in-game an arc never
remains on the same beat beyond the window.

**Files.** `sidecar/sensewright_sidecar/god/orchestrator.py`,
`sidecar/sensewright_sidecar/god/arcs.py`.

---

### NOTE-01 — `sim.reaction` routed to a reasoning model (ops, not code) ✅ DOCUMENTED

**Symptom.** In the 02/10 sessions, 111× `sim.reaction: all routes failed (model
deepseek/deepseek-v4-pro benched (unusable output))`. Mitigated by hardening 4.4 (per-purpose
breaker + 120 s bench): new run dropped to 2 `all routes failed`, 7 `unusable output`.

**Action.** In the installed `sidecar/config.toml`, route `sim.reaction` (and any JSON-only
purpose) to a JSON-capable model. Not a code defect; no engineering item required.

---

### Baseline that already works (do not regress)

- Hardening fixes verified in the new run: `rewind` = 0 (was 18), `ignoring tick drift` present,
  `stale_epoch` = 36 (stale callbacks dropped), `unusable output` 159 → 7,
  `mem.consolidate` fired (1) and `consolidated` rows exist.
- Agent pipeline works: DB `memories` = 300 (`thought` 282, `sleep_reflection` 5, `dream` 5,
  `legacy` 4, `diary` 3, `consolidated` 1).
- `sim.impulse` intentionally never speaks (REQ-IMP-01); its visible output is
  `set_mood`/`bias_interaction` (moodlets/buffs).

---

### Verification performed (2026-10-03)

- `cd sidecar && python -m pytest -q` → **623 passed** (11 new in `test_bugs.py`).
- `py -3.7 -m compileall -q mod/sensewright_mod` → clean.
- `python mod/build_package.py` → `Sensewright.package` (17,037 B, 44 resources).
- `python mod/build.py` → `Sensewright.ts4script` (91,397 B, 3.7 bytecode).
- **Still pending:** the in-game playtest (Phase 6.2 in [`operations.md`](operations.md))
  to confirm `sim.social` fires, `speak` intents arrive, `social_sessions` fills and
  exactly one arc progresses. Deploy with `scripts/install-mod.ps1` then play.

### How to inspect a session (if a regression appears)

1. With the game closed:
   - Sidecar log: `%USERPROFILE%\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\Sensewright\sidecar\data\logs\sensewright-sidecar.log`
   - Worker log: `%USERPROFILE%\OneDrive\Documents\Electronic Arts\The Sims 4\mod_logs\Sensewright_Worker.log`
   - DB: `...\Mods\Sensewright\sidecar\data\saves\slot_<save>.committed.db`
2. Look for `sim.social`, `sim.social.close`, `god_beat_timeouts`,
   `stale_arcs_deactivated` and the `arcs` table (exactly one `active` row).

---

## Post-deploy playtest #2 (2026-10-03 12:34–12:44) — observability pass + BUG-04..07

> **Status:** ✅ CLOSED — BUG-04/05/06/07 fixed with regression tests/asserts.
> **Basis:** first in-game session after the observability instrumentation
> (`.ts4script` 95,687 B). Logs: `mod_logs/Sensewright_Worker.log` (12:34–12:44),
> `sidecar/data/logs/sensewright-sidecar.log`, `lastUIException.txt`.

This playtest used the instrumented build and, for the first time, produced
**deterministic evidence** for why four previously-unmapped features were dead.
The observability pass added a "heartbeat" log line to every feature path so a
session log now shows, per feature, whether it fired and what it did (see the
"Observability coverage" table at the end).

### Summary

| ID | Bug | Severity | Evidence (this session) | Status |
|----|-----|----------|--------------------------|--------|
| BUG-04 | Object interactions never appear: `_object_name` returns `<definition: NNNN>` | High | `mirror handler first object name="<definition: 30457>"` | ✅ Fixed |
| BUG-05 | `sim.social` never fires: `Sim` has no `social_group` attr | High | `delta: 12 sims, 0 conversing, 12 activity-idle` | ✅ Fixed |
| BUG-06 | Chat shows "not delivered": `handle_chat` omits `ok` | High | sidecar `sim.chat tokens=317` + pt-BR `chat.error_failed` | ✅ Fixed |
| BUG-07 | `lastUIException` flood: `BuffInfo/MoodKey()` null (mood_type `<T>` not `<E>`) | Medium | `Error #1009 ... BuffInfo/MoodKey()` (force-close) | ✅ Fixed |

### BUG-04 — object menus (mirror/diary/mailbox) never appear ✅

**Symptom.** Right-clicking a mirror/diary/mailbox shows no Sensewright option.

**Evidence.**
```
object_interactions: mirror handler first object name="<definition: 30457>"
object_interactions: diary  handler first object name="<definition: 30457>"
object_interactions: mailbox handler first object name="<definition: 30457>"
```

**Root cause.** `_object_name` read `script_object.definition.name`, which is
`None` for these base-game objects, then fell back to `str(definition)` →
`"<definition: 30457>"`. The `mirror`/`diary`/`mailbox` markers therefore never
matched and `should_add` always returned `False`.

**Fix.** Prefer the Python class name (`script_object.__class__.__name__` →
`Mirror`, `Mailbox`, …), which is stable and contains the marker; keep the
definition-name path as a fallback. Also added a per-handler diagnostic that logs
the first object seen + the first match, and a tuning-load check
(`tuning interaction.mirror_reflect ... loaded=True/False`).

**Files.** `mod/sensewright_mod/object_interactions.py`.

### BUG-05 — `sim.social` never fires ✅

**Symptom.** No Sim-to-Sim dialogue; `sim.social` = 0 all session.

**Evidence.**
```
delta: 12 sims, 0 conversing, 5 room_id, 0 sleeping, 12 activity-idle
```

**Root cause.** The conversation signal read `sim.social_group`, but `Sim` has no
such attribute (the S4CL source only ever reads `si.social_group` on each social
*interaction* in `sim.si_state`). The social peer therefore always resolved to 0.

**Fix.** `_resolve_social_group_peer` now iterates `sim.si_state` and `sim.queue`,
reading `social_group` off each social interaction and returning the first other
Sim id. `room_id` was already correct (5/12 instanced sims had a valid id).

**Files.** `mod/sensewright_mod/state_collector.py`.

### BUG-06 — chat shows "not delivered" despite a successful sidecar reply ✅

**Symptom.** Player message → "A mensagem não pôde ser entregue" even though the
sidecar answered.

**Evidence.** Sidecar: `llm.route purpose=sim.chat ... tokens=317` (a real reply);
mod side rendered `t('chat.error_failed')`.

**Root cause.** `handle_chat` returned `{"response": ..., "deferred": ...}` without
an `ok` key, but `chat_ui._handle_chat_response` gates on `response.get('ok', False)`
→ always `False` → error path. No test asserted `ok`, so it regressed silently.

**Fix.** `handle_chat` returns `"ok": True` on both the normal and deferred paths.
`tests/test_services_endpoints.py` now asserts `data["ok"] is True` on `/chat` and
`/hey`.

**Files.** `sidecar/sensewright_sidecar/services.py`, `sidecar/tests/test_services_endpoints.py`.

### BUG-07 — `lastUIException` flood: `BuffInfo/MoodKey()` null ✅

**Symptom.** Client throws `TypeError: Error #1009 ... BuffInfo/MoodKey()` repeatedly
(the session ended with a force-close).

**Root cause.** The emotion buffs wrote `mood_type` as a plain numeric tunable
(`<T n="mood_type">14632</T>`), but `mood_type` is a `TunableEnumEntry` — the XML
must use `<E n="mood_type">ANGRY</E>` (the same `<E>` element used by `buff_type`).
The misparse made the buff resolve to `Mood.FINE`, which has no client `MoodKey`.

**Fix.** All 12 `buff_mood_*.xml` now use `<E n="mood_type">ANGRY|BORED|CONFIDENT|DAZED|
ENERGIZED|FLIRTY|FOCUSED|HAPPY|INSPIRED|SAD|STRESSED|UNCOMFORTABLE</E>`
(enum member names from S4CL `CommonMoodId`). `buff_mood_fine` was already removed in
the previous wave (Mood_Fine has no MoodKey).

**Files.** `mod/tuning/buffs/buff_mood_*.xml`.

---

### Observability coverage (added across this + previous wave)

Every feature now logs a decisive line to `Sensewright_Worker.log` (success *and*
failure paths), so a single session pinpoints any dead feature:

| Feature | Log line |
|---|---|
| Mod loaded / tunings | `tuning interaction.chat ... loaded=True/False` |
| Pie menu reachable | `pie menu: interaction hook reached a Sim instance` |
| Chat entry / submit / reply | `chat entry point` · `chat submitted` · `chat response` / `chat response FAILED` |
| Sim-to-Sim dialogue | `delta: N sims, M conversing, K room_id` + sidecar `sim.social pair ... gate=...` |
| Reaction speech / mood | `intent ... [speak]/[set_mood] ... success=True` |
| Intent TTL loss | `intent bus: expired N intents ...` |
| God/catalyst | sidecar `god.plan created` / `god.puppeteer` / `god beat timeout` · mod `catalyst tracker: ... -> beat-ended` · `visit_situation: started native visit` |
| Object interactions | `tuning interaction.mirror_reflect ... loaded=` · `mirror handler first object name` · `mirror MATCHED` · `mirror reflect clicked` |
| Lifecycle events | `lifecycle: suppressing events until first autonomy pulse` → `lifecycle event posted` |
| Save/Shadow DB | sidecar `committed save ... at tick` |

### Verification performed (2026-10-03)

- `cd sidecar && python -m pytest -q` → **637 passed** (regression: reaction `sim_id`
  in `test_bugs.py`, `ok` asserts in `test_services_endpoints.py`).
- `py -3.7 -m py_compile` on all changed Mod files → clean.
- `python mod/build_package.py` → `Sensewright.package` (16,864 B, 43 resources, mood_type `<E>`).
- `python mod/build.py` → `Sensewright.ts4script` (95,981 B, 3.7 bytecode).
- Deployed with `scripts/install-mod.ps1`.
- Installed sidecar boot-tested (`/v1/health` 200, `handle_chat` returns `ok`).

---

## Playtest #3 (2026-10-03) — chat grounding & family-tree hallucination

> **Status:** ✅ CLOSED — BUG-08/09 fixed with regression tests.
> **Basis:** sidecar log `llm.route purpose=sim.chat ... tokens≈600` with every reply
> generic, plus an SMS chat in which a Sim mentioned a brother absent from the
> genealogy. Root causes traced from the wire contract, the prompt templates and the
> census family-link collection.

### Summary

| ID | Bug | Severity | Status |
|----|-----|----------|--------|
| BUG-08 | Chat replies are generic/repetitive — `player_name`, `friendship` and the conversation history never reach the LLM | High | ✅ Fixed |
| BUG-09 | Sims hallucinate relatives (a "brother") — the family tree is collected but never grounded into the prompt | High | ✅ Fixed |

### BUG-08 — chat context was almost empty (player name, trust, history) ✅

**Symptom.** Every SMS reply looked like the same generic greeting.

**Root cause.** Four independent gaps made the `sim.chat` prompt degenerate:
1. The Mod never sent `player_name` — `post_chat`/`post_hey` omitted it, so the prompt
   rendered `"Trust with : 1"` / `"Message from : ..."`.
2. `friendship` was never available — the full census (`_collect_full_sim_census`)
   does not emit a per-sim friendship and the Mod did not send one, so
   `sim.get("friendship", 0.0)` was always `0.0` → `trust` pinned at the lowest tier.
3. The short-term chat buffer (`state.chat_buffers`) was written by
   `append_chat_turn` but **never read** by `handle_chat`, so every message was
   processed as a standalone greeting with no prior turns.
4. The `user_phone_sms` prompt dropped `memories_text` (only `pc_chat` had it), so SMS
   had no memory/backstory grounding.

**Fix.**
- Mod (`http_client.py`, `chat_ui.py`): resolve the hidden confidant's name and the
  `sim ↔ confidant` friendship track and send both as `player_name`/`friendship`.
- Sidecar (`services.handle_chat`): prefer the wire `friendship`, fall back to census;
  pass `state.chat_turns(sim_id)` as `history` and the resolved family as `family`.
- `llm/context.py` renders `history_hint` and `family_hint`; the locale `sim.chat`
  templates now include history + memories for all three channels.

### BUG-09 — relatives hallucinated because the family tree never reached the LLM ✅

**Symptom.** An SMS Sim mentioned a brother that does not exist in the family tree.

**Root cause.** `_collect_full_sim_census` attempted to read `rel.target_sim_id` and
`rel.relationship_bits`, neither of which exists on TS4's `Relationship` object (it
exposes `sim_id_a`/`sim_id_b` and `get_all_bits`). The `family_links` list was
therefore always empty, and nothing in `build_chat_context`/`handle_chat` ever fed
family data into the prompt — the model, asked to roleplay a real person with no
family grounding, invented a sibling. (A second latent crash: `background_scheduler.
priority_class` treated `family_links` as `list[int]` and would `int(dict)` on the
real dict shape.)

**Fix.**
- Mod (`state_collector._collect_family_links`): use S4CL
  `CommonRelationshipUtils.get_sim_info_of_all_sims_with_relationship_bit_generator`
  with `instanced_only=False` and `CommonRelationshipBitId` to build a stable,
  language-independent `[{target_sim_id, relationship}]` list.
- Sidecar (`services._resolve_family` + `agent.chat.family_relation_label`): resolve
  each edge to `{name, relation}` and inject a localized `family_hint`
  ("Sua família: … Nunca invente parentes que não estejam listados aqui.").
- Sidecar (`god.background_scheduler._family_link_ids`): accept both the canonical dict
  shape and the legacy bare-int shape.

### Verification performed (2026-10-03)

- `cd sidecar && python -m pytest -q` → **647 passed** (10 new: chat history/family,
  `family_relation_label`, dict-shape `family_links`, `services._resolve_family`).
- `py -3.7 -m py_compile` on changed Mod files → clean.
- `python -m py_compile` on changed Sidecar files → clean.

---

## Context-awareness pass (2026-10-03) — every interaction carries scene context

> **Status:** ✅ CLOSED — the scene context (location / relationship / selected action)
> is now collected and grounded into every dialogue path.
> **Basis:** requirement review — "any interaction must consider context". Validated the
> three paradigms (sim↔sim `sim.social`, player↔sim `sim.chat`, god↔sim `god.puppeteer`)
> and found the setting, the pair relationship and the chosen interaction text were never
> sent to the LLM.

### BUG-10 — dialogues ignored location, relationship and the selected action ✅

**Symptom.** The tone never changed between "chatting on a sofa at home" vs "outdoors in
a public park with a stranger"; the specific pie-menu action (tell a joke / complain about
the weather / kiss) and the queued follow-up action against the same Sim were invisible to
the model, so dialogue could not reference what was actually happening.

**Root cause.** The wire + prompt carried only mood/activity class-names:
- The Mod reported `activity = interaction.__name__` (a Python class name, e.g.
  `MixerInteraction`), never the localized menu title.
- No venue / indoor-outdoor / home-away signals were collected.
- No per-pair friendship/romance was read from the imported relationship edges.
- `build_social_context`/`build_chat_context`/`run_puppeteer` never carried any of this.

**Fix.**
- Mod (`state_collector`): collect per-Sim `is_outside`/`is_at_home`, the localized
  `interaction_text` (via `LocalizationHelperTuning.get_raw_text(display_name)`), and
  `queued_interaction_texts`; collect zone `venue_type`/`is_residential`.
- Mod (`http_client`/`main`): send `venue` on the autonomy tick; store it in
  `state.zone_context`.
- Sidecar (`agent.social`): add `location_context` / `relationship_context` /
  `action_context` + `relationship_tier` (stranger→acquaintance→friend→close→family).
- Sidecar (`services`): `sim.social` now passes location + relationship + action;
  `sim.chat` passes location + action (on top of family/history/trust from BUG-08/09).
- Sidecar (`god.puppeteer.run_puppeteer`): ground the orchestrated approach in the same
  scene context.
- `llm/context.py`: renders `location_hint` / `relationship_hint` / `action_hint` (and the
  previously-unused `asymmetric_directive` for catalyst puppeteering) into the prompts.
- Locales: added `enums.inside_outside`/`home_away`/`relationship`/`venue` and the hint
  anchors in en-US + pt-BR.

#### Native relationship feedback (friendship/rivalry delta)

The in-game outcome of an interaction (friendship up/down, rivalry up) is read **before**
the prompt is sent, so the tone follows the real feedback:

- Mod (`state_collector`): when a social target is resolved, read the fresh
  `social_friendship`/`social_romance` via `CommonRelationshipUtils` and report them in
  the delta.
- Sidecar (`agent.social.relationship_context`): compare the fresh value against the census
  baseline and derive `friendship_delta`/`romance_delta`; `relationship_tier` now maps
  negative friendship to `rival`.
- `llm/context.py`: renders the delta, e.g. `Relação: amigos, amizade 45 (+5)` or
  `Relação: rivais, amizade -22 (-8)`.

### Verification performed (2026-10-03)

- `cd sidecar && python -m pytest -q` → **656 passed** (9 new: scene-context helpers,
  `build_social_context` location/relationship/action, native feedback delta).
- `py -3.7 -m py_compile` on changed Mod files → clean.
- `python -m py_compile` on changed Sidecar files → clean.

---

## Playtest #4 — diagnosis (2026-10-03 14:42–14:54) — FIXED

> **Status:** ✅ CLOSED (2026-10-03) — BUG-11/12/13/14/15/16/17 fixed with regression
> tests (`sidecar/tests/test_playtest4.py`, 16 tests) + NOTE-02 addressed in config/docs.
> **Branch:** `v2-remake`
> **Basis:** real session `save 1488584711`, logs
> `Mods/Sensewright/sidecar/data/logs/sensewright-sidecar.log` +
> `mod_logs/Sensewright_Worker.log`, DB
> `Mods/Sensewright/sidecar/data/saves/slot_1488584711.committed.db` (committed 14:54).

> **Post-install follow-up (2026-10-03, session 15:23–15:30):** the first deploy left
> three items incomplete, now fixed and re-deployed:
> - **BUG-07 regression** — the `bias`/`dream`/`missing_player` buffs still used
>   `<T n="mood_type">0</T>` (= `Mood.INVALID`), so `BuffInfo/MoodKey()` null kept
>   flooding `lastUIException`. All buffs now use `<E n="mood_type">…</E>`.
> - **BUG-12** — the hidden household's name doesn't persist, so the confidant was
>   re-created (21 rows). `get_or_create_player_confidant` now searches the whole sim
>   manager by last name first.
> - **BUG-11** — census-time scheduling gated on `is_player` (unreliable at
>   session-start). Added a seat-based trigger in `handle_autonomy_tick` + a census
>   diagnostic log line.

Status legend: ⬜ Pending · 🟡 In progress · ✅ Done

### Summary

| ID | Bug | Severity | Evidence (this session) | Status |
|----|-----|----------|--------------------------|--------|
| BUG-11 | `sim.profile` never runs → every Sim has an empty persona | Critical | `sim.profile` = **0** all-time; DB **114/124** profiles `source=template`, **0** `source=llm`, all personality fields empty | ✅ Fixed |
| BUG-12 | Player confidant re-created every session → **20** "Confidente Sensewright" | High | `SELECT COUNT(*) FROM sims WHERE profile LIKE '%Confidente Sensewright%'` = 20 | ✅ Fixed |
| BUG-13 | `relationships` table empty → no relationship graph/baseline | High | `relationships` = **0 rows**; `relationships_imported=0` | ✅ Fixed |
| BUG-14 | `beat-ended` posted for **every** conversation → arc burns through beats | High | 30 `beat-ended posted`; arc `28abc5324e9b` idx 1→6 → `done` in ~3 min; `god.react` 7× | ✅ Fixed |
| BUG-15 | `age_stage` carries an `Age.` prefix → enum never translates | Medium | DB `age_stage="Age.YOUNGADULT"`; prompt shows `Age.YOUNGADULT` not `Jovem Adulto` | ✅ Fixed |
| BUG-16 | Mailbox `/world/neighborhood` request aborts (WinError 10053) | Medium | 2× `Request exception for /world/neighborhood?save_id=...` | ✅ Fixed |
| BUG-17 | `gender` never collected → gender inflection never applies | Low | `llm/context._render_ctx` reads `context.get("gender")`, never populated by the Mod | ✅ Fixed |
| NOTE-02 | LLM routes unreliable (deepseek unusable, groq 403, circuit-open) | Ops | many `all routes failed` / `circuit-open` at 14:52; benches on deepseek & openrouter free | ✅ Addressed |

#### Fix summary

- **BUG-11** — `handle_census` now schedules a bounded background `sim.profile`
  generation for household sims whose stored profile is still a template;
  `handle_profile` regenerates when `source == "template"` (empty persona) instead
  of only when the profile is `None`; `handle_chat` kicks off a one-shot fallback
  generation (RAM-guarded per session). Generated personas are tagged
  `source="llm"`; the 0-key fallback stays `template`.
- **BUG-12** — `get_or_create_player_confidant` now searches the hidden household
  for an existing member (name marker, then first member) before spawning a new
  `SimInfo`.
- **BUG-13** — `collect_full_census` collects relationship edges via S4CL
  `CommonRelationshipUtils.get_relationships_gen` + `get_friendship_level` /
  `get_romance_level` (the engine's `Relationship` exposes `sim_id_a`/`sim_id_b`/
  `get_other_sim_id`, not `target_sim_id`/`friendship`/`romance`).
- **BUG-14** — the Mod reports the conversation peer (`target_sim_id`) with
  `beat-ended`; the sidecar gates `run_react` on whether either participant is the
  catalyst (leased puppeteer NPC or a resolved cast member). Ambient chatter no
  longer advances the arc.
- **BUG-15** — the Mod reports `age_stage` via `Age.name` (stripping an `Age.`
  prefix); the sidecar normalizes legacy stored values in `normalize_age_stage`.
- **BUG-16** — `http_client._make_request` no longer sends a JSON body on GET;
  any GET payload (e.g. `trace_id`) is moved into the query string.
- **BUG-17** — the Mod collects `gender` (`M`/`F`/`N` via S4CL `CommonGenderUtils`)
  and the sidecar threads it into `sim.chat`, `sim.social` and `sim.profile` contexts.
- **NOTE-02** — `sidecar/config.example.toml` + the installed `config.toml` now route
  JSON-only purposes explicitly to a JSON-capable free model and keep `deepseek`
  disabled (ops, no code change).

---

### Baseline that already works (do not regress)

- **Chat** (10 msgs): `chat submitted ... player=Confidente friendship=0.05` and
  `chat response ... len=55..263` — the BUG-08 grounding fix is live (player name +
  friendship + varied replies).
- **sim.social** (34 runs): pairs form and pass `gate={... ok: True}`.
- **Memory** (581 rows): `thought` 495, `sleep_reflection` 21, `consolidated` 19,
  `backstory` 15, `legacy` 12, `dream` 11, `diary` 8.
- **God Director**: `god.plan`, `god.cast → spawn_npc` (2×), `god.puppeteer`; intents
  applied (`bias_interaction`, `set_mood`, `speak`, `command`, `spawn_npc`).

---

### BUG-11 — `sim.profile` never runs; every Sim has an empty persona ✅ FIXED

**Symptom.** Chat/dialogue prompts render with empty `Core personality / Current
demeanor / Speech style`. Replies feel generic even with the scene context in place.

**Evidence.**
- Sidecar log: `purpose=sim.profile` = **0** (entire history).
- DB: `source="llm"` = **0**, `source="template"` = **114** (of 124 sims); e.g.
  `core_personality=""`, `current_demeanor=""`, `speech_style=""`, `backstory=""`.

**Root cause.** `handle_census` (`services.py:835`) pre-creates a **template** profile for
every census Sim; `handle_profile` (`services.py:1555`) only calls `run_purpose("sim.profile")`
when `profile is None or force_interactive` — since the template already exists, the LLM
profile is never generated. The Mod never posts `/v1/profile`.

**Impact.** The `sim.chat`/`sim.social` system prompt has no persona to ground the voice
(the very "respostas sempre iguais/genéricas" symptom).

**Fix (implemented).**
- `handle_census` schedules a bounded background `sim.profile` for household sims whose
  stored profile is still a template; `handle_profile` regenerates on `source == "template"`
  (empty persona); `handle_chat` triggers a one-shot (RAM-guarded) fallback generation.
- Generated personas are tagged `source="llm"`; the 0-key fallback stays `template`.

**Files.** `sidecar/sensewright_sidecar/services.py` (`handle_census`, `handle_profile`,
`handle_session_start`), `mod/sensewright_mod/state_collector.py` (census), purpose
`sim.profile` (`purposes.py:55`).

---

### BUG-12 — Player confidant re-created every session (20 duplicates) ✅ FIXED

**Symptom.** The player's identity/trust does not persist; the DB accumulates confidants.

**Evidence.** DB: **20** rows with `name="Confidente Sensewright"` across different
`generated_at_tick`s (17988692 … 34155186).

**Root cause.** `native_hooks.get_or_create_player_confidant` (`native_hooks.py:94`) only
checks the in-memory `_player_confidant_sim_id` (0 on every game restart). It finds the
hidden household by name but then **always** `CommonSimSpawnUtils.create_sim_info(...)`,
never searching the household for an existing confidant.

**Impact.** Friendship/trust (sim↔confidant) restarts near 0 each session; `state.relationships`
and the native-feedback delta lose their anchor; DB growth.

**Fix (implemented).** After resolving the hidden household, `_find_existing_confidant`
returns an existing member (name marker, then first member) before spawning a new `SimInfo`.

**Files.** `mod/sensewright_mod/native_hooks.py`.

---

### BUG-13 — `relationships` table is empty (no relationship graph/baseline) ✅ FIXED

**Symptom.** Web Studio relationship graph is empty; relationship-based logic has no data.

**Evidence.** DB: `relationships` = **0 rows**; census response `relationships_imported=0`.

**Root cause.** `collect_full_census` (`state_collector.py:743-750`) iterates
`rel_tracker.relationships` and reads `rel.target_sim_id` / `.friendship` / `.romance` —
none of these exist on TS4's `Relationship` (it exposes `sim_id_a`/`sim_id_b`,
`get_other_sim_id`, and track accessors). Same failure class as the old `family_links` bug.

**Impact.** `mem.relationship.review` has no edges; `relationship_context` baseline is
always 0 (so the native-feedback delta is really "current value"); Web Studio empty.

**Fix (implemented).** `collect_full_census` collects edges via S4CL
`CommonRelationshipUtils.get_relationships_gen` + `get_friendship_level`/`get_romance_level`
(the engine's `Relationship` exposes `sim_id_a`/`sim_id_b`/`get_other_sim_id`).

**Files.** `mod/sensewright_mod/state_collector.py` (`collect_full_census`).

---

### BUG-14 — `beat-ended` fires for every conversation; arc burns through beats ✅ FIXED

**Symptom.** The God Director's arc advances on ambient chatter and completes within minutes.

**Evidence.** Worker log: 30 `beat-ended posted` for unrelated sims; sidecar
`god.react beat resolved idx=1..6`; arc `28abc5324e9b` went `active`→`done` in ~3 min
(14:49:47 → 14:52:44).

**Root cause.** `catalyst_tracker.observe` (`catalyst_tracker.py:55-71`) reports the end of
**any** conversation as `beat-ended`; it never checks whether the conversation involved the
current **catalyst** (lease from `god.cast`). Every ambient sim conversation therefore
triggers `god.react` and advances the arc.

**Impact.** Wasted `god.react` LLM calls; incoherent narrative pacing; beats consumed by
random conversations.

**Fix (implemented).** The Mod reports the conversation peer (`target_sim_id`) with
`beat-ended`; the sidecar gates `run_react` on whether either participant is the catalyst
(leased puppeteer NPC or a resolved cast member). Ambient chatter no longer advances the arc.

**Files.** `mod/sensewright_mod/catalyst_tracker.py` (+ possibly `native_hooks`/sidecar lease
exposure to the Mod).

---

### BUG-15 — `age_stage` carries an `Age.` prefix ✅ FIXED

**Symptom.** Age renders as `Age.YOUNGADULT` in profiles/prompts instead of a localized label.

**Evidence.** DB profiles: `age_stage="Age.YOUNGADULT"`, `"Age.ADULT"`, `"Age.INFANT"`.
Prompt enum lookup key is `YOUNGADULT`.

**Root cause.** `state_collector.py:643` does `str(_safe_getattr(sim_info, 'age', 'YOUNGADULT'))`;
`sim_info.age` is an `Age` enum whose `str()` is `"Age.YOUNGADULT"`.

**Fix (implemented).** The Mod reports `age_stage` via `Age.name` (stripping an `Age.` prefix);
the sidecar normalizes legacy stored values in `normalize_age_stage`.

**Files.** `mod/sensewright_mod/state_collector.py` (+ `agent/profile.normalize_profile`).

---

### BUG-16 — Mailbox `/world/neighborhood` GET aborts (WinError 10053) ✅ FIXED

**Symptom.** "Neighborhood Stories" mailbox notification fails; a request exception is logged.

**Evidence.** Worker log 14:48:07 and 14:52:32:
`Request exception for /world/neighborhood?save_id=1488584711: [WinError 10053]`.

**Root cause (probable).** `get_async` builds a GET request but `http_client._make_request`
always serializes the payload as a JSON **body** (`data=`) even for GET; with a query string
already present, the server (uvicorn) resets the connection. (`handle_neighborhood` itself is
fast/side-effect-free.)

**Fix (implemented).** `http_client._make_request` no longer sends a JSON body on GET; any GET
payload (e.g. `trace_id`) is moved into the query string.

**Files.** `mod/sensewright_mod/http_client.py` (`get_async` / `_make_request`).

---

### BUG-17 — `gender` never collected (no gender inflection) ✅ FIXED

**Symptom.** Gender-inflected pt-BR strings always use the masculine/neutral form.

**Evidence.** `llm/context._render_ctx` reads `context.get("gender")`; neither the census nor
the delta ever sends a `gender` field.

**Fix (implemented).** The Mod collects `gender` (`M`/`F`/`N` via S4CL `CommonGenderUtils`) and
the sidecar threads it into `sim.chat`, `sim.social` and `sim.profile` contexts.

**Files.** `mod/sensewright_mod/state_collector.py`, sidecar contexts.

### NOTE-02 — LLM routes unreliable during the session (ops) ✅ ADDRESSED

**Symptom.** Many purposes fell back to deterministic templates around 14:52.

**Evidence.** `deepseek-flash`/`deepseek-v4-pro` benched ("unusable output") per NOTE-01;
`groq` returned `HTTP 403: error code 1010` (Cloudflare) → provider circuit opened; opencode
and openrouter free models benched/circuit-open; `sim.impulse`, `god.react`,
`sim.social.close`, `god.narration`, `god.scene` → `all routes failed` → fallback.

**Action (config/ops, done).** `sidecar/config.example.toml` + the installed `config.toml`
route JSON-only purposes explicitly to a JSON-capable free model, keep `deepseek` disabled,
and document the groq 403 (Cloudflare) user-agent issue. No code change required.

---

### How to re-inspect this session

1. With the game closed:
   - Sidecar log: `%USERPROFILE%\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\Sensewright\sidecar\data\logs\sensewright-sidecar.log`
   - Worker log: `...\The Sims 4\mod_logs\Sensewright_Worker.log`
   - DB: `...\Mods\Sensewright\sidecar\data\saves\slot_1488584711.committed.db`
2. Quick DB probes:
   - `sim.profile` count: `grep -c 'purpose=sim.profile' sensewright-sidecar.log` (expect > 0).
   - Confidants: `SELECT COUNT(*) FROM sims WHERE profile LIKE '%Confidente%';`
   - Profiles: `SELECT COUNT(*) FROM sims WHERE profile LIKE '%"source": "llm"%';`
   - Edges: `SELECT COUNT(*) FROM relationships;`
   - Arcs: `SELECT id,status,current_beat_idx,theme FROM arcs;`

---

## Weak-Point Remediation

Full defect sweep + fixes (19 corrected: 9 sidecar, 10 mod/contract). Verified with
`pytest` **689 passed** (16 new in `test_fixes_wave.py`), `py -3.7` compile, and rebuilt
`.package` (46 resources) / `.ts4script`.

### Fixed

- **Sidecar:** catalyst lease and seat lease converted from sim-minutes to ticks
  (`TICKS_PER_SIM_MINUTE`); `context_json` no longer double-encoded (affected all 33
  prompts); `sim.social.close` persists on the fallback path (`event_summary`);
  `autonomy_mode` (`full|reactive|off`) accepted, exposed and applied; `GameBudgeter` cap
  enforced (`gameplay.game_budget_tokens`, 0 = unlimited); per-model cooldown cleared on
  credential reload and made configurable; `duty_imminent` accepts the Mod's real
  `start_hour`/`start_minute_of_day` shape; `POST /agency/seats` persists its override;
  deep-window signal persisted and exposed in `/v1/status`; eviction distance uses the real
  active position.
- **Mod (Python 3.7):** honest failures instead of false success for `prefer_target`,
  `weather.set` (real `CommonWeatherUtils.start_weather_event`), `zone.modifier`,
  `notification.send` and `spawn_npc`; added the missing `playful`/`embarrassed`/`scared`
  emotion buffs; `next_sleep` expiry + failed-intent retry wired; `set_goal` reports a
  local-mirror note; `save_id="unknown"` no longer crashes the sidecar; provoke pie-menu
  fixed (S4CL-aware sim id + localized prompt).
- **Contracts:** defensive `to_int()` for `save_id`; canonical tick units across
  leases/seats/impulse.

### Deferred / documented

Dead config keys and no-op functions, wire fields the sidecar ignores (`content`,
`households`, `player_id`, `new_zone_id`, `player_confidant_sim_id`), `remember`/`forget`
(no-op by design), some swallowed exceptions, and the MCP layer (see [`mcp.md`](mcp.md)).

---

## Stage 1 — Spike-Driven Development & State Sanitation (2026-10-05)

> **Branch:** `v2-remake`. First wave of the [restructured roadmap](#restructured-execution-roadmap).
> Executed under the "never code blind" rule: every native-hook probe is now backed by a
> decompilation study and a runtime harness instead of guesswork.

### Decompilation study

- `scripts/decompile_ts4.py` (new) + `scripts/decompile-scripts.ps1` (rewritten): modern TS4
  ships its server scripts as `.pyc` archives at `Data\Simulation\Gameplay\{base,core,
  simulation}.zip` (Python 3.7, magic `42 0d 0d 0a`). The old script pointed at a layout that
  no longer exists. Extraction + decompile via `decompyle3` into `research/ts4/` (gitignored —
  proprietary EA code).
- `research/engine_api_notes.md` (new): ground-truth facts read from the decompiled source —
  console-command registration (`CommandType.Live`, not `DebugOnly`), `SituationManager.
  create_situation/create_visit_situation`, `Relationship.sim_id_a/sim_id_b`, `SocialGroup.
  member_sim_ids_gen()`, `Buff.mood_type`/`mood_weight`, `SimInfo` fields, and the
  implications for each of the 4 probes.

### Closed-loop intent telemetry (R1)

- Mod (`intent_bus.py`): `IntentBus.record_outcome`/`drain_outcomes` + a bounded outcomes
  deque; expiring intents now emit `expired` outcomes instead of vanishing silently.
- Mod (`tool_executor.py`): `execute_intents` records `applied` / `failed`(retry) /
  `failed`(max_retries) per intent.
- Mod (`main.py` / `http_client.py`): the autonomy pulse drains and attaches `outcomes[]`.
- Sidecar (`services.py`, `routers/autonomy.py`, `sqlite_store.py`): `_ingest_outcomes`
  validates/counts/persists outcomes to a new `intent_outcomes` table; `POST /v1/actions/
  outcomes` for immediate reports; counters exposed in `/v1/status`.

### Confidant persistence (R8 / P0)

- Sidecar: `player_confidant_sim_id` is stored in the save's `metadata` table (new
  `SqliteStore.get_metadata`/`set_metadata`) and returned on `session-start`.
- Mod (`native_hooks.py`, `main.py`, `http_client.py`): the `session-start` callback adopts
  the persisted id (`set_player_confidant_sim_id`) instead of re-running the BUG-12 string
  search; a first-time save creates the confidant and reports it on the next pulse.

### Pre-session event buffer (R7)

- `lifecycle_hooks.py`: genuine lifecycle events (death/birth/marriage) that arrive during
  the load window are now **buffered** (max 8) and flushed on `mark_lifecycle_ready()`,
  instead of being silently dropped (previously the realtime lane saturated and epoch-0
  events were lost).

### LLM JSON repair (R5)

- `llm/json_repair.py` (new) + wired into `llm/scheduler._extract_json` /
  `_balanced_json_block`: strips `<think>/<reasoning>` blocks and markdown fences, fixes
  trailing commas, smart quotes, and bare `NaN`/`Infinity` before parsing. 53 tests.
- `response_format: {"type":"json_object"}` deferred (touches 4+ provider files; lower value
  than the repair layer and riskier to do blind).

### Spike harness & data probes (R3)

- `mod/sensewright_mod/engine_facade.py` (new): defensive, never-raising facade isolating
  EA/S4CL access (SimInfo fields, interaction/social-group reads, situation spawn, buff
  roundtrip, object resolution) — the single place native idiosyncrasies live.
- `mod/sensewright_mod/spikes.py` (new): console commands `sw.spike <name>` and
  `sw.smoke_test` (registered via `sims4.commands.Command(..., CommandType.Live)`), plus the
  4 data probes (`interaction`, `ui_injection`, `routing`, `relationship`). Each probe prints
  a console summary and appends a JSON line to `mod_logs/Sensewright_Spike.log`.
- `main.py`: imports `spikes` for the command-registration side effect.
- **In-game validation (2026-10-05):** the 4 probes were run in build 1.128.90.1030 —
  `interaction`, `routing` and the `ui_injection` buff roundtrip are ✅ validated; balloon,
  tooltip and `relationship` (bits `[]`, sentiments unread) are 🟡 partial. Full table:
  [`spike-strategy.md`](spike-strategy.md) §5.1.

### Deferred

- **SSE unification (R2)** — the single-inbound-thread transport (SSE `timeout=15` + keepalive
  + pull fallback). Deferred deliberately: it is a shutdown-path-sensitive change (`timeout=None`
  hangs `TS4_x64.exe`, PC-02) that must be validated in-game, and the existing intent pull
  (4.3) already delivers intents. Tracked for the next wave.

### Verification

- `cd sidecar && python -m pytest -q` → **763 passed** (689 → +53 json_repair + +21 stage1).
- `py -3.7 -m compileall -q mod\sensewright_mod` → clean (spikes.py + engine_facade.py included).
- `python mod/build_package.py` → 46 resources; `python mod/build.py` → 118,174 bytes.

---

## Remaining work after Stage 1 (2026-10-05)

The gap between where the project is now and the rest of the [restructured roadmap]
(#restructured-execution-roadmap). Ordered by the stability critical path; each entry
names what depends on it. The new data probes proposed for the next in-game session are
detailed in [`spike-strategy.md`](spike-strategy.md) §6.

### A. In-game validation (blocks release — needs the game)

1. **Object interactions end-to-end** — the tunings load and mirror/mailbox match, but the
   click→endpoint flow was never exercised: Mirror "Reflect" → `/v1/evolve`; Mailbox →
   `/v1/world/neighborhood`; Diary "Ler/Snoop" → `/v1/memory/diary` (diary `found=0` — see
   `diary_object` spike). Unblocks P2 native hooks.
2. **God Director full loop** — `god.plan` → `god.cast` (spawn ✅) → `god.puppeteer`
   (approach ✅ fixed) → conversation → `beat-ended` → `god.react` → arc advance. Confirm a
   single arc completes without burning through beats (BUG-14).
3. **M8 acceptance** — lot transition, *Save As*, *Alt+F4* rollback, invisible autoboot.
   None executed yet (unit tests only).

### B. Sidecar-only (no game needed — do in parallel)

4. **Token Priority Packing (R4)** — `ContextAssembler` overflows the 700-token realtime
   tier; the BUG-10 scene hints crowd out persona/memories. P0/P1/P2 packing + a
   parameterized 33-purpose token test.
5. **`response_format: {"type":"json_object"}`** — the deferred half of R5 (touches the
   provider layer; reduces the fallback cascade on free models).
6. **R8 GC routine — needs the game, not sidecar-only.** The ~20 orphan "Confidente
   Sensewright" `SimInfo`s live in the TS4 `.save`; only the canonical id is in the sidecar
   `metadata`. Purging them requires a Mod-side routine run in-game (Stage 3).

### C. Deferred / risky (documented, revisit carefully)

7. **SSE unified transport (R2)** — single inbound thread (SSE `timeout=15` + keepalive +
   pull fallback). Shutdown-sensitive (`timeout=None` hangs `TS4_x64.exe`, PC-02); the
   intent pull already delivers intents.
8. **MCP layer (Stage 4)** — only after Stages 1–3; facades over levers that are 100%
   in-game validated.

### D. Backlog / scope decisions

9. **P2 hook decisions** — keep `sim_GetToKnow`; **defer** the physical Autobiography book
   and the Tombstone epitaph; sleep balloons stay best-effort (complex `BalloonRequest`).
10. **Web Studio (P4)** — real `spoiler_shield`, Sim export/import (FC2), cost dashboard
    (FC3), `director_mode` selector.
11. **FC5 compatibility layer** (MCCC/Whims) — backlog.
12. **FC1 Onboarding Wizard (2.6)** — still the single notification; the 3-option dialog
    (Quick / Web / Play) is scheduled as Stage 4 (first thing a new user sees).

## Recommended execution order (2026-10-05)

Canonical order, revalidated against all docs. Principle: resolve what is unproven in the game
first (almost every severe blocker came from wrong EA/S4CL assumptions, not the sidecar); run
everything that does not need the game in parallel.

| Stage | Scope | Needs game | Notes |
|---|---|---|---|
| **0** | Docs sync (this revision) | No | Status summary, open items, probe results, single roadmap. |
| **1** | Phase-2 spikes in **one batched session**: `relationship_bits` → `mood_effect` → `lifecycle` → `diary_object` → `trait_levers`; then move findings into `engine_facade.py` (balloon signature, tooltip via `obj.tooltip_text`, relationship bits) | Yes | `relationship_bits` first: blocks `sim.social` tier, `mem.relationship.review`, sentiments. |
| **2** (parallel) | Sidecar: **R4 token packing** (+ parameterized 33-purpose token test) → `response_format: json_object` → Web Studio P4 (`spoiler_shield`, `director_mode` selector, FC2 export/import, FC3 cost dashboard) | No | R4 first: highest quality/cost return (BUG-10 hints overflow the 700-token tier). Also automate non-game M8 scenarios (no key, network timeout, long session). |
| **3** | **Playtest #5 consolidated**: object interactions (Mirror/Mailbox/Diary), full God loop + BUG-14, M8 game scenarios (zone transition, *Save As*, *Alt+F4*, invisible autoboot), R8 confidant GC | Yes | One session for both E2E flows and M8. |
| **4** | FC1 Onboarding Wizard, close-out of `project-status.md` / README | Partly | |
| **5** | MCP layer ([`mcp.md`](mcp.md)); adds the `RULE_AUTOMATION` lease (PC-04) | Yes | Only after Stages 1–3; `outcomes[]` closed loop already exists. |

**Defer / cut:** R2 SSE transport (only if Playtest #5 shows intent-pull latency; shutdown-hang
risk), physical Autobiography book, Tombstone epitaph, FC5, sleep balloons (best-effort).

### Open "coded blind" surfaces (→ new spikes)

The 4 master probes validated interaction/routing/buff/relationship-friendship, but these
remain unproven and are the target of [`spike-strategy.md`](spike-strategy.md) §6:

- **Relationship bits + sentiments** — the relationship probe returned `bits: []` for a
  high-friendship pair; sentiments are unread. Feeds `sim.social` tier, `mem.relationship.
  review`, sentiment feedback.
- **Mood effect** — `set_mood` applies the buff but was never confirmed to change the mood.
- **Lifecycle events** — death/marriage/birth S4CL events are wired but never fired.
- **Trait levers** — `set_trait`/`remove_trait`/`add_relationship_bit` coded blind.
- **Custom diary object** — `sw_diary_object` `found=0` on the test lot.

