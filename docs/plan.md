# Sensewright v2 — Plan to Close All Remaining Gaps

> **Date:** 2026-10-02
> **Branch:** `v2-remake`
> **Gap base:** [`status.md`](status.md) · [`requirements.md`](requirements.md)
> **Goal:** an executable plan to close every remaining development gap recorded in
> `status.md` (P1 residual, P2, P4, and the FC2/FC5 backlog).

This document is the execution roadmap. Each item lists: what exists today (`file:line`),
the concrete action, the affected files, and verification. At the end of each phase, update
`docs/status.md`.

---

## 1. Principles and constraints

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
  `python mod/build.py` / `python mod/build_package.py` → `docs/status.md`.
- **Compatible HTTP contract.** New endpoints/intents are additive; the existing contract does
  not break. Intent normalization degrades to `command` safely.

### Status legend

- ⬜ Pending · 🟡 In progress · ✅ Done

---

## 2. Wave map and dependencies

```
Phase 1 (pure sidecar) ─────────────┐
   │                                │
   ├─ Phase 2 (Mod: events/infra) ──┤
   │        │                       │
   │        ├─ Phase 3 (P2 hooks) ──┤
   │                                │
   └─ Phase 4 (Web Studio/P4) ──────┤
                                    ▼
                      Phase 5 (in-game validation M8)
                                    ▼
                        Close-out (docs/status.md + README)
```

- **Phase 1** depends on nothing and is most of the effort (fully automatable).
- **Phase 2** defines contracts that Phase 1 (1.1/1.2) and Phase 3 (3.3) consume.
- **Phase 4** is independent; it can run in parallel with Phase 2.
- **Phase 3** depends on the Phase 2 contracts (`spawn_npc`, `beat-ended`).
- **Phase 5** requires running inside The Sims 4.

> Approved scope decisions: (1) code all P2 hooks blind + in-game checklist; (2) include FC2
> and FC5; (3) the user has TS4 to run Phase 5.

---

## Phase 1 — P1 residual: God Director & World Layer (sidecar, no TS4)

### 1.1 `god.cast` (P16) — townie reuse + casting ✅

- **Exists:** purpose `purposes.py:99-101`, fallback `fallbacks.py:157-158`; no handler/caller.
- **Action:**
  - New `run_cast(state, arc, beat, save_id, tick, lang)` in `god/orchestrator.py` (or `god/cast.py`).
  - Compatible-townie matching using the census (`name/traits/age_stage/career/household_id/is_player`).
  - No candidate → emit an intent `spawn_npc` (contract in task 2.4).
  - `_cast_callback` writes `NpcSheet {sim_id, name, role, objective}` into `arc["cast"]` and the beat; `save_arc`.
  - Trigger from `god_tick`/`_scene_callback` when the armed beat needs a catalyst.
- **Verify:** `test_god.py`/`test_p1_god_world.py` — townie reuse + spawn fallback.

### 1.2 `god.react` (P19) + `advance_arc` caller ✅

- **Exists:** `arcs.py:36-41` `advance_arc` with no production caller; `purposes.py:108-110`; fallback `fallbacks.py:176-177`.
- **Action:**
  - `run_react(state, arc, agent_decision, save_id, tick, lang)` submitting `god.react`.
  - `_react_callback`: reads `pivot`/`next_beat`, branches `arc["beats"]`, calls `advance_arc(arc)`, `save_arc`, marks `ARC_DONE` when exhausted.
  - Trigger: new `/v1/god/beat-ended` endpoint, fed by the Mod (task 2.9).
- **Verify:** `pivot → next beat → ARC_DONE` test.

### 1.3 `god.background` (P21) + `BackgroundScheduler` (REQ-GOD-03) ⬜

