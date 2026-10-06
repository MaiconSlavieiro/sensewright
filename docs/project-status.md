# Project Status & Roadmap

Where the project stands against the specification and what remains: the spec↔code gap per milestone/feature/purpose, the execution plan to close the gaps, and the reverse-chronological changelog.

**On this page**

- [Implementation Status](#implementation-status)
- [Gap-Closing Plan](#gap-closing-plan)
- [Changelog](#changelog)

---

## Implementation Status

> **Date:** 2026-10-02
> **Branch:** `v2-remake`
> **Reference base:** [`specification.md`](specification.md)
> **Purpose:** to precisely record what **is already implemented and verified** and what
> **is genuinely still missing** from the full plan (22 features, 33 purposes, adjustments
> A1–A11, and complementary features FC1–FC5).

This document is the source of truth for the gap between the specification and the code.
References use the `file:line` format.

---

### 1. Executive summary

> ⚠️ **CRITICAL ARCHITECTURAL IMPERATIVE:** Infrastructure and communication hardening (like the SSE protocol unification `P1` and the Sidecar thread-safety `P2` listed in `operations.md`) are NOT secondary technical debt. Because TS4 is strictly single-threaded, any latency or IPC flaw breaks the core gameplay loops. **These hardening items MUST be treated as primary features and blockers for any further functional playtests.**

> ✅ **Current state (2026-10-06):** Stage 2 (Web Studio Phase 4 & FC2/FC3) is complete. The sidecar suite has **763 tests**; **26 of 33 purposes Full**.
> The canonical execution order is the [Recommended execution order](operations.md#recommended-execution-order-2026-10-05) in `operations.md`, with **Architectural Review & Evolution Plan (Hardening)** taking precedence over Playtest #5.

The project has a **solid, tested foundation**: both processes (Mod Python 3.7 and Sidecar
FastAPI) talk to each other, the transactional save cycle works, the manifest-driven i18n
engine is complete, the LLM layer (triple limits, circuit breaker, single-queue scheduler,
tiered ContextAssembler) exists, and the build produces valid `.ts4script` (bytecode 3.7) and
`.package` (DBPF + STBL).

> ⚠️ **New Methodology: Spike-Driven Development.** To stop the cycle of "coding blind" against EA's volatile API and the resulting rework loops, all future Mod-side features (especially Phase 5 / native hooks) MUST follow the [Spike-Driven Development Strategy](spike-strategy.md). Every EA API interaction will be proven via an in-game spike (`sw.spike` / `sw.smoke_test`) *before* integration.

What is **genuinely missing** is not foundation, it is **wiring and triggers** (mostly Phase 5 in-game validation):

- **Three partial purposes** (`sim.diary`, `sim.lifestory`, `mem.consolidate` triggers missing/partial).
- **Native hooks (M5/M6)**: missing Diary/"Snoop", Autobiography Book, `VisitSituation` (NPC
  ringing the doorbell), Tombstone Epitaph, sleep balloons, and the "Reflect" interaction on
  the mirror (some implemented but need in-game validation).

Everything that exists today is covered by **763 tests** (sidecar) and compiles under both correct interpreters. The 2026-10-02 P2/P3 wave (lifecycle
events, `spawn_npc`, `god.react`/`beat-ended`, mirror/diary/mailbox hooks, sleep balloons,
object/situation build types) is coded blind and awaits the Phase 5 in-game checklist.

---

### 2. Validation performed in this review

> Numbers below are the 2026-10-06 snapshot. Current: `pytest` **763 passed**; `.package`
> 46 resources; `.ts4script` rebuilt (see [Changelog](#changelog)).

| Check | Command | Result |
|---|---|---|
| Sidecar test suite | `python -m pytest -q` in `sidecar/` | **763 passed**, 1 warning |
| Mod syntax (Python 3.7) | `py -3.7 -m py_compile` on `mod/sensewright_mod/*.py` | **OK** (20 files) |
| Build script syntax (3.10+) | `python -m py_compile mod/build.py mod/build_package.py` | **OK** |
| `.package` build | `python mod/build_package.py` | **OK** — 44 resources (32 buffs, 7 interactions, 1 trait, 1 object, 1 situation, 2 STBL) |
| `.ts4script` build | `python mod/build.py` | **OK** — 84,686 bytes, Python 3.7 magic number `42 0d 0d 0a` verified |
| Secret scan of the diff | `git diff` for `sk-…`/`api_key=` | **Clean** |
| `.gitignore` | `git check-ignore` | `sidecar/config.toml` and `dist/` ignored |

> Validation is **unit/static**. The M8 acceptance criteria (batch transition, *Save As*,
> *Alt+F4*, invisible autoboot) **require execution inside The Sims 4** and have not yet been
> performed.

---

### 3. Milestones M0 → M8

| Milestone | Focus | Status | Note |
|---|---|---|---|
| **M0** | Foundation, IPC & Save Vault | ✅ **Complete** | Thread isolation, dual-clock, SaveVault (working/committed/ring buffer), `/v1/lifecycle/*`. |
| **M1** | Routing, TPM & Language | 🟡 **Partial** | Triple limits, 60 s circuit breaker, `free_only`, 6 providers, and i18n complete. **Missing**: per-model 120 s cooldown (`chain.py:28-29` is dead code). |
| **M2** | Scheduler, ContextAssembler & Intents | 🟡 **Partial** | Single-queue scheduler, SLO, input ceiling, dedup, and 2-layer config OK. **Missing**: per-tier concurrency enforcement; asymmetric refund inert. |
| **M3** | Cognition, Dreams & FTS5 | 🟡 **Partial** | FTS5 (BM25) and full tables; dream/cognition engines and prompts exist. **Missing**: sleep triggers, `apply_cognition`, psyche decay/prune, VACUUM. |
| **M4** | God Director & Catalysts | 🟡 **Partial** | `god.zeitgeist`, `god.narration`, `god.plan` (submitted), and basic lease/puppeteer. **Missing**: build/query arcs, `god.cast`/`god.scene`/`god.react`/`god.background`, NPC spawn, `BackgroundScheduler`. |
| **M5** | Levers, ArchetypeResolver & Hooks | 🟡 **Partial** | Buffs/moodlets/sentiments/traits and 14 bias buffs. **Missing**: empty activity/archetype maps, `VisitSituation`, likes/dislikes, mirror. |
| **M6** | Chat Hidden SimInfo, Diary & World | 🟡 **Partial** | Hidden SimInfo + chat channels (SMS) + basic chained loop. **Missing**: navigable `pc_chat`/`pc_email`, Diary/"Snoop", mailbox, gossip SMS. |
| **M7** | Dual UI & Logs | 🟡 **Partial** | Quick Menu + real Web Studio SPA; `trace_id` and 10 MB × 3 rotation. **Missing**: wiring of several Web Studio controls; `trace_id` is lost in `bg` jobs. |
| **M8** | In-Game Validation & Release | ❌ **Not started** | Only unit validation. `/v1/i18n/compile-addon` is a stub. Acceptance criteria not executed. |

---

### 4. Features F01 → F22

| Feature | Status | Evidence / main gap |
|---|---|---|
| **F01** Multi-channel chat, Hidden SimInfo & continuous UI | 🟡 Partial | Hidden SimInfo complete (`native_hooks.py:85-160`); basic chained UI (`chat_ui.py:75-209`). Missing `pc_chat`/`pc_email` channel, native Wants (fallback via moodlet `native_hooks.py:340-363`), inert local deferral. |
| **F02** Profile Generation & bootstrap | ✅ Complete | `normalize_profile` (`agent/profile.py:31`), hydration via census (`services.py:111-121`), 2 stages (template + `bg`). |
| **F03** Initiative / Impulse | 🟡 Partial | `idle` impulse and speech pruning OK (`services.py:146-153`). Survival guard computed but **not applied** (empty schedule in `agent/impulse.py:81`; no filter in the executor). |
| **F04** Social Layer & asymmetric dialogue | 🟡 Partial | Symmetric pre-flight OK (`agent/social.py:17-43`). **Asymmetric is not routed**: `build_social_context` never receives `puppeteer` (`services.py:269`); lines/min limit not enforced; CHILD not blocked. |
| **F05** IntentBus | ✅ Complete | Canonical shape, TTL, `expires_on`, `retry_count`/`max_retries` (`intent_bus.py:37,44,272`), freeze on pause. |
| **F06** SeatManager | ✅ Complete | Strict priority, anti-thrashing lease, distance eviction (`agent/seats.py:18-133`). Caveat: pool can exceed `max_seats` with many protected leases. |
| **F07** Hybrid cognition & Dream Engine | 🟡 Partial | Surrealism formula and `dream`/`cognition` ready (`agent/dreams.py`, `agent/cognition.py`). **No sleep trigger**; sleep balloons and tooltip tokens missing; `apply_cognition` never called. |
| **F08** Personality & Psyche | 🟡 Partial | Salience by metadata + reinforcement wired (`services.py:393-406`). **Missing**: exponential decay per `sim_tick` and prune never called; Life Story limit (20 lines / 2,000 chars) not enforced. |
| **F09** Evolution, Demeanor & Likes | 🟡 Partial | `evo.reflect` responds, but `apply_reflection` **is not called** (`services.py:456-471`); no likes/dislikes writer; swap proposal not emitted. |
| **F10** Memory, FTS5 & Shadow DB | ✅ Core / 🟡 Periphery | Core complete and tested. Periphery: 180-day prune unscheduled, "Save As" doesn't read `previous_save_id`, VACUUM missing. |
| **F11** Speech Policy (Pre-Flight) & routing | 🟡 Partial / ❌ | `hearing_radius` OK; `max_lines_per_minute`/`min_interval` **not enforced**. Channels: compact `SPEECH` card missing; banner/portrait partial. |
| **F12** Presence Policy & Capability Matrix | 🟡 Partial | Capabilities and BABY exclusion OK (`agent/presence.py:19-45`). **`hard_blocked_social` (CHILD flirty/intimate) defined but never called**; `off` tier dead. |
| **F13** Coordinator & arbitration | 🟡 Partial | Priorities/constants and 3 leases (`coordinator.py:23-30`). `SANDBOX_OVERRIDE` not assigned; lease expiration not checked. |
| **F14** God Director & `god.puppeteer` | 🟡 Partial | 7 presets/5 dials defined, but only `intervention_frequency` influences (`orchestrator.py:54`). `CO_DIRECTOR` ≡ `AUTONOMOUS`; casting/spawn missing; no `BackgroundScheduler`. |
| **F15** LLM Provider Chain, TPM & language | 🟡 Partial | RPM/RPD/TPM, circuit breaker, `free_only`, 6 providers — OK. Missing per-model cooldown. |
| **F16** ModelRouter, Tiers & ContextAssembler | 🟡 Partial | SLO/ceiling/dedup/2 layers OK. Per-tier concurrency not applied; asymmetric refund inert; `thinking_budget` only becomes `temperature=0`. |
| **F17** Tools, Levers, ArchetypeResolver & Hooks | 🟡 Partial | 9 intents with `_safe_call`; buffs/moodlets/sentiments/traits. Activity/archetype maps **empty** (`tuning.py:229,232`); several native matrix rows missing. |
| **F18** i18n System & STBL | ✅ Engine / 🟡 Export | 4-level cascade, manifest, gender, rotation, hot-reload, and Mod compiler — OK. `/v1/i18n/compile-addon` is a stub. |
| **F19** Observability & rotation | 🟡 Partial | `trace_id` propagated and 10 MB × 3 rotation OK. `bg` worker loses `trace_id` (ContextVar not inherited). |
| **F20** Build, Deploy & autoboot | ✅ Complete | `.ts4script` 3.7 + `.package` DBPF/STBL; autoboot `CREATE_NO_WINDOW` (`http_client.py:94-155`). |
| **F21** Dual UI (Quick Menu + Web Studio) | 🟡 Partial | Quick Menu OK; real Web Studio SPA (`webui/`). Incomplete wiring: saving profile/keys and scene buttons don't persist. |
| **F22** World Layer & rumor epidemiology | 🟡 Partial | `RumorNode` model complete and tested (`world/rumors.py`). **No production call** creates/spreads a rumor; chronicle/mailbox/aftermath missing. |

---

### 5. Catalog of the 33 purposes

States: **Full** = complete wiring + consumption · **Partial** = pipeline exists but no
trigger/application · **Fallback-only** = only `fallbacks.py` + declaration in
`purposes.py` (no production trigger) · **Missing** = not implemented.

> All 33 have a deterministic 0-key fallback (project guarantee), so "Fallback-only" means
> *the service responds, but is never triggered with real data*.

> **Note:** A purpose (Pxx) can be ✅ Full while its parent feature (Fxx) is still 🟡
> Partial, because the feature encompasses additional integration work (e.g., in-game
> hooks, native UI, sleep balloons) beyond the sidecar pipeline itself.

| ID | Purpose | Status | Evidence / gap |
|---|---|---|---|
| P01 | `sim.chat` | ✅ Full | `services.py:333-382` |
| P02 | `sim.profile` | ✅ Full | `services.py:426-453` — generation-only by design; the endpoint generates a profile, it does not accept one from the client (Web Studio profile editing is the gap-closing plan §4.1). |
| P03 | `sim.impulse` | ✅ Full | `services.py:245-260` (inert survival guard) |
| P04 | `sim.reaction` | ✅ Full | `services.py:386-422` |
| P05 | `sim.social` | ✅ Full | `services.py:262-276` (asymmetric not routed) |
| P06 | `sim.social.close` | ✅ Full | tracking edges from census; callback writes social memories and fills social_sessions |
| P07 | `sim.dream` | ✅ Full | Sleep trigger (`services._process_sleep_transitions`) + engine/prompt/fallback + `dream_urge` in the profile |
| P08 | `sim.cognition` | ✅ Full | Chained post-dream; `apply_cognition` persists `daily_plan`/biases (`services._cognition_callback`) |
| P09 | `sim.sleep` | ✅ Full | Wake trigger (if salient event); memory + psyche reinforcement |
| P10 | `sim.diary` | 🟡 Partial | End-of-day trigger + `diary` memory; missing in-game Tooltip/Snoop (`P2`) |
| P11 | `sim.lifestory` | ⚪ Fallback-only | Life Story limits applied (`enforce_life_story`), but no 7-day trigger |
| P12 | `sim.aspiration` | ✅ Full | ambition in profile, /v1/sim/aspiration endpoint, census ingested |
| P13 | `sim.background.expand` | ✅ Full | family backstory memories on demand |
| P14 | `god.zeitgeist` | ✅ Full | `god/zeitgeist.py:20`, `services.py:517` |
| P15 | `god.plan` | ✅ Full | `_plan_callback` creates and persists the arc (`create_arc` + `save_arc`) |
| P16 | `god.cast` | ✅ Full | Reuses compatible non-player townie or emits `spawn_npc` |
| P17 | `god.scene` | ✅ Full | Beat armed → `god.scene` writes `scene_draft`/`scene_subtext` to the beat |
| P18 | `god.puppeteer` | 🟡 Partial | Lease + opening line (`god/puppeteer.py`); no spawn/approach/asymmetric objective/continuation |
| P19 | `god.react` | ✅ Full | Folds agent decision, inserts `next_beat`, `advance_arc` |
| P20 | `god.narration` | ✅ Full | `god/orchestrator.py:17-80` |
| P21 | `god.background` | ✅ Full | BackgroundScheduler with priority |
| P22 | `world.npc.backstory` | ✅ Full | recurring-townie detection + background |
| P23 | `world.household.chronicle` | 🟡 Partial | End-of-day trigger + persistence; missing in-game Mailbox (`P2`) |
| P24 | `world.gossip` | ✅ Full | Creation on salient public event + contagion at the end of `sim.social` + SMS (`_create_rumor_from_event`/`_spread_rumor`) |
| P25 | `world.aftermath` | ✅ Full | high-salience events shift zeitgeist and enqueue durable intents |
| P26 | `mem.consolidate` | 🟡 Partial | Endpoint works (`services.py:474`); **no automatic trigger** (300 s/zone) |
| P27 | `mem.compact` | 🟡 Partial | Automatic trigger (≥ 20 consolidated) + archive 15 + VACUUM (`services._maybe_compact`); missing panel exposure |
| P28 | `mem.legacy` | ✅ Full | Legacy memory on death/marriage/birth |
| P29 | `mem.relationship.review` | ✅ Full | census ingested; once-per-day edge review |
| P30 | `evo.reflect` | ✅ Full | `handle_evolve` + `_reflect_callback` apply and persist `current_demeanor` |
| P31 | `evo.trait` | 🟡 Partial | Helpers ready; no `run_purpose`/emission |
| P32 | `ops.recap` | ✅ Full | recapped at session-start, stored, GET /v1/recap |
| P33 | `ops.panel.summary` | ✅ Full | deterministic 2-line summary in GET /v1/panel/summary and /v1/status |

**Total: 26 Full · 6 Partial · 1 Fallback-only.**

---

### 6. Adjustments A1–A11 and Complementary Features

| Item | Status | Evidence / gap |
|---|---|---|
| **A1** 3-layer autoboot | 🟡 Partial | Layers 2 (Popen) and degraded exist; **external launcher missing**; manual guidance only in the docs. |
| **A2** Extra Python 3.7 constraints | ✅ Complete | No walrus/match/union/future/`cached_property` in the Mod. |
| **A3** Detailed freeze on pause | ✅ Complete | `intent_bus.py:173-180`; sidecar freezes (`services.py:216-218`). |
| **A4** Wants → moodlet | 🟡 Partial | "Missing" moodlet implemented (`native_hooks.py:340-363`); native Wants missing. |
| **A5** `queue_interaction` → `bias_activity` | ✅ Resolved | Canonical intent is `bias_interaction` (`intent_bus.py:16`). |
| **A6** `retry_count` in IntentBus | ✅ Complete | `intent_bus.py:37,58,272`; `agent/intents.py:65-66`. |
| **A7** Pool of 4 dream buffs | ✅ Complete | `mod/tuning/buffs/buff_dream_*.xml`; selection in `native_hooks.py:212-233`. |
| **A8** "Reflect" interaction on the mirror | ❌ Missing | Only the locale key exists; no class/XML. |
| **A9** VACUUM after `mem.compact` | ❌ Missing | `MemoryStore.vacuum()` exists but is never called (`sqlite_store.py:565`). |
| **A10** Expansion Pack guard | ❌ Missing | Mod sends `installed_packs` (`state_collector.py:490`); sidecar ignores it. |
| **A11** Hook prioritization | 🟡 Partial | High priority partial; medium/low items missing. |
| **FC1** Onboarding Wizard | 🟡 Partial | Single notification (`main.py:149-206`); no 3 options (Quick/Web/Play). |
| **FC2** Sim Export/Import | ❌ Missing | Backlog (M8+). |
| **FC3** Cost/usage dashboard | ❌ Missing | Tab 3 only shows current RPM/RPD/TPM. |
| **FC4** Panic Button (Ctrl+Shift+S) | ❌ Missing | `IntentBus.clear_all` defined and never called (`intent_bus.py:283`). |
| **FC5** Compatibility layer (MCCC/Whims) | ❌ Missing | Backlog. |

---

### 7. Prioritized gaps (what genuinely remains to implement)

> **Detailed execution plan:** the [Gap-Closing Plan](#gap-closing-plan) below (phases P1 residual → P2/P4 → M8,
> with dependencies, risks, and the in-game checklist).

#### P0 — Unblock the narrative core (highest impact, lowest effort) — ✅ DONE

1. ✅ **Sleep triggers** (Mod → Sidecar): `_process_sleep_transitions` detects `is_sleeping`
   edges in the autonomy pulse and fires `sim.dream` → `sim.cognition`
   (`apply_cognition` persists `daily_plan`/biases) and, on wake, `sim.sleep` (if salient
   event) + `evo.reflect`.
2. ✅ **Apply `evo.reflect`**: `handle_evolve` and `_reflect_callback` call
   `apply_reflection` and persist `current_demeanor` (`services.py`).
3. ✅ **Psyche decay/prune** on wake (`decay_blocks`, by sim-day delta) and **Life Story limit**
   (`agent.profile.enforce_life_story`, 20 lines / 2,000 chars).
4. ✅ **Speech Policy enforcement**: `agent/speech.py` (60 s window + minimum interval)
   applied at the `sim.social` gate; `hard_blocked_social` (CHILD) in pre-flight and on
   emission; `physical_actions_allowed` computed with real `schedule_blocks` and applied in
   the `sim.impulse` callback.
5. ✅ **`world.gossip` + social contagion**: `_create_rumor_from_event` creates and persists
   the rumor on a salient public event (with witnesses), `_spread_rumor` contaminates at the
   end of `sim.social`, and the Mod displays the diegetic SMS (`tool_executor.py`).

#### P1 — Complete God Director and World Layer (partial)

6. 🟡 **Consume `god.plan`** ✅ (`_plan_callback` → `create_arc` + `save_arc`) and
   **`god.scene`** ✅ (`_scene_callback` writes `scene_draft`/`scene_subtext` to the beat).
   **`god.cast`** (NPC spawn) and **`god.background`** still pending.
7. ❌ **Real `god.puppeteer`**: spawn/`VisitSituation`, approach, injection, and
   post-reaction branching (depends on the Mod / in-game validation).
8. 🟡 **`sim.diary`** ✅ and **`mem.compact`** ✅ (trigger + VACUUM) with handlers.
   **`sim.social.close`, `mem.legacy`, `mem.relationship.review`, `ops.panel.summary`**
   still pending.
9. ❌ **`BackgroundScheduler`** with priority `PLAYER > HOUSEHOLD > ACTIVE > RELATED`.
10. 🟡 **Family chronicle** ✅ (`_maybe_end_of_day` → `append_chronicle`).
    In-game **Mailbox** and **`world.aftermath`** pending.

#### P2 — Native hooks (M5/M6) — pending (requires in-game validation)

11. `VisitSituation` (catalyst NPC via the sidewalk/doorbell).
12. Diary with *TooltipComponent* + **"Snoop"** interaction; Autobiography Book.
13. `sim_GetToKnow` revealing `secrets[]`/`background`.
14. Tombstone Epitaph; sleep balloons; custom "Reflect" interaction on the Mirror (A8).

#### P3 — LLM, Config & Observability — ✅ DONE

15. ✅ Per-model 120 s cooldown in `chain.py` (`_record_failure` per `(provider, model)`).
16. ✅ Per-tier concurrency enforcement in `LLMScheduler` (non-blocking semaphore; excess
    degrades to the deterministic fallback).
17. ✅ Asymmetric refund fixed: debit on send; refund only the Game Budget on failure and
    settle with actual usage on success.
18. ✅ `installed_packs` in the Census → `AppState.installed_packs` + exposed in `/v1/status`
    (basis for EP guards).
19. ✅ `trace_id` propagated to `bg`/`deep` jobs (`set_trace_id` in the worker).
20. ✅ VACUUM after `mem.compact` (A9), called every 20 consolidated memories.

#### P4 — UI, Release & Backlog — pending

21. Web Studio: persist profile/keys/casting/beats (the backend ignores them today).
22. Real `/v1/i18n/compile-addon` (generate `Sensewright_Locale_<code>.package`).
23. Panic Button (FC4), Onboarding Wizard (FC1), cost dashboard (FC3).
24. **M8 in-game**: lot transition, *Save As*, *Alt+F4* rollback, invisible autoboot.
25. Sim Export/Import (FC2) and compatibility layer (FC5).

---

### 8. Repository hygiene notes

- `sidecar/python.txt` is a **local** configuration file (points to the user's 3.10+
  interpreter). It is listed in `.gitignore` so machine-absolute paths are not versioned;
  if present in the working tree it is ignored by Git. Create it manually after cloning.
- `research/s4cl/` and `research/lot51_core/` are reference clones and remain ignored (not
  redistributed).

---

### 9. Implementation changelog (2026-10-02)

Waves P0, P3, and part of P1 implemented and covered by tests. No schema change; the HTTP
wire remains compatible.

#### New modules (sidecar)

- `agent/sleep.py` — `sleep_start`/`wake` edge detection (P07-P09).
- `agent/speech.py` — speech policy (lines/min + minimum interval) (F11).
- `agent/profile.enforce_life_story` — Life Story limit (REQ-PSY-03).

#### Main wiring (`services.py`)

- `_process_sleep_transitions` / `_on_sleep_start` / `_on_wake`: fires
  `sim.dream` → `sim.cognition` (`apply_cognition`) and, on wake, `sim.sleep` +
  `evo.reflect` (`apply_reflection`); applies psyche decay.
- `_maybe_end_of_day`: family chronicle + active Sim diary (P23/P10).
- `_create_rumor_from_event` / `_spread_rumor`: gossip and contagion (P24).
- `_impulse_callback` now respects `physical_actions_allowed` (REQ-IMP-03);
  the `sim.social` gate respects the speech policy and the CHILD hard-block.
- `_maybe_compact` + `SqliteStore.consolidated_memory_ids`: compaction and VACUUM (P27/A9).
- `handle_census` stores `installed_packs`; `/v1/status` exposes them (A10).

#### God Director (`god/orchestrator.py`)

- `_plan_callback` creates/persists the arc (`god.plan`, P15).
- `_scene_callback` writes `scene_draft`/`scene_subtext` to the armed beat (`god.scene`, P17).

#### LLM (`llm/`)

- `chain.py`: per-model cooldown (120 s) effectively enforced.
- `scheduler.py`: per-tier concurrency (non-blocking semaphore), correct asymmetric refund,
  and `trace_id` on `bg`/`deep` jobs.
- `sqlite_store.py`: `consolidated_memory_ids`; `vacuum()` is now called.

#### Mod (`mod/sensewright_mod/tool_executor.py`)

- `world.gossip` now displays the rumor as a diegetic notification (SMS/gossip).

#### Tests

- `sidecar/tests/test_p0_lifecycle.py` (19 tests), `test_p3_resilience.py` (8), and
  `test_p1_god_world.py` (7) → **508 green tests**.
- Verification: `python -m pytest -q` (508), `py -3.7 -m py_compile` on the Mod,
  `python mod/build.py` (69,683 bytes), and `python mod/build_package.py` (25 resources).

#### Still pending

P1 residual (complete `god.puppeteer`, `BackgroundScheduler`, `world.aftermath`,
`ops.panel.summary`, `mem.relationship.review`, `sim.social.close`), the remaining P2 hooks
(`sim_GetToKnow`, Autobiography Book, Tombstone Epitaph) and P4 (Web Studio, compile-addon,
M8 in-game, FC2/FC5).

---

### 10. Implementation changelog — P2/P3 wave (2026-10-02)

Wired the Mod event sources / God Director contracts and the tangible UI hooks. All Mod
hooks are coded **blind** and must be validated in-game (Phase 5); the sidecar side is
covered by tests. No schema change; the HTTP wire remains additive and compatible.

#### Sidecar

- `schemas.INTENT_KINDS` / `agent.intents.PHYSICAL_KINDS`: new `spawn_npc` kind (2.4).
- `services.handle_event`: lifecycle categories (`death`/`marriage`/`birth`, from
  `constants.LEGACY_CATEGORIES`) now fire `mem.legacy` synchronously → decay-immune
  `legacy` memory + `sim.lifestory` chapter (2.1/1.8, P28/P11).
- `god/cast.py` (new): `run_cast` reuses a compatible non-player townie or emits a
  `spawn_npc` intent; integrated into `god_tick` (1.1, P16).
- `god/react.py` (new) + `POST /v1/god/beat-ended`: `run_react` / `apply_react` fold the
  agent's accept/reject/fight decision, insert a `next_beat`, `advance_arc`, and mark
  `ARC_DONE` (1.2/2.9, P19).
- `GET|POST /v1/world/neighborhood`: chronicles + zeitgeist + a Sim's known rumors (3.9).
- `GET|POST /v1/memory/diary`: latest saved diary entry for the Tooltip/Snoop (3.4).
- `god_tick` now receives `active_sim_id` so casting targets the active Sim.

#### Mod (`mod/sensewright_mod/`, Python 3.7)

- `lifecycle_hooks.py` (new): S4CL `S4CLSimDiedEvent`, `S4CLSimPregnancyEndedEvent`
  (birth) and relationship-bit marriage detection → `post_events` (2.1).
- `visit_situation.py` (new) + `spawn_npc` handler in `tool_executor.py`: picks/creates a
  townie, spawns them via S4CL, starts the custom/native VisitSituation and routes them to
  the target (2.4/3.3).
- `catalyst_tracker.py` (new): detects conversation end across autonomy pulses and posts
  `/v1/god/beat-ended` with an inferred decision (2.9).
- `object_interactions.py` (new): mirror "Reflect" (`/v1/evolve`, A8/3.2), diary read +
  "Snoop" (`/v1/memory/diary`, 3.4), mailbox "Neighborhood Stories"
  (`/v1/world/neighborhood`, 3.9); diary TooltipComponent injection (best-effort).
- `native_hooks.apply_dream_buff`: injects `dream_narrative` as the buff reason + best-effort
  sleep balloon (3.8).
- New tuning XML: `sw_mirror_reflect_interaction`, `sw_diary_read_interaction`,
  `sw_diary_snoop_interaction`, `sw_mailbox_interaction`, `sw_visit_situation` (situation),
  `sw_diary_object` (object).
- `build_package.py`: `object` (0xB61DE6B4) and `situation` (0xFBC3AEEB) tuning types (3.1).
- New UI/STBL keys (en-US + pt-BR): `pie_menu.diary_read/diary_snoop/mailbox` and
  `notify.mirror.*`, `notify.diary.*`, `notify.mailbox.*`.

#### Tests

- `sidecar/tests/test_p2_infra.py` (15 tests): `spawn_npc` contract, `run_cast` reuse/spawn,
  lifecycle legacy memory + life story, `apply_react` beat insertion/`ARC_DONE`,
  `handle_beat_ended`, neighborhood/diary handlers and routes → **523 green tests**.
- Verification: `python -m pytest -q` (523), `py -3.7 -m py_compile` on the Mod (20 files),
  `python mod/build_package.py` (44 resources), `python mod/build.py` (84,686 bytes).

#### Follow-up after the first in-game run (logs 2026-10-02 18:04–18:11)

Log validation (mod `Sensewright_Worker.log` + sidecar `sensewright-sidecar.log` +
`slot_1488584711.working.db`): the mod loaded and executed (autoboot, 123 intents, 104 profiles,
130 `thought` memories), but nothing was visible in-game. Root causes and fixes:

- **Only 7 of 33 purposes had prompt templates**, so everything else fell back to the Sim
  roleplay `_default` prompt. Confirmed `render_prompt('god.plan',...)` returned "You are
  {sim_name}, a Sim…", so `god.plan` returned no `beats` (10 runs, **0 arcs persisted**).
  Added `system` prompts for all remaining purposes + one-shot JSON examples (en-US & pt-BR).
- **`god.plan` resilience:** when the model returns a theme without beats, synthesize a
  default beat so the arc/narrative always starts.
- **`set_mood` failed 100%** (`mood_failed`/`unknown_mood`): TS4 cannot set the mood statistic
  directly. Added **13 `buff_mood_*` emotion buffs** (`mood_type` + `mood_weight`) plus a
  native-mood→buff map; `set_mood` now applies them (and `sleepy` maps to Dazed).
- **Deployed:** rebuilt and reinstalled (44 resources / 42 tunings). Verified the installed
  sidecar serves `/v1/god/beat-ended`, `/v1/world/neighborhood` and `/v1/memory/diary`.

Expected visible results after relaunch: `sim.reaction` emits spoken lines (notifications),
God Director arcs form and narrate, impulse moods become real moodlets, and the mirror/diary/
mailbox interactions are available (they were never installed before).

#### Regression caught on the next launch (18:22) and fixed

The 18:22 launch produced a `lastException` (`categoryid=object_interactions.py:9`):
`ModuleNotFoundError: No module named 'sims4.sim'` from a stray, unused
`from sims4.sim import Sim` in `object_interactions.py`. That import aborts the whole
`sensewright_mod.main` import (the game loads `main.py`), so the mod did **not** load:
the worker never started and the sidecar was never autobooted (the 18:21 sidecar log lines
were a local smoke test, not the game). Removed the import and added
`tests/test_mod_game_imports.py`, a static guard that fails if any Mod file imports a
non-existent `sims4.<submodule>` (the game packages live at the top level: `sims.sim`,
`services`, `objects.*`, `situations.*`). Rebuilt and reinstalled; the installed
`object_interactions.pyc` no longer references `sims4.sim`. 524 tests green.

#### Runtime reliability & concurrency hardening (2026-10-02, branch `v2-remake`)

Executed [`operations.md`](operations.md) against the audit findings
(`lastException.txt`, worker/sidecar logs, `slot_1488584711.*.db`):

- **Mod session state machine (1.1):** `HOUSEHOLDS_AND_SIMS_LOADED` no longer re-fires
  `session-start`/census; it starts a session only for a new save or a same-save reload that
  rolled the clock back, and closes the session on optional `CLIENT_DISCONNECT`/`GAME_LOAD`.
- **Pre-save clock (1.2):** `GAME_PRE_SAVE` captures the tick and `GAME_SAVE` consumes it when
  fresh (< 30 s), removing the ~68-tick post-serialization drift.
- **Strict rewind tolerance (2.1/2.2):** `REWIND_TOLERANCE_TICKS` (default 3000, configurable)
  ignores ordinary drift; only a genuine rollback restores the ring snapshot and seeds
  `last_processed_tick`.
- **Tick idempotency (2.3) + session epochs (2.4):** `accept_tick` rejects duplicates; every
  async callback is wrapped by `guard_callback` and dropped (`stale_epoch_dropped`) when its
  session is obsolete, so a job can never write into a newer session's store.
- **God single-flight (3.1):** an atomic `arc_planning` claim guarantees exactly one active arc.
- **Mod two-lane queue + coalescing slot (3.3):** bounded realtime lane drops stale events only,
  autonomy/player-activity coalesce `sims_delta` by `sim_id`, an event-driven worker replaces the
  10 ms poll, per-endpoint timeouts, and an idle intent pull (4.3, 2 s→10 s backoff).
- **Marriage snapshot (3.4):** the load-time relationship-bit rehydration is absorbed silently.
- **Atomic rate limiter (3.6):** `try_accept_and_record` closes the check-then-act overshoot.
- **LLM pressure (4.1/4.2/4.4):** per-sim impulse cooldown + queue-depth backpressure,
  `sim.reaction` on a dedicated realtime pool, configurable bench/purpose cooldowns with a
  per-purpose breaker exposed in `/v1/status`.
- **Memory (4.5):** `mem.consolidate` now fires on zone-transition, save (before commit) and
  chat silence; the wake `sim.sleep` reflection is no longer gated behind a salient event.
- **Observability (5.1):** `/v1/status` exposes `metrics`, `session_epoch`,
  `last_processed_tick` and `arc_planning`.

Verification: `python -m pytest -q` → **535 green** (new `tests/test_hardening.py`),
`py -3.7 -m py_compile` clean, `build_package.py` (42 tunings) and `build.py` (88,405 bytes)
rebuilt. In-game validation (hardening Phase 6.2) remains.

#### Post-deploy playtest findings (2026-10-03) — see [`operations.md`](operations.md)

The hardening build was installed and played. The runtime fixes held, but the playtest exposed
**new, previously unmapped bugs** that keep the visible features dead:

- **BUG-01** — `sim.social` never triggers: activity-based pair detection never matches, so no
  Sim-to-Sim dialogue and no catalyst conversation (`project-status.md` F04/P05 marked this "Full").
- **BUG-02** — stale duplicate `active` arcs persist (2 arcs at beat 0); hardening 3.1 only
  prevents *new* duplicates.
- **BUG-03** — armed beats have no liveness/timeout, so arcs stall forever.

Details, evidence and proposed fixes are in [`operations.md`](operations.md).

#### Bug-fix + P1/P4 wave (2026-10-03) — second pass

Closed the three playtest bugs (see [`operations.md`](operations.md)) and implemented a broad
slice of the still-missing wiring. **623 sidecar tests green** (was 536); Mod
compiles under 3.7; `.package` (44 resources) and `.ts4script` (91,397 B) rebuilt.

**Bugs (all with regression tests in `tests/test_bugs.py`)**
- BUG-01 `sim.social`: Mod reports `is_conversing` + `social_target_sim_id`; sidecar
  prefers it, keeps marker + proximity fallbacks; asymmetric puppeteer routing wired
  (F04/P18). `state_collector._resolve_interaction_target_sim_id`, `services._find_conversational_pair`,
  `_proximity_pair`, `_puppeteer_context`.
- BUG-02 stale arcs: `SqliteStore.deactivate_stale_arcs`, `god.arcs.load_active_arc`
  self-heal, `handle_session_start` keeps one `active` arc.
- BUG-03 beat liveness: `beat_armed_tick` + `god.beat_timeout_sim_days` (default 1);
  `god_tick` advances/completes a stalled beat.
- NOTE-01: `config.example.toml` documents JSON-purpose routing.

**Sidecar — purposes promoted to Full**
- P06 `sim.social.close`: conversation sessions tracked from census edges; callback
  writes social memories; `social_sessions` returned on the tick.
- P12 `sim.aspiration`: `ambition` added to the profile shape; new
  `POST /v1/sim/aspiration`; census aspiration ingested.
- P13 `sim.background.expand`: family backstory memories on demand.
- P21 `god.background` + `BackgroundScheduler` (`god/background_scheduler.py`,
  priority `PLAYER > HOUSEHOLD > ACTIVE > RELATED`).
- P22 `world.npc.backstory`: recurring-townie detection + background.
- P25 `world.aftermath` (`world/aftermath.py`): high-salience events shift the
  zeitgeist and enqueue durable intents.
- P29 `mem.relationship.review`: census relationships ingested; once-per-day edge review.
- P32 `ops.recap`: recapped at session-start, stored, `GET /v1/recap`.
- P33 `ops.panel.summary`: deterministic 2-line summary in `GET /v1/panel/summary` and `/v1/status`.
- F12 `off` presence tier is now effective (sensory-only/excluded → no seat).
- F13 catalyst leases expire (swept in `god_tick`).

**Web Studio / P4**
- 4.1 persist posted profile; 4.2 `POST /v1/config/provider` + live client reload
  (the SPA's `provider.*` control keys are routed to it); 4.3 `GET /v1/god/arc` /
  `/v1/god/cast` (+ SPA arc/beat/cast panel and steer buttons); 4.5 real
  `compile-addon` via `i18n_compile.py` (byte-compatible DBPF/STBL);
  4.8 `POST /v1/config/panic` + `/v1/config/resume` (autonomy freeze).

**Mod (Python 3.7)**
- 2.2 aspiration collection; 2.3 `installed_packs` via S4CL `CommonPackUtils`;
  2.5 Panic Button (`sw.panic` / `sw.resume` + Quick Menu buttons, clears IntentBus);
  2.7 compatible-mod detection (`detected_mods`, exposed in `/v1/status`);
  2.8 `archetype_map` populated from owned bias buffs.

**Still remaining**
- FC3 cost dashboard (4.7), real spoiler-shield wiring (4.4), Onboarding Wizard (2.6,
  currently the single notification), P2 in-game hooks (Autobiography Book 3.5,
  GetToKnow 3.6, epitaph 3.7) and **Phase 5 in-game validation** (all Mod hooks are
  coded blind and need a playtest).

#### Weak-point / bug remediation wave (2026-10-03, branch `v2-remake`)

Full defect sweep + fixes documented in **[`operations.md`](operations.md)**. 19 defects corrected
(9 sidecar, 10 mod/contract), including:

- **S-B01/S-H02** lease/seat de sim-minutos → ticks (`TICKS_PER_SIM_MINUTE`).
- **S-B03** `context_json` double-encoded (afetava os 33 prompts).
- **S-H01** `autonomy_mode` aceito/aplicado (full/reactive/off).
- **S-H03** `GameBudgeter` cap agora aplicado (`gameplay.game_budget_tokens`).
- **S-H04** cooldown por-modelo limpo no reload + configurável.
- **S-H07** 3 buffs de emoção faltantes (`playful`/`embarrassed`/`scared`).
- **M-H02** `next_sleep` + retry de intents agora funcionam.
- Falsos sucessos honestos: `prefer_target`, `weather.set`, `zone.modifier`,
  `notification.send`, `spawn_npc`; `save_id="unknown"` não crasha mais.

Verificação: `pytest` **689 passed** (16 novos em `test_fixes_wave.py`); `py -3.7`
compile limpo; `.package` 46 recursos; `.ts4script` rebuilt. Itens deferidos e a
camada MCP estão em [`operations.md`](operations.md) e [`mcp.md`](mcp.md).


---

## Gap-Closing Plan

> **Date:** 2026-10-02
> **Branch:** `v2-remake`
> **Gap base:** [`specification.md`](specification.md) · implementation status in this document
> **Goal:** an executable plan to close every remaining development gap recorded in
> the Implementation Status section above (P1 residual, P2, P4, and the FC2/FC5 backlog).

> **Note (2026-10-05):** this section is a **catalog of work items**. Its "Phase 1–5" labels are
> *not* the execution order (e.g. "Phase 1" holds sidecar tasks, not spikes). Execution follows the
> Stages 0–5 in [`operations.md`](operations.md#recommended-execution-order-2026-10-05).

This document is the execution roadmap. Each item lists: what exists today (`file:line`),
the concrete action, the affected files, and verification. At the end of each phase, update
`docs/project-status.md`.

---

### 1. Principles and constraints

- **Two interpreters.** The Mod runs on **Python 3.7.0**: `walrus (:=)`, `match/case`,
  union `X | Y`, `f-string =`, and `from __future__ import annotations` are forbidden. The
  sidecar is Python 3.10+ (uses `from __future__ import annotations`).
- **Thread model.** In the Mod, `GAME_TICK` only reads state and dispatches events; heavy work
  goes to the worker/sidecar. Never block the main thread.
- **Shadow DB.** `working.db`/`committed.db`; spatial intents cleared on `zone_transition`.
- **Engine facade.** Isolate calls to EA's volatile API in dedicated helpers so patches hit a
  single location.
- **Defensive.** `try/except Exception` + `sims4.log.Logger` in hooks; `trace_id` end to end.
- **Per-phase delivery:** code → tests → `py -3.7 -m py_compile` (Mod) →
  `python mod/build.py` / `python mod/build_package.py` → `docs/project-status.md`.
- **Compatible HTTP contract.** New endpoints/intents are additive; the existing contract does
  not break. Intent normalization degrades to `command` safely.
- **Spike-Driven Development (SDD).** Never code blind. Any feature interacting with TS4's native API must be prototyped and validated in-game via a standalone Spike (`sw.spike`) before being wired to the `IntentBus` or Sidecar. See [`spike-strategy.md`](spike-strategy.md).

#### Status legend

- ⬜ Pending · 🟡 In progress · ✅ Done

---

### 2. Wave map and dependencies

```
Phase 1 (Spike-Driven Dev) ─────────┐
   (sw.smoke_test, isolated APIs)   │
   │                                ▼
   ├─ Phase 2 (Facade Integration) ─┤
   │  (Mod: events/infra/hooks)     │
   │                                │
   ├─ Phase 3 (Sidecar Completeness)│
   │  (God Director, World Layer)   │
   │                                │
   └─ Phase 4 (Web Studio/P4) ──────┤
                                    ▼
                      Phase 5 (in-game validation M8)
                                    ▼
                        Close-out (docs/project-status.md + README)
```

- **Phase 1 (Spike-Driven Dev)** is the mandatory first step for all native TS4 interactions. We write isolated spikes (`sw.spike`) to prove the EA API works. See [`spike-strategy.md`](spike-strategy.md).
- **Phase 2 (Facade & Mod Infra)** moves validated spikes into `engine_facade.py` and wires them to the `IntentBus` and event listeners.
- **Phase 3 (Sidecar Completeness)** implements the remaining Python 3.10+ logic (God Director, World Layer, Memory compaction). It depends on the telemetry and contracts from Phase 2.
- **Phase 4** is independent; it can run in parallel with Phase 3.
- **Phase 5** is the final end-to-end acceptance run.

> Approved scope decisions: (1) **Zero blind coding**: all native TS4 hooks must be spiked and validated in-game *before* integration; (2) include FC2 and FC5; (3) the user has TS4 to run spikes and Phase 5.

---

### Phase 1 — Spike-Driven Development & Native Hooks

*Before wiring any Mod logic, we must prove the EA APIs via `sw.smoke_test`.*

#### 1.1 `god.cast` (P16) — townie reuse + casting ✅

- **Exists:** purpose `purposes.py:99-101`, fallback `fallbacks.py:157-158`; no handler/caller.
- **Action:**
  - New `run_cast(state, arc, beat, save_id, tick, lang)` in `god/orchestrator.py` (or `god/cast.py`).
  - Compatible-townie matching using the census (`name/traits/age_stage/career/household_id/is_player`).
  - No candidate → emit an intent `spawn_npc` (contract in task 2.4).
  - `_cast_callback` writes `NpcSheet {sim_id, name, role, objective}` into `arc["cast"]` and the beat; `save_arc`.
  - Trigger from `god_tick`/`_scene_callback` when the armed beat needs a catalyst.
- **Verify:** `test_god.py`/`test_p1_god_world.py` — townie reuse + spawn fallback.

#### 1.2 `god.react` (P19) + `advance_arc` caller ✅

- **Exists:** `arcs.py:36-41` `advance_arc` with no production caller; `purposes.py:108-110`; fallback `fallbacks.py:176-177`.
- **Action:**
  - `run_react(state, arc, agent_decision, save_id, tick, lang)` submitting `god.react`.
  - `_react_callback`: reads `pivot`/`next_beat`, branches `arc["beats"]`, calls `advance_arc(arc)`, `save_arc`, marks `ARC_DONE` when exhausted.
  - Trigger: new `/v1/god/beat-ended` endpoint, fed by the Mod (task 2.9).
- **Verify:** `pivot → next beat → ARC_DONE` test.

#### 1.3 `god.background` (P21) + `BackgroundScheduler` (REQ-GOD-03) ⬜

- **Exists:** `purposes.py:114-116`; `set_sim_background` (`sqlite_store.py:450-457`) with no caller; no scheduler.
- **Action:**
  - New `god/background_scheduler.py`: priority `PLAYER > HOUSEHOLD > ACTIVE > RELATED` via the census (`is_player`, `household_id`, `family_links`).
  - `submit_bg("god.background", dedup_key=...)` with a per-tick cap; `_background_callback` → `set_sim_background`.
  - Integrate into `god_tick`/`handle_autonomy_tick`.

#### 1.4 Complete `god.puppeteer` (P18) ⬜

- **Exists:** `god/puppeteer.py:17-66` (only `speak` + lease); `agent/social.py:88-104` already accepts `puppeteer=`, but `services.py:613` never passes it.
- **Action:**
  - `run_puppeteer`: also emit an `approach` intent (the Mod already implements it: `tool_executor.py:255-278`).
  - At the `sim.social` gate (`services.py`), when a pair has a catalyst lease, build `puppeteer={"objective","catalyst_name","agent_name"}` → **actual asymmetric routing**.
  - Spawn as a prior step via `god.cast` (1.1); persist `scene_subtext` in the beat.

#### 1.5 `world.aftermath` (P25) ⬜

- **Exists:** `purposes.py:128-130`, `_fb_aftermath` (`fallbacks.py:196-201`); flag in `controls.py:22-26` unread; `handle_event` (`services.py:794-849`) does not fire it.
- **Action:** branch `salience >= 2.0` (`constants.AFTERMATH_SALIENCE_THRESHOLD`) → `world.aftermath`; callback applies `zeitgeist_shift` (`world/chronicle.py:25`), enqueues intents via `normalize_intent`, optionally `upsert_relationship`.

#### 1.6 `world.npc.backstory` (P22) ⬜

- **Exists:** `purposes.py:119-121`; census sends `is_player`/`household_id` (`state_collector.py:365-386`) but `handle_census` discards them.
- **Action:** ingest the fields, detect a recurring townie (non-player seen across multiple zones/sessions) → `world.npc.backstory` → `set_sim_background`. Mostly pure-sidecar.

#### 1.7 `sim.social.close` (P06) ⬜

- **Exists:** `purposes.py:67-69`; `state.conversations` never populated; `social_sessions` always `[]` (`services.py:639`); `_spread_rumor` already exists (`services.py:517`).
- **Action:** track `ConversationSession` edges in `handle_autonomy_tick` (`activity` is already reported), `submit_bg("sim.social.close")`, callback writes a social memory + contagion, fills `social_sessions`.

#### 1.8 `mem.legacy` handler (P28, sidecar side) ✅

- **Exists:** `purposes.py:139-141`; `add_memory(type="legacy")` works; prune protects legacy (`sqlite_store.py:329`).
- **Action:** in `handle_event`, branches `death|marriage|birth` → `mem.legacy` → `add_memory("legacy")`; optionally fire `sim.lifestory`. (The Mod trigger is task 2.1.)

#### 1.9 `mem.relationship.review` (P29) ⬜

- **Exists:** `purposes.py:142-144`; `relationships.qualitative_note` exists (`sqlite_store.py:70`) but is never written; `state.relationships` always empty; `deep_window_open` computed and idle (`services.py:1007`).
- **Action:** ingest the census `relationships[]` (currently discarded) → `upsert_relationship`; in the deep window, review active edges → `run_purpose("mem.relationship.review")` → callback writes `qualitative_note`.

#### 1.10 `ops.panel.summary` (P33) ⬜

- **Exists:** `purposes.py:158-160`; `handle_controls_get/post` (`services.py:983-991`) without a trigger.
- **Action:** trigger on `set_control`/panel open; expose the 2-line summary in `/v1/status`; consume in the Quick Menu (Mod).

#### 1.11 `ops.recap` consumption (P32) ⬜

- **Exists:** `services.py:352-376` submits `ops.recap`, but `recap_job_id` is always `None` and the result is discarded.
- **Action:** capture the job id, `_recap_callback` stores `headline/recap_text`, new `GET /v1/recap`; the Mod displays a banner (Phase 2).

#### 1.12 `sim.aspiration` (P12, sidecar side) ⬜

- **Exists:** `purposes.py:85-87`; **`ambition` is missing** from `PROFILE_SHAPE_KEYS` (`agent/profile.py:16-21`).
- **Action:** add `ambition` to the shape/normalize; handler persists it and feeds `sim.cognition`. (Mod collection = 2.2.)

#### 1.13 `sim.background.expand` (P13, sidecar side) ⬜

- **Exists:** `purposes.py:88-90`; `relationships.known_secrets` + `add_known_secret` (`sqlite_store.py:421`) with no caller.
- **Action:** handler writes 3 `backstory` memories; expose/consume `known_secrets` for the `sim_GetToKnow` hook (3.6).

#### 1.14 F13/F12 residuals ⬜

- Lease expiration checked in `god/coordinator.py`; the `off` tier in `agent/presence.py` made effective.

#### Phase 1 verification

- Extend `test_god.py`, `test_p1_god_world.py`, `test_services_endpoints.py`, `test_world_rumors.py` (+~40 tests).
- `python -m pytest -q` green; no schema change.

---

### Phase 2 — Mod: Facade Integration & Infra (Python 3.7)

*Integrating the validated spikes from Phase 1 into the `engine_facade` and `IntentBus`.*

#### 2.1 Lifecycle listeners (unblocks 1.8) ✅

- **Exists:** `post_events` defined (`http_client.py:462-478`) and **never called**; `/v1/events` + `handle_event` idle.
- **Action:** S4CL death/marriage/birth listeners → `post_events(event_category ∈ death|marriage|birth)`. Isolate the API in a facade.

#### 2.2 Aspiration collection (unblocks 1.12) ✅

- **Action:** `state_collector.py` collects the current aspiration in the delta/census; detect change/milestone and report.

#### 2.3 Real `installed_packs` (A10) ⬜

- **Exists:** `_get_installed_packs` is an empty stub (`state_collector.py:124-133`); the sidecar already stores/exposes it (`services.py:402`, `:1042`).
- **Action:** implement via S4CL `CommonPackUtils`; the sidecar guards `set_weather` (Seasons) and dependent arcs + warning.

#### 2.4 `spawn_npc` intent contract ✅

- **Action:** new kind in `schemas.py` + `agent/intents.py` (sidecar) + dispatch/`_WHITELISTED_COMMANDS` in `tool_executor.py` (Mod), via `SituationManager.create_situation()` (prerequisite of 1.1/1.3/3.3).
- **Risk:** contract change; normalize degrades to `command`.

#### 2.5 FC4 — Panic Button (`Ctrl+Shift+S`) ⬜

- **Exists:** `IntentBus.clear_all()` (`intent_bus.py:283`) never called; no Mod hotkey; locale `notify.paused.*` already exists (`en-US.json:75-78`).
- **Action:** S4CL keybind (or Quick Menu button) → `clear_all()` + `POST /v1/config/panic` + notification. Sidecar endpoint = 4.8.

#### 2.6 FC1 — Onboarding Wizard ⬜

- **Exists:** single notification (`main.py:149-206`); `bootstrap_needed` returned and discarded.
- **Action:** `post_lifecycle_session_start` callback reads `bootstrap_needed` → `CommonChooseResponseDialog` with `[⚡ Quick Mode]` / `[🌐 Configure in Browser]` / `[🎮 Play First]` (`post_async` with callback already exists: `http_client.py:296-306`).

#### 2.7 FC5 — Compatibility detection ✅

- **Action:** scan `Mods/` for signatures (MCCC, WickedWhims, Slice of Life) → `detected_mods[]` in the census; the sidecar exposes it in `/v1/status` + warnings (SPA Tab 3).

#### 2.8 A11 — Activity/archetype maps ✅

- **Action:** fill `activity_map`/`archetype_map` (`tuning.py:229,232`, currently empty).

#### 2.9 Catalyst end-of-interaction signal (unblocks 1.2) ✅

- **Action:** report the end of the `ConversationSession` + the agent's decision (`accept/reject/fight`) via `/v1/god/beat-ended`/`post_events`.

#### Phase 2 verification

- `py -3.7 -m py_compile mod/sensewright_mod/*.py`; `test_mod_ui_keys.py` for new keys; sidecar tests for the new event categories.

---

### Phase 3 — Sidecar Completeness: God Director & World Layer

#### 3.1 `build_package.py` — `object` and `situation` types ✅

- **Exists:** `TUNING_TYPES` (`build_package.py:59-66`) only has buff/trait/snippet/interaction/pie_menu_category/sim_data.
- **Action:** add the **object definition** and **situation** resource types (needed for 3.3–3.7).

#### 3.2 Mirror "Reflect" (A8) ✅

- **Exists:** only the `stbl.pie_menu.mirror_reflect` key (`en-US.json:7`/`pt-BR.json:7`).
- **Action:** XML `mod/tuning/interactions/sw_mirror_reflect_interaction.xml` + class `SensewrightMirrorReflectInteraction` in `interactions.py` → fires `evo.reflect` (`/v1/evolve` trigger `mirror`); object target (mirror), not Sim.

#### 3.3 VisitSituation / NPC spawn ✅ (blind; Phase 5 checklist)

- **Action:** consume the `spawn_npc` intent (2.4) via `SituationManager`; catalyst NPC walks the sidewalk/rings the doorbell.

#### 3.4 Diary + "Snoop" ✅ (blind; Phase 5 checklist)

- **Action:** object with a `TooltipComponent` showing the `sim.diary` text; hook into the Snoop interaction; new `stbl.diary.*` keys.

#### 3.5 Autobiography Book ⬜

- **Action:** physical book object with `profile.life_story` chapters; spawn on the bookshelf; new STBL keys.

#### 3.6 `sim_GetToKnow` ⬜

- **Action:** hook into the native "Get to Know" interaction → endpoint increments `known_secrets` and reveals 1 secret/backstory from `relationships`.

#### 3.7 Tombstone Epitaph ⬜

- **Action:** hook into "Engrave Epitaph" writing the poetic `mem.legacy` text (low priority).

#### 3.8 Sleep balloons ✅ (blind; Phase 5 checklist)

- **Exists:** `native_hooks.py:212-233` applies the dream buff but does not inject the text (`:226-228`).
- **Action:** `balloon_requests` during the sleep animation + `{0.String}` injection of the `dream_narrative` into the buff tooltip (re-apply the buff with tokens).

#### 3.9 Mailbox ✅ (blind; Phase 5 checklist)

- **Action:** new `GET /v1/world/neighborhood` (sidecar) returning chronicles (`world/chronicle.py`) + `rumors_known_by` (`world/rumors.py:58`); "Neighborhood Stories" interaction in the Mod.

#### Phase 3 verification

- `py -3.7 -m py_compile`; `build_package.py` emits the new resources; locale parity; **Phase 5 manual checklist**.

---

### Phase 4 — Web Studio & P4 (sidecar + SPA, no TS4)

#### 4.1 Persist profile ⬜

- **Exists:** `handle_profile` (`services.py:853-880`) ignores `payload["profile"]`; the SPA sends it (`app.js:301-315`).
- **Action:** accept the posted `profile` → merge with `normalize_profile` → `upsert_sim_profile`.

#### 4.2 API keys — Layer 1 ⬜

- **Exists:** the SPA posts to `/v1/god/controls` (`app.js:414-422`), but `set_control` (`controls.py:131-159`) does not handle `provider.*`.
- **Action:** new credentials endpoint (e.g., `POST /v1/config/provider`) outside `panel.toml` (REQ-PNL-02/REQ-SCHED-01); update `app.js`.

#### 4.3 Casting/Beats in the SPA ⬜

- **Action:** `GET /v1/god/arc` (beats; `steer_arc` for edit/skip/rewrite) and `GET /v1/god/cast`; wire `btn-recast`, `casting-list`, `beats-list` in `app.js`.

#### 4.4 Zeitgeist/Spoiler/free_only ⬜

- **Action:** `handle_zeitgeist` persists `tags`/`weather_preference` (ignored in `services.py:977`); SPA sends `spoiler_shield` and listens for the `free_only` `change`.

#### 4.5 Real `compile-addon` ⬜

- **Exists:** stub (`routers/i18n.py:26-28`, `services.py:1056-1064`); the compiler is ready in the Mod (`build_package.py`: `extract_stbl_strings`, `fnv1_32`, `build_stbl_body`, `stbl_resource_key`, `build_dbpf`).
- **Action:** port the logic into the sidecar; generate `Sensewright_Locale_<code>.package` into `Mods/`; `FileResponse` download; button in Tab 3.

#### 4.6 FC2 — Sim Export/Import ⬜

- **Action:** `GET /v1/sim/{id}/export` (profile + memories + psyche) and `POST /v1/sim/import`; buttons in Tab 1. Testable without TS4.

#### 4.7 FC3 — Cost dashboard ⬜

- **Action:** record requests/tokens per provider with per-model pricing (Layer 1) and an aggregator; `GET /v1/status/cost` (day/week + projection); widget in Tab 3.

#### 4.8 Panic endpoint (sidecar side) ⬜

- **Action:** `POST /v1/config/panic` (pairs with 2.5): pause the `LLMScheduler` + `state.drain_intents()`.

#### Phase 4 verification

- Extend `test_services_endpoints.py`, `test_god.py`, `test_i18n_engine.py` (FNV-32/`ts4_stbl_byte`) (+~25 tests).

---

### Phase 5 — M8: in-game validation (manual checklist, TS4)

Acceptance criteria (`specification.md` "Acceptance Criteria for M8"):

| Scenario | Steps | Expected | Status |
|---|---|---|---|
| Save & Reload | normal save; inspect `working.db`/`committed.db` | working discarded, committed restored, 0 orphans | ⬜ |
| Save As (new slot) | Save As into a new slot | new committed created, old one intact | ⬜ |
| Alt+F4 (crash) | kill the game without saving | working discarded on the next session, 0 corruption | ⬜ |
| Zone Transition | change lots | spatial intents cleared, memories preserved, 0 duplicates | ⬜ |
| 10-min AFK | idle for 10 min | deep tier exploited, no job pile-up | ⬜ |
| No API Key | remove the key | 100% of the 33 purposes answer with 0-key templates | ⬜ |
| Network Timeout | drop the network | Game Budget refunded, FPS unchanged, transparent fallback | ⬜ |
| macOS | autoboot | sidecar starts with no visible console | ⬜ |
| 6h+ session | play a long session | logs rotated, `.db` < 50MB, RAM stable | ⬜ |
| 12 Sims on lot | party with 12+ | seat eviction < 100ms, no thrashing | ⬜ |
| Hook: mirror (A8) | click the mirror | "Reflect on Life" option appears and fires `evo.reflect` | ⬜ |
| Hook: diary/snoop | interact with the diary | correct Tooltip; "Snoop" reveals the text | ⬜ |
| Hook: tombstone | a Sim with legacy dies | epitaph written on the tombstone | ⬜ |
| Hook: catalyst | `god.puppeteer` active | NPC spawns, rings the doorbell, and approaches | ⬜ |
| Hook: mailbox | open the mailbox | chronicles/rumors listed | ⬜ |
| Hook: sleep balloons | go to sleep | balloons appear; text in the moodlet tooltip | ⬜ |

---

### 3. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| EA tuning IDs/APIs change between patches | High (Phase 3) | Facade isolating engine calls; validate per build in the in-game phases |
| New `spawn_npc`/`beat-ended` contract | Medium | Normalization degrades to `command`; additive endpoints |
| `build_package.py` lacks `object`/`situation` types | Medium | Implement 3.1 before 3.3–3.7; validate the emitted resources |
| Heuristic `installed_packs` / labeled `family_links` | Low | Conservative guard (do not enable a lever when uncertain) |
| `balloon_requests`/tooltip tokens are workarounds | Medium (Phase 3.8) | Leave for last in P2; document in `project-status.md` |
| `handle_profile` currently ignores the posted profile | Low | Isolated fix in 4.1 with a regression test |

---

### 4. Plan completion criteria

1. All phases F1–F4 items ✅ with green tests (`pytest` + `py_compile` 3.7 + builds).
2. Phase 5 executed in-game, with the table filled in.
3. `docs/project-status.md` updated: F01–F22, P01–P33 (all **Full** or justifiably deferred), A1–A11, FC1–FC5.
4. `README.md` aligned (the "Not yet done" section revised).

---

### 5. Progress

- 🟡 Phase 1 — P1 residual (sidecar) — **1.1–1.10, 1.12, 1.13, 1.14 done** (1.11 `ops.recap`
  now consumed; only the physical Autobiography Book and in-game hooks remain)
- 🟡 Phase 2 — Mod: events & infra — **2.1–2.5, 2.7, 2.8 done** (2.6 Onboarding Wizard / FC1 pending — scheduled as Stage 4)
- 🟡 Phase 3 — P2 native hooks — **3.1–3.4, 3.8, 3.9 coded blind** (3.5–3.7 + Phase 5 in-game validation pending)
- [x] Phase 4 — P3: LLM, Config & Observability — done (per-model cooldown, tier concurrency, asymmetric refund, trace_id, VACUUM)
- 🟡 Phase 4b — Web Studio/P4 — **4.1, 4.2, 4.3, 4.5, 4.8 done** (4.4 spoiler, 4.6 FC2, 4.7 FC3 pending)
- [ ] Phase 5 — M8 in-game validation
- [ ] Close-out — docs/project-status.md + README

See the 2026-10-03 changelog in [`project-status.md`](project-status.md) for the bug fixes (BUG-01/02/03)
and the full list of purposes promoted to Full.


---

## Changelog

> **Branch:** `v2-remake`

Reverse-chronological record of what **changed** per session, plus the **open items**
that remain. Complements [`project-status.md`](project-status.md) (spec↔code gap) and [`operations.md`](operations.md)
(playtest findings) — this file records the actual edits, not the plan.

---

### 2026-10-03 — Playtest #4 follow-up (post-install regression fixes)

After the first deploy, a real session (`save 1488584711`, 15:23–15:30) showed three
fixes were incomplete. Closed them:

#### A. `lastUIException` flood returned (BUG-07 regression)

- The earlier `mood_type` fix only touched `buff_mood_*.xml`; the **bias**, **dream**
  and **missing_player** buffs still used `<T n="mood_type">0</T>` (= `Mood.INVALID`,
  no client `MoodKey`), so `BuffInfo/MoodKey()` null still flooded `lastUIException`.
- All remaining buffs now use `<E n="mood_type">HAPPY|INSPIRED|DAZED|STRESSED|SAD</E>`;
  `tools/gen_bias_buffs.py` template fixed so regeneration can't reintroduce it;
  `test_tuning_refs.py` now asserts no buff uses a numeric `mood_type`. | `mod/tuning/buffs/*.xml`, `tools/gen_bias_buffs.py`, `test_tuning_refs.py` |

#### B. Confidant still duplicated (BUG-12)

- The hidden household's **name** doesn't reliably persist, so the household-name
  search re-created the confidant each session (21 rows). `get_or_create_player_confidant`
  now searches the whole sim manager for the existing confidant by last name
  ("Sensewright") before spawning a new `SimInfo`. | `native_hooks.py` |

#### C. `sim.profile` still never ran (BUG-11)

- Census-time scheduling gated on `is_player`, which was unreliable at session-start.
  Added a second, seat-based trigger in `handle_autonomy_tick` (the same assignment
  that already drives impulses, so it provably identifies household sims) and a
  diagnostic census log line. | `services.py`, `test_playtest4.py` |

#### Verification

- `cd sidecar && python -m pytest -q` → **673 passed** (2 new).
- `py -3.7 -m compileall -q mod/sensewright_mod` → clean.
- Build + deploy via `scripts/install-mod.ps1`.

---

### 2026-10-03 — Playtest #4 fixes: personas, relationships, catalyst gating, census hygiene

Closed **BUG-11/12/13/14/15/16/17** and addressed **NOTE-02** (see [`operations.md`](operations.md)).

#### A. `sim.profile` actually runs (BUG-11)

| # | Change | Files |
|---|--------|-------|
| 1 | `handle_census` schedules a bounded background `sim.profile` for household sims whose stored profile is still a template (deduped + RAM-guarded per session). | `services.py`, `state.py` |
| 2 | `handle_profile` regenerates when the profile is a template (empty persona), not just when it is `None`; generated personas are tagged `source="llm"`. | `services.py`, `agent/profile.py` |
| 3 | `handle_chat` kicks off a one-shot fallback generation when the persona is still empty. | `services.py` |

#### B. Player confidant dedupe (BUG-12)

- `get_or_create_player_confidant` searches the hidden household for an existing member
  (name marker, then first member) before spawning a new `SimInfo`. | `native_hooks.py` |

#### C. Relationship graph collection (BUG-13)

- `collect_full_census` collects edges via S4CL `CommonRelationshipUtils.get_relationships_gen`
  + `get_friendship_level`/`get_romance_level`; the engine's `Relationship` exposes
  `sim_id_a`/`sim_id_b`/`get_other_sim_id`, not `target_sim_id`/`friendship`/`romance`. | `state_collector.py` |

#### D. Catalyst gate on `beat-ended` (BUG-14)

- The Mod reports the conversation peer (`target_sim_id`) with `beat-ended`.
- The sidecar gates `run_react` on whether either participant is the catalyst (leased
  puppeteer NPC or a resolved cast member); ambient chatter no longer advances the arc. | `catalyst_tracker.py`, `god/react.py`, `god/orchestrator.py`, `services.py` |

#### E. Census hygiene (BUG-15/16/17)

- `age_stage` reported via `Age.name` (stripping an `Age.` prefix); sidecar normalizes legacy
  stored values in `normalize_age_stage`. | `state_collector.py`, `agent/profile.py`, `services.py` |
- `http_client._make_request` no longer sends a JSON body on GET (moves the payload into the
  query string), fixing the mailbox `/world/neighborhood` WinError 10053. | `http_client.py` |
- `gender` (`M`/`F`/`N`) collected via S4CL `CommonGenderUtils` and threaded into `sim.chat`,
  `sim.social` and `sim.profile` contexts. | `state_collector.py`, `agent/chat.py`, `agent/social.py`, `services.py` |

#### F. LLM routing (NOTE-02, ops)

- `config.example.toml` documents JSON-only routing + the groq 403 user-agent issue; the
  installed `config.toml` routes JSON-only purposes to a JSON-capable free model and keeps
  `deepseek` disabled. | `config.example.toml`, `config.toml` |

#### Verification

- `cd sidecar && python -m pytest -q` → **671 passed** (16 new in `test_playtest4.py`, plus
  the updated catalyst-gate assertions in `test_p2_infra.py`).
- `py -3.7 -m compileall -q mod/sensewright_mod` → clean.
- `python mod/build_package.py` → `Sensewright.package` (16,864 B, 43 resources).
- `python mod/build.py` → `Sensewright.ts4script` (100,257 B, 3.7 bytecode).
- Deployed with `scripts/install-mod.ps1`.

---

### 2026-10-03 — Chat grounding + context-aware dialogue + native relationship feedback

Requirement review: "any interaction must consider context", plus the native
relationship feedback of a sim↔sim interaction, must be grounded into the LLM prompt.
Closed **BUG-08/09/10** (see [`operations.md`](operations.md)).

#### A. Chat grounding (player↔sim `sim.chat`)

| # | Change | Files |
|---|--------|-------|
| 1 | The Mod now sends `player_name` (hidden confidant) + `friendship` (sim↔confidant) on `/chat` and `/hey`, so the prompt no longer renders "Trust with : 1" / "Message from : …". | `mod/sensewright_mod/http_client.py`, `chat_ui.py` |
| 2 | `handle_chat` prefers the wire friendship, falls back to census, and passes the short-term chat buffer (`state.chat_turns`) as `history`. | `sidecar/.../services.py` |
| 3 | `build_chat_context` accepts `history`/`family`/`location`/`action`; `sim.chat` prompt now includes history + memories for all channels. | `agent/chat.py`, `llm/context.py`, `locales/content/*.json` |

#### B. Family-tree grounding (BUG-09)

- `_collect_full_sim_census` read nonexistent `Relationship.target_sim_id`/`relationship_bits`;
  replaced with S4CL `CommonRelationshipUtils` + `CommonRelationshipBitId` (stable, instanced=False).
- `services._resolve_family` + `agent.chat.family_relation_label` inject a localized
  `family_hint` ("Sua família: … Nunca invente parentes…"). `background_scheduler._family_link_ids`
  now accepts both dict and legacy int shapes (was `int(dict)` crash). | `state_collector.py`, `services.py`, `agent/chat.py`, `god/background_scheduler.py` |

#### C. Scene context (BUG-10) — location / relationship / selected action

- Mod collects `is_outside`/`is_at_home`, localized `interaction_text`
  (`LocalizationHelperTuning.get_raw_text(display_name)`) and `queued_interaction_texts`,
  plus zone `venue_type`/`is_residential` (sent on the autonomy tick). | `state_collector.py`, `http_client.py`, `main.py` |
- Sidecar adds `location_context`/`relationship_context`/`action_context` +
  `relationship_tier`; `sim.social`, `sim.chat` and `god.puppeteer.run_puppeteer` now carry
  the scene context. `llm/context.py` renders `location_hint`/`relationship_hint`/`action_hint`
  and the previously-unused `asymmetric_directive`. | `agent/social.py`, `services.py`, `god/puppeteer.py`, `llm/context.py`, `state.py`, `locales/content/*.json` |

#### D. Native relationship feedback (friendship/rivalry delta)

- Mod reports fresh `social_friendship`/`social_romance` when a social target is resolved.
- `relationship_context` derives `friendship_delta`/`romance_delta` vs the census baseline;
  `relationship_tier` maps negative friendship to `rival`; the prompt renders
  e.g. `Relação: amigos, amizade 45 (+5)` / `Relação: rivais, amizade -22 (-8)`. | `state_collector.py`, `agent/social.py`, `llm/context.py`, `locales/content/*.json` |

#### Verification

- `cd sidecar && python -m pytest -q` → **656 passed** (19 new across the three waves).
- `py -3.7 -m py_compile` over changed Mod files → clean.
- `python -m py_compile` over changed Sidecar files → clean.

---

### 2026-10-03 — Review hardening + Web Studio / Director / background fixes

#### A. Code-review hardening (review of `a314bbf`)

| # | Change | Files |
|---|--------|-------|
| 1 | Panic state is now **readable**: added `GET /v1/config/panic` (`handle_config_panic_state`). The Web Studio previously polled a POST-only route (405 → always "not paused"). | `routers/health.py`, `services.py` |
| 2 | `priority_class` docstring corrected — the active sim is classified *before* the household check; ranking still follows `PRIORITY_ORDER` (`HOUSEHOLD > ACTIVE`). Behavior unchanged. | `god/background_scheduler.py` |
| 3 | Mods-folder detection is no longer a single `sims4.paths` guess: `_resolve_mods_folder()` walks up from `__file__`, then tries S4CL path utils, then game `paths` — all guarded. | `mod/sensewright_mod/state_collector.py` |
| 4 | Idle intent pull moved off the outbound worker onto a dedicated thread (`_intent_pull_loop`), so a slow `GET /autonomy/intents` can no longer delay lifecycle/chat/event dispatch. | `mod/sensewright_mod/http_client.py` |
| 5 | TPM pre-check is now atomic: `try_accept_and_record` reserves the estimate; `settle_reservation`/`release_reservation` reconcile it (fixes a concurrent overshoot). | `llm/limits.py`, `llm/chain.py` |
| 6 | `/v1/status` exposes a flat `limits` map again (it was shadowed by the nested `chain` dict); Web Studio "Rate Limits" restored. | `services.py`, `webui/app.js` |
| 7 | `mem.relationship.review` cadence advances only inside its callback, so a stale-epoch-dropped job retries instead of skipping a whole sim-day. | `services.py` |
| 8 | `LLMScheduler.shutdown()` releases the realtime pool on interpreter exit. | `llm/scheduler.py` |

#### B. Playtest fixes (found while testing the Web Studio in-game)

- **Director Quick Menu sent wrong control keys/values.** `director_preset` → `preset`;
  `director_mode` values now uppercased (`AUTONOMOUS`/`CO_DIRECTOR`/`SANDBOX`). In-game
  theme/mode changes now persist and reach the Web Studio (it re-reads `/v1/god/controls`
  every 15 s). (`mod/sensewright_mod/panel_ui.py`)
- **Web Studio Sims tab rendered "Sim <id>" with empty profiles.** Seats only carried
  `sim_id/role/tier/lease`. `handle_seats_get` now merges census identity, stored profile,
  background and relationship edges; added a "Background" field + locale keys.
  (`services.py`, `webui/index.html`, `webui/app.js`, `webui/locales/*`)
- **Reasoning-model output rejected as "unusable".** `_extract_json` now strips
  `<thinking>/<reasoning>/<thought>` tags and falls back to the last balanced JSON object
  (deepseek-v4-pro emits prose/thinking around the payload). (`llm/scheduler.py`)

#### Verification

- `cd sidecar && python -m pytest -q` → **635 passed** (12 new regression tests).
- `py -3.7 -m py_compile` over `mod/sensewright_mod/*.py` → clean (20 files).
- `python mod/build_package.py` → `Sensewright.package` (17,037 B, 44 resources).
- `python mod/build.py` → `Sensewright.ts4script` (92,361 B, Python 3.7 bytecode).
- Deployed via `scripts/install-mod.ps1` (OneDrive Mods folder).

---

### Open items (still to do)

- [x] **`autonomy_mode` (Quick Menu "Autonomia")** — resolved in the weak-point wave
      (`full|reactive|off` accepted, exposed and applied).
- [ ] **`deepseek-v4-pro` (reasoning model) still returns non-JSON for some purposes.** The JSON
      extractor is more tolerant now, but the durable fix is config: route JSON-only purposes to
      a JSON-capable model (OpenRouter `nemotron` free models work) or set `free_only = true` to
      block the paid deepseek provider. See `docs/operations.md` NOTE-01.
- [~] **Load-time event ordering.** Mitigated in Stage 1 (R7): lifecycle events arriving during
      the load window are buffered (max 8) and flushed on `mark_lifecycle_ready()`. Still to
      confirm in-game (Playtest #5) that no `stale_epoch_dropped epoch=0` / lane saturation remains.
- [ ] **Web Studio UX gaps.** The Sims tab has no auto-refresh (manual "Refresh Sims" only), and
      the God tab does not render `director_mode` (only the preset dropdown).
- [ ] **In-game Phase 6.2 validation still pending** — see [`operations.md`](operations.md).
- [ ] **Playtest #4 follow-up playtest.** BUG-11..17 + NOTE-02 are now fixed in code/config
      (see [`operations.md`](operations.md) → "Playtest #4 — diagnosis — FIXED"), but the in-game
      confirmation is still pending: `sim.profile` should run (`purpose=sim.profile` > 0),
      exactly one confidant should persist, `relationships` should fill, and only catalyst
      conversations should advance an arc. Re-verify with `scripts/install-mod.ps1` + play.

---

### Earlier waves

For P0–P4, the hardening pass, and BUG-01/02/03, see `git log` and [`operations.md`](operations.md).
