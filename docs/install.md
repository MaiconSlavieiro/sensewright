# Sensewright v2 — Installation Guide

Step-by-step installation for players (Windows / macOS). Covers dependencies, mod build, sidecar configuration, autoboot, and the 0-key fallback.

---

## 1. Prerequisites

### The Sims 4
- Game version 1.90 or later (current patch).
- **Base game only** — no DLC/Expansion Packs required.
- **Script Mods Allowed** must be enabled:
  - In-game: **Options → Game Options → Other → ✅ Script Mods Allowed**
  - Restart the game after enabling.

### Required Mods (Install First)
Download and place in `Documents/Electronic Arts/The Sims 4/Mods/`:

| Mod | Source | Notes |
|-----|--------|-------|
| **S4CL (Sims 4 Community Library)** | [GitHub Releases](https://github.com/DeviantGameMods/Sims4CommunityLibrary/releases) | Download the `sims4communitylib.vX.Y.Z.zip` (not Source Code). Extract → copy `.ts4script` + `.config` files to Mods folder. |
| **Lot 51 Core Library** | [GitHub Releases](https://github.com/lot51/lot51_core/releases) | Download latest release. Extract → copy `.ts4script` to Mods folder. |

> **Important**: These are **runtime dependencies**. Sensewright will not load without them. Do not bundle them with Sensewright — install separately.

### Python (for Sidecar)
- **Windows**: Python 3.10+ (3.12 recommended). Download from [python.org](https://www.python.org/downloads/). **Check "Add Python to PATH" during install.**
- **macOS**: `brew install python@3.12` or download from python.org.
- Verify: open terminal / PowerShell and run:
  ```bash
  python --version
  # Should show 3.10.x, 3.11.x, or 3.12.x
  ```

---

## 2. Get Sensewright

### Option A: Pre-built Release (Recommended)
1. Go to [Sensewright Releases](https://github.com/<owner>/sensewright/releases) (or your distribution platform).
2. Download `Sensewright.v2.X.Y.zip`.
3. Extract → you get:
   - `Sensewright.ts4script`
   - `Sensewright.package`
   - `sidecar/` folder (contains `main.py`, `config.example.toml`, etc.)

### Option B: Build from Source
```bash
# Clone repo
git clone https://github.com/<owner>/sensewright.git
cd sensewright

# Build (requires Python 3.7 as `py -3.7` and Python 3.10+ as `python`)
make all          # builds .ts4script + .package
# Artifacts in mod/dist/
```

---

## 3. Install the Mod

### Windows
1. Open File Explorer → `Documents\Electronic Arts\The Sims 4\Mods\`
2. Copy `Sensewright.ts4script` and `Sensewright.package` into this folder.
3. **Do not** put them in subfolders deeper than one level (Mods/ or Mods/Sensewright/ only).

### macOS
1. Open Finder → `~/Documents/Electronic Arts/The Sims 4/Mods/`
   - If `Mods` doesn't exist, create it.
2. Copy `Sensewright.ts4script` and `Sensewright.package` into this folder.

### Using the Installer Script (Windows)
```powershell
# From repo root
.\scripts\install-mod.ps1
```
This copies both artifacts to your Mods folder automatically.

---

## 4. Configure & Run the Sidecar

### 4.1 Create Config
```bash
cd sidecar
cp config.example.toml config.toml
```

Edit `config.toml` with a text editor. **Minimum required changes**:

```toml
# If you have API keys, enable providers:
[llm.providers.openrouter]
enabled = true
api_key = "sk-or-..."          # Your OpenRouter key
models = ["openai/gpt-4o-mini"]

# Or use local Ollama (no key needed):
[llm.providers.ollama]
enabled = true
base_url = "http://127.0.0.1:11434"
models = ["llama3.1"]

# If you have NO keys and want fully offline play:
# Leave all providers.enabled = false (default).
# The mod will use deterministic localized fallbacks for all 33 purposes.
```

### 4.2 Run Sidecar Manually
```bash
cd sidecar
python main.py
```
Output:
```
INFO:     Uvicorn running on http://127.0.0.1:8765 (Press CTRL+C to quit)
INFO:     Sensewright Sidecar v2.0.0 started
```
- **REST API**: `http://127.0.0.1:8765/v1/...`
- **Web Studio**: `http://127.0.0.1:8765/ui` (open in browser)

Keep this terminal window open while playing.

### 4.3 Autoboot (Zero-Click Sidecar Start)

The mod's worker thread can auto-launch the sidecar when the game starts.

**Setup**:
1. Create `sidecar/python.txt` with the **full path** to your Python 3.10+ executable:
   - Windows: `C:\Python312\python.exe` or `C:\Users\<you>\AppData\Local\Programs\Python\Python312\python.exe`
   - macOS: `/usr/local/bin/python3.12` or `/opt/homebrew/bin/python3.12`
2. Ensure the sidecar folder is at `<Mods folder>/../sensewright/sidecar/` relative to the mod, OR the mod can locate it via the installed `.ts4script` path.

**How it works**:
- On `GAME_TICK`, worker thread calls `_probe_sidecar_health()`.
- If sidecar not responding, reads `sidecar/python.txt`, spawns `subprocess.Popen([python_exe, 'main.py'], cwd=sidecar_dir, CREATE_NO_WINDOW)`.
- Waits up to 5s for health check to pass.
- Logs: `Started sidecar process (PID: XXXX)` / `Sidecar autoboot successful`.

**macOS Note**: Autoboot uses `subprocess.Popen` with default flags. Test manually first with `python main.py`.

---

## 5. Verify Installation

1. Launch The Sims 4.
2. Load a save (or start new game).
3. **Mod Load Confirmation**: Check the cheat console (`Ctrl+Shift+C`):
   ```
   sensewright.version
   ```
   Should print `Sensewright v2.X.Y loaded`.
4. **Sidecar Connection**: Open browser → `http://127.0.0.1:8765/health`
   ```json
   {"status": "ok", "version": "2.0.0", "game_pid": 12345}
   ```
5. **In-Game Test**: Click any Sim → **Sensewright** pie menu → **Chat (Celular)**. Type a message. You should get a notification with the Sim's reply and a **[Responder Agora]** button.

---

## 6. The 0-Key Fallback (Offline Play)

If **no provider is enabled** or **all API keys are empty**, Sensewright operates fully offline:

- Every one of the 33 purposes returns a **deterministic localized fallback** (from `sidecar/locales/content/<lang>.json` under `fallbacks.<purpose_id>`).
- No network requests leave your machine.
- All gameplay loops work: chat, autonomy, dreams, evolution, God Director (soft influence only), memory, rumors.
- LLM-enhanced prose is replaced by templated but varied fallbacks (list rotation + gender inflection).

**To enable**: Simply leave `enabled = false` for all providers in `config.toml` (the default in `config.example.toml`).

---

## 7. Updating

### Mod Update
1. Download new `Sensewright.ts4script` + `Sensewright.package`.
2. Replace files in Mods folder.
3. Restart game.

### Sidecar Update
1. Pull latest repo / download new release.
2. If `config.toml` format changed, merge your keys into new `config.example.toml`.
3. Restart sidecar (`Ctrl+C` → `python main.py`).

### Save Compatibility
- Sensewright uses **Shadow DB** with transactional save sync.
- Loading an older save (rewind) automatically restores from ring buffer (last 3 checkpoints).
- "Save As" creates a new independent save slot.
- No manual migration needed.

---

## 8. Troubleshooting

### Mod Doesn't Appear / Pie Menu Missing
| Check | Fix |
|-------|-----|
| Script Mods enabled? | Game Options → Other → ✅ Script Mods Allowed → **Restart Game** |
| S4CL installed? | Must be in Mods folder (`.ts4script` + `.config`) |
| Lot 51 Core installed? | Must be in Mods folder (`.ts4script`) |
| Files in correct location? | `Mods/Sensewright.ts4script` and `Mods/Sensewright.package` (not deeper than 1 subfolder) |
| Python 3.7 bytecode? | If building from source: `make test` verifies syntax; `make mod` compiles with `py -3.7` |

### Sidecar Won't Start
| Error | Fix |
|-------|-----|
| `python: command not found` | Add Python to PATH; restart terminal |
| `ModuleNotFoundError: fastapi` | `pip install -r requirements.txt` (create if missing: `fastapi uvicorn pydantic tomli httpx pytest`) |
| `Address already in use` | Port 8765 busy → change `port` in `config.toml` `[server]` section |
| `config.toml not found` | `cp config.example.toml config.toml` |

### Autoboot Fails
| Symptom | Fix |
|---------|-----|
| `python.txt` not found | Create `sidecar/python.txt` with full Python path |
| Wrong Python version | Must be 3.10+; check `python --version` |
| Sidecar starts but health check fails | Check sidecar console for errors; verify `config.toml` syntax |

### Chat Shows `[missing:key]`
- Locale file missing translation key.
- Run `make doctor` → checks locale key parity.
- Add missing key to `data/locales/ui/<lang>.json` (overlay) or `sidecar/locales/ui/<lang>.json` (bundle).

### Autonomy Pulses Not Firing
- Lot 51 Core not loaded → verify `.ts4script` in Mods.
- Run `.\scripts\doctor.ps1` → checks all dependencies.

### Web Studio Not Loading
- Sidecar must be running (`python main.py`).
- Open `http://127.0.0.1:8765/ui` (not `localhost` if IPv6 issues).
- Check browser console for JS errors.

---

## 9. Running Diagnostics

```bash
# From repo root
make doctor
# or
.\scripts\doctor.ps1
```

Checks:
- Python 3.7 (`py -3.7`) and 3.10+ (`python`) availability
- All mod source files present
- Locale JSON validity + key parity (en-US vs pt-BR)
- Tuning XML present + generated `dist/stbl_keys.json` and `dist/tuning_ids.json`
- Build artifacts (`.ts4script`, `.package`) exist and valid
- Sidecar directory + `python.txt` + `main.py`
- TS4 Mods folder + installed artifacts

Exit code: `0` = all OK, `1` = issues found.

---

## 10. Uninstall

1. Delete `Sensewright.ts4script` and `Sensewright.package` from Mods folder.
2. (Optional) Delete `Documents/Electronic Arts/The Sims 4/mod_data/Sensewright/` (mod logs + SQLite saves).
3. Stop sidecar process (`Ctrl+C` in terminal).
4. S4CL and Lot 51 Core can remain (other mods may need them).

---

## 11. Support & Logs

### Log Locations
| Component | Location |
|-----------|----------|
| Mod (S4CL logger) | `Documents/Electronic Arts/The Sims 4/mod_data/Sensewright.log` |
| Sidecar | Terminal stdout/stderr (configured by `log_level` in `config.toml`) |
| Trace Correlation | Every request has `X-Trace-Id: tr_XXXXXXXX` — search in both logs |

### Reporting Issues
Include:
- Game version (bottom of main menu)
- Sensewright version (`sensewright.version` cheat)
- Sidecar version (`/v1/health` response)
- Relevant log snippets (mod log + sidecar console)
- Steps to reproduce

---

## 12. Advanced: Development Setup

If you want to modify the mod:

```bash
# Prerequisites
# - Python 3.7.9 installed (for `py -3.7`)
# - Python 3.12+ installed (for `python`)
# - S4CL & Lot 51 Core source in research/ (for reference)

# Build & test cycle
make test        # syntax check
make all         # build both artifacts
make install     # install to Mods
make sidecar     # run sidecar in foreground
# Edit code → make test → make all → make install → reload game (or restart)
```

### Decompile TS4 Scripts (for API reference)
```bash
make decompile
# Output: ~/Documents/TS4_Decompiled/
# Requires: pip install unpyc3
```

---

## 13. macOS Specific Notes

- **Mods folder**: `~/Documents/Electronic Arts/The Sims 4/Mods/` (create if missing).
- **Python**: Use Homebrew (`brew install python@3.12`) or official installer.
- **Autoboot**: `sidecar/python.txt` should contain `/opt/homebrew/bin/python3.12` (Apple Silicon) or `/usr/local/bin/python3.12` (Intel).
- **Gatekeeper**: If sidecar binary blocked, allow in System Settings → Privacy & Security.
- **Case-sensitive filesystem**: File paths in code use forward slashes; should work natively.

---

## 14. Quick Reference Card

| Task | Command |
|------|---------|
| Build mod + package | `make all` |
| Install to Mods | `make install` |
| Run sidecar | `make sidecar` (or `cd sidecar && python main.py`) |
| Open Web Studio | `http://127.0.0.1:8765/ui` |
| Run diagnostics | `make doctor` |
| Clean build artifacts | `make clean` |
| Enable autoboot | Create `sidecar/python.txt` with Python path |
| Play offline (0-key) | Leave all `enabled = false` in `config.toml` |
| Mod version cheat | `sensewright.version` (in-game console) |
| Sidecar health | `curl http://127.0.0.1:8765/v1/health` |