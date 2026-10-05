# Sensewright v2 — MCP Layer (Architecture & Plan)

> **Branch:** `v2-remake`
> **Status:** design — not yet implemented.
> **Goal:** let LLM agents actually **control** the Sims and the world (especially the
> "God/Director" case) accurately and dynamically, and let the user's custom **"ifs"**
> (conditions) run inside the game. Delivery: **≥2 MCP servers with distinct in-game control
> APIs** plus a rules server.
>
> **Locked decisions (2026-10-03):**
> 1. **Protocol:** official **`mcp`** SDK (FastMCP, *Streamable HTTP*, spec 2025-06-18).
> 2. **Exposure:** three URL endpoints mounted in the existing sidecar FastAPI app
>    (`/mcp/agency`, `/mcp/god`, `/mcp/rules`), loopback only.
> 3. **Order:** **substrate first, facades second.** Close the in-game validation (Phase 5) and
>    the review's R1–R5 prerequisites (closed-loop telemetry, unified transport, engine facade +
>    smoke test, token packing, JSON repair) **before** exposing the facades — otherwise MCP
>    would only standardize access to broken or silent levers.
>
> > **Superseded by the Architectural Review.** This design has been revised per the
> > [Architectural Review & Evolution Plan](operations.md): the Action Gateway now uses
> > **closed-loop telemetry** (Mod ACK/NACK, R1), the transport is **unified** (2 threads, SSE
> > timeout+heartbeat, R2), and sovereignty arbitration (PC-04) plus a reordered phase plan are
> > reflected below. The earlier "fire-and-forget + `timeout=None` SSE" description was replaced.

