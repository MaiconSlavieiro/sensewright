# Sensewright v2 — Implementation Status (M0 → M8)

> **Date:** 2026-10-02
> **Branch:** `v2-remake`
> **Reference base:** [`requirements.md`](requirements.md)
> **Purpose:** to precisely record what **is already implemented and verified** and what
> **is genuinely still missing** from the full plan (22 features, 33 purposes, adjustments
> A1–A11, and complementary features FC1–FC5).

This document is the source of truth for the gap between the specification and the code.
References use the `file:line` format.

---

## 1. Executive summary

The project has a **solid, tested foundation**: both processes (Mod Python 3.7 and Sidecar
FastAPI) talk to each other, the transactional save cycle works, the manifest-driven i18n
engine is complete, the LLM layer (triple limits, circuit breaker, single-queue scheduler,
tiered ContextAssembler) exists, and the build produces valid `.ts4script` (bytecode 3.7) and
`.package` (DBPF + STBL).

What is **genuinely missing** is not foundation, it is **wiring and triggers**:

- **18 of the 33 purposes** only have a deterministic fallback — they have no trigger or
  production handler (e.g., `sim.dream`, `sim.cognition`, `god.cast`, `world.gossip`,
  `mem.compact`, `mem.legacy`, `ops.panel.summary`).
- **Three partial purposes** (`sim.dream`, `sim.cognition`, `evo.reflect`) have the engine and
  prompt ready, but **nothing triggers them** and the result is not applied back to the profile.
- **God Director**: arcs/beats are planned but never consumed; `god.cast`, `god.scene`, and
  `god.react` do not exist; `god.puppeteer` does not spawn/approach an NPC and does not inject
  the asymmetric objective into `sim.social`.
- **World Layer**: the rumor model is ready and tested, but **no production code creates or
  spreads rumors**; chronicle, mailbox, and aftermath are missing.
- **Native hooks (M5/M6)**: missing Diary/"Snoop", Autobiography Book, `VisitSituation` (NPC
  ringing the doorbell), Tombstone Epitaph, sleep balloons, and the "Reflect" interaction on
  the mirror.
- **Speech Policy (F11)**: `max_lines_per_minute` and `min_interval_between_lines` are defined
  but **not enforced**; the 4-channel visual routing is incomplete.
- **Settings/Concurrency (F15/F16)**: the per-model cooldown (120 s) is dead code; per-tier
  concurrency is not enforced; the "asymmetric refund" is logically inert.

Everything that exists today is covered by **523 tests** (sidecar) and compiles under both
correct interpreters. The 2026-10-02 P2/P3 wave (lifecycle events, `spawn_npc`,
`god.react`/`beat-ended`, mirror/diary/mailbox hooks, sleep balloons, object/situation build
types) is coded blind and awaits the Phase 5 in-game checklist.

---

## 2. Validation performed in this review

| Check | Command | Result |
|---|---|---|
| Sidecar test suite | `python -m pytest -q` in `sidecar/` | **523 passed**, 1 warning |
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

## 3. Milestones M0 → M8

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

## 4. Features F01 → F22

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

