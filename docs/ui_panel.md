# Sensewright — In-Game Configuration Panel (design + settings inventory)

> Goal: **one** in-game panel that exposes every configurable option of the mod
> and its agents — **sliders**, toggles, selects, tags and per-agent values.
> Two render paths share the same control model:
> **(A) native dialog menu** (works today, no dependency) and
> **(B) custom GFX/Flash panel** (real sliders, planned).
>
> The declarative source of truth is the sidecar's `ControlSpec` registry
> (`sidecar/sensewright_sidecar/god/controls.py`). Adding a setting = one spec
> entry + i18n keys; both UI paths pick it up for free.

---

## 1. Settings inventory

### 1.1 God / world orchestration (ControlSpec, `POST /v1/config/god`)

| Key | Kind | Range / step | Default |
|---|---|---|---|
| `autonomy_degree` | slider | 0..1 / 0.05 | 0.5 |
| `chaos_degree` | slider | 0..1 / 0.05 | 0.3 |
| `mood_influence` | slider | 0..1 / 0.05 | 0.5 |
| `intervention_frequency` | slider | 0..1 / 0.05 | 0.5 |
| `intensity` | slider | 0..1 / 0.05 | 0.5 |
| `evolution_speed` | select | slow / normal / fast | normal |
| `mood_tags` | tags | 7 mood tags (multi) | [] |
| `power_spawn_npc` | toggle | on/off | on |
| `power_apply_trait` | toggle | on/off | on |
| `power_force_social` | toggle | on/off | on |
| `power_gossip` | toggle | on/off | on |
| `power_relationship_shift` | toggle | on/off | on |
| `power_extreme_events` | toggle | on/off | **off** |

### 1.2 Agent roster dials (ControlSpec *advanced*, same endpoint)

| Key | Kind | Range / step | Default |
|---|---|---|---|
| `agent_seats` | slider | 1..24 / 1 | 12 |
| `impulse_frequency` | slider | 0..1 / 0.05 | 0.2 |
| `player_sim_impulse_frequency` | slider | 0..1 / 0.05 | 0.0 |
| `reactions_enabled` | toggle | on/off | on |
| `reasoning_effort` | select | none / minimal / low / medium / high | none |
| `layer_memory` | toggle | on/off | on |
| `layer_cognition` | toggle | on/off | on |
| `layer_social` | toggle | on/off | on |

### 1.3 Per-Sim

| Item | Kind | Values | Endpoint |
|---|---|---|---|
| Autonomy level | select | off / observe / suggest / semi / full | `POST /v1/config/autonomy` |
| Impulse frequency (override) | slider | 0..1 / 0.05 | `POST /v1/agency/seats` (`sim_id`,`impulse_frequency`) |
| Roster (seats used, tier, sim_id) | list (read) | — | `GET /v1/agency/seats` |

### 1.4 Mod / global (partly exposed today; candidates to promote into ControlSpec)

| Setting | Kind | Default | Status |
|---|---|---|---|
| `ui.language` | select | auto / en / pt-BR | exposed via `sw.lang` (`POST /v1/config/lang`) |
| Zeitgeist text + tags | text + tags | — | `POST /v1/god/zeitgeist` |
| `llm.temperature` | slider 0..2 | 0.8 | not exposed |
| `llm.max_tokens` | slider 128..4096 | 700 | not exposed |
| `llm.budget_per_sim_per_day` | slider 0..2000 | 500 | not exposed |
| `llm.reasoning_effort` | select | none | global fallback |
| `memory.consolidation_enabled` | toggle | on | not exposed |
| `memory.decay_preset` | select | fast / normal / slow | not exposed |
| `memory.dejavu_chance` | slider 0..1 | 0.05 | not exposed |
| `agents.personality.absorption_enabled` | toggle | on | not exposed |
| `agents.personality.salience_threshold` | slider 0..5 | 1.5 | not exposed |
| `agents.personality.sleep_consolidation` | toggle | on | not exposed |
| `agents.evolution.enabled` | toggle | on | not exposed |
| `agents.evolution.trait_swap` | select | off / propose / auto | not exposed |
| `agents.evolution.drift_strength` | slider 0..1 | 0.2 | not exposed |
| `agents.social.max_pairs_per_tick` | slider 0..4 / 1 | 1 | not exposed |
| `agents.social.pair_cooldown_seconds` | slider 30..600 / 30 | 180 | not exposed |
| `god.backgrounds.enabled` | toggle | on | not exposed |
| `god.backgrounds.batch_size` | slider 1..10 / 1 | 2 | not exposed |
| `runtime.expose_roster` | toggle | on | not exposed |
| `runtime.shutdown_on_game_exit` | toggle | on | not exposed |