- **Exists:** `purposes.py:114-116`; `set_sim_background` (`sqlite_store.py:450-457`) with no caller; no scheduler.
- **Action:**
  - New `god/background_scheduler.py`: priority `PLAYER > HOUSEHOLD > ACTIVE > RELATED` via the census (`is_player`, `household_id`, `family_links`).
  - `submit_bg("god.background", dedup_key=...)` with a per-tick cap; `_background_callback` → `set_sim_background`.
  - Integrate into `god_tick`/`handle_autonomy_tick`.

### 1.4 Complete `god.puppeteer` (P18) ⬜

- **Exists:** `god/puppeteer.py:17-66` (only `speak` + lease); `agent/social.py:88-104` already accepts `puppeteer=`, but `services.py:613` never passes it.
- **Action:**
  - `run_puppeteer`: also emit an `approach` intent (the Mod already implements it: `tool_executor.py:255-278`).
  - At the `sim.social` gate (`services.py`), when a pair has a catalyst lease, build `puppeteer={"objective","catalyst_name","agent_name"}` → **actual asymmetric routing**.
  - Spawn as a prior step via `god.cast` (1.1); persist `scene_subtext` in the beat.

### 1.5 `world.aftermath` (P25) ⬜

- **Exists:** `purposes.py:128-130`, `_fb_aftermath` (`fallbacks.py:196-201`); flag in `controls.py:22-26` unread; `handle_event` (`services.py:794-849`) does not fire it.
- **Action:** branch `salience >= 2.0` (`constants.AFTERMATH_SALIENCE_THRESHOLD`) → `world.aftermath`; callback applies `zeitgeist_shift` (`world/chronicle.py:25`), enqueues intents via `normalize_intent`, optionally `upsert_relationship`.

### 1.6 `world.npc.backstory` (P22) ⬜

- **Exists:** `purposes.py:119-121`; census sends `is_player`/`household_id` (`state_collector.py:365-386`) but `handle_census` discards them.
- **Action:** ingest the fields, detect a recurring townie (non-player seen across multiple zones/sessions) → `world.npc.backstory` → `set_sim_background`. Mostly pure-sidecar.

### 1.7 `sim.social.close` (P06) ⬜

- **Exists:** `purposes.py:67-69`; `state.conversations` never populated; `social_sessions` always `[]` (`services.py:639`); `_spread_rumor` already exists (`services.py:517`).
- **Action:** track `ConversationSession` edges in `handle_autonomy_tick` (`activity` is already reported), `submit_bg("sim.social.close")`, callback writes a social memory + contagion, fills `social_sessions`.

### 1.8 `mem.legacy` handler (P28, sidecar side) ✅

- **Exists:** `purposes.py:139-141`; `add_memory(type="legacy")` works; prune protects legacy (`sqlite_store.py:329`).
- **Action:** in `handle_event`, branches `death|marriage|birth` → `mem.legacy` → `add_memory("legacy")`; optionally fire `sim.lifestory`. (The Mod trigger is task 2.1.)

### 1.9 `mem.relationship.review` (P29) ⬜

- **Exists:** `purposes.py:142-144`; `relationships.qualitative_note` exists (`sqlite_store.py:70`) but is never written; `state.relationships` always empty; `deep_window_open` computed and idle (`services.py:1007`).
- **Action:** ingest the census `relationships[]` (currently discarded) → `upsert_relationship`; in the deep window, review active edges → `run_purpose("mem.relationship.review")` → callback writes `qualitative_note`.

### 1.10 `ops.panel.summary` (P33) ⬜

- **Exists:** `purposes.py:158-160`; `handle_controls_get/post` (`services.py:983-991`) without a trigger.
- **Action:** trigger on `set_control`/panel open; expose the 2-line summary in `/v1/status`; consume in the Quick Menu (Mod).

### 1.11 `ops.recap` consumption (P32) ⬜

- **Exists:** `services.py:352-376` submits `ops.recap`, but `recap_job_id` is always `None` and the result is discarded.
- **Action:** capture the job id, `_recap_callback` stores `headline/recap_text`, new `GET /v1/recap`; the Mod displays a banner (Phase 2).

