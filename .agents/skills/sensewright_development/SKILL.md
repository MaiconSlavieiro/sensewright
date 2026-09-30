---
name: Sensewright Development Guidelines
description: Architecture, constraints, patterns, and gotchas for agents working on the Sensewright (formerly SimsSense) Sims 4 mod, its sidecar, and the sw.* cheats. Read this before writing any code.
---

# Sensewright Development Guidelines

When modifying or extending the Sensewright project, adhere to the following rules,
patterns, and architecture constraints. **Read `PLANO.md` for the full design**;
this skill covers the day-to-day coding rules.

> **Project renamed.** What was once called *SimsSense* is now **Sensewright**:
> cheats are **`sw.*`**, the artifact is `Sensewright.ts4script`, and the install
> folder is `Mods\Sensewright\`. Old `ss.*`/SimsSense names are gone — do not
> reintroduce them.

> **Starting a new session?** Read, in order: **`docs/STATUS.md`** (current build,
> what's validated live, pending checks, known issues) → **`docs/stack_migration.md`**
> (S4CL + Lot 51 base, the seam and the live checklist) → **`docs/ts4_internals.md`**
> (confirmed game APIs) → **`docs/ui_panel.md`** (panel plan) → `PLANO.md`.

---

## 1. Two-Process Architecture

Sensewright is split into two strictly isolated packages:

| Layer | Package | Runtime | Deps allowed |
|---|---|---|---|
| **In-game mod** | `mod/sensewright_mod/` | Python 3.7 (game sandbox) | **stdlib + S4CL + Lot 51 Core** (runtime libs installed by the player) |
| **Sidecar** | `sidecar/sensewright_sidecar/` | Python 3.12+ | Pydantic v2, FastAPI, httpx, SQLite (stdlib) |

**The sidecar never imports game modules. The mod never imports third-party libs.**

The mod communicates with the sidecar over HTTP (`127.0.0.1:8765`, `/v1/*` routes).
The shared wire contract lives in `sidecar/sensewright_sidecar/schemas.py` (Pydantic
models) and is mirrored by plain dicts in the mod's `http_client.py`.

---

## 2. Safety and Best-Effort Paradigm (In-Game Mod)

The Sims 4 does not tolerate unhandled exceptions — they crash the game or break
simulation loops.

- **Always guard game APIs:** Wrap game object manipulations and API lookups using
  `_safe_call` and `_safe_getattr` (see `sim_context.py`).
- **Never raise:** Public functions in the mod should return `None`, `{}`, or `False`
  instead of raising exceptions.
- **Log exceptions, don't swallow:** Never use bare `pass` in `except Exception:`
  blocks for non-trivial errors. Use `debug_log._debug_log()` or `_log_exception()`
  to write to `sensewright_output.log` so developers can debug without crashing the
  game. Logging is gated behind `DEBUG_MODE` (`SENSEWRIGHT_DEBUG` env var).
- **Validation logging:** use `validation_log()` for the **semantic** decisions
  (which intent/tool ran, seat sync, roster) — it prefixes `[validate]` and is
  gated by `SENSEWRIGHT_VALIDATION` (on by default). The sidecar mirrors this with
  `logger.info` (pulse/intent/cognition/event summaries). Together with the
  uvicorn access log, an in-game session can be validated from the two logs.
- **Services may not exist at import time:** The game loads script mods before
  services are ready. Always call service accessors lazily (inside functions, not
  at module level). `events.register()` uses a deferred-flush pattern for this.

---

## 3. Python Version Constraints

- **Mod (`mod/sensewright_mod/`):** Python 3.7 **only**. You **cannot** use:
  - Walrus operator (`:=`)
  - `match` statements
  - Modern union types (`int | str` — use `Union[int, str]`)
  - `from __future__ import annotations` (**breaks TS4 command parsing** — the game
    introspects type annotations at runtime for `@sims4.commands.Command`; stringified
    annotations cause the parser to fail silently)
  - Third-party libraries **except** the stack base (`sims4communitylib`,
    `lot51_core`), which must be imported **only through `integrations.py`**
    (no `pydantic`, `requests`, `dataclasses` beyond stdlib)
  - `asyncio` (the game is single-threaded with GIL)
- **Sidecar (`sidecar/sensewright_sidecar/`):** Python 3.12+. Modern features and
  external libraries are fine.

---

## 4. Module Map

### In-game mod (`sensewright_mod/`)

```
sensewright_mod/
├── __init__.py          # registers cheat commands at import
├── config.py            # sidecar URL + timeouts; reads port/token/lang
├── debug_log.py         # gated best-effort logging to sensewright_output.log
├── i18n.py              # locale loader + t(key, **args) + game-language detection
├── locales/
│   ├── manifest.json    # data-driven registry: {default, locales:[{code,name,match}]}
│   ├── en.json          # default locale (source of truth)
│   └── pt-BR.json       # Brazilian Portuguese translation
├── main.py              # @sims4.commands.Command bindings (sw.chat, sw.help, etc.)
├── sim_context.py       # collects Sim state → primitive-only dicts
├── state_collector.py   # zone pulse, census, event ingestion, directive pull, sleep
├── events.py            # event subscriptions + alarm management (deferred flush)
├── http_client.py       # POST via urllib; typed errors; payload sanitization
├── tool_executor.py     # dispatches tool_calls → game functions → POST result
├── rails.py             # mod-side rate limit + player-priority lock + never-tools
├── chat_ui.py           # notification → dialog → console fallback for chat
├── hud.py               # sw.hud debug HUD: periodic in-game status line
├── god_ui.py            # zeitgeist onboarding / household background dialogs
├── player_activity.py   # wraps Sim.push_super_affordance → player-priority lock
├── probe.py             # sw.probe: live autonomy dump (dev, R1/F1)
├── dialogs.py           # native text-input and confirmation dialogs
├── pie_menu.py          # S4CL interactions (tuning .package + registry; no XmlInjector)
├── panel_ui.py          # R7 config panel over GET /v1/god/controls (S4CL dialogs)
├── stack_service.py     # Lot 51 custom service: owns the collector lifecycle
└── integrations.py      # the stack seam: Lot 51 Core + S4CL lookups (guarded)

mod/
├── build.py             # Python 3.7 bytecode → dist/Sensewright.ts4script
├── build_package.py     # DBPF writer → dist/Sensewright.package (tuning + STBL)
└── tuning/              # interaction tuning XML + stbl.json (no XmlInjector)
```

### Sidecar (`sensewright_sidecar/`)

```
sensewright_sidecar/
├── __main__.py          # entry point (python -m sensewright_sidecar)
├── server.py            # FastAPI app + lifespan
├── config.py            # Pydantic Settings, config.toml loader
├── schemas.py           # Pydantic v2 wire models (THE contract with the mod)
├── auth.py              # shared-token auth (X-Sensewright-Token)
├── lifecycle.py         # game-process watchdog: exits with The Sims 4
├── locales.py           # thin wrapper over content_i18n for system messages
├── content_i18n.py      # data-driven content localization (t/language_name/normalize_lang)
├── locales_content/     # manifest.json + <code>.json content tables + lexicon.json
├── panel_store.py       # data/panel.toml overlay for panel ControlSpec values (P1)
├── routers/             # FastAPI route modules
│   ├── admin.py         # /v1/config/*, /v1/reset
│   ├── autonomy.py      # /v1/autonomy/tick, /v1/autonomy/directives
│   ├── chat.py          # /v1/chat, /v1/hey
│   ├── deps.py          # shared FastAPI dependencies (auth, settings)
│   ├── events.py        # /v1/events
│   ├── god.py           # /v1/god/*, /v1/census
│   ├── health.py        # /v1/health, /v1/status
│   ├── lifecycle.py     # /v1/lifecycle/attach
│   └── profiles.py      # /v1/profile
├── agent/               # Core agent logic
│   ├── graph.py         # State machine: the central orchestrator
│   ├── nodes.py         # Graph node implementations
│   ├── state.py         # AgentState, Turn, Memory, ToolCall models
│   ├── prompts.py       # System/user prompt templates (language-aware)
│   ├── profiler.py      # 1-sentence → full profile JSON
│   ├── evolution.py     # Reflection loop, personality drift, trait-swap
│   ├── personality.py   # Psyche + life_story + sleep consolidation
│   ├── agency.py        # Agency scheduler + seats + IntentBus + pull (v0.3 R2/R3)
│   ├── seats.py         # SeatManager: agent-seat pool (v0.3 R2)
│   ├── intents.py       # Intent model + IntentBus (v0.3 R3)
│   ├── cognition.py     # CognitionLayer: daily plan/goals at sleep (v0.3 R4)
│   ├── social.py        # SocialLayer: sim<->sim dialogue channel (v0.3 R5)
│   ├── context_forge.py # per-Sim / pair context assembly (v0.3 R3)
│   ├── coordinator.py   # Single-writer arbitration (agent vs God)
│   ├── initiative.py    # LLM impulse prompt building + execution
│   └── memory_fallback.py
├── llm/
│   ├── base.py          # LLMProvider protocol
│   ├── chain.py         # Ordered fallback + circuit breaker
│   ├── limits.py        # Per-provider RPM/RPD rate limiter
│   ├── budgeter.py      # Per-Sim daily request cap
│   ├── registry.py      # Auto-discovery of free models
│   └── providers/
│       ├── openai_compat.py  # OpenAI-compat base + OpenCodeZenProvider
│       ├── openrouter.py     # OpenRouter (:free, free_only guard)
│       ├── gemini.py         # Gemini (free tier, last resort)
│       └── deepseek.py       # DeepSeek (paid, God)
├── memory/
│   ├── base.py          # MemoryProvider protocol
│   ├── sqlite_store.py  # SQLite store + embeddings + decay columns
│   ├── embeddings.py    # Cloudflare BGE-M3 + lexical fallback
│   ├── consolidation.py # Dialogue → consolidated memory event
│   └── decay.py         # Strength decay, touch, déjà vu, pruning
├── god/
│   ├── orchestrator.py  # God agent intervention loop
│   ├── interventions.py # Intervention deck (presets)
│   ├── world_model.py   # Census → WorldState, aggregates
│   ├── zeitgeist.py     # Tag normalization, templates, suggest + rewrite
│   ├── controls.py      # ControlSpec registry (single source of truth)
│   ├── backgrounder.py  # Sim/household background writer
│   ├── scheduler.py     # Progressive background priority queue
│   └── budgeter.py      # Sliding-window + daily quota for backgrounds
├── tools/
│   ├── schemas.py       # JSONSchema per tool (THE tool contract)
│   ├── registry.py      # Autonomy level → tool-set mapping
│   └── rails.py         # Sidecar-side safety rails
└── observability/
    ├── logging.py       # Rotating file logger
    └── audit.py         # JSONL audit log of tool calls
```

---

## 5. Tool Arguments and Wire Protocol

- **Strict payload mapping:** The mod parses sidecar instructions manually (no
  Pydantic). When adding or modifying tools:
  - Define a **single, strict key** per argument in `sidecar/.../tools/schemas.py`.
  - Do **not** add aliases (e.g. `args.get("buff_name") or args.get("buff")`).
  - The mod's `tool_executor.py` reads exactly the keys from `schemas.py`.
- **JSON serialization:** In `http_client.py`, ensure no complex Sims 4 objects
  leak into payloads. Extract primitive values (`int`, `float`, `str`, `bool`,
  `list`, `dict`) inside `sim_context.py` or `state_collector.py` **before**
  returning them. `http_client._sanitize_payload` is the last-resort guard.
- **Every request carries `lang`** (a locale code from the manifest; shipped:
  `en`, `pt-BR`). Never hardcode a locale in logic — resolve via the manifest.
- **Non-LLM responses** may return `message_key` + `message_args` (the mod
  localizes via `i18n.t(key, **args)`).
- **Schema changes** always require updating both `schemas.py` (sidecar) and the
  corresponding handler in `tool_executor.py` (mod).

---

## 6. Type Hinting

- Follow standard Python type hinting conventions.
- **Never** use `lambda` for type aliases (e.g. `ToolFunc = lambda args: Dict`).
  Always use `from typing import Callable, Dict` and `ToolFunc = Callable[...]`.
- In the mod (3.7), use `typing.Union`, `typing.Optional`, `typing.Dict`, etc.
  Do **not** use `from __future__ import annotations` (see §3).
- In the sidecar (3.12+), modern syntax (`int | str`, `dict[str, Any]`) is fine.

---

## 7. Identifying Game States

- **Do not** rely on substring matches for identifying game states like buffs
  (e.g. `if "sleep" in buff_name`). This causes false positives with buffs like
  "Not sleeping well".
- Match exact known buff tuning IDs (`buff_Sleeping`, `moodlet_sleeping`, etc.)
  or Tuning IDs.
- See `state_collector._is_sleeping` for the validated pattern.

---

## 8. Configuration and Config Models

- **All** config lives in `config.toml` (loaded by `sidecar/.../config.py`).
- **Config model hierarchy** (`sidecar/.../config.py`):
  ```
  Settings
  ├── UiConfig           [ui]
  ├── NetworkConfig       [network]
  ├── LoggingConfig       [logging]
  ├── LLMConfig           [llm]
  │   └── ProviderConfig  [llm.providers.<name>]
  ├── MemoryConfig        [memory]
  ├── AgentsConfig        [agents]
  │   ├── EvolutionConfig [agents.evolution]
  │   ├── InitiativeConfig [agents.initiative]
  │   └── PersonalityConfig [agents.personality]
  └── GodConfig           [god]
      └── BackgroundsConfig [god.backgrounds]
  ```
- When adding a new config field: add it to the Pydantic model, document it in
  `config.example.toml`, and update `PLANO.md` Appendix A if significant.
- **ControlSpec** (`god/controls.py`) is the single source of truth for God dials.
  Adding a control = one `ControlSpec` entry + i18n keys. No router/UI rewrite.

---

## 9. Localization (i18n)

- **Data-driven locales.** The set of languages is described by a manifest, never
  hardcoded in code:
  - Mod UI: `mod/sensewright_mod/locales/manifest.json` (`{default, locales:[{code,
    name, match}]}`), loaded by `i18n.py` (filesystem **and** `.ts4script` zip).
  - Sidecar deterministic content: `sidecar/sensewright_sidecar/locales_content/`
    (`manifest.json` + `<code>.json`), loaded by `content_i18n.py`.
- **Two locales ship:** `en` (default, source of truth) and `pt-BR`. **No code
  references a specific locale** (`("en","pt-BR")`, `_LANG_NAMES`, `"pt-BR"`
  comparisons are forbidden). Language matching is driven by the manifest
  `match` tokens and is BCP-47 boundary aware (so `french` never matches `en`).
- **To add a language (no code change):** drop `locales/<code>.json` +
  `locales_content/<code>.json` (copy `en.json`, translate the values, keep every
  key and its `{placeholders}`) and append `{code, name, match}` to **both**
  manifests. `sw.lang <code>` and the panel pick it up automatically.
- **Every** player-facing string goes through `i18n.t(key, **args)` / the
  sidecar's `content_i18n.t(lang, key, **args)`. No hardcoded UI text, and no
  localized content strings inline in Python.
- **Key format:** dotted `snake_case`, grouped by domain:
  `cmd.*`, `notify.*`, `error.*`, `status.*`, `panel.*`, `god.*`.
- **When adding a feature:** add the key to every shipped locale JSON (a missing
  key falls back to the manifest default). `test_locales_parity.py` (mod) and
  `test_content_i18n.py` (sidecar) enforce key/placeholder parity across **all**
  manifest locales.
- **Code/docs/comments** are always in **English**.
- **LLM-generated content** is produced in `lang` (the sidecar receives it on
  every request). Prompt templates are English (for model quality).

---

## 10. Test Conventions

- **Sidecar tests:** `sidecar/tests/` — run with
  `cd sidecar; .\.venv\Scripts\python.exe -m pytest tests -q`
- **Mod tests:** `mod/tests/` — run with `python -m pytest mod\tests -q`
  (uses the system Python, not 3.7, since tests don't need the game runtime)
- **Current counts:** sidecar **463**, mod **384** (update when adding tests).
- **Every new feature should include tests.** Prefer unit tests; integration tests
  for wire/endpoint behavior.
- **CHANGELOG** (`CHANGELOG.md`) must be updated for every meaningful change.
  Follow the format: section header (`### Added` / `### Changed` / `### Fixed`),
  bullet points with enough detail for a developer to understand what changed.

---

## 11. The Sims 4 Community Modding Best Practices

- **Use injections over hard overrides:** Inject or wrap existing functions via
  decorators rather than overriding original methods. Prevents conflicts with
  other mods.
- **Stack base (S4CL + Lot 51):** do all library access through
  `integrations.py`. Pie-menu interactions use a tuning `.package`
  (`mod/tuning/**` + `build_package.py`) wired to targets by S4CL's
  `CommonInteractionRegistry` (`pie_menu.install`); the event bus / cadence is Lot
  51's. **XmlInjector is retired; the tuning `.package` is required.**
- **UI and Dialogs:** prefer the stack (S4CL notifications/dialogs) and fall back
  to TS4's native dialogs. We do not use Flash/GFX. See `chat_ui.py`,
  `dialogs.py` and `panel_ui.py`.
- **Installation structure:** The game only reads `.ts4script` files up to one
  subfolder deep inside the `Mods` folder.
- **Patch testing:** TS4 patches frequently break script mods. Always re-test
  after patches. Use **Better Exceptions** for deep debugging.
- **EA guidelines:** Mods must be accessible for free (though early access is
  temporarily allowed) and must not use official game logos/trademarks.
- **Alarms:** Use `alarms.add_alarm(owner, time_span, callback, ...)` — the
  top-level `alarms` module (not `sims4.alarms`). Alarms **require a live owner**
  (`AlarmHandle` raises if `owner` is `None`) **and the owner must be a live
  GameObject the alarm service advances** — the **active Sim instance** works;
  the zone/household/service managers may register a handle but never tick (this
  caused the v0.3 pulse/pull alarms to silently never fire). Use
  `events._resolve_alarm_owner` (active Sim instance first) and re-arm on zone
  load.
- **Events:** Register via `services.get_event_manager()` (not `sims4.event_manager`).
  `TestEvent` members live under `event_testing.test_events.TestEvent`.
- **Time spans:** Use `date_and_time.create_time_span(days, hours, minutes)` (not
  `sims4.math.TimeSpan`).

---

## 12. Known Gotchas (from live validation)

These bugs were found during in-game validation and are critical to avoid:

1. **`from __future__ import annotations` breaks TS4 command parsing.** The game
   introspects annotation types at runtime. Stringified annotations cause
   `isinstance(arg_type, type)` to fail, so typed parameters never parse.
   **Never** use this import in the mod.

2. **Services don't exist at script-mod load time.** `services.get_event_manager()`,
   `services.game_clock_service()`, etc. all return `None` at import. Use lazy
   resolution and the deferred-flush pattern in `events.py`. **The deferred flush
   only retries where `ensure_started()` is called**, so don't rely on command
   paths alone — `install_zone_hook()` drives the collector (via the **Lot 51
   `GAME_TICK`** when the library is present, else the native `zone.Zone.update`
   wrapper).

3. **Alarm owners must be live _and ticked_.** Passing `None` as the alarm owner
   raises `ValueError('Alarm created without owner')`. Use
   `events._resolve_alarm_owner()` (active **Sim instance** first); a zone/
   household/service owner may register a handle that never fires.

4. **Service accessors are functions, not values.** `services.client_manager` is
   a function — you must call `services.client_manager()`. Same for
   `sim_info.get_traits()`, `sim_info.get_mood()`, etc. Forgetting the `()` returns
   the bound method object instead of the result.

5. **Double `/v1` prefix.** `config.get_base_url()` returns the server root. The
   endpoint paths add `/v1/...`. If the base URL already ends in `/v1`, all
   requests hit `/v1/v1/...` (404). A regression test exists for this.

6. **Payload serialization.** `json.dumps(payload)` outside the try/except means
   a non-serializable game object raises `TypeError` before any request is sent.
   Always use `http_client._sanitize_payload` or ensure primitive coercion at
   the source.

7. **Gemini thinking budget.** Gemini 2.5+ models spend part of `maxOutputTokens`
   on internal thinking, truncating JSON. The provider disables it
   (`thinkingConfig.thinkingBudget = 0`).

8. **Buffs are `SimInfo.Buffs` (property), not `buff_component`.** The buff
   component is `objects.components.buff_component.BuffComponent`; active buffs are
   `BuffComponent._active_buffs` (handle id → `Buff`), and the tuning id is
   `Buff.buff_type.__name__` (e.g. `buff_Sleeping`). Detected live via the probe.

9. **Don't rely on game-clock alarms for the loop.** Alarms with `owner=object_sim`
   or `owner=Zone` registered but never fired live. The loop is driven by the
   **Lot 51 `GAME_TICK`** (`state_collector.install_zone_hook` →
   `events.register_lot51_tick`), with the native `zone.Zone.update` wrapper as
   fallback; start the collector only once the active Sim is instanced. See
   `docs/ts4_internals.md`.

10. **Tuning XML must be zlib compressed in the `.package`.** TS4 stores tuning as
    zlib-compressed XML, not raw XML. Uncompressed resources with the "uncompressed" flag
    are silently ignored by the game. Ensure your package builder compresses them (`zlib.compress(..., 9)`)
    and sets the correct index flag (`0x80000000 | compressed_size`).

11. **STBL language codes.** Localized names (like pie menu items) require string tables (STBL)
    where the language is the top byte of the instance (`0x00` for ENG_US, `0x11` for POR_BR).
    You must pack both STBLs if supporting both languages, otherwise the text will be blank.

12. **Never rewrite `.md`/`.json` with PowerShell `Set-Content -Encoding UTF8`.** The
    Windows PowerShell 5.1 encoder writes a BOM and, combined with mis-decoding, turns
    `—` into `â€"` and `§` into `Â§` (double-encoded UTF-8). This is how this very skill
    got corrupted. Use the editor/Write tools, a UTF-8 no-BOM .NET write
    (`[System.IO.File]::WriteAllText($p, $t, (New-Object System.Text.UTF8Encoding($false)))`),
    or Python `open(path, "w", encoding="utf-8")`.

13. **`.package` (DBPF) header.** The index offset lives at `0x40` (64-bit) and the
    field at `0x28` must be written as `0` (matches S4S-built packages). A wrong
    index/offset makes the game silently ignore the package.

14. **Alarm callbacks must accept `*args`.** The game passes the `AlarmHandle` to the
    callback; a zero-arg callback raises `TypeError` on fire (fixed in build `.13`).

15. **Pie-menu interactions use S4CL registration + a tuning package
    (XmlInjector retired).** A bare interaction tuning is never offered, and S4CL
    does **not** register custom interaction *classes* — `CommonInteractionRegistry`
    only adds interaction *tuning ids* to script objects. A custom interaction
    therefore needs a tuning resource (`mod/tuning/interactions/*.xml`, built into
    `dist/Sensewright.package` by `mod/build_package.py`) whose `m`/`c` point at the
    S4CL interaction classes; `pie_menu.install` then registers
    `CommonScriptObjectInteractionHandler`s (`CommonInteractionType.ON_SCRIPT_OBJECT_LOAD`)
    for Sims and for `Func_Computer` objects. **Live-validation risk:** the S4CL
    registry path/name and the packaged-STBL display names (`sw.lang`) must be
    confirmed in-game — see `docs/stack_migration.md`.

16. **Never hardcode locales.** Do not write `("en","pt-BR")`, `_LANG_NAMES`,
    `if lang == "pt-BR"`, or inline Portuguese/English content strings in code.
    Locales are data-driven (manifests + JSON tables; see §9). Compare only against
    `i18n.available_locales()` / `content_i18n.default_lang()`. A short token like
    `en` must match on a BCP-47 boundary (else `french` false-matches `en`).

17. **All stack access goes through `integrations.py`.** Never
    `import lot51_core` / `import sims4communitylib` elsewhere. The helpers are
    guarded and return `None`/`False` when a library is missing (the offline test
    host has neither), so features degrade instead of crashing.

---

## 13. Build and Deploy

There are **two artifacts** to rebuild on a mod change (S4CL needs a tuning
`.package` for the custom interactions; XmlInjector is retired):

```powershell
py -3.7 mod\build.py            # -> dist\Sensewright.ts4script + dist\Sensewright.package
powershell -ExecutionPolicy Bypass -File scripts\install-mod.ps1   # copies both + sidecar
```

- **Script mod:** `mod/build.py` compiles with Python 3.7 and then calls
  `build_package.py`. The bytecode magic must be `42 0d 0d 0a` (3.7). Use
  `--allow-any-python` only for dev builds.
- **Tuning package:** `mod/build_package.py` writes `dist/Sensewright.package`
  (pure-Python DBPF) from `mod/tuning/interactions/*.xml` + `mod/tuning/stbl.json`.
  No XmlInjector snippet is shipped.
- **Stack libraries:** the player installs **S4CL** and **Lot 51 Core** at the Mods
  root (top level or one folder deep). Sensewright no longer ships a `.package` or
  requires XmlInjector.
- **Sidecar:** runs **from source** with the workspace venv (no PyInstaller yet —
  Phase 6). The mod **autoboots** it: `install-mod.ps1` writes the venv interpreter
  to `sidecar/python.txt` and `config.find_python()` reads it; it auto-exits with
  the game. Reinstall after any venv change.
- **Install:** `scripts/install-mod.ps1` copies the `.ts4script` + sidecar into
  `Mods\Sensewright\`, and warns when the stack libraries (S4CL / Lot 51 Core) are
  missing from the Mods root.
- **Health check:** `scripts/doctor.ps1` (`make doctor`) validates the environment;
  `make status` / `GET http://127.0.0.1:8765/v1/health` checks a running sidecar.
- **Dev loop:** `scripts/dev.ps1` (`make dev`) is the development helper.

**Makefile targets** (thin wrappers; use the PowerShell scripts directly on Windows):

| Target | Does |
|---|---|
| `make install` | `uv sync --extra dev` in `sidecar/` |
| `make run` | run the sidecar (`uv run python -m sensewright_sidecar`) |
| `make build-mod` | build the `.ts4script` artifact |
| `make install-mod` | `scripts/install-mod.ps1` |
| `make check` | sidecar + mod pytest |
| `make doctor` / `status` / `logs` / `dev` | env check / health / tail log / dev helper |

**Game internals:** decompile the shipped scripts with
`scripts/decompile-scripts.ps1` into the gitignored `research/ts4/`; the
confirmed APIs live in **`docs/ts4_internals.md`**. Read those before wiring a
new game API.

---

## 14. v0.3 Direction (Inhabited Agents) — R2–R6 done, R7 in progress

> **Live-validated:** R2 (agent seats/eviction), R3 (intents), R4 (cognition/daily
> plan), R5 (sim↔sim channel — `[validate] social: 1 dialogue pair(s)`), R6 (God
> director scoping), plus the pie menu, lifecycle, and zone heartbeat.
> **God orchestration (Phase 5c) is now wired in the mod:** `state_collector.
> maybe_god_tick` polls `POST /v1/god/tick` from the zone heartbeat and executes
> the returned directives; `sw.god on|off|tick|scan|preset|set` controls it, and
> `scan_neighborhood` maps the full-save census (kinship included). Needs a live
> re-check.
> **R7 (native config panel):** P1 is done (sidecar `ControlSpec`
> `target`/`path` promotion + `data/panel.toml` overlay + i18n; `ui.language`
> options are data-driven). **P2 (in-game panel) is now implemented on the stack
> base** — `mod/sensewright_mod/panel_ui.py` (sections from `GET /v1/god/controls`,
> S4CL dialog + console fallback), `sw.panel` cheat and a pie-menu entry. Live
> validation of the S4CL dialog navigation is pending.
> **R1 (native `say_to` lever spike)** still needs live runtime validation, as do
> the `.22` player-activity detection + precise `cancel_current` changes.
> Files: `agent/seats.py`, `agent/intents.py`, `agent/cognition.py`,
> `agent/social.py`, `agent/context_forge.py`, `graph.py`,
> `routers/autonomy.py`, `config.py`, plus the mod's `execute_intent` +
> `sw.agents`. The rest of this section is the design context.

The mod is transitioning from **command-centric** (LLM emits tool calls that puppet
the Sim) to **inhabitation + nudge** (biasing native autonomy):

- **SeatManager:** Pool of N agent seats; active household > visitors; eviction on
  lot exit; memory persists without a seat.
- **IntentBus:** Replaces the pending-directive store. Intents are validated by
  rails + coordinator, then translated by a **GameLever** adapter.
- **CognitiveLayer:** Each layer (perception, seats, intent/bias, memory, cognition,
  social, God) has a budget, cadence, and deterministic fallback.
- **Intent model:** Agents emit intents (not commands). Each intent carries a
  native-lever payload and a lifecycle (`expires_at`).
- **Sim↔Sim dialogue channel:** Two agent-owned Sims get a real conversation.

Implementation phases: R1 (lever spike) → R2 (seats) → R3 (intents) → R4
(cognition) → R5 (sim↔sim) → R6 (God director) → R7 (panel).

See `PLANO.md` §15 for the full design.

---

## 15. Task Recipes and Definition of Done

Checklists for the most common changes. Keep the two packages in lock-step.

### 15.1 Add a tool (LLM → in-game action)

1. **Sidecar contract:** add one **strict** schema in `tools/schemas.py` (single
   key per argument, no aliases) and map it to autonomy levels in
   `tools/registry.py`. Add a sidecar-side guard in `tools/rails.py` if needed.
2. **Mod handler:** implement it in `tool_executor.py`, reading **exactly** the
   schema keys. Return primitives only.
3. **Safety:** guard game APIs (`_safe_call`/`_safe_getattr`), never raise, and
   log failures via `debug_log`/`validation_log`.
4. **Mod rail:** add rate-limit/never-tool entries in `mod/.../rails.py`.
5. **i18n:** if it surfaces text, add `notify.*`/`error.*` keys to **both**
   locales.
6. **Tests:** sidecar (schema/registry) + mod (`tool_executor`) tests.
7. **Docs:** `CHANGELOG.md`; update `PLANO.md` if the wire contract changed.

### 15.2 Add a config field

1. Add it to the Pydantic model in `sidecar/.../config.py`.
2. Document it in `config.example.toml`.
3. If a player/God dial: add a `ControlSpec` in `god/controls.py` (`target`/`path`,
   `restart_only`) + `god.control.*` i18n keys.
4. Update `PLANO.md` Appendix A if significant. Add tests + `CHANGELOG.md`.

### 15.3 Add i18n keys

- `en.json` is the **source of truth**; mirror every key in `pt-BR.json`.
- Key format: dotted `snake_case` with a domain prefix (`cmd.*`, `notify.*`,
  `error.*`, `status.*`, `panel.*`, `god.*`).
- Mod code uses `i18n.t(key, **args)`; **never** hardcode UI text.
- `mod/tests/test_locales_parity.py` guards en/pt-BR parity.

### 15.4 Definition of done

- [ ] Sidecar tests green: `cd sidecar; .\.venv\Scripts\python.exe -m pytest tests -q`
      (currently **463**).
- [ ] Mod tests green: `python -m pytest mod\tests -q` (currently **384**).
- [ ] Lint clean (sidecar: ruff). Mod compiles with `py -3.7 mod\build.py`.
- [ ] `CHANGELOG.md` updated under `[Unreleased]` (Added/Changed/Fixed).
- [ ] If tests were added, update the counts in §10 of this skill.
- [ ] For any mod/game change: build **both** artifacts, run `scripts/install-mod.ps1`,
      **restart the game** (script mods load only at boot), validate live, then
      update `docs/STATUS.md` (§4/§5) and the current TODO.
