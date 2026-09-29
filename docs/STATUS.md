# Sensewright — Status & Handoff

> Last updated: **2026-09-29**. Build in the game: **`2026-09-29.2`** (project renamed
> **Sensewright**; cheats are now **`sw.*`**, artifact `Sensewright.ts4script`, install
> folder `Mods\Sensewright\` — see `CHANGELOG.md`).
> (`.8` validated live; `.9` two fixes; `.10` `sw.hud`; `.11` autoboot finds its
> interpreter; `.12` notification diagnostics; `.13` notification rendering;
> `.14` review-pass logging; `.15` `from __future__` removed, HUD on/off/error,
> sidecar port guard; `.16` fixed the `python.txt` BOM; `.17` **reasoning**: default
> effort `none` + per-agent `reasoning_effort`, impulse retry, cleaner prompt;
> `.18` **v0.3 R5**: sim↔sim dialogue channel + probe/inventory data-quality
> fixes). `2026-09-29.1` applies the **`docs/code_review_2026-09-27.md`
> remediation** (C1, H1–H6, M1–M8, L1–L9) plus defensive **R1** native-lever
> hardening (see `CHANGELOG.md`). The sidecar watchdog no longer self-kills on the
> DRM-protected game.
> This file is the entry point for a new session. Read it, then
> `docs/ts4_internals.md`, `PLANO.md`, and `CHANGELOG.md` as needed.

---

## 1. Snapshot

| Item | Value |
|---|---|
| Repo root | `C:\workspace\sims-sense-8-agent` (git repo; `main` → `origin` github.com/MaiconSlavieiro/sensewright) |
| In-game mod | `mod/sensewright_mod/` (Python 3.7, stdlib only) |
| Sidecar | `sidecar/sensewright_sidecar/` (Python 3.12 target; runs on 3.10.11 here) |
| Build stamp | `mod/sensewright_mod/main.py` → `_BUILD = "2026-09-29.2"` |
| Installed artifact | `C:\Users\maico\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\Sensewright\Sensewright.ts4script` |
| Sidecar data | `...\Mods\Sensewright\sidecar\data\` (`memory.sqlite3`, `sidecar.log`, `audit.log`, `runtime.json`, `token`) |
| Mod log | `...\Mods\Sensewright\sensewright_output.log` |
| Game install | `C:\Program Files\EA Games\The Sims 4` |
| Tests | sidecar **406**, mod **305**; ruff clean; `py -3.7 mod/build.py` clean |

**Sidecar runs from source with the workspace venv** (no PyInstaller yet — Phase 6).
The mod **autoboots** it: `install-mod.ps1` writes the venv interpreter to
`sidecar/python.txt` and `config.find_python()` reads it. To start/restart it by
hand:

```powershell
& "C:\workspace\sims-sense-8-agent\sidecar\.venv\Scripts\python.exe" -m sensewright_sidecar
# working directory: C:\Users\maico\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\Sensewright\sidecar
```

It auto-exits when The Sims 4 closes (game-process watchdog, validated live).

**Common commands**

```powershell
# Build + install the mod
python mod\build.py
powershell -ExecutionPolicy Bypass -File scripts\install-mod.ps1

# Tests
cd sidecar; .\.venv\Scripts\python.exe -m pytest tests -q; .\.venv\Scripts\python.exe -m ruff check sensewright_sidecar tests
python -m pytest mod\tests -q

# Decompile the shipped scripts (needs unpyc37; decompyle3 also works)
powershell -ExecutionPolicy Bypass -File scripts\decompile-scripts.ps1 -VerifyOnly
```

> Decompiled EA sources live in the gitignored `research/ts4/`. **Run `git init`
> before committing anything** so they are never committed.

---

## 2. What is implemented

- **Phases 1–5c** (skeleton → God orchestration): code-complete.
- **v0.2 §14** (M1/M2 memory, A1–A3 agency, P1 personality, G1 God scoping): code-complete.
- **v0.3 §15**:
  - **R2 seats** — `agent/seats.py` (`SeatManager`), `/v1/agency/seats`, `agent_seats`/`[agents.layers]`/`[runtime]`.
  - **R3 intents** — `agent/intents.py` (`Intent`/`IntentBus`), `/v1/autonomy/intents` (+ directives alias), `initiative.py` emits intents, `GameLever` in the mod (`tool_executor.execute_intent`).
  - **R4 cognition** — `agent/cognition.py` (daily plan/goals at sleep), wired into sleep consolidation.
  - **R5 sim↔sim channel** — `agent/social.py` (`SocialLayer`/`Dialogue`): picks two
    seated non-player Sims, renders a 1–2 line exchange (LLM + template fallback),
    stores two `speak` intents (executed by the GameLever) and remembers it for
    both; `[agents.social]` cadence + cooldown. Wire: `AutonomyTickResponse.social`.
  - **R6 God director** — verified: the orchestrator only targets non-player Sims
    (`god/orchestrator.py`) and broadcasts world events to witnesses.
  - **R7 panel** — dials + `sw.agents` roster/frequency fallback + `sw.lang`
    selector done; the full **native-dialog panel** is specified in
    `docs/ui_panel.md` (no Flash/slider).
  - **F0** — `scripts/decompile-scripts.ps1`.
  - **F1** — `mod/sensewright_mod/probe.py` + `sw.probe` cheat.
- **Lifecycle** — `sidecar/.../lifecycle.py` + `/v1/lifecycle/attach`; exits with the game.
- **Validation logging** — `[validate]` lines (mod) and semantic `logger.info` (sidecar).
- **Collector auto-start + heartbeat** — `state_collector.install_zone_hook()` wraps
  `zone.Zone.update`; starts once the active Sim is instanced and drives pulse/pull
  every 15 s (`ZONE_PULSE_INTERVAL_SECONDS`).
- **Buffs** — `SimInfo.Buffs._active_buffs` → `Buff.buff_type.__name__` (sleep detection).
- **Debug HUD** — `hud.py` + `sw.hud on|off|now|status`: periodic in-game status
  line (`sidecar ON/OFF | HB #n | N sims | pulled n | ok n/total`) and a trace per
  executed intent. **Notifications fixed** (`chat_ui`): real
  `LocalizationHelperTuning.get_raw_text` strings instead of the invalid
  `urgent=`/`TunableLocalizedStringFactory` usage, so messages render in-game.

---

## 2b. In-game configuration panel (planned — see `docs/ui_panel.md`)

Decision (2026-09-29): the settings UI lives **inside the game** and uses TS4's
**native dialogs only** — picker/list rows, paginated responses, native numeric
input and multi-select. **No Flash/GFX and no drag sliders** (sliders are not
scriptable in TS4), no external tools; a 0..1 value is a row of stepped choices
or a numeric input. Entry = boot-notification button + `sw.panel` cheat
(pie-menu category optional). Persistence via a `data/panel.toml` overlay that
never touches the user's `config.toml`. Roadmap: **P1** model + persistence →
**P2** native panel + `sw.set` → **P2b** pie-menu entry (optional) → **P3**
validation. A short in-game **P0 spike** (`sw.uitest`) confirms the dialog skins
before P2 ships.

---

## 3. Validated live (in-game)

- `sw.help`, `sw.status` (providers up), `sw.chat` (pt-BR reply + tool calls →
  `/v1/tools/result`), `sw.probe` (full autonomy snapshot + module map).
- **Lifecycle**: `game watchdog attached to pid …` then `game process gone` → clean shutdown.
- **Zone heartbeat (build `.8`)** — during normal play (no commands):
  `zone hook installed` → auto-start with `owner=object_sim` →
  `census: 12 sim(s), 9 household(s)` → `[validate] zone-pulse: heartbeat` every
  ~15 s (26 beats) → sidecar `POST /v1/autonomy/tick` + `GET /v1/autonomy/intents` 200.
- **Seats/eviction (R2)** — `seats: 12, used: …, household: 5, visitors: …` with
  evictions as Sims leave.
- **Intents (R3)** — `impulse … intents=['speak']` → `intent(s) stored` →
  `pull: 1 intent(s)` → `intent … kind=speak name=spontaneous_line -> ok=True`.
- Autonomy **module map** importability captured (`docs/ts4_internals.md`).

---

## 4. Pending live validation (priority order)

> Items #1 and #2 (heartbeat + intents) are **validated in build `.8`** (see §3).
> Now confirm the `.9` fixes and the remaining layers.
>
> **Fast path on `.11`:** the sidecar now autoboots (the installer wrote
> `sidecar/python.txt` with the venv interpreter). Open the game, run `sw.hud on`,
> and watch for the periodic `Sensewright ● sidecar ON | HB #n | N sims …`
> notifications. If they appear, the loop is alive and notifications render; type
> `sw.hud now`/`sw.hud status` anytime. If you see `sidecar OFF`, autoboot failed —
> check `sidecar/python.txt` and `sidecar.log`.

1. **Debug HUD + notifications (build `.10`).** `sw.hud on` → periodic in-game
   status line; confirm `notify.*`/`notify.social.speech` also render (not just
   the cheat console).
2. **`.9` speak fallback (re-run).** Repeat a session and confirm a targeted
   `speak`/`say_to` intent now logs `ok=True` with a text line (not
   `err=not_implemented`), and `bias_interaction` ack (`applied=false`), plus the
   impulse log no longer stores meta thoughts ("the user …").
3. **Buffs**: `sw.probe` → `sections.buffs` populated; sleeping buffs drive `sleeping: true`.
4. **Events delivered**: `[validate] event: <type>` on buffs/relationships/social.
5. **God**: zeitgeist onboarding on first load; backgrounds pipeline cadence.
6. **Memory cadence**: consolidation after the idle window; decay/deja-vu over long play.
7. **UI**: God onboarding dialogs + the native **configuration panel**
   (`sw.panel`; see `docs/ui_panel.md`) once P1/P2 land.
8. **Native interaction APIs (R1)**: `tool_executor` now tries multiple
   `InteractionContext` import paths/signatures and candidate social affordances
   (best-effort), but `say_to` still needs live confirmation that the push
   succeeds in-game (otherwise it degrades to a notification). Resolve the real
   social affordance + `push_super_affordance`/`move_to`/`cancel_all` (`sw.probe`).
9. **R5 sim↔sim (build `.18`)**: with two seated non-player Sims on the lot, watch
   the log for `[validate] social: N dialogue pair(s)` and the sidecar's
   `social dialogue(s)`. Confirm the two lines surface (native `say_to` or the
   `notify.social.speech` fallback) and that the relationship moves in-game. If
   pairs never form, check that both Sims are non-player, awake and in seats
   (`sw.agents`) and that `[agents.layers] social = true`.

---

## 5. Known issues / mitigations

- **Player-priority lock is per-Sim** (build `2026-09-29.1`): a player `ai.*`
  command arms the 10 s lock on the player's **active** Sim only, so the agent may
  still act on other seated Sims. Intended — the lock stops the agent from fighting
  the player over the *same* Sim.
- **Code review resolved** (`docs/code_review_2026-09-27.md`): C1/H1–H6/M1–M8/L1–L9
  applied; M9 (split the collector), L10 (TOML parser) and L3 (duplicate refs)
  deferred as documented in `CHANGELOG.md`.
- **Game-clock alarms are unreliable** (owner `object_sim` and `Zone` both failed to fire
  live). Mitigated by the `zone.Zone.update` heartbeat. Keep alarms as a bonus only.
- **Starting the collector too early** gives `owner=Zone` and a `0`-Sim census. The hook
  waits for the active Sim instance.
- **OpenRouter** first model `nvidia/nemotron-3.5-lightning:free` often fails then falls
  through to the next model (works, but slower).
- **Sidecar needs the venv Python** until Phase 6 (PyInstaller). Autoboot now finds
  it via `sidecar/python.txt` (written by `install-mod.ps1`); if that file is
  missing/stale the spawn falls back to PATH Python, which lacks the deps — start
  manually (`sw.start` won't help without the venv). Re-run the installer after a
  venv change.
- **`sw.probe`** now resolves `full_name` (via the tuning/`LocalizedString` path)
  and a real career name; `get_inventory` is implemented best-effort (returns an
  empty list when the inventory component is unavailable).
- **R5** uses a deterministic template dialogue in native (0-key) mode, so
  conversations appear even without a provider (one pair per ~3 min by default).
- **Git**: initialized; `main` → `origin` (`github.com/MaiconSlavieiro/sensewright`).
  `research/ts4/` and `research/ui-refs/` (cloned reference mods) are gitignored.

---

## 6. Key files & docs

- **Plan / roadmap**: `PLANO.md` (§11 phases, §14 v0.2, §15 v0.3, §2.3 checklist).
- **In-game UI plan**: `docs/ui_panel.md` (native-dialog panel, full settings
  inventory, `panel.toml` persistence overlay, `sw.set`/`sw.panel`).
- **Change log**: `CHANGELOG.md` ([Unreleased] has the v0.3 + live-validation entries).
- **Confirmed game APIs**: `docs/ts4_internals.md`.
- **Agent guidelines**: `.agents/skills/sims_mod_guidelines/SKILL.md` (module map, gotchas,
  test counts, conventions).
- **Decompiled stubs**: `research/ts4/` (gitignored).

---

## 7. How to continue (new session)

1. Read this file + `docs/ts4_internals.md`.
2. Confirm the sidecar is up (`GET /v1/health`) or start it (command in §1).
3. Run the **#1 check** above (play → read logs). If the heartbeat appears, proceed to
   #2–#4; if not, investigate `install_zone_hook` (the `zone` hook may need a different
   method on this patch).
4. Keep the loop: implement → test → build → install → validate live → document
   (`CHANGELOG.md` + this file). Update the test counts in the skill.
5. Before any commit: `git init` (so `research/ts4/` stays ignored) and follow the
   CHANGELOG format.

**Current TODO on the board:** run the current build with the sidecar up and
`sw.hud on` to confirm the HUD/notifications render → re-check the speak fallback
+ clean impulse thoughts → buffs/events live → **R5 sim↔sim** (`[validate]
social:` line, two lines surface, relationship moves) → resolve a real social
affordance for native `say_to` (R1) → build the in-game **configuration panel**
(`docs/ui_panel.md`: P1 model+persistence, P2 native panel + `sw.set`).
