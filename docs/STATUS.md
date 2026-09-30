# Sensewright â€” Status & Handoff

> Last updated: **2026-09-29**. Build in the game: **`2026-09-29.22`** (project
> renamed **Sensewright**; cheats are **`sw.*`**, artifact `Sensewright.ts4script`,
> install folder `Mods\Sensewright\` â€” see `CHANGELOG.md`).
>
> This file is the entry point for a new session. Read it, then
> `docs/ts4_internals.md`, `PLANO.md`, `docs/ui_panel.md`, and `CHANGELOG.md`.

---

## 1. Snapshot

| Item | Value |
|---|---|
| Repo root | `C:\workspace\sims-sense-8-agent` (git repo; `main` â†’ `origin` github.com/MaiconSlavieiro/sensewright) |
| In-game mod | `mod/sensewright_mod/` (Python 3.7, stdlib only) |
| Sidecar | `sidecar/sensewright_sidecar/` (Python 3.12 target; runs on 3.10.11 here) |
| Build stamp | `mod/sensewright_mod/main.py` â†’ `_BUILD = "2026-09-29.22"` |
| Installed artifact | `...\Mods\Sensewright\Sensewright.ts4script` **+ `Sensewright.package`** |
| Tuning package | `dist/Sensewright.package` â€” pie-menu interactions + XmlInjector snippet + STBL (en/pt-BR) |
| XmlInjector lib | `...\Mods\XmlInjector_Script_v4.2.ts4script` (Mods **root**; required dependency) |
| Sidecar data | `...\Mods\Sensewright\sidecar\data\` (`memory.sqlite3`, `sidecar.log`, `audit.log`, `runtime.json`, `token`) |
| Mod log | `...\Mods\Sensewright\sensewright_output.log` |
| Game install | `C:\Program Files\EA Games\The Sims 4` |
| Tests | sidecar **437**, mod **337**; ruff clean (sidecar); `py -3.7 mod/build.py` clean |

**Sidecar runs from source with the workspace venv** (no PyInstaller yet â€” Phase 6).
The mod **autoboots** it (`install-mod.ps1` writes the venv interpreter to
`sidecar/python.txt`; `config.find_python()` reads it). It auto-exits with the game.

**Build + install**

```powershell
py -3.7 mod\build.py            # -> dist\Sensewright.ts4script
python mod\build_package.py     # -> dist\Sensewright.package  (tuning/pie menu)
powershell -ExecutionPolicy Bypass -File scripts\install-mod.ps1   # copies both + sidecar
```

**Tests**

```powershell
cd sidecar; .\.venv\Scripts\python.exe -m pytest tests -q
python -m pytest mod\tests -q
```

> Decompiled EA sources live in the gitignored `research/ts4/`; cloned reference
> mods in `research/ui-refs/` (also gitignored). The XmlInjector modder docs were
> downloaded to `%TEMP%\opencode\xmlinj` (temp; re-download from
> <https://scumbumbomods.com/xml-injector> if needed).

---

## 2. What is implemented

- **Phases 1â€“5c** (skeleton â†’ God orchestration): code-complete.
- **v0.2 Â§14** (M1/M2 memory, A1â€“A3 agency, P1 personality, G1 God scoping): code-complete.
- **v0.3 Â§15**:
  - **R2 seats** (`agent/seats.py`), **R3 intents** (`agent/intents.py` + mod `GameLever`),
    **R4 cognition** (`agent/cognition.py`), **R6 God director**, **F0/F1** decompiler + `sw.probe`.
  - **R5 simâ†”sim channel** (`agent/social.py`): two seated Sims get a 1â€“2 line exchange
    (LLM + template fallback) â†’ two `speak` intents (executed by the GameLever).
  - **R7 panel** â€” dials + `sw.agents` + `sw.lang`; full native panel specified in
    `docs/ui_panel.md`.
- **Lifecycle**, **validation logging**, **collector auto-start** (`zone.Zone.update`
  heartbeat every 15 s), **buffs** (`SimInfo.Buffs._active_buffs` â†’ `Buff.buff_type.__name__`).

### 2a. In-game native UI (P0 spike â€” validated live)

`mod/sensewright_mod/ui_probe.py` + `sw.uitest <kind>` (also `all`, `probe`, `pie`):

- Dialog kinds (all `ok=True` live): `notification`, `okcancel`, `picker`,
  `picker_icons` (EA icons), `picker_text`, `dropdown`, `labeled_icons`,
  `info_columns`, `response` (`SEND_COMMAND` button), `input` (numeric), `multi`.
- **Navigable panel mock**: `sw.uitest panel` / `sw.uitest panel_home`
  (sections â†’ settings â†’ best widget per kind).
- **API map learned** (from the shipped `simulation.zip` bytecode): dialog
  **title/text/text_ok** = factories; picker **row name/description** =
  `LocalizedString`; **row tooltip** = factory; **row icon** = `ResourceKey`;
  `response_command` = namedtuple + `CommandArgType`; `UiTextInput` needs a
  `length_restriction`.

### 2b. In-game configuration panel (P1 done, P2 next)

`docs/ui_panel.md`: native dialogs only (no Flash/slider), `data/panel.toml`
overlay (never touches `config.toml`), `sw.set`/`sw.panel`.

- **P1 â€” done (build `.21`)**: all Â§1.4 settings promoted into `ControlSpec`
  with `target`/`path` (+ `restart_only`); generic `apply_values_to_settings` /
  `apply_control_values_to_settings` / `values_from_settings`;
  `panel_store.py` overlay (`POST /v1/config/god?persist` â†’ `data/panel.toml`,
  deep-merged in `load_settings`, `POST /v1/config/panel/reset` deletes it);
  label/desc i18n keys for every spec (en + pt-BR). Sidecar-only + locales.
- **P2 â€” next**: `mod/sensewright_mod/panel_ui.py` (model + native renderer +
  console fallback), `sw.set`/`sw.panel`, `http_client.set_god_controls`,
  boot-notification button.

### 2c. Pie menu (interaction menu) â€” WORKS via XmlInjector (builds `.12`â†’`.20`)

- **`mod/tuning/interactions/*.xml`** â€” 4 `ImmediateSuperInteraction`s:
  `SensewrightPanelInteraction`, `â€¦ChatInteraction`, `â€¦ConfirmInteraction`,
  `â€¦HudInteraction` (module `sensewright_mod.pie_menu`).
- **`mod/tuning/snippets/sw_injector.xml`** â€” an **XmlInjector** snippet
  (`m="xml_injector.snippet"`, type `0x7DF2169C`) that injects the 4 interactions
  into the **Sim** (`add_interactions_to_sims`) and the Panel into **computers**
  (`add_interactions_to_objects` + tag `Func_Computer`).
- **`mod/build_package.py`** â€” pure-Python DBPF writer: packs the interaction XML
  (type `0xE882D22F`), the snippet (`0x7DF2169C`), and two STBLs (type `0x220557DA`)
  into `dist/Sensewright.package`. **Tuning must be zlib-compressed XML**
  (`sf = 0x80000000|compressed`, `size=uncompressed`, flag `0x00015A42`); STBL is
  uncompressed (flag `0x00010000`).
- **STBL language = top byte of the instance**: `0x00` ENG_US, `0x11` POR_BR
  (group `0`). The package ships **both** tables.
- **`mod/sensewright_mod/pie_menu.py`** â€” the interactions dispatch to real native
  dialogs (`panel` â†’ panel mock, `chat` â†’ text input â†’ `main.run_chat`,
  `confirm` â†’ Ok/Cancel, `hud` â†’ toggle).
- **`mod/sensewright_mod/dialogs.py`** â€” native **text input** + **confirmation**
  helpers (production, reusable by the panel).
- Live: the items **appear and run**; text (pt-BR/en) resolved via the STBL fix.

---

## 3. Validated live (in-game)

- `sw.help`, `sw.status`, `sw.chat` (pt-BR reply + tool calls), `sw.probe`.
- **Lifecycle**: watchdog attached â†’ clean shutdown with the game.
- **Zone heartbeat** (build `.8`): `zone hook installed` â†’ auto-start â†’ pulse every
  ~15 s â†’ sidecar `POST /v1/autonomy/tick` + `GET /v1/autonomy/intents` 200.
- **Seats/eviction (R2)**, **Intents (R3)**.
- **P0 dialog spike** (`.9`): all 8 kinds render; `picker_icons` = 16 EA keys.
- **Pie menu** (`.13`â†’`.19`): the 4 Sim items render (category **AÃ§Ãµes**), the
  computer item injected; **Chat** opens a text input and the Sim replies;
  **Confirm** works; STBL names resolve.
- **Simâ†”sim (R5)**: `[validate] social: 1 dialogue pair(s)` and two spoken lines
  (pt-BR/en) surfaced as notifications + `say_to`.

---

## 4. What changed in `.22` / `.21` / `.20`

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

**`.20` (needs a live re-check):** a user-requested stack of improvements â€”
**code + tests done**, not yet validated live:

1. **HUD is now quiet**: the periodic status line and intent traces are **log-only**
   (`[validate] hud: â€¦`); only sidecar **state flips** (connected/lost/error) raise a
   notification. `sw.hud now` still shows the line on demand.
2. **Dialogue language**: the chat/dialogue LLM prompt now names the language
   ("Brazilian Portuguese (pt-BR)") and forbids English when `lang != en`; the mod
   `_current_lang()` retries game-locale detection (`i18n.ensure_locale`).
3. **Richer agent context in dialogues**: `social.sim_brief(...)` feeds each Sim's
   **background, personality, recent memories and who they're talking to** (plus
   `sim_id`) into the prompt.
4. **Audience**: `SocialLayer.pick_pairs` now **prefers household Sims**
   (householdâ†”household / householdâ†”guest) instead of only non-player visitors.
5. **Speaker attribution**: speech notifications are prefixed with the speaker's
   name and owned by that Sim (native portrait).

---

## 5. Pending live validation (priority order)

1. **`.22` changes** above: play a pie-menu/click interaction and confirm the log
   shows the player-priority lock arming on both sides (mod rails +
   `POST /v1/config/player-activity`), and that the agent's own pushes do **not**
   arm it; confirm `cancel_current` stops the running interaction.
2. **`.20` changes** above (HUD quiet, pt-BR dialogues, richer context, household
   pairing, speaker names).
2. **R1 native `say_to`**: `tool_executor` tries multiple `InteractionContext`
   paths; confirm the native push works (else it degrades to a notification).
3. **Buffs** (`sw.probe` â†’ `sections.buffs`), **events** (`[validate] event:`),
   **God** onboarding/backgrounds, **memory** consolidation/decay.
4. **Pie menu polish** (next features): a real **God submenu** on the computer, an
   **agent submenu** on the Sim, a **custom â€œSensewrightâ€ category**, and **our own
   icons** (SVGâ†’DDSâ†’`.package`).

---

## 6. Known issues / mitigations

- **Pie menu requires XmlInjector** installed in the Mods **root**. A bare
  `interaction` tuning is **not offered** by the game â€” it must be injected; that
  was the multi-build wall (`test()` was never called until injection).
- **STBL language** is the **top byte of the instance** (`0x00` en, `0x11` pt-BR);
  a wrong byte â†’ blank item names.
- **`.package` HEADER**: index offset lives at `0x40` (64-bit); write `0` at
  `0x28` (matches S4S-built packages).
- **Game-clock alarms** are unreliable (validated: don't tick). Use the
  `zone.Zone.update` heartbeat. Alarm callbacks **must accept `*args`** (the game
  passes the handle) â€” `.13` fixed the crash.
- **Player-priority lock is per-Sim** (intended).
- **Sidecar needs the venv Python** until Phase 6; re-run the installer after a
  venv change.
- **`sw.uitest` is a dev spike** and its `input` kind is **numeric** (intentional);
  production text input is `dialogs.prompt_text`.
- **Docs encoding**: do **not** rewrite `.md`/`.json` with PowerShell
  `Set-Content -Encoding UTF8` (it double-encodes accents); use the editor tools.

---

## 7. Key files & docs

- **Roadmap**: `PLANO.md` (Â§11 phases, Â§14 v0.2, Â§15 v0.3).
- **UI plan**: `docs/ui_panel.md` (native panel, settings inventory, `panel.toml`).
- **Confirmed game APIs**: `docs/ts4_internals.md`.
- **Change log**: `CHANGELOG.md` (`[Unreleased]` has builds `.3`â€“`.21`).
- **Pie menu**: `mod/tuning/**`, `mod/build_package.py`, `mod/sensewright_mod/pie_menu.py`,
  `dialogs.py`, `ui_probe.py`.
- **Guidelines**: `.agents/skills/sims_mod_guidelines/SKILL.md`.

---

## 8. How to continue (new session)

1. Read this file + `docs/ts4_internals.md`; confirm the sidecar is up (`GET /v1/health`).
2. Rebuild + reinstall after any code change; **restart the game** (script mods load
   only at boot).
3. Validate Â§4/Â§5 in-game; keep the loop: implement â†’ test â†’ build â†’ install â†’
   validate live â†’ document (`CHANGELOG.md` + this file) â†’ update test counts in SKILL.
4. Before committing: `git init` (keep `research/ts4/` ignored) and follow the
   CHANGELOG format.

**Current TODO on the board:** validate the `.20` improvements live; then build
**P2** (the native config panel over the P1 sidecar: `panel_ui.py` + `sw.set`/
`sw.panel`, `http_client.set_god_controls`, boot-notification button). After that
the recommended order is **(a)** real **God submenu** on the computer, **(b)**
real **agent submenu** on the Sim, **(c)** custom **â€œSensewrightâ€ pie category** +
**own icons** (DDS pipeline).
