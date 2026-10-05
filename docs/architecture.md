# Sensewright v2 — Detailed Architecture

This document describes the internal architecture of Sensewright v2: the dual-process design, threading model, dual-clock system, Shadow DB, IntentBus, LLM layer, i18n engine, God Director, and world layer. It is intended for contributors and advanced modders.

> **Planned changes (see the [Architectural Review & Evolution Plan](operations.md), 2026-10-03):**
> the open-loop `IntentBus` will become **closed-loop** (Mod ACK/NACK outcomes on
> `/v1/autonomy/tick`), all EA/S4CL access will move behind **`engine_facade.py`** with an
> in-game **`sw.smoke_test`** introspection harness, the `ContextAssembler` will gain
> **token-priority packing**, and the LLM output parser will gain a **local JSON repair** layer.
> These are planned, not yet implemented; this document describes the current code.
>
> **Reconciled 2026-10-04** against the code and [`doc-review.md`](doc-review.md): canonical
> tick unit (§2), real Mod threading model (§1.3), `remember`/`forget` removed from the
> IntentBus (§4), reordered 5-level lease matrix (§4.4), and refreshed gap summary (§13).

---

## 1. Dual-Process Architecture

### 1.1 Process Boundary

| Process | Runtime | Responsibility |
|---------|---------|----------------|
| **The Sims 4 (Game)** | Python 3.7 (stdlib + S4CL + Lot 51 Core) | Main thread: `GAME_TICK`, state collection, intent execution, native hooks, UI. Two daemon threads: outbound HTTP worker + idle intent pull (see §1.3). |
| **Sidecar** | Python 3.10+ (FastAPI, uvicorn, SQLite, LLM providers) | REST API (`/v1/*`), Web Studio (`/ui`), LLM orchestration (scheduler, router, provider chain), SaveVault (SQLite + FTS5), i18n compilation. |

### 1.2 Communication Contract

- **Transport**: HTTP/1.1 over loopback (`127.0.0.1:8765` by default).
- **Serialization**: JSON only. Strict sanitization (`_sanitize_payload`) ensures only primitive JSON types (`int`, `float`, `str`, `bool`, `list`, `dict`).
- **Trace ID**: Every request carries `X-Trace-Id` (format `tr_XXXXXXXX`) for end-to-end correlation.
- **Direction**:
  - **Mod → Sidecar**: `POST /v1/lifecycle/*`, `/v1/census`, `/v1/autonomy/tick`, `/v1/chat`, `/v1/events`, `/v1/profile`, `/v1/evolve`, `/v1/memory/consolidate`, `/v1/god/*`, `/v1/agency/seats`, `/v1/config/player-activity`.
  - **Sidecar → Mod**: Responses on same HTTP connection (request-reply). Intents returned inline in `/v1/autonomy/tick` response (delta tick + pull integrated). Async intents also available via `GET /v1/autonomy/intents`.

### 1.3 Threading Model (Mod Side)

Post-hardening (`mod/sensewright_mod/http_client.py`), the Mod runs **two daemon threads**
next to the main thread, fed by **two outbound lanes**:

```
Main Thread (GAME_TICK)          Outbound lanes                 SensewrightWorker (daemon)
┌───────────────────────────┐    ┌──────────────────────────┐   ┌──────────────────────────────┐
│ state_collector.collect() │    │ _realtime_q (FIFO, ≤256; │   │ _worker_loop():              │
│ intent_bus.update()       │───▶│  only /events droppable, │──▶│   _next_item(): realtime     │
│ execute_intents(ready)    │    │  ≤48)                    │   │     lane first, then slots   │
│ update_idle_detection()   │    │ _slots (coalescing:      │   │   _make_request()            │
│ autonomy pulse check      │    │  /autonomy/tick merges   │   │   put(inbound_intents_q)     │
│                           │    │  sims_delta by sim_id,   │   │   idle → _wakeup.wait(0.5)   │
│ _submit() + _wakeup.set() │    │  /config/player-activity)│   └──────────────────────────────┘
│                           │    └──────────────────────────┘   SensewrightIntentPull (daemon)
│ process_inbound_queue() ◀─┼───────── inbound_intents_q ◀────┐ ┌──────────────────────────────┐
│   (drain responses)       │                                 └─│ _intent_pull_loop():         │
└───────────────────────────┘                                   │   GET /autonomy/intents      │
                                                                │   (after session-start;      │
                                                                │    backoff 2 s → 10 s)       │
                                                                └──────────────────────────────┘
```

