# Sensewright v2 — Documentation

Central documentation hub. All project documentation lives in this folder. The
[`README.md`](../README.md) at the repository root is the entry point; everything
below is the detailed reference (English).

| Document | What it covers |
|----------|----------------|
| [`requirements.md`](requirements.md) | Full v2 specification: milestones M0–M8, features F01–F22, purposes, adjustments A1–A11, complementary features FC1–FC5, acceptance criteria. |
| [`architecture.md`](architecture.md) | Detailed architecture: dual-process boundary, dual clocks, Shadow DB, IntentBus, LLM layer, i18n engine, God Director, World Layer, REST reference. |
| [`install.md`](install.md) | Installation guide: prerequisites, build, mod install, sidecar config, autoboot, verification, troubleshooting, uninstall. |
| [`purposes.md`](purposes.md) | Canonical catalog of the 33 purposes (tier, trigger, artifact, in-game consumer). |
| [`i18n.md`](i18n.md) | Localization engine: 4-layer cascade, manifest contract, file topology, and how to contribute a translation. |
| [`development.md`](development.md) | Build system (Make targets, PowerShell scripts), build details, and test cycle. |
| [`status.md`](status.md) | Implementation status: gap between spec and code, per milestone / feature / purpose. |
| [`plan.md`](plan.md) | Execution plan to close all remaining gaps (phases, dependencies, risks, in-game checklist). |

## Repository layout

| Path | Contents |
|------|----------|
| `mod/` | The Sims 4 mod side — Python 3.7 (`sensewright_mod/`), tuning XML (`tuning/`), build scripts. |
| `sidecar/` | FastAPI sidecar — Python 3.10+ (`sensewright_sidecar/`), config, locales, tests. |
| `docs/` | This documentation hub. |
| `scripts/` | PowerShell helpers (build, install, doctor, decompile). |
| `tools/` | Auxiliary tooling (DBPF, bias-buff generation, bias map). |
| `research/` | Third-party reference clones (S4CL, Lot 51 Core) — not redistributed. |

## Conventions

- **Language:** English is the canonical documentation language.
- **Architecture decisions** and cross-process contracts are documented in
  [`architecture.md`](architecture.md); implementation gaps in [`status.md`](status.md).
