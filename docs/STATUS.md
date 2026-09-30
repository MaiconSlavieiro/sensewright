# Sensewright — Status & Handoff

> Last updated: **2026-09-29**. Build in the game: **`2026-09-29.23`** (project
> renamed **Sensewright**; cheats are **`sw.*`**, artifact `Sensewright.ts4script`,
> install folder `Mods\Sensewright\` — see `CHANGELOG.md`).
>
> This file is the entry point for a new session. Read it, then
> `docs/ts4_internals.md`, `PLANO.md`, `docs/ui_panel.md`, and `CHANGELOG.md`.

---

## 1. Snapshot

| Item | Value |
|---|---|
| Repo root | `C:\workspace\sensewright` (git repo, branch **`migrate-s4cl-lot51`**; pre-migration on `main` / tag `pre-migracao`) |
| In-game mod | `mod/sensewright_mod/` (Python 3.7; **stdlib + S4CL + Lot 51 Core**) |
| Sidecar | `sidecar/sensewright_sidecar/` (Python 3.12 target; runs on 3.10.11 here) |
| Build stamp | `mod/sensewright_mod/main.py` → `_BUILD = "2026-09-29.22"` |
| Installed artifact | `...\Mods\Sensewright\Sensewright.ts4script` (no `.package`; XmlInjector retired) |
| Stack libs | `...\Mods\` root: `sims4communitylib*.ts4script` + `lot51_core*.ts4script` (required) |
| Sidecar data | `...\Mods\Sensewright\sidecar\data\` (`memory.sqlite3`, `sidecar.log`, `audit.log`, `runtime.json`, `token`) |
| Mod log | `...\Mods\Sensewright\sensewright_output.log` |
| Game install | `C:\Program Files\EA Games\The Sims 4` |
| Tests | sidecar **461**, mod **360**; ruff clean (sidecar); `py -3.7 mod/build.py` clean |

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
> names. XmlInjector and the tuning `.package` are **retired**.

---

## 2. What is implemented

- **Phases 1–5c** (skeleton → God orchestration): code-complete.
- **v0.2 §14** (M1/M2 memory, A1–A3 agency, P1 personality, G1 God scoping): code-complete.
- **v0.3 §15**:
  - **R2 seats** (`agent/seats.py`), **R3 intents** (`agent/intents.py` + mod `GameLever`),
    **R4 cognition** (`agent/cognition.py`), **R6 God director**, **F0/F1** decompiler + `sw.probe`.
  - **R5 sim↔sim channel** (`agent/social.py`): two seated Sims get a 1–2 line exchange
    (LLM + template fallback) → two `speak` intents (executed by the GameLever).
  - **R7 panel** — dials + `sw.agents` + `sw.lang`; full native panel specified in
    `docs/ui_panel.md`.
  - **God orchestration loop (`.23`)** — `state_collector.maybe_god_tick` runs the
    Phase 5c tick from the zone heartbeat and executes the directives;
    `sw.god on|off|tick|preset|set` controls it.
- **Lifecycle**, **validation logging**, **collector auto-start** (`zone.Zone.update`
  heartbeat every 15 s), **buffs** (`SimInfo.Buffs._active_buffs` → `Buff.buff_type.__name__`).

### 2a. In-game native UI (P0 spike — validated live)

`mod/sensewright_mod/ui_probe.py` + `sw.uitest <kind>` (also `all`, `probe`, `pie`):

- Dialog kinds (all `ok=True` live): `notification`, `okcancel`, `picker`,
  `picker_icons` (EA icons), `picker_text`, `dropdown`, `labeled_icons`,
  `info_columns`, `response` (`SEND_COMMAND` button), `input` (numeric), `multi`.
- **Navigable panel mock**: `sw.uitest panel` / `sw.uitest panel_home`
  (sections → settings → best widget per kind).
- **API map learned** (from the shipped `simulation.zip` bytecode): dialog
  **title/text/text_ok** = factories; picker **row name/description** =
  `LocalizedString`; **row tooltip** = factory; **row icon** = `ResourceKey`;
  `response_command` = namedtuple + `CommandArgType`; `UiTextInput` needs a
  `length_restriction`.

### 2b. In-game configuration panel (P1 done, P2 next)

`docs/ui_panel.md`: native dialogs only (no Flash/slider), `data/panel.toml`
overlay (never touches `config.toml`), `sw.set`/`sw.panel`.

- **P1 — done (build `.21`)**: all §1.4 settings promoted into `ControlSpec`
  with `target`/`path` (+ `restart_only`); generic `apply_values_to_settings` /
  `apply_control_values_to_settings` / `values_from_settings`;
  `panel_store.py` overlay (`POST /v1/config/god?persist` → `data/panel.toml`,
  deep-merged in `load_settings`, `POST /v1/config/panel/reset` deletes it);
  label/desc i18n keys for every spec (en + pt-BR). Sidecar-only + locales.
- **P2 — next**: `mod/sensewright_mod/panel_ui.py` (model + native renderer +
  console fallback), `sw.set`/`sw.panel`, `http_client.set_god_controls`,
  boot-notification button.

### 2c. Pie menu (interaction menu) — WORKS via XmlInjector (builds `.12`→`.20`)

- **`mod/tuning/interactions/*.xml`** — 4 `ImmediateSuperInteraction`s:
  `SensewrightPanelInteraction`, `…ChatInteraction`, `…ConfirmInteraction`,
  `…HudInteraction` (module `sensewright_mod.pie_menu`).
- **`mod/tuning/snippets/sw_injector.xml`** — an **XmlInjector** snippet
  (`m="xml_injector.snippet"`, type `0x7DF2169C`) that injects the 4 interactions
  into the **Sim** (`add_interactions_to_sims`) and the Panel into **computers**
  (`add_interactions_to_objects` + tag `Func_Computer`).
- **`mod/build_package.py`** — pure-Python DBPF writer: packs the interaction XML
  (type `0xE882D22F`), the snippet (`0x7DF2169C`), and two STBLs (type `0x220557DA`)
  into `dist/Sensewright.package`. **Tuning must be zlib-compressed XML**
  (`sf = 0x80000000|compressed`, `size=uncompressed`, flag `0x00015A42`); STBL is
  uncompressed (flag `0x00010000`).
- **STBL language = top byte of the instance**: `0x00` ENG_US, `0x11` POR_BR
  (group `0`). The package ships **both** tables.
- **`mod/sensewright_mod/pie_menu.py`** — the interactions dispatch to real native
  dialogs (`panel` → panel mock, `chat` → text input → `main.run_chat`,
  `confirm` → Ok/Cancel, `hud` → toggle).
- **`mod/sensewright_mod/dialogs.py`** — native **text input** + **confirmation**
  helpers (production, reusable by the panel).
- Live: the items **appear and run**; text (pt-BR/en) resolved via the STBL fix.

---

## 3. Validated live (in-game)

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

## 4. What changed in `.23` / `.22` / `.21` / `.20`

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
   library import paths resolve, `lot51_status()` reports `available/tick=true`, the
   pulse runs off `CoreEvent.GAME_TICK`, S4CL notifications render, the pie menu
   shows the 4 items **without XmlInjector**, display names switch with `sw.lang`,
   and `sw.panel` opens.
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

## 6. Known issues / mitigations

- **Pie menu requires XmlInjector** installed in the Mods **root**. A bare
  `interaction` tuning is **not offered** by the game — it must be injected; that
  was the multi-build wall (`test()` was never called until injection).
- **STBL language** is the **top byte of the instance** (`0x00` en, `0x11` pt-BR);
  a wrong byte → blank item names. The pie-menu tables are data-driven
  (`mod/tuning/stbl.json`).
- **Locales are data-driven.** Do not hardcode `("en","pt-BR")`/`_LANG_NAMES` or
  inline translated content. Mod UI: `locales/manifest.json` + `i18n.py`. Sidecar
  content: `locales_content/manifest.json` + `content_i18n.py` (+ `lexicon.json`).
  Adding a language = drop a JSON + a manifest entry (SKILL §9).
- **`.package` HEADER**: index offset lives at `0x40` (64-bit); write `0` at
  `0x28` (matches S4S-built packages).
- **Game-clock alarms** are unreliable (validated: don't tick). Use the
  `zone.Zone.update` heartbeat. Alarm callbacks **must accept `*args`** (the game
  passes the handle) — `.13` fixed the crash.
- **Player-priority lock is per-Sim** (intended).
- **Sidecar needs the venv Python** until Phase 6; re-run the installer after a
  venv change.
- **`sw.uitest` is a dev spike** and its `input` kind is **numeric** (intentional);
  production text input is `dialogs.prompt_text`.
- **Docs encoding**: do **not** rewrite `.md`/`.json` with PowerShell
  `Set-Content -Encoding UTF8` (it double-encodes accents); use the editor tools.

---

## 7. Key files & docs

- **Roadmap**: `PLANO.md` (§11 phases, §14 v0.2, §15 v0.3).
- **UI plan**: `docs/ui_panel.md` (native panel, settings inventory, `panel.toml`).
- **Confirmed game APIs**: `docs/ts4_internals.md`.
- **Change log**: `CHANGELOG.md` (`[Unreleased]` has builds `.3`–`.23`).
- **Pie menu**: `mod/tuning/**` (incl. `stbl.json`), `mod/build_package.py`,
  `mod/sensewright_mod/pie_menu.py`, `dialogs.py`, `ui_probe.py`.
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
4. Before committing: `git init` (keep `research/ts4/` ignored) and follow the
   CHANGELOG format.

**Current TODO on the board:** validate the `.20` improvements live; then build
**P2** (the native config panel over the P1 sidecar: `panel_ui.py` + `sw.set`/
`sw.panel`, `http_client.set_god_controls`, boot-notification button). After that
the recommended order is **(a)** real **God submenu** on the computer, **(b)**
real **agent submenu** on the Sim, **(c)** custom **“Sensewrightâ€ pie category** +
**own icons** (DDS pipeline).
