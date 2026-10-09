# Dev Mode / WebUI — Co-Author & LLM Grounding (Plan)

> **Status:** ✅ **Implemented** (2026-10-09) — S1–S5 sidecar, B1–B5 mod, tuning/locales and
> `tests/test_grounding.py`. In-game click flow pending Playtest #5 (Stage 3).
> **Date:** 2026-10-09
> **Branch:** `v2-remake`
> **Closes:** [`project-status.md`](project-status.md) → Gap-Closing Plan §4.9 (Dev Mode / WebUI stubs)
> **Depends on:** the canonical execution order in
> [`operations.md` → Recommended execution order](operations.md#recommended-execution-order-2026-10-05)

This document specifies the remaining Dev Mode / WebUI work (the menu shell shipped in
commit `3985684`, but every action behind the items is a stub) **and** the LLM *grounding*
contract that the co-author and regeneration flows must obey. It is a **design + item
catalog**; the sequence lives in `operations.md`.

**On this page**

- [1. Scope & decisions](#1-scope--decisions)
- [2. Business requirements](#2-business-requirements)
- [3. Native ground-truth inventory](#3-native-ground-truth-inventory)
- [4. Discovery — `sim.profile` is under-grounded](#4-discovery--simprofile-is-under-grounded)
- [5. Reference pattern — `sim.dream`](#5-reference-pattern--simdream)
- [6. Implementation plan](#6-implementation-plan)
- [7. Tests, docs & verification](#7-tests-docs--verification)
- [8. Commit sequence](#8-commit-sequence)
- [9. Open decisions](#9-open-decisions)

---

## 1. Scope & decisions

### 1.1 The stubs being completed (§4.9)

| Menu item | Today | Evidence |
|---|---|---|
| `[SW Dev: Sim]` → Rewrite Profile / Co-Author | shows "WIP" only | `dev_interactions.py:49-52` |
| `[SW Dev: God Mod]` → Rewrite Background / Co-Author | shows "WIP" only | `dev_interactions.py:77-80` |
| `[SW Dev: Sim]` → Dump Profile | notifies "Triggering dump…", no call | `dev_interactions.py:64-66` |
| `[SW Dev: God Mod]` → Dump Zeitgeist | notifies "Triggering dump…", no call | `dev_interactions.py:92-94` |
| `[SW Dev: System]` | empty category (`debug_sys` never invoked) | `dev_manager.py:34-37` |
| God actions placement | anchored on the **mailbox** object | `object_interactions.py:360-362` |

### 1.2 Decisions (closed)

| # | Decision | Choice |
|---|---|---|
| **D1** | Rewrite/Co-Author behavior | **Always via LLM** |
| **D2** | Dump output | **Worker log + summarized in-game notification** |
| **D3** | `[SW Dev: System]` | **Implement** (Status / Panic / Resume / Reload i18n / toggle debug) |
| **D4** | God action placement | **Keep on the mailbox** (no code change) |
| **D5** | Native merge | **Mandatory for every steered text** (co-author *and* pure regeneration) |
| **D6** | Co-author purpose | **Reuse `sim.profile`** (Option A — keeps "33 purposes"; fixes base generation too) |
| **D7** | "Rewrite Background" target | **Neighborhood zeitgeist** (reuses `/v1/god/zeitgeist`; matches the stub's "Neighborhood co-author" wording) |

---

## 2. Business requirements

### R-0 — Invariant: merge, never replace

> Every steered text (Sim profile, neighborhood background/zeitgeist) is written by the LLM
> as a **merge of three layers**: (1) the player's free text (optional), (2) the God
> Director's theme, (3) the native ground truth. The LLM **never invents or contradicts**
> a native fact; it only writes the narrative layer on top.

This is the prompt-level counterpart of `REQ-PROF-02` (native traits/likes/dislikes/species/
age_stage are ground truth and never overwritten by the LLM, enforced today only in
`normalize_profile`).

### R-1 — Co-author receives the full native context

The co-author handler MUST build the prompt context with: full profile, `traits`/`likes`/
`dislikes`/`age_stage`/`species`, relationships, recent memories, `legacy` memories,
`life_story`, family and `zeitgeist`.

- **Acceptance:** the `context_json` sent to the LLM contains these blocks (unit test asserts
  presence, not content).

### R-2 — Native facts are immutable

`traits`/`likes`/`dislikes`/`species`/`age_stage` keep coming from the census via
`normalize_profile`; the LLM cannot overwrite them.

- **Acceptance:** a co-author attempt to change a trait is reverted by `normalize_profile`.

### R-3 — Historical milestones preserved and incorporated

`life_story` and `legacy` memories (death/marriage/birth — `constants.LEGACY_CATEGORIES`)
MUST be passed to the LLM (for coherence) and never deleted — merge, do not replace.

- **Acceptance:** after co-authoring, the existing `life_story` survives (unless the player
  explicitly directs otherwise) and `legacy` memories are untouched.

### R-4 — Explicit "merge, not replace" instruction

The co-author prompt template MUST tell the LLM to honor (a) the player's text, (b) native
facts, (c) existing history, and return the **merged** profile/background.

- **Acceptance:** the new text reflects the player's direction **and** stays consistent with
  traits/age/relationships/history.

### R-5 — Neighborhood symmetry

The neighborhood co-author receives the current `zeitgeist` + `chronicles` + `rumors` +
`active arc`, merging with the player's text.

- **Acceptance:** the new zeitgeist/background is coherent with the neighborhood history, not
  a disconnected reinvention.

### R-6 — 0-key fallback stays truthful

Offline, the deterministic fallback MUST NOT invent native facts: it returns the existing
profile plus the player's text stored as a narrative field (or a localized fallback that
respects traits/age).

- **Acceptance:** offline operation never corrupts ground truth.

### R-7 — Pure regeneration also merges director theme + native truth

Regeneration **without** co-author text MUST merge the God Director's theme
(`active_arc.theme` + `current_beat().god_whisper_hint` + `zeitgeist.preset/tags`) **and** the
native truth (Sim: traits/age/relationships/memories/`life_story`/family; neighborhood:
chronicles/rumors/arc). Co-author is only a special case: same merge + the player's text.

- **Acceptance:**
  - `sim.profile` (pure regeneration) receives theme/whisper + zeitgeist tags + relationships
    + memories + `life_story` + family + traits/age in `context_json`.
  - `god.zeitgeist` (pure regeneration) receives `active_arc.theme` + chronicles + rumors.
  - The result is coherent with the active arc and the Sim/neighborhood history — not invented
    from scratch.

---

## 3. Native ground-truth inventory

These are the sources the merge must read (all already exist in the sidecar):

| Layer | Source (`file:line`) | Provides |
|---|---|---|
| Native census | `services.py:927-1023` (`handle_census`); `state.py:194-221` | name, species, age_stage, gender, traits, likes, dislikes, aspiration, career, household_id, family_links, is_player, schedule_blocks, mood, activity, location |
| Persistent profile | `memory/sqlite_store.py:492` (`get_sim_profile`); shape `agent/profile.py:16-21` | core_personality, current_demeanor, speech_style, backstory, goals, ambition, secrets, quirks, life_story |
| Background | `memory/sqlite_store.py:501` (`set_sim_background`) | scene/context narrative |
| Relationships | `memory/sqlite_store.py:511` (`export_sim_bundle`); `:418` (`upsert_relationship`); runtime `state.relationships` | friendship, romance, known_traits, known_secrets, qualitative_note, bits/sentiments |
| Memories | `memory/sqlite_store.py:296` (`recent_memories`); `export_sim_bundle.memories` | thoughts, events, diary, consolidated, **legacy** |
| Family | `services.py:65-94` (`_resolve_family`) | named relatives (never invent one) |
| Director theme | `god/arcs.py:16` (`create_arc`); `god/orchestrator.py:182` (`god_whisper_hint`) | active arc theme + beat whisper |
| Neighborhood | `god/zeitgeist.py:37` (`current_zeitgeist`); `world/chronicle.py` (`get_chronicles`); `world/rumors.py` (`get_rumors`); `services.py:2085` (`handle_get_arc`) | zeitgeist tags/preset/weather, chronicles, rumors, active arc |

---

## 4. Discovery — `sim.profile` is under-grounded

The pure regeneration path does **not** consider the director's theme nor the native truth
today (the only exception is `sim.dream`):

| Flow | Context built today | Director theme? | Native truth? |
|---|---|---|---|
| `sim.profile` (bootstrap/bg) | `_schedule_profile_generation` ctx = `{sim_name, species, age_stage, gender, traits, likes, dislikes}` (`services.py:185-191`) | ❌ | ❌ |
| `sim.profile` (endpoint) | `handle_profile` ctx, same shape (`services.py:1818-1821`) | ❌ | ❌ |
| `god.zeitgeist` | `run_zeitgeist` ctx = `{save_id, zeitgeist_text}` (`god/zeitgeist.py:16-20`) | ❌ | ❌ (no chronicles/rumors) |
| `sim.dream` ✅ | `_on_sleep_start` reads `current_zeitgeist` + `active_arc`→`god_whisper_hint` (`services.py:323-336`) | ✅ | ✅ |

**Aggravating factor:** even the `traits`/`age` that *are* passed to `sim.profile` are
**discarded** from the payload — `_build_payload` (`llm/context.py:308-342`) only copies
`_DEEP_FIELDS` (`llm/context.py:32-35`) + the P0/P1/P2 keys, so `traits`/`likes`/`dislikes`/
`age_stage`/`species`/`goals`/`secrets`/`quirks`/`ambition` never reach `context_json`, despite
the prompt claiming "Ground it in the provided traits and age" (`locales/content/en-US.json:85`).

Fixing this once benefits bootstrap, chat, endpoint and co-author paths.

---

## 5. Reference pattern — `sim.dream`

`_on_sleep_start` (`services.py:317-342`) already does the merge correctly: it reads
`current_zeitgeist`, `state.active_arc` → `current_beat().god_whisper_hint`, and feeds them,
with traits and psyche, into `build_dream_context`. The fix is to **generalize this pattern**
to `sim.profile` and `god.zeitgeist`.

---

## 6. Implementation plan

### 6.1 Sidecar (Python 3.10+)

#### S1 — Transversal context enrichment for `sim.profile` (R-1 / R-7)

- `services.py:185-191` (`_schedule_profile_generation`) and `services.py:1818-1821`
  (`handle_profile`): build a rich ctx via `export_sim_bundle`
  (profile + background + relationships + memories) + `current_zeitgeist` +
  `state.active_arc` (`theme`/`god_whisper_hint`) + `_resolve_family`.
- `llm/context.py:308-342` (`_build_payload`): include `traits`/`likes`/`dislikes`/`age_stage`/
  `species`/`goals`/`secrets`/`quirks`/`ambition` in the profile payload (not only
  `_DEEP_FIELDS`); include `active_arc`/`theme`/`zeitgeist` in the P0 keys.
- `i18n_engine.py:376-382` (`render_prompt`): add `"coauthor_block": ""` to `base_vars`
  (safe default for every caller).
- `locales/content/{en,pt}.json:85` (`sim.profile` system): instruct the merge and inject
  `{coauthor_block}` + trait/age/relationship/zeitgeist anchors.

#### S2 — Profile co-author (R-1 / R-4)

- `handle_profile` (`services.py:1785`): add a `coauthor_text` branch → rich ctx (S1) +
  `coauthor_block = "player directs: …"` → `run_purpose("sim.profile", ctx, lang)` →
  `normalize_profile` (R-2) + `upsert` (preserve `life_story`, R-3).
- **Contract:** `POST /v1/profile`
  `{sim_id, coauthor_text?, lang, world_sim_tick, save_id}` → `{profile: {...}}`.

#### S3 — Neighborhood co-author / regeneration (R-5 / R-7)

- `run_zeitgeist` (`god/zeitgeist.py:10`): enrich the ctx with `active_arc.theme` +
  `chronicles` + `rumors`; instruct the merge in the `god.zeitgeist` template
  (`locales/content/{en,pt}.json:109`).
- **Contract:** `POST /v1/god/zeitgeist` `{save_id, zeitgeist_text?, lang}`.

#### S4 — 0-key fallback stays truthful (R-6)

- `fallbacks.py` (`_fb_profile:67`, `_fb_zeitgeist:266`): return the existing profile + the
  player's text (or a localized fallback respecting traits/age); never contradict ground truth.

#### S5 — Dumps & System (D2 / D3)

- **Dump Profile:** reuse `POST /v1/sim/export` (`handle_sim_export:1841`). No new endpoint.
- **Dump Zeitgeist:** new `handle_god_dump` (near `handle_get_arc:2085`) returning
  `{zeitgeist, arc, cast, chronicles, rumors}`; new `GET /v1/god/dump?save_id=` in `god.py`.
- **System:** reuse `GET /v1/status` (`health.py:23`), `POST /v1/config/panic|resume` +
  `GET /v1/config/panic`, `POST /v1/i18n/reload` (`i18n.py:19`). No new endpoints.

### 6.2 Mod (Python 3.7)

Primary file: `mod/sensewright_mod/dev_interactions.py` (dialogs reuse
`chat_ui.py:97-103`; HTTP via `http_client.py:580/585` `post_async`/`get_async`).

| Item | Action |
|---|---|
| **B1 Rewrite Profile** (`dev_interactions.py:49-52`) | `post_async('/profile', {sim_id, force_interactive:false})` → open `CommonInputTextDialog` prefilled with the current profile → submit `post_async('/profile', {sim_id, coauthor_text, …})` |
| **B2 Rewrite Background** (`:77-80`) | prefill via `get_async('/world/neighborhood?save_id=')` → submit `post_async('/god/zeitgeist', {save_id, zeitgeist_text, lang})` |
| **B3 Dump Profile** (`:64-66`) | `post_async('/sim/export', {sim_id})` → `worker_log_info` (full JSON) + summarized notification |
| **B4 Dump Zeitgeist** (`:92-94`) | `get_async('/god/dump?save_id=')` → log + summarized notification |
| **B5 System** | 4 new classes: `DevSysToggleDebug`, `DevSysDumpStatus`, `DevSysPanic` (toggle), `DevSysReloadI18n`; register in `_MailboxInteractionHandler` (`object_interactions.py:360-362`) + `_log_object_tuning_status` (`:91-93`) |

### 6.3 Tuning / XML / locales

- 4 new XMLs under `mod/tuning/interactions/`:
  `sw_dev_sys_{toggle_debug,dump_status,panic,reload_i18n}_interaction.xml`
  (`c="SensewrightDevSys*Interaction"`, `m="sensewright_mod.dev_interactions"`,
  `category=swtune:sw_pie_menu_category_dev_sys`, `target_type=OBJECT`, `pie_menu_icon` =
  `sensewright_icon`).
- `tuning.py:39-49`: register the `interaction_dev_sys_*` keys.
- STBL/UI keys (`mod/locales/ui/{en,pt}.json`): `stbl.pie_menu.dev.*` + `notify.dev.*`.
- `build_package.py` already globs `TUNING_DIR.rglob("*.xml")` (`:238`, `:511`) — no change.

---

## 7. Tests, docs & verification

### 7.1 Tests

- **Sidecar** (`sidecar/tests/`): `test_dev_mode.py` + `test_grounding.py` —
  - `handle_profile` with `coauthor_text` persists the merged profile and leaves
    traits/age untouched.
  - `_build_payload` includes `traits`/`age_stage`/`theme`/`zeitgeist`.
  - `handle_god_dump` contract `{zeitgeist, arc, cast, chronicles, rumors}`.
  - `run_zeitgeist` receives `theme`/chronicles.
  - `render_prompt` expands `{coauthor_block}` and does not break when empty.
- **Mod:** `test_tuning_refs.py` (new `interaction_dev_sys_*`), `test_package_index.py`,
  `test_mod_game_imports.py`.

### 7.2 Verification (exit 0)

```
cd sidecar && python -m pytest -q
py -3.7 -m py_compile mod/sensewright_mod/*.py
python mod/build_package.py
python mod/build.py
```

In-game validation (Playtest #5 / Stage 3) for the dialogs + notifications.

### 7.3 Docs touched

- This document (canonical plan).
- [`project-status.md`](project-status.md) — §4.9 (stubs + grounding scope) and the changelog.
- [`operations.md`](operations.md) — the execution-order note.
- [`architecture.md`](architecture.md) — the grounding/merge pipeline.
- [`specification.md`](specification.md) — reference to the co-author/grounding requirements.
- [`README.md`](README.md) (hub) and the repository `README.md`.

---

## 8. Commit sequence

1. `feat(sidecar): ground sim.profile + god.zeitgeist in native truth & director theme`
   (S1 + S3 + S4, R-7)
2. `feat(dev): co-author rewrite (profile + background) via LLM merge` (S2, B1 + B2, R-1…R-6)
3. `feat(dev): dump profile/zeitgeist wired (log + notification)` (S5, B3 + B4)
4. `feat(dev): System dev actions (status/panic/reload/toggle)` (B5 + XML/locales)
5. `docs(dev): co-author & grounding spec + close §4.9`

---

## 9. Open decisions

Both default to the recommendation below; change here if the direction differs.

1. **Co-author purpose — Option A vs B.** Reuse `sim.profile` enriched (Option A, keeps the
   "33 purposes", also fixes base generation) **vs** a new `sim.profile.rewrite` purpose
   (Option B, 34 purposes, isolated). → **Option A (D6).**
2. **"Rewrite Background" (God) — target.** The stub says *"Neighborhood co-author"*, so the
   target is the **neighborhood zeitgeist** (not the per-Sim `god.background`). →
   **Zeitgeist (D7).**
