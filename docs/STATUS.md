# Sensewright — Status & Handoff

> Last updated: **2026-09-30**. In-game build: **`2026-09-29.26`**;
> **in-game layer migrated to the stack base (S4CL + Lot 51 Core)** on branch
> **`migrate-s4cl-lot51`** (repo moved to `C:\workspace\sensewright`). Cheats are
> **`sw.*`**, artifacts `Sensewright.ts4script` + `Sensewright.package` (tuning),
> install folder `Mods\Sensewright\` (no XmlInjector — see `CHANGELOG.md`).
>
> **⚠️ The stack migration is code-complete and offline-green but NOT yet validated
> in-game.** The exact S4CL/Lot 51 import paths must be confirmed live; start with
> **`docs/stack_migration.md`** and §5 item 0.
>
> This file is the entry point for a new session. Read it, then
> `docs/stack_migration.md`, `docs/ts4_internals.md`, `PLANO.md`,
> `docs/ui_panel.md`, and `CHANGELOG.md`.

---

## 1. Snapshot

| Item | Value |
|---|---|
| Repo root | `C:\workspace\sensewright` (git repo, branch **`migrate-s4cl-lot51`**; pre-migration on `main` / tag `pre-migracao`) |
| In-game mod | `mod/sensewright_mod/` (Python 3.7; **stdlib + S4CL + Lot 51 Core**) |
| Sidecar | `sidecar/sensewright_sidecar/` (Python 3.12 target; runs on 3.10.11 here) |
| Build stamp | `mod/sensewright_mod/main.py` → `_BUILD = "2026-09-29.26"` |
| Installed artifact | `...\Mods\Sensewright\Sensewright.ts4script` + `Sensewright.package` (tuning; XmlInjector retired) |
| Stack libs | `...\Mods\` root: `sims4communitylib*.ts4script` + `lot51_core*.ts4script` (required) |
| Sidecar data | `...\Mods\Sensewright\sidecar\data\` (`memory.sqlite3`, `sidecar.log`, `audit.log`, `runtime.json`, `token`) |
| Mod log | `...\Mods\Sensewright\sensewright_output.log` |
| Game install | `C:\Program Files\EA Games\The Sims 4` |
| Tests | sidecar **463**, mod **384**; ruff clean (sidecar); `py -3.7 mod/build.py` clean |

**Sidecar runs from source with the workspace venv** (no PyInstaller yet — Phase 6).
The mod **autoboots** it (`install-mod.ps1` writes the venv interpreter to
`sidecar/python.txt`; `config.find_python()` reads it). It auto-exits with the game.

**Build + install**

```powershell
py -3.7 mod\build.py            # -> dist\Sensewright.ts4script
powershell -ExecutionPolicy Bypass -File scripts\install-mod.ps1   # copies the mod + sidecar
```

**Tests**

```powershell
cd sidecar; .\.venv\Scripts\python.exe -m pytest tests -q
python -m pytest mod\tests -q
```

> Decompiled EA sources live in the gitignored `research/ts4/`; cloned reference
> mods in `research/ui-refs/` (also gitignored). The stack migration (S4CL + Lot 51
> Core) is documented in **`docs/stack_migration.md`** — including the
> live-validation checklist for the library import paths and the pie-menu display
> names. XmlInjector is **retired**; the interaction tuning `.package`
> (`mod/tuning/**`, `mod/build_package.py`) is **kept** because S4CL custom
> interactions require a tuning resource.

---

## 2. What is implemented

- **Stack base (S4CL + Lot 51 Core)**: the in-game layer is now built on the two
  community libraries (branch `migrate-s4cl-lot51`); all access is isolated in
  `mod/sensewright_mod/integrations.py`. Offline-green; **live validation of the
  import paths is pending** (`docs/stack_migration.md`).
- **Phases 1–5c** (skeleton → God orchestration): code-complete.
- **v0.2 §14** (M1/M2 memory, A1–A3 agency, P1 personality, G1 God scoping): code-complete.
- **v0.3 §15**:
  - **R2 seats** (`agent/seats.py`), **R3 intents** (`agent/intents.py` + mod `GameLever`),
    **R4 cognition** (`agent/cognition.py`), **R6 God director**, **F0/F1** decompiler + `sw.probe`.
  - **R5 sim↔sim channel** (`agent/social.py`): two seated Sims get a 1–2 line exchange
    (LLM + template fallback) → two `speak` intents (executed by the GameLever).
  - **R7 panel** — `panel_ui.py` (S4CL) + `sw.panel`, plus the `sw.agents` roster
    and `sw.lang`; see `docs/ui_panel.md`.
  - **God orchestration loop (`.23`)** — `state_collector.maybe_god_tick` runs the
    Phase 5c tick from the zone heartbeat and executes the directives;
    `sw.god on|off|tick|preset|set` controls it.
- **Lifecycle**, **validation logging**, **collector auto-start** (Lot 51
  `GAME_TICK`, native `zone.Zone.update` fallback; ~15 s pulse), **buffs**
  (`SimInfo.Buffs._active_buffs` → `Buff.buff_type.__name__`).
- **Sidecar offline-green gate fixed (sidecar only, no build stamp)**: the social
  pair cooldown no longer blocks the first-ever pair on a freshly-booted machine
  (`time.monotonic()` starts at boot, not at `0.0`), and `graph.configure()` now
  releases the previous memory store's SQLite connection (no leak on reconfigure;
  fixes the Windows temp-dir teardown errors). Sidecar **461 -> 463**.

### 2a. In-game UI on the stack (S4CL + Lot 51)

The P0 native-dialog spike (`ui_probe.py` + `sw.uitest`) was **validated live and
then retired** with the stack migration. Notifications/dialogs now prefer the S4CL
APIs via `integrations.py`; the native dialog classes remain the fallback. The
native API map learned in P0 still applies to that fallback:
- **API map learned** (from the shipped `simulation.zip` bytecode): dialog
  **title/text/text_ok** = factories; picker **row name/description** =
  `LocalizedString`; **row tooltip** = factory; **row icon** = `ResourceKey`;
  `response_command` = namedtuple + `CommandArgType`; `UiTextInput` needs a
  `length_restriction`.

### 2b. In-game configuration panel (P1 + P2 done)

`docs/ui_panel.md`: S4CL dialogs (no Flash/slider), `data/panel.toml` overlay
(never touches `config.toml`), `sw.panel`.

- **P1 — done (build `.21`)**: all §1.4 settings promoted into `ControlSpec`
  with `target`/`path` (+ `restart_only`); generic `apply_values_to_settings` /
  `apply_control_values_to_settings` / `values_from_settings`;
  `panel_store.py` overlay (`POST /v1/config/god?persist` → `data/panel.toml`,
  deep-merged in `load_settings`, `POST /v1/config/panel/reset` deletes it);
  label/desc i18n keys for every spec (en + pt-BR). Sidecar-only + locales.
- **P2 — implemented (stack base)**: `mod/sensewright_mod/panel_ui.py` groups the
  ControlSpec list from `GET /v1/god/controls` into sections and renders them with
  S4CL dialogs (+ console fallback); opened via `sw.panel` and the pie menu. Live
  validation of the S4CL dialog navigation is pending.

### 2c. Pie menu (interaction menu) — S4CL registry + tuning package

- **`mod/sensewright_mod/pie_menu.py`** — 4 `CommonImmediateSuperInteraction`
  classes (`Sensewright{Panel,Chat,Confirm,Hud}Interaction`). Their tuning lives
  in `mod/tuning/interactions/*.xml` (built into `dist/Sensewright.package` by
  `mod/build_package.py`); `pie_menu.install()` (called from `__init__`) registers
  two S4CL `CommonScriptObjectInteractionHandler`s: all four on Sims, the panel on
  `Func_Computer` objects. **No XmlInjector** (S4CL's `CommonInteractionRegistry`
  replaces it); the tuning `.package` is **kept** — S4CL needs a tuning per custom
  interaction.
- Display names come from the packaged STBL (`cmd.pie.*` keys in
  `mod/tuning/stbl.json`, en + pt-BR); `get_name` is overridden at runtime so
  `sw.lang` can still switch language (**needs live check**).
- Dispatch runs the same actions as before (`panel` → `panel_ui.open_panel`,
  `chat` → text input → `main.run_chat`, `confirm` → Ok/Cancel, `hud` → toggle).
- The XmlInjector snippet pipeline and the P0 dialog spike (`ui_probe.py`,
  `sw.uitest`) were **removed**.

---

## 3. Validated live (in-game)

> **Pre-migration baseline.** Everything below was validated with the **native**
> implementation. The S4CL/Lot 51 migration (branch `migrate-s4cl-lot51`) reuses
> these flows but its library paths are **not yet validated in-game** — see
> `docs/stack_migration.md` and §5 item 0.

- `sw.help`, `sw.status`, `sw.chat` (pt-BR reply + tool calls), `sw.probe`.
- **Lifecycle**: watchdog attached → clean shutdown with the game.
- **Zone heartbeat** (build `.8`): `zone hook installed` → auto-start → pulse every
  ~15 s → sidecar `POST /v1/autonomy/tick` + `GET /v1/autonomy/intents` 200.
- **Seats/eviction (R2)**, **Intents (R3)**.
- **P0 dialog spike** (`.9`): all 8 kinds render; `picker_icons` = 16 EA keys.
- **Pie menu** (`.13`→`.19`): the 4 Sim items render (category **Ações**), the
  computer item injected; **Chat** opens a text input and the Sim replies;
  **Confirm** works; STBL names resolve.
- **Sim↔sim (R5)**: `[validate] social: 1 dialogue pair(s)` and two spoken lines
  (pt-BR/en) surfaced as notifications + `say_to`.

---

## 4. What changed in `.26` / `.25` / `.24` / `.23` / `.22` / `.21` / `.20`

**`.26` (God UI through the seam):** `god_ui._show_ok_cancel` prefers S4CL
(`integrations.s4cl_ok_cancel`/`s4cl_show_ok_cancel`) with the native
`UiDialogOkCancel` fallback; `_localize` uses
`integrations.native_localized_string`. Tests: mod **381 -> 384**.

**`.25` (Lot 51 custom service, needs a live re-check):** the stack base owns the
collector lifecycle:

1. `stack_service.py` (new) registers a `sims4.service_manager.Service` subclass
   with Lot 51 (`lot51_service_base` + `lot51_register_service`); `on_zone_load`
   calls `state_collector.ensure_started()`, `stop` calls
   `state_collector.stop()`. `__init__` registers it after the zone hook.
2. **Fixed** the Lot 51 `CoreEvent` member mapping: `OBJECT_ADDED` /
   `OBJECT_DESTROYED` (was `GAME_OBJECT_ADDED`/`GAME_OBJECT_DESTROYED`, which
   never resolved) and `LOADING_SCREEN_LIFTED` for the late zone load.
3. Tests: mod **375 -> 381**.

**`.24` (Fase E, needs a live re-check):** the collectors read trait/buff/career/
age/gender through S4CL utilities first, native fallback kept:

1. `integrations.py` adds `s4cl_trait_utils` / `s4cl_buff_utils` /
   `s4cl_sim_career_utils` / `s4cl_age_utils` / `s4cl_gender_utils`.
2. `sim_context._get_traits` / `_get_careers` and `state_collector._buff_names_of`
   / `_age_of` / `_gender_of` prefer S4CL; a failure or a missing library falls
   through to the validated native reads. The buff path still uses the exact
   tuning id (`_buff_type_name`), never a display name.
3. Tests: mod **366 -> 375**.

**`.23` (needs a live re-check):** the God **orchestration loop** is now live
in-game (Phase 5c gap closed) - **code + tests done**, not yet validated live:

1. **Mod God tick loop** (`state_collector.maybe_god_tick`): polls
   `POST /v1/god/tick` on a 60 s wall-clock cadence from the zone heartbeat,
   executes each returned directive through `tool_executor.execute`
   (`add_trait`/`add_buff`/`queue_interaction`/`say_to`) and surfaces the
   `narration` as a narrator notification. World events (no `tool_call`) stay
   notification-only. Logged as `[validate] god: ...`.
2. **`sw.god` control surface**: `sw.god` (summary + current preset),
   `sw.god on|off`, `sw.god tick` (forced), `sw.god scan` (full-save
   neighborhood census), `sw.god preset <name>` / `sw.god <preset>`,
   `sw.god set <key> <value>` (ControlSpec-validated, via
   `POST /v1/config/god`). New `http_client.god_tick` / `set_god_controls`.
   **Neighborhood mapping**: `scan_neighborhood` runs a full-save census once per
   session (the sidecar queues a background per household/Sim/related NPC); the
   sidecar merges censuses so a `full_save` map survives active-zone re-sends.
   **Native kinship**: the census now carries the family tree (`kinship`, from
   `SimInfo.genealogy`) so backgrounds respect real parent/child/sibling/partner
   ties (needs a live check on the genealogy enum labels).
3. **Sidecar orchestrator lifecycle**: returned directives are marked `issued`,
   history capped at `MAX_DIRECTIVE_HISTORY`, `drain_directives()` added, and
   `status()` reports `issued_directives`/`history_size`; `god/preset` surfaced
   in the controls value map.
4. i18n `cmd.god.*` + `notify.god.directive` (en + pt-BR); mod tests **337 ->
   363**, sidecar **437 -> 461**.
5. **Data-driven locales (no hardcoded languages)**: mod `locales/manifest.json`
   + `i18n` discovery, sidecar `locales_content/` + `content_i18n` (JSON content
   tables; lexical data in `lexicon.json`). No `("en","pt-BR")`/`_LANG_NAMES`
   references remain in code; adding a language = drop a JSON + a manifest entry.
   See SKILL §9 for the recipe.

**`.22` (needs a live re-check):** adopted from the MIT `dnavaria/sims4ai`
reference (see `THIRD_PARTY_NOTICES.md`) — **code + tests done**, not yet
validated live:

1. **Player-activity detector** (`player_activity.py`): wraps
   `Sim.push_super_affordance` and arms the player-priority lock (mod rails +
   `POST /v1/config/player-activity`) when the **player** (not the agent) queues
   an interaction. Agent `SOURCE_SCRIPT` pushes and unclassifiable sources do
   **not** fire. Installed at load + retried via `main._ensure_ready()`.
2. **Precise `cancel_current`**: cancels only the running interaction
   (`queue.running.cancel(...)`) before falling back to `cancel_all`.
3. **`_push_affordance`**: added a `queue.run_super` fallback.
4. **License**: `LICENSE` (MIT) + `THIRD_PARTY_NOTICES.md`.

**`.21` (P1, sidecar + locales):** the panel model/persistence (ControlSpec
`target`/`path`, `data/panel.toml` overlay, `?persist`, reset endpoint, i18n
keys). Offline-complete + tested; no game behaviour change (only new locale
keys), so no live check needed beyond the rebuilt artifact loading.

**`.20` (needs a live re-check):** a user-requested stack of improvements —
**code + tests done**, not yet validated live:

1. **HUD is now quiet**: the periodic status line and intent traces are **log-only**
   (`[validate] hud: …`); only sidecar **state flips** (connected/lost/error) raise a
   notification. `sw.hud now` still shows the line on demand.
2. **Dialogue language**: the chat/dialogue LLM prompt now names the language
   ("Brazilian Portuguese (pt-BR)") and forbids English when `lang != en`; the mod
   `_current_lang()` retries game-locale detection (`i18n.ensure_locale`).
3. **Richer agent context in dialogues**: `social.sim_brief(...)` feeds each Sim's
   **background, personality, recent memories and who they're talking to** (plus
   `sim_id`) into the prompt.
4. **Audience**: `SocialLayer.pick_pairs` now **prefers household Sims**
   (household↔household / household↔guest) instead of only non-player visitors.
5. **Speaker attribution**: speech notifications are prefixed with the speaker's
   name and owned by that Sim (native portrait).

---

## 5. Pending live validation (priority order)

0. **Stack migration (S4CL + Lot 51)** — see `docs/stack_migration.md`: confirm the
   library import paths resolve (they were verified against the cloned sources),
   `lot51_status()` reports `available/tick=true`, the pulse runs off
   `CoreEvent.GAME_TICK`, S4CL notifications render, the pie menu shows the 4 items
   (tuning `.package` + S4CL `CommonInteractionRegistry`, **no XmlInjector**),
   display names follow the packaged STBL / switch with `sw.lang`, and `sw.panel`
   opens.
1. **`.22` changes** above: play a pie-menu/click interaction and confirm the log
   shows the player-priority lock arming on both sides (mod rails +
   `POST /v1/config/player-activity`), and that the agent's own pushes do **not**
   arm it; confirm `cancel_current` stops the running interaction.
2. **`.20` changes** above (HUD quiet, pt-BR dialogues, richer context, household
   pairing, speaker names).
2. **R1 native `say_to`**: `tool_executor` tries multiple `InteractionContext`
   paths; confirm the native push works (else it degrades to a notification).
3. **Buffs** (`sw.probe` → `sections.buffs`), **events** (`[validate] event:`),
   **God** onboarding/backgrounds, **memory** consolidation/decay.
4. **God orchestration loop** (`.23`): `sw.god on`, then `sw.god tick` - confirm
   `[validate] god: directive ...` lines, a narrator notification, and the
   mapped tool landing (trait/buff/social) on an unplayed Sim.
4. **Pie menu polish** (next features): a real **God submenu** on the computer, an
   **agent submenu** on the Sim, a **custom “Sensewrightâ€ category**, and **our own
   icons** (SVG→DDS→`.package`).

---

## 5a. Pendências técnicas (follow-ups)

> Board of fixes/features that are **known but not done**, ordered by priority.
> Keep this list current when a session closes.

| # | Pendência | Tipo | Notas |
|---|---|---|---|
| P0 | **Live-validate the stack migration** | validation | `docs/stack_migration.md` checklist; requires S4CL + Lot 51 Core at the Mods root and the game open. Only remaining step *of the migration itself*. |
| P0 | **R1 `say_to` native lever** | fix (runtime) | `tool_executor` tries several `InteractionContext` paths; confirm the native push works, else it degrades to a notification (`PLANO.md` §15.8). |
| P1 | **`.22` player-activity + precise `cancel_current`** | validation | Play a click/pie interaction; confirm the player-priority lock arms on both sides and the agent's own pushes do not. |
| P1 | **God orchestration loop (`.23`) + Fase E reads (`.24`) + Lot 51 service (`.25`) + God UI seam (`.26`)** | validation | All offline-complete; need one live pass (`STATUS` §5). |
| P1 | **Drop the native alarm safety net** | cleanup | Once the Lot 51 `GAME_TICK` pulse is proven live, the `zone.Zone.update` / native alarm fallback can be removed (`state_collector`, `events`). |
| P2 | **Custom `Sensewright` `PieMenuCategory` + SimData + submenus** | feature | God submenu (computer), agent submenu (Sim). Needs extra DBPF resource types in `build_package.py` (`PLANO.md` §15.8 / `stack_migration.md`). |
| P2 | **Own pie-menu icons (SVG→DDS→`.package`)** | feature | Currently uses the packaged STBL names only. |
| P2 | **Levers catalog runtime validation (`docs/ts4_internals.md`)** | docs/validation | F2 produced the autonomy/levers map; entries still marked code-validated vs runtime-validated. |
| P3 | **Phase 6 — packaging** | feature | PyInstaller/Nuitka for the sidecar exe, README (OneDrive warning), 0-key mode (`PLANO.md` §11). |
| P3 | **Doc encoding cleanup** | chore | `CHANGELOG.md` / old docs contain double-encoded UTF-8 (`â€"` for `—`, `Â§`). Never rewrite with PowerShell `Set-Content -Encoding UTF8` (SKILL §12.12); fix entry-by-entry with the editor tools. |

**Recently closed (this session, sidecar only):** social cooldown epoch bug and
the `graph.configure()` SQLite leak (sidecar **461 -> 463**). See `CHANGELOG.md`.

---

## 6. Known issues / mitigations

- **Stack base (S4CL + Lot 51 Core) must be installed at the Mods root.**
  Sensewright needs XmlInjector no more: the pie menu tuning (`Sensewright.package`)
  is wired to targets by S4CL's `CommonInteractionRegistry` (`pie_menu.install`)
  and library access is isolated in `integrations.py`. The exact S4CL/Lot 51
  import paths were source-verified but still need live validation
  (`docs/stack_migration.md`).
- **Locales are data-driven.** Do not hardcode `("en","pt-BR")`/`_LANG_NAMES` or
  inline translated content. Mod UI: `locales/manifest.json` + `i18n.py`. Sidecar
  content: `locales_content/manifest.json` + `content_i18n.py` (+ `lexicon.json`).
  Adding a language = drop a JSON + a manifest entry (SKILL §9).
- **`.package` HEADER**: index offset lives at `0x40` (64-bit); write `0` at
  `0x28` (matches S4S-built packages).
- **Game-clock alarms** are unreliable (validated: don't tick). The pulse loop is
  driven by the **Lot 51 `GAME_TICK`** (`events.register_lot51_tick`), falling back
  to the native `zone.Zone.update` wrapper. Alarm callbacks **must accept `*args`**
  (the game passes the handle) — `.13` fixed the crash.
- **Player-priority lock is per-Sim** (intended).
- **Sidecar needs the venv Python** until Phase 6; re-run the installer after a
  venv change.
- **`sw.uitest`/`ui_probe` were removed** with the stack migration; the real panel
  is `panel_ui.py` (open with **`sw.panel`** or the pie-menu entry).
- **Docs encoding**: do **not** rewrite `.md`/`.json` with PowerShell
  `Set-Content -Encoding UTF8` (it double-encodes accents); use the editor tools.

---

## 7. Key files & docs

- **Roadmap**: `PLANO.md` (§11 phases, §14 v0.2, §15 v0.3).
- **UI plan**: `docs/ui_panel.md` (native panel, settings inventory, `panel.toml`).
- **Confirmed game APIs**: `docs/ts4_internals.md`.
- **Change log**: `CHANGELOG.md` (`[Unreleased]` has builds `.3`–`.23`).
- **Stack migration**: `docs/stack_migration.md` (API surface + live checklist);
  `mod/sensewright_mod/integrations.py` (the seam), `pie_menu.py`, `panel_ui.py`.
- **Localization**: `mod/sensewright_mod/locales/manifest.json` + `i18n.py`;
  `sidecar/sensewright_sidecar/locales_content/` + `content_i18n.py` (SKILL §9).
- **God orchestration**: `sidecar/.../god/orchestrator.py` + `routers/god.py`;
  `mod/.../state_collector.maybe_god_tick` + `main.sw.god`.
- **Guidelines**: `.agents/skills/sensewright_development/SKILL.md`.

---

## 8. How to continue (new session)

1. Read this file + `docs/ts4_internals.md`; confirm the sidecar is up (`GET /v1/health`).
2. Rebuild + reinstall after any code change; **restart the game** (script mods load
   only at boot).
3. Validate §4/§5 in-game; keep the loop: implement → test → build → install →
   validate live → document (`CHANGELOG.md` + this file) → update test counts in SKILL.
4. Commit on the branch and follow the CHANGELOG format (keep `research/ts4/` and
   `research/ui-refs/` gitignored).

**Current TODO on the board — the stack migration is offline-complete (build
`.26`).** The in-game layer is based on **S4CL + Lot 51 Core** (branch
`migrate-s4cl-lot51`), offline-green (384 mod tests, `py -3.7 mod/build.py` builds
the `.ts4script` + `.package`, no direct library import outside `integrations.py`).
**Only live validation remains.** Next session, in order:

1. **Validate the stack live** (`docs/stack_migration.md` checklist): install S4CL +
   Lot 51 Core at the Mods root, then confirm the import paths resolve
   (`integrations`), `lot51_status()` reports `available/tick=true`, the pulse runs
   on `CoreEvent.GAME_TICK`, S4CL notifications render, the pie menu shows the 4
   items (tuning `.package` + `CommonInteractionRegistry`, no XmlInjector), display
   names follow the packaged STBL / `sw.lang`, and `sw.panel` opens.
2. **API surface** — done offline: paths were verified against the cloned S4CL /
   Lot 51 sources (`research/ui-refs/`) and `integrations.py` + `pie_menu.py` were
   corrected (registry path, dialog/notification signatures, choose-response
   dialog). Every dialog (notifications, ok/cancel, God UI) now goes through the
   seam (`.26`). Fix anything the live run still proves wrong and update the API
   table in `docs/stack_migration.md`.
3. **Fase E — done offline (build `.24`)**: the collectors now prefer the S4CL
   utilities (`CommonTraitUtils`/`CommonBuffUtils`/`CommonSimCareerUtils`/
   `CommonAgeUtils`/`CommonGenderUtils`) with the validated native paths as
   fallback, keeping the primitive-coercion contract and **exact** tuning-id
   matching (SKILL §7). Needs a live re-check (trait/buff/career reads).
4. **Lot 51 custom service — done offline (build `.25`)**: `stack_service.py`
   owns the collector lifecycle; the CoreEvent mapping was corrected
   (`OBJECT_ADDED`/`OBJECT_DESTROYED`, `LOADING_SCREEN_LIFTED`). The native
   alarms remain as a safety net until the tick path is proven live, then they can
   be dropped.
5. Then resume the previous board: God submenu (computer), agent submenu (Sim),
   custom pie category + own icons (DDS pipeline).