- **Main Thread**: Never performs network I/O. Enqueues via `_submit()` (realtime lane or coalescing slot) and signals the `threading.Event` `_wakeup`; drains `inbound_intents_q` with `get_nowait()`.
- **`SensewrightWorker`**: Runs `_ensure_sidecar_running()` (autoboot) + `/lifecycle/attach`, then drains the realtime lane first and the coalescing slots second. When both are idle it blocks on `_wakeup.wait(0.5)` (no 10 ms busy poll). Per-endpoint timeouts (`_ENDPOINT_TIMEOUTS`).
- **`SensewrightIntentPull`**: Dedicated thread for the idle `GET /v1/autonomy/intents` pull, so a slow pull (5 s timeout) never delays lifecycle/chat/event dispatch. Gated on `session-start`; exponential backoff 2 s → 10 s, reset when intents arrive.
- **Locks**: the lanes are guarded by short `threading.Lock` sections (`_realtime_lock`, `_slot_lock`); no lock is held across network I/O. `queue.Queue` carries responses back to the main thread.
- **Shutdown**: `stop_worker()` sets `_shutdown_event` + `_wakeup` and joins both threads (2 s timeout each).
- **Frame Budget**: `process_inbound_queue()` processes max 50 items per `GAME_TICK` to avoid frame hitch.
- **Planned (doc-review ACT-06):** merge the intent pull and the future SSE stream into one inbound delivery thread (`_inbound_delivery_loop`, `timeout=15.0`, never `timeout=None`) — the Mod stays at 2 network threads.

### 1.4 Sidecar Threading

- **uvicorn** runs the FastAPI app (async, single-threaded event loop).
- **LLMScheduler** runs a background asyncio task (`_scheduler_loop`) that drains the job queue, enforces tier concurrency limits, and calls the ProviderChain.
- **SaveVault** uses a dedicated thread pool (`ThreadPoolExecutor`) for SQLite operations (WAL mode, `backup()` for Shadow DB).
- **Watchdog**: A daemon thread (`_watchdog_loop`) polls the attached `game_pid` every 5s; clean shutdown on game exit.

---

## 2. Dual-Clock System

| Clock | Source | Used For |
|-------|--------|----------|
| **Wall-Clock** | `time.time()` (real seconds) | HTTP timeouts, SLO enforcement (`llm.tiers.*.slo_seconds`), Provider rate limits (RPM/RPD/TPM), circuit breaker cooldowns, sidecar watchdog. |
| **Sim-Clock** | `world_sim_tick` (game ticks, **1 sim-minute = 1000 ticks**) | Intent `delay_sim_minutes`, `ttl_sim_minutes`, social cooldowns, memory decay (`PSYCHE_PRUNE_THRESHOLD` per sim-day), dream schedule, cognition daily plan, lease expiration (`lease_min_sim_minutes`), zone transition cleanup. |

**Conversion (canonical)**: `TICKS_PER_SIM_MINUTE = 1000` (`sidecar/sensewright_sidecar/constants.py`), hence `TICKS_PER_SIM_DAY = 1440 × 1000 = 1,440,000`. A 60 sim-minute lease is **60,000 ticks**, a 3 sim-minute rewind tolerance is **3000 ticks** (`REWIND_TOLERANCE_TICKS`). Game speed (`clock_speed`) scales wall-time → sim-time. When `clock_speed == 0` (pause), the mod's autonomy dispatcher freezes intent delay countdowns and suspends autonomy pulses.

> [!IMPORTANT]
> **No raw time arithmetic.** Any conversion between sim-minutes/sim-days and
> `world_sim_tick` must go through `TICKS_PER_SIM_MINUTE` / `TICKS_PER_SIM_DAY`. Treating
> 1 tick as 1 sim-minute shrinks leases, TTLs and psyche decay by three orders of magnitude
> (the root cause of S-B01/S-H02). External clients (e.g. MCP `ActionEnvelope`) must send
> durations in sim-minutes, never pre-converted ticks.

**Implementation**:
- Mod collects `world_sim_tick` and `clock_speed` from `GameClockService` via Lot 51 Core on every `GAME_TICK`.
- Sidecar receives these in every payload (`/v1/autonomy/tick`, `/v1/lifecycle/*`, etc.).
- Sidecar stores `world_sim_tick` in SQLite as the authoritative time column (`created_sim_tick`, `updated_sim_tick`, `expires_on_sim_tick`).

---

## 3. Shadow DB (Transactional Save Sync)

### 3.1 File Layout (per save slot)

```
data/saves/
├── slot_<save_id>.committed.db   # Exact state at last confirmed "Save Game"
├── slot_<save_id>.working.db     # Active session: all reads/writes happen here
├── slot_<save_id>.rev1.db        # Ring buffer: 3 most recent checkpoints
├── slot_<save_id>.rev2.db
└── slot_<save_id>.rev3.db
```

### 3.2 Lifecycle Events & DB Operations