### 1.12 `sim.aspiration` (P12, sidecar side) ⬜

- **Exists:** `purposes.py:85-87`; **`ambition` is missing** from `PROFILE_SHAPE_KEYS` (`agent/profile.py:16-21`).
- **Action:** add `ambition` to the shape/normalize; handler persists it and feeds `sim.cognition`. (Mod collection = 2.2.)

### 1.13 `sim.background.expand` (P13, sidecar side) ⬜

- **Exists:** `purposes.py:88-90`; `relationships.known_secrets` + `add_known_secret` (`sqlite_store.py:421`) with no caller.
- **Action:** handler writes 3 `backstory` memories; expose/consume `known_secrets` for the `sim_GetToKnow` hook (3.6).

### 1.14 F13/F12 residuals ⬜

- Lease expiration checked in `god/coordinator.py`; the `off` tier in `agent/presence.py` made effective.

### Phase 1 verification

- Extend `test_god.py`, `test_p1_god_world.py`, `test_services_endpoints.py`, `test_world_rumors.py` (+~40 tests).
- `python -m pytest -q` green; no schema change.

---

## Phase 2 — Mod: event sources & infra (Python 3.7, blind)

### 2.1 Lifecycle listeners (unblocks 1.8) ✅

- **Exists:** `post_events` defined (`http_client.py:462-478`) and **never called**; `/v1/events` + `handle_event` idle.
- **Action:** S4CL death/marriage/birth listeners → `post_events(event_category ∈ death|marriage|birth)`. Isolate the API in a facade.

### 2.2 Aspiration collection (unblocks 1.12) ⬜

- **Action:** `state_collector.py` collects the current aspiration in the delta/census; detect change/milestone and report.

### 2.3 Real `installed_packs` (A10) ⬜

- **Exists:** `_get_installed_packs` is an empty stub (`state_collector.py:124-133`); the sidecar already stores/exposes it (`services.py:402`, `:1042`).
- **Action:** implement via S4CL `CommonPackUtils`; the sidecar guards `set_weather` (Seasons) and dependent arcs + warning.

### 2.4 `spawn_npc` intent contract ✅

- **Action:** new kind in `schemas.py` + `agent/intents.py` (sidecar) + dispatch/`_WHITELISTED_COMMANDS` in `tool_executor.py` (Mod), via `SituationManager.create_situation()` (prerequisite of 1.1/1.3/3.3).
- **Risk:** contract change; normalize degrades to `command`.

### 2.5 FC4 — Panic Button (`Ctrl+Shift+S`) ⬜

- **Exists:** `IntentBus.clear_all()` (`intent_bus.py:283`) never called; no Mod hotkey; locale `notify.paused.*` already exists (`en-US.json:75-78`).
- **Action:** S4CL keybind (or Quick Menu button) → `clear_all()` + `POST /v1/config/panic` + notification. Sidecar endpoint = 4.8.

### 2.6 FC1 — Onboarding Wizard ⬜

- **Exists:** single notification (`main.py:149-206`); `bootstrap_needed` returned and discarded.
- **Action:** `post_lifecycle_session_start` callback reads `bootstrap_needed` → `CommonChooseResponseDialog` with `[⚡ Quick Mode]` / `[🌐 Configure in Browser]` / `[🎮 Play First]` (`post_async` with callback already exists: `http_client.py:296-306`).

### 2.7 FC5 — Compatibility detection ⬜

- **Action:** scan `Mods/` for signatures (MCCC, WickedWhims, Slice of Life) → `detected_mods[]` in the census; the sidecar exposes it in `/v1/status` + warnings (SPA Tab 3).

### 2.8 A11 — Activity/archetype maps ⬜

- **Action:** fill `activity_map`/`archetype_map` (`tuning.py:229,232`, currently empty).

