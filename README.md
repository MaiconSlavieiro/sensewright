# Sensewright

> **English** · [Português (Brasil)](README.pt-BR.md)

**Sensewright** gives *The Sims 4* Sims an **LLM agency** layer and a **"God agent"**
that orchestrates the world. Agents don't *puppet* the Sim: they emit **intents**
(nudges) that are translated into the game's native levers, and the player stays in
control.

> Formerly **SimsSense**. Cheats are `sw.*`, the artifact is `Sensewright.ts4script`,
> and the install folder is `Mods\Sensewright\`. Old names (`ss.*`, SimsSense) are gone.

## Status

| | |
|---|---|
| In-game build | `2026-09-29.26` (`mod/sensewright_mod/main.py` → `_BUILD`) |
| Branch | `main` |
| Tests | sidecar **546** · mod **412** · `ruff` clean · `py -3.7 mod/build.py` ok |
| Stack migration | **S4CL + Lot 51 Core**: offline-complete, in-game validation **pending** |

## How it works

Two strictly isolated processes:

| Layer | Package | Runtime | Dependencies |
|---|---|---|---|
| **In-game mod** | `mod/sensewright_mod/` | Python **3.7** | stdlib + **S4CL** + **Lot 51 Core** (via `integrations.py`) |
| **Sidecar** | `sidecar/sensewright_sidecar/` | Python **3.12+** | FastAPI, Pydantic v2, httpx, SQLite |

The mod **never** imports third-party libraries outside the *stack seam*
(`integrations.py`); the sidecar **never** imports game modules. They talk over HTTP
at `127.0.0.1:8765` (`/v1/*` routes), with the wire contract modeled in
`sidecar/sensewright_sidecar/schemas.py`.

Besides the per-Sim agent, a **God agent** intervenes in the neighborhood (story
presets, backgrounds, zeitgeist) and a **panel** (web and in-game) exposes the
controls.

## Requirements

- The Sims 4 and **Python 3.7** (to build the `.ts4script`) + **Python 3.12+** (sidecar).
- **S4CL** (`sims4communitylib*.ts4script`) and **Lot 51 Core** (`lot51_core*.ts4script`)
  at the **root** of `Mods` — the libraries are **not** redistributed (XmlInjector is no longer used).
- An LLM provider key (OpenRouter `:free`, OpenCode Zen, or Gemini).

## Installation

```powershell
# 1. sidecar dependencies
make install            # or: cd sidecar; uv sync --extra dev

# 2. build the artifacts (Sensewright.ts4script + Sensewright.package)
py -3.7 mod\build.py

# 3. install the mod + sidecar into Mods\Sensewright\
powershell -ExecutionPolicy Bypass -File scripts\install-mod.ps1

# 4. launch the game (script mods only load at boot)
```

The sidecar **starts by itself** with the game (the mod auto-boots it) and **exits
with it**. A web panel is available at <http://127.0.0.1:8765/> to watch the sidecar
alongside the game, and the in-game native panel opens with `sw.panel`. Reinstall
after any venv or code change.

## `sw.*` cheats

| Command | Action |
|---|---|
| `sw.help` | help for all commands |
| `sw.status` | sidecar status + provider health |
| `sw.start` | start the sidecar manually |
| `sw.chat <text>` | talk to the selected Sim |
| `sw.hey` | trigger a spontaneous greeting from the Sim |
| `sw.profile <1 sentence>` | generate the Sim's profile (1 sentence → JSON) |
| `sw.autonomy off\|observe\|suggest\|semi\|full` | the Sim's autonomy level |
| `sw.agents [<seats> \| <sim_id> <freq>]` | agent roster + impulse dial |
| `sw.god [on\|off\|tick\|scan\|preset <name>\|set <k> <v>]` | God control |
| `sw.zeitgeist <tags_csv\|auto\|empty>` | set the neighborhood zeitgeist |
| `sw.evolve [save]` | run the reflection/evolution loop |
| `sw.reset session\|sim\|save\|all` | clear session/memory |
| `sw.forget sim\|save\|all` | erase memory |
| `sw.panel` | open the in-game configuration panel |
| `sw.hud on\|off\|now\|status` | loop debug HUD |
| `sw.probe` | dump the autonomy surface (dev) |
| `sw.lang auto\|<locale>` | UI language (persists to config) |

## Configuration

All configuration lives in `config.toml` — the file's source of truth is
**`config.example.toml`**. With **no keys at all**, the mod already runs in "native
mode". Blocks: `[ui]`, `[network]`, `[logging]`, `[llm]`, `[memory]`, `[agents]`,
`[runtime]`, `[god]`.

The settings exposed to the panel are the **ControlSpec** (`god/controls.py`); panel
overrides are written to `data/panel.toml` without touching `config.toml`. Two
locales ship: `en` (default) and `pt-BR`; adding a language is JSON + manifest, no
code change.

## Documentation

The **single source of truth** is
**[`docs/feature-review.html`](docs/feature-review.html)** (open it in a browser). It
follows the Diátaxis split, with each topic in exactly one place:

| Tab | Purpose |
|---|---|
| **Início** | overview, status and quick start |
| **Arquitetura** | the two processes, module map, wire protocol, S4CL/Lot51 base |
| **Desenvolvimento** | loop, conventions, constraints, recipes and gotchas |
| **Validação** | logs/DB, live checklist and how to prove each feature |
| **Referência** | config, `sw.*` cheats, endpoints, locales, providers |
| **Internals TS4** | confirmed game APIs (autonomy, buffs, alarms, genealogy) |
| **Roadmap** | phases, v0.2/v0.3, open items and risks |
| **Changelog** | history per build |
| **Review** | interactive per-feature checklist (exports JSON) |

The day-to-day coding rules are in
`.agents/skills/sensewright_development/SKILL.md`.

## Development

```powershell
# tests
cd sidecar; .\.venv\Scripts\python.exe -m pytest tests -q   # sidecar — 546
python -m pytest mod\tests -q                               # mod — 412

# build + install
py -3.7 mod\build.py
powershell -ExecutionPolicy Bypass -File scripts\install-mod.ps1
```

Other helpers: `make doctor` / `scripts\doctor.ps1` (validate the environment),
`make status` (sidecar health) and `make dev` (development helper).

## License

MIT — see [`LICENSE`](LICENSE). Runtime dependencies (S4CL, Lot 51 Core) and adapted
code (SimAI) are credited in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