| Event | Endpoint | DB Action |
|-------|----------|-----------|
| **Load save from Main Menu** | `POST /v1/lifecycle/session-start` | Discard any `.working.db`. Clone `.committed.db` → `.working.db`. Clear all RAM buffers (IntentBus, Short-Term Chat Buffer, ConversationManager). |
| **Travel between lots (same session)** | `POST /v1/lifecycle/zone-transition` | Keep `.working.db` intact. Clear only zone-scoped intents & social sessions. |
| **Player clicks "Save Game"** | `POST /v1/lifecycle/save` | Flush RAM buffers → `.working.db`. `sqlite3.Connection.backup(.working.db → .committed.db)` (< 5ms). Rotate ring buffer: `rev3←rev2←rev1←old_committed`. |
| **Player clicks "Save As..."** | `POST /v1/lifecycle/save` (with `previous_save_id != save_id`) | Preserve old `.committed.db` untouched. Create new `slot_<new_id>.committed.db` + `.working.db` pair from current `.working.db`. |
| **Load older save (rewind)** | `POST /v1/lifecycle/session-start` (tick < committed tick) | Restore from ring buffer (`rev1..rev3`) matching `world_sim_tick`, or `rewind_to_tick()` via SQL. |

### 3.3 Schema (SQLite)

```sql
-- metadata
CREATE TABLE metadata (
    save_id TEXT PRIMARY KEY,
    world_sim_tick INTEGER,
    last_committed_at INTEGER,  -- wall-clock epoch ms
    schema_version INTEGER
    -- planned (doc-review ACT-01): player_confidant_sim_id, returned on session-start
);

-- memories (core + FTS5 virtual table)
CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    sim_id INTEGER,
    type TEXT,                    -- 'event' | 'thought' | 'dream' | 'diary' | 'legacy' | 'compact'
    content TEXT,                 -- JSON
    search_text TEXT,             -- denormalized for FTS5
    importance REAL,              -- 0.0..1.0+
    strength REAL,                -- 0.0..1.0 (decays)
    created_sim_tick INTEGER,
    last_accessed_sim_tick INTEGER,
    consolidated INTEGER,         -- 0/1
    archived INTEGER              -- 0/1
);
CREATE VIRTUAL TABLE memories_fts USING fts5(search_text, content='memories', content_rowid='rowid');

-- relationships
CREATE TABLE relationships (
    sim_id INTEGER,
    target_id INTEGER,
    friendship REAL,
    romance REAL,
    known_traits TEXT,            -- JSON
    known_secrets TEXT,           -- JSON
    dynamic_label TEXT,
    qualitative_note TEXT,
    updated_sim_tick INTEGER,
    PRIMARY KEY (sim_id, target_id)
);

-- sims
CREATE TABLE sims (
    sim_id INTEGER PRIMARY KEY,
    profile TEXT,                 -- JSON (PROFILE_SHAPE)
    background TEXT,              -- JSON
    updated_sim_tick INTEGER
);

-- arcs (God Director)
CREATE TABLE arcs (
    id TEXT PRIMARY KEY,
    theme TEXT,
    beats TEXT,                   -- JSON
    current_beat_idx INTEGER,
    cast TEXT,                    -- JSON (NpcSheet[])
    status TEXT,                  -- 'planned' | 'armed' | 'executing' | 'completed' | 'aborted'
    created_sim_tick INTEGER
);

-- neighborhoods (World Layer)
CREATE TABLE neighborhoods (
    save_id TEXT PRIMARY KEY,
    zeitgeist TEXT,               -- JSON
    chronicles TEXT,              -- JSON
    rumors TEXT,                  -- JSON (RumorNode[])
    updated_sim_tick INTEGER
);
```

### 3.4 FTS5 Recall (Zero-Dependency)

When `embeddings = "none"` (default), memory recall uses `memories_fts` with BM25 ranking:

```sql
SELECT m.*, bm25(memories_fts) AS rank
FROM memories_fts
JOIN memories m ON m.rowid = memories_fts.rowid
WHERE memories_fts MATCH ? AND m.sim_id = ?
ORDER BY rank LIMIT ?;
```

No external vector DB or embedding model required.

> [!WARNING]
> **Known gap (doc-review §3.4 / ACT-04).** `SqliteStore.search_memories` currently binds the
> raw query text to `MATCH ?`. FTS5 query syntax (punctuation such as `?`, `:`, `-`, `*`, or the
> bare words `AND`/`OR`/`NOT`) raises `sqlite3.OperationalError`, which is swallowed and returns
> **zero memories**; whitespace is an implicit `AND`, so long natural-language queries rarely
> match. Planned fix: `sanitize_fts5_query(text)` — strip special characters, drop tokens
> ≤ 2 chars, quote each token and join with `OR`, letting BM25 rank the overlap.

---

## 4. IntentBus

### 4.1 Canonical Intent Shape