### 2.9 Catalyst end-of-interaction signal (unblocks 1.2) ✅

- **Action:** report the end of the `ConversationSession` + the agent's decision (`accept/reject/fight`) via `/v1/god/beat-ended`/`post_events`.

### Phase 2 verification

- `py -3.7 -m py_compile mod/sensewright_mod/*.py`; `test_mod_ui_keys.py` for new keys; sidecar tests for the new event categories.

---

## Phase 3 — P2 native hooks (blind; validate in Phase 5)

### 3.1 `build_package.py` — `object` and `situation` types ✅

- **Exists:** `TUNING_TYPES` (`build_package.py:59-66`) only has buff/trait/snippet/interaction/pie_menu_category/sim_data.
- **Action:** add the **object definition** and **situation** resource types (needed for 3.3–3.7).

### 3.2 Mirror "Reflect" (A8) ✅

- **Exists:** only the `stbl.pie_menu.mirror_reflect` key (`en-US.json:7`/`pt-BR.json:7`).
- **Action:** XML `mod/tuning/interactions/sw_mirror_reflect_interaction.xml` + class `SensewrightMirrorReflectInteraction` in `interactions.py` → fires `evo.reflect` (`/v1/evolve` trigger `mirror`); object target (mirror), not Sim.

### 3.3 VisitSituation / NPC spawn ✅ (blind; Phase 5 checklist)

- **Action:** consume the `spawn_npc` intent (2.4) via `SituationManager`; catalyst NPC walks the sidewalk/rings the doorbell.

### 3.4 Diary + "Snoop" ✅ (blind; Phase 5 checklist)

- **Action:** object with a `TooltipComponent` showing the `sim.diary` text; hook into the Snoop interaction; new `stbl.diary.*` keys.

### 3.5 Autobiography Book ⬜

- **Action:** physical book object with `profile.life_story` chapters; spawn on the bookshelf; new STBL keys.

### 3.6 `sim_GetToKnow` ⬜

- **Action:** hook into the native "Get to Know" interaction → endpoint increments `known_secrets` and reveals 1 secret/backstory from `relationships`.

### 3.7 Tombstone Epitaph ⬜

- **Action:** hook into "Engrave Epitaph" writing the poetic `mem.legacy` text (low priority).

### 3.8 Sleep balloons ✅ (blind; Phase 5 checklist)

- **Exists:** `native_hooks.py:212-233` applies the dream buff but does not inject the text (`:226-228`).
- **Action:** `balloon_requests` during the sleep animation + `{0.String}` injection of the `dream_narrative` into the buff tooltip (re-apply the buff with tokens).

### 3.9 Mailbox ✅ (blind; Phase 5 checklist)

- **Action:** new `GET /v1/world/neighborhood` (sidecar) returning chronicles (`world/chronicle.py`) + `rumors_known_by` (`world/rumors.py:58`); "Neighborhood Stories" interaction in the Mod.

### Phase 3 verification

- `py -3.7 -m py_compile`; `build_package.py` emits the new resources; locale parity; **Phase 5 manual checklist**.

---

## Phase 4 — Web Studio & P4 (sidecar + SPA, no TS4)

### 4.1 Persist profile ⬜

- **Exists:** `handle_profile` (`services.py:853-880`) ignores `payload["profile"]`; the SPA sends it (`app.js:301-315`).
- **Action:** accept the posted `profile` → merge with `normalize_profile` → `upsert_sim_profile`.

### 4.2 API keys — Layer 1 ⬜

- **Exists:** the SPA posts to `/v1/god/controls` (`app.js:414-422`), but `set_control` (`controls.py:131-159`) does not handle `provider.*`.
- **Action:** new credentials endpoint (e.g., `POST /v1/config/provider`) outside `panel.toml` (REQ-PNL-02/REQ-SCHED-01); update `app.js`.

### 4.3 Casting/Beats in the SPA ⬜

