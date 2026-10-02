# Build & Development

## Prerequisites

- **Python 3.7.9** available as `py -3.7` — required to compile the mod's `.ts4script` (Python 3.7 bytecode).
- **Python 3.10+** (3.12 recommended) available as `python` — required for build scripts and the sidecar.
- **S4CL** and **Lot 51 Core** source in `research/` (for API reference only).
- **`sidecar/python.txt`** — create this file after cloning, containing the full path to a
  Python 3.10+ executable (e.g., `C:\Python312\python.exe`). The mod reads this at runtime
  to auto-start the sidecar process. This file is `.gitignore`d and not versioned.

## Make Targets

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

## PowerShell Scripts

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

## Build Details

- **`.ts4script`**: compiled with Python 3.7 (`py -3.7 -m py_compile`). Verifies the magic number `42 0d 0d 0a`. Includes the `locales/` JSON files.
- **`.package`**: DBPF with XML tuning + manifest-driven STBL compilation. Reads `manifest.json`, iterates locales, converts `ts4_stbl_byte` to a Resource Key, compiles FNV-1 hashed keys. Emits `stbl_keys.json` mapping.

## Development Cycle

```bash
# Edit code → make test → make all → make install → reload game (or restart)
make test        # syntax check
make all         # build both artifacts
make install     # install to Mods
make sidecar     # run sidecar in foreground
```

### Running Tests

```bash
cd sidecar
python -m pytest -q
```

### Decompile TS4 Scripts (for API reference)

```bash
make decompile
# Output: ~/Documents/TS4_Decompiled/
# Requires: pip install unpyc3
```

## Working the Backlog

Remaining implementation gaps and the execution plan to close them live in
[`status.md`](status.md) and [`plan.md`](plan.md). The full specification is
[`requirements.md`](requirements.md).