```json
{
  "id": "hex-uuid",
  "trace_id": "tr_9a8f12",
  "sim_id": 12345,
  "kind": "speak | approach | set_mood | bias_interaction | prefer_target | set_goal | command | spawn_npc",
  "target_sim_id": 67890,
  "params": {"text": "...", "tone": "friendly", "archetype": "..."},
  "thought": "...",
  "narration": "...",
  "delay_sim_minutes": 0.0,
  "ttl_sim_minutes": 15.0,
  "expires_on": "ttl | next_sleep | zone_transition",
  "priority": 0,
  "source": "agent | god | puppeteer | social"
}
```

> **Memory is not an intent.** Memories (SQLite + FTS5) live in the Sidecar, so `remember` /
> `forget` are **Sidecar-internal operations** (writes/archives on the `memories` table, exposed
> to MCP as `sim.remember` / `sim.forget`). They never travel through the IntentBus. The Mod
> still accepts the legacy wire kinds as a no-op (`GameLever._execute_remember` →
> `delegated_to_sidecar`) until they are removed from `INTENT_KINDS` (doc-review ACT-08).

### 4.2 Expiration Rules

| Intent Kind | `expires_on` | Default TTL |
|-------------|--------------|-------------|
| `speak`, `approach`, `command`, `spawn_npc` | `ttl` / `zone_transition` | 15.0 sim-minutes (15,000 ticks) |
| `set_mood`, `bias_interaction`, `prefer_target`, `set_goal` | `next_sleep` | — (cleared on sleep) |

### 4.3 Dispatch Pipeline (Main Thread)

1. `intent_bus.update()` called each `GAME_TICK`:
   - Decrement `delay_sim_minutes` for pending intents (scaled by `clock_speed`).
   - Move ready intents (`delay <= 0`) to `ready_list`.
   - Expire intents past `ttl_sim_minutes` or on `zone_transition` / `next_sleep`.
2. `execute_intents(ready_list)`:
   - For each intent, call `tool_executor.execute(intent)`.
   - Handlers are wrapped in `_safe_call` / `_safe_getattr` — never raise on main thread.
3. Results (success/failure) logged; failed intents may retry (config `intent_bus.max_retries`).

### 4.4 Source Priorities (Coordination)

Canonical matrix (shared with [`specification.md`](specification.md) F13 and [`mcp.md`](mcp.md)):

| Priority | Lease | Source | Behavior |
|----------|-------|--------|----------|
| 1 (highest) | `PLAYER_MANUAL` | Player click | Aborts AI actions on that Sim; locks autonomy for `player_lock_seconds` (15s). |
| 2 | `SANDBOX_OVERRIDE` | Player "Direct Scene Here (Sandbox Mode)" | Explicit player order — full control of any Sim (opt-in only); preempts every AI lease. |
| 3 | `GOD_CATALYST_PUPPET` | `god.puppeteer` | Full control of **catalyst NPCs only** (never household agents). |
| 4 | `SOVEREIGN_AGENT` | `sim.impulse`, `sim.reaction`, `sim.social`, Agency MCP | Autonomous agents. God applies only **Soft Influence**. |
| 5 (lowest) | `RULE_AUTOMATION` | `rules` engine (MCP, R6) | Soft Influence only, or acts only when the Sim is `idle` (honors REQ-IMP-03). |

`GOD_CATALYST_PUPPET` ranking above `SOVEREIGN_AGENT` does not let God hijack agents: the two
leases target **disjoint Sim sets** (catalyst NPCs vs. household/`full` seats).

**Code status:** `constants.LEASE_PRIORITY` encodes this order. `god/coordinator.lease_for`
currently assigns only `PLAYER_MANUAL` (wall-clock lock), `GOD_CATALYST_PUPPET` (catalyst
leases, expiring in ticks via `TICKS_PER_SIM_MINUTE`) and `SOVEREIGN_AGENT`;
`SANDBOX_OVERRIDE` and `RULE_AUTOMATION` are not yet assigned.

---

## 5. LLM Layer (Sidecar)

### 5.1 Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        LLMScheduler                             │
│  (single async queue, dedup by player:save:scope:id:purpose)   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌────────────────┐ ┌───────────────┐ ┌────────────────┐
│  interactive   │ │   realtime    │ │      bg        │  (tiers = concurrency + SLO + token budgets)
│  concurrency=4 │ │ concurrency=2 │ │ concurrency=1  │
└───────┬────────┘ └───────┬───────┘ └───────┬────────┘
        │                  │                  │
        └──────────────────┼──────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ModelRouter                                │
