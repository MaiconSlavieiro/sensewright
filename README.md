# Sensewright v2

**The Sims 4 AI Companion & World Director** — A dual-process mod that gives every Sim an inner life: dreams, memories, evolving personality, and a hidden digital confidant you can text. A God Director shapes the neighborhood through soft influence and catalyst NPCs, all without mandatory API costs.

---

## What It Does

- **Hidden Digital Confidant**: A native `SimInfo` in a hidden household appears in the Relationships panel. Chat via Phone (SMS) or Computer (Chat/Email). Conversations raise Social/Fun needs, generate native Wants, and produce native Sentiments (Adoration, Hurt, Grudge, etc.).
- **Autonomous Inner Life**: Each seated Sim runs `sim.impulse` (idle thoughts), `sim.reaction` (to salient events), `sim.dream` (nightly surrealism feeding next-day urges), `sim.cognition` (daily plan biased by dreams and duties), and `sim.evolve` (demeanor shifts, native Likes/Dislikes updates, trait-swap proposals).
- **Memory & Narrative**: SQLite + FTS5 (BM25) memory store with gradual decay, consolidation, compaction, and legacy memories immune to pruning. Shadow DB (working/committed/ring-buffer) syncs transactionally with TS4 saves.
- **God Director**: Creates narrative arcs, manages Zeitgeist, whispers into dreams (soft influence), and puppeteers catalyst NPCs (`god.puppeteer`) who visit lots, ring doorbells, and provoke genuine reactions from your sovereign Sims. Three modes: `AUTONOMOUS`, `CO_DIRECTOR`, `SANDBOX`.
- **Dual UI**: In-game **Quick Menu** (pie menu on any Sim + Shift-click panel) and browser-based **Web Studio** (`/ui`) for Inspector, Script, and Setup panels.
- **Zero-Key Operation**: All 33 purposes have deterministic localized fallbacks. The mod works fully without any API key.

---

## Dual-Process Architecture

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

**Key Architectural Rules**
- **Thread Isolation**: Main thread only enqueues to `outbound_q` and drains `inbound_intents_q`. All HTTP I/O runs in a single daemon worker thread.
- **Python 3.7 Constraints**: No walrus (`:=`), no `match/case`, no union types, no `from __future__ import annotations`, no third-party deps beyond S4CL and Lot 51 Core.
- **Dual Clocks**: Wall-clock (real seconds) for HTTP timeouts, rate limits, SLOs. Sim-clock (`world_sim_tick`, sim-minutes) for all gameplay: intent delays, social cooldowns, memory decay, dream schedules. When `clock_speed == 0` (pause), intent dispatch freezes.

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

## Installation

