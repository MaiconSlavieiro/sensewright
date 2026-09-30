# Sensewright — In-Game Configuration Panel (design + settings inventory)

> Goal: **one** panel **inside the game** that exposes every configurable option
> of the mod and its agents — values, toggles, selects, tags and per-agent
> settings — using **The Sims 4's own native dialogs** (list/picker, paginated
> responses, numeric input, multi-select).
>
> **No Flash, no slider, no external tools, no `.package` for the UI.** Drag
> sliders are not scriptable in TS4, so a 0..1 value is a **row of stepped
> choices** (`0 / .25 / .5 / .75 / 1`) or a **native numeric input**. The look is
> the game's own.
>
> The declarative source of truth is the sidecar's `ControlSpec` registry
> (`sidecar/sensewright_sidecar/god/controls.py`). Adding a setting = one spec
> entry + i18n keys; the panel picks it up for free.

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

### 1.4 Mod / global — promoted into `ControlSpec` (P1)

These become ControlSpec entries (single source of truth) with a `target`/`path`
so `/v1/config/god` validates and applies them, and the panel renders them.

| Setting | Kind | Range / step | Default |
|---|---|---|---|
| `ui.language` | select | auto / <every manifest locale> | auto |
| `llm.temperature` | slider | 0..2 / 0.05 | 0.8 |
| `llm.max_tokens` | slider | 128..4096 / 64 | 700 |
| `llm.budget_per_sim_per_day` | slider | 0..2000 / 50 | 500 |
| `memory.consolidation_enabled` | toggle | on/off | on |
| `memory.decay_preset` | select | fast / normal / slow | normal |
| `memory.dejavu_chance` | slider | 0..0.5 / 0.01 | 0.05 |
| `agents.personality.absorption_enabled` | toggle | on/off | on |
| `agents.personality.salience_threshold` | slider | 0..5 / 0.1 | 1.5 |
| `agents.personality.sleep_consolidation` | toggle | on/off | on |
| `agents.evolution.enabled` | toggle | on/off | on |
| `agents.evolution.trait_swap` | select | off / propose / auto | propose |
| `agents.evolution.drift_strength` | slider | 0..1 / 0.05 | 0.2 |
| `agents.social.max_pairs_per_tick` | slider | 0..4 / 1 | 1 |
| `agents.social.pair_cooldown_seconds` | slider | 30..600 / 30 | 180 |
| `god.backgrounds.enabled` | toggle | on/off | on |
| `god.backgrounds.batch_size` | slider | 1..10 / 1 | 2 |
| `runtime.expose_roster` | toggle | on/off | on |

> **Excluded from the panel (`restart_only`):** `network.*` and
> `runtime.shutdown_on_game_exit` (read once at sidecar startup). Zeitgeist is
> **not** a flat setting — it gets its own panel page via `POST /v1/god/zeitgeist`.

---

## 2. UI design

**Sections (panel pages):**
1. **God** — the 5 dials, `evolution_speed`, mood tags, the 6 power toggles.
2. **Agents** — seats, impulse dials, reasoning effort, layer toggles, reactions.
3. **Per-Sim** — pick a Sim from the roster; autonomy + impulse override; tier.
4. **World** — zeitgeist (tags + free text); language.
5. **Advanced** — every `advanced=True` spec (incl. promoted llm/memory/etc.).

**Widgets (all native EA dialogs — no Flash, no slider)**
| Control kind | Native rendering |
|---|---|
| `slider` | **row of stepped choices** (0 / .25 / .5 / .75 / 1, or the spec step) **or** native numeric input (min/max validated) |
| `toggle` | two-row choice On / Off (current one marked chosen) |
| `select` | list of options (picker rows), current one marked chosen |
| `tags` | native **multi-select** dialog over the 7 mood tags |
| per-Sim + roster | `UiObjectPicker`/sim picker list → per-Sim page |
| status/providers/memory | read-only text page (console fallback for long output) |

**Data flow:**
`GET /v1/god/controls` (+ `GET /v1/agency/seats`) → render →
`POST /v1/config/god` (`persist=true`) / `POST /v1/agency/seats` /
`POST /v1/config/autonomy` / `POST /v1/config/lang` → refresh the page.

---

## 3. Architecture

**Script side (`mod/sensewright_mod/`)** — new `panel_ui.py`:
- `build_sections(controls, values, roster)` → the panel model (pure, tested).
- `format_panel(...)` → console fallback (pure, tested).
- Native renderer: section list → option pages → value pages. Uses EA's native
  dialogs (see §3.1), each row dispatches `sw.set <key> <value>` or a roster
  endpoint. Layered fallback: picker → paginated responses → console.