│  purpose → RoutePlan (provider, model, tier, params)           │
└──────────────────────────┬──────────────────────────────────────┘
                           │
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌────────────────┐ ┌───────────────┐ ┌────────────────┐
│ ContextAssembler│ │ ProviderChain │ │  Rate Limiter  │
│ (profile slice, │ │ (RPM/RPD/TPM, │ │  (per provider,│
│  TPM ceiling)   │ │  circuit brk) │ │   per model)   │
└────────────────┘ └───────────────┘ └────────────────┘
```

### 5.2 Two-Layer Configuration

**Layer 1 — `config.toml` `[llm.providers.*]`** (credentials & technical limits only):
```toml
[llm.providers.openrouter]
enabled = true
base_url = "https://openrouter.ai/api/v1"
api_key = "sk-..."
models = ["openai/gpt-4o-mini", "meta-llama/llama-3.1-8b-instruct:free"]
rpm = 20
rpd = 200
tpm = 40000
```

**Layer 2 — `config.toml` `[llm.routes.*]`, `[llm.tiers.*]`** (routing & generation budgets only):
```toml
[llm.routes.default]
provider = "openrouter"
model = "openai/gpt-4o-mini"

[llm.tiers.interactive]
slo_seconds = 3.0
max_input_tokens = 1500
max_output_tokens = 250
concurrency = 4
```

### 5.3 ProviderChain — Rate Limiting & Failover

- **Triple Limit**: RPM (req/min), RPD (req/day), TPM (tokens/min). TPM estimated before send (input tokens via tiktoken approx), reconciled with `usage.total_tokens` on response.
- **Circuit Breaker**: 3 consecutive failures → provider marked `cold` for 60s. Per-model cooldown: 2 failures → 120s.
- **Failover**: On rate limit exceed or circuit open, chain immediately tries next provider in route fallback order. No HTTP 429 bubbles up.
- **Free-Only Guard**: `free_only = true` blocks any paid model at client level.

### 5.4 ContextAssembler — Token Budgeting

Per-purpose input token ceiling (from `purposes.py` `in_tokens`), further capped by tier `max_input_tokens`. Assembles context from:
1. **Profile slices**: `micro` (~250 tok) for `phone_sms`, `deep` (~1200 tok) for `pc_chat`.
2. **Memory recall**: FTS5 top-K (default 5) by BM25.
3. **Psyche blocks**: Active blocks (`strength > 0.05`).
4. **Dream residue**: Last dream narrative.
5. **Relationship context**: Qualitative notes for target Sim.
6. **One-shot example**: Localized 1-shot (~15 tok) for output format.
7. **Anchor directive**: Imperative language lock as **last line** of prompt.

### 5.5 Structural Language Prevention (No `lexicon.json`)

Language adherence guaranteed at **prompt construction time**:
1. All enums (`mood`, `traits`, `activity`, `weather`, `sentiment`) translated via i18n `enum()` before prompt assembly.
2. One-shot example in target language (`prompt.one_shot_<lang>`).
3. Anchor directive (`prompt.anchor_<lang>`) injected as **absolute last line** of system prompt.

---

## 6. i18n Engine (4-Layer Cascade)

### 6.1 Resolution Order

For a key `k` in locale `L` (e.g., `pt-BR`):

1. **Overlay**: `data/locales/<kind>/L.json` (user/community drop-in)
2. **Exact Locale**: `sidecar/locales/<kind>/L.json` (official bundle)
3. **Base Subtag**: If `L` has `base_subtag: "pt"`, try `sidecar/locales/<kind>/pt.json`
4. **Manifest Default**: `sidecar/locales/<kind>/<default_locale>.json` (e.g., `en-US`)
5. **Missing Marker**: Returns `[missing:k]` + logs `validation_log("i18n.missing_key")`

### 6.2 Manifest as Single Source of Truth

```json
{
  "schema_version": 2,
  "default_locale": "en-US",
  "locales": [
    {
      "code": "pt-BR",
      "base_subtag": "pt",
      "display_name": "Português (Brasil)",
      "llm_language_name": "Português do Brasil (pt-BR)",
      "ts4_stbl_byte": "0x11",
      "ts4_client_tokens": ["por_br", "pt_br", "pt-br", "pt"],
      "direction": "ltr"
    }
  ]
}
```

Consumed by:
- **Mod detection**: `ts4_client_tokens[]` matched via word-boundary regex against TS4 client language string.
- **STBL compiler**: `ts4_stbl_byte` → Resource Key (`int(..., 16) << 32`).
- **LLM prompts**: `llm_language_name` injected into system prompt.
- **STBL byte**: `0x00` (en-US), `0x11` (pt-BR), etc. — matches Maxis STBL locale encoding.

### 6.3 Gender Inflection Macro

Syntax: `{g:masculine|feminine|neutral}` in any string value.

```python
# Runtime resolution
def _apply_gender(text, gender):
    # gender: "M" | "F" | "N"
    if gender == "F": return feminine
    if gender == "N" and neutral is not None: return neutral
    return masculine