> **Recommendation:** promote the "not exposed" rows into `ControlSpec` so the
> panel and `/v1/config/god` cover them with the same validation (single source
> of truth, no UI rewrite).

---

## 2. UI design

**Sections (tabs / pages):**
1. **God** — orchestration sliders, `evolution_speed`, mood tags, power toggles.
2. **Agents** — seats, impulse dials, reasoning effort, layer toggles,
   reactions.
3. **Per-Sim** — pick a Sim from the roster; set autonomy + impulse override;
   show tier/seat.
4. **World & Language** — language select; zeitgeist (tags + free text).
5. **Advanced** — the `advanced=True` specs (agent dials + promoted settings).

**Widgets and their native approximations**
| Design widget | Native dialog | Flash panel |
|---|---|---|
| slider | stepped choice (`0`, `.1` … `1`) or `−` / `+` | real slider |
| toggle | choice On/Off | switch |
| select | single-choice dialog | dropdown |
| tags (multi) | multi-select dialog | checkbox group |
| list (roster) | read-only text + per-row action | scroll list |

**Data flow (both paths):**
`GET /v1/god/controls` (+ `GET /v1/agency/seats`) → render →
`POST /v1/config/god` / `POST /v1/agency/seats` / `POST /v1/config/autonomy` /
`POST /v1/config/lang` → refresh.

---

## 3. Architecture

**Script side (`mod/sensewright_mod/`)** — new `panel_ui.py`:
- `build_sections(controls, values)` → the panel model (pure, unit-tested).
- `format_panel(...)` → console fallback text (pure).
- `show_panel(sim_info)` → native dialogs, with console fallback.
- new cheat `sw.panel` (Live), registered in `main.py` and `cmd.help.body`.
- `http_client.set_god_controls(values)` → `POST /v1/config/god`.

**GFX side (planned)** — `SensewrightUI.package`:
- overrides/creates a GFX screen (sliders, toggles, select, list);
- the `.ts4script` opens it and receives values back (via a callback command or
  a shared JSON file the mod polls and forwards to the sidecar).

---

## 4. Flash/GFX pipeline (how real TS4 UI mods do it)

Source: SimsEdit UI docs (2026).

- The TS4 UI is **Adobe Flash / Scaleform GFX** (a modified **SWF**) inside the
  base-game **`UI.package`**. It supports shapes, images, text, animation and
  **ActionScript 3** (compiled to P-code).
- **Tools:** **Sims 4 Studio** or **Sims 4 Editor (S4E)** to browse/extract UI
  resources from `UI.package`; **JPEXS Free Flash Decompiler (FFDec)** to edit
  the `.gfx` (tags + ActionScript). FFDec does not understand `.package`, so
  images show as red boxes — cross-reference with S4E/S4S.
- **Approach:** extract a GFX that already contains a slider (e.g. a Game
  Options screen), clone/repurpose it, add our labels and callbacks, rebuild a
  `.package` that overrides the target resource key.
- **AS3 ↔ Python bridge options:** (a) buttons call a cheat command; (b) the
  screen writes a small JSON file that the mod polls and forwards to the
  sidecar; (c) reuse an existing EA dialog resource and only reskin.
- **Risks / constraints:**
  - **Patch fragility:** UI resource keys/layout change on patches; the
    override must be rebuilt.
  - **Licensing:** EA UI assets **cannot be redistributed** — the panel's GFX
    must be original (or built at install time from the player's own files).
  - **Tooling is GUI-only.** The GFX binary cannot be produced headless in this
    repo; AS3 source, resource definitions and the build script can be authored
    here, but the final compile is manual in S4S/FFDec.
- Sources: <https://simsedit.com/ui-mods/ui-101/>,
  <https://simsedit.com/ui-mods/gfx/gfx-intro/>,
  <https://simsedit.com/ui-mods/gfx/gfx-modding/>,
  <https://simsedit.com/references/software-setup/>.

---

## 5. Roadmap

1. **P1 — Model:** promote the "not exposed" settings into `ControlSpec`;
   add `http_client.set_god_controls`; i18n labels/descriptions for every key.
2. **P2 — Native panel:** `panel_ui.py` + `sw.panel` covering **all** sections
   (stepped sliders, toggles, selects, tags, roster). Works in-game today.
3. **P3 — GFX panel:** `SensewrightUI.package` (S4S/S4E + FFDec) with real
   sliders + the AS3↔Python bridge; keep the native menu as fallback.
4. **P4 — Live validation:** render check, write-back check, patch rebuild.

> Until P3 ships, `sw.panel` (native) is the shipping UI; it covers the same
> settings, only with stepped values instead of real sliders.
