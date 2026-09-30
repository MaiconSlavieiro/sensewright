# Sensewright — Planning Document (v1.6)

Mod for **The Sims 4 (PC/Windows)**: autonomous LLM-driven Sim agents, a configurable
"God" orchestrator Agent, and expanded intelligence for the player-controlled Sim.

> **Document version:** v1.6 (2026-09-27). Project release version is **0.1.0**
> (Phase 1). Feature milestones: v0.2 (§14 "Living Sim Agents") and v0.3 (§15
> "Inhabited Agents") describe forward plans with increasing scope.
>
> **Implementation status** (see `CHANGELOG.md` for the living log):
>
> | Scope | State |
> |---|---|
> | Phases 1–5c (skeleton → God orchestration) | Sidecar + mod **code complete**; most items pending **in-game validation** |
> | v0.2 §14 (M1/M2, A1–A3, P1, G1) | Sidecar + mod **code complete** + unit/graph tested; live-save cadence tuning pending |
> | In-game spike | `sw.chat`/`sw.status`/`sw.profile` round-trip validated; event/alarm APIs wired to the real TS4 names; alarms fire with a live owner; census/autonomy tick reach the sidecar |
> | Provider chain | `openrouter → opencode → gemini` (Groq removed); OpenRouter `:free` + free_only guard validated; OpenCode Zen restricted to `space-bunny-free` from external clients |
> | v0.3 §15 ("Inhabited Agents") | **R2 seats + R3 intents + R4 cognition + R5 sim↔sim** implemented; R1 + R6/R7 verified; the in-game **configuration panel** is specified in `docs/ui_panel.md` (**native dialogs; no Flash, no slider**) |
> | Phase 6 (publishing) | Not started |
>
> **Pending in-game validation:** live alarm/event behavior, interaction queue APIs
> (`push_super_affordance`, `move_to`, `say_to`), God UI dialogs, census cost on
> large saves, background pipeline cadence tuning, player-activity detection signal.
>
> **Direction (v0.3 §15 "Inhabited Agents"):** the mod moves from a
> **command-centric** loop (LLM emits tool calls that puppet the Sim) to an
> **inhabitation + nudge** model — a configurable pool of *agent seats* biases the
> game's native autonomy ("changes of route") instead of issuing every action; cognition
> runs mainly at sleep, with per-agent impulse frequency exposed in an agent-roster panel;
> and two agent-owned Sims get a real sim↔sim dialogue channel. §14 (v0.2) is retained as
> the foundation; §15 defines what is **kept, absorbed or replaced** item by item.
>
> **Scope:** target architecture (v1 → v0.3) of the mod, fundamentals of the TS4
> engine, provider strategy, performance, fallbacks, phases and risks.
>
> **Conventions:** all code, docs and code comments are written in **English**.
> Player-facing text is localized via the locale system (English default, pt-BR supported).

---

## Table of Contents