```

### 6.4 List Rotation (Deterministic Variety)

Any string value can be a `list[str]`. Selection (`i18n_engine.py`):
```python
seed = f"{sim_id}:{world_sim_tick // 60}"
index = md5(f"{seed}:{key}").hexdigest() % len(list)
```

> [!NOTE]
> The bucket was designed as "per Sim per sim-hour", but with `TICKS_PER_SIM_MINUTE = 1000`
> `world_sim_tick // 60` changes every 60 ticks (~0.06 sim-minutes). A per-sim-hour bucket
> would be `world_sim_tick // (60 * TICKS_PER_SIM_MINUTE)`. Tracked as a code fix.

### 6.5 Hot-Reload

- Mod reads overlay from `data/locales/` (user data folder) with priority over embedded `.ts4script` locales.
- `POST /v1/i18n/reload` triggers `engine.reload()` — clears file cache, re-reads manifest + overlay.
- No game restart needed for translation updates.

---

## 7. God Director & Puppeteer

### 7.1 Four Soft Influence Levers (on Sovereign Agents)

| Lever | Mechanism | Purpose |
|-------|-----------|---------|
| **Dream Whisper** (`god_whisper`) | Injected into `sim.dream` prompt (weight 0.20 in Surrealism formula) | Plant premonitions, temptations, paranoia night before beat. |
| **Spatial/Thematic Gravity** | `prefer_target` + `bias_interaction` intents → hidden Commodity Buffs | Nudge native autonomy toward target/object/activity. |
| **Subtext Injection** | `scene_subtext` added to `ContextAssembler` for target agent | One perceptual line: *"You feel tension when X checks their phone."* Agent decides reaction. |
| **World Pressure** | `set_weather`, `world.gossip` (SMS/mailbox) | Set mood-congruent weather; deliver rumor via native channels. |

### 7.2 `god.puppeteer` — Catalyst NPC Loop

```
Beat Start
    │
    ▼
god.cast ──▶ Recruit existing townie (from census) OR instantiate new SimInfo
    │
    ▼
VisitSituation ──▶ NPC walks sidewalk, rings doorbell (native TS4 situation)
    │
    ▼
god.puppeteer (lease: GOD_CATALYST_PUPPET) ──▶ NPC approaches Sovereign Agent,
                                                delivers opening line/action,
                                                sustains puppeteer_objective
                                                during ConversationSession (F04)
    │
    ▼
god.react ──▶ Reads Agent's actual response (accept/reject/fight)
              Branches next beat accordingly
```

### 7.3 Director Modes

| Mode | Behavior |
|------|----------|
| `AUTONOMOUS` | God runs arcs, sends catalysts silently. No player prompts. |
| `CO_DIRECTOR` | Before catalyst beat: `SPECIAL_MOMENT` banner with **[🎬 Iniciar Cena]**, **[⏳ Adiar]**, **[🔄 Mudar Rumo]**. |
| `SANDBOX` | God only acts on manual player trigger ("Dirigir Cena Aqui" or Web Studio). |

### 7.4 God Controls (Editable In-Game / Web Studio)

```toml
[god]
director_mode = "AUTONOMOUS"
preset = "novela"                    # novela|sitcom|drama|caos|terror|romance|filme_adolescente
intervention_frequency = 0.5         # 0.0..1.0
intensity = 0.5
mood_influence = 0.5
autonomy_degree = 0.5
chaos_degree = 0.5
```

Presets map to default dial values (defined in `constants.py` `GOD_PRESETS`).

---

## 8. World Layer — Rumor Epidemiology

### 8.1 RumorNode

```json
{
  "id": "rumor_abc123",
  "origin_sim_id": 12345,
  "content": "Sim A traiu Sim B",
  "category": "betrayal",
  "salience": 1.8,
  "infected_sim_ids": [12345, 67890],
  "transmission_log": [{"from": 12345, "to": 67890, "tick": 1000, "channel": "social"}],
  "decay_rate": 0.05,
  "created_sim_tick": 950
}
```

### 8.2 Transmission Rules

- **Social Transmission**: During `sim.social` (F04), if Sim A knows a `RumorNode` unknown to Sim B and interaction category ∈ {`friendly`, `gossip`, `mean`}, rumor transmits to B (added to `infected_sim_ids`).
- **Phone SMS**: `world.gossip` purpose sends rumor via SMS to friends (`friendship > 20`).
- **Mailbox**: `world.household.chronicle` compiles daily chronicle; player reads via Mailbox → "Histórias da Vizinhança".
- **Decay**: Each sim-day, `salience *= (1 - decay_rate)`. Below threshold → purged.

### 8.3 Zeitgeist