**On this page**
- [Why: root cause](#why-root-cause)
- [Invariants & constraints](#invariants--constraints)
- [Components](#components)
- [Protocol & transport](#protocol--transport)
- [Action Gateway](#action-gateway)
- [Facade `agency` — per-Sim embodiment](#facade-agency--per-sim-embodiment)
- [Facade `god` — world / Director](#facade-god--world--director)
- [Facade `rules` — the "ifs"](#facade-rules--the-ifs)
- [Authority, leases & security](#authority-leases--security)
- [Intent delivery to the mod (SSE)](#intent-delivery-to-the-mod-sse)
- [New intent kinds](#new-intent-kinds)
- [Observability & Web Studio](#observability--web-studio)
- [Phases & acceptance](#phases--acceptance)
- [Risks](#risks)
- [Integration map](#integration-map)
- [Test strategy](#test-strategy)

---

## Why: root cause

The project has a complete **perception → cognition → intent → execution** pipeline, but the
only control plane is **one-way** (mod reports state, receives intents). There is **no** MCP,
tool/function-calling, inbound agent API, or rule engine. Three structural failures explain
why features "run but stay invisible":

| # | Cause | Consequence |
|---|---|---|
| C1 | No inbound control plane | LLMs only *react* to the autonomy tick; they cannot *drive* |
| C2 | Intents are fire-and-forget | No closed loop: agents never see the outcome |
| C3 | Missing wiring/triggers; misleading levers | Code exists but is never triggered, or reports success with no effect |
| C4 | No in-game validation in the dev loop | Defects surface only at playtest |

The MCP layer turns the existing `IntentBus` into a **bidirectional actuator with telemetry**:
a Tool Gateway validates authority, maps tools to intents, and reports an `outcome` back.

---

## Invariants & constraints

| Invariant | How MCP honors it |
|---|---|
| Mod main thread only drains `inbound_intents_q` (max 50/tick) | The SSE stream only `put`s on the queue; no I/O on the main thread |
| Worker thread is the only HTTP path | The SSE reader is an additional isolated thread; it only enqueues |
| Pure Python 3.7 in the mod | No 3.10+ syntax; SSE consumed via stdlib `urllib.request` |
| Sidecar is the single source of truth | MCP translates tools → Gateway → `AppState`/intents; no state duplication |
| Failure degrades to deterministic fallback (0-key) | LLM-backed tools go through `LLMScheduler` (fallbacks) |
| Player sovereignty | Gateway consults `lease_for`/`can_god_puppeteer`; conflict → `LEASE_DENIED` |
| Additive wire contract | New intent kinds degrade to `command` via `normalize_intent` |

---

## Components

```
┌─ SIDECAR (Python 3.10+, 127.0.0.1:8765) ─────────────────────────────────────────────┐
│                                                                                       │
│  REST /v1/*            MCP Streamable HTTP (SDK `mcp`)         Rules                  │
│  ┌──────────────┐      ┌──────────────────────────────┐        ┌───────────────────┐   │
│  │ current routes│     │ FastMCP#agency  → /mcp/agency│        │ ConditionEngine   │   │
│  │ + /v1/actions│      │ FastMCP#god     → /mcp/god   │        │ (table `rules`)   │   │
│  │ + /stream    │      │ FastMCP#rules   → /mcp/rules │        └─────────┬─────────┘   │
│  └──────┬───────┘      └───────────────┬──────────────┘                  │             │
│         │        ┌─────────────────────┴─────────────────┐               │             │
│         └───────▶│            Action Gateway              │◀──────────────┘             │
│                  │  token→scope→sim_id · dedup action_id  │                             │
│                  │  tool→(read | intent | world | llm)    │                             │
│                  │  outcome ledger                        │                             │
│                  └───────┬─────────────┬─────────┬────────┘                             │
│         read: AppState/SQLite   intents: enqueue   world: god handlers                  │
│                          │   AppState.enqueue_intents ─┐                               │
│                          │   LLMScheduler (sim.chat)   │                               │
│                          ▼                             ▼                               │
│                   /v1/status  ◀──────────────  _pending_intents                        │
└───────────────────────────────────────────────┬───────────────────────────────────────┘
         ┌───────────────────────┬──────────────┴───────────────┐
         │ /v1/autonomy/tick     │ GET /v1/autonomy/intents     │ GET /v1/autonomy/stream (SSE)
         │ (inline response)     │ (pull 2–10 s, fallback)      │ (NEW: sub-second push)
         ▼                       ▼                              ▼
┌─ MOD (Python 3.7) ────────────────────────────────────────────────────────────────────┐
│ worker thread (urllib)  +  intent-pull thread  +  NEW streaming thread                │
│        └─────────────► _inbound_intents_queue  ◀───────────────────────────────┘      │
│ main thread (GAME_TICK): process_inbound_queue → IntentBus.update → execute_intents    │
└───────────────────────────────────────────────────────────────────────────────────────┘
```

**Why in the sidecar (not a separate process):** reuses `AppState`, `SaveVault`,
`LLMScheduler`, leases and logging; one connection to the game; no cross-process state.

---

## Protocol & transport

### MCP Streamable HTTP (spec 2025-06-18)

- **One endpoint per facade:** `POST /mcp/agency`, `/mcp/god`, `/mcp/rules` (+ `GET` for the
  session SSE channel).
- **Messages:** JSON-RPC 2.0. Methods: `initialize`, `notifications/initialized`, `tools/list`,
  `tools/call`, `ping`.
- **Session:** `initialize` returns `Mcp-Session-Id`; the client echoes it. `tools/call`
  answers as plain JSON; the SSE channel carries **server→client notifications** (an action's
  `outcome`, `rule.fired`).
- **Capabilities:** `tools: {}` (no resources/prompts yet); `protocolVersion: "2025-06-18"`.

### Implementation with the SDK

- New dependency: `mcp>=1.9` in `sidecar/requirements.txt` and `pyproject.toml`.
- Each facade is a `FastMCP(name=..., stateless_http=False)` instance mounted on the existing
  app:
  ```python
  # sidecar/sensewright_sidecar/server.py (create_app)
  from .mcp import build_mcp_apps
  for path, asgi in build_mcp_apps(config).items():
      app.mount(path, asgi)   # /mcp/agency, /mcp/god, /mcp/rules
  ```
- **Isolation:** the three instances share the same `ActionGateway`/`AppState` but have
  distinct tool registries and scopes (the token decides what a client may see).
- **Dependency fallback:** if the SDK cannot be installed, `mcp/spec.py` exposes the **same
  internal interface** (`list_tools`, `call_tool`) and `server.py` falls back to a minimal
  JSON-RPC 2.0 server (Starlette `EventSourceResponse`) behind the same contract.

---

## Action Gateway

New module `sidecar/sensewright_sidecar/mcp/gateway.py`; endpoint `POST /v1/actions`.

### Envelope

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "ActionEnvelope",
  "type": "object",
  "required": ["action_id", "tool", "authority", "lang"],
  "properties": {
    "action_id":  { "type": "string", "pattern": "^[a-f0-9]{16}$" },
    "trace_id":   { "type": "string" },
    "authority":  { "enum": ["player", "agent", "god", "rules"] },
    "tool":       { "type": "string", "pattern": "^[a-z]+\\.[a-z_]+$" },
    "sim_id":     { "type": "integer", "minimum": 0 },
    "target_sim_id": { "type": ["integer", "null"] },
    "params":     { "type": "object" },
    "delay_sim_minutes": { "type": "number", "minimum": 0 },
    "ttl_sim_minutes":   { "type": "number", "minimum": 0, "maximum": 1440 },
    "expires_on": { "enum": ["ttl", "next_sleep", "zone_transition"] },
    "priority":   { "type": "integer", "minimum": 0, "maximum": 10 },
    "lang":       { "type": "string", "minLength": 2 },
    "world_sim_tick": { "type": "integer", "minimum": 0 },
    "save_id":    { "type": "integer", "minimum": 0 }
  }
}
```

### Pipeline

1. **Auth:** `Authorization: Bearer <token>` → `{scope, sim_id, exp}` (see §Security).
2. **Tool belongs to scope?** otherwise `unknown_tool`.
3. **Params** validated against the tool's `inputSchema`.
4. **Authority/lease:** `agent` pinned to its `sim_id`; `god` restricted to its domain;
   `rules` limited to the whitelist; consult `lease_for`/`can_god_puppeteer`.
5. **Idempotency:** dedup `action_id` in RAM (same pattern as `state.accept_tick`), 10-min TTL,
   replay returns the cached result.
6. **Routing** by tool class:

   | Class | Gateway action |
   |---|---|
   | `read` | read `AppState`/SQLite and answer directly |
   | `intent` | `normalize_intent` + `AppState.enqueue_intents` |
   | `world` | call the existing handler (`god_tick`, `run_cast`, `create_arc`, `steer_arc`, `run_zeitgeist`, …) |
   | `llm` | `LLMScheduler.submit_bg` / `submit_realtime` |
7. **Outcome ledger (closed-loop — R1):** the Sidecar records `queued`, but the authoritative
   `applied|failed|expired|preempted_by_player` comes back from the Mod. The Mod attaches
   `outcomes: [...]` to `POST /v1/autonomy/tick` (and may `POST /v1/actions/outcomes` when an
   MCP call awaits a synchronous/SSE answer). The ledger is keyed by `action_id` and exposed in
   `/v1/status` and via SSE. The Sidecar never assumes success after enqueue.

### Tool registry

```python
@dataclass
class ToolSpec:
    name: str                 # "sim.speak"
    scope: str                # "agency" | "god" | "rules"
    kind: str                 # "read" | "intent" | "world" | "llm"
    intent_kind: str | None   # maps to Intent.kind when kind == "intent"
    input_schema: dict        # JSON Schema
    handler: Callable         # optional (world/read)
    min_lease: str | None     # "SOVEREIGN_AGENT" | "GOD_CATALYST_PUPPET" | None
    risk: str                 # "low" | "medium" | "high"
```

`tools/list` is generated from the `ToolSpec`s of the scope; each `description` states the
real effect and current limits (honesty).

---

## Facade `agency` — per-Sim embodiment

**Scope:** one Sim = one `SOVEREIGN_AGENT` lease. Speaks in **character verbs**.

### Perception (read)

| Tool | Params | Returns | Source | Status |
|---|---|---|---|---|
| `sim.perceive` | `sim_id` | mood, needs, activity, room, pos, queue, relationships | **new** `GET /v1/sims/{id}` (from `state.census`) | GAP |
| `sim.nearby` | `sim_id, radius` | nearby sims/objects | **new** read via `pos`/`room_id` | GAP |
| `sim.recall` | `sim_id, query, k` | memories (FTS5/BM25) | **new** `POST /v1/memory/recall` | GAP |
| `sim.list_sims` | — | seats + census | `GET /v1/agency/seats` | EXISTS |

### Action (intent/llm)

| Tool | Intent kind | Params | Native lever (mod) | Status |
|---|---|---|---|---|
| `sim.speak` | `speak` | `text, tone, balloon_type` | `tool_executor._execute_speak` | EXISTS |
| `sim.set_mood` | `set_mood` | `mood, duration_sim_minutes` | `native_hooks.apply_mood` (+3 new buffs) | EXISTS |
| `sim.go_to` | `approach` | `target_sim_id` | `send_near_position` | Partial (pos/room = GAP) |
| `sim.interact_sim` | **`interact`** | `target_sim_id, interaction` | S4CL `queue_interaction` | GAP |
| `sim.interact_object` | **`interact`** | `object_type\|object_id, interaction` | S4CL + `object_manager` | GAP |
| `sim.queue` | **`interact`** | `interaction, delay_sim_minutes` | `intent_bus` delay | GAP |
| `sim.cancel_queue` | **`cancel`** | `interaction?` | mutate `sim.queue` | GAP |
| `sim.set_goal` | `set_goal` | `goal, block` | write-only (sidecar owns plan) | Documented |
| `sim.bias` | `bias_interaction` | `archetype, weight, duration` | commodity/mood buffs | EXISTS |
| `sim.prefer_target` | `prefer_target` | `target_sim_id` | `add_relationship_bit` | EXISTS (honest) |
| `sim.relate` | **`relate`** | `sentiment, target_sim_id` | `add_relationship_bit` | GAP |
| `sim.remember` | — | `text, category` | sidecar memory | **new** `/v1/memory/remember` |
| `sim.forget` | — | `memory_id` | sidecar memory | **new** `/v1/memory/forget` |
| `sim.chat` | `llm` | `channel, message` | `/v1/chat` | EXISTS |
| `sim.diary` / `sim.profile` | read | `sim_id` | `/v1/memory/diary`, `/v1/profile` | EXISTS |

---

## Facade `god` — world / Director

**Scope:** world, arcs, catalysts, neighborhood. Speaks in **world verbs**. No per-Sim
sovereignty (soft influence only).

| Tool | Params | Mapping | Status |
|---|---|---|---|
| `god.weather` | `weather, duration_sim_hours` | `command:weather.set` (real API already fixed) | EXISTS (validate in-game) |
| `god.set_speed` | `speed (0–3)` | **new** `command:time.set_speed` (S4CL `set_clock_speed`) | GAP |
| `god.set_time` | `day, hour, minute` | **new** `command:time.set` (mutate `GameClock`) | GAP (high risk) |
| `god.spawn_npc` | `target_sim_id, role, objective` | kind `spawn_npc` | EXISTS |
| `god.cast` | `role, objective, target_sim_id` | **new** `POST /v1/god/cast` (`run_cast`) | GAP endpoint |
| `god.route_catalyst` | `catalyst_sim_id, target_sim_id, objective` | `POST /v1/god/direct-scene` (`run_puppeteer`) | EXISTS |
| `god.dream_whisper` | `sim_id, hint` | **new** `POST /v1/god/whisper` | GAP |
| `god.subtext` | `beat_id, subtext` | **new** `POST /v1/god/subtext` | GAP |
| `god.gossip` | `text, from_sim_id, tags` | **new** `POST /v1/world/rumor` | GAP |
| `god.chronicle` | `text` | **new** `POST /v1/world/chronicle` | GAP |
| `god.zeitgeist` | `tags?, text?, preset?, weather_preference?` | `POST /v1/god/zeitgeist` | EXISTS |
| `god.arc_plan` | `theme, beats?, cast?` | **new** `POST /v1/god/arc/plan` (`create_arc`) | GAP endpoint |
| `god.arc_steer` | `action, beat_id?, instruction?` | `POST /v1/god/arc/steer` (`steer_arc`) | EXISTS |
| `god.arc_advance` | — | **new** `POST /v1/god/arc/advance` (`advance_arc`) | GAP endpoint |
| `god.scene_direct` | `catalyst_sim_ids, target_sim_ids, prompt_text, mode` | `POST /v1/god/direct-scene` | EXISTS |
| `god.spawn_object` | `object_type, position?` | **new** `command:object.spawn` | GAP (high risk) |
| `god.trigger_event` | `sim_id, category, impact, …` | `POST /v1/events` (`handle_event`) | EXISTS |
| `god.inspect_world` | `save_id, sim_id?` | `neighborhood` + `arc` + `cast` + `status` | EXISTS |

### API distinction

`agency` talks **character verbs** (speak, feel, go, interact, remember) bound to a `sim_id`;
`god` talks **world verbs** (weather, time, catalysts, arcs, rumors). Two distinct contracts,
different authority and risk.

**Zero-save-pollution (R8).** `god.cast` must **reuse** census townies whenever >5 available
townies exist (~99% of cases) — never spawn a persistent `SimInfo` casually. The Hidden
Confidant's `player_confidant_sim_id` is persisted in the save's `metadata` table and returned
on `session-start`, replacing string-search heuristics and enabling a one-shot GC of the
orphan confidants.

---

## Facade `rules` — the "ifs"

### Tools

| Tool | Params | Returns |
|---|---|---|
| `rules.define_rule` | `rule_id?, name, when, then[], enabled?, cooldown_sim_minutes?, max_fires_per_sim_day?` | persisted rule |
| `rules.list_rules` | `enabled?` | list |
| `rules.enable_rule` / `rules.disable_rule` | `rule_id` | ok |
| `rules.test_rule` | `rule_id` | `{would_fire, actions}` (dry-run) |

### DSL (`when`)

```json
{
  "rule_id": "cond_abc123",
  "sim_id": null,
  "name": "sad_and_alone",
  "enabled": true,
  "when": {
    "trigger": "tick",
    "every_sim_minutes": 30,
    "all": [
      { "predicate": "mood_is", "value": "SAD" },
      { "predicate": "no_nearby_sims", "radius": 8.0 }
    ]
  },
  "then": [
    { "tool": "sim.speak", "sim_id": 12345, "params": { "text": "*sigh*", "tone": "melancholic" } },
    { "tool": "sim.bias",  "sim_id": 12345, "params": { "archetype": "write_diary", "weight": 2.0 } }
  ],
  "cooldown_sim_minutes": 30,
  "max_fires_per_sim_day": 3
}
```

**Triggers:** `tick`, `interval`, `event`, `need`, `relationship`, `venue`, `time`.
**Combinators:** `all`, `any`, `not` (recursive).
**Predicates:** `mood_is`, `no_nearby_sims`, `need_below/above`, `relationship` (min/max),
`venue_type`, `time_of_day`, `min_salience`, `event_category`.

### Execution

- **Storage:** a `rules` table in the SaveVault (`sqlite_store.py`) — follows the
  working/committed cycle.
- **Trigger indexing (R6):** the `ConditionEngine` does **not** scan every rule each
  `autonomy_tick`. In-memory indexes in `AppState` — `rules_by_trigger["tick"]`,
  `rules_by_trigger["event:<category>"]`, `rules_by_trigger["need"]` — select only the rules
  relevant to the current trigger.
- **Deterministic evaluation:**
  - tick/interval/need/relationship/venue/time → `handle_autonomy_tick`.
  - event/min_salience → `handle_event`.
  - Actions → the Action Gateway with `authority="rules"` (`sim.*`/`god.*` whitelist).
- **Lease (R6):** rules run under `RULE_AUTOMATION` (below `GOD_CATALYST_PUPPET`), emitting
  **Soft Influence only** or acting only when the Sim is `idle`, honoring the Survival &
  Punctuality Guard of REQ-IMP-03.
- **Safety caps:** ≤32 rules/save; ≤5 actions/rule; ≤10 rule-actions/tick (global); per-rule
  cooldown (default 60 sim-min); recursion depth ≤3; 5 ms evaluation timeout; whitelist
  **excludes** `god.set_time`, `god.spawn_object`, `god.arc_steer(abort)`.
- **Observability:** `rules_fired` metric + `rule.fired` SSE event.

---

## Authority, leases & security

### Leases (reuse of `god/coordinator.py`)

| Priority | Lease | Source | Behavior |
|---|---|---|---|
| 1 | `PLAYER_MANUAL` | player click | aborts AI on that Sim; locks autonomy |
| 2 | `SANDBOX_OVERRIDE` | "Direct Scene" | full control, opt-in |
| 3 | `GOD_CATALYST_PUPPET` | `god.puppeteer` | full control of the catalyst NPC only |
| 4 | `SOVEREIGN_AGENT` | `sim.impulse/reaction/social` **and Agency MCP** | autonomy; God applies soft influence only |
| 5 | `RULE_AUTOMATION` | `rules` engine (R6) | Soft Influence only; acts on idle Sims, honoring REQ-IMP-03 |

Boundary rules: `agency` never touches world state; `god` never overrides a
`SOVEREIGN_AGENT` queue (only the four soft channels). Conflict → `LEASE_DENIED` with
`retry_after_sim_minutes`.

**Sovereignty arbitration (PC-04).** `agency` and the internal engine (`sim.impulse`/
`sim.social`) share the `SOVEREIGN_AGENT` slot while `rules` runs on the lower
`RULE_AUTOMATION` lease. To prevent queue thrashing, the Gateway arbitrates:

- An external `agency` lease for a Sim **holds the `SOVEREIGN_AGENT` slot** and the internal
  engine skips idle impulses / social for that Sim while the external lease is live.
- `rules` actions on a Sim whose `SOVEREIGN_AGENT` slot is held are **coalesced** (a per-Sim
  action cap + cooldown) instead of firing every tick, and are limited to Soft Influence when
  the Sim is not idle (R6).
- `preempted_by_player` is reported as an outcome when `PLAYER_MANUAL` wins mid-flight.

### Session token

- Issued at `POST /v1/lifecycle/attach` (the mod already calls it on boot): payload
  `{scope, sim_id?, exp}`; stored as a **hash** in `data/mcp_token` (0600), rotated on each
  attach.
- Middleware validates `Authorization: Bearer <token>` on `/mcp/*` and derives the scope; the
  Gateway rechecks authority (never trusts the client).
- **Rate limit** per token (bucket, e.g. 10 req/s) + an SSE connection cap per facade (`503` +
  `Retry-After`).
- **Audit:** structured log per `action_id`.
- Note: since the service is loopback, the token provides **facade isolation and
  traceability**, not defense against local malicious code.

---

## Intent delivery to the mod (SSE)

Today there are two slow, asynchronous paths: the inline `POST /v1/autonomy/tick` response
(~15 sim-min) and `GET /v1/autonomy/intents` (pull, 2–10 s backoff).

**Unified transport (R2) — two threads only.** The Mod keeps the outbound worker thread and a
**single inbound delivery thread** with a state machine; the pull loop and the stream thread are
merged to eliminate the race on `_pending_intents` / `_inbound_intents_queue`.

- **Sidecar:** `GET /v1/autonomy/stream` (`EventSourceResponse`) broadcasts
  `event: intents\ndata: <json>` and sends `: keepalive` every 5 s.
- **Mod (Python 3.7, stdlib):** the inbound thread connects with `timeout=15.0` (**never**
  `timeout=None`). On 15 s of silence `socket.timeout` fires, the thread checks
  `_shutdown_event.is_set()` and either keeps reading or exits cleanly (no hung
  `TS4_x64.exe`). After **2 failed SSE connections** the same thread degrades to
  `GET /v1/autonomy/intents` (3 s→10 s) and reconnects to SSE when it recovers.
- **Closed-loop:** outcomes ride back on `POST /v1/autonomy/tick` (R1), not on a separate
  per-intent request.

```python
def _inbound_delivery_loop():
    backoff = 1.0
    sse_failures = 0
    while _worker_running and not _shutdown_event.is_set():
        try:
            req = urllib.request.Request(_base_url() + '/v1/autonomy/stream',
                                         headers={'Accept': 'text/event-stream'})
            # Short, finite timeout so shutdown is never blocked by a silent socket.
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                sse_failures = 0
                backoff = 1.0
                event, data_lines = None, []
                for raw in resp:
                    line = raw.decode('utf-8', 'replace').rstrip('\n')
                    if not line:
                        if event == 'intents' and data_lines:
                            payload = json.loads(''.join(data_lines))
                            _inbound_intents_queue.put({
                                'type': 'response',
                                'trace_id': generate_trace_id(),
                                'endpoint': '/autonomy/stream',
                                'response': payload,
                            })
                        event, data_lines = None, []
                    elif line.startswith('event:'):
                        event = line[6:].strip()
                    elif line.startswith('data:'):
                        data_lines.append(line[5:].strip())
        except Exception as e:
            worker_log_warn('intent delivery dropped: {}'.format(e))
            sse_failures += 1
            if sse_failures >= 2:
                # Degraded mode: short poll in the SAME thread until SSE recovers.
                _poll_intents_once()
            if _shutdown_event.wait(min(backoff, 10.0)):
                break
            backoff = min(backoff * 2, 10.0)
```

| Path | Frequency | Latency | Role |
|---|---|---|---|
| `/v1/autonomy/tick` (inline) | ~15 sim-min | up to 15 sim-min | autonomy batch + outcome ACK/NACK |
| `GET /v1/autonomy/intents` | 2–10 s | 2–10 s | degraded fallback (same thread) |
| `GET /v1/autonomy/stream` (SSE) | continuous, `timeout=15` | < 1 s | **primary** |

**Why not `timeout=None`:** a blocked `recv()` would pin the thread (and game shutdown) if the
Sidecar dies without a FIN/RST (PC-02).

---

## New intent kinds

Add to `schemas.INTENT_KINDS`, `mod/intent_bus.py`, and handlers in `tool_executor.py`:

| Kind | `params` | Native handler | Risk | Expiry |
|---|---|---|---|---|
| `interact` | `interaction`, `object_id?` | `CommonSimInteractionUtils.queue_interaction` / `object_manager` | Medium | `ttl` |
| `cancel` | `interaction?` | remove from `sim.queue` | Medium | `ttl` |
| `relate` | `sentiment`, `target_sim_id` | `add_relationship_bit` | Medium | `next_sleep` |

`normalize_intent` degrades unknown kinds to `command` (compatible). Tools are exposed only
**after** the mod implements the handler (Phase 0a before the facades).

---

## Observability & Web Studio

- `/v1/status` gains `mcp`: connections per facade, active tokens (no secrets), per-tool
  counters, recent `outcomes`, `rules_fired`, `deep_window_open`.
- Web Studio (Script Room) gains an **MCP panel**: facade status, `action_id`/outcome log, and
  a rules ("ifs") editor with `test_rule`.
- `trace_id` propagated end to end (already exists in the sidecar; the Gateway injects it into
  the envelope).

---

## Phases & acceptance

> Reordered per the [Architectural Review](operations.md): **close the in-game substrate first**
> (Phase 5), then build the facades. The facades are thin wrappers over the levers; exposing
> them before the levers pass the in-game checklist only standardizes access to broken calls.

### Phase 0 — Substrate prerequisites (before any facade)
- **0.1 Engine facade:** isolate all EA/S4CL imports behind `engine_facade.py` (R3).
- **0.2 Smoke test:** `sw.smoke_test` self-test (tuning loaded, active-Sim introspection,
  mirror/mailbox/diary resolution, one emotion buff apply/remove) → `Sensewright_SmokeTest.json`.
- **0.3 Closed-loop telemetry:** Mod `_completed_outcomes` → `outcomes` on `/v1/autonomy/tick`
  (+ `POST /v1/actions/outcomes` when awaited) (R1).
- **0.4 Unified transport:** 2 threads, SSE `timeout=15` + 5 s keepalive, integrated degraded
  pull (R2).
- **0.5 ContextAssembler priority packing:** P0/P1/P2 knapsack + token-boundary test (R4).
- **0.6 JSON repair:** `llm/json_repair.py` + native `response_format: json_object` (R5).
- **0.7 New intent kinds:** `interact`/`cancel`/`relate` + mod handlers (exposed only after 0.1).
- **0.8 Pre-session event buffer:** gate hydration events until `session-start` returns
  `ok: true`; hold genuine events in a max-8 buffer (R7).
- **0.9 Confidant persistence & GC:** persist `player_confidant_sim_id` in `metadata`; one-shot
  cleanup of orphan confidants (R8).
- **Acceptance:** `sw.smoke_test` green on a real save; intent → visible effect **< 1 s**;
  outcome `applied/failed/expired` round-trips; `pytest` green; `py -3.7` clean.

### Phase 1 — In-game validation (M8 / Phase 5) — **gate before facades**
- Run the `plan.md`/specification M8 checklist: save/reload, Save As, Alt+F4, zone transition,
  10-min AFK, 0-key, network timeout, long session, mirror/diary/tombstone/catalyst/mailbox/
  sleep-balloon hooks. Fix what fails here first.

### Phase 2 — Gateway + MCP + rules (sidecar)
- **Artifacts:** `POST /v1/actions` (envelope, dedup, authority, closed-loop outcome); `mcp/`
  (FastMCP ×3) mounted in `server.py`; `rules` table + `ConditionEngine`; token/scope; rate
  limit; sovereignty arbitration (PC-04).
- **Acceptance:** `tools/list` on all three facades; `rules.define_rule` persists; a rule fires
  and its action is visible; gateway/lease/rules tests.

### Phase 3 — `agency` & `god`
- **Artifacts:** the tools of both tables + GAP endpoints (`cast`, `whisper`, `subtext`,
  `rumor`, `chronicle`, `arc/plan`, `arc/advance`).
- **Acceptance:** an external script drives a Sim (speak/go/mood/interact) and directs a scene
  (cast/direct/advance arc/set weather) → visible effects with correct outcomes.

### Phase 4 — Close-out
- **Artifacts:** MCP panel in the Web Studio; docs; final M8 playtest.
- **Acceptance:** checklist filled; zero test regressions.

---

## Risks

| # | Risk | Mitigation |
|---|---|---|
| 1 | Latency without SSE | unified transport (R2) before the facades |
| 2 | New intent contract | degrade to `command`; expose only after `engine_facade.py` + handler |
| 3 | Event loop saturation (PC-03) | SSE connection cap, timeouts, rate limit; offload sync work |
| 4 | Lease/sovereignty contention (PC-04) | arbitration within `SOVEREIGN_AGENT`: external lease holds the slot, rules coalesce |
| 5 | EA/S4CL coupling (PC-02, `queue_interaction`, `object_manager`, `GameClock`) | `engine_facade.py` + `sw.smoke_test`; validate per build (Phase 1) |
| 6 | MCP divergence across clients | spec 2025-06-18; test with ≥2 clients |
| 7 | `mcp` dependency in the player's env | minimal JSON-RPC fallback behind the same contract |
| 8 | False-success telemetry (PC-01) | closed-loop outcomes (R1); never assume success after enqueue |
| 9 | Save corruption/bloat (PC-07) | idempotent creation (find-before-spawn), audit, smoke test; no orphan Sim/object |
| 10 | Context overflow / free-model JSON failures (PC-05/06) | priority packing (R4) + JSON repair (R5) |

---

## Integration map

| Point | File |
|---|---|
| Queue/contract | `sidecar/sensewright_sidecar/schemas.py`, `agent/intents.py`, `state.py` |
| Gateway/MCP (new) | `sidecar/sensewright_sidecar/mcp/{__init__,gateway,servers,registry,spec}.py` |
| Rules (new) | `sidecar/sensewright_sidecar/mcp/conditions.py` + table in `memory/sqlite_store.py` |
| Mount | `sidecar/sensewright_sidecar/server.py`, `routers/__init__.py` |
| SSE | `sidecar/sensewright_sidecar/routers/autonomy.py`, `services.py` |
| Native execution | `mod/sensewright_mod/tool_executor.py`, `native_hooks.py`, `visit_situation.py` |
| Stream/pull (mod) | `mod/sensewright_mod/http_client.py`, `main.py` |
| God | `sidecar/sensewright_sidecar/god/{orchestrator,arcs,cast,puppeteer,react,controls,coordinator}.py` |

---

## Test strategy

- **Unit (sidecar):** gateway (auth/dedup/routing), per-scope registry, ConditionEngine
  (caps/recursion), token/scope.
- **Contract:** `tools/list` on the three facades; `normalize_intent` for the new kinds;
  envelope JSON Schema.
- **Integration:** `TestClient` calling `/mcp/*` and `/v1/actions` → verify the intent is
  queued and the outcome reported.
- **Mod (static):** `py -3.7 -m py_compile`; `test_mod_game_imports.py` (no non-existent
  `sims4.<submodule>` imports).
- **In-game (Phase 5):** SSE < 1 s; `interact`/`relate`; weather; cast/puppeteer; a user rule.

---

## Glossary

- **Action Gateway:** the single translator from MCP tools to intents/state.
- **Tool registry:** the typed catalog per facade (scope, kind, schema).
- **Outcome:** the result of an action (`applied|failed|expired`) returned to the caller.
- **Lease:** the right to control a Sim (player > catalyst > agent).
- **"Ifs":** author rules (`rules`) evaluated deterministically.
- **SSE push:** the sidecar→mod channel for reactive delivery.
