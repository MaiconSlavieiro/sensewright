# Sensewright v2

**The Sims 4 AI Companion & World Director** — A dual-process mod that gives every Sim an inner life: dreams, memories, evolving personality, and a hidden digital confidant you can text. A God Director shapes the neighborhood through soft influence and catalyst NPCs, all without mandatory API costs.

> **Documentation hub:** [`docs/`](docs/README.md)

---

## What It Does

- **Hidden Digital Confidant**: A native `SimInfo` in a hidden household appears in the Relationships panel. Chat via Phone (SMS) or Computer (Chat/Email). Conversations raise Social/Fun needs, generate native Wants, and produce native Sentiments (Adoration, Hurt, Grudge, etc.).
- **Autonomous Inner Life**: Each seated Sim runs `sim.impulse` (idle thoughts), `sim.reaction` (to salient events), `sim.dream` (nightly surrealism feeding next-day urges), `sim.cognition` (daily plan biased by dreams and duties), `evo.reflect` (demeanor shifts), and `evo.trait` (native Likes/Dislikes updates, trait-swap proposals).
- **Memory & Narrative**: SQLite + FTS5 (BM25) memory store with gradual decay, consolidation, compaction, and legacy memories immune to pruning. Shadow DB (working/committed/ring-buffer) syncs transactionally with TS4 saves.
- **God Director**: Creates narrative arcs, manages Zeitgeist, whispers into dreams (soft influence), and puppeteers catalyst NPCs (`god.puppeteer`) who visit lots, ring doorbells, and provoke genuine reactions from your sovereign Sims. Three modes: `AUTONOMOUS`, `CO_DIRECTOR`, `SANDBOX`.
- **Dual UI**: In-game **Quick Menu** (pie menu on any Sim + Shift-click panel) and browser-based **Web Studio** (`/ui`) for Inspector, Script, and Setup panels.
- **Zero-Key Operation**: All 33 purposes have deterministic localized fallbacks. The mod works fully without any API key.

---

## Architecture at a Glance

```
┌─ The Sims 4 (Game Process — Python 3.7) ──────────────────────┐     ┌─ Sidecar (FastAPI — Python 3.10+/3.12+) ──────────────┐
│ Main Thread (GAME_TICK via Lot 51 Core):                      │     │  Routers: lifecycle / chat / autonomy / god / memory    │
│  ├─ state_collector  (pulse deltas, census, events)           │     │  LLMScheduler   → single queue, tiers, SLOs, deep win │
│  ├─ tool_executor    (GameLever, ArchetypeResolver)           │     │  ContextAssembler → profile slicing, TPM ceiling      │
│  ├─ native_hooks     (Hidden SimInfo, Diary, Sentiments)      │     │  ModelRouter    → purpose → RoutePlan                 │
│  ├─ ui_manager       (4 visual channels, chained chat)        │     │  ProviderChain  → RPM/RPD/TPM, circuit breaker, swap  │
│  └─ RAM queues       (outbound_q / inbound_intents_q)         │     │  SaveVault      → Working DB ↔ Committed DB + FTS5    │
│         │▲ (lock-free, < 0.1 ms)                              │     │  Web Studio     → Inspector SPA, Script, Setup        │
│ Worker Thread (daemon, urllib.request):                       │ HTTP│                                                         │
│  └─ HTTP I/O ─────────────────────────────────────────────────┼────▶│                                                         │
└────────────────────────────────────────────────────────────────┘     └─────────────────────────────────────────────────────────┘
```

**Key architectural rules:** thread isolation (main thread only enqueues/drains RAM queues), Python 3.7 constraints in the Mod, and a dual-clock system (wall-clock for infrastructure, sim-clock for gameplay; intent dispatch freezes while the game is paused). Full details in [`docs/architecture.md`](docs/architecture.md).

---

## Requirements

| Component | Version | Notes |
|-----------|---------|-------|
| The Sims 4 | 1.90+ (current patch) | Base game only; no DLC required |
| S4CL (Sims 4 Community Library) | Latest release | Required dependency — install separately |
| Lot 51 Core Library | Latest release | Required dependency — install separately |
| Python (sidecar) | 3.10+ (3.12 recommended) | Sidecar runs on 3.10+; 3.12+ preferred for performance |
| Python (mod build) | 3.7.9 exactly | `.ts4script` must be compiled with Python 3.7 bytecode |

---

## Quick Start

1. Install **S4CL** and **Lot 51 Core** into your TS4 `Mods/` folder and enable **Script Mods Allowed** (Game Options → Other).
2. Build and install Sensewright: `make all && make install` (or `.\scripts\dev.ps1 build` then `.\scripts\dev.ps1 install`).
3. Configure and run the sidecar: `cd sidecar && cp config.example.toml config.toml && python main.py`.
4. Launch The Sims 4 and load a save. Click any Sim → **Sensewright** → **Chat (Phone)** or **Chat (PC)**.
5. Open `http://127.0.0.1:8765/ui` for the Web Studio.

The mod can auto-start the sidecar: create `sidecar/python.txt` containing the full path to a Python 3.10+ executable. With no provider enabled, every purpose answers with a deterministic localized fallback (fully offline).

Full step-by-step instructions: [`docs/install.md`](docs/install.md).

---

## Documentation

| Document | Contents |
|----------|----------|
| [`docs/install.md`](docs/install.md) | Installation, configuration, autoboot, troubleshooting, uninstall |
| [`docs/architecture.md`](docs/architecture.md) | Dual-process architecture, Shadow DB, LLM layer, i18n, God Director, World Layer, REST reference |
| [`docs/purposes.md`](docs/purposes.md) | Canonical catalog of the 33 purposes (tier, trigger, artifact, consumer) |
| [`docs/i18n.md`](docs/i18n.md) | Localization engine and translation contribution guide |
| [`docs/development.md`](docs/development.md) | Build system, Make targets, PowerShell scripts, test cycle |
| [`docs/requirements.md`](docs/requirements.md) | Full v2 specification (milestones, features, acceptance criteria) |
| [`docs/status.md`](docs/status.md) | Implementation status and known gaps |
| [`docs/plan.md`](docs/plan.md) | Plan to close all remaining gaps |

---

## License

**Sensewright v2** — MIT License (see [`LICENSE`](LICENSE)). Third-party dependency licenses
are listed in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md). S4CL and Lot 51 Core are
**runtime dependencies** installed separately by the player; they are included under
`research/` only as development reference and are not redistributed.