- new cheats `sw.panel` (Live) + `sw.set <key> <value>` (validated; persists).
  **Today:** `sw.god set <key> <value>` already applies a ControlSpec value; the
  dedicated `sw.set`/`sw.panel` surface is the remaining P2 work.
- `http_client.set_god_controls(values, persist=True)` → `POST /v1/config/god`
  (**done**).
- `ui.language` options are **data-driven**: the sidecar renders `auto` + every
  locale from `locales_content/manifest.json` and ships each option's human
  `label`, so the panel/localization needs no per-language keys.

**Entry points**
- **Now:** a button on the boot notification ("Open Panel") using
  `ui_responses` + `SEND_COMMAND` → `sw.panel`, plus the `sw.panel` cheat.
- **Optional (P2b):** a **pie-menu category** "Sensewright" on the Sim, via a
  tiny XML tuning `.package` (writer in pure Python; no S4S/FFDec).

**Sidecar (P1)** — `ControlSpec` promotion + persistence overlay (§4).

### 3.1 Native dialog mechanics (what the game already exposes)

Verified from the S4CL documentation (`DeviantGameMods/Sims4CommunityLibrary`,
open source) which wraps EA's native dialogs — we **reimplement the pattern**
in our own module (no dependency, no copied code):

- **List/picker dialogs:** `ui.ui_dialog_picker.UiObjectPicker` with
  `BasePickerRow`/`ObjectPickerRow`/`SimPickerRow` — native rows with icon,
  description, tooltip, **pagination (`per_page`)**, a category dropdown, and
  "always visible" rows. This is the "choose a trait/object" look.
- **Paginated responses:** a response dialog that pages buttons (Previous /
  Next) — used for long option lists.
- **Numeric input:** a native input dialog with `initial_value`, `min_value`,
  `max_value` (used for the 0..1 values as an alternative to step buttons).
- **Multi-select:** native multi-select dialog with `min/max_selectable`
  (used for the 7 mood tags).
- **Toggle/select** are just option rows (current value pre-selected).
- **Buttons that act:** `UiDialogResponse(..., ui_request=SEND_COMMAND,
  response_command=<command>)` — a button runs a cheat command, so rows apply
  settings through `sw.set` without extra wiring.
- **Owners/labels:** dialog owner = the active Sim instance; text via
  `sims4.localization.LocalizationHelperTuning.get_raw_text(...)` (already
  validated in `chat_ui.py`).

> **No scriptable slider exists.** Drag sliders live only in EA's GFX screens
> (see §5, deferred). The native step buttons + numeric input are the shipping
> UX and are indistinguishable from the game's own menus.

---

## 4. Persistence — overlay `panel.toml`

Today `POST /v1/config/god` mutates settings **in memory only**. The panel adds
a persistence overlay so changes survive a sidecar restart, **without touching
the user's `config.toml`**:

- **Load:** `load_settings` loads `config.toml`, then, if present,
  `data/panel.toml`, deep-merging **only** `ControlSpec`-known paths (env
  expanded).
- **Write:** `POST /v1/config/god` with `persist=true` writes the validated
  overrides to `data/panel.toml` via a small built-in TOML serializer (no new
  dependency; flat `[section] key = value` per path).
- **Reset:** a panel action deletes the overlay (back to `config.toml`).
- `restart_only` settings are never written here.

---

## 5. Appendix — Flash/GFX sliders (deferred, not planned)

Kept for reference only; **not** on the roadmap. Drag-slider screens require the
game's Flash/Scaleform GFX inside `UI.package` (tools: S4S/S4E + JPEXS FFDec;
patch-fragile; EA assets cannot be redistributed). Sources: SimsEdit UI docs
(<https://simsedit.com/ui-mods/ui-101/>, `.../gfx/gfx-intro/`,
`.../gfx/gfx-modding/`, `.../references/software-setup/`).

### Reference implementations (cloned into `research/ui-refs/`, never committed)

| Repo | License | Use |
|---|---|---|
| `lot51/core-library` → `utils/dialog.py` | MIT | `DialogHelper`: notification/`UiDialogOkCancel`/`UiDialogTextInputOk` factories + `build_ui_response(response_command=…)`. |
| `TitanNano/TS4ControlAnySim` → `canys_ui.py` | Apache-2.0 | Custom `UiDialogOk` subclass with a `responses` tuple; pie-menu category tuning. |
| `mf-rl/ShadySimDeals` | Apache-2.0 | Confirmations; pie-menu category SimData build; DDS icons. |
| `azigler/ts4-modding-workspace` | (none) | Minimal notification dialog + hot-reload utilities. |