- **Action:** `GET /v1/god/arc` (beats; `steer_arc` for edit/skip/rewrite) and `GET /v1/god/cast`; wire `btn-recast`, `casting-list`, `beats-list` in `app.js`.

### 4.4 Zeitgeist/Spoiler/free_only ⬜

- **Action:** `handle_zeitgeist` persists `tags`/`weather_preference` (ignored in `services.py:977`); SPA sends `spoiler_shield` and listens for the `free_only` `change`.

### 4.5 Real `compile-addon` ⬜

- **Exists:** stub (`routers/i18n.py:26-28`, `services.py:1056-1064`); the compiler is ready in the Mod (`build_package.py`: `extract_stbl_strings`, `fnv1_32`, `build_stbl_body`, `stbl_resource_key`, `build_dbpf`).
- **Action:** port the logic into the sidecar; generate `Sensewright_Locale_<code>.package` into `Mods/`; `FileResponse` download; button in Tab 3.

### 4.6 FC2 — Sim Export/Import ⬜

- **Action:** `GET /v1/sim/{id}/export` (profile + memories + psyche) and `POST /v1/sim/import`; buttons in Tab 1. Testable without TS4.

### 4.7 FC3 — Cost dashboard ⬜

- **Action:** record requests/tokens per provider with per-model pricing (Layer 1) and an aggregator; `GET /v1/status/cost` (day/week + projection); widget in Tab 3.

### 4.8 Panic endpoint (sidecar side) ⬜

- **Action:** `POST /v1/config/panic` (pairs with 2.5): pause the `LLMScheduler` + `state.drain_intents()`.

### Phase 4 verification

- Extend `test_services_endpoints.py`, `test_god.py`, `test_i18n_engine.py` (FNV-32/`ts4_stbl_byte`) (+~25 tests).

---

## Phase 5 — M8: in-game validation (manual checklist, TS4)

Acceptance criteria (`requirements.md` "Acceptance Criteria for M8"):

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

## 3. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| EA tuning IDs/APIs change between patches | High (Phase 3) | Facade isolating engine calls; validate per build in the in-game phases |
| New `spawn_npc`/`beat-ended` contract | Medium | Normalization degrades to `command`; additive endpoints |
| `build_package.py` lacks `object`/`situation` types | Medium | Implement 3.1 before 3.3–3.7; validate the emitted resources |
| Heuristic `installed_packs` / labeled `family_links` | Low | Conservative guard (do not enable a lever when uncertain) |
| `balloon_requests`/tooltip tokens are workarounds | Medium (Phase 3.8) | Leave for last in P2; document in `status.md` |
| `handle_profile` currently ignores the posted profile | Low | Isolated fix in 4.1 with a regression test |

---

## 4. Plan completion criteria

1. All phases F1–F4 items ✅ with green tests (`pytest` + `py_compile` 3.7 + builds).
2. Phase 5 executed in-game, with the table filled in.
3. `docs/status.md` updated: F01–F22, P01–P33 (all **Full** or justifiably deferred), A1–A11, FC1–FC5.
4. `README.md` aligned (the "Not yet done" section revised).

---

## 5. Progress

- [x] Phase 1 — P1 residual (sidecar) — P0 done; **1.1, 1.2, 1.8 done** (1.3–1.7, 1.9–1.14 pending)
- 🟡 Phase 2 — Mod: events & infra — **2.1, 2.4, 2.9 done** (2.2/2.3/2.5–2.8 pending)
- 🟡 Phase 3 — P2 native hooks — **3.1–3.4, 3.8, 3.9 coded blind** (Phase 5 in-game validation pending)
- [x] Phase 4 — P3: LLM, Config & Observability — done (per-model cooldown, tier concurrency, asymmetric refund, trace_id, VACUUM)
- [ ] Phase 5 — M8 in-game validation
- [ ] Close-out — docs/status.md + README
