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
- `show_panel(sim_info)` → a **paged native dialog menu**, with console fallback.
- new cheat `sw.panel` (Live) + `sw.set <key> <value>` (apply one control; used
  by the dialog buttons), registered in `main.py` and `cmd.help.body`.
- `http_client.set_god_controls(values)` → `POST /v1/config/god`.

**GFX side (planned, P3)** — `SensewrightUI.package`:
- overrides/creates a GFX screen (real sliders, toggles, select, list);
- the `.ts4script` opens it and receives values back (via a callback command or
  a shared JSON file the mod polls and forwards to the sidecar).

### 3.1 Native panel mechanics (how the reference mods do it)

Confirmed by cloning reference mods into `research/ui-refs/` (see §4.1). The
mainstream approach is **native dialogs with button responses that dispatch
commands** — there is **no scriptable slider widget**, so a "slider" is a row of
stepped choice buttons.

- **Dialog factory:** `UiDialogOkCancel.TunableFactory().default(owner, text=…,
  title=…, text_ok=…)` and `UiDialogTextInputOk.TunableFactory().default(…)`
  (free text — e.g. the zeitgeist prompt).
- **Buttons that act:** `UiDialogResponse(dialog_response_id=ButtonType…,
  text=…, ui_request=UiDialogResponse.UiDialogUiRequest.SEND_COMMAND,
  response_command=<command>)`. This is how a menu button applies a setting
  without extra code — the command is our `sw.set`.
- **Custom dialog subclasses:** subclass `UiDialogOk` and override `responses`
  (see `TS4ControlAnySim/canys_ui.py`).
- **Panel = N pages:** a top page lists sections (God / Agents / Per-Sim /
  World & Language / Advanced); each section opens a page of rows; each row
  opens a choice (or steps the value) and calls `sw.set` / the roster endpoints.
- **In-game entry point (not just a cheat):** a **pie-menu category** on the Sim
  ("Sensewright") registered by a tiny XML tuning `.package` (interaction +
  `PieMenuCategory`), as `TS4ControlAnySim` and `ShadySimDeals` do. The pie
  interaction just runs `sw.panel`. No EA assets are redistributed.
- **Icons (optional):** custom art is packed as DDS/BC3 resource type
  `0x00B2D882`, group 0, referenced by `pie_menu_icon` (`ShadySimDeals`).

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

### 4.1 Reference implementations (cloned into `research/ui-refs/`)

Cloned for study only (never committed — see `.gitignore`).

| Repo | License | What it demonstrates |
|---|---|---|
| `lot51/core-library` → `utils/dialog.py` | MIT | `DialogHelper`: notification/`UiDialogOkCancel`/`UiDialogTextInputOk` factories + **`build_ui_response(response_command=…)`** (buttons that run commands) and `create_text_dialog` (free-text input). The cleanest blueprint for our native panel. |
| `TitanNano/TS4ControlAnySim` → `canys_ui.py` | Apache-2.0 | Custom `UiDialog` subclass (`UiDialogQuitIgnore(UiDialogOk)`) with a custom `responses` tuple; `dialog_class.TunableFactory(**kwargs).load_etree_node(...)`; pie-menu category + interaction tuning in a `.package`. |
| `mf-rl/ShadySimDeals` | Apache-2.0 | `UiDialogOkCancel`/`UiDialogNotification` confirmations; pie-menu category SimData build; custom UI icons as BC3/DST5 `0x00B2D882`. |
| `azigler/ts4-modding-workspace` | (none) | Minimal `UiDialogNotification.TunableFactory().default(...)` example + hot-reload utilities. |

Take-aways: (1) nobody ships a scriptable slider — panels are stepped choice
dialogs or pie menus; (2) the reusable piece we want is `DialogHelper`-style
factories + `response_command` buttons; (3) a pie-menu category is the standard
"open the mod's UI" entry without shipping EA assets.

> **Licensing:** `core-library` is MIT (adaptable with attribution);
> `TS4ControlAnySim`/`ShadySimDeals` are Apache-2.0. We will **reimplement** the
> small dialog helper in our own module (no code copied verbatim) and credit the
> originals in `docs/`/`CHANGELOG.md`.

---

## 5. Roadmap (adjusted after the reference study)

1. **P1 — Model:** promote the "not exposed" settings into `ControlSpec`;
   add `http_client.set_god_controls` + a generic `sw.set <key> <value>`;
   i18n labels/descriptions for every key.
2. **P2 — Native panel:** `panel_ui.py` (a `DialogHelper`-style module) +
   `sw.panel`, covering **all** sections. Rows are stepped choice buttons whose
   responses dispatch `sw.set`/roster commands. Works in-game today, no
   dependency, no EA assets.
3. **P2b — In-game entry:** a tiny XML tuning `.package` adding a **"Sensewright"
   pie-menu category** on the Sim that runs `sw.panel` (the usual mod-UI entry).
4. **P3 — GFX sliders:** `SensewrightUI.package` (S4S/S4E + FFDec) with **real
   sliders** + the AS3↔Python bridge; the native panel stays as fallback.
5. **P4 — Live validation:** render + write-back on the real client, then the
   patch-rebuild drill for the package.

> Until P3 ships, the native panel + pie entry is the shipping UI; it exposes the
> same settings, only with stepped values instead of real sliders.