## 5. Catalog of the 33 purposes

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
| P02 | `sim.profile` | ✅ Full | `services.py:426-453` — generation-only by design; the endpoint generates a profile, it does not accept one from the client (Web Studio profile editing is plan.md 4.1). |
| P03 | `sim.impulse` | ✅ Full | `services.py:245-260` (inert survival guard) |
| P04 | `sim.reaction` | ✅ Full | `services.py:386-422` |
| P05 | `sim.social` | ✅ Full | `services.py:262-276` (asymmetric not routed) |
| P06 | `sim.social.close` | ⚪ Fallback-only | No handler; `social_sessions` always `[]` (`services.py:296`) |
| P07 | `sim.dream` | ✅ Full | Sleep trigger (`services._process_sleep_transitions`) + engine/prompt/fallback + `dream_urge` in the profile |
| P08 | `sim.cognition` | ✅ Full | Chained post-dream; `apply_cognition` persists `daily_plan`/biases (`services._cognition_callback`) |
| P09 | `sim.sleep` | ✅ Full | Wake trigger (if salient event); memory + psyche reinforcement |
| P10 | `sim.diary` | 🟡 Partial | End-of-day trigger + `diary` memory; missing in-game Tooltip/Snoop (`P2`) |
| P11 | `sim.lifestory` | ⚪ Fallback-only | Life Story limits applied (`enforce_life_story`), but no 7-day trigger |
| P12 | `sim.aspiration` | ⚪ Fallback-only | No handler/trigger |
| P13 | `sim.background.expand` | ⚪ Fallback-only | No handler; `sim_GetToKnow` missing |
| P14 | `god.zeitgeist` | ✅ Full | `god/zeitgeist.py:20`, `services.py:517` |
| P15 | `god.plan` | ✅ Full | `_plan_callback` creates and persists the arc (`create_arc` + `save_arc`) |
| P16 | `god.cast` | ⚪ Fallback-only | No casting/townie reuse/spawn |
| P17 | `god.scene` | ✅ Full | Beat armed → `god.scene` writes `scene_draft`/`scene_subtext` to the beat |
| P18 | `god.puppeteer` | 🟡 Partial | Lease + opening line (`god/puppeteer.py`); no spawn/approach/asymmetric objective/continuation |
| P19 | `god.react` | ⚪ Fallback-only | `advance_arc` without caller (`god/arcs.py:36`) |
| P20 | `god.narration` | ✅ Full | `god/orchestrator.py:17-80` |
| P21 | `god.background` | ⚪ Fallback-only | `set_sim_background` without caller |
| P22 | `world.npc.backstory` | ⚪ Fallback-only | No trigger |
| P23 | `world.household.chronicle` | 🟡 Partial | End-of-day trigger + persistence; missing in-game Mailbox (`P2`) |
| P24 | `world.gossip` | ✅ Full | Creation on salient public event + contagion at the end of `sim.social` + SMS (`_create_rumor_from_event`/`_spread_rumor`) |
| P25 | `world.aftermath` | ⚪ Fallback-only | Constant/flag unused |
| P26 | `mem.consolidate` | 🟡 Partial | Endpoint works (`services.py:474`); **no automatic trigger** (300 s/zone) |
| P27 | `mem.compact` | 🟡 Partial | Automatic trigger (≥ 20 consolidated) + archive 15 + VACUUM (`services._maybe_compact`); missing panel exposure |
| P28 | `mem.legacy` | ⚪ Fallback-only | No death/marriage/birth trigger |
| P29 | `mem.relationship.review` | ⚪ Fallback-only | `qualitative_note` never written |
| P30 | `evo.reflect` | ✅ Full | `handle_evolve` + `_reflect_callback` apply and persist `current_demeanor` |
| P31 | `evo.trait` | 🟡 Partial | Helpers ready; no `run_purpose`/emission |
| P32 | `ops.recap` | 🟡 Partial | Submitted at bootstrap (`services.py:61`); `recap_job_id` always `None`; result discarded |
| P33 | `ops.panel.summary` | ⚪ Fallback-only | No caller |

**Total: 14 Full · 7 Partial · 12 Fallback-only.**

---

## 6. Adjustments A1–A11 and Complementary Features

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

## 7. Prioritized gaps (what genuinely remains to implement)

> **Detailed execution plan:** [`plan.md`](plan.md) (phases P1 residual → P2/P4 → M8,
> with dependencies, risks, and the in-game checklist).

### P0 — Unblock the narrative core (highest impact, lowest effort) — ✅ DONE

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

### P1 — Complete God Director and World Layer (partial)

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

### P2 — Native hooks (M5/M6) — pending (requires in-game validation)

11. `VisitSituation` (catalyst NPC via the sidewalk/doorbell).
12. Diary with *TooltipComponent* + **"Snoop"** interaction; Autobiography Book.
13. `sim_GetToKnow` revealing `secrets[]`/`background`.
14. Tombstone Epitaph; sleep balloons; custom "Reflect" interaction on the Mirror (A8).

### P3 — LLM, Config & Observability — ✅ DONE

15. ✅ Per-model 120 s cooldown in `chain.py` (`_record_failure` per `(provider, model)`).
16. ✅ Per-tier concurrency enforcement in `LLMScheduler` (non-blocking semaphore; excess
    degrades to the deterministic fallback).
17. ✅ Asymmetric refund fixed: debit on send; refund only the Game Budget on failure and
    settle with actual usage on success.
18. ✅ `installed_packs` in the Census → `AppState.installed_packs` + exposed in `/v1/status`
    (basis for EP guards).
19. ✅ `trace_id` propagated to `bg`/`deep` jobs (`set_trace_id` in the worker).
20. ✅ VACUUM after `mem.compact` (A9), called every 20 consolidated memories.

### P4 — UI, Release & Backlog — pending