Neighborhood-level thematic tags (`zeitgeist.tags[]`) influence:
- Dream engine (`zeitgeist` weight 0.15 in Surrealism).
- God Director `god.plan` (arc theme selection).
- Weather preference (`god.zeitgeist` output includes `weather_preference`).

---

## 9. REST Endpoint Reference

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/lifecycle/attach` | POST | Register game PID (watchdog) |
| `/v1/lifecycle/session-start` | POST | New session: clone committed→working, send bootstrap flag |
| `/v1/lifecycle/zone-transition` | POST | Zone change: clear spatial intents |
| `/v1/lifecycle/save` | POST | Flush + promote working→committed, rotate ring buffer |
| `/v1/census` | POST | Full static sim/household/relationship data |
| `/v1/autonomy/tick` | POST | Delta tick → returns `intents[]` + `social_sessions[]` inline |
| `/v1/autonomy/intents` | GET | Pull any pending intents (fallback) |
| `/v1/chat` | POST | Multi-channel chat (phone_sms / pc_chat / pc_email) |
| `/v1/hey` | POST | Alias: `channel="phone_sms"` |
| `/v1/events` | POST | Gameplay event → salience, psyche blocks, triggered jobs |
| `/v1/profile` | POST | Generate/fetch Sim profile (PROFILE_SHAPE) |
| `/v1/evolve` | POST | Reflection (sleep/mirror) → demeanor/preference/trait updates |
| `/v1/memory/consolidate` | POST | Consolidate short-term chat buffer → long-term memory |
| `/v1/god/tick` | POST | God Director tick → directives, active arc, catalyst leases |
| `/v1/god/direct-scene` | POST | Manual scene direction (sandbox/co-director) |
| `/v1/god/arc/steer` | POST | Player steers arc: approve/skip/rewrite/abort beat |
| `/v1/god/beat-ended` | POST | Catalyst conversation ended → `god.react` branches/advances the arc |
| `/v1/world/neighborhood` | GET/POST | Chronicles + zeitgeist + a Sim's known rumors (Mailbox) |
| `/v1/memory/diary` | GET/POST | Latest saved diary entry (Diary Tooltip / Snoop) |
| `/v1/god/controls` | GET/POST | Read/write God dials & mode |
| `/v1/god/zeitgeist` | POST | Set neighborhood zeitgeist from player text |
| `/v1/agency/seats` | GET/POST | SeatManager status / set seat count |
| `/v1/config/player-activity` | POST | Idle/clock_speed → deep window signal |
| `/v1/health` | GET | Health check + version + game_pid |
| `/v1/status` | GET | Full system status (providers, queue, tiers, routes, active save) |
| `/v1/config/lang` | POST | Set active language |
| `/v1/i18n/reload` | POST | Hot-reload locale files |
| `/v1/i18n/compile-addon` | POST | Compile STBL addon from overlay |
| `/ui` | GET | Web Studio SPA |

---

## 10. Key Invariants & Safety Nets

| Invariant | Enforcement |
|-----------|-------------|
| Main thread never blocks on I/O | Worker thread only HTTP path; `queue.Queue` non-blocking |
| Python 3.7 bytecode in `.ts4script` | `build.py` verifies magic number `42 0d 0d 0a` |
| Save sync atomic | `sqlite3.backup()` (< 5ms); ring buffer preserves last 3 checkpoints |
| No orphan LLM data | Every purpose has `fallback_key` → deterministic localized output |
| Language adherence | Structural prevention (enum translation + 1-shot + anchor) |
| Agent sovereignty | `GOD_CATALYST_PUPPET` applies to catalyst NPCs only; God never overrides a `SOVEREIGN_AGENT` queue (Soft Influence only); `RULE_AUTOMATION` ranks below agents |
| Canonical time unit | Every sim-time span converted with `TICKS_PER_SIM_MINUTE = 1000` |
| Visitor protection | `REQ-SEAT-02`: no eviction during active conversation / catalyst lease / `lease_min_sim_minutes` |
| Rate limit honesty | Provider RPM/RPD/TPM **not refunded** on timeout; Game Budget **refunded** |
| Zero hardcoded locales | All locale codes, STBL bytes, client tokens from `manifest.json` |

---

## 11. Data Flow Summary

```
GAME_TICK (Main Thread)
    │
    ├─▶ state_collector → sims_delta
    │
    ├─▶ _submit(POST /v1/autonomy/tick {sims_delta, ...}) → coalescing slot
    │         │
    │         ▼ (SensewrightWorker thread)
    │    HTTP POST → Sidecar
    │         │
    │         ▼ (Sidecar)
    │    LLMScheduler.enqueue(purpose=sim.impulse, tier=realtime, ...)
    │         │
    │         ▼ (async)
    │    ModelRouter → RoutePlan
    │    ContextAssembler → prompt (≤700 tok)
    │    ProviderChain → LLM call (with RPM/RPD/TPM guard)
    │         │
    │         ▼
    │    Response: {intents[], social_sessions[]}
    │         │
    │         ▼ (Worker Thread)
    │    inbound_intents_q.put(response)
    │
    ▼ (next GAME_TICK)
