# Sensewright v2 — Documentation

Central documentation hub. The repository [`README.md`](../README.md) is the entry point;
everything below is the detailed reference.

## Start here

| Document | What it covers |
|----------|----------------|
| [`getting-started.md`](getting-started.md) | Install, configure, run and build: prerequisites, mod install, sidecar setup, autoboot, troubleshooting, uninstall, Make/PowerShell targets, test cycle, decompile. |
| [`architecture.md`](architecture.md) | How the system works: dual-process boundary, dual clocks, Shadow DB, IntentBus, LLM layer, i18n engine, God Director, World Layer, REST reference, invariants. |

## Reference

| Document | What it covers |
|----------|----------------|
| [`reference.md`](reference.md) | The canonical catalog of the 33 purposes (tier, trigger, artifact, consumer) and the localization engine / translation contribution guide. |
| [`specification.md`](specification.md) | The complete v2 technical specification: milestones M0–M8, features F01–F22, adjustments A1–A11, complementary features FC1–FC5, acceptance criteria. |

## Design & planning

| Document | What it covers |
|----------|----------------|
| [`mcp.md`](mcp.md) | MCP layer (design + plan): root cause, protocol/transport (official `mcp` SDK, Streamable HTTP), Action Gateway, the three facades (`agency`/`god`/`rules`), tool schemas, SSE push, rules DSL, phases, risks. |
| [`spike-strategy.md`](spike-strategy.md) | Spike-Driven Development strategy (Data Probes) to map the EA API reality before integrating native features. |
| [`project-status.md`](project-status.md) | Where the project stands and what remains: spec↔code gap per milestone/feature/purpose, the gap-closing plan, and the reverse-chronological changelog. |

## Quality & operations

| Document | What it covers |
|----------|----------------|
| [`operations.md`](operations.md) | Quality & operations: the **architectural review & evolution plan**, the concurrency/thread-safety hardening plan, the bugs found in deploy/playtest, and the weak-point remediation wave. |

## Conventions

- **Language:** English is the canonical documentation language.
- **Architecture decisions** and cross-process contracts live in
  [`architecture.md`](architecture.md); implementation gaps and history in
  [`project-status.md`](project-status.md); forward-looking design in [`mcp.md`](mcp.md).
- **Single roadmap:** the execution order lives only in
  [`operations.md` → Recommended execution order](operations.md#recommended-execution-order-2026-10-05);
  the Gap-Closing Plan in `project-status.md` is a catalog of items, not a sequence.

## Repository layout

| Path | Contents |
|------|----------|
| `mod/` | The Sims 4 mod side — Python 3.7 (`sensewright_mod/`), tuning XML (`tuning/`), build scripts. |
| `sidecar/` | FastAPI sidecar — Python 3.10+ (`sensewright_sidecar/`), config, locales, tests. |
| `docs/` | This documentation hub. |
| `scripts/` | PowerShell helpers (build, install, doctor, decompile). |
| `tools/` | Auxiliary tooling (DBPF, bias-buff generation, bias map). |
| `research/` | Third-party reference clones (S4CL, Lot 51 Core) — not redistributed. |