21. Web Studio: persist profile/keys/casting/beats (the backend ignores them today).
22. Real `/v1/i18n/compile-addon` (generate `Sensewright_Locale_<code>.package`).
23. Panic Button (FC4), Onboarding Wizard (FC1), cost dashboard (FC3).
24. **M8 in-game**: lot transition, *Save As*, *Alt+F4* rollback, invisible autoboot.
25. Sim Export/Import (FC2) and compatibility layer (FC5).

---

## 8. Repository hygiene notes

- `sidecar/python.txt` is a **local** configuration file (points to the user's 3.10+
  interpreter). It is listed in `.gitignore` so machine-absolute paths are not versioned;
  if present in the working tree it is ignored by Git. Create it manually after cloning.
- `research/s4cl/` and `research/lot51_core/` are reference clones and remain ignored (not
  redistributed).

---

## 9. Implementation changelog (2026-10-02)

Waves P0, P3, and part of P1 implemented and covered by tests. No schema change; the HTTP
wire remains compatible.

### New modules (sidecar)

- `agent/sleep.py` — `sleep_start`/`wake` edge detection (P07-P09).
- `agent/speech.py` — speech policy (lines/min + minimum interval) (F11).
- `agent/profile.enforce_life_story` — Life Story limit (REQ-PSY-03).

### Main wiring (`services.py`)

- `_process_sleep_transitions` / `_on_sleep_start` / `_on_wake`: fires
  `sim.dream` → `sim.cognition` (`apply_cognition`) and, on wake, `sim.sleep` +
  `evo.reflect` (`apply_reflection`); applies psyche decay.
- `_maybe_end_of_day`: family chronicle + active Sim diary (P23/P10).
- `_create_rumor_from_event` / `_spread_rumor`: gossip and contagion (P24).
- `_impulse_callback` now respects `physical_actions_allowed` (REQ-IMP-03);
  the `sim.social` gate respects the speech policy and the CHILD hard-block.
- `_maybe_compact` + `SqliteStore.consolidated_memory_ids`: compaction and VACUUM (P27/A9).
- `handle_census` stores `installed_packs`; `/v1/status` exposes them (A10).

### God Director (`god/orchestrator.py`)

- `_plan_callback` creates/persists the arc (`god.plan`, P15).
- `_scene_callback` writes `scene_draft`/`scene_subtext` to the armed beat (`god.scene`, P17).

### LLM (`llm/`)

- `chain.py`: per-model cooldown (120 s) effectively enforced.
- `scheduler.py`: per-tier concurrency (non-blocking semaphore), correct asymmetric refund,
  and `trace_id` on `bg`/`deep` jobs.
- `sqlite_store.py`: `consolidated_memory_ids`; `vacuum()` is now called.

### Mod (`mod/sensewright_mod/tool_executor.py`)

- `world.gossip` now displays the rumor as a diegetic notification (SMS/gossip).

### Tests

- `sidecar/tests/test_p0_lifecycle.py` (19 tests), `test_p3_resilience.py` (8), and
  `test_p1_god_world.py` (7) → **508 green tests**.
- Verification: `python -m pytest -q` (508), `py -3.7 -m py_compile` on the Mod,
  `python mod/build.py` (69,683 bytes), and `python mod/build_package.py` (25 resources).

### Still pending

P1 residual (complete `god.puppeteer`, `BackgroundScheduler`, `world.aftermath`,
`ops.panel.summary`, `mem.relationship.review`, `sim.social.close`), the remaining P2 hooks
(`sim_GetToKnow`, Autobiography Book, Tombstone Epitaph) and P4 (Web Studio, compile-addon,
M8 in-game, FC2/FC5).

---

## 10. Implementation changelog — P2/P3 wave (2026-10-02)

Wired the Mod event sources / God Director contracts and the tangible UI hooks. All Mod
hooks are coded **blind** and must be validated in-game (Phase 5); the sidecar side is
covered by tests. No schema change; the HTTP wire remains additive and compatible.

### Sidecar

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

### Mod (`mod/sensewright_mod/`, Python 3.7)

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

### Tests

- `sidecar/tests/test_p2_infra.py` (15 tests): `spawn_npc` contract, `run_cast` reuse/spawn,
  lifecycle legacy memory + life story, `apply_react` beat insertion/`ARC_DONE`,
  `handle_beat_ended`, neighborhood/diary handlers and routes → **523 green tests**.
- Verification: `python -m pytest -q` (523), `py -3.7 -m py_compile` on the Mod (20 files),
  `python mod/build_package.py` (44 resources), `python mod/build.py` (84,686 bytes).

### Follow-up after the first in-game run (logs 2026-10-02 18:04–18:11)

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

### Regression caught on the next launch (18:22) and fixed

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
