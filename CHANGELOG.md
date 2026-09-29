# Changelog

All notable changes to **Sensewright** are documented in this file.

- Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
- Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
- Conventions: code, docs and code comments are in **English**; player-facing text
  goes through the locale system (`en` default, `pt-BR` supported).
- The phase names/numbers match `PLANO.md` §11.

---

## [Unreleased] — Phases 2, 2b, 3, 4, 5a, 5b, 5c + v0.2 §14: Directives, Census, Agents, Evolution, God foundation, backgrounds, orchestration & autonomous Sim agents

### Changed — renamed the project to **Sensewright** (build `2026-09-29.2`)
Full rename from `SimsSense` to **Sensewright** (descriptive subtitle: *for The Sims 4*;
no "Sims" in technical identifiers). A git baseline was committed **before** the rename so
it stays revertible.
- **Packages:** `mod/simssense_mod` → `mod/sensewright_mod`; `sidecar/sims_sense_sidecar` →
  `sidecar/sensewright_sidecar` (incl. `pyproject` `name`, console script and wheel package).
- **Cheats (breaking):** every `ai.*` → **`sw.*`** (`sw.help`, `sw.chat`, `sw.hey`, `sw.status`,
  `sw.reset`, `sw.forget`, `sw.autonomy`, `sw.lang`, `sw.hud`, `sw.uitest`, `sw.god`,
  `sw.zeitgeist`, `sw.profile`, `sw.evolve`, `sw.agents`, `sw.probe`, `sw.start`), including the
  `cmd.help.body` text in `en` + `pt-BR`.
- **Wire/security:** auth header `X-SimsSense-Token` → `X-Sensewright-Token`; env vars
  `SIMS_SENSE_*` → `SENSEWRIGHT_*` (`HOME`, `CONFIG`, `LANG`, `DEBUG`, `VALIDATION`,
  `GAME_PID`, `PYTHON`, `TS4_STUBS`).