S4CL (`DeviantGameMods/Sims4CommunityLibrary`) is the key reference for the
**native picker/response/input dialogs** (§3.1). We reimplement, never copy, and
credit the originals in `docs/`/`CHANGELOG.md`.

---

## 6. Roadmap

1. **P1 — Model + persistence (sidecar).** ✅ **Done** (build `2026-09-29.21`).
   §1.4 promoted into `ControlSpec` with `target`/`path`; generic
   `apply_values_to_settings` / `apply_control_values_to_settings` /
   `values_from_settings`; `POST /v1/config/god?persist` → `panel.toml` overlay
   (`panel_store.py`; deep-merged in `load_settings`);
   `POST /v1/config/panel/reset`; `restart_only` marked (hidden + never
   persisted); i18n label/desc keys for every spec. Tests:
   `sidecar/tests/test_controls_panel.py`.
2. **P2 — Native panel (mod).** `panel_ui.py` (model + native renderer +
   console fallback) + `sw.set`; `http_client.set_god_controls`; boot-notification
   button; `cmd.help.body`.
3. **P2b — Pie-menu entry (optional).** `mod/ui_package/` (category + interaction
   `do_command sw.panel` + data-driven STBL `tuning/stbl.json`) and `build_package.py` (pure-Python DBPF
   writer, reference `ShadySimDeals/build_mod.py`).
4. **P3 — Live validation + docs.** Round-trip on the client, restart-persistence
   check, `[validate]` logs, CHANGELOG/STATUS/PLANO, test counts.

### P0 — In-game spike (validated live)
**Validated** (build `2026-09-29.9`): `mod/sensewright_mod/ui_probe.py` + `sw.uitest`
kinds confirm on the live client: (a) picker rows + pagination (`picker`, 24
rows); (b) a response dialog with `SEND_COMMAND` buttons (`response` → a button
runs `sw.uitest clicked`); (c) the numeric input dialog (`input`,
`UiDialogTextInputOk` + `UiTextInput`); (d) multi-select (`multi`, picker with
`max_selectable > 1`). All **8 kinds render** (`ok=True` in the log). Run
`sw.uitest all` (or one kind), and `sw.uitest probe` for a no-UI
class-availability report. Each probe returns `{kind, ok, layer, error}` and logs
`[validate] uitest …`.

Live findings (build `2026-09-29.8`): the **object skin** (`picker`) reads best;
rows should carry an **icon**. Confirmed from the shipped bytecode that
`ObjectPickerRow(icon=<ResourceKey>)` (row reads `.type/.group/.instance`, builds
`IconInfoData(icon_resource=…)`) — so `picker_icons` decorates rows with real EA
icons (object definitions / mood / traits) with **no `.package`**. Player text
must be short; long copy goes in the **row tooltip**. TS4 renders **DDS**
textures, not SVG: per-setting custom art needs an SVG→DDS→DBPF pipeline
(`research/ui-refs/ShadySimDeals/build_mod.py` is the writer reference).

APIs were cross-checked against the shipped `simulation.zip` bytecode
(`ui.ui_dialog_picker.UiDialogObjectPicker`/`UiObjectPicker`/`UiSimPicker`,
`ui.ui_dialog_generic.UiDialogTextInputOk`, `ui.ui_text_input.UiTextInput`,
`ui.ui_dialog.UiDialogResponse` + `UiDialogUiRequest.SEND_COMMAND`,
`distributor.shared_messages.IconInfoData`).

---

## 7. Test plan & risks

**Tests.** Sidecar: promoted specs (validate/coerce/route), overlay precedence +
serializer round-trip, `config_god` persist. Mod: panel model, `sw.set` parsing,
`set_god_controls`, console fallback, locales parity, Python 3.7. Full suites +
ruff + `py -3.7 mod/build.py`.

**Risks.**
- Dialog API varies by patch → P0 spike + layered fallback (picker → response →
  console).
- Numeric input returns a string → parse/validate (`invalid_argument`).
- Live-apply per key → verified in P1; `restart_only` excluded and labelled.
- Notification buttons not yet validated live → P0(b).
- Rendering is only testable in-game → the model stays 100% unit-tested.