process_inbound_queue() → intent_bus.update() → execute_intents()
    │
    ▼
Native TS4 execution (interactions, buffs, moodlets, sentiments, mailbox, etc.)
```

---

## 12. Extension Points

| Extension | Mechanism |
|-----------|-----------|
| New LLM Provider | Add `[llm.providers.<name>]` section + implement `BaseProvider` interface |
| New Purpose | Add to `purposes.py` `PURPOSES` list + implement handler in `services/` + register route |
| New Locale | Add `<locale>.json` to `sidecar/locales/ui/` & `content/` + update `manifest.json` + `make package` |
| New God Preset | Add to `constants.py` `GOD_PRESETS` + define dial defaults in `god.plan` prompt template |
| New Intent Kind | Add to `Intent.kind` union + handler in `tool_executor.py` + archetype mapping in `register_archetype_mappings` |
| New Visual Channel | Extend `ui_manager` + add `visual_type` to intent `params` + STBL keys in `ui` locale |

---

## 13. Unverified / Implementation Gaps

For the precise, up-to-date gap analysis (per milestone, feature, and purpose, with
`file:line` evidence), see **[`docs/project-status.md`](project-status.md)**. In summary:

State as of 2026-10-04 (689 sidecar tests; `.package` 46 resources):

- **Full (29 of 33 purposes):** every purpose except the four below has a production trigger
  and consumes its result — including `god.cast`, `god.react`, `god.background`
  (+ `BackgroundScheduler`), `world.aftermath`, `world.npc.backstory`, `mem.legacy`,
  `mem.relationship.review`, `sim.social.close`, `sim.aspiration`, `ops.recap`,
  `ops.panel.summary`. Per-model cooldown, tier concurrency, asymmetric refund, `trace_id`
  on `bg`/`deep`, `autonomy_mode` (`full|reactive|off`) and `GameBudgeter` are enforced.
- **Partial:** `god.puppeteer` (lease + opening line + asymmetric routing in `sim.social`; no
  `approach` intent), `sim.lifestory` (only on lifecycle events; no 7-day trigger),
  `mem.compact` (no panel exposure), `evo.trait` (helpers ready, no emission).
- **Synchronous LLM in `handle_event`:** `mem.legacy` + `sim.lifestory` still run inline on
  `death|marriage|birth` (doc-review §3.3 / ACT-04 — to be made async).
- **Open-loop actuation:** the Mod does not report intent outcomes yet (`outcomes[]`, ACT-03).
- **Native object coupling (M5/M6):** `VisitSituation`, Diary/Snoop, Mailbox, sleep balloons
  and the Mirror "Reflect" interaction were **coded blind**. To prevent breaking the engine, they must now be validated via [Spike-Driven Development](spike-strategy.md) (`sw.spike`) *before* Playtest #5.
  `sim_GetToKnow` is pending; the physical Autobiography Book and Tombstone Epitaph are
  **deferred post-v2.0** (replaced by Diary/Computer/Web Studio reading).
- **Hidden Confidant** is still located by last-name heuristic; persisting
  `player_confidant_sim_id` in `metadata` is pending (BUG-12, ACT-01).
- In-game acceptance criteria (zone transition, Save As, Alt+F4 rollback, invisible
  autoboot) remain unvalidated outside unit tests.
- S4CL / Lot 51 Core integration points are exercised against pinned reference clones;
  actual game-build versions may differ.

---

## 14. Dual UI — Quick Menu & Web Studio

| UI | Access | Purpose |
|----|--------|---------|
| **Quick Menu (Pie)** | Click any Sim → Sensewright | Chat (Phone/PC), Provoke, Panel, Director controls |
| **Quick Menu (Shift+Click)** | Shift+Click any Sim → Sensewright | Advanced: Profile, Memory, Seat, God controls |
| **Web Studio — Inspector** | `http://127.0.0.1:8765/ui` → Inspector | Live sim state, intent bus, memory, psyche, relationships |
| **Web Studio — Script Room** | `http://127.0.0.1:8765/ui` → Script Room | God Director controls, arc/beat editor, scene direction |
| **Web Studio — Setup** | `http://127.0.0.1:8765/ui` → Setup | Config editor, provider status, locale manager, STBL compiler |

The Web Studio SPA is served by `sidecar/sensewright_sidecar/webui/` (`GET /ui`); its REST
backing endpoints are listed in §9. The in-game Quick Menu is the Mod-side `panel_ui.py` /
`pie_menu.py`.