### 1. Install Dependencies (Mods Folder)
Download and place in `Documents/Electronic Arts/The Sims 4/Mods/`:
- **S4CL** — from [GitHub Releases](https://github.com/DeviantGameMods/Sims4CommunityLibrary/releases)
- **Lot 51 Core** — from [GitHub Releases](https://github.com/lot51/lot51_core/releases)

Enable **Script Mods Allowed** in Game Options → Other.

### 2. Build & Install Sensewright
```bash
# From repo root (requires Python 3.7 on PATH as `py -3.7` and Python 3.10+ as `python`)
make all          # builds .ts4script + .package
make install      # copies both to your Mods folder
```

Or use the PowerShell helper:
```powershell
.\scripts\dev.ps1 build
.\scripts\dev.ps1 install
```

### 3. Configure & Run Sidecar
```bash
cd sidecar
cp config.example.toml config.toml
# Edit config.toml — at minimum set API keys if you want LLM features
python main.py
```
The sidecar serves:
- REST API at `http://127.0.0.1:8765/v1/...`
- Web Studio at `http://127.0.0.1:8765/ui`

**Autoboot**: The mod's worker thread will auto-start the sidecar if it detects `sidecar/python.txt` pointing to a Python 3.10+ executable. Create that file in `sidecar/python.txt` with the full path (e.g., `C:\Python312\python.exe`) to enable zero-click startup.

**0-Key Fallback**: If no provider is enabled or all keys are empty, every purpose returns a deterministic localized fallback. The mod is fully playable offline.

---

## Quick Start

1. Launch The Sims 4, load a save.
2. The mod initializes on `HOUSEHOLDS_AND_SIMS_LOADED`: creates the Hidden Confidant Sim, sends census, starts autonomy pulses.
3. Click any Sim → **Sensewright** pie menu → **Chat (Phone)** or **Chat (PC)**.
4. Type a message. The Sim replies in a notification with a **[Responder Agora]** button — click to continue the conversation without re-opening the pie menu.
5. Open `http://127.0.0.1:8765/ui` in a browser for the Web Studio (Inspector, Script, Setup).

---

## Configuration (Two-Layer `config.toml`)

**Layer 1 — Providers & Technical Limits** (`[llm.providers.*]`)
```toml
[llm.providers.openrouter]
enabled = true
base_url = "https://openrouter.ai/api/v1"
api_key = "sk-..."
models = ["openai/gpt-4o-mini", "meta-llama/llama-3.1-8b-instruct:free"]
rpm = 20        # requests/minute
rpd = 200       # requests/day
tpm = 40000     # tokens/minute
```
Supported providers: `openrouter`, `gemini`, `groq`, `deepseek`, `ollama`. Set `free_only = true` to block paid models client-side.

**Layer 2 — Routing & Budgets** (`[llm.routes.*]`, `[llm.tiers.*]`)
```toml
[llm.routes.default]
provider = "openrouter"
model = "openai/gpt-4o-mini"

[llm.tiers.interactive]
slo_seconds = 3.0
max_input_tokens = 1500
max_output_tokens = 250
concurrency = 4

[llm.tiers.realtime]
slo_seconds = 12.0
max_input_tokens = 700
max_output_tokens = 220
concurrency = 2
thinking_budget = 0

[llm.tiers.bg]
slo_seconds = 60.0
max_input_tokens = 1500
max_output_tokens = 400
concurrency = 1

[llm.tiers.deep]
slo_seconds = 300.0
max_input_tokens = 4000
max_output_tokens = 600
concurrency = 1
```

**Gameplay Tunables** (`[gameplay]`, `[god]`) — editable in-game via Quick Menu / Web Studio:
```toml
[gameplay]
agent_seats = 12
lease_min_sim_minutes = 60
hearing_radius_m = 20.0
max_lines_per_minute = 12
min_interval_between_lines_seconds = 30
player_lock_seconds = 15

[god]
director_mode = "AUTONOMOUS"   # AUTONOMOUS | CO_DIRECTOR | SANDBOX
preset = "novela"              # novela|sitcom|drama|caos|terror|romance|filme_adolescente
intervention_frequency = 0.5
intensity = 0.5
mood_influence = 0.5
autonomy_degree = 0.5
chaos_degree = 0.5
```

---

## Web Studio (`/ui`) & Quick Menu

| UI | Access | Purpose |
|----|--------|---------|
| **Quick Menu (Pie)** | Click any Sim → Sensewright | Chat (Phone/PC), Provoke, Panel, Director controls |
| **Quick Menu (Shift+Click)** | Shift+Click any Sim → Sensewright | Advanced: Profile, Memory, Seat, God controls |
| **Web Studio — Inspector** | `http://127.0.0.1:8765/ui` → Inspector | Live sim state, intent bus, memory, psyche, relationships |
| **Web Studio — Script** | `http://127.0.0.1:8765/ui` → Script | Manual purpose invocation, prompt preview, trace viewer |
| **Web Studio — Setup** | `http://127.0.0.1:8765/ui` → Setup | Config editor, provider status, locale manager, STBL compiler |

---

## The 33 Purposes (Canonical Catalog)

Each purpose has a stable ID, tier (driving SLO + token budget + concurrency), input/output token budgets, trigger, SQLite artifact, and in-game consumer. All have 0-key fallbacks.

### Domain: `sim` (13)
| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `sim.chat` | interactive | Phone / PC (`sw.chat`) | memory thought + speech + intents | Chat card + Hidden SimInfo |
| `sim.profile` | bg / interactive | New seat (bg) / chat (int) | `sims.profile` (PROFILE_SHAPE) | All sim prompts + GetToKnow |
| `sim.impulse` | realtime | Zone pulse (full tier) | memory thought + 1 non-verbal intent | Sim mood/action on lot |
| `sim.reaction` | realtime | Event salience ≥ 1.5 | memory thought + speak intent | Immediate reaction to causer |
| `sim.social` | realtime | Pair in conversation (pre-flight ok) | `{a_line, b_line, topic, impact}` | Compact dialogue card |
| `sim.social.close` | bg | End of ConversationSession | social memory + rumor contagion | Social history + world.gossip |
| `sim.dream` | deep | Start of sleep (1×/night) | dream memory + dream_urge | Sleep balloons + morning moodlet tooltip |
| `sim.cognition` | deep | Post-dream / bootstrap | `profile.daily_plan` + biases | Commodity buffs + Web Studio |
| `sim.sleep` | deep | Sleep (if salient event) | `profile.psyche_blocks` | Sim prompts + evo.trait trigger |
| `sim.diary` | bg | Write diary / end of day | diary memory (1st person) | Diary tooltip + Snoop |
| `sim.lifestory` | deep | Every 7 sim days / mem.legacy | `profile.life_story` | ContextAssembler + physical book |
| `sim.aspiration` | deep | Aspiration change/milestone | `profile.ambition` | Mid-term goals in cognition |
| `sim.background.expand` | bg | 1× for family/close friends | 3 backstory memories | Revealed via GetToKnow |

### Domain: `god` (8)
| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `god.zeitgeist` | bg | Onboarding / panel edit | `neighborhoods.zeitgeist` | Dreams, weather, god.plan |
| `god.plan` | deep | No arc / end of arc | `arcs` (beats + god_whisper_hint) | god.scene + dream whispers |
| `god.cast` | bg | Beat needs catalyst NPC | `arcs.cast` (NpcSheet) | spawn_npc lever (VisitSituation) |
| `god.scene` | bg | Beat enters armed | `beat.scene_draft` + scene_subtext | Prep catalyst objective for P18 |
| `god.puppeteer` | realtime | Catalyst NPC + target on lot | lease + approach + objective | Controls catalyst + subtext |
| `god.react` | realtime | End of beat interaction | branched next beat (pivot) | Adapt arc to agent's choice |
| `god.narration` | realtime | Beat start / intervention | 1 atmospheric line (≤80 tok) | SPECIAL_MOMENT banner |
| `god.background` | bg | BackgroundScheduler queue | `sims.background` | Scene context + chronicles |

### Domain: `world` (4)
| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `world.npc.backstory` | bg | Recurring townie without story | `sims.background` (NPC) | Seed for profile + god.cast |
| `world.household.chronicle` | bg | End of in-game day | `neighborhoods.chronicles` | Mailbox + ops.recap + god.plan |
| `world.gossip` | bg | Public salient event / snoop | RumorNode in neighborhoods | Social dialogues + phone SMS |
| `world.aftermath` | bg | Post-climax (salience ≥ 2.0) | durable intents + zeitgeist shift | Alters relations and weather |

### Domain: `mem` (4)
| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `mem.consolidate` | bg | 300s chat silence / zone change | consolidated memory + player_facts | FTS5 index + player bond |
| `mem.compact` | deep | ≥ 20 consolidated memories | compact memory (archive 15) | Keeps context window lean |
| `mem.legacy` | deep | Death, marriage, birth | legacy memory (immune to decay) | sim.lifestory + epitaph |
| `mem.relationship.review` | deep | Deep window (active edges) | `relationships.qualitative_note` | Native sentiments + chat/social |

### Domain: `evo` (2)
| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `evo.reflect` | deep | Sleep (≥8 ev) / mirror | updates `current_demeanor` | Phase shift preserving `core_personality` |
| `evo.trait` | deep | Trauma/belief > 0.85 / habit | likes/dislikes / trait swap | trait_tracker + Accept banner |

### Domain: `ops` (2)
| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `ops.recap` | bg | `lifecycle/session-start` | `{headline, recap_text}` | "Previously on..." banner |
| `ops.panel.summary` | bg | State change / panel open | 2-line diagnostic summary | Quick Menu header + Web Studio |

---

## Localization & Translation Contribution

Sensewright uses a **manifest-driven, zero-hardcode i18n engine** with a 4-layer cascade:

```
User Overlay (data/locales/) → Active Locale (sidecar/locales/) → Base Subtag (e.g., pt) → Manifest Default (en-US)
```

### File Topology
```
PlaintextMods/Sensewright/
├── Sensewright.ts4script          # Embedded fallback locales/
├── Sensewright.package            # Compiled STBLs from locales/stbl/
├── data/
│   └── locales/                   # [LAYER 1 — USER/COMMUNITY OVERLAY]
│       ├── manifest.override.json # Optional: register new languages
│       ├── ui/                    # Drop-in: <locale>.json (overrides Mod UI)
│       └── content/               # Drop-in: <locale>.json (overrides Prompts/Fallbacks)
└── sidecar/
    └── locales/                   # [LAYER 2 — OFFICIAL BUNDLE]
        ├── manifest.json          # Single source of truth
        ├── ui/
        │   ├── en-US.json
        │   └── pt-BR.json
        └── content/
            ├── en-US.json
            └── pt-BR.json
```

### Manifest Contract (`manifest.json`)
```json
{
  "schema_version": 2,
  "default_locale": "en-US",
  "locales": [
    {
      "code": "en-US",
      "base_subtag": "en",
      "display_name": "English (US)",
      "llm_language_name": "English",
      "ts4_stbl_byte": "0x00",
      "ts4_client_tokens": ["eng_us", "en_us", "en-us", "en"],
      "direction": "ltr"
    },
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

### Contributing a Translation
1. Fork the repo.
2. Add `<new-locale>.json` under `sidecar/locales/ui/` and `sidecar/locales/content/`.
3. Add the locale entry to `manifest.json` (copy an existing entry, adjust `code`, `base_subtag`, `ts4_stbl_byte`, `ts4_client_tokens`, `llm_language_name`).
4. Run `make package` to compile STBLs into `.package`.
5. Submit PR.

### Gender Inflection & List Rotation
- **Gender macro**: `{g:masculine|feminine|neutral}` in any string. At runtime, the engine picks the correct form based on the Sim's gender (`M`/`F`/`N`).
- **List rotation**: Any string value can be a `list[str]`. The engine picks one deterministically via `hash(seed + key) % len(list)`. Seed defaults to `sim_id:sim_hour`.

---

## Build & Development

### Make Targets
```bash
make all        # mod + package (default)
make mod        # .ts4script only (requires py -3.7)
make package    # .package only (requires Python 3.10+)
make test       # syntax check (3.7 for mod, 3.10 for build scripts)
make install    # copy artifacts to Mods folder
make doctor     # run diagnostics (scripts/doctor.ps1)
make clean      # remove dist/ and __pycache__
make sidecar    # run sidecar dev server
make dev        # interactive helper (build/test/clean/sidecar/install/doctor/decompile)
make decompile  # decompile TS4 scripts for reference (needs unpyc3)
```

### PowerShell Scripts
| Script | Purpose |
|--------|---------|
| `scripts/dev.ps1 build` | Build both artifacts |
| `scripts/dev.ps1 test` | Syntax verification |
| `scripts/dev.ps1 clean` | Clean artifacts |
| `scripts/dev.ps1 sidecar` | Run sidecar |
| `scripts/dev.ps1 install` | Install to Mods |
| `scripts/dev.ps1 doctor` | Diagnostics |
| `scripts/dev.ps1 decompile` | Decompile TS4 scripts |
| `scripts/install-mod.ps1` | Direct install |
| `scripts/doctor.ps1` | Full environment check |

### Build Details
- **`.ts4script`**: Compiled with Python 3.7 (`py -3.7 -m py_compile`). Verifies magic number `42 0d 0d 0a`. Includes `locales/` JSON files.
- **`.package`**: DBPF with XML tuning + manifest-driven STBL compilation. Reads `manifest.json`, iterates locales, converts `ts4_stbl_byte` to Resource Key, compiles FNV-1 hashed keys. Emits `stbl_keys.json` mapping.

---

## Troubleshooting

### `make doctor` / `.\scripts\doctor.ps1`
Checks:
- Python 3.7 (`py -3.7`) and 3.10+ (`python`) availability
- All mod source files present
- Locale JSON validity + key parity (en-US vs pt-BR)
- Tuning XML present + generated `dist/stbl_keys.json` and `dist/tuning_ids.json`
- Build artifacts (`.ts4script`, `.package`) exist and are valid ZIP/DBPF
- Sidecar directory + `python.txt` + `main.py`
- TS4 Mods folder + installed artifacts

### Common Issues
| Symptom | Cause | Fix |
|---------|-------|-----|
| Mod doesn't load | Script Mods disabled | Game Options → Other → ✅ Script Mods Allowed |
| Sidecar won't start | `python.txt` missing/wrong | Create `sidecar/python.txt` with full path to Python 3.10+ |
| No STBL strings in-game | `.package` not installed / outdated | `make package && make install` |
| Chat shows `[missing:key]` | Locale file missing key | Check `data/locales/ui/<lang>.json` overlay or sidecar bundle |
| Autonomy pulses not firing | Lot 51 Core not loaded | Install Lot 51 Core; check `doctor.ps1` |
| `py -3.7` not found | Python 3.7 not installed | Install Python 3.7.9 from python.org; ensure `py` launcher works |

### Logs
- **Mod logs**: `Documents/Electronic Arts/The Sims 4/mod_data/Sensewright.log` (via S4CL CommonLogUtils)
- **Sidecar logs**: Console output (configured by `log_level` in `config.toml`)
- **Trace IDs**: Every request carries `X-Trace-Id` header; appears in both mod and sidecar logs for correlation.

---

## License

**Sensewright v2** — MIT License (see `LICENSE`)

### Third-Party Notices
| Component | License | Source |
|-----------|---------|--------|
| The Sims 4 Community Library (S4CL) | **CC BY 4.0** | `research/s4cl/` (reference only) |
| Lot 51 Core Library | **MIT** | `research/lot51_core/` (reference only) |
| FastAPI | MIT | `sidecar/requirements.txt` |
| Uvicorn | BSD-3-Clause | `sidecar/requirements.txt` |
| Pydantic | MIT | `sidecar/requirements.txt` |
| Tomli | MIT | `sidecar/requirements.txt` |
| HTTPX | MIT | `sidecar/requirements.txt` |
| Pytest | MIT | `sidecar/requirements.txt` |

> **Note**: S4CL and Lot 51 Core are **runtime dependencies** — players must install them separately. They are included under `research/` only as reference for development. Sensewright does not bundle or redistribute them.

---

## Implementation Status & Known Gaps

> **Full, per-purpose status matrix:** [`docs/status.md`](docs/status.md) tracks the gap
> between the spec and the code (milestones M0–M8, features F01–F22, all 33 purposes,
> adjustments A1–A11, and complementary features FC1–FC5).

Highlights as of 2026-10-02 (474 sidecar tests passing; both build artifacts validated):

- **Implemented and wired:** dual-process IPC, Shadow DB (working/committed/ring buffer),
  FTS5 memory, i18n engine (4-layer cascade + gender + rotation), LLM layer (RPM/RPD/TPM,
  circuit breaker, scheduler, tiered ContextAssembler), Hidden Confidant chat (SMS), seat
  manager, presence capabilities, IntentBus, God Zeitgeist/Narration, Quick Menu, Web
  Studio SPA, and the build pipeline.
- **Partial (engine present, wiring/trigger missing):** `sim.dream`, `sim.cognition`,
  `evo.reflect`, `evo.trait`, `god.plan`, `god.puppeteer`, `mem.consolidate`, `ops.recap`,
  speech-policy rate limits, tier concurrency, per-model cooldown, Web Studio persistence.
- **Fallback-only (no production trigger yet):** 18 purposes including `sim.social.close`,
  `sim.sleep`, `sim.diary`, `sim.lifestory`, `sim.aspiration`, the remaining `world.*`
  and `mem.*` purposes, and `ops.panel.summary`.
- **Native hooks still pending (M5/M6):** `VisitSituation`, Diary/"Snoop", Autobiography
  Book, `sim_GetToKnow` secret reveal, epitaph, sleep balloons, custom Mirror interaction.
- **Not yet done:** in-game M8 acceptance tests (zone transition, Save As, Alt+F4
  rollback, invisible autoboot), `/v1/i18n/compile-addon`, VACUUM (A9), EP guards (A10),
  Panic Button (FC4).
- The exact DBPF tuning group/type emitted by `build_package.py` still needs in-game
  validation. S4CL license confirmed as CC BY 4.0; Lot 51 Core as MIT.