- **Artifacts/paths:** `Sensewright.ts4script`, `Sensewright-sidecar.exe`,
  `Mods\Sensewright\`, `sensewright.toml`, `sensewright_output.log`, sidecar window/log titles.
- **Docs/scripts:** `PLANO.md`, `CHANGELOG.md`, `docs/*`, `SKILL.md`, `Makefile`,
  `scripts/*.ps1`, `config.example.toml` updated.
- **Repo:** `git init` + baseline commit; remote `https://github.com/MaiconSlavieiro/sensewright`.
- Note: installs now land in `Mods\Sensewright\` — delete the old `Mods\SimsSense\` folder so
  the game does not load both.
- **Tests:** sidecar **406**, mod **305**; ruff + `py -3.7 mod/build.py` clean.

### Changed — code-review remediation + R1 hardening (build `2026-09-29.1`)
Applied the full correction plan from `docs/code_review_2026-09-27.md` on the in-game mod
(sidecar unchanged), plus defensive hardening of the R1 native levers and a shared
best-effort guard.

**Security / correctness**
- **C1 (critical) — the player-priority lock is now armed.** Every player-issued `ai.*`
  command calls the new `tool_executor.record_player_activity()` (via
  `main._note_player_active`), so `DirectiveRails` actually blocks agent intents on the
  player's Sim for the lock window (previously it was only ever exercised by tests). The
  lock stays **per-Sim** by design — the agent may still act on other seated Sims.
- **H6 — strict tool-argument types.** `tool_executor` coerces ids via `_as_int`
  (`int` / numeric `str` / integral `float`; `bool` and non-numeric → `invalid_argument`)
  and requires a real `tone` `str`, so a malformed payload is reported instead of silently
  falling back to a default.

**Robustness / observability**
- **H5 — one shared guard.** `debug_log.safe_getattr`/`safe_call` (both log the real
  exception once) replace the duplicate non-logging copies in `events.py`, `god_ui.py` and
  `tool_executor.py` (module aliases kept for compatibility).
- **H1–H4 — no more silent swallows.** Event/alarm registration (`events`), the collector's
  HTTP sends (`_send`, `send_autonomy_tick`, `_pull_intents`, `send_census`,
  `notify_player_activity`) and the UI/config/probe paths now `log_exception`/`debug_log`
  instead of `pass`.
- **M3 — the alarm owner must be a live, ticking Sim instance.** `events._resolve_alarm_owner`
  no longer falls back to zone/household/client (which registered handles that never fired);
  it returns `None` and the `zone.Zone.update` hook re-arms. `_ensure_alarm` now logs when an
  alarm is deferred.
- **M4 — every `add_alarm` attempt is logged** (was only the last one).
- **M5 — sleep detection uses the exact tuning id only** (`buff_type.__name__`), never a
  localized display name.
- **M1/M2 — `health()` no longer sends the auth header** (`_make_request(no_auth=True)`), and
  `json.dumps` now runs inside the request `try` so a serialization error cannot escape before
  handling.

**UI / i18n**
- **M6 — hardcoded UI strings localized:** `god.zeitgeist.hint`, `god.background.hint`,
  `notify.app_title`, `error.title` (en + pt-BR). **M7** the HUD passes canonical
  `ON`/`OFF`/`ERROR` tokens to `hud.line`. **M8** `i18n.t` is robust to non-string
  placeholders (`AttributeError` + `str()` coercion).

**R1 (native levers, best-effort)**
- `_build_interaction_context` tries multiple real import paths/signatures
  (`interactions.context` / `sims4.interactions.context`; `(source, priority)`,
  `(source, source_priority, run_priority)`, `(source,)`) and never raises; `tool_say_to`
  tries the tone-mapped name and candidate base-game social affordances. Still needs live
  validation before `say_to` can push natively in-game.

**LOW**
- Removed the dead `StateCollector._register_handlers`; `rails.NEVER_TOOLS` no longer lists
  the non-existent `shell`/`http`; `note_executed` failures are logged; `probe` renders via
  the payload sanitizer (no `default=str` masking); `print` → `debug_log`; `cmd_zeitgeist
  auto` forwards `lang`; `sw.autonomy` persists the level to `sensewright.toml` and, with no
  argument, re-applies it (`read_autonomy_level`); the sidecar already persists the
  per-Sim level in SQLite.
- **Deferred (documented):** M9 (split the 1.5k-line `state_collector`), L10 (harden the
  hand-rolled TOML parser), L3 (duplicate Sim-ref helpers).

**Tests.** mod 241 → **305** (C1 wiring, H6 coercion/validation, H1–H3 logging, M3
alarm-owner, M4 attempts, M5 exact tuning id, M6/M7/M8 i18n, H5 shared-guard identity, R1
import paths, `write_autonomy_level`); sidecar **406** unchanged. ruff + `py -3.7
mod/build.py` clean. Build `2026-09-29.1`.

### Added — v0.3 R5: sim↔sim dialogue channel + R6/R7 status (build `.18`)
Two seated, non-player agent Sims now hold a short (1–2 line) conversation. The
exchange reaches the game through the normal intent pull (each line is a
`speak`/`say_to` intent) and is remembered by both Sims, so the relationship
keeps moving natively when the social affordance resolves (notification fallback
otherwise, per the locked decision §15.1 #5).
- **Sidecar — `agent/social.py` (`SocialLayer`, `Dialogue`).** Picks disjoint
  pairs of awake, seated, **non-player** Sims (per-pair cooldown, `max_pairs`
  per pulse), builds a `PairContext` (both profiles + relationship hint) and
  renders the dialogue with the LLM or a deterministic `template_dialogue`
  fallback. `Dialogue.intents()` yields one `speak` intent per line
  (`say_to`-compatible: `params.message` for the native push, `params.text` for
  the notification fallback).
- **Sidecar — agency/graph.** `Agency` owns the `SocialLayer`
  (`set_context_forge`), plans dialogues inside `ingest_tick` (returned as
  `social` + `social_intents`) and exposes it in `snapshot()`;
  `graph._store_social` passes the intents through the rails, stores them on the
  IntentBus and writes a `social` memory event for both participants.
- **Wire/config.** `AutonomyTickResponse.social` (`SocialDialogue`/`SocialLine`);
  new `[agents.social]` (`max_pairs_per_tick`, `pair_cooldown_seconds`,
  `line_max_tokens`); the `[agents.layers] social` toggle already existed and now
  actually gates the layer.
- **Mod.** The zone pulse logs `[validate] social: N dialogue pair(s)`; the
  resulting `speak` intents flow through the existing GameLever (`say_to`, with a
  `notify.social.speech` fallback). No new locale keys were needed.
- **R6/R7 (verified code-complete).** The God orchestrator already targets only
  non-player Sims and broadcasts world events to witnesses; the agent-roster
  panel is the `sw.agents` text fallback plus the `ControlSpec` dials and
  `sw.lang`. Only the optional native visual panel remains gated.
- **Data-quality nits (mod).** `sw.probe` now reports a real `full_name` and a
  career name (was `""` / numeric); `get_inventory` is implemented best-effort
  instead of returning `not_implemented`.
- **Tests.** sidecar 356 → **406** (`agent/social.py` unit tests + Agency/graph
  integration); mod 225 → **241** (`full_name`/career-name/inventory). ruff clean;
  `py -3.7 mod/build.py` produces the `.ts4script`.

### Fixed/Added — reasoning handling + per-agent reasoning effort (build `.17`)
Root cause (confirmed by a live OpenRouter probe, outside the game): the free
Nemotron chain is a reasoning model. With the default effort it spent ~580 hidden
reasoning tokens per impulse, hit `finish_reason=length`, and **dumped its
"thinking process" into `content`** — which the impulse parser discarded, so every
impulse fell back (`used_llm=False`, no intents). With `reasoning.effort="none"`
the chain returns `reasoning_tokens=0` and a clean line or tool call.
- **Config.** New `[llm] reasoning_effort` (default **none**: none|minimal|low|
  medium|high) and a per-agent `[agents.initiative] reasoning_effort` override
  (None inherits). New `ProviderConfig.supports_reasoning` gates forwarding (so a
  provider that would 400 is untouched).
- **LLM layer.** `complete()` accepts `reasoning_effort` through
  `LLMProvider`/`ProviderChain`/`ProviderRegistry`; the OpenAI-compatible provider
  forwards `reasoning.effort` per request; Gemini accepts and ignores it (its
  thinking is already disabled).
- **Impulse.** `build_impulse` retries once when a response yields no usable
  line/tool call (reasoning-trace or empty), and forwards the configured effort.
- **God control.** New `reasoning_effort` select in the `ControlSpec` registry
  (`GET /v1/god/controls`, `POST /v1/config/god`); maps to
  `settings.agents.initiative.reasoning_effort`.
- **Prompt/cleanup (earlier pass).** `_clean_thought` strips a leading
  "Here's a thought:" prefix and drops reasoning-trace/meta content (en + pt-BR);
  `IMPULSE_MAX_TOKENS` 250 → 600; the impulse prompt forbids preamble/headings.
- Verified live: `build_impulse` now returns `used_llm=True` with an in-character
  pt-BR line.
- **Tests.** sidecar 341 → **356**; mod **225**; ruff + compileall clean.

### Fixed — autoboot ignored `python.txt` because of a UTF-8 BOM (build `.16`)
The spawn log showed `spawning sidecar: ['...\Python310\python.EXE', …]` — i.e.
the mod fell back to the PATH Python (no deps), so the sidecar never started and
the HUD stayed `DESLIGADO`. Root cause: `install-mod.ps1` wrote `sidecar/python.txt`
with `Set-Content -Encoding UTF8`, which prepends a UTF-8 **BOM** on PowerShell
5.1; `read_interpreter_hint` read the line as `"\ufeffC:\…"`, the existence check
failed, and the hint was discarded.
- `read_interpreter_hint` now reads with `utf-8-sig` (strips a BOM) **and**
  `lstrip("\ufeff")`.
- `install-mod.ps1` writes the hint with .NET `UTF8Encoding($false)` (no BOM).
- **Tests.** mod 224 → **225** (BOM stripping).
- Verified end-to-end: the venv interpreter starts the sidecar from the installed
  folder and `GET /v1/health` returns 200.

### Changed — review/adviser follow-through (build `.15`)
- **Mod — removed `from __future__ import annotations` everywhere.** Applied the
  skill's hard rule across all 13 mod modules (`__init__`, `config`, `chat_ui`,
  `state_collector`, `tool_executor`, …). Harmless before (only `main.py` defines
  commands) but a landmine; a regression test now fails if it returns
  (`mod/tests/test_python37_compat.py`).
- **Mod — HUD tri-state.** `hud` now distinguishes **on / off / error**; when the
  tick and pull both fail, `pulse_and_pull` probes `/v1/health` so a reachable
  sidecar with a failing endpoint shows `⚠ sidecar ERROR` instead of a false
  "OFF". New `hud.line.error`/`hud.sidecar.*`/`hud.error` keys in `en` + `pt-BR`.
- **Sidecar — port-conflict guard (`__main__._port_in_use`).** A second sidecar
  on the same port now logs and exits cleanly instead of an opaque uvicorn bind
  crash (the mod always reuses the instance already up).
- **Mod — observability.** `_post_tool_result` logs a debug line when a result
  cannot be posted (sidecar unreachable); `_push_affordance` logs when the
  interaction context could not be built.
- **Tests.** sidecar 339 → **341** (`_port_in_use`); mod 218 → **224** (future-
  import guard, HUD tri-state, `_sidecar_state`).

### Changed — review/adviser pass (build `.14`)
A code review + architecture advisory pass on this session's changes. Applied:
- **No more silent swallows (mod).** `StateCollector._emit` now logs event-send
  failures (`log_exception`), and `pulse_and_pull` logs a failing
  `hud.note_heartbeat` instead of a bare `except: pass` — so the validation log
  always shows why a pulse/event produced nothing.
- **Spawn visibility (mod).** `main._spawn_sidecar` logs
  `spawning sidecar: <cmd> (cwd=…, game_pid=…)` so `sensewright_output.log` records
  exactly what was launched and with which PID.
- **Impulse marker robustness (sidecar).** `_META_MARKERS` covers `I am Sim …`
  with `,`/`.`/space endings (kept the trailing space to avoid matching
  "I am simply…").
- **Tests unchanged:** sidecar **339**, mod **218**; ruff + compileall clean.
- **Advisory (not blockers, tracked):** `from __future__ import annotations` is
  present across the mod modules (pre-existing; harmless because only `main.py`
  defines `@sims4.commands.Command`, but it violates the skill's blanket rule —
  candidate for a dedicated cleanup); HUD treats any tick/pull `None` as "sidecar
  down" (could be a transient error); watchdog has no PID-reuse/process-name
  verification; no port-conflict retry.

### Fixed — sidecar watchdog no longer kills itself on the protected game (sidecar)
The HUD logged `sidecar DESLIGADO` because the sidecar started and then shut
itself down ~6 s later with `game process gone` — while the game was running.
Root cause: `_windows_pid_alive` treated any `OpenProcess` failure as "process
dead". The Sims 4 is DRM-protected, so `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`
returns **ERROR_ACCESS_DENIED (5)** even though the game is alive, so the
watchdog false-triggered on every session.
- `_windows_pid_alive` now reads `GetLastError`: only **ERROR_INVALID_PARAMETER
  (87)** (no such PID) counts as dead; access-denied/unknown counts as alive
  (never kill on doubt). `GetExitCodeProcess` failure likewise counts as alive.
- Startup now logs `game watchdog armed: pid=… watch_name=… name=…` so the
  watched PID is visible in `sidecar.log`.
- **Tests.** sidecar 338 → **339** (access-denied counts as alive).

### Fixed — notifications now render (LocalizedString factory) (build `.13`)
`sw.uitest` pinpointed the failure: `TypeError: 'LocalizedString' object is not
callable` at `ui_dialog._build_localized_string_msg` (`string(*tokens)`). The
dialog resolves `text`/`title` by **calling** them with localization tokens, but
`LocalizationHelperTuning.get_raw_text(...)` returns a `LocalizedString`, not a
callable. `chat_ui._build_dialog` now passes small factories
(`lambda *a, **k: loc`) so the dialog can call them. This is the real cause of
"no UI appears" for the HUD, `notify.*` and `notify.social.speech`.
- The earlier `sw.hud on` console-only result was this fallback; the HUD loop
  itself was already running (`hud: … HB #3 … 6 sims` in the log).
- **Tests.** mod **218** (unchanged; diagnostics test covers the failure path).

### Added — notification diagnostics + HUD log trace (build `.12`)
`sw.hud on` still showed only the console ack, so the in-game UI path needs
pinpointing.
- **`sw.uitest` cheat.** New `chat_ui.notification_diagnostics()` reports the
  exact failing layer of the dialog path (`build` vs `show_dialog`) and the error
  string; `sw.uitest` prints `ok=… | layer=… | error=…` to the cheat console.
  `show_notification` now logs the real exception to `sensewright_output.log`.
- **HUD log trace.** Every HUD line is mirrored to the log as `hud: …`, so the
  loop's liveness is provable from `sensewright_output.log` even if notifications
  do not render.
- **Tests.** mod 217 → **218** (`notification_diagnostics`).

### Fixed — sidecar autoboot finds its interpreter (build `.11`)
The sidecar is supposed to start by itself (`main.autoboot()` → `find_python()`),
but on the dev machine it silently spawned the PATH Python 3.10, which has none
of the sidecar deps (`fastapi`/`httpx`/`pydantic`) — those live in the workspace
`.venv`. So the sidecar never came up unless started by hand.
- **`install-mod.ps1` records the interpreter.** After copying, it resolves the
  dev venv (`sidecar\.venv\Scripts\python.exe`, else PATH `python`) and writes
  it to `Mods/Sensewright/sidecar/python.txt`.
- **`config.find_python()` reads it.** New `read_interpreter_hint()` is consulted
  after the env override and the sidecar's own `.venv`, before PATH — so autoboot
  spawns an interpreter that actually has the deps. Missing/stale paths are
  ignored (falls through to PATH).
- **Tests.** mod 214 → **217** (`read_interpreter_hint`, `find_python` hint).

### Added — in-game debug HUD (`sw.hud`) + working notifications (build `.10`)
- **Debug HUD (`mod/sensewright_mod/hud.py`).** The mod runs behind the scenes, so
  a player could not tell whether the loop was alive. New opt-in overlay:
  `sw.hud on|off|now|status` (empty toggles). While on, each zone heartbeat emits
  a compact notification — `sidecar ON/OFF | HB #n | N sims | pulled n | ok n/total`
  — and every executed intent adds a one-line trace (`▶ kind name → status`);
  sidecar connect/loss flips announce immediately. Counters keep running while
  off, so `sw.hud now` shows a reading at any time. New `cmd.hud.*`/`hud.*` keys in
  `en` + `pt-BR`; `sw.hud` added to `sw.help`.
- **Fixed — notifications now actually render in-game (`chat_ui.show_notification`).**
  The dialog call passed `urgent=` (not a notification tunable) and wrapped the
  text in `TunableLocalizedStringFactory` (a tunable type, not a runtime string),
  so `UiDialogNotification` raised and every message silently fell back to the
  cheat console (invisible unless the console was open). It now builds real
  localized strings with `LocalizationHelperTuning.get_raw_text(...)` (confirmed
  against the shipped `sims4/localization`), resolves the owner (live Sim →
  SimInfo → active client) and calls
  `UiDialogNotification.TunableFactory().default(owner, title=…, text=…)`. This
  makes the HUD, the `notify.*` messages and `notify.social.speech` visible.
- **Wired through the heartbeat (`state_collector`).** New `pulse_and_pull()` runs
  the pulse + intent pull once and feeds `hud.note_heartbeat`; both the zone hook
  and the event safety net call it. `pull_and_execute_directives` feeds
  `hud.note_intent`, and `send_autonomy_tick` records the last pulse size.
- **Docs.** `docs/ts4_internals.md` records the validated notification API.
- **Tests.** mod 203 → **214** (`test_hud.py`, `test_chat_ui.py`).

### Validated — build `2026-09-27.8` live (zone heartbeat + R2/R3)
The `.8` session validated the core loop during **normal play, with no commands**:
- **Zone heartbeat (the #1 board item)** — `install_zone_hook` started only after
  the active Sim was instanced, giving `owner=object_sim` and a non-empty census:
  `[validate] census: 12 sim(s), 9 household(s) scope=active_zone`,
  `[validate] zone-pulse: heartbeat` every ~15 s (26 beats),
  `[validate] pulse: N sim(s) zone=1488584711`, and the sidecar logging
  `POST /v1/autonomy/tick` + `GET /v1/autonomy/intents` 200 at the same cadence.
- **Seats/eviction (R2)** — `seats: 12, used: …, household: 5, visitors: …` with
  `evicted: […]` as Sims left the lot.
- **Intents (R3)** — sidecar `impulse … intents=['speak']` → `intent(s) stored`
  → mod `pull: 1 intent(s)` → `intent … kind=speak name=spontaneous_line -> ok=True`.
- **LLM** — OpenRouter 200 across impulses.
Found while validating (fixed below): targeted `say_to` intents failed with
`not_implemented`, and weak prompt framing produced meta/empty impulse thoughts.

### Fixed — speak intents never drop silently + impulse thought quality (build `.9`)
- **Mod — `speak` lever fallback (`tool_executor.py`).** A targeted `speak`
  intent (`say_to`) that cannot be pushed natively now degrades to a surfaced
  `spontaneous_line` notification (`audience` = target id, `native_error`
  recorded) instead of returning `not_implemented` and vanishing.
- **Mod — native push context (`tool_executor._push_affordance`).** Now prefers
  the validated `sim.push_super_affordance(affordance, target, context)` entry
  point and builds a real `InteractionContext(SOURCE_SCRIPT, High)` (passing
  `None` made the push fail); the interaction-queue methods remain a fallback.
- **Mod — `bias_interaction` acknowledgement.** When the native affordance is
  unresolved the intent is acknowledged (`applied=false`, `native_error`) rather
  than reported as a failure.
- **Sidecar — impulse prompt (`agent/initiative.py`).** Rewritten to be strictly
  in-character / first-person and to forbid task/scene narration; added
  `_clean_thought`, which drops meta output ("The user gives a situation …"),
  punctuation-only fragments (`)`, `.`) and empty text so the deterministic
  impulse is used instead of storing junk.
- **Tests.** sidecar 335 → **338** (meta/punctuation thought discard, prompt
  framing); mod 201 → **203** (targeted speak fallback, bias ack).

### Added — v0.3 R2/R3: agent seats + intent bus (inhabitation pivot)
- **Seats (`agent/seats.py`).** New `SeatManager`: a runtime pool of `agent_seats`
  assigned by priority (active household → instanced visitors), rebuilt from the
  census/zone pulse (`sync`). A Sim that leaves the lot frees its seat
  (eviction), while memory persists without a seat. This is L2 of the §15.3
  framework.
- **Intents (`agent/intents.py`).** New `Intent` shape + `IntentBus`: the v0.2
  command palette becomes intent-first (`bias_interaction`, `speak`, `set_mood`,
  `approach`, `prefer_target`, `set_goal`, `remember`, `forget`) with a gated
  `command` escape hatch. `intent_from_directive` maps the legacy palette so the
  old `/v1/autonomy/directives` round-trip keeps working.
- **Agency (`agent/agency.py`).** `Agency` now owns the `SeatManager` and the
  `IntentBus` (replacing the pending-directive store) and honors the new dials:
  idle impulses are gated by the seat + per-Sim `impulse_frequency` (0 =
  sleep-only) and `reactions_enabled`; `snapshot()` exposes seats and intents.
- **Initiative (`agent/initiative.py`).** `build_impulse` emits `intents`
  (derived from the model's tool calls) alongside the legacy `directives`.
- **Graph (`agent/graph.py`).** `_gate_directives` → `_gate_intents` (rails +
  coordinator arbitration on intents); new `ContextForge` assembles the per-Sim
  context once per "think"; new `pull_intents`, `seats_roster`, `assign_seat`,
  `update_agents`; `ingest_census`/`ingest_tick` seed the seats; `/v1/status`
  surfaces the seat pool.
- **Wire (`schemas.py`, `routers/autonomy.py`).** New `SeatInfo`, `RosterResponse`,
  `SeatAssignRequest`, `IntentItem`, `IntentResponse`; endpoints
  `GET /v1/agency/seats`, `POST /v1/agency/seats`, `GET /v1/autonomy/intents`
  (`/v1/autonomy/directives` kept as the transitional alias).
- **Config.** `[agents] agent_seats` (overrides legacy `max_active`),
  `[agents.initiative] impulse_frequency` / `player_sim_impulse_frequency` /
  `reactions_enabled`, `[agents.layers]` (memory/cognition/social) and
  `[runtime] expose_roster`; the `ControlSpec` registry (`god/controls.py`) gains
  the agent-seat/impulse/layer dials behind `POST /v1/config/god`.
- **Mod — GameLever (`tool_executor.py`).** New `execute_intent` translates each
  intent into the closest native lever (`speak` → `say_to`/`spontaneous_line`,
  `set_mood`, `approach`, `bias_interaction` → a gated queue candidate) and falls
  back to the gated command; `_post_tool_result` is shared with `execute`.
  (`tool_executor.py`, `state_collector.py`.)
- **Mod — roster + intent pull.** `state_collector.pull_and_execute_directives`
  now pulls `/v1/autonomy/intents` and translates via GameLever (speech shown
  through `notify.social.speech`); new `sw.agents [<seats>|<sim_id> <freq>]` cheat
  and `god_ui.format_roster`; new keys in `en` + `pt-BR`.
- **Tests.** sidecar 298 → **309** (`SeatManager`, `IntentBus`, seats/intents
  endpoints); mod 167 → **179** (GameLever, roster, intent pull, v0.2 fallback).

### Added — handoff/status doc
- **`docs/STATUS.md`** — single entry point for a new session: current build,
  how to run the sidecar, what's implemented/validated live, the pending
  validation checklist (zone heartbeat first), known issues, and how to continue.
  The skill now points to it.

### Added/Investigated — R1/F2: decompiled the shipped scripts; fixed buffs + heartbeat
Instead of guessing, decompiled the shipped Python (`decompyle3` → `research/ts4/`,
gitignored) and documented the confirmed APIs in **`docs/ts4_internals.md`**.
- **Buffs (root cause).** `sim_info.buff_component` does not exist: buffs live on
  **`SimInfo.Buffs`** (a `BuffComponent`) → `_active_buffs` (handle id → `Buff`) →
  `Buff.buff_type` (tuning; `__name__` = `buff_Sleeping`, …). `_buff_names_of`
  now reads that path, so sleep detection / P1 actually work.
- **Reliable heartbeat.** Alarms were confirmed unreliable live (owner `object_sim`
  and `Zone` both failed to fire). `state_collector.install_zone_hook` now keeps a
  `zone.Zone.update` wrapper installed: it starts the collector once the **active
  Sim is instanced** (correct alarm owner + non-empty census) and drives a
  wall-clock-throttled pulse/pull every `ZONE_PULSE_INTERVAL_SECONDS` (15 s), so
  the agency loop runs during normal play with no command and no dependence on
  alarms. Per-frame cost after startup is one timestamp compare.
- **Probe** reads `SimInfo.Buffs` and lists `buff_members` for future diagnosis.
- **Tests.** mod 200 → **201** (buff component `_active_buffs`, zone-heartbeat
  start/throttle/wait).

### Fixed — zone hook gating (owner=Zone + empty census) + event logging
The `.6` session confirmed the zone hook installs and auto-starts, but it fired
on the first `Zone.update` **before the active Sim was instanced**, so the alarms
got `owner=Zone` (do not tick) and the bootstrap census was `0 sims`; nothing was
collected during the session.
- The hook now waits until `sim_context._get_active_sim_instance()` exists before
  calling `ensure_started()`, so the alarm owner is the **Sim instance** and the
  census is non-empty. Still self-uninstalls once live.
- `_emit` now logs every forwarded event (`[validate] event: <type>`) so the next
  run shows whether game events are actually delivered (registration on an early,
  stale event manager would otherwise be invisible).
- **Tests.** mod 199 → **200** (zone hook waits for the active Sim).

### Fixed — collector auto-start at zone load (why play sessions collected nothing)
Root cause of the empty live sessions: the collector was only ever started from
the **command paths** (`_ensure_ready`/`_output`), and its deferred event/alarm
flush was only retried there. So a session where the player just *plays* never
registered events or alarms — the `.5` session logged nothing until the final
`sw.probe`, and only then (19 s before exit) did the alarms register.
- **`state_collector.install_zone_hook()`** wraps `zone.Zone.update` to call
  `ensure_started()` on the first zone ticks (when a live Sim exists to own the
  alarms) and **self-uninstalls** once the collector is live, so it comes up
  automatically at zone load with no lingering per-frame cost. Installed from
  `__init__.py`. This makes the zone pulse/pull/events fire during normal play,
  independent of cheat commands.
- **Tests.** mod 197 → **199** (zone-hook install/auto-start/self-uninstall +
  no-op without the `zone` module).

### Fixed — second live-validation pass (pulse safety net, buff discovery)
The second in-game run (build `.4`) confirmed the census/seat fix (census 7 Sims,
seats `household: 5, visitors: 2`) and the lifecycle attach/exit, but the
game-clock alarms still never fired and buffs were still empty, so:
- **Event-driven pulse safety net.** `StateCollector._maybe_pulse` fires a pulse
  (`/v1/autonomy/tick`) + intent pull piggy-backed on forwarded gameplay events
  (wall-clock throttled by `PULSE_MIN_INTERVAL_SECONDS`, only once the collector
  is started). Game-clock alarms pause with the game; events only fire during
  active play, so the agency loop now runs whenever the player actually plays.
- **Alarms prefer `use_sleep_time=False`** so a Sim-owned repeating alarm keeps
  advancing while the Sim sleeps (it otherwise silently stalls at night).
- **Buff discovery.** `probe` now lists buff/mood member names
  (`sim_info.buff_members`, `sim_instance.buff_members`); `_buff_names_of` also
  probes `mood_component`/`buff_tracker`/`mood_tracker` and
  `get_active_buffs`/`active_buffs`. `_on_zone_load` logs `zone_load event fired`.
- **Tests.** mod 195 → **197** (event-pulse gating/throttle).

### Fixed — first live-validation pass (alarms never fired, census scope, buffs)
Found while validating the R2/R3/R4 build in-game (only `sw.probe` was run):
- **Alarms never fired (blocker).** The pulse/pull/snapshot alarms registered but
  their owner was the zone/household/service, which the alarm service does not
  advance. `events._resolve_alarm_owner` now prefers the **active Sim instance**
  (a live GameObject), falling back to zone/household/client, and `add_alarm`
  logs the chosen owner type. `_on_zone_load` re-arms the alarms and sends one
  immediate pulse, so the agency loop gets data even across zone/active-Sim
  changes.
- **Census read the whole save.** `build_census` now takes a `scope`: the default
  `active_zone` reads only the **instanced** Sims (+ active), `full_save` is
  opt-in. This fixes the seat pool being filled with 81 NPCs (`household: 1,
  visitors: 81`) — the `[validate]` census line reported 82 sims for
  `scope=active_zone`.
- **Buffs/whims empty → sleep detection broken.** The probe showed
  `sim_info.buff_component` is absent in the current patch; `_buff_names_of` now
  also reads the buff component from the **Sim instance** and `get_buffs`-style
  accessors. `probe` gained a `sim_instance` section and probes the instance's
  buff component for next-run diagnosis.
- **`/v1/lifecycle/attach` 401 on the first boot.** `http_client.attach_lifecycle`
  now clears the runtime cache and retries once on a 401 (stale `runtime.json`).
- **Tests.** mod 191 → **195** (alarm-owner preference + fallback, instance-level
  buff reading, census scope). sidecar unchanged (**335**).

### Added — validation logging (close the in-game observability gaps)
- **Mod — `debug_log.validation_log()`.** New semantic logging of the decisions
  that were invisible: each executed intent (`kind`/`name`/`sim`/`ok`/`err`) in
  `pull_and_execute_directives`, chat tool calls, zone-pulse Sim count, census
  counts and the `sw.agents` roster. Prefixed `[validate]`, gated by
  `SENSEWRIGHT_VALIDATION` (on by default; `=0` mutes without touching errors).
- **Mod — log rotation.** `sensewright_output.log` no longer silently stops at the
  size cap: it rotates (keeps the tail), so a late `sw.probe` dump is never lost;
  cap raised to 1 MB.
- **Sidecar — semantic logs (`logger.info`).** Pulse (`sims`/`sleeping`/
  `scheduled`/`seats`), stored intents (`kinds`), impulse outcome (`kind`/
  `autonomy`/`intents`/`thought`/`used_llm`), live cognition plan (`source`/
  `focus`/`goals`), event ingestion (`count`/`types`), intent pull (`count`/
  `kinds`) and census seat sync. Together with the existing uvicorn access log,
  a session can be validated from `sidecar.log` + `sensewright_output.log`.
- **Tests.** sidecar 333 → **335** (pulse/intent log assertions); mod 188 → **191**
  (`test_debug_log.py`: validation prefix/mute + rotation).

### Added — sidecar lifecycle: exits with the game
- **Game-process watchdog (`sidecar/.../lifecycle.py`).** The sidecar now shuts
  itself down when The Sims 4 exits, so it never lingers after the game closes.
  The mod passes its PID via `SENSEWRIGHT_GAME_PID` on spawn (`main._spawn_sidecar`);
  a background thread watches that PID (Windows `ctypes` `OpenProcess` +
  `GetExitCodeProcess`; `os.kill(pid, 0)` elsewhere) with a grace period and asks
  uvicorn to stop (`app.state.server.should_exit`) for a graceful shutdown
  (`graph.shutdown()` + `runtime.json` cleanup). An optional process-name watch
  is available but off by default.
- **`POST /v1/lifecycle/attach` (`routers/lifecycle.py`).** A sidecar already
  running (manual start or a previous session) can be armed at boot: the mod
  calls this when autoboot finds the sidecar up. The watcher is always created
  when `shutdown_on_game_exit` is on, so attach works even with no target at
  startup.
- **`__main__.py`** now runs a `uvicorn.Server` and exposes it on `app.state`
  (the `--reload` dev path keeps the plain runner).
- **Config.** `[runtime]` gains `shutdown_on_game_exit`, `game_pid`,
  `watch_game_process_name`, `game_process_name`, `game_watch_interval_seconds`,
  `game_watch_grace_seconds` (documented in `config.example.toml`).
- **Validated live.** With a fake "game" process: both the env-from-spawn path
  and the attach path shut the sidecar down ~5–6 s after the process died, with a
  clean `Application shutdown complete` and the memory DB closed.
- **Tests.** sidecar 319 → **333** (`test_lifecycle.py`: PID checks, watchdog
  trigger/attach/name/stop, watcher factory, attach endpoint); mod 186 → **188**
  (`attach_lifecycle` payload + autoboot attaching on an already-running sidecar).

### Added — v0.3 F0/F1: R1 research tooling (`sw.probe` + decompile script)
- **F1 — `sw.probe` (mod).** New permanent dev cheat (`mod/.../probe.py`) that
  dumps a JSON snapshot of the active Sim's autonomy surface to
  `sensewright_output.log`: the autonomy service/component, `si_state`, commodity
  (motive) values, buffs/traits, whims, relationship tracks and the interaction
  queue. It also attempts to import every module from the §15.7 module map and
  records which exist in the current patch plus their public names — the raw
  material for the R1 levers catalog. Every read is guarded; pure helpers
  (`_describe`, `_prune`, `render_probe`, `_probe_modules`) are unit-tested.
- **F0 — `scripts/decompile-scripts.ps1`.** Reproducible decompile step: locates
  the game, stages `Game/Bin/Python/generated.zip` +
  `Data/Simulation/Gameplay/{base,core,simulation}.zip`, verifies the 3.7
  bytecode magic (`42 0D 0D 0A`) and decompiles with a configurable unpyc37
  command into the gitignored `research/ts4/`. `-VerifyOnly` runs without a
  decompiler.
- **Docs.** Module map updated (`probe.py`); `sw.probe` added to `sw.help` and the
  `en`/`pt-BR` locale tables.
- **Tests.** mod 179 → **186** (`test_probe.py`: describe/prune/render, module
  importability, no-sim snapshot, log write).

### Added — v0.3 R4: cognition layer (daily plan + goals at sleep)
- **Cognition (`agent/cognition.py`).** New `CognitionLayer` + `make_daily_plan`:
  at sleep one budgeted call turns recent events + profile into a compact
  **daily plan** (`day_focus` + up to 3 `goals`) stored on the profile
  (`daily_plan`/`day_focus`/`goals`), with a deterministic template fallback so
  native mode keeps planning. Absorbs the Phase 4 reflection into the sleep
  cycle; `sw.evolve` remains the manual trigger. Disabled via
  `[agents.layers] cognition = false`.
- **Graph (`agent/graph.py`).** `_sleep_consolidation` now runs the cognition
  layer after P1 absorption (one sleep = fold dialogue + drift psyche + plan the
  day); the absorbed profile is threaded through so the plan sees the latest state.
- **Prompt (`agent/initiative.py`).** Awake impulses render the stored plan
  (`render_plan`) so the Sim "adjusts the next day".
- **Tests.** sidecar 309 → **319** (`test_cognition.py`: template/LLM plan,
  bad-JSON fallback, layer toggle, prompt shaping).

### Changed — Roadmap pivot: v0.3 "Inhabited Agents" (plan)
- **Direction.** The agency model moves from command-centric (the LLM emits tool calls that
  puppet the Sim) to **inhabitation + nudge**: a configurable **agent-seat pool** biases the
  game's **native autonomy** ("changes of route"); cognition runs mainly at **sleep**; a
  per-agent **impulse-frequency** dial is surfaced in an **agent-roster panel**; two
  agent-owned Sims get a real **sim↔sim dialogue channel**; the God directs the **inactive
  neighbors' stories** on the free tier. Reference: *Generative Agents (Smallville)*.
- **Documented in `PLANO.md` §15** (bumped to v1.5): the `§14` per-item
  **keep/absorb/replace** map, the **L0–L7 layered framework** (new `CognitiveLayer`,
  `SeatManager`, `IntentBus`, `GameLever`, `LayerBudget`, `ContextForge`/`PairContext`), an
  **intent model** with lifecycle (`expires_at`), the phases **R1–R7**, a **fix-point map**
  of the already-implemented code, and the v0.3 risks/config draft.
- **Locked decisions.** Decompiled stubs in a gitignored `research/ts4/`; sequential internals
  reading; permanent `sw.probe` cheat; **hybrid nudge** (pure bias when available, else a
  gated candidate in the queue); sim↔sim **speech bubble with notification fallback**; seat
  eviction **on lot exit**; God **free/slow**; idle impulses **kept as a per-agent dial**.
- **Research plan.** `F0` tooling (`unpyc37`, reproducible `scripts/decompile-scripts.ps1`),
  `F1` live probe, `F2` `docs/ts4_internals.md` (autonomy architecture + native-levers
  catalog), `F3` this registration.
- **No code change yet** — this entry records the approved plan; implementation starts at R1.
- `.gitignore` now excludes `research/ts4/` (proprietary EA scripts must never be committed).

### Changed — LLM provider strategy (OpenRouter-first, model fallback, RPM/RPD, OpenCode Zen)
- **Chain order (OpenRouter first, Gemini demoted).** `LLMConfig.chain` default and
  `config.example.toml` now order `openrouter → opencode → gemini`; Google AI
  Studio's free tier rate-limits aggressively, so it moves to last resort (kept, not
  removed, for a final fallback).
- **Groq provider removed.** The `GroqProvider` (class, module, registry mapping,
  discovery branch), its config block and its chain entry were removed end to end
  (code + `config.py` default + `config.example.toml` + docs).
- **OpenCode Zen provider.** New `OpenCodeZenProvider` (OpenAI-compatible, Bearer),
  registered as `opencode` and defaulting to `https://opencode.ai/zen/v1` (+ discovery in
  `registry.py` and a documented `[llm.providers.opencode]` block). It is an optional power
  tier (requires a Zen key) and never replaces the 0-key native mode; note its free tier is
  client-restricted (see the live-validation section below).
- **Per-model fallback within a provider.** `OpenAICompatProvider.complete` now walks
  `model` + `models` in order, so a 429/unavailable model falls through to the next model
  on the same provider before the chain moves on; a key-level auth error (401) stops the
  loop early while a 403 stays model-level. `LLMError` gained a `status` field to support
  this.
- **RPM/RPD rate limiting.** New `llm/limits.py:ProviderRateLimiter`; `ProviderChain`
  builds one per provider from `ProviderConfig.rpm`/`rpd` and skips a provider that would
  exceed its cap instead of burning a 429. `config.example.toml` documents realistic
  free-tier limits. The agency scheduler now paces on the chain's `primary_rpm()` (wired
  via `Agency.set_registry`), with `AGENCY_BASE_RPM` remaining only a fallback.
- **Tests.** sidecar 286 → **295** (rate limiter, chain skip, `primary_rpm`, per-model
  fallback, auth short-circuit, OpenCode Zen defaults/registration, agency RPM).

### Validated — live provider smoke test (OpenCode Zen)
- **Zen's free tier is client-only.** Calling the Zen key from the sidecar, the free models
  `mimo-v2.6-flash-free`, `nemotron-3.5-lightning-free`, `nemotron-3-ultra-free` and
  `longcat-2.5-preview-free` return HTTP 403
  `FreeTierError: OpenCode's free tier can only be used from within OpenCode`. Only
  **`space-bunny-free`** works from an external client (validated: pt-BR text **and** a
  tool call `add_buff`), so it is the only Zen free slug the sidecar can use.
- **403 is model-level, not auth.** `_is_auth_error` now short-circuits only on 401, so a
  403 on one model makes the provider try its next model instead of aborting the whole
  provider. **Tests.** sidecar 295 → **296**.

### Added — Free-tier billing guard + OpenRouter validation
- **`free_only` guard.** `ProviderConfig.free_only` restricts a provider to models whose id
  contains `:free`; the OpenRouter block enables it, so a misconfigured list can never call
  a paid model (no billing). With `free_only` and no free candidate left, the provider fails
  retryably and the chain moves on. **Tests.** sidecar 296 → **298**.
- **OpenRouter live-validated (free models only).** With `free_only = true` the chain ran
  end-to-end: pt-BR text **and** a tool call (`add_buff`) via
  `nvidia/nemotron-3.5-lightning:free`. Free availability on this key:
  `nemotron-3.5-lightning`, `nemotron-3-ultra-550b-a55b`, `nemotron-3-super-120b-a12b` and
  `gemma-4-31b-it` answered; `qwen3.8-27b` frequently returned upstream 429 (shared pool)
  and is kept last. Note: these reasoning models sometimes answer in text under
  `tool_choice = auto` (they do call tools reliably when forced).

### Fixed — v1.4 live-validation pass (build 2026-09-26.6/.7)
The first live gameplay session (build `.5`) showed the collector never reaching
the sidecar and the Sim context degrading; root cause: **script mods load before
the game services exist**, so the event manager, the clock and the locale API all
failed at import and were never retried. Fixed:
- **Event/alarm bootstrap (no more dead collector).** `events.register` now
  *merges* handlers into a persistent store and flushes every handler not yet
  handed to a live manager, so a later call registers whatever was queued at
  import (`_flush`/`flush_pending`/`have_event_manager`, deduplicated). The
  collector caches its handler dict once (bound methods are fresh objects on each
  access) and `StateCollector.start()` retries each missing alarm/handler instead
  of bailing after one attempt; `ensure_started()` re-runs on the command paths
  (`main._ensure_ready`, called from `_output`) and pushes the zone **census once**
  when it first comes live. **Alarms now require a live owner** — `AlarmHandle`
  raises `ValueError('Alarm created without owner')`, so `events._resolve_alarm_owner`
  passes the active zone/household/client instead of `None` (build `.7`; the
  `.6` session logged `events.add_alarm deferred`). This finally wires
  `/v1/census`, `/v1/events` and `/v1/autonomy/tick`.
- **Sim context / service accessors (build `.7`).** Several reads called a service
  *accessor* or a method as if it were the value: fixed `_get_active_sim_info`
  (call `services.client_manager()` then `get_first_client()`),
  `_get_game_clock` (call the accessor), `_get_mood` (`get_mood()`),
  `_get_skills`/`_get_careers`/`_get_needs`/`_get_queue_size`/`_get_location`
  (call the method instead of returning the bound method). `_get_traits` uses
  `SimInfo.get_traits()` / `TraitTracker.equipped_traits` (the tracker has no
  `get_traits`/`traits`); `_get_relationships` uses
  `RelationshipTracker.get_target_sim_infos()` + `get_relationship_depth(id)`.
  Live check (build `.6`): `sw.chat lang='pt-BR' ... traits=65 rels=25`.
- **Save id (build `.7`).** `_get_save_id` reads the persistence service's
  `get_save_slot_proto_guid()` (stable per save) and skips `0`/empty, fixing the
  `save_id='0'` seen with `.6`.
- **Locale (Sim replied in English).** `i18n` gained `_detect_game_locale()`
  (returns availability) and `ensure_locale()`, which re-detects in `auto` mode
  until a game locale API answers, then locks. `main._get_current_lang` calls it,
  so requests carry `lang=pt-BR` when the game is Portuguese; `sw.lang` still
  forces an override.
- **Silent tool-only replies.** `main._render_response` surfaces the text of a
  `spontaneous_line`/`say_to` tool call when the model returns no reply (a
  `move_to`-only reply stays silent, as before).
- **Diagnostics.** Chat/debug logs now stamp the resolved `lang`, `save_id` and
  trait/relationship counts; the sidecar logs `lang`/`sim`/`save` per chat/hey.
- **Tests**: mod 153 → **167** (deferred event flush, alarm owner, locale retry,
  tool-text render, traits/relationships/clock/mood/active-sim reads, save-id
  fallbacks, census bootstrap); sidecar **286** (chat/hey lang log only).

### Changed — Code review pass (mod robustness, from `code_review.md`)
- **Swallowed-exception logging (review #1).** New `sensewright_mod/debug_log.py`
  writes to `sensewright_output.log` (size-capped, de-duplicated per signature) behind a
  `DEBUG_MODE` flag (`SENSEWRIGHT_DEBUG=0` override). The `_safe_call`/`_safe_getattr`
  guards in `sim_context.py`, `state_collector.py` and `tool_executor.py` now record
  the real exception + traceback; so do the collector's alarm/registration `except`
  blocks and the tool-result post. `main.py` delegates to the shared logger.
- **Type-hint fix (review #2).** `ToolFunc = Callable[[Dict[str, Any]], Dict[str, Any]]`
  (was an invalid `lambda` alias).
- **Strict tool arguments (review #3).** Tools read only the canonical key defined in
  the sidecar's `tools/schemas.py` — `buff_name`, `trait_name`, `interaction_name` —
  with the permissive aliases removed; contracts are documented in `tool_executor.py`.
- **Exact sleep detection (review #4).** `state_collector._is_sleeping` matches whole
  buff/moodlet tuning ids (`sleeping`, `buff_sleeping`, `moodlet_sleeping`, …) instead
  of substrings, so buffs like "Not sleeping well" no longer cause false positives.
- **Payload sanitization (review #5).** `http_client._sanitize_payload` recursively
  reduces every request body to primitives (non-finite floats → `null`, leaked game
  objects dropped), replacing `json.dumps(..., default=str)`; `sim_context` now coerces
  `full_name`, `save_id`, `zone_id`, skills/careers/funds at the source so no legitimate
  value is lost.
- **Adjacent fixes.** `tool_say_to` derives an affordance from `tone` (the schema never
  sends `interaction_name`); `sim_context._get_sim_info_manager` now calls the accessor
  instead of returning it.
- **Tests**: mod 148 → **153** (payload sanitization + non-finite floats, sleep
  substring false positives, primitive coercion).

### Added — v0.2 §14: Autonomous Sim Agents (M1, M2, A1–A3, P1, G1)
- **M1 — memory consolidation.** `memory/consolidation.py` folds a silent dialogue into
  one `consolidated_memory` event (deterministic extractive fallback + optional LLM);
  raw turns are archived (`consolidated=1`), never deleted, and leave the context.
  `graph.maybe_consolidate` runs lazily once the `dialogue_idle_seconds` window has
  passed on the next chat/hey; the sleep job consolidates too.
- **M2 — graded forgetting.** New `events` columns `strength`, `last_accessed_at`,
  `consolidated`, `emotion`, `salience` (additive migration). `memory/decay.py`
  computes lazy decay with `fast|normal|slow` presets; `recent_events`/`search_events`
  drop forgotten/archived rows and rank by `importance × strength × recency`
  (lexical) or `cosine × strength` (semantic). Recalled memories are `touch`ed;
  `prune_forgotten` and a rare déjà vu hint complete the lifecycle.
- **A1 — world context.** `POST /v1/autonomy/tick` ingests a zone pulse (active +
  nearby instanced Sims, zone context, **sleep detection** via the sleeping buff);
  the mod builder (`state_collector.sample_zone`) and the `AutonomyTickRequest` wire
  model land the snapshot in the agency world cache.
- **A2 — agency skeleton.** `agent/agency.py` (`Agency`) is a priority scheduler
  (reaction → sleep → idle) with per-Sim cooldown, quota-aware pacing and a
  pending-directive store; `GET /v1/autonomy/directives` lets the mod pull and
  execute them (reusing `/v1/tools/result`). `agent/coordinator.py` implements
  single-writer arbitration (the Sim agent wins on a played Sim; denied God
  directives are logged, never silently dropped).
- **A3 — LLM impulse.** `agent/initiative.py` builds a compact impulse prompt
  (profile + memories + world) and lets the model emit a bounded tool call and/or an
  internal `thought` (stored as an event, so life evolves even when unseen).
  Deterministic rule-based fallback keeps native/0-key mode alive.
- **P1 — living personality.** `agent/personality.py` adds `psyche`
  (traumas/baggage/aversions/attachments) + `life_story`, salience-gated absorption,
  intensity decay unless reinforced, capped blocks and prompt shaping
  (`format_life`). Sleep jobs consolidate dialogue + drift the psyche; the system
  prompt renders the shaping lines.
- **G1 — God scoping.** `god/world_model.aggregates()` (public population, mood
  distribution, tension and funds only) behind `GET /v1/god/aggregates`; the
  orchestrator never targets a played Sim and issues no control directive when only
  played Sims are present.
- **Wire/config.** New schemas (`ZoneContext`, `AutonomySimState`,
  `AutonomyTick*`, `DirectiveItem`, `DirectivesResponse`, `NeighborhoodAggregates`,
  `AggregatesResponse`, `EventRecord.source`, `StatusResponse.agency/personality`);
  `[memory]` consolidation/forgetting fields; `[agents.initiative]` and
  `[agents.personality]`; new initiative tools (`spontaneous_line`, `set_mood`,
  `act_out`, `socialize`, `approach`, `nearby_sims`, `world_state`, `sim_profile`)
  in `tools/schemas.py`/`registry.py`.
- **Mod.** `http_client.autonomy_tick` / `get_directives`; the zone-pulse and
  directive-pull game-clock alarms in `state_collector`; the eight new executor
  tools; `notify.autonomy.*` locale keys in `en` + `pt-BR`.
- **Tests.** sidecar 188 → **286** (memory decay/consolidation, agency, coordinator,
  initiative, personality, god scoping, v0.2 graph + endpoints); mod 110 → **148**
  (zone pulse/sleep, directive pull, new tools).

### Added — Phase 5c (God orchestration tier)
- **Sidecar — `god/orchestrator.py`**: `GodOrchestrator` is no longer a stub. It
  reads the world model, applies the dials (preset, `intervention_frequency`,
  `intensity`, `autonomy_degree`, `chaos_degree`, power toggles) and picks at most
  one intervention per tick from the preset deck, honoring per-intervention
  cooldowns. Cadence is `base_interval_seconds × (1 − frequency) × (1 − ½·autonomy)`
  with a 30 s floor; `frequency = 0` disables it. Chaos boosts `extreme_event`/
  `spawn_npc` weights. Deterministic with an injected RNG/clock; an optional LLM
  registry adds a short in-character narration (falls back to the deck description,
  so it works in native/0-key mode).
- **Sidecar — `god/world_model.py`**: `WorldState.from_census()` builds the public
  world snapshot (Sims, relationships, funds, time/lot) from the cached census;
  `SimProfile`/`Directive` gained `is_player`, `narration` and `tool_call`.
- **Sidecar — directive mapping**: interventions become mod tool calls where the
  executor supports them (`apply_trait` → `add_trait`/`add_buff` by duration,
  `force_social` → `queue_interaction` with a relationship partner, `gossip` →
  `say_to`); `spawn_npc`/`relationship_shift`/`extreme_event` stay as broadcast
  world events (`source=god`) the Sim agents react to.
- **Sidecar — wire/graph**: `POST /v1/god/tick` (`GodTickRequest`/`GodDirective`/
  `GodTickResponse`) runs a tick against the last census and returns the issued
  directives. `graph.god_tick` records each directive in the target Sim's memory
  (`type=god`, importance 0.9) and `/v1/status` now exposes the orchestrator
  snapshot. `POST /v1/config/god` re-applies the dials to the live orchestrator
  (the previous forward hit a module with no `configure` and silently did nothing).
- **Config**: `[god] base_interval_seconds` (default 600), documented in
  `config.example.toml`.
- **Tests**: sidecar 167 → **188** (`test_orchestrator.py` + god-tick graph/endpoint).

### Added
- **Sidecar — LLM tool calling**
  - `LLMToolCall` and `LLMResponse.tool_calls`; `complete(..., tools=...)` through
    `ProviderRegistry`/`ProviderChain` and the OpenAI-compatible + Gemini providers
    (schema conversion, argument parsing, `tool_choice=auto`).
- **Sidecar — safety rails** (`tools/rails.py`)
  - `DirectiveRails`: never-tools, per-Sim player-priority lock (10 s), rolling
    rate limit (60 s window, default 10 calls/min) and audit hooks
    (`tool_check` entries in `data/audit.log`).
  - Configurable via `[agents] tool_calls_per_minute` and `player_lock_seconds`.
- **Sidecar — directive round-trip**
  - Agent graph parses model tool calls, gates each through the rails, returns the
    allowed calls to the mod and stores them as pending calls per Sim.
  - `POST /v1/tools/result` now matches results to pending calls, records them in
    memory and drains the pending queue.
  - `POST /v1/events` ingests game events from the mod; `player_activity` /
    `player_interaction` events arm the player-priority lock.
  - `POST /v1/config/player-activity` arms the lock explicitly.
  - `/v1/status` exposes the rails snapshot.
  - New `add_buff` / `add_trait` tool schemas (semi + full autonomy).
- **Mod — DirectiveExecutor v1** (`tool_executor.py`)
  - Guarded game actions: `add_buff`, `add_trait`, `queue_interaction`, `move_to`,
    `say_to`, `cancel_current`; every call passes mod-side rails first and posts the
    result to `/v1/tools/result`.
- **Mod — state collector** (`state_collector.py`, `events.py`)
  - Game-clock alarm samples the active Sim every 30 sim-minutes; game-event
    handlers forward compact events to the sidecar. No per-frame work, no threads.
  - `http_client.send_events` / `send_event` / `send_player_activity`.
- **i18n**: `error.directive_denied` added to `en` and `pt-BR`.
- **Tests**: sidecar 56 → **96**; mod 21 → **61**.

### Added — Phase 2b + 5a (Census & God agent foundation)
- **Sidecar — memory**: `neighborhoods` and `households` tables plus async
  `upsert/get_neighborhood`, `upsert/get_household`, `list_households` and
  `set_sim_background`; reset/stats cover the new tables.
- **Sidecar — wire**: `SimRef.household_id`; God models (`Zeitgeist*`,
  `Background*`, `CensusSim/Household/Request/Response`, `ControlsResponse`);
  `GodConfig`/`GodConfigRequest` gained `mood_influence`, `autonomy_degree`,
  `chaos_degree` and a free-form `settings` map; `MOOD_TAGS` (7 tags).
- **Sidecar — `god/controls.py`**: declarative `ControlSpec` registry
  (slider/toggle/select/tags) that is the single source of truth for validation,
  `GET /v1/god/controls` and TOML defaults.
- **Sidecar — `god/zeitgeist.py`**: tag normalization, prompt block, deterministic
  `en`/`pt-BR` template and agent `suggest_zeitgeist` (suggest + rewrite).
- **Sidecar — `god/backgrounder.py`**: Sim/household background generation where
  native data is ground truth and `mood_influence` is the thermometer; deterministic
  fallbacks and `is_stale`.
- **Sidecar — endpoints**: `GET/POST /v1/god/zeitgeist`,
  `POST /v1/god/zeitgeist/suggest`, `POST /v1/god/background`,
  `GET /v1/god/controls`, `POST /v1/census`; `/v1/config/god` validates values
  against the ControlSpec registry (unknown keys → `ok=false`).
- **Sidecar — agent graph**: `get/set/suggest_zeitgeist`, `generate_background`,
  `ingest_census`, `god_controls`, census cache, background staleness on zeitgeist
  change; the generated background is now rendered into the Sim prompt.
- **Mod**: census builder + `send_census`; `god_ui.py` (vanilla-dialog zeitgeist
  onboarding and household background prompt, with console fallback); `sw.zeitgeist`
  cheat and `sw.god` controls summary; 52 `god.*` + 2 `cmd.zeitgeist.*` locale keys
  in `en` and `pt-BR`.
- **Tests**: sidecar 96 → **133**; mod 61 → **88**.

### Added — Phase 5b (background batch pipeline)
- **Sidecar — `god/budgeter.py`**: `BackgroundBudgeter`, a sliding-window
  (per-minute) + daily quota meter dedicated to background work, kept separate
  from the chat path. Limit `0` means unlimited; injectable clocks for tests.
- **Sidecar — `god/scheduler.py`**: `BackgroundScheduler`, a priority queue
  (active-zone households → active-zone Sims → related NPCs) with key
  deduplication, bounded queue, retry-on-failure and an async loop that paces
  itself between ticks. The generation logic is injected as a `runner(job)`,
  so the scheduler is decoupled and deterministic to test.
- **Sidecar — agent graph**: the graph now owns the scheduler; `configure`
  drops any previous instance, `start_backgrounds`/`stop_backgrounds` manage
  its lifecycle, `process_backgrounds_once` drains a batch, `/v1/census`
  enqueues active-zone households/Sims (and relationship-discovered NPCs) and a
  zeitgeist change re-queues the save's backgrounds. `/v1/status` exposes the
  scheduler + budget snapshot. Generators now receive the registry only when a
  provider is actually available (`_effective_registry`), so native mode skips
  futile calls and the budget meters real usage only.
- **Sidecar — server**: the lifespan now configures the graph synchronously
  (it previously awaited the sync `configure`, which silently failed) and
  starts/stops the background scheduler.
- **Wire**: `CensusResponse.queued`.
- **Config**: `[god.backgrounds]` (`enabled`, `batch_size`, `interval_seconds`,
  `idle_seconds`, `per_minute`, `daily_limit`, `max_queue`, `max_attempts`),
  documented in `config.example.toml`.
- **Tests**: sidecar 133 → **146** (budgeter, scheduler, graph integration).

### Added — Phase 3 (Agents): profiles, chat budget, semantic memory
- **Sidecar — `agent/profiler.py`**: one-sentence seed → structured profile JSON
  (`name`, `backstory`, `personality`, `speech_style`, `goals`, `secrets`,
  `quirks`, `traits`) with native data as ground truth, deterministic `en`/`pt-BR`
  fallback and `normalize_profile`. Never raises.
- **Sidecar — chat budgeter (`llm/budgeter.py`)**: per-Sim daily request cap
  (`llm.budget_per_sim_per_day`), enforced on `/v1/chat` and `/v1/hey` only when
  a provider is available; exhausted requests return `error.budget_exhausted`.
  Exposed in `/v1/status` (`budget`).
- **Sidecar — semantic memory**: `MemoryConfig.embedding_provider_config`
  (Cloudflare account/token); events now store embeddings (new
  `events.embedding_json` column + additive migration) and `search_events`
  ranks by cosine similarity, falling back to lexical.
- **Sidecar — wire/endpoints**: `POST /v1/profile` (`ProfileRequest/Response`).
- **Mod**: `sw.profile <one sentence>` cheat + `request_profile` client.

### Added — Phase 4 (Evolution): reflection & personality drift
- **Sidecar — `agent/evolution.py`**: `reflect` (events → reflection JSON +
  trait-swap proposal), `normalize_reflection`, deterministic `en`/`pt-BR`
  fallback, `should_reflect` (min events + cooldown), `propose_trait_swap`.
- **Sidecar — storage**: `list_profiles`, `add_reflection`,
  `recent_reflections` (SQLite + in-memory fallback).
- **Sidecar — agent graph**: `evolve(scope="sim"|"save")` reflects, drifts the
  profile personality, stores the reflection and a `proposed_trait_swap`;
  `evolution_speed` scales the thresholds. `POST /v1/evolve`
  (`EvolveRequest/Response`).
- **Config**: `[agents.evolution]` (`enabled`, `min_events`, `cooldown_seconds`,
  `max_reflections_per_day`, `trait_swap`, `drift_strength`).
- **Mod**: `sw.evolve [save]` cheat + `evolve` client; `error.budget_exhausted`,
  `cmd.profile.*`, `cmd.evolve.*` locale keys in `en` and `pt-BR`.
- **Tests**: sidecar 146 → **167** (profiler, evolution, phase 3/4 wiring).

### Changed
- **`PLANO.md` bumped to v1.2** with a new **§14 "Autonomous Sim Agents (v0.2)"**: the
  per-Sim agency layer (initiative loop, `tick`/`directives`, quota-max scheduler),
  memory consolidation + graded forgetting (strength decay, touch, déjà vu), a living
  personality (`psyche` blocks + `life_story`, sleep consolidation, immediate extreme
  absorption) and the God ↔ Sim-agent coordination contract (single-writer, aggregates
  only, broadcast events, arbitration). Also added the v0.2 wire endpoints and config.
- Mod chat/hey only show the "brain foggy" fallback when no reply, system message
  *and* no tool calls were produced (tool effects are the response).
- `PLANO.md` §1/§2.3/§4/§7/§8/§9/§11/§14 rewritten for the God agent (zeitgeist,
  backgrounds, ControlSpec framework, 5a/5b/5c split) and the reviewer's fixes.
- `config.example.toml` documents the rails settings and the new `[god]` dials +
  `[god.settings]`.

### Fixed — Phase 0 spike (events & alarms wired to the real API)
- **Mod `events.py`** corrected against the scripts shipped with the live client
  (patch 1.113, extracted from `Data/Simulation/Gameplay/*.zip`):
  - `TestEvent` is an enum nested under `event_testing.test_events.TestEvent`; the
    old lookup used module-level `hasattr`, so **no event ever registered**. The
    map now reads the class members and uses the verified names:
    `BuffBeganEvent`/`BuffEndedEvent` (buff), `RelationshipChanged` (relationship),
    `InteractionComplete` (social/object), `TraitAddEvent`/`TraitRemoveEvent`,
    `SkillLevelChange`, `CareerEvent`/`CareerPromoted`, `SimDeathTypeSet`,
    `HouseholdChanged` (household), `LoadingScreenLifted`/`SimHomeZoneChanged`/
    `SimTravel` (zone load). `EVENT_SIM_SPAWN` has no native TestEvent and stays
    unmapped (census diff covers it).
  - Event manager now comes from `services.get_event_manager()` (there is no
    `sims4.event_manager` module), and unregistration passes the event type:
    `unregister_single_event(handler, event_type)`.
  - Alarms use the top-level `alarms` module (there is no `sims4.alarms`), with the
    verified signature `add_alarm(owner, time_span, callback, repeating=False,
    repeating_time_span=None, use_sleep_time=True, cross_zone=False)`.
  - Time spans use `date_and_time.create_time_span(days, hours, minutes)` (the old
    `sims4.math.TimeSpan` path never existed).
- **Mod — sidecar autostart from source.** With no packaged `.exe` yet (PyInstaller
  is Phase 6), `sw.start`/autoboot could not launch the sidecar, so it stayed down
  and `sw.chat`/`sw.status` reported "sidecar unreachable". `config.sidecar_launch()`
  now prefers the exe and otherwise runs the bundled source
  (`python -m sensewright_sidecar`), choosing the interpreter from
  `SENSEWRIGHT_PYTHON` → the sidecar `.venv` → `python`/`python3`/`py` on PATH.
- **Mod — chat never fails silently.** `sw.chat`/`sw.hey` now run context
  collection inside the `try` (a failure surfaces as a message instead of dying in
  the command system) and render through a shared `_render_response`: the dialog is
  tried first and the reply/fallback falls back to the cheat console. `chat_ui`
  passes the real connection to `CheatOutput` instead of only `None`.
- **Mod — command arguments to the real TS4 parser.** `main.py` used
  `from __future__ import annotations`, so `message: str` reached the command system
  as the *string* `'str'`; the parser (`sims4/commands.py`) does
  `isinstance(arg_type, type)`/`issubclass`, so typed args never parsed and
  `sw.chat`/`sw.profile`/`sw.zeitgeist` produced no request and no message. The
  future-import was removed (the annotations are all 3.7-safe) and the free-text
  commands now use an unannotated ``message`` + ``*args`` hybrid joined together —
  a lone variadic can be rejected by the console and an annotated positional
  collides with the injected ``_connection`` on multi-word input. `sw.chat` logs
  its raw args plus a `_BUILD` stamp to `sensewright_output.log` (and `sw.help` logs
  the build) so the loaded build can be confirmed; the game only loads script mods
  at startup, so a full restart is required after each install.
- **Mod — JSON payload with game objects (the "Internal error").** `http_client`
  called `json.dumps(payload)` *before* its request try/except, so a non-serializable
  value in the collected `context` (e.g. `relationship_track` / `full_name`)
  raised a `TypeError` that surfaced as an in-game "Internal error" **before any
  request was sent**. Serialization now uses `default=str`, and
  `sim_context._get_relationships` coerces `target_name`/`track` to `str` and
  `depth` to `float`. The chat/hey handlers also log the real exception + traceback
  to `sensewright_output.log` instead of swallowing it.
- **Mod — language resolved at boot (Sim replied in English).** `i18n._current_locale`
  was never set: `resolve_locale()` returned the detected locale but did not apply
  it, so every request sent `lang="en"`. Added `i18n.init_locale()` (called from
  `__init__` with `config.read_ui_language()`) which sets the active locale from the
  config override or the game language. `detect_game_language()` now reads
  `services.get_locale()` (`client.account.locale`), also consulting the enum's
  `name` and `SimSpawner.LOCALE_MAPPING`, and `_normalize_locale` matches by
  substring so `Locale.PORTUGUESE_BRAZIL`/`Language.ENGLISH` resolve correctly.
- **Tests**: mod 88 → **110** (`mod/tests/test_events.py`, `test_config.py`,
  `test_chat_flow.py`, `test_http_client.py`, `test_i18n.py` lock in the validated
  enum/mapping, manager/alarm modules, sidecar launch, always-surface chat rendering,
  multi-word command parsing, non-JSON-safe payload and locale resolution).

### Fixed
- `scripts/install-mod.ps1`: `Join-Path` returns a string, so `$sidecarSrc.Path`
  was empty and the relative path chopped the drive letter, breaking the sidecar
  copy with "The given path's format is not supported".
- `server.py` lifespan awaited the synchronous `configure`, so the agent graph
  was never configured at boot (now called synchronously and the scheduler is
  started/stopped around the app lifespan).
- **Mod (found in the in-game spike):** `config.get_base_url()` already ended in
  `/v1` while every endpoint path also starts with `/v1/...`, so all requests hit
  `/v1/v1/...` and returned 404. It now returns the server root; a regression
  test asserts the prefix appears exactly once.
- **Mod (found in the in-game spike):** cheat commands produced no visible
  console output. Two causes: the connection was received in a plain
  `connection` parameter (TS4 injects a parameter named `_connection` only), and
  it was annotated `_connection: int = 0`, which made the command system treat it
  as a user argument instead of injecting the connection. Fixed by using
  `_connection=None` (unannotated) and emitting through `CheatOutput` first; a
  best-effort `sensewright_output.log` next to the mod records output for
  troubleshooting. i18n also reads locale JSON from inside the `.ts4script`.
- **Mod:** `sw.status` raised `TypeError` because `providers` is a list of dicts
  on the wire, not strings; added `_format_providers`.
- **Providers (found while configuring keys):**
  - Gemini API key was sent as a `?key=` query parameter, so httpx wrote the key
    into `sidecar.log`. It now uses the `x-goog-api-key` header, and the Gemini
    model auto-discovery does the same. *(Rotate any key exposed this way.)*
  - Gemini 2.5+ spends part of `maxOutputTokens` on internal "thinking", which
    truncated structured JSON answers; the provider now disables it
    (`thinkingConfig.thinkingBudget = 0`) for those models.
  - OpenRouter sample models were stale (`deepseek-chat-v3-0324:free` → 404);
    updated to currently-free slugs (`qwen/qwen3.8-27b:free`,
    `nemotron-3-ultra-550b-a55b:free`, `gemma-4-31b-it:free`).

### Validated in-game (Phase 0 spike, live client 1.113.277.1030)
- Python 3.7 confirmed (`Game/Bin/python37_x64.dll`); `.ts4script` is a valid zip
  of 3.7 bytecode and **loads from the OneDrive `Documents` folder**.
- Mod → sidecar autoboot ping reaches the sidecar; Mods had been auto-disabled by
  the game (`modsdisabled=1`) after the patch — re-enabling is required.
- Cheat commands now render in the console (`sw.help`), confirmed side-by-side
  with an independent reference script mod with the same pattern.
- **End-to-end LLM round-trip from inside the game**: `POST /v1/chat`,
  `POST /v1/profile` and `GET /v1/status` all returned 200 via Gemini
  (`gemini-2.5-flash`) in the sidecar logs, and the regenerated key never appears
  in the request URL (the `x-goog-api-key` header fix holds).
- **`sw.chat` works in-game (builds `2026-09-26.3`/`.4`).** After the
  command-annotation and JSON-serialization fixes above, typing `sw.chat <text>`
  reaches the sidecar (`POST /v1/chat → 200`, Gemini), the reply is rendered and the
  conversation is persisted in `memory.sqlite3` (`events`: user + assistant turns,
  e.g. `olá` stored as `ol\u00e1`). The earlier `olA` seen in the debug log was only
  the terminal's display encoding, not the game's. Build `.4` additionally resolves
  the locale at boot, so requests now carry `lang` (`pt-BR` when the game is
  Portuguese) instead of always `en` — pending in-game confirmation.
- **§2.3 API validation against the shipped scripts** (`Game/Bin/Python/
  generated.zip`, `Data/Simulation/Gameplay/{base,core,simulation}.zip`):
  `TestEvent` members, `services.get_event_manager()`, the `alarms` module and
  `create_time_span`, `sim_info.add_trait/add_buff` (C-backed forwarders),
  `sim_info.genealogy`/`household`, `InteractionQueue.insert_next`/`cancel_all`,
  and `Zone.save_slot_data_id` — see the Fixes above for what changed.
- Background scheduler/budget defaults still need tuning against a live save.

### Pending (not yet validated in-game)
- Phase 0 spike: the event/alarm names are now validated and wired (see the Fixes
  above); still to confirm **live behavior** — that alarms fire on the game clock,
  that the chosen events fire as expected, and the real interaction/queue APIs
  (`push_super_affordance`, `move_to`, `say_to`) plus census cost measurements.
- Game-event driven player-activity detection (the endpoint and lock exist; wiring
  a real "player clicked" signal is still to be confirmed in-game).
- God UI: `UiDialogTextInput` / multi-choice dialog signatures and reliable
  new-household / new-Sim detection (best-effort census diff in the meantime).
- Background batch pipeline: scheduler and budgeter are unit-tested, but the
  cadence/budget defaults are not yet tuned against a live save.

---

## [0.1.0] — 2026-09-25 — Phase 1: Skeleton

First end-to-end skeleton: sidecar boots by itself, mod handshake works, all UI text is localized.

### Added
- **Foundation / wire contract**
  - `sidecar/sensewright_sidecar/schemas.py`: Pydantic v2 models for `/v1` (`ChatRequest`,
    `ChatResponse` with `message_key`/`message_args`, `ToolResultRequest`, `ResetRequest`,
    `AutonomyConfigRequest`, `LangConfigRequest`, `GodConfigRequest`, `StatusResponse`, …)
    plus `normalize_lang` and `SUPPORTED_LANGS = ("en", "pt-BR")`.
  - `config.py`: `config.toml` loader with `${ENV}` expansion, `[ui].language`, platform-aware home.
  - `auth.py`: shared-token auth (`X-Sensewright-Token`), `runtime.json` writer, 0600 token file.
- **Sidecar (Python 3.10+, FastAPI)**
  - `server.py` (`create_app` + lifespan) and `__main__.py` CLI.
  - Endpoints: `GET /v1/health`, `GET /v1/status`, `POST /v1/chat`, `/v1/hey`,
    `/v1/tools/result`, `/v1/reset`, `/v1/config/{autonomy,lang,god}`.
  - `observability/`: rotating file logging + JSONL audit log.
  - LLM layer: Gemini, Groq, OpenRouter and DeepSeek providers (OpenAI-compat shared),
    fallback `ProviderChain` with per-provider circuit breaker (3 failures → 60 s),
    `ProviderRegistry` + best-effort `auto_discover()`.
  - Memory: SQLite store (`sims`, `events`, `relationships`, `reflections`, `directives`)
    with async wrappers, plus embedding provider protocols (lexical default).
  - Agent graph: recall → prompt → model → persist → format, with **native fallback**
    (`message_key = notify.no_llm_native`) when no provider is configured.
  - God stub (world model, intervention presets, orchestrator) and tool JSON schemas +
    autonomy→tool-set mapping.
- **In-game mod (Python 3.7, stdlib only)**
  - `i18n.py` + `locales/en.json` + `locales/pt-BR.json` (24 keys, EN reference/default,
    per-key EN fallback, defensive game-language detection).
  - `config.py` (install/sidecar discovery, `runtime.json` candidates), `http_client.py`
    (`urllib`, typed errors), `chat_ui.py` (notification → command → print fallback),
    `sim_context.py`, `events.py` (guarded `event_manager`/`sims4.alarms` scaffold),
    `tool_executor.py` (8 tool stubs), `main.py` (cheats `sw.chat`, `sw.hey`, `sw.status`,
    `sw.reset`, `sw.forget`, `sw.autonomy`, `sw.lang`, `sw.god`, `sw.start`, `sw.help`),
    and sidecar autoboot (`CREATE_NO_WINDOW`).
  - `mod/build.py`: compiles with Python 3.7 → `dist/Sensewright.ts4script`
    (`--python`, `PY37`, `py -3.7` detection; `--allow-any-python` for dev).
- **Toolchain**
  - Root `Makefile` (`install`, `run`, `doctor`, `status`, `logs`, `build-mod`,
    `build-mod-dev`, `install-mod`, `check`, `dev`).
  - `scripts/doctor.ps1`, `scripts/dev.ps1`, `scripts/install-mod.ps1`.
  - `.gitignore`, `config.example.toml`.
- **Tests**: 56 sidecar (`pytest`) + 21 mod (locale parity, i18n, HTTP client).

### Changed
- `PLANO.md` rewritten from v1.0 (PT-BR) to **v1.1 (English)** with a new
  §4 *Localization (i18n)*, `lang` on the wire, and the English-everywhere convention.
- All shared foundation files converted to English.

### Fixed
- `mod/build.py`: `py -3.7` was invoked as a single string (WinError 2); `compileall -v`
  is unsupported on 3.7. Now uses a command list, cleans stale bytecode, and omits `-v`.
- `scripts/doctor.ps1`: PowerShell parse error (`$name:` drive reference) and wrong artifact path.
- `scripts/dev.ps1`: reserved `$args` variable and wrong module entry point (`-m sensewright_sidecar`).
- `scripts/install-mod.ps1`: looked for the artifact under `mod/dist` instead of `dist`.
- Sidecar `/v1/status` now returns a coherent provider list + chain health; `/v1/config/lang`
  no longer `await`s the synchronous `set_lang`.

### Environment
- Installed **Python 3.7.9** (`winget Python.Python.3.7`) for correct `.ts4script` bytecode
  (magic `42 0d 0d 0a`); sidecar runs on the existing Python 3.10.11.

### Known limitations
- No packaged `Sensewright-sidecar.exe` yet (runs from source; PyInstaller is a later phase).
- Tool execution and game events are guarded stubs; the `PLANO.md` §2.3 spike is not yet
  validated inside the live game.
- With no API keys the agent runs in **native mode** (no LLM), by design.

---

## Development status

| Phase | Scope | Status |
|---|---|---|
| 0 — Spike | Decompile stubs; validate §2.3 checklist in-game | ◐ Core event/alarm APIs validated vs shipped scripts; live measurements pending |
| 1 — Skeleton | Toolchain, handshake, autoboot, i18n scaffold | ☑ Done (0.1.0) |
| 2 — State & Directives | StateCollector, DirectiveExecutor v1, rails | ◐ Events/alarms now wired to the real API; in-game behavior pending |
| 2b — Census & household events | `/v1/census`, neighborhoods/households schema, events | ◐ Census + schema done; `HouseholdChanged` validated, live detection pending |
| 3 — Agents | Profiles, MemoryDB, ModelRouter + budgeter, chat | ◐ In-game `sw.chat` validated; provider chain live-tested (OpenRouter free + OpenCode Zen, pt-BR + tool calling); profile/memory visuals pending |
| 4 — Evolution | Reflection loop, personality drift, trait swaps | ◐ Reflection/drift/trait-swap proposal done; auto-apply pending |
| 5a — Zeitgeist | Onboarding, 7 tags, suggest+rewrite, ControlSpec framework | ◐ Sidecar + mod wiring done; in-game dialog spike pending |
| 5b — Backgrounds | Sim/household background writer, batch pipeline, thermometer | ◐ Generator + batch scheduler done; in-game validation pending |
| 5c — God panel | In-game sliders, DeepSeek orchestration, intervention deck | ◐ Orchestration tier done (`/v1/god/tick`, deck live, directives → tool calls); in-game panel + wired DeepSeek provider pending |
| v0.2 M1/M2 — Memory | Consolidation + graded forgetting (strength decay, touch, déjà vu, pruning) | ☑ Done (unit + graph tested); cadence tuning against a live save pending |
| v0.2 A1–A3 — Agency | Zone pulse, agency scheduler, tick/directives, LLM impulse + reactions | ☑ Sidecar + mod wired; live cadence/quota tuning pending |
| v0.2 P1 — Living personality | `psyche` + `life_story`, sleep absorption, immediate extreme path hook | ☑ Done (unit tested); in-game validation pending |
| v0.2 G1 — God scoping | Aggregates-only visibility, played-Sim protection, coordinator | ☑ Done (unit tested) |
| 6 — Publishing | Packaging, README, 0-key mode, degradation, perf | ☐ Planned |

### Verification commands
```powershell
# Sidecar tests + lint
cd sidecar; .\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check sensewright_sidecar tests

# In-game mod tests + build (requires Python 3.7)
python -m pytest mod\tests -q
python mod\build.py

# Environment health
powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1
```