1. [Vision and Pillars](#1-vision-and-pillars)
2. [TS4 Engine Fundamentals](#2-ts4-engine-fundamentals)
3. [Overall Architecture](#3-overall-architecture)
4. [Localization (i18n)](#4-localization-i18n)
5. [Provider and Fallback Strategy](#5-provider-and-fallback-strategy)
6. [Anti-Lag Strategy (performance)](#6-anti-lag-strategy-performance)
7. [Data Model and Evolution](#7-data-model-and-evolution)
8. [Configurable God Agent](#8-configurable-god-agent)
9. [Wire Protocol (summary)](#9-wire-protocol-summary)
10. [Security and Privacy](#10-security-and-privacy)
11. [Implementation Phases](#11-implementation-phases)
12. [Risks and Mitigations](#12-risks-and-mitigations)
13. [Next Steps](#13-next-steps)
14. [Autonomous Sim Agents (v0.2)](#14-autonomous-sim-agents-v02)
15. [Inhabited Agents (v0.3)](#15-inhabited-agents-v03)
16. [Appendices](#16-appendices)

---

## 1. Vision and Pillars

| Pillar | Description |
|---|---|
| **P1 — Autonomous Sim agents** | A profile created from 1 sentence; they act freely in the game; they **evolve** (personality, memory, traits) as they interact with other Sims and the world. |
| **P2 — Configurable God agent** | Owns the neighborhood **zeitgeist** (storytelling/mood layer), writes a background for every Sim and household, and orchestrates the world: spawns Sims, applies traits/buffs, forces interactions, spreads events. **Configuration panel** with presets, toggles and native-dialog controls (no drag sliders — see `docs/ui_panel.md`). |
| **P3 — Smarter player Sim** | Persistent memory, own personality, free chat (locale-driven language, English default). |

### 1.1 Project constraints

- **5–15 agents** active simultaneously.
- **Cloud free-tier APIs only** for the Sims; the God agent may use a cheap paid API.
- **Zero perceptible stutter** — the game never blocks waiting on an API call.
- **Very low-friction install** — autoboot, 1 folder, optional keys.
- **Publishable to the community** — clean packaging, docs, configuration GUI.
- **Language:** all in-game player-facing text goes through the **locale system**
  (`en` default, `pt-BR` also shipped). Code, docs and code comments are always in English.

### 1.2 Non-goals (v1)

- Changing the game's save format or replacing EA persistence.
- Multiplayer / shared worlds.
- Voice synthesis (future roadmap).
- Replacing cheats (`motherlode` etc.) — the agent has read access plus a curated, gated surface.

---

## 2. TS4 Engine Fundamentals

> Research into the internal architecture of TS4 and the TRD of the equivalent
> `sims4ai` project. These facts shape the entire mod architecture.

### 2.1 Execution model

| Fact | Impact on the mod |
|---|---|
| **Python 3.7 sandbox, stdlib only** (`urllib`, `json`, `threading`, `os`, `re`). No `requests`/asyncio. | All heavy work runs in the sidecar (external process). |
| **Game clock** (`game_clock_service`, sim-time with speed multiplier) ≠ wall clock. | Mod timers use **`sims4.alarms.add_alarm`** (respect pause). **Never** `threading.Timer`. |
| **Single zone/lot loaded at a time**; off-zone Sims are "uninstanced". | State reads via `SimInfoManager` (sim_info) are cheap and safe; `get_sim_instance()` may be `None`. |
| **Main thread with GIL**; frame callbacks are the lag path. | **Forbidden** to do heavy work in frame callbacks; only fast reads + scheduling. |
| **`.ts4script` is a zip of the Python package**; I/O restricted to the mod's own folder. | Memory persistence is NOT in the game — it lives in the sidecar's SQLite. |
| **Game UI:** `UiDialogNotification` → `UiDialogOkCancel` → console. | Chat rendered in 3 layers with fallback. |

### 2.2 Native levers (the "Tier 0", zero API)

The game has an **autonomy engine based on scoring**. That is exactly where the
personality generated by the LLM is "written" — without touching the real-time loop.

| Native system | What it does | Our use |
|---|---|---|
| **Autonomy scoring** (`autonomy_service`, motive commodities, `AutonomyGroup`, `TestBasedScore`) | Each interaction scores; highest wins; motives (hunger, energy, fun…) push scores. | The engine decides the action in **0 ms**. |
| **Traits with autonomy modifiers** | Traits change scoring globally (e.g. "Ambitious" → more work). | LLM proposes a trait → behavior changes long-term. |
| **Buffs (moodlets)** | Change mood and can alter scoring/commodities for a while. | LLM "colors" the emotional state (short-term). |
| **Whims/wants** | Goals that steer autonomy and grant points. | LLM suggests "wants" → direction without direct command. |
| **Interaction queue** (`sim.queue`, `push_super_affordance`) | The Sim's interaction queue. | Explicit directives: `queue_interaction`, `move_to`, `say_to`, `cancel_current`. |
| **Event system** (`event_manager` + `test_events`: zone load, sim spawn, social, relationship, buff) | Callbacks when something happens. | **Event-driven** instead of polling — lower cost, more precision. |

### 2.3 Verification checklist (Phase 0 — spike in the real game)

> Validated statically against the scripts shipped with the live client
> (patch 1.113.277.1030) — `Game/Bin/Python/generated.zip` and
> `Data/Simulation/Gameplay/{base,core,simulation}.zip`. Items still marked `[ ]`
> need an in-game measurement or a live interaction that scripts cannot prove.

- [x] **Alarms — game-clock timers.** Module is the top-level **`alarms`** (there is
      no `sims4.alarms`): `add_alarm(owner, time_span, callback, repeating=False,
      repeating_time_span=None, use_sleep_time=True, cross_zone=False)`; build the
      span with **`date_and_time.create_time_span(days, hours, minutes)`**. Wired in `events.py`.
- [x] **Event registration + names.** Manager from **`services.get_event_manager()`**
      (`EventManagerService`, no `sims4.event_manager`); register with
      `register_single_event(handler, event_type)` and unregister with
      `unregister_single_event(handler, event_type)`. `TestEvent` members live under
      **`event_testing.test_events.TestEvent`**: `BuffBeganEvent`/`BuffEndedEvent`,
      `RelationshipChanged`, `InteractionComplete`, `TraitAddEvent`/`TraitRemoveEvent`,
      `SkillLevelChange`, `CareerEvent`/`CareerPromoted`, `SimDeathTypeSet`,
      `HouseholdChanged`, `LoadingScreenLifted`/`SimHomeZoneChanged`/`SimTravel`. Wired in `events.py`.
- [ ] Autonomy scoring hooks (traits/buffs/whims; interaction injection with autonomy).
- [x] `sim_info.add_trait/remove_trait`, `add_buff` exist (C-backed `*args/**kwargs`
      forwarders in `SimInfoMixin`); trait availability by DLC still to check.
- [x] Queue primitives exist: `InteractionQueue.insert_next` / `cancel_all` (the
      `sim.queue` surface); `push_super_affordance`/`move_to`/`say_to` still to confirm in-game.
- [ ] NPC spawn: `sim_spawner_service` / `household_manager.create_household`.
- [x] Active zone id read via `Zone.save_slot_data_id`; save-GUID keying still to confirm.
- [x] `@sims4.commands.Command` + `CheatOutput(context)(msg)` / `commands.cheat_output(s, context)`
      for cheats/console output (validated in-game: `sw.help` renders).
- [~] `UiDialogNotification` for chat rendering: `chat_ui.py` attempts it with
      console fallback; native dialog constructor signatures vary by patch, not
      yet confirmed live.
- [ ] Current whims/wants API (current patch).
- [x] **Locale read API:** `services.get_locale()` / `client.account.locale` and
      `SimSpawner.LOCALE_MAPPING` work; `i18n._detect_game_locale()` confirmed
      in builds `.6`/`.7`. Fallback to `en` on detection failure is wired.
- [x] **Household / new-Sim detection:** `TestEvent.HouseholdChanged` is the reliable
      household signal; there is no CAS/spawn TestEvent, so zone-load **census diff**
      remains the fallback (as planned).
- [ ] **Native dialogs for God UI:** `UiDialogTextInput` (free text) and a multi-choice /
      multi-select dialog for the 7 mood tags; constructor signatures vary by patch.
      Fallback: sequential single-choice dialogs + cheat input (`sw.zeitgeist`).
- [x] **UI feasibility (settled):** TS4 has **no scriptable slider**; the panel uses
      native dialogs only (picker/list rows, paginated responses, numeric input,
      multi-select) — see `docs/ui_panel.md`. No S4CL/Lot51/Flash dependency.
- [x] **Genealogy read:** `sim_info.genealogy` and `sim_info.household`/`household_id`
      exist; cost over large saves still to measure.
- [ ] **Census cost:** collecting traits/kinship for big saves (50–100+ Sims) — measure
      the per-zone read and keep it off the frame path.

### 2.4 Development stack

| Layer | Stack |
|---|---|
| **In-game** | Python 3.7 (from the game) + stdlib + game APIs. No external deps. |
| **Sidecar** | Python 3.12 + FastAPI + Pydantic v2 + httpx + SQLite (stdlib). Managed with `uv`. |
| **Mod build** | `build.py` invokes **Python 3.7.9** (last 3.7 with Windows installers; bytecode magic `42 0d`) → `.pyc` → zip `.ts4script`. |
| **Sidecar build** | PyInstaller → `Sensewright-sidecar.exe` (bundles Python + deps). |
| **Decompilation** | `decompile_scripts.py` (s4cl-template-project) → stubs as Sources Root. |
| **IDE** | PyCharm (community standard); VS Code for the sidecar. |
| **Modding lib** | Core with **no dependencies**. UI uses the game's **native dialogs** (`docs/ui_panel.md`); S4CL/Lot51/Flash only if native proves insufficient. |

---

## 3. Overall Architecture

### 3.1 Two-process structure (autoboot)

```
Mods/Sensewright/                         ← install = drag 1 folder
├─ Sensewright.ts4script                  (in-game mod, Python 3.7)
├─ sidecar/Sensewright-sidecar.exe        (PyInstaller: Python 3.12 + FastAPI + httpx + SQLite)
└─ sidecar/config.toml                  (optional keys + presets)
```

### 3.2 Boot flow

1. Mod loads (the only moment script mods load) → **ping** `127.0.0.1:8765`.
2. No response → **spawn `Sensewright-sidecar.exe`** via `subprocess`
   (hidden window with `CREATE_NO_WINDOW`, fire-and-forget). The game never waits.
3. No sidecar/API → **native mode** (graceful degradation; the mod stays functional).
4. Cheat `sw.start` for manual boot; file log (`sidecar.log`) for debugging without a console.
5. **Shutdown:** the mod passes its own PID (`SENSEWRIGHT_GAME_PID`) when spawning; a
   watchdog in the sidecar (`lifecycle.py`) watches that PID and stops the server
   when the game exits, so the sidecar never lingers. An already-running sidecar is
   armed at boot via `POST /v1/lifecycle/attach`.

### 3.3 Responsibility split (strict contract)

| Responsibility | `.ts4script` (game) | Sidecar (host) |
|---|:---:|:---:|
| Reading live game state | ✓ (the only place possible) | ✗ |
| UI (notifications, dialogs, cheats) | ✓ | ✗ |
| **Execution** of tools (queue, buff, trait, walk, say) | ✓ | ✗ |
| Orchestration, prompt assembly, decision | ✗ | ✓ |
| Model selection, retries, fallback, budgeter | ✗ | ✓ |
| Memory (SQLite), reflection, evolution | ✗ | ✓ |
| Autonomy gating, rate limits, safety rails | ✗ | ✓ |
| Localization of player-facing strings | ✓ (renders) | ✓ (defines/returns keys) |

The sidecar **never** imports game modules; the `.ts4script` **never** imports third-party libs.

### 3.4 Module map

**In-game (`Sensewright.ts4script`):**

```
sensewright_mod/
├── __init__.py          # registers cheat commands
├── config.py            # sidecar URL + timeouts (reads port/token/lang)
├── debug_log.py         # gated best-effort logging to sensewright_output.log
├── i18n.py              # locale loader + t(key, **args) + game-language detection
├── locales/
│   ├── en.json          # default locale (source of truth)
│   └── pt-BR.json       # Brazilian Portuguese translation
├── main.py              # @sims4.commands.Command bindings
├── sim_context.py       # collects state (mood, needs, traits, skills, careers,
│                        #   relationships, queue, location, clock, funds);
│                        #   primitive-coerced, never leaks game objects
├── state_collector.py   # zone pulse/alarms, census builder, event ingestion,
│                        #   directive pull loop, sleep detection
├── events.py            # event subscriptions + alarms (event-driven collection)
├── http_client.py       # POST via urllib; typed errors; payload sanitization
├── tool_executor.py     # dispatches tool_calls → local functions → POST result
│                        #   (strict keys mirroring tools/schemas.py)
├── rails.py             # mod-side rate limit + player-priority lock + never-tools
├── chat_ui.py           # UiDialogNotification → UiDialogOkCancel → console
├── god_ui.py            # zeitgeist onboarding / household background dialogs
├── player_activity.py   # wraps Sim.push_super_affordance → player-priority lock
└── probe.py             # sw.probe: live autonomy dump (dev, R1/F1)
```

**Sidecar (`sensewright_sidecar`):**

```
sensewright_sidecar/
├── server.py            # FastAPI app + lifespan (starts graph, scheduler)
├── config.py            # Pydantic Settings, config.toml loader + env expansion
├── schemas.py           # Pydantic v2 wire models (shared contract with the mod)
├── auth.py              # shared-token auth (X-Sensewright-Token), runtime.json
├── lifecycle.py         # game-process watchdog: exit with The Sims 4
├── locales.py           # system-message localization for UI/returned keys
├── routers/
│   ├── admin.py         # /v1/config/*, /v1/reset, /v1/events
│   ├── autonomy.py      # /v1/autonomy/tick, /v1/autonomy/directives
│   ├── chat.py          # /v1/chat, /v1/hey
│   ├── deps.py          # FastAPI Depends helpers (auth)
│   ├── events.py        # /v1/events (game event ingestion)
│   ├── god.py           # /v1/god/*, /v1/census
│   ├── health.py        # /v1/health, /v1/status
│   ├── lifecycle.py     # /v1/lifecycle/attach
│   └── profiles.py      # /v1/profile
├── agent/
│   ├── graph.py         # state machine (recall → plan → model → tools → consolidate)
│   ├── nodes.py         # graph nodes
│   ├── state.py         # AgentState, Turn, Memory, ToolCall
│   ├── prompts.py       # base personality, prompts (language-aware)
│   ├── profiler.py      # 1-sentence → full profile JSON (Phase 3)
│   ├── evolution.py     # reflection loop + personality drift + trait-swap (Phase 4)
│   ├── personality.py   # psyche + life_story + sleep consolidation (v0.2 P1)
│   ├── agency.py        # Agency scheduler + pending directives + pull (v0.2 A2)
│   ├── coordinator.py   # single-writer arbitration: agent vs God (v0.2 A2)
│   ├── initiative.py    # LLM impulse prompt + tool calls (v0.2 A3)
│   └── memory_fallback.py # deterministic memory-based fallback when no LLM
├── llm/
│   ├── base.py          # LLMProvider protocol, capability flags
│   ├── chain.py         # ordered fallback + circuit breaker + RPM/RPD skip
│   ├── limits.py        # per-provider RPM/RPD rate limiter
│   ├── budgeter.py      # per-Sim daily request cap (Phase 3)
│   ├── registry.py      # auto-discovery of free models (GET /models)
│   └── providers/
│       ├── openai_compat.py  # OpenAI-compat base + OpenCodeZenProvider
│       ├── openrouter.py     # OpenRouter (:free, free_only guard)
│       ├── gemini.py         # Gemini (free tier, last resort)
│       └── deepseek.py       # DeepSeek (paid, God)
├── memory/
│   ├── base.py          # MemoryProvider protocol, MemKey
│   ├── sqlite_store.py  # default: SQLite + embeddings + decay columns
│   ├── embeddings.py    # Cloudflare BGE-M3 (free) + lexical fallback
│   ├── consolidation.py # M1: dialogue → consolidated_memory event
│   └── decay.py         # M2: strength decay, touch, déjà vu, pruning
├── god/
│   ├── orchestrator.py  # God Agent loop (preset deck, dials, intervention pick)
│   ├── interventions.py # intervention deck (presets/sliders/toggles)
│   ├── world_model.py   # world model (census → WorldState, aggregates)
│   ├── zeitgeist.py     # tags, templates, agent suggest + rewrite (Phase 5a)
│   ├── controls.py      # ControlSpec registry (single source of truth)
│   ├── backgrounder.py  # Sim/household background writer (Phase 5b)
│   ├── scheduler.py     # progressive background priority queue (Phase 5b)
│   └── budgeter.py      # sliding-window + daily quota for backgrounds (Phase 5b)
├── tools/
│   ├── registry.py      # autonomy → tool-set mapping
│   ├── schemas.py       # JSONSchema per tool (shared with the mod)
│   └── rails.py         # sidecar-side safety rails (never-tools, rate limit, audit)
└── observability/
    ├── logging.py       # rotating file
    └── audit.py         # audit log of tool calls
```

---

## 4. Localization (i18n)

> **Decisions:** the mod ships with **two locales**: `en` (default) and `pt-BR`.
> Every player-facing string used inside the game is localized; no user-visible text
> is hardcoded. Code, docs and code comments are always English.

### 4.1 Principles

1. **Single source of truth:** `en.json` is the reference locale. Every other locale is
   a translation of the same key set. A missing key in any locale falls back to `en`.
2. **No hardcoded UI text:** every in-game string (cheat help, notifications, errors,
   dialog titles/buttons, config panel labels, status text) goes through `t(key, **args)`.
3. **Content vs. chrome:** "chrome" (UI/system text) is localized by the locale system.
   LLM-generated content (Sim dialogue) is produced in the **active language** passed to
   the sidecar; it is not translated after the fact.
4. **English default:** unknown/unsupported game languages resolve to `en`.

### 4.2 Locale resolution order

For in-game "chrome" text:

1. Explicit override in `config.toml` → `[ui] language = "en" | "pt-BR" | "auto"`.
2. If `auto`: detect the current game language and map it to a supported locale.
3. Unsupported / detection failure → `en`.

For LLM content (dialogue, reflections, generated profiles):

1. Explicit override `[ui] language` when not `auto`.
2. Otherwise the resolved game language (`en` fallback).
3. The sidecar always receives `lang` in every request and must produce content in it.
   Prompt templates are English (for model quality) and instruct output in `lang`.

### 4.3 Locale file format

Locale files are JSON, bundled inside the `.ts4script` under `sensewright_mod/locales/`.
The format is flat with IDE-friendly dotted keys:

```json
{
  "_meta": { "locale": "en", "name": "English", "version": "0.1.0" },
  "cmd.help.title": "Sensewright commands",
  "cmd.help.body": "sw.chat <text> — chat with the selected Sim\n...",
  "notify.no_sidecar": "Sensewright: sidecar is not running. Starting it…",
  "error.brain_foggy": "My brain is foggy, try again.",
  "status.providers": "Providers: {providers}"
}
```

Rules:
- Keys use `snake_case` segments joined by dots, grouped by domain prefix
  (`cmd.*`, `notify.*`, `error.*`, `status.*`, `panel.*`, `god.*`). The `god.*`
  domain covers the zeitgeist onboarding, background prompts, the 7 mood tags and
  the control labels/descriptions rendered by the config panel.
- Placeholders use `{name}` and are formatted with `str.format`-style arguments.
  Values must be HTML/newline-safe for the game notification renderer.
- `_meta` is required and identifies the locale.

### 4.4 Language selection UI

- **Config file:** `[ui] language = "auto" | "en" | "pt-BR"` (default `auto`).
- **In-game cheat:** `sw.lang en` / `sw.lang pt-BR` / `sw.lang auto` (persists to config).
- **God panel (Phase 5):** a language dropdown alongside the other settings.
- Changing language takes effect immediately (locales are reloaded) and is also sent to
  the sidecar (`/v1/config/lang` or per-request `lang`) so LLM content matches.

### 4.5 Wire protocol impact

- Every request carries `lang` (BCP-47: `en`, `pt-BR`).
- Non-LLM system responses may return a `message_key` + `message_args` instead of a
  human string; the mod localizes it through `i18n.t`. LLM `reply` is already localized
  content (produced in `lang`).
- The sidecar keeps its own `locales.py` only for its own diagnostics/notifications; the
  canonical locale data for the game UI lives with the mod.

---

## 5. Provider and Fallback Strategy

### 5.1 Three levels of friction

| Level | User setup | Result |
|---|---|---|
| **0 keys** | Nothing | Mod works: native autonomy + **embedded template profiles** (pre-generated JSONs) + rule-based evolution. Already playable. |
| **1 key (recommended)** | Paste an **OpenRouter** key into `config.toml` | Full LLM: dozens of free models on one endpoint (deepseek, qwen, gemini, llama). In-game notification guides the step. |
| **2–3 keys (boost)** | + Gemini (quality) and/or OpenCode Zen (extra free tier) | Maximum quality/speed. All optional, in any order. |

### 5.2 Provider matrix

| Layer | Primary | Backup | Role |
|---|---|---|---|
| **Real-time chat** | OpenRouter `:free` (most stable free tier; ~20 RPM, 50 RPD → 1,000 RPD with ≥$10) | OpenCode Zen free (space-bunny-free) → Gemini Flash free | Low latency |
| **Evolution/reflection** (background, batch) | OpenRouter `:free` (deepseek/qwen) | Gemini Flash free → OpenCode Zen free | Quality, batch |
| **Semantic memory** | Cloudflare Workers AI (BGE-M3 embeddings, 10K neurons/day free) | local lexical fallback | Free memory search |
| **God/orchestrator** | **DeepSeek v4-pro (paid, cents)** | deepseek-flash | Reasoning, 1M context |

**Default chain order:** `openrouter → opencode → gemini`. Google AI Studio is
**demoted to last resort** (kept, not removed) because its free tier rate-limits hardest.
Providers without a key are skipped, so listing more than you configured is safe.

**OpenCode Zen (optional power tier).** The [OpenCode Zen](https://opencode.ai/zen) gateway
is OpenAI-compatible (`https://opencode.ai/zen/v1`, Bearer token) and wired in as the
`opencode` provider. It requires a Zen key, so it never replaces the 0-key native mode.
**Caveat (validated live):** Zen's *free tier* is restricted to the OpenCode client —
external calls return HTTP 403 `FreeTierError` — so only **`space-bunny-free`** works from
the sidecar (pt-BR text + tool calling validated); the other `*-free` slugs (MiMo, Nemotron,
LongCat) do **not**. Paid Zen models work but are billed.

**Fallback is two-level.** Within a provider the chain walks `model` + `models` in order
(a 429/unavailable model tries the next one), then falls through to the next provider. Per
provider, `rpm`/`rpd` are enforced by a `ProviderRateLimiter`: a provider about to exceed its
cap is skipped rather than burned into a 429. The agency scheduler paces on the chain's
primary RPM. OpenRouter sets `free_only = true`, so only model ids containing `:free` are
ever called — a hard billing guard (validated: pt-BR text + tool calling via
`nemotron-3.5-lightning:free`).

**Extra secondaries (aspirational, no code yet):** Cerebras free (speed), Hugging Face Inference (niche), NVIDIA NIM (optional),
Z.ai GLM free (character voice/roleplay), Mistral free (creativity).

**Excluded:** GitHub Models (retired on 2026-07-30), Together AI (no clear free tier), local Ollama (user chose cloud).

### 5.3 Fallback chain (5 layers)

```
1. Provider   : primary → backup → tertiary (skips a provider at its RPM/RPD cap;
                circuit breaker: 3 failures = 60 s cool-down, retest after the window)
2. Model      : per-provider multi-model fallback (`model` + `models` in order,
                a 429/unavailable model tries the next) + auto-discovery (GET /models)
3. System     : no LLM at all → native autonomy + rules (the mod NEVER dies)
4. Sidecar    : spawn failed → manual sw.start → run the .exe by hand → log guides
5. Language   : weak locale → auto English prompt
```

### 5.4 Budgeter and economy

- Per-provider quotas (`rpm`/`rpd`) enforced by `ProviderRateLimiter` in the chain; the
  agency scheduler paces on the chain's primary RPM (`Agency.set_registry`).
- `free_only` guard on OpenRouter: only `:free` model ids are ever called (no billing).
- Per-Sim priority queue.
- **Aggressive prompt caching** (profiles/memory are fixed per turn → cached tokens don't count).
- Response cache for repeated situations.
- **Auto-discovery** at sidecar boot: free tiers rotate; nothing is hardcoded.
- README tip: **$10 once on OpenRouter** raises free usage from 50 → 1,000 req/day (no recurring cost).

---

## 6. Anti-Lag Strategy (performance)

| Tier | Latency | Executor | Function |
|---|---|---|---|
| **0 — Native** | 0 ms | Game autonomy engine | LLM **pre-writes the "autonomy vector"** (trait + buff + want + motive tweak) in background; the game acts on its own. **Zero API on this path.** |
| **1 — Reactive** | 0.5–3 s | Fast free | Chat replies + immediate reaction to events. Asynchronous. |
| **2 — Evolution** | 30 s–10 min | Free (batch) | Generative-Agents-style reflections: personality drift, memory consolidation, trait-swap proposal. |
| **3 — Orchestration** | 1–10 min | DeepSeek | God: reads the world model → picks an intervention from the deck → writes directives. |

**Core principle:** the LLM adjusts the "personality climate" in background; the game's
native autonomy executes in real time. LLM interventions only when they matter.

**State collection:** event-driven (`event_manager`) + **alarms** every N sim-minutes
(never per frame); reads via `SimInfoManager` only. The `.ts4script` never blocks.

---

## 7. Data Model and Evolution

SQLite in the sidecar, keyed by `(player_id, save_id, sim_id)`.

> `save_id` = GUID of the active zone → **memories survive save reload**.

| Table | Content |
|---|---|
| `neighborhoods` | one row per save: the **zeitgeist** (mood tags, free/rewritten text, `mood_influence`) plus per-save God overrides, stored as a flexible `data_json`. Keyed `(player_id, save_id)`. |
| `households` | one row per household: the God-written **background** and its metadata, as `data_json`. Keyed `(player_id, save_id, household_id)`. |
| `sims` | JSON profile (background, backstory, Big Five mapped to TS4 traits, speech style, secrets, `household_id`) + personality vector + state. |
| `events` | memory stream with importance and decay (Generative Agents style). |
| `relationships` | pair-to-pair sentiment (graph). |
| `reflections` | outputs of the reflection loop. |
| `directives` | audit log of everything the God/modes did. |

**Census.** On zone load and on household change the mod pushes a compact **census**
(`POST /v1/census`): Sims in the zone with traits/age/career/skills/relationships and
households with members/funds. It is the native base material the God uses to suggest a
zeitgeist and to write backgrounds. The census is read-only and event-driven; never per frame.

### 7.1 Profile creation

1 sentence (e.g. *"nosy neighbor who envies my Sim"*) → free model generates a complete
profile JSON: backstory, traits, speech style, goals, secrets, quirks.

### 7.2 Evolution

- Important events + periodic reflections → personality vector drift.
- Trait-swap proposal (configurable speed) → applied via `add_trait`/`remove_trait`
  (check DLCs first; fallback to base game).
- Embeddings (BGE-M3 via Cloudflare free) for semantic memory search.

---

## 8. Configurable God Agent

The God agent has three responsibilities, from broadest to most concrete: the
**neighborhood zeitgeist** (8.1), the **per-Sim / per-household backgrounds** (8.2), and
the **runtime orchestration** driven by an extensible control framework (8.3).

### 8.1 Neighborhood zeitgeist (the first layer of meaning)

The zeitgeist is the storytelling/mood of a whole neighborhood; it is the "sense" that
guides every other God decision.

- **Onboarding:** when a save/zone is loaded and its zeitgeist is **not configured yet**,
  the mod shows a UI. The player either picks **mood tags** or writes a **free-form
  prompt** (both are allowed).
- **Mood tags (v1, multi-select):** `novela`, `sitcom`, `drama` (slow drama), `caos`,
  `terror` (light horror), `romance`, `filme_adolescente` (teen movie). They map onto the
  existing intervention presets (§8.3).
- **Agent suggestion:** before the player picks, the God agent reads the **census** and
  proposes a default zeitgeist suited to the Sims that already live there. If the player
  picks alternative tags, the agent **rewrites** the text so it incorporates them.
- **Persistence:** per save (`player_id`, `save_id` = zone GUID) in the `neighborhoods`
  table. `config.toml` only holds global defaults. A "not configured" neighborhood is one
  with no row.
- **Degradation:** with no sidecar/LLM the dialog is skipped and the mod stays in native
  mode; the tags are still stored optimistically once the sidecar returns.

### 8.2 Backgrounds for Sims and households

The God writes a background (profile) for each Sim **and** each household; these are what
the per-Sim agent uses to stay in character.

- **Native base material:** background writing always starts from the native traits,
  age, career, skills and **kinship / family tree** (parent-child, spouse/partner) read
  from the game — never inventing contradicting facts.
- **Zeitgeist thermometer:** `mood_influence` (0..1) is passed into the background
  prompt. At 0 the background is neutral/realistic; at 1 it is strongly colored by the
  neighborhood mood. This is the coupling between §8.1 and §8.2.
- **Player intent for new Sims/households:** when the player creates a new Sim and/or
  household, the mod asks for free-text hints; those hints are sent with the census data
  and the God writes the background as the player wishes, still respecting native traits
  and genealogy.
- **Progressive batch pipeline (cost control):** backgrounds are generated in the
  background on the **free tier** (Tier 2), active-zone households first, then related
  NPCs; **lazy generation on first interaction** is the fallback. Results are cached in
  `households` / `sims`; a zeitgeist change marks them **stale** and they regenerate
  lazily. A dedicated budgeter keeps background work separate from the chat budgeter.
  Implemented by `god/scheduler.py` (priority queue + async loop; injected `runner`) and
  `god/budgeter.py` (sliding-window + daily quota); configured via `[god.backgrounds]`.
- **Detection caveat:** TS4 has no confirmed script event for "player finished CAS".
  Detection is best-effort (household-change event + **census diff** on zone load) and is
  a Phase 0 spike item.

### 8.3 Configurable orchestration and the control framework

The configuration surface is **declarative and extensible**: one registry is the single
source of truth and drives the TOML defaults, the sidecar validation and the future UI.

- **Presets (tags):** Soap opera · Sitcom · Slow drama · Total chaos · Light horror ·
  Romance · Teen movie.
- **v1 controls** (each `slider` / `toggle` / `select`):
  - `autonomy_degree` (0..1) — how freely the God acts.
  - `chaos_degree` (0..1) — randomization/unpredictability.
  - `mood_influence` (0..1) — zeitgeist influence over backgrounds and mood.
  - `intervention_frequency` (0..1), `intensity` (0..1).
  - `evolution_speed` (select: slow | normal | fast).
  - power toggles: `spawn_npc`, `apply_trait`, `force_social`, `gossip`,
    `relationship_shift`, `extreme_events` (off by default).
- **Control framework:** `god/controls.py` defines `ControlSpec`
  (`key`, `kind`, `label_key`, `description_key`, `default`, `min`/`max`/`step`,
  `options`, `requires_power`, `advanced`). `GET /v1/god/controls` returns the specs +
  current values; `POST /v1/config/god` validates values against the specs. Adding a
  control = one spec entry + i18n keys (no router/UI rewrite).
- **UI strategy (v1):** vanilla TS4 **native dialogs only**. Tags via the native
  multi-select; text via `UiDialogTextInput` (fallback: `sw.zeitgeist` cheat). The
  configuration panel uses the native picker/list, paginated responses, numeric
  input and multi-select — **no Flash and no drag sliders** (not scriptable in TS4),
  i.e. the game's own menus. Full design, settings inventory and the `panel.toml`
  persistence overlay live in **`docs/ui_panel.md`**.
- **Hardcoded never-tools:** killing the player's Sim, touching money, deleting saves,
  shell/fs/http. A power toggle that is off behaves like a never-tool.
- **Safety rails:** rate limit (tool calls/min), player-priority lock (10 s after a
  player action), audit log — all already in `tools/rails.py`.

---

## 9. Wire Protocol (summary)

HTTP versioned (`/v1`) on `127.0.0.1:8765`, shared token in a file (0600).

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/chat` | Player message + Sim context → reply or tool_calls |
| `POST` | `/v1/hey` | Spontaneous Sim greeting |
| `POST` | `/v1/tools/result` | Game returns the result of an executed tool |
| `POST` | `/v1/events` | Game pushes events (zone load, buff, relationship, snapshot…) |
| `POST` | `/v1/reset` | Clear conversation/memory in `session\|sim\|save\|all` scope |
| `POST` | `/v1/config/*` | Live update (autonomy, God settings, language) |
| `POST` | `/v1/config/player-activity` | Arm the player-priority lock |
| `POST` | `/v1/lifecycle/attach` | Arm the game-process watchdog (sidecar exits with the game) |
| `GET` | `/v1/status` | Active providers, chain health, autonomy, memory, rails |
| `GET` | `/v1/health` | Liveness check |
| `GET` | `/v1/god/zeitgeist` | Current neighborhood zeitgeist + `configured` flag |
| `POST` | `/v1/god/zeitgeist` | Set/update zeitgeist (tags, free text, `mood_influence`) |
| `POST` | `/v1/god/zeitgeist/suggest` | Agent proposes a zeitgeist from the census |
| `POST` | `/v1/god/background` | Generate a Sim/household background (with player hints) |
| `GET` | `/v1/god/controls` | Declarative `ControlSpec` list + current values |
| `POST` | `/v1/god/tick` | **5c** — run one God-orchestration tick; returns the issued directives (tool calls / broadcast events) |
| `POST` | `/v1/census` | Push the neighborhood census (Sims + households) |
| `POST` | `/v1/autonomy/tick` | **v0.2** — fire-and-forget zone pulse (multi-Sim + zone); schedules impulses |
| `GET` | `/v1/autonomy/directives` | **v0.2** — pull pending per-Sim directives for the mod to execute |
| `GET` | `/v1/god/aggregates` | **v0.2** — aggregated neighborhood state the God may read (never psyche) |

Every request body includes `lang` (`en` | `pt-BR`). Responses that carry system/UI text
may include `message_key` + `message_args` for mod-side localization. Events from the God
carry `source=god`; raw chat turns are archived after consolidation (v0.2).

Outgoing payloads are **sanitized recursively to JSON primitives** before transmission:
any game object that leaks from the collectors is dropped (never stringified), and
non-finite floats become `null`. Tool arguments use the canonical keys of
`sidecar/sensewright_sidecar/tools/schemas.py` with **no aliases** (strict parsing).

**Tool round-trip:** sidecar **decides** → game **executes** → result returns (<2 ms localhost).
Errors are mapped to *in-character* responses ("my brain is foggy, try again"), localized
via `error.*` keys.

**In-game cheats:** `sw.chat` · `sw.hey` · `sw.status` · `sw.reset` · `sw.forget` ·
`sw.autonomy` · `sw.lang` · `sw.zeitgeist` (onboarding/config) · `sw.god` (opens the
panel) · `sw.help`.

---

## 10. Security and Privacy

- **Localhost-only by default** (`127.0.0.1`); remote binding requires explicit opt-in.
- **Shared-token auth** (`X-Sensewright-Token`); mismatch → 401.
- **API keys never leave the sidecar** — the `.ts4script` only knows the local URL + token.
- **No telemetry** — the sidecar only makes HTTP calls to configured providers.
- **Local, controlled memory** — `sw.forget all` wipes; the data folder is documented.
- **Never-tools** prevent destructive changes regardless of jailbreak.
- **Rate limits and player-priority lock** prevent loops and queue thrashing.

---

## 11. Implementation Phases

| Phase | Deliverable | Success criterion |
|---|---|---|
| **0 — Spike** | Decompile stubs; validate checklist §2.3 | Minimal mod loads on the current patch |
| **1 — Skeleton** | Toolchain (uv + build.py Py3.7 + Makefile), handshake, **.exe auto-spawn**, i18n scaffold (en + pt-BR) | `sw.status` green; sidecar boots by itself; all UI text localized |
| **2 — State & Directives** | StateCollector (event-driven + alarms) + DirectiveExecutor v1 + rails (rate limit, player lock) | Directive changes visible game state |
| **2b — Census & household events** (amendment) | `/v1/census`, `neighborhoods`/`households` schema, household-change detection + zone-load census diff | Sidecar holds an accurate census of the loaded zone |
| **3 — Agents** | Auto-generated profiles, MemoryDB, **multi-provider ModelRouter** + budgeter + auto-discovery, chat in the active locale | Conversation with a Sim via `sw.chat` |
| **4 — Evolution** | Reflection loop, personality drift, trait swaps | Behavior changes over 1 h of play |
| **5a — Zeitgeist** | Onboarding UI on first load, 7 mood tags + free text, agent suggest + rewrite, per-save persistence, **ControlSpec framework** + `/v1/god/controls` | First-load dialog writes and persists the zeitgeist; the suggestion reflects existing Sims |
| **5b — Backgrounds** | Sim/household background writer from native traits + genealogy, new-Sim/household prompt UI, progressive batch pipeline, `mood_influence` thermometer | New household asks for hints; agents use the generated backgrounds in character |
| **5c — God panel & orchestration** | In-game panel with **native dialog controls** (framework-driven; stepped values, no drag sliders — see `docs/ui_panel.md`), DeepSeek orchestration tier, intervention deck live | God creates drama under the "Soap opera" preset and controls move the dials |
| **6 — Publishing** | Packaging (exe + 1 folder), README (OneDrive warning!), 0-key mode, degradation, perf | Clean install on a non-technical machine |

Each phase is independently testable; the mod remains usable between phases.

### 11.1 Phase detail

**Phase 0 — Research spike**
- Decompile EA scripts (`base/core/generated/simulation` folders).
- Validate every §2.3 checklist item in the real game.
- Confirm toolchain: Python 3.7 for build + Python 3.12 for sidecar.

**Phase 1 — Skeleton**
- `Makefile` targets: `install`, `run`, `doctor`, `status`, `logs`, `build-mod`, `install-mod`, `check`.
- `build.py` (Py 3.7) → `.ts4script` (bundles `locales/`).
- Mod ↔ sidecar handshake; ping + auto-spawn of the exe.
- Degraded mode already functional.
- i18n scaffold: `i18n.py` + `locales/en.json` + `locales/pt-BR.json`; language resolution (config → game → en).

**Phase 2 — State & Directives** *(done)*
- `sim_context.py` + `events.py` (events + alarms).
- `tool_executor.py` v1: buff, trait, social queue, walk, say.
- Rails: rate limit, player-priority lock, audit log, never-tools.

**Phase 2b — Census & household events (amendment)**
- Memory: `neighborhoods` + `households` tables; `SimRef.household_id`.
- `POST /v1/census` + mod-side census builder (traits, age, career, skills, kinship).
- Wire `EVENT_HOUSEHOLD_CHANGE` (or the verified equivalent) + zone-load census diff.

**Phase 3 — Agents**
- Profile generator (1 sentence → JSON) in the active language.
- `memory/sqlite_store.py` + embeddings.
- `llm/registry.py` (auto-discovery) + `chain.py` (fallback + circuit breaker).
- Chat in the selected language (prompt in English, output in `lang`).

**Phase 4 — Evolution**
- Batch reflection loop; personality drift; trait swaps.

**Phase 5a — Zeitgeist**
- `god/zeitgeist.py` (tags, templates, agent suggest + rewrite) and `god/controls.py`
  (`ControlSpec` registry + validation).
- Onboarding: first-load detection (`GET /v1/god/zeitgeist` → `configured=false`) and the
  mod dialog (`god_ui.py`); persistence in `neighborhoods`.
- `GET /v1/god/controls`, `POST /v1/config/god` (spec-validated), `sw.zeitgeist` cheat.

**Phase 5b — Backgrounds**
- `god/backgrounder.py`: Sim + household background writer (native traits/genealogy as
  base, `mood_influence` thermometer), progressive batch on the free tier + lazy fallback,
  cache + stale-on-zeitgeist-change.
- Mod: new-Sim/household prompt UI, census-driven generation requests, sim agent prompt
  reads the background from the profile.

**Phase 5c — God panel & orchestration**
- `world_model.py`, `interventions.py`, `orchestrator.py` fully wired. *(Orchestration
  tier done: the deck is live behind `god/orchestrator.py`, `POST /v1/god/tick` runs a
  tick against the census and returns directives; `POST /v1/config/god` re-applies the
  dials.)*
- In-game panel with framework-driven **native-dialog controls** (picker/list rows,
  paginated responses, numeric input, multi-select — **no drag sliders**) + language
  selector; see `docs/ui_panel.md`; DeepSeek tier. *(Pending: the mod
  panel + the periodic pull loop that executes the returned directives.)*

**Phase 6 — Publishing**
- Package the exe + 1 folder; README with the OneDrive warning; 0-key mode.
- Performance tuning; translation docs (how to add a locale).

---

## 12. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Game patch breaks 3.7 bytecode | Mod doesn't load | Pin version in the build; fast rebuild; post-patch test |
| Free tiers rotate/die | Agents with no LLM | Auto-discovery + multiple providers (openrouter/opencode/gemini) + model & provider fallback chain + native mode |
| Antivirus blocks the .exe (PyInstaller) | Autoboot fails | Documented; fallback "run the exe manually"; Nuitka as plan B |
| Rate limits (15 Sims) | Replies lag | Budgeter + prompt caching + reflection batching |
| Weak free-model output in a locale | Poor quality | Auto English prompt fallback; locale-aware prompts |
| Missing/partial translation keys | Raw keys shown in-game | `en` fallback per key + a test that validates key parity across locales |
| OneDrive in `Documents` breaks script mods | Mod silently inactive | Dedicated README section + `doctor` detection |
| Missing DLC traits | Error applying a trait | Ownership check; base-game fallback |
| God latency (paid) | Slow cycles | Timer-based loop (1–10 min), never real-time |

---

## 13. Next Steps

1. Create the repository structure + toolchain (uv, Makefile, `build.py` Py 3.7) — Phase 0/1.
2. Minimal mod that pings and spawns the sidecar — autoboot proof of life.
3. Add the i18n scaffold (`en` default, `pt-BR`) and route all UI text through it.
4. Sign test keys: OpenRouter, Gemini.
5. Decompile and map the §2.3 APIs.
6. Follow Phases 2–6 per the §11 table.
7. Then implement the **v0.2 "Living Sim Agents"** plan (§14): M1 memory consolidation →
   M2 forgetting → A1 world context → A2 agency skeleton → A3 LLM impulse →
   P1 living personality (sleep consolidation) → G1 God scoping.

---

## 14. Autonomous Sim Agents (v0.2)

> **Goal.** Give every **Sim agent** (not the God) a life of its own: read the world,
> take its own actions and attitudes, and let experience **shape personality over
> time**. The God stays on the world layer (zeitgeist, backgrounds, world events,
> unplayed Sims). This section is the forward plan; v1 (Phases 0–6) remains valid.

> **⚠️ Superseded in part by §15 (v0.3 "Inhabited Agents").** The v0.2 material below
> is the foundation, but the **agency mechanism** (A2/A3) changes: the mod no longer
> puppets every Sim with a command palette. The per-item disposition is:
>
> | v0.2 item | Disposition in v0.3 |
> |---|---|
> | A1 — zone pulse, sleep detection (`state_collector`, `events`) | **Kept** (perception) |
> | M1 — memory consolidation (`memory/consolidation.py`) | **Kept** (memory layer) |
> | M2 — graded forgetting / strength decay (`memory/decay.py`) | **Kept** (memory layer) |
> | A2 — `Agency` scheduler, pending-directive store, pull loop | **Replaced** by `SeatManager` + `IntentBus` |
> | A3 — `initiative.py` impulse/tool-call loop | **Absorbed**: emits *intents*, cadence becomes a per-agent dial |
> | P1 — psyche + `life_story` + sleep consolidation (`agent/personality.py`) | **Kept**, becomes the cognition axis |
> | G1 — God scoping + `coordinator.py` | **Kept** (God/world layer) |
> | Phase 4 evolution (`agent/evolution.py`, `sw.evolve`) | **Absorbed** into the cognition layer (manual trigger kept) |
> | Command palette (`tools/schemas.py`, `tools/registry.py`, `tool_executor.py`) | **Reduced** to intents + a minimal, gated direct-command escape hatch |
> | Rails + audit (both sides) | **Kept**, applied to intents |
> | ControlSpec / sliders (`god/controls.py`) | **Kept + extended** (`max_agents`, `impulse_frequency`, layer toggles) |

### 14.1 Locked decisions

| Question | Decision |
|---|---|
| Player-controlled Sim | Initiative is a **config** (minimal / moderate / full); the player chooses how much autonomy the agent has over their own Sim. NPCs get their own initiative. |
| Cadence / cost | **Quota-max**: drive the free tiers to their rate limit (chat always first). |
| Visibility | Spontaneous actions **and** lines surface as notifications. |
| Autonomy `full` | Personality changes (incl. traits) are **automatic** (DLC-checked). |
| Raw chat turns | **Archived**, never deleted, after consolidation. |
| Forgetting | Decay with **presets** (`fast` / `normal` / `slow`). |
| Forgotten memories | Can resurface as a **subtle déjà vu** hint. |
| Sleep detection | Via the **sleeping buff** in the zone pulse, matched by **exact tuning id** (`buff_Sleeping`, `moodlet_sleeping`, …, not substrings) to avoid false positives; `BuffBeganEvent` is validated. |
| Traumas / baggage | **Fade without reinforcement**. |
| Personality changes | Applied **during sleep** + **immediately** for extreme events (death, betrayal). |
| God visibility | **Aggregates only** (neighborhood mood) — never psyche/secrets. |
| Directive conflict | **Agent wins on its own Sim**; God acts on world/unplayed only. |
| God gossip | May reach played Sims **as knowledge** (an event), never as control. |
| God world events | **Always broadcast** to affected/witness Sims' feeds. |

### 14.2 Agency Layer (per-Sim initiative)

**Context reading (mod).** The 30 sim-minute alarm becomes a **zone pulse** that samples
the active Sim **and nearby instanced Sims** (mood, needs-lite, location, current
interaction) plus zone context (world time, lot type, weather when Seasons is present).
The event handlers (already wired to the real `TestEvent` names) carry `sim_id`/target/
importance. Sleep is detected here (sleeping buff) and pushed as `sim_state`.

**New read tools:** `nearby_sims`, `world_state`, `sim_profile` (another Sim's public state).

**Initiative loop (sidecar).**

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/autonomy/tick` | Fire-and-forget zone snapshot; updates the world-model cache and schedules impulses. |
| `GET` | `/v1/autonomy/directives` | Pull pending directives per Sim; the mod executes them with `execute_batch` and posts `/v1/tools/result` (reuses pending calls). |

`agent/initiative.py` builds a compact prompt (profile + recent memories + world context
+ attitude) and the model may emit **tool calls and/or an internal thought** (stored as
an event, so life evolves even when nothing visible happens). The pull model adds one
tick of latency (~10 sim-minutes) but never blocks the game thread.

**Triggers:** event reactions (salience ≥ `event_react_threshold`, prioritized) and idle
impulses (round-robin fairness across Sims, per-Sim cooldown).

**Budget — `AgencyScheduler` (quota-aware).** A global scheduler paces requests to the
provider free-tier ceiling (target ~80% of RPM; Gemini ~15, OpenRouter `:free` ~20,
OpenCode Zen ~20) using the existing circuit breaker. Priority: **chat/hey (player) → event reactions
→ sleep/consolidation → idle impulses → backgrounds**. Per-Sim daily caps remain; under
quota-max the quota is the real limiter.

**New tools (schemas + executor):** `spontaneous_line(text, audience)` (thought/speech
notification), `act_out` / `socialize` / `approach` (reuse `queue_interaction` /
`say_to` / `move_to`), `set_mood` (`add_buff`) and, at `full`, `add_trait` (automatic,
DLC-checked).

**Autonomy mapping.** `minimal` → `observe`/`suggest` + rare reactions; `moderate` →
`semi` + buffs/spontaneous lines; `full` → full palette + automatic traits. `sw.autonomy`
keeps working **per Sim** (persisted in the sidecar).

### 14.3 Memory: consolidation and forgetting

**Consolidation at end of dialogue.** Chat turns stay unconsolidated until a silence
window (`dialogue_idle_seconds`). A low-priority scheduler job then summarizes them
(with the profile) into `{summary, topics, emotional_takeaways, facts,
relationships_touched}`, stored as a `consolidated_memory` event (importance ≥ 1.2,
with its own embedding). Raw turns are **archived** (a `consolidated` flag; excluded
from context, never deleted). Deterministic extractive fallback, like the profiler.

**Strength and forgetting.** `events` gain `strength` (0..1, default 1.0) and
`last_accessed_at`. Strength decays `s(t) = s₀ · e^(−λ·Δt)`, with λ from a preset
(`fast` / `normal` / `slow`) and weighted by importance. Decay is computed **lazily on
read**. Whenever a memory is used in a prompt, `touch(ids)` resets `last_accessed_at`
and boosts it (`min(1, s·1.1 + 0.05)`) — *revisiting is remembering.*

| Strength | Behaviour |
|---|---|
| `s > 0.5` | Vivid — full text in context. |
| `0.2 – 0.5` | Weak — semantic recall only, shown as *"you vaguely remember…"*. |
| `< 0.2` | Forgotten — excluded from context and search (archived; pruned per `retention_days`). |

`recent_events`/`search_events` filter by strength and rank by `importance × strength ×
recency` (or `cosine × strength`). **Déjà vu:** a small chance (`dejavu_chance`) that a
forgotten memory resurfaces as a truncated hint in a similar situation.

### 14.4 Living personality: psyche and sleep consolidation

**Emotional salience.** Events gain an `emotion` tag derived from buff names, the
consolidation's `emotional_takeaways` and extreme events. `salience = importance ×
emotion weight`; above `salience_threshold` the event enters the **absorption queue**
(processed at the next sleep, or immediately if extreme).

**Psyche blocks (`profile.psyche`) and `life_story`.**

```json
"psyche": {
  "traumas":     [{"trigger","belief","intensity","first_seen","last_reinforced","source_event_ids"}],
  "baggage":     [{"belief","source","intensity"}],
  "aversions":   ["..."],
  "attachments": ["..."]
},
"life_story": "append-only lines of what the Sim lived through (capped)"
```

Blocks are capped (`max_traumas`, `max_beliefs`; the weakest is merged when full) and
their **intensity decays** (`trauma_decay`) **unless reinforced** by a similar event.
`_format_profile` renders them as shaping lines (*"Because of what happened with X, you
now …"*), so they change speech and decisions.

**Sleep consolidation.** The mod detects the sleeping buff and pushes `sim_state`
(`sleeping: true/false`). On `sleeping_start` the sidecar enqueues **one sleep job per
sleep** (deduplicated) in the scheduler. One budgeted batch call then: consolidates
pending turns + salient events → **drifts `personality`** (bounded by `drift_strength`),
adds/merges **psyche blocks**, appends **`life_story`**, and proposes a trait (applied
automatically at `full`). While awake the Sim uses the last consolidated profile — as in
real life. This **absorbs the Phase-4 evolution** (`sw.evolve` remains the manual
trigger). Extreme events apply the same absorption **immediately**.

**Immutable base vs living layers.** The God's `background` is the immutable base (native
facts + zeitgeist); `life_story`/`psyche` are agent-owned and **persist** across zeitgeist
rewrites (which only mark the base stale).

### 14.5 God ↔ Sim-agent coordination

**Single-writer jurisdiction.**

| Resource | Owner |
|---|---|
| Native traits / skills | Game (ground truth) |
| `background` (base) | God (regenerated on zeitgeist change only) |
| `personality` / `psyche` / `life_story` | Sim agent (evolution / sleep) |
| Actions, mood, memory, 1st-order relationships of a Sim | Sim agent |
| `zeitgeist`, world events, **unplayed** Sims (spawn, traits, interventions) | God |

**Rules.**
- **God sees aggregates only** (neighborhood mood/tension) to pick coherent events —
  never a played Sim's psyche/secrets (only what the Sim *tells* via dialogue/gossip).
- **God world events are always broadcast** to affected/witness Sims' feeds (`/v1/events`,
  `source=god`); the agents react/absorb. God never reacts to its own events — no double
  response. Synergy: a God fire + a fire trauma → amplified reaction.
- **Gossip is knowledge, not control**: it injects a rumor into played Sims' feeds.
- **Arbitration (`agent/coordinator.py`):** every directive passes rails → single-writer →
  played/unplayed → conflict with the other agent's pending directive. On a played Sim the
  **agent wins**; the losing directive is logged, not silently dropped.
- **Handoff NPC → tracked:** when an unplayed Sim becomes tracked (census diff), God's
  traits become native and the God background becomes the base; the agent takes over.
- **One priority queue** (`AgencyScheduler`) with **separate quotas** (God runs on paid
  DeepSeek at 1–10 min; Sim agents on the free tier).

### 14.6 v0.2 phases

| Phase | Deliverable | Success criterion | Status |
|---|---|---|---|
| **M1 — Memory consolidation** | Silence-window job, `consolidated_memory`, archived raw turns, deterministic fallback | A dialogue collapses into one memory; raw turns leave the context but stay in the DB | ☑ Done |
| **M2 — Memory forgetting** | `strength`/`last_accessed_at`, presets, `touch`, thresholds, déjà vu, pruning | Unrevisited memories fade to "vague"; used ones stay vivid; forgotten ones resurface rarely | ☑ Done |
| **A1 — World context** | Zone pulse (multi-Sim + zone), enriched events, read tools, sleep detection, `source=god` events | Sidecar holds a fresh zone snapshot; sleep/buff events arrive with `sim_id` | ☑ Sidecar + mod wired |
| **A2 — Agency skeleton** | `tick`/`directives`, `AgencyScheduler`, `coordinator` base (single-writer + played/unplayed) | Rule-based impulses round-trip in-game with no stutter | ☑ Sidecar + mod wired |
| **A3 — LLM impulse** | `initiative.py`, quota-max pacing, reactions, spontaneous lines | Sims act/speak on their own within the free-tier ceiling | ☑ Done (live tuning pending) |
| **P1 — Living personality** | `psyche` + `life_story`, sleep job, immediate extreme absorption (absorbs evolution) | A Sim's prompt changes after sleep; a trauma forms and fades without reinforcement | ☑ Done |
| **G1 — God scoping** | Filtered deck, aggregates endpoint, broadcast + full arbitration | God only touches world/unplayed; played Sims are agent-owned | ☑ Done |

### 14.7 Config additions (v0.2)

```toml
[agents]

# The player's own Sim gets its own initiative level (usually lower).
# `level` lives inside the table to avoid a TOML key/table name clash.
[agents.initiative]
level = "full"                       # minimal | moderate | full
player_sim_level = "suggest"         # the player chooses their own Sim's autonomy
cooldown_sim_minutes = 8
event_react_threshold = 1.0
spontaneous_lines = true
quota_fraction = 0.8                 # target fraction of the free-tier RPM
max_impulses_per_tick = 1

[agents.personality]
absorption_enabled = true
salience_threshold = 1.5
max_traumas = 5
max_beliefs = 10
trauma_decay = "slow"                # fast | normal | slow
sleep_consolidation = true

[memory]
consolidation_enabled = true
dialogue_idle_seconds = 300
decay_preset = "normal"              # fast | normal | slow
weaken_threshold = 0.5
forget_threshold = 0.2
dejavu_chance = 0.05
retention_days = 180
```

---

## 15. Inhabited Agents (v0.3)

> **Goal.** Move from a **command-centric** mod (the LLM emits tool calls that puppet the
> Sim) to an **inhabitation + nudge** model: a configurable pool of *agent seats* biases
> the game's **native autonomy** ("changes of route") instead of issuing every action; the
> game keeps driving most behavior. Cognition happens mainly at **sleep**, with a
> configurable impulse frequency surfaced in an **agent-roster panel**; two agent-owned
> Sims get a real **sim↔sim dialogue channel**; the God directs the **stories of the
> inactive neighbors** on the free tier. Reference: *Generative Agents (Smallville)*.

### 15.1 Locked decisions

| # | Question | Decision |
|---|---|---|
| 1 | Decompiled game stubs | **Inside the repo, gitignored**: `research/ts4/` (repo must be `git init`-ed first; EA code never leaves local) |
| 2 | Research reading order | **Everything in sequence** (module-map order) |
| 3 | Dev probe cheat | `sw.probe` — **permanent** dev tool (dumps live autonomy/state) |
| 4 | If the game exposes no pure runtime autonomy bias | **Hybrid accepted**: use pure bias when available, else **insert a candidate** into the queue (gated by rails) |
| 5 | Sim↔sim dialogue surface | **Game speech bubble**, with notification fallback if the API can't render arbitrary text |
| 6 | Seat eviction for a visiting Sim | **On leaving the lot** (memory persists without a seat) |
| 7 | God provider/cadence | **Free tier, slow** (DeepSeek paid only as an opt-in) |
| 8 | Idle impulses | **Not removed** — become a **per-agent dial** (increase/decrease; `0` = sleep-only) exposed in the **agent-roster panel** |

### 15.2 The pivot (delta vs v0.2 §14)

| Area | v0.2 | v0.3 |
|---|---|---|
| Mechanism | Tool calls = direct commands | **Intents/biases** translated into native levers; direct command is a gated exception |
| Cadence | Continuous impulse loop (~5 s drain, ~8 sim-min idle) | **Sleep-first cognition** + a **configurable** impulse frequency per agent (default low) |
| Ownership | Any Sim can act (autonomy levels) | **Seats**: active household > instanced visitors > God covers the rest |
| Schema | ~19 rigid command verbs | A small **intent** schema + a minimal escape hatch |
| God | Periodic world interventions | **Story director for inactives** + broadcast events (aggregates only) |
| Social | Player↔Sim chat | + **Sim↔Sim channel** (two agents, native relationship delta) |

### 15.3 Framework layers

Each layer is a `CognitiveLayer`: budget, cadence, deterministic fallback (0-key mode stays
alive) and emits **intents** on a shared bus. Adding intelligence = adding a layer.

| # | Layer | Responsibility | Cost / cadence | State |
|---|---|---|---|---|
| **L0** | Native autonomy | The game executes actions in real time | 0 | exists |
| **L1** | Perception (mod) | Zone pulse, census, events, sleep detection | 0 | exists (A1) |
| **L2** | **Seats (inhabitation)** | Pool of N agents; active > visitor; eviction on lot exit; memory persists | 0 (state only) | **new** |
| **L3** | **Intent/bias** | `bias_interaction`, `prefer_target`, `set_mood`, `set_goal` → native levers | cheap, applied after cognition | **new** |
| **L4** | Memory | Stream + decay + déjà vu + psyche + `life_story` | existing cadence | exists (M1/M2/P1) |
| **L5** | Cognition | Reflection, **daily plan**, goals; runs at sleep (+ salient reactions) | 1 batch per sleep | **new** (absorbs Phase 4) |
| **L6** | Social sim↔sim | Dialogue between two agents + native relationship delta | per relevant interaction | **new** |
| **L7** | God/director | Zeitgeist, backgrounds, arcs for inactives, broadcast events | free tier, 1–10 min | exists (G1) |

### 15.4 Framework abstractions (the scalability spine)

1. **`CognitiveLayer`** (sidecar protocol): `name`, `budget`, `cadence`, `configure/start/stop`,
   `status()`, `emit_intents(context)`. A registry holds the enabled layers in order.
2. **`SeatManager`**: assigns/frees seats by priority rules; `agent_seats` is the pool size;
   `GET /v1/agency/seats` exposes the roster. Seats are **runtime-only** (reassigned from the
   census on load); a Sim's **memory persists** without a seat.
3. **`IntentBus`** (replaces the pending-directive store): intents are validated by rails +
   coordinator, audited, and translated by the **`GameLever` adapter** (mod) — the only point
   that touches game APIs, swappable per patch. Pull becomes `GET /v1/autonomy/intents`
   (with `/v1/autonomy/directives` kept as a **transitional alias**).
4. **`LayerBudget`**: generalizes `BackgroundBudgeter`/`ProviderRateLimiter`; each layer gets a
   RPM/RPD ceiling and a preferred provider.
5. **`ContextForge`**: builds the per-Sim context (profile + relevant memories + world) once per
   "think"; a **`PairContext`** variant feeds L6 with both Sims' profiles, relationship and
   memories.
6. **Deterministic fallback per layer** (the pattern already used in `initiative.py`/`profiler.py`):
   every layer degrades to native rules without an LLM.

### 15.5 Intent model (hybrid rule)

The agent emits **intents**, not commands. Each intent may carry a native-lever payload and a
lifecycle, so a single sleep-time decision can bias the whole day:

```jsonc
{
  "id": "…",
  "sim_id": 123,
  "kind": "bias_interaction",      // bias_interaction | prefer_target | set_mood
                                    // | set_goal | approach | speak | remember | forget
  "target_sim_id": 456,
  "params": { "interaction_kind": "romantic", "tone": "flirty", "strength": 0.4 },
  "reason": "…",
  "expires_at": "next_sleep",       // "next_sleep" | ISO sim-time | game-clock span
  "priority": 0,
  "source": "agent"                 // agent | god
}
```

**Hybrid rule (decision #4).** The `GameLever` adapter tries, in order: (1) a **pure bias**
lever (autonomy/game-effect modifiers on commodity/scoring), and (2) failing that, a **gated
candidate** inserted into the interaction queue. Every applied intent is logged and audited;
direct commands remain behind the existing rails and the player-priority lock.

### 15.6 Agent-roster panel

A mod config surface that shows **active agents and which Sims each one controls** (live seat
occupancy) and a **control for impulse/thought frequency** (global and per agent, as stepped
choices; `0` = sleep-only). Implementation:

- The dials register in the existing **`ControlSpec`** registry (`god/controls.py`):
  `agent_seats`, `impulse_frequency`, `player_sim_impulse_frequency`, `reactions_enabled`,
  plus per-layer toggles.
- **Native-dialog panel:** a live list + the dials render as the game's own
  dialogs — picker/list rows for the roster and sections, stepped choices or a
  numeric input for values, multi-select for tags. **No Flash and no drag
  sliders** (not scriptable in TS4). Design + settings inventory + `panel.toml`
  persistence: **`docs/ui_panel.md`**. Interim fallback: the `sw.agents`/`sw.god`
  text commands (`sw.agents` lists; `sw.agents <sim> <freq>` sets).

### 15.7 Research plan (TS4 internals)

**F0 — Tooling & stubs.** *(script done; run against the local install)*
- `git init` the repo, add `research/ts4/` to `.gitignore` **before** downloading anything. *(done)*
- Decompile `base/core/simulation/generated` with **`unpyc37`** (the S4S starter project's
  `decompile_all.py`, or `github.com/andrews4s/unpyc37`) into `research/ts4/`.
- **Pre-check** the `.pyc` magic byte (3.7 = `42 0d 0d 0a`) before bulk decompiling; if the
  runtime changed, the tooling adjusts.
- Add `scripts/decompile-scripts.ps1` so the step is reproducible after each patch. *(done)*

**F1 — Live probe.** Add the permanent `sw.probe` cheat (dev) that dumps, for the active/selected
Sim: autonomy requests/service state, `si_state`, commodity values, active buffs/traits and their
modifiers, whims and relationship tracks → `sensewright_output.log`. *(done: also probes which §15.7
modules are importable + their public names.)*

**F2 — Sequential read + deliverable.** Read the module map in order and produce
`docs/ts4_internals.md`: *(started: autonomy/buff/event/zone APIs documented from
the decompiled scripts; levers catalog still pending runtime validation)*
- the autonomy cycle (`AutonomyService` → `AutonomyRequest` → `TestBasedScoreThreshold` → best
  affordance), how traits/buffs/mood/whims/relationship weights enter;
- the **levers catalog** ("intent → native lever"), each entry marked
  *code-validated / runtime-validated / tuning-only*.

**F3 — Register.** This section, the §14 disposition table, the CHANGELOG pivot and the config
draft.

**Module map (source of truth for F2, from `simulation.zip`):**

| Area | Modules |
|---|---|
| Autonomy | `autonomy/autonomy_service`, `autonomy_request`, `autonomy_component`, `autonomy_modifier(_enums)`, `autonomy_modes(_tuning)`, `autonomy_preference`, `autonomy_object_preference_tracker`, `parameterized_autonomy_request_info`, `distance_based_scoring_modifier` |
| Interactions | `interactions/interaction_queue`, `interactions/si_state`, `aop`, `choices`, `context`, `base/super_interaction`, `base/interaction`, `social/social_super_interaction` |
| Modifiers | `game_effect_modifier/affordance_reference_scoring_modifier`, `affordance_filter_modifier`, `mood_effect_modifier`, `continuous_statistic_modifier`, `relationship_track_decay_modifier`, `statistic_static_modifier` |
| Traits/prefs | `traits/traits`, `trait_commands`, `preference*`, `gameplay_object_preference*`, `statistics/trait_statistic(_tracker)` |
| Buffs/mood | `buffs/buff`, `buffs/memory`, `statistics/mood`, `statistics/commodity(_tracker)` |
| Whims | `whims/whims_tracker`, `whim`, `whim_set`, `whim_modifiers` |
| Relationships | `relationships/relationship_track`, `sentiment_track(_tracker)`, `relationship_bit`, `compatibility`, `global_relationship_tuning` |
| Debug commands | `server_commands/autonomy_commands`, `interaction_commands`, `relationship_commands`, `whim_commands`, `sim_commands`, `statistic_commands` |

### 15.8 Phases (v0.3)

| Phase | Deliverable | Success criterion | Risk |
|---|---|---|---|
| **R1 — Lever spike** | Levers catalog validated live; `GameLever` decides pure-bias vs candidate | An intent visibly changes the game's chosen action | **High** (the core bet; hybrid fallback accepted) |
| **R2 — Seats** | `SeatManager` + wire + census/household integration + `agent_seats` | Visitor claims a free seat; leaving the lot frees it; memory persists | Low | ☑ Done |
| **R3 — Intents** | Intent schema + `IntentBus` + `GameLever` + new pull (+ alias) | Agent changes the route without commanding each step | Med (needs R1) | ☑ Done (lever spike pending) |
| **R4 — Cognition** | Daily plan + reflections + goals at sleep; **impulse frequency dial** | A Sim "thinks" at sleep and adjusts the next day; impulses configurable | Low (P1 exists) | ☑ Done (plan+goals §15.4) |
| **R5 — Sim↔sim channel** | `agent/social.py` (`SocialLayer`/`Dialogue`): two seated non-player Sims dialogue + two `speak` intents + a `social` memory event; native `say_to` with notification fallback | Two agent Sims converse; the relationship moves in-game | Med (bubble API) | ☑ Done (build `.18`; live check pending) |
| **R6 — God director** | Orchestrator re-scoped to inactives; background arcs; broadcast events | God pushes neighbor stories without touching the played Sim | Low | ☑ Done |
| **R7 — Panel** | `ControlSpec` dials + roster + `sw.agents` fallback + language selector; full native-dialog panel per `docs/ui_panel.md` | Control the degree of agency without intrusive UI | Low (native dialogs) | ☑ Dials done (text); panel specified |

### 15.9 Fix points — existing code to change

Mapping of what is already implemented to the v0.3 target (this is the concrete fix list).

> **Status:** R2/R3/R4/R5 rows are **implemented** (plus F0's
> `scripts/decompile-scripts.ps1` and F1's `sw.probe`), and R6/R7 are
> **verified**. R1 levers still need live runtime validation. The in-game panel is
> **no longer gated on Flash**: it is specified for **native dialogs only** in
> `docs/ui_panel.md` (no slider).

| Existing artifact | v0.3 fix | Phase |
|---|---|---|
| `sidecar/…/agent/agency.py` (`Agency`, `ImpulseJob`, `_pending`, `pull`) | Split: `SeatManager` (assignment) + `IntentBus` (store/validation); impulse cadence from config | R2/R3 |
| `sidecar/…/agent/initiative.py` (`build_impulse`, tool-call directives) | Emit **intents** (with `expires_at`); drop command-palette coupling | R3 |
| `sidecar/…/agent/graph.py` (`_gate_directives`, `_run_agency_job`, `pull_directives`, `configure`) | Gate **intents**; wire `ContextForge`; seats in `configure` | R2/R3 |
| `sidecar/…/agent/coordinator.py` | Keep single-writer; extend reason codes to intents | R3 |
| `sidecar/…/tools/schemas.py`, `tools/registry.py` | Add **intent** schemas; keep the command palette only for the escape hatch | R3 |
| `sidecar/…/tools/rails.py` | Keep; apply to intents (unchanged semantics) | R3 |
| `sidecar/…/god/controls.py` | Add `agent_seats`, `impulse_frequency`, `player_sim_impulse_frequency`, `reactions_enabled`, layer toggles | R4/R7 |
| `sidecar/…/god/orchestrator.py`, `god/world_model.py` | Re-scope targets to **inactive** Sims; keep aggregates-only | R6 |
| `sidecar/…/agent/evolution.py`, `agent/personality.py` | Keep; evolution absorbed by L5, manual `sw.evolve` stays | R4 |
| `sidecar/…/memory/*` | Keep (no change) | — |
| `sidecar/…/schemas.py` | Add `SeatInfo`/`Roster`, `IntentItem`, `IntentResponse`; alias old directive model | R2/R3 |
| `sidecar/…/routers/autonomy.py` | `GET /v1/agency/seats`, `POST /v1/agency/seats`, `GET /v1/autonomy/intents` (+ directives alias) | R2/R3 |
| `sidecar/…/config.py` (`AgentsConfig.max_active`) | Rename to `agent_seats` (keep `max_active` alias) + `impulse_frequency`, `reactions_enabled`, layer config | R2/R4 |
| `mod/…/tool_executor.py` | Becomes the **`GameLever` adapter**: intent handlers + speech-bubble attempt | R1/R3/R5 |
| `mod/…/state_collector.py` | Pull intents; **visitor detection + eviction via instanced diff** on the pulse | R2 |
| `mod/…/main.py` | `sw.probe` (permanent), `sw.agents` (roster/freq), render intents | R1/R7 |
| `mod/…/god_ui.py` | Roster text panel + frequency dial fallback | R7 |
| `mod/…/i18n.py` + `locales/*.json` | New keys (`cmd.probe.*`, `cmd.agents.*`, `notify.social.*`) in `en` + `pt-BR` | R1/R5/R7 |
| `.gitignore` | Add `research/ts4/` | F0 |
| `scripts/decompile-scripts.ps1` | New: reproducible decompile step | F0 |
| `docs/ts4_internals.md` | New: autonomy architecture + levers catalog | F2 |

### 15.10 Risks (v0.3 additions)

| Risk | Impact | Mitigation |
|---|---|---|
| No runtime autonomy-bias API (only tuning) | Pure nudge impossible | **Hybrid** (decision #4): gated candidate in the queue; keep bias for what exists |
| Arbitrary-text speech bubble not exposed | Sim↔sim chat invisible | Fallback to `notify.*` (decision #5) |
| Native UI can't render a live roster/sliders | Panel limited | Native dialogs cover roster (picker) + stepped values; `sw.agents`/`sw.god` text fallback |
| Eviction has no direct event | Seat freed late | Instanced-diff on the pulse; document latency (~10 sim-min) |
| Endpoint rename breaks installed mod | Agency dies (mod loads only at boot) | Keep `/v1/autonomy/directives` as an alias until mod+sidecar ship together |
| EA code leaks to the public repo | Legal/IP | `git init` + `research/ts4/` gitignored; never commit stubs |

### 15.11 Config additions (v0.3 draft)

```toml
[agents]
# Renamed from max_active; the size of the agent-seat pool.
agent_seats = 12

[agents.initiative]
# Impulse/thought frequency (0 = sleep-only). The roster panel adjusts this live.
impulse_frequency = 0.2              # 0..1 (default low)
player_sim_impulse_frequency = 0.0   # the player's own Sim: sleep-only by default
# Salient event reactions stay on independently of the impulse dial.
reactions_enabled = true

[agents.layers]
memory = true
cognition = true                     # daily plan + reflection at sleep
social = true                        # sim<->sim channel
# A layer disabled here degrades to native deterministic behavior.

[runtime]                            # exposes the roster + dials to the panel
expose_roster = true
```

---

## 16. Appendices

### A. Configuration (`config.toml`) — matches `config.example.toml`

> The canonical reference is [`config.example.toml`](file:///c:/workspace/sims-sense-8-agent/config.example.toml).
> This appendix is a readable summary; if they diverge, the example file wins.

```toml
# ─── UI / LANGUAGE ───────────────────────────────────────────────────
[ui]
language = "auto"                              # auto | en | pt-BR

[network]
host = "127.0.0.1"
port = 8765

[logging]
level = "INFO"
file = "data/sidecar.log"
audit = "data/audit.log"

# ─── LLM ─────────────────────────────────────────────────────────────
[llm]
chain = ["openrouter", "opencode", "gemini"]   # fallback order
budget_per_sim_per_day = 500

[llm.providers.openrouter]
enabled = true
models = ["nvidia/nemotron-3.5-lightning:free", "nvidia/nemotron-3-ultra-550b-a55b:free",
          "nvidia/nemotron-3-super-120b-a12b:free", "google/gemma-4-31b-it:free"]
api_key = "${OPENROUTER_API_KEY}"
base_url = "https://openrouter.ai/api/v1"
free_only = true                               # hard billing guard
rpm = 20
rpd = 50                                       # 1,000 RPD with $10 credit

[llm.providers.opencode]                       # optional power tier
enabled = false
models = ["space-bunny-free"]
api_key = "${OPENCODE_API_KEY}"
base_url = "https://opencode.ai/zen/v1"

[llm.providers.gemini]                         # last resort (aggressive rate limits)
enabled = true
model = "gemini-2.5-flash"
api_key = "${GEMINI_API_KEY}"
rpm = 15
rpd = 1500

[llm.providers.deepseek]                       # paid, God agent only
enabled = false
model = "deepseek-chat"
api_key = "${DEEPSEEK_API_KEY}"
base_url = "https://api.deepseek.com/v1"

# ─── MEMORY ──────────────────────────────────────────────────────────
[memory]
provider = "sqlite"
embedding_provider = "none"                    # none | cloudflare (BGE-M3 free)
retention_days = 180
consolidation_enabled = true                   # v0.2 M1
dialogue_idle_seconds = 300.0
decay_preset = "normal"                        # v0.2 M2: fast | normal | slow
weaken_threshold = 0.5
forget_threshold = 0.2
dejavu_chance = 0.05

[memory.embedding_provider_config]             # Cloudflare credentials
# account_id = "..."
# api_token = "..."

# ─── AGENTS ──────────────────────────────────────────────────────────
[agents]
max_active = 12
evolution_speed = "normal"                     # slow | normal | fast
autonomy_default = "semi"                      # off | observe | suggest | semi | full
tool_calls_per_minute = 10
player_lock_seconds = 10.0

[agents.evolution]                             # Phase 4
enabled = true
min_events = 8
cooldown_seconds = 900.0
max_reflections_per_day = 24
trait_swap = "propose"                         # off | propose | auto
drift_strength = 0.2

[agents.initiative]                            # v0.2 A2/A3
level = "full"                                 # minimal | moderate | full
player_sim_level = "suggest"
cooldown_sim_minutes = 8.0
event_react_threshold = 1.0
spontaneous_lines = true
quota_fraction = 0.8
max_impulses_per_tick = 1

[agents.personality]                           # v0.2 P1
absorption_enabled = true
salience_threshold = 1.5
max_traumas = 5
max_beliefs = 10
trauma_decay = "slow"                          # fast | normal | slow
sleep_consolidation = true

# ─── GOD ─────────────────────────────────────────────────────────────
[god]
enabled = false
preset = "novela"
intervention_frequency = 0.5
intensity = 0.5
mood_influence = 0.5
autonomy_degree = 0.5
chaos_degree = 0.3
base_interval_seconds = 600.0                  # Phase 5c orchestration cadence
powers = { spawn_npc = true, apply_trait = true, force_social = true,
           gossip = true, relationship_shift = true, extreme_events = false }

[god.settings]
evolution_speed = "normal"

[god.backgrounds]                              # Phase 5b batch pipeline
enabled = true
batch_size = 2
interval_seconds = 15.0
idle_seconds = 30.0
per_minute = 6
daily_limit = 120
max_queue = 200
max_attempts = 2
```

### B. Tool surface (by autonomy level)

| Tool | Executes | observe | suggest | semi | full |
|---|---|:---:|:---:|:---:|:---:|
| `get_needs` | game | ✓ | ✓ | ✓ | ✓ |
| `get_relationships` | game | ✓ | ✓ | ✓ | ✓ |
| `get_inventory` | game | ✓ | ✓ | ✓ | ✓ |
| `get_world_time` | game | ✓ | ✓ | ✓ | ✓ |
| `propose_action` | game | ✗ | ✓ | ✓ | ✓ |
| `queue_interaction` | game | ✗ | ✗ | ✓ | ✓ |
| `move_to` | game | ✗ | ✗ | ✓ | ✓ |
| `say_to` | game | ✗ | ✗ | ✓ | ✓ |
| `cancel_current` | game | ✗ | ✗ | ✗ | ✓ |

Canonical argument keys are defined in `sidecar/sensewright_sidecar/tools/schemas.py`
(the single source of truth); the mod reads them strictly, without aliases
(`buff_name`, `trait_name`, `interaction_name`, `target_sim_id`, …).

### C. Locale files and language resolution

- Shipped locales: `en` (default, source of truth) and `pt-BR`.
- Files live at `sensewright_mod/locales/<locale>.json` and are bundled in the `.ts4script`.
- Resolution: `config [ui].language` → game language (if `auto`) → `en`.
- Missing keys fall back to `en`; a CI/test validates key parity between locales.
- The sidecar receives `lang` on every request and produces LLM content in it; system/UI
  responses return `message_key` + `message_args` for mod-side localization.

### D. References

- sims4ai — TRD and implementation (equivalent project): https://github.com/dnavaria/sims4ai
- Sims 4 Community Library (S4CL): https://github.com/DeviantGameMods/Sims4CommunityLibrary
- S4CL Template Project (decompile): https://github.com/DeviantGameMods/s4cl-template-project
- ts4-modding-workspace: https://github.com/azigler/ts4-modding-workspace
- Sentient Sims: https://www.sentientsimulations.com/
- Generative Agents (Smallville): https://arxiv.org/abs/2304.03442
- Voyager (Minecraft): https://arxiv.org/abs/2305.16291
- Providers: Gemini (sw.google.dev) · OpenRouter (openrouter.ai) · OpenCode Zen (opencode.ai/zen) · DeepSeek (api-docs.deepseek.com) · Cloudflare Workers AI (developers.cloudflare.com/workers-ai)

---

*End of document.*
