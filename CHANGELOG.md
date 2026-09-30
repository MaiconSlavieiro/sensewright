# Changelog

All notable changes to **Sensewright** are documented in this file.

- Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
- Versioning follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
- Conventions: code, docs and code comments are in **English**; player-facing text
  goes through the locale system (`en` default, `pt-BR` supported).
- The phase names/numbers match `PLANO.md` Â§11.

---

## [Unreleased] â€” Phases 2, 2b, 3, 4, 5a, 5b, 5c + v0.2 Â§14: Directives, Census, Agents, Evolution, God foundation, backgrounds, orchestration & autonomous Sim agents

### Changed - Sidecar content localization is data-driven (sidecar only)
All deterministic (no-LLM) content strings moved out of Python into flat JSON
locale tables, so adding a language is a data change (drop a JSON file + add a
manifest entry), not a code change.
- **`sidecar/sensewright_sidecar/content_i18n.py`** (new) +
  **`locales_content/`** (`manifest.json`, `en.json`, `pt-BR.json`): lazy-loaded
  tables keyed by dotted names (`sys.*`, `background.*`, `profile.*`,
  `personality.*`, `social.line.*`, `consolidation.*`, `reflection.*`,
  `initiative.*`). Public API: `default_lang`, `locale_entries`,
  `available_locales`, `language_name`, `normalize_lang`, `t`. `t()` never
  raises; unknown tags fall back to the manifest default.
- **`locales.py`** is now a thin wrapper over the `sys.*` content keys.
  **`schemas.py`** derives `DEFAULT_LANG` / `SUPPORTED_LANGS` / `normalize_lang`
  from the manifest. **`config.py`** uses `content_i18n.default_lang()`.
- Refactored to render from locale keys (no inline pt-BR tables, no per-lang
  `_LANG_NAMES`): `god/backgrounder.py`, `god/zeitgeist.py`,
  `agent/{profiler,personality,initiative,evolution,social}.py` and
  `memory/consolidation.py`. English LLM prompts stay in code.
- **`god/controls.py`**: `ControlOption` gained an optional ready-to-render
  `label`, populated for the data-driven `ui.language` options (`auto` + every
  manifest locale) via `content_i18n.language_name`.
- Tests: sidecar **461** (new `tests/test_content_i18n.py`: manifest discovery,
  `normalize_lang` incl. enum-repr strings, `language_name`, unknown → default,
  locale parity; plus a data-driven `ui.language` options test). Existing
  prompt-language assertions updated to the manifest name "Português (Brasil)".
- The sidecar's multilingual lexical data (stopwords / emotion words / name
  exclusions used by consolidation) moved to `locales_content/lexicon.json`, so
  no language word list is hardcoded in code.

### Changed - Mod localization is data-driven (add a language without touching code)
- **`mod/sensewright_mod/locales/manifest.json`** (new): `{default, locales:[{code,
  name, match}]}` describes the supported set. Adding a language = drop
  `locales/<code>.json` + append a manifest entry.
- **`mod/sensewright_mod/i18n.py`**: discovery (`available_locales`,
  `locale_entries`, `language_name`), boundary-aware `_normalize_locale` driven
  by the manifest `match` tokens (so `french` no longer false-matches `en`, while
  enum reprs like `Locale.PORTUGUESE_BRAZIL` still resolve), default from the
  manifest, and no fixed `("en","pt-BR")` references. Works from the filesystem
  and from inside the `.ts4script` zip (manifest is bundled).
- **`mod/build_package.py`** + **`mod/tuning/stbl.json`** (new): the pie-menu
  string tables are now data-driven (one entry per language); adding a language
  is a JSON entry, no code change.
- **`main.py`**: `VALID_LANGUAGES` is derived from `i18n.available_locales()`
  (`sw.lang` accepts any injected locale). **`config.py`** validates
  `[ui].language` against the manifest. **`god_ui._control_options`** prefers a
  literal option `label`, so the sidecar's language names render with no
  per-language keys.
- Tests: mod **363** (`test_locales_parity.py` now iterates the manifest;
  `test_i18n.py` gained discovery + boundary-matching tests).

### Added - God orchestration loop in-game (build `2026-09-29.23`)
Closes the Phase 5c gap: the God orchestrator existed sidecar-side but nothing
on the mod ever ran a tick or executed the returned directives.
- **`mod/sensewright_mod/http_client.py`**: `god_tick(sim, time_of_day,
  lot_type, lang)` (`POST /v1/god/tick`) and `set_god_controls(preset, enabled,
  powers, values, persist)` (`POST /v1/config/god`).
- **`mod/sensewright_mod/state_collector.py`**: the God tick loop.
  `maybe_god_tick(force=False)` polls the sidecar on a slow wall-clock cadence
  (`GOD_TICK_INTERVAL_SECONDS = 60`) from the existing `pulse_and_pull`
  heartbeat and executes the response. `execute_god_directives(directives)` runs
  each directive through the standard `tool_executor.execute` (add_trait,
  add_buff, queue_interaction, say_to) and surfaces its `narration` as a
  narrator notification; world events with no `tool_call` stay
  notification-only. Every decision is logged with `[validate] god: ...`.
- **`mod/sensewright_mod/main.py`**: `sw.god` is now a real control surface -
  `sw.god` (summary, now showing the current preset), `sw.god on|off`,
  `sw.god tick` (forced tick), `sw.god preset <name>` / `sw.god <preset>`, and
  `sw.god set <key> <value>` (ControlSpec-validated). Build `2026-09-29.23`.
- **`mod/sensewright_mod/god_ui.py`**: `GOD_PRESETS` mirrored from the sidecar
  intervention deck.
- **`sidecar/sensewright_sidecar/god/orchestrator.py`**: directive lifecycle -
  returned directives are marked `issued`, the in-memory history is capped
  (`MAX_DIRECTIVE_HISTORY`), `drain_directives()` added, and `status()` reports
  `issued_directives`/`history_size`.
- **`sidecar/sensewright_sidecar/god/controls.py`**: `values_from_settings` now
  surfaces the active God `preset` in the value map so the mod can display it.
- **Neighborhood mapping**: `state_collector.scan_neighborhood(force=False)` sends
  a **full-save census** once per session (and on demand via `sw.god scan`), so
  the God models **every** Sim/household in the save - not just the active zone -
  and the background pipeline queues a background per household, per Sim and for
  relationship-linked NPCs. `main._run_neighborhood_scan` reports the counts.
- **`sidecar/sensewright_sidecar/agent/graph.py`**: `_merge_census` merges census
  snapshots by id (never shrinking a `full_save` map with a later `active_zone`
  re-send; household member lists are unioned, newer native data wins), so the
  neighborhood stays mapped across zone loads and household changes.
- **Native family ties (kinship)**: `sim_context._get_kinship` reads the game's
  genealogy tracker (`SimInfo.genealogy` / `SimInfo.get_relations` with the
  `FamilyRelationshipIndex` enum, confirmed in the shipped `sims.sim_info`),
  falling back to `get_family_sim_ids_gen`; the census now carries a `kinship`
  list (`{relation, target_id, name}`) and the background prompt/fallback render
  it as a "Family" line, so written backstories never contradict the real family
  tree. (`CensusSim.kinship` added to the wire contract.)
- i18n: `cmd.god.*` control keys + `notify.god.directive` (en + pt-BR).
- Tests: sidecar **445**, mod **360** (new `mod/tests/test_god_orchestration.py`:
  HTTP payloads, tick execution/narration/throttle/failure, `sw.god` subcommands,
  neighborhood scan; sidecar orchestrator lifecycle + census-merge tests; kinship
  is covered in `test_sim_context.py`, `test_census.py` and `test_backgrounder.py`).

### Added â€” player-activity detection + precise cancel (build `2026-09-29.22`)
Adopted, with attribution, from the MIT-licensed `dnavaria/sims4ai` reference
(see `THIRD_PARTY_NOTICES.md`):
- **`mod/sensewright_mod/player_activity.py` (new)** â€” a `Sim.push_super_affordance`
  wrapper detects **real player interactions** (pie menu/click; `InteractionSource`
  `USER`/`PIE_MENU`/`GET_TO_WORK`) and arms the player-priority lock **locally and
  on the sidecar** (`POST /v1/config/player-activity`). This closes the
  "player-activity detection signal" spike item: previously the lock was only
  armed when the player typed a `sw.*` command. Agent pushes use `SOURCE_SCRIPT`
  and are ignored; **unknown sources do not fire** (safer than the reference,
  which fires on every unrecognised push). Installed from `__init__.py` and
  retried from `main._ensure_ready()`.
- **`tool_cancel_current`** now cancels only the **running** interaction
  (`queue.running.cancel(finishing_type=None, cancel_reason_msg=â€¦)`, with a
  `TypeError` fallback) before dropping back to `cancel_all`/`clear` â€” the
  faithful "override its own current interaction" lever for the `full` level.
- **`_push_affordance`** gains a `queue.run_super(affordance, target=â€¦)` fallback.
- **License**: added `LICENSE` (MIT) and `THIRD_PARTY_NOTICES.md` (SimAI/MIT
  attribution for the adapted code).
- Tests: mod **325 â†’ 337** (new `test_player_activity.py`: source classification,
  local+sidecar dispatch, install/idempotence, error swallowing; plus
  `test_executor.py` cancel and `run_super` paths).

### Added â€” panel P1: ControlSpec promotion + `panel.toml` overlay (build `2026-09-29.21`)
Sidecar groundwork for the in-game configuration panel (`docs/ui_panel.md` Â§6, P1).
Offline-testable; the panel UI itself is P2.
- **Promoted Â§1.4 settings into `ControlSpec`**: each spec now carries a
  `target`/`path` (e.g. `agents.personality` / `salience_threshold`) plus
  `restart_only`. New entries: `ui.language`, `llm.temperature`,
  `llm.max_tokens`, `llm.budget_per_sim_per_day`, the memory dials,
  `agents.personality.*`, `agents.evolution.*`, `agents.social.*`,
  `god.backgrounds.*`, `runtime.expose_roster`; existing God/agent dials also
  got their canonical path.
- **Generic mapping**: `apply_values_to_settings` / `values_from_settings` read
  and write the promoted paths directly; `apply_control_values_to_settings`
  applies a full map (God + agents + promoted) to a live `Settings`.
  `apply_agents_patch` moved out of the router into `god/controls.py`.
- **Overlay `data/panel.toml`** (`panel_store.py`): `POST /v1/config/god` with
  `persist=true` validates and writes overrides (nested `[section] key = value`,
  tiny dependency-free TOML serializer); `load_settings` deep-merges them over
  `config.toml` for ControlSpec-known paths only. It **never** touches the
  user's `config.toml`. `POST /v1/config/panel/reset` deletes the overlay.
  `restart_only` specs are never persisted or shown (`controls_payload`).
- i18n: `god.control.*` label/desc keys (en + pt-BR) for every promoted spec.
- Tests: sidecar **437** (new `test_controls_panel.py`: spec targets, mapping,
  overlay round-trip/serializer, `load_settings` precedence, persist/reset
  endpoints).

### Changed â€” HUD, dialogue language, social context & audience (build `2026-09-29.20`)
Live feedback pass:
- **HUD is quiet**: the periodic status line and per-intent traces are now
  **log-only** (`[validate] hud: â€¦`); only sidecar **state flips**
  (connected/lost/error) raise a notification. `sw.hud now` still surfaces the line.
- **Language**: the dialogue/chat LLM prompt names the target language
  ("Brazilian Portuguese (pt-BR)") and forbids English when `lang != en`; the mod's
  `state_collector._current_lang()` retries game-locale detection.
- **Richer Sim context in dialogues**: `social.sim_brief(...)` adds each Sim's
  **background, personality, recent memories and conversation partner** (and
  `sim_id`) to the prompt.
- **Audience**: `SocialLayer.pick_pairs` now **prefers household Sims**
  (householdâ†”household / householdâ†”guest) instead of only non-player visitors, so
  the player's household is involved rather than two passers-by.
- **Speaker attribution**: speech notifications are prefixed with the speaker's
  name and owned by that Sim (native portrait).
- **New `mod/sensewright_mod/dialogs.py`** (native text input + confirmation);
  the pie "Chatâ€¦" sends the typed line via the new `main.run_chat(...)`.
- Tests: sidecar **412**, mod **325** (`test_social.py` covers `sim_brief`, the
  household pairing and the pt-BR prompt enforcement; `test_social_integration.py`
  the household pair; `test_hud.py` the log-only HUD).

### Added â€” pie menu works (XmlInjector) + real chat/confirm dialogs (build `2026-09-29.19`)
The pie-menu items now appear in-game. Two findings from live debugging:
- A bare `interaction` tuning is **not offered**; it must be injected. We adopted
  the community-standard **XmlInjector** library and ship a snippet
  (`mod/tuning/snippets/sw_injector.xml`, type `0x7DF2169C`,
  `add_interactions_to_sims`) that wires our interactions into the Sim pie menu.
  (`mod/build_package.py` now packs snippet resources; the XmlInjector v4.2
  script is installed to the Mods root.)
- **Localized names**: the STBL language is the **top byte of the instance**
  (`0x00` ENG_US, `0x11` POR_BR); the package ships **both** string tables, and
  the blank-name problem is gone.
- New **`mod/sensewright_mod/dialogs.py`**: native **text-input** and
  **confirmation** helpers. The pie "Chatâ€¦" now opens a real **text** field (it
  was opening the numeric input spike) and sends the turn via the new
  `main.run_chat(...)` (also used by `sw.chat`); "Confirmâ€¦" opens a real Ok/Cancel.
- Tests: mod **325**.

### Changed â€” pie-menu diagnostics + header/XML alignment (build `2026-09-29.14`)
Still no items after `.13`; this pass adds observability and mirrors the working
reference more closely:
- **`pie_menu.py`** logs `[pie_menu] module imported â€¦` at import and
  `[pie_menu] dispatch â€¦` on use, so `sensewright_output.log` tells us whether the
  tuning package loaded at all.
- **`build_package.py`** now writes `0` in the header's `0x28` field (matching
  S4S-built packages; the real index offset is the 64-bit value at `0x40`).
- **interaction XML** now includes the `_icon` participant and `test_globals`
  (mirroring the TS4ControlAnySim template) so the base interaction test has what
  it expects on a Sim target.

### Fixed â€” pie menu didn't appear + autonomy alarm crashes (build `2026-09-29.13`)
First live test: no items showed. Root cause found by comparing our `.package`
with a working S4S-built one (ControlAnySim): TS4 stores tuning as **zlib-
compressed XML**, not raw XML. Our resources were uncompressed and used the
"uncompressed" flag, so the game ignored them.
- **`mod/build_package.py`**: tuning XML resources are now `zlib.compress(..., 9)`
  with index `sf = 0x80000000 | compressed_size`, `size = uncompressed_size`,
  flag `0x00015A42` (verified by decompressing our package back to XML).
- **`state_collector.py`**: alarm callbacks took no argument but the game passes
  one (`_on_autonomy_alarm() takes 1 positional argument but 2 were given`, seen
  in `lastException.txt`). `_on_snapshot_alarm`/`_on_autonomy_alarm`/
  `_on_directive_alarm` now accept `*args, **kwargs` â€” the game-clock alarms now
  run instead of throwing every tick.

### Added â€” pie-menu spike, phase 1 (build `2026-09-29.12`)
First pie-menu ("interaction menu") entry point, so the panel can later be opened
from the Sim/computer instead of only cheats. **Phase 1 deliberately reuses an
existing EA category** (`pieMenuCategory_Actions`, id `129388`) to validate the
pipeline before a custom category/SimData is added.
- **`mod/sensewright_mod/pie_menu.py`**: `ImmediateSuperInteraction` subclasses
  (`SensewrightPanelInteraction`, `â€¦Chatâ€¦`, `â€¦Confirmâ€¦`, `â€¦Hudâ€¦`) that dispatch to
  the existing native dialogs (`panel`, `input`, `okcancel`, `hud`) â€” i.e. menu â†’
  input/confirmation/toggle.
- **Tuning** `mod/tuning/interactions/*.xml` (4 interactions; minimal
  `ImmediateSuperInteraction` template, display names + EA pie-menu icon).
- **`mod/build_package.py`**: pure-Python DBPF writer (no S4S/FFDec) that packs
  the interaction XML + an English STBL into `dist/Sensewright.package`. DBPF/STBL
  formats reimplemented from the TS4 package format (studied the MIT ShadySimDeals
  `build_mod.py` and Apache-2.0 TS4ControlAnySim tuning).
- **`scripts/install-mod.ps1`** now copies `dist/Sensewright.package`; `Makefile`
  gains `build-package`.
- Tests: **mod 324** (`test_pie_menu.py`: interaction classes + package builder).
- Phase 2 (next): a custom `Sensewright` `PieMenuCategory` (category XML + SimData)
  with subcategories, STBL pt-BR, and moving the entry to the computer for God.

### Added â€” navigable panel mock (`sw.uitest panel`) (build `2026-09-29.11`)
A preview of the real P2 panel, using the **best native widget per setting kind**:
- **`panel`** â€” home = section list (object-icon picker) â†’ section page = settings
  list with icons, labels and current values â†’ **control per kind**: `slider` â†’
  stepped choices, `select` â†’ **dropdown**, `toggle` â†’ On/Off rows, `tags` â†’
  multi-select, `number` â†’ numeric input. Applying logs `[validate] panel: key=val`
  (P2 will apply + persist via `sw.set`).
- **`panel_home`** â€” the same home as a `UiDialogLabeledIcons` grid (icon per
  section), the candidate home skin.
- Self-contained mock inventory (`_PANEL_SECTIONS`: God / Agents / Powers) using
  the existing `god.control.*` labels; P2 will fetch the real `ControlSpec`s from
  the sidecar.
- `sw.uitest all` now runs **13** kinds. Tests: **mod 317** (`_format_value`,
  panel inventory).

### Added â€” more native dialog styles in the spike (build `2026-09-29.10`)
Explored additional native dialog families for the panel:
- **`dropdown`** (`UiDropdownPicker`) â€” a native dropdown for single-choice
  settings (built like the object picker; rows become the options).
- **`labeled_icons`** (`UiDialogLabeledIcons`, `labeled_icons` = list of
  ``(icon, label)``) â€” an icon-grid dialog; the candidate **panel home** (one icon
  per section), decorated with the EA icon pool.
- **`info_columns`** (`UiDialogInfoInColumns`, `column_headers`) â€” a read-only
  column table for status/roster pages.
- `sw.uitest all` now runs **11** kinds; `UiMultiPicker`/`UiItemPicker` were
  skipped (they need specialised picker/row models).

### Validated live â€” P0 native-dialog spike (build `2026-09-29.9`)
`sw.uitest all` now renders **all 8 kinds** in-game (`ok=True`): notification,
okcancel, picker, picker_icons, picker_text, response (the `SEND_COMMAND` button
runs `sw.uitest clicked`), input (numeric) and multi (selection captured, e.g.
`picked ['sitcom','drama','caos']`). `picker_icons` gathered **16 EA icon keys**
(from object definitions) and decorated the rows; `picker_text` is intentionally
image-less (plain text list, for comparison); `picker` selection logged
(`picked ['14']`). P0 is closed â€” next is **P1** (sidecar `ControlSpec` model +
`panel.toml` persistence).

### Added â€” P0 native-dialog spike (`sw.uitest` kinds)
Shipped the in-game spike that validates TS4's native dialog family before P2
builds the configuration panel (`docs/ui_panel.md` Â§6, item P0). Build
`2026-09-29.3`.
- **New `mod/sensewright_mod/ui_probe.py`**: probes `notification`, `okcancel`,
  `picker` (24 rows â†’ automatic pagination), `response` (a button that runs
  `sw.uitest clicked` via `SEND_COMMAND`), `input` (`UiDialogTextInputOk`) and
  `multi` (picker with `max_selectable > 1`). Each returns `{kind, ok, layer,
  error}`, logs `[validate] uitest â€¦` + a `[uitest]` debug line and never raises
  (lazy, guarded game imports).
- **`inspect()` / `format_report()`** report which dialog classes/modules exist
  without showing UI, so the spike still yields data when a dialog cannot render.
- **`sw.uitest`** extended: bare (notification, back-compat), `<kind>`, `all`,
  `probe` (class report) and the internal `clicked` used by the SEND_COMMAND
  button to prove the round-trip end to end.
- APIs confirmed from the shipped `simulation.zip` bytecode and the cloned
  references (`UiDialogObjectPicker`/`UiObjectPicker`/`UiSimPicker`,
  `UiDialogOkCancel`, `UiDialogTextInputOk` + `UiTextInput`,
  `UiDialogNotification(ui_responses=â€¦)`, `UiDialogResponse` with
  `UiDialogUiRequest.SEND_COMMAND`).
- i18n: new `cmd.uitest.*` keys in `en` + `pt-BR`; `cmd.help.body` lists
  `sw.uitest`.
- Tests: **mod 313** (+8 in `test_ui_probe.py`); `py -3.7 mod/build.py` clean.
  Pending: run `sw.uitest all` / `sw.uitest probe` in the live client to fix the
  P2 widget matrix.

### Fixed â€” P0 spike, first live run (build `2026-09-29.4`)
First in-game run of `sw.uitest all` (notification/okcancel/picker/multi rendered;
response + input failed) produced three fixes:
- **`response`**: the `UiDialogResponse` button text must be a *factory* (the
  dialog calls it with tokens), not a bare `LocalizedString` â€” this raised
  `'LocalizedString' object is not callable` in `show_dialog`. Confirmed against
  `research/ui-refs/core-library/snippets/mod_manifest.py` (`button_text` is a
  `TunableLocalizedStringFactory`).
- **`input`**: `UiTextInput.min_length` is a read-only property on this patch
  (`can't set attribute`); stopped assigning it, guarded `max_length`/bounds, and
  set `restricted_characters` to the numeric character set.
- **`picker`**: `ObjectPickerRow.name`/`row_description` are passed as factories,
  and rows now show real settings labels. Added a **`picker_text`** variant
  (`ObjectPickerType.OBJECT_TEXT`) so the object/thumbnail skin can be compared
  with a plain text-list skin for the P2 panel.

### Fixed â€” P0 spike, second live run (build `2026-09-29.5`)
Corrected three wrong assumptions from `.4` (the first run's fixes regressed
pickers and left two kinds failing):
- **Picker rows** need a `LocalizedString`, **not** a factory: `.4`'s factory
  broke `picker`/`picker_text`/`multi` with `value has type function, but expected
  LocalizedString`. Reverted to `LocalizationHelperTuning.get_raw_text`.
- **`restricted_characters`** on `UiTextInput` is called by the dialog, so it
  must be a factory (like lot51's `CharacterRestriction.NUMBERS`); passing a bare
  `LocalizedString` raised `'LocalizedString' object is not callable`.
- **`response_command`** must be the game's command/argument namedtuples (the
  dialog reads `.command` and each arg's `.arg_type`/`.arg_value`), with
  `CommandArgType.ARG_TYPE_STRING` â€” a plain tuple raised `'tuple' object has no
  attribute 'command'`. Confirmed against
  `research/ui-refs/core-library/snippets/mod_manifest.py` + `utils/dialog.py`.
- Net API map: dialog **title/text/text_ok** = factories; picker **row
  name/description** and input **restricted_characters** = factories; dialog
  **response text** = factory; **response_command** = namedtuple(command, args).
  Re-run `sw.uitest all` to confirm all 7 kinds render.

### Changed â€” P0 spike, third live run (build `2026-09-29.6`)
Six of seven kinds now render; the picker skin needed options and the input
needed its length restriction:
- **`input`**: `UiDialogTextInputOk` reads `UiTextInput.length_restriction`, so
  the probe now builds one (a minimal `build_msg` object; base factories when
  importable) â€” fixes `'UiTextInput' object has no attribute 'length_restriction'`.
- **Picker cleanup**: the probe now sets `use_dropdown_filter=False`,
  `hide_row_description=True`, `is_sortable=False`, `bubble_up_selected=False`
  (best-effort) for a plain list look.
- **Added `items`** kind (`UiItemPicker`) so the object/thumbnail skin, the
  `OBJECT_TEXT` skin and the item-list skin can be compared side by side for the
  P2 panel. `sw.uitest all` now runs **8** kinds.

### Changed â€” P0 spike: EA icons + layout (build `2026-09-29.8`)
Live feedback: the picker skin is best, but the missing per-row images look bad
and long text overflows.
- **Icons**: confirmed from the shipped bytecode that `BasePickerRow` stores
  `icon`/`icon_info` and that `icon` must be a `ResourceKey` (it reads
  `.type/.group/.instance` and builds `IconInfoData(icon_resource=â€¦)`). Added the
  **`picker_icons`** kind, which decorates the settings rows with real EA icons
  gathered from object definitions (primary), the Sim's mood and traits; rows
  cycle the collected keys. **No `.package` needed** for this spike.
- **Long text**: row labels stay short and the explanation moved to `row_tooltip`
  (hover); `hide_row_description=True` keeps rows compact. (TS4 renders **DDS**
  textures, not SVG â€” custom art would need an SVGâ†’DDSâ†’DBPF pipeline; see
  `docs/ui_panel.md`.)
- **Dropped `items`**: `UiItemPicker` uses `PickerBaseRowData`, not
  `ObjectPickerRow` (`'PickerBaseRowData' object has no attribute 'base_data'`),
  so it is not a general list widget.
- Tests: **mod 315** (`_is_resource_key`, `_icon_pool`); `py -3.7 mod/build.py`
  clean.

### Fixed â€” picker row tooltip must be a factory (build `2026-09-29.9`)
The `.8` icon pass collected **16 EA icon keys** (object definitions), but every
picker then failed with `'LocalizedString' object is not callable`. Cause: the
shipped `BasePickerRow.populate_protocol_buffer` **calls** `row_tooltip`
(`CALL_METHOD 0`) while it stores `name` and `row_description` as-is â€” so
`row_tooltip` must be a factory. Non-empty tooltips hit the bug; the earlier
empty tooltips had skipped that branch. Fixed (`row_tooltip=_factory(...)`), so
`picker`, `picker_icons` and `picker_text` should render again â€” this time with
icons. Refined API map: **row name/description** = LocalizedString;
**row tooltip** = factory; **row icon** = `ResourceKey`.

### Changed â€” in-game configuration panel plan: native dialogs, no Flash (docs)
Settled the settings-UI direction after a research pass (reference mods cloned
into the gitignored `research/ui-refs/`). The panel lives **inside the game** and
uses **TS4's native dialogs only** â€” picker/list rows, paginated responses,
numeric input and multi-select (the S4CL pattern, **reimplemented** in our own
module). **No Flash/GFX and no drag sliders** (not scriptable in TS4); a 0..1
value renders as a row of stepped choices or a numeric input. Entry =
boot-notification button + `sw.panel` cheat (pie-menu category optional later).
Persistence = a `data/panel.toml` overlay written by `POST /v1/config/god?persist`,
keeping the user's `config.toml` untouched.
- **`docs/ui_panel.md`** rewritten: full settings inventory (God, agents, per-Sim,
  plus the previously unexposed `llm`/`memory`/`personality`/`evolution`/`social`/
  `backgrounds`/`runtime` settings to be promoted into `ControlSpec`), the native
  widget matrix, the `panel.toml` overlay, and the P0â€“P3 roadmap.
- **`PLANO.md`** Â§8/Â§11/Â§15 updated: the panel is **no longer gated on Flash**
  (native dialogs; R7 marked "dialogs done, panel specified").
- **`docs/STATUS.md`**: added Â§2b (panel decision) and refreshed the build
  stamp / git facts.
- No code change yet; **P1** (model + persistence) and **P2** (native panel) are next.

### Changed â€” renamed the project to **Sensewright** (build `2026-09-29.2`)
Full rename from `SimsSense` to **Sensewright** (descriptive subtitle: *for The Sims 4*;
no "Sims" in technical identifiers). A git baseline was committed **before** the rename so
it stays revertible.
- **Packages:** `mod/simssense_mod` â†’ `mod/sensewright_mod`; `sidecar/sims_sense_sidecar` â†’
  `sidecar/sensewright_sidecar` (incl. `pyproject` `name`, console script and wheel package).
- **Cheats (breaking):** every `ai.*` â†’ **`sw.*`** (`sw.help`, `sw.chat`, `sw.hey`, `sw.status`,
  `sw.reset`, `sw.forget`, `sw.autonomy`, `sw.lang`, `sw.hud`, `sw.uitest`, `sw.god`,
  `sw.zeitgeist`, `sw.profile`, `sw.evolve`, `sw.agents`, `sw.probe`, `sw.start`), including the
  `cmd.help.body` text in `en` + `pt-BR`.
- **Wire/security:** auth header `X-SimsSense-Token` â†’ `X-Sensewright-Token`; env vars
  `SIMS_SENSE_*` â†’ `SENSEWRIGHT_*` (`HOME`, `CONFIG`, `LANG`, `DEBUG`, `VALIDATION`,
  `GAME_PID`, `PYTHON`, `TS4_STUBS`).
- **Artifacts/paths:** `Sensewright.ts4script`, `Sensewright-sidecar.exe`,
  `Mods\Sensewright\`, `sensewright.toml`, `sensewright_output.log`, sidecar window/log titles.
- **Docs/scripts:** `PLANO.md`, `CHANGELOG.md`, `docs/*`, `SKILL.md`, `Makefile`,
  `scripts/*.ps1`, `config.example.toml` updated.
- **Repo:** `git init` + baseline commit; remote `https://github.com/MaiconSlavieiro/sensewright`.
- **Installer:** `scripts/install-mod.ps1` now preserves `sidecar\config.toml` (model/API keys)
  and `sidecar\data\` (memory DB / shared token) â€” never overwritten by the source copy on a
  re-install, migrated from a legacy `Mods\SimsSense` install when present â€” and gained a
  `-RemoveLegacy` switch to delete the old folder after installing.
- Note: installs now land in `Mods\Sensewright\` â€” delete the old `Mods\SimsSense\` folder so
  the game does not load both.
- **Tests:** sidecar **406**, mod **305**; ruff + `py -3.7 mod/build.py` clean.

### Changed â€” code-review remediation + R1 hardening (build `2026-09-29.1`)
Applied the full correction plan from `docs/code_review_2026-09-27.md` on the in-game mod
(sidecar unchanged), plus defensive hardening of the R1 native levers and a shared
best-effort guard.

**Security / correctness**
- **C1 (critical) â€” the player-priority lock is now armed.** Every player-issued `ai.*`
  command calls the new `tool_executor.record_player_activity()` (via
  `main._note_player_active`), so `DirectiveRails` actually blocks agent intents on the
  player's Sim for the lock window (previously it was only ever exercised by tests). The
  lock stays **per-Sim** by design â€” the agent may still act on other seated Sims.
- **H6 â€” strict tool-argument types.** `tool_executor` coerces ids via `_as_int`
  (`int` / numeric `str` / integral `float`; `bool` and non-numeric â†’ `invalid_argument`)
  and requires a real `tone` `str`, so a malformed payload is reported instead of silently
  falling back to a default.

**Robustness / observability**
- **H5 â€” one shared guard.** `debug_log.safe_getattr`/`safe_call` (both log the real
  exception once) replace the duplicate non-logging copies in `events.py`, `god_ui.py` and
  `tool_executor.py` (module aliases kept for compatibility).
- **H1â€“H4 â€” no more silent swallows.** Event/alarm registration (`events`), the collector's
  HTTP sends (`_send`, `send_autonomy_tick`, `_pull_intents`, `send_census`,
  `notify_player_activity`) and the UI/config/probe paths now `log_exception`/`debug_log`
  instead of `pass`.
- **M3 â€” the alarm owner must be a live, ticking Sim instance.** `events._resolve_alarm_owner`
  no longer falls back to zone/household/client (which registered handles that never fired);
  it returns `None` and the `zone.Zone.update` hook re-arms. `_ensure_alarm` now logs when an
  alarm is deferred.
- **M4 â€” every `add_alarm` attempt is logged** (was only the last one).
- **M5 â€” sleep detection uses the exact tuning id only** (`buff_type.__name__`), never a
  localized display name.
- **M1/M2 â€” `health()` no longer sends the auth header** (`_make_request(no_auth=True)`), and
  `json.dumps` now runs inside the request `try` so a serialization error cannot escape before
  handling.

**UI / i18n**
- **M6 â€” hardcoded UI strings localized:** `god.zeitgeist.hint`, `god.background.hint`,
  `notify.app_title`, `error.title` (en + pt-BR). **M7** the HUD passes canonical
  `ON`/`OFF`/`ERROR` tokens to `hud.line`. **M8** `i18n.t` is robust to non-string
  placeholders (`AttributeError` + `str()` coercion).

**R1 (native levers, best-effort)**
- `_build_interaction_context` tries multiple real import paths/signatures
  (`interactions.context` / `sims4.interactions.context`; `(source, priority)`,
  `(source, source_priority, run_priority)`, `(source,)`) and never raises; `tool_say_to`
  tries the tone-mapped name and candidate base-game social affordances. Still needs live
  validation before `say_to` can push natively in-game.

**LOW**
- Removed the dead `StateCollector._register_handlers`; `rails.NEVER_TOOLS` no longer lists
  the non-existent `shell`/`http`; `note_executed` failures are logged; `probe` renders via
  the payload sanitizer (no `default=str` masking); `print` â†’ `debug_log`; `cmd_zeitgeist
  auto` forwards `lang`; `sw.autonomy` persists the level to `sensewright.toml` and, with no
  argument, re-applies it (`read_autonomy_level`); the sidecar already persists the
  per-Sim level in SQLite.
- **Deferred (documented):** M9 (split the 1.5k-line `state_collector`), L10 (harden the
  hand-rolled TOML parser), L3 (duplicate Sim-ref helpers).

**Tests.** mod 241 â†’ **305** (C1 wiring, H6 coercion/validation, H1â€“H3 logging, M3
alarm-owner, M4 attempts, M5 exact tuning id, M6/M7/M8 i18n, H5 shared-guard identity, R1
import paths, `write_autonomy_level`); sidecar **406** unchanged. ruff + `py -3.7
mod/build.py` clean. Build `2026-09-29.1`.

### Added â€” v0.3 R5: simâ†”sim dialogue channel + R6/R7 status (build `.18`)
Two seated, non-player agent Sims now hold a short (1â€“2 line) conversation. The
exchange reaches the game through the normal intent pull (each line is a
`speak`/`say_to` intent) and is remembered by both Sims, so the relationship
keeps moving natively when the social affordance resolves (notification fallback
otherwise, per the locked decision Â§15.1 #5).
- **Sidecar â€” `agent/social.py` (`SocialLayer`, `Dialogue`).** Picks disjoint
  pairs of awake, seated, **non-player** Sims (per-pair cooldown, `max_pairs`
  per pulse), builds a `PairContext` (both profiles + relationship hint) and
  renders the dialogue with the LLM or a deterministic `template_dialogue`
  fallback. `Dialogue.intents()` yields one `speak` intent per line
  (`say_to`-compatible: `params.message` for the native push, `params.text` for
  the notification fallback).
- **Sidecar â€” agency/graph.** `Agency` owns the `SocialLayer`
  (`set_context_forge`), plans dialogues inside `ingest_tick` (returned as
  `social` + `social_intents`) and exposes it in `snapshot()`;
  `graph._store_social` passes the intents through the rails, stores them on the
  IntentBus and writes a `social` memory event for both participants.
- **Wire/config.** `AutonomyTickResponse.social` (`SocialDialogue`/`SocialLine`);
  new `[agents.social]` (`max_pairs_per_tick`, `pair_cooldown_seconds`,
  `line_max_tokens`); the `[agents.layers] social` toggle already existed and now
  actually gates the layer.
- **Mod.** The zone pulse logs `[validate] social: N dialogue pair(s)`; the
  resulting `speak` intents flow through the existing GameLever (`say_to`, with a
  `notify.social.speech` fallback). No new locale keys were needed.
- **R6/R7 (verified code-complete).** The God orchestrator already targets only
  non-player Sims and broadcasts world events to witnesses; the agent-roster
  panel is the `sw.agents` text fallback plus the `ControlSpec` dials and
  `sw.lang`. Only the optional native visual panel remains gated.
- **Data-quality nits (mod).** `sw.probe` now reports a real `full_name` and a
  career name (was `""` / numeric); `get_inventory` is implemented best-effort
  instead of returning `not_implemented`.
- **Tests.** sidecar 356 â†’ **406** (`agent/social.py` unit tests + Agency/graph
  integration); mod 225 â†’ **241** (`full_name`/career-name/inventory). ruff clean;
  `py -3.7 mod/build.py` produces the `.ts4script`.

### Fixed/Added â€” reasoning handling + per-agent reasoning effort (build `.17`)
Root cause (confirmed by a live OpenRouter probe, outside the game): the free
Nemotron chain is a reasoning model. With the default effort it spent ~580 hidden
reasoning tokens per impulse, hit `finish_reason=length`, and **dumped its
"thinking process" into `content`** â€” which the impulse parser discarded, so every
impulse fell back (`used_llm=False`, no intents). With `reasoning.effort="none"`
the chain returns `reasoning_tokens=0` and a clean line or tool call.
- **Config.** New `[llm] reasoning_effort` (default **none**: none|minimal|low|
  medium|high) and a per-agent `[agents.initiative] reasoning_effort` override
  (None inherits). New `ProviderConfig.supports_reasoning` gates forwarding (so a
  provider that would 400 is untouched).
- **LLM layer.** `complete()` accepts `reasoning_effort` through
  `LLMProvider`/`ProviderChain`/`ProviderRegistry`; the OpenAI-compatible provider
  forwards `reasoning.effort` per request; Gemini accepts and ignores it (its
  thinking is already disabled).
- **Impulse.** `build_impulse` retries once when a response yields no usable
  line/tool call (reasoning-trace or empty), and forwards the configured effort.
- **God control.** New `reasoning_effort` select in the `ControlSpec` registry
  (`GET /v1/god/controls`, `POST /v1/config/god`); maps to
  `settings.agents.initiative.reasoning_effort`.
- **Prompt/cleanup (earlier pass).** `_clean_thought` strips a leading
  "Here's a thought:" prefix and drops reasoning-trace/meta content (en + pt-BR);
  `IMPULSE_MAX_TOKENS` 250 â†’ 600; the impulse prompt forbids preamble/headings.
- Verified live: `build_impulse` now returns `used_llm=True` with an in-character
  pt-BR line.
- **Tests.** sidecar 341 â†’ **356**; mod **225**; ruff + compileall clean.

### Fixed â€” autoboot ignored `python.txt` because of a UTF-8 BOM (build `.16`)
The spawn log showed `spawning sidecar: ['...\Python310\python.EXE', â€¦]` â€” i.e.
the mod fell back to the PATH Python (no deps), so the sidecar never started and
the HUD stayed `DESLIGADO`. Root cause: `install-mod.ps1` wrote `sidecar/python.txt`
with `Set-Content -Encoding UTF8`, which prepends a UTF-8 **BOM** on PowerShell
5.1; `read_interpreter_hint` read the line as `"\ufeffC:\â€¦"`, the existence check
failed, and the hint was discarded.
- `read_interpreter_hint` now reads with `utf-8-sig` (strips a BOM) **and**
  `lstrip("\ufeff")`.
- `install-mod.ps1` writes the hint with .NET `UTF8Encoding($false)` (no BOM).
- **Tests.** mod 224 â†’ **225** (BOM stripping).
- Verified end-to-end: the venv interpreter starts the sidecar from the installed
  folder and `GET /v1/health` returns 200.

### Changed â€” review/adviser follow-through (build `.15`)
- **Mod â€” removed `from __future__ import annotations` everywhere.** Applied the
  skill's hard rule across all 13 mod modules (`__init__`, `config`, `chat_ui`,
  `state_collector`, `tool_executor`, â€¦). Harmless before (only `main.py` defines
  commands) but a landmine; a regression test now fails if it returns
  (`mod/tests/test_python37_compat.py`).
- **Mod â€” HUD tri-state.** `hud` now distinguishes **on / off / error**; when the
  tick and pull both fail, `pulse_and_pull` probes `/v1/health` so a reachable
  sidecar with a failing endpoint shows `âš  sidecar ERROR` instead of a false
  "OFF". New `hud.line.error`/`hud.sidecar.*`/`hud.error` keys in `en` + `pt-BR`.
- **Sidecar â€” port-conflict guard (`__main__._port_in_use`).** A second sidecar
  on the same port now logs and exits cleanly instead of an opaque uvicorn bind
  crash (the mod always reuses the instance already up).
- **Mod â€” observability.** `_post_tool_result` logs a debug line when a result
  cannot be posted (sidecar unreachable); `_push_affordance` logs when the
  interaction context could not be built.
- **Tests.** sidecar 339 â†’ **341** (`_port_in_use`); mod 218 â†’ **224** (future-
  import guard, HUD tri-state, `_sidecar_state`).

### Changed â€” review/adviser pass (build `.14`)
A code review + architecture advisory pass on this session's changes. Applied:
- **No more silent swallows (mod).** `StateCollector._emit` now logs event-send
  failures (`log_exception`), and `pulse_and_pull` logs a failing
  `hud.note_heartbeat` instead of a bare `except: pass` â€” so the validation log
  always shows why a pulse/event produced nothing.
- **Spawn visibility (mod).** `main._spawn_sidecar` logs
  `spawning sidecar: <cmd> (cwd=â€¦, game_pid=â€¦)` so `sensewright_output.log` records
  exactly what was launched and with which PID.
- **Impulse marker robustness (sidecar).** `_META_MARKERS` covers `I am Sim â€¦`
  with `,`/`.`/space endings (kept the trailing space to avoid matching
  "I am simplyâ€¦").
- **Tests unchanged:** sidecar **339**, mod **218**; ruff + compileall clean.
- **Advisory (not blockers, tracked):** `from __future__ import annotations` is
  present across the mod modules (pre-existing; harmless because only `main.py`
  defines `@sims4.commands.Command`, but it violates the skill's blanket rule â€”
  candidate for a dedicated cleanup); HUD treats any tick/pull `None` as "sidecar
  down" (could be a transient error); watchdog has no PID-reuse/process-name
  verification; no port-conflict retry.

### Fixed â€” sidecar watchdog no longer kills itself on the protected game (sidecar)
The HUD logged `sidecar DESLIGADO` because the sidecar started and then shut
itself down ~6 s later with `game process gone` â€” while the game was running.
Root cause: `_windows_pid_alive` treated any `OpenProcess` failure as "process
dead". The Sims 4 is DRM-protected, so `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`
returns **ERROR_ACCESS_DENIED (5)** even though the game is alive, so the
watchdog false-triggered on every session.
- `_windows_pid_alive` now reads `GetLastError`: only **ERROR_INVALID_PARAMETER
  (87)** (no such PID) counts as dead; access-denied/unknown counts as alive
  (never kill on doubt). `GetExitCodeProcess` failure likewise counts as alive.
- Startup now logs `game watchdog armed: pid=â€¦ watch_name=â€¦ name=â€¦` so the
  watched PID is visible in `sidecar.log`.
- **Tests.** sidecar 338 â†’ **339** (access-denied counts as alive).

### Fixed â€” notifications now render (LocalizedString factory) (build `.13`)
`sw.uitest` pinpointed the failure: `TypeError: 'LocalizedString' object is not
callable` at `ui_dialog._build_localized_string_msg` (`string(*tokens)`). The
dialog resolves `text`/`title` by **calling** them with localization tokens, but
`LocalizationHelperTuning.get_raw_text(...)` returns a `LocalizedString`, not a
callable. `chat_ui._build_dialog` now passes small factories
(`lambda *a, **k: loc`) so the dialog can call them. This is the real cause of
"no UI appears" for the HUD, `notify.*` and `notify.social.speech`.
- The earlier `sw.hud on` console-only result was this fallback; the HUD loop
  itself was already running (`hud: â€¦ HB #3 â€¦ 6 sims` in the log).
- **Tests.** mod **218** (unchanged; diagnostics test covers the failure path).

### Added â€” notification diagnostics + HUD log trace (build `.12`)
`sw.hud on` still showed only the console ack, so the in-game UI path needs
pinpointing.
- **`sw.uitest` cheat.** New `chat_ui.notification_diagnostics()` reports the
  exact failing layer of the dialog path (`build` vs `show_dialog`) and the error
  string; `sw.uitest` prints `ok=â€¦ | layer=â€¦ | error=â€¦` to the cheat console.
  `show_notification` now logs the real exception to `sensewright_output.log`.
- **HUD log trace.** Every HUD line is mirrored to the log as `hud: â€¦`, so the
  loop's liveness is provable from `sensewright_output.log` even if notifications
  do not render.
- **Tests.** mod 217 â†’ **218** (`notification_diagnostics`).

### Fixed â€” sidecar autoboot finds its interpreter (build `.11`)
The sidecar is supposed to start by itself (`main.autoboot()` â†’ `find_python()`),
but on the dev machine it silently spawned the PATH Python 3.10, which has none
of the sidecar deps (`fastapi`/`httpx`/`pydantic`) â€” those live in the workspace
`.venv`. So the sidecar never came up unless started by hand.
- **`install-mod.ps1` records the interpreter.** After copying, it resolves the
  dev venv (`sidecar\.venv\Scripts\python.exe`, else PATH `python`) and writes
  it to `Mods/Sensewright/sidecar/python.txt`.
- **`config.find_python()` reads it.** New `read_interpreter_hint()` is consulted
  after the env override and the sidecar's own `.venv`, before PATH â€” so autoboot
  spawns an interpreter that actually has the deps. Missing/stale paths are
  ignored (falls through to PATH).
- **Tests.** mod 214 â†’ **217** (`read_interpreter_hint`, `find_python` hint).

### Added â€” in-game debug HUD (`sw.hud`) + working notifications (build `.10`)
- **Debug HUD (`mod/sensewright_mod/hud.py`).** The mod runs behind the scenes, so
  a player could not tell whether the loop was alive. New opt-in overlay:
  `sw.hud on|off|now|status` (empty toggles). While on, each zone heartbeat emits
  a compact notification â€” `sidecar ON/OFF | HB #n | N sims | pulled n | ok n/total`
  â€” and every executed intent adds a one-line trace (`â–¶ kind name â†’ status`);
  sidecar connect/loss flips announce immediately. Counters keep running while
  off, so `sw.hud now` shows a reading at any time. New `cmd.hud.*`/`hud.*` keys in
  `en` + `pt-BR`; `sw.hud` added to `sw.help`.
- **Fixed â€” notifications now actually render in-game (`chat_ui.show_notification`).**
  The dialog call passed `urgent=` (not a notification tunable) and wrapped the
  text in `TunableLocalizedStringFactory` (a tunable type, not a runtime string),
  so `UiDialogNotification` raised and every message silently fell back to the
  cheat console (invisible unless the console was open). It now builds real
  localized strings with `LocalizationHelperTuning.get_raw_text(...)` (confirmed
  against the shipped `sims4/localization`), resolves the owner (live Sim â†’
  SimInfo â†’ active client) and calls
  `UiDialogNotification.TunableFactory().default(owner, title=â€¦, text=â€¦)`. This
  makes the HUD, the `notify.*` messages and `notify.social.speech` visible.
- **Wired through the heartbeat (`state_collector`).** New `pulse_and_pull()` runs
  the pulse + intent pull once and feeds `hud.note_heartbeat`; both the zone hook
  and the event safety net call it. `pull_and_execute_directives` feeds
  `hud.note_intent`, and `send_autonomy_tick` records the last pulse size.
- **Docs.** `docs/ts4_internals.md` records the validated notification API.
- **Tests.** mod 203 â†’ **214** (`test_hud.py`, `test_chat_ui.py`).

### Validated â€” build `2026-09-27.8` live (zone heartbeat + R2/R3)
The `.8` session validated the core loop during **normal play, with no commands**:
- **Zone heartbeat (the #1 board item)** â€” `install_zone_hook` started only after
  the active Sim was instanced, giving `owner=object_sim` and a non-empty census:
  `[validate] census: 12 sim(s), 9 household(s) scope=active_zone`,
  `[validate] zone-pulse: heartbeat` every ~15 s (26 beats),
  `[validate] pulse: N sim(s) zone=1488584711`, and the sidecar logging
  `POST /v1/autonomy/tick` + `GET /v1/autonomy/intents` 200 at the same cadence.
- **Seats/eviction (R2)** â€” `seats: 12, used: â€¦, household: 5, visitors: â€¦` with
  `evicted: [â€¦]` as Sims left the lot.
- **Intents (R3)** â€” sidecar `impulse â€¦ intents=['speak']` â†’ `intent(s) stored`
  â†’ mod `pull: 1 intent(s)` â†’ `intent â€¦ kind=speak name=spontaneous_line -> ok=True`.
- **LLM** â€” OpenRouter 200 across impulses.
Found while validating (fixed below): targeted `say_to` intents failed with
`not_implemented`, and weak prompt framing produced meta/empty impulse thoughts.

### Fixed â€” speak intents never drop silently + impulse thought quality (build `.9`)
- **Mod â€” `speak` lever fallback (`tool_executor.py`).** A targeted `speak`
  intent (`say_to`) that cannot be pushed natively now degrades to a surfaced
  `spontaneous_line` notification (`audience` = target id, `native_error`
  recorded) instead of returning `not_implemented` and vanishing.
- **Mod â€” native push context (`tool_executor._push_affordance`).** Now prefers
  the validated `sim.push_super_affordance(affordance, target, context)` entry
  point and builds a real `InteractionContext(SOURCE_SCRIPT, High)` (passing
  `None` made the push fail); the interaction-queue methods remain a fallback.
- **Mod â€” `bias_interaction` acknowledgement.** When the native affordance is
  unresolved the intent is acknowledged (`applied=false`, `native_error`) rather
  than reported as a failure.
- **Sidecar â€” impulse prompt (`agent/initiative.py`).** Rewritten to be strictly
  in-character / first-person and to forbid task/scene narration; added
  `_clean_thought`, which drops meta output ("The user gives a situation â€¦"),
  punctuation-only fragments (`)`, `.`) and empty text so the deterministic
  impulse is used instead of storing junk.
- **Tests.** sidecar 335 â†’ **338** (meta/punctuation thought discard, prompt
  framing); mod 201 â†’ **203** (targeted speak fallback, bias ack).

### Added â€” v0.3 R2/R3: agent seats + intent bus (inhabitation pivot)
- **Seats (`agent/seats.py`).** New `SeatManager`: a runtime pool of `agent_seats`
  assigned by priority (active household â†’ instanced visitors), rebuilt from the
  census/zone pulse (`sync`). A Sim that leaves the lot frees its seat
  (eviction), while memory persists without a seat. This is L2 of the Â§15.3
  framework.
- **Intents (`agent/intents.py`).** New `Intent` shape + `IntentBus`: the v0.2
  command palette becomes intent-first (`bias_interaction`, `speak`, `set_mood`,
  `approach`, `prefer_target`, `set_goal`, `remember`, `forget`) with a gated
  `command` escape hatch. `intent_from_directive` maps the legacy palette so the
  old `/v1/autonomy/directives` round-trip keeps working.
- **Agency (`agent/agency.py`).** `Agency` now owns the `SeatManager` and the
  `IntentBus` (replacing the pending-directive store) and honors the new dials:
  idle impulses are gated by the seat + per-Sim `impulse_frequency` (0 =
  sleep-only) and `reactions_enabled`; `snapshot()` exposes seats and intents.
- **Initiative (`agent/initiative.py`).** `build_impulse` emits `intents`
  (derived from the model's tool calls) alongside the legacy `directives`.
- **Graph (`agent/graph.py`).** `_gate_directives` â†’ `_gate_intents` (rails +
  coordinator arbitration on intents); new `ContextForge` assembles the per-Sim
  context once per "think"; new `pull_intents`, `seats_roster`, `assign_seat`,
  `update_agents`; `ingest_census`/`ingest_tick` seed the seats; `/v1/status`
  surfaces the seat pool.
- **Wire (`schemas.py`, `routers/autonomy.py`).** New `SeatInfo`, `RosterResponse`,
  `SeatAssignRequest`, `IntentItem`, `IntentResponse`; endpoints
  `GET /v1/agency/seats`, `POST /v1/agency/seats`, `GET /v1/autonomy/intents`
  (`/v1/autonomy/directives` kept as the transitional alias).
- **Config.** `[agents] agent_seats` (overrides legacy `max_active`),
  `[agents.initiative] impulse_frequency` / `player_sim_impulse_frequency` /
  `reactions_enabled`, `[agents.layers]` (memory/cognition/social) and
  `[runtime] expose_roster`; the `ControlSpec` registry (`god/controls.py`) gains
  the agent-seat/impulse/layer dials behind `POST /v1/config/god`.
- **Mod â€” GameLever (`tool_executor.py`).** New `execute_intent` translates each
  intent into the closest native lever (`speak` â†’ `say_to`/`spontaneous_line`,
  `set_mood`, `approach`, `bias_interaction` â†’ a gated queue candidate) and falls
  back to the gated command; `_post_tool_result` is shared with `execute`.
  (`tool_executor.py`, `state_collector.py`.)
- **Mod â€” roster + intent pull.** `state_collector.pull_and_execute_directives`
  now pulls `/v1/autonomy/intents` and translates via GameLever (speech shown
  through `notify.social.speech`); new `sw.agents [<seats>|<sim_id> <freq>]` cheat
  and `god_ui.format_roster`; new keys in `en` + `pt-BR`.
- **Tests.** sidecar 298 â†’ **309** (`SeatManager`, `IntentBus`, seats/intents
  endpoints); mod 167 â†’ **179** (GameLever, roster, intent pull, v0.2 fallback).

### Added â€” handoff/status doc
- **`docs/STATUS.md`** â€” single entry point for a new session: current build,
  how to run the sidecar, what's implemented/validated live, the pending
  validation checklist (zone heartbeat first), known issues, and how to continue.
  The skill now points to it.

### Added/Investigated â€” R1/F2: decompiled the shipped scripts; fixed buffs + heartbeat
Instead of guessing, decompiled the shipped Python (`decompyle3` â†’ `research/ts4/`,
gitignored) and documented the confirmed APIs in **`docs/ts4_internals.md`**.
- **Buffs (root cause).** `sim_info.buff_component` does not exist: buffs live on
  **`SimInfo.Buffs`** (a `BuffComponent`) â†’ `_active_buffs` (handle id â†’ `Buff`) â†’
  `Buff.buff_type` (tuning; `__name__` = `buff_Sleeping`, â€¦). `_buff_names_of`
  now reads that path, so sleep detection / P1 actually work.
- **Reliable heartbeat.** Alarms were confirmed unreliable live (owner `object_sim`
  and `Zone` both failed to fire). `state_collector.install_zone_hook` now keeps a
  `zone.Zone.update` wrapper installed: it starts the collector once the **active
  Sim is instanced** (correct alarm owner + non-empty census) and drives a
  wall-clock-throttled pulse/pull every `ZONE_PULSE_INTERVAL_SECONDS` (15 s), so
  the agency loop runs during normal play with no command and no dependence on
  alarms. Per-frame cost after startup is one timestamp compare.
- **Probe** reads `SimInfo.Buffs` and lists `buff_members` for future diagnosis.
- **Tests.** mod 200 â†’ **201** (buff component `_active_buffs`, zone-heartbeat
  start/throttle/wait).

### Fixed â€” zone hook gating (owner=Zone + empty census) + event logging
The `.6` session confirmed the zone hook installs and auto-starts, but it fired
on the first `Zone.update` **before the active Sim was instanced**, so the alarms
got `owner=Zone` (do not tick) and the bootstrap census was `0 sims`; nothing was
collected during the session.
- The hook now waits until `sim_context._get_active_sim_instance()` exists before
  calling `ensure_started()`, so the alarm owner is the **Sim instance** and the
  census is non-empty. Still self-uninstalls once live.
- `_emit` now logs every forwarded event (`[validate] event: <type>`) so the next
  run shows whether game events are actually delivered (registration on an early,
  stale event manager would otherwise be invisible).
- **Tests.** mod 199 â†’ **200** (zone hook waits for the active Sim).

### Fixed â€” collector auto-start at zone load (why play sessions collected nothing)
Root cause of the empty live sessions: the collector was only ever started from
the **command paths** (`_ensure_ready`/`_output`), and its deferred event/alarm
flush was only retried there. So a session where the player just *plays* never
registered events or alarms â€” the `.5` session logged nothing until the final
`sw.probe`, and only then (19 s before exit) did the alarms register.
- **`state_collector.install_zone_hook()`** wraps `zone.Zone.update` to call
  `ensure_started()` on the first zone ticks (when a live Sim exists to own the
  alarms) and **self-uninstalls** once the collector is live, so it comes up
  automatically at zone load with no lingering per-frame cost. Installed from
  `__init__.py`. This makes the zone pulse/pull/events fire during normal play,
  independent of cheat commands.
- **Tests.** mod 197 â†’ **199** (zone-hook install/auto-start/self-uninstall +
  no-op without the `zone` module).

### Fixed â€” second live-validation pass (pulse safety net, buff discovery)
The second in-game run (build `.4`) confirmed the census/seat fix (census 7 Sims,
seats `household: 5, visitors: 2`) and the lifecycle attach/exit, but the
game-clock alarms still never fired and buffs were still empty, so:
- **Event-driven pulse safety net.** `StateCollector._maybe_pulse` fires a pulse
  (`/v1/autonomy/tick`) + intent pull piggy-backed on forwarded gameplay events
  (wall-clock throttled by `PULSE_MIN_INTERVAL_SECONDS`, only once the collector
  is started). Game-clock alarms pause with the game; events only fire during
  active play, so the agency loop now runs whenever the player actually plays.
- **Alarms prefer `use_sleep_time=False`** so a Sim-owned repeating alarm keeps
  advancing while the Sim sleeps (it otherwise silently stalls at night).
- **Buff discovery.** `probe` now lists buff/mood member names
  (`sim_info.buff_members`, `sim_instance.buff_members`); `_buff_names_of` also
  probes `mood_component`/`buff_tracker`/`mood_tracker` and
  `get_active_buffs`/`active_buffs`. `_on_zone_load` logs `zone_load event fired`.
- **Tests.** mod 195 â†’ **197** (event-pulse gating/throttle).

### Fixed â€” first live-validation pass (alarms never fired, census scope, buffs)
Found while validating the R2/R3/R4 build in-game (only `sw.probe` was run):
- **Alarms never fired (blocker).** The pulse/pull/snapshot alarms registered but
  their owner was the zone/household/service, which the alarm service does not
  advance. `events._resolve_alarm_owner` now prefers the **active Sim instance**
  (a live GameObject), falling back to zone/household/client, and `add_alarm`
  logs the chosen owner type. `_on_zone_load` re-arms the alarms and sends one
  immediate pulse, so the agency loop gets data even across zone/active-Sim
  changes.
- **Census read the whole save.** `build_census` now takes a `scope`: the default
  `active_zone` reads only the **instanced** Sims (+ active), `full_save` is
  opt-in. This fixes the seat pool being filled with 81 NPCs (`household: 1,
  visitors: 81`) â€” the `[validate]` census line reported 82 sims for
  `scope=active_zone`.
- **Buffs/whims empty â†’ sleep detection broken.** The probe showed
  `sim_info.buff_component` is absent in the current patch; `_buff_names_of` now
  also reads the buff component from the **Sim instance** and `get_buffs`-style
  accessors. `probe` gained a `sim_instance` section and probes the instance's
  buff component for next-run diagnosis.
- **`/v1/lifecycle/attach` 401 on the first boot.** `http_client.attach_lifecycle`
  now clears the runtime cache and retries once on a 401 (stale `runtime.json`).
- **Tests.** mod 191 â†’ **195** (alarm-owner preference + fallback, instance-level
  buff reading, census scope). sidecar unchanged (**335**).

### Added â€” validation logging (close the in-game observability gaps)
- **Mod â€” `debug_log.validation_log()`.** New semantic logging of the decisions
  that were invisible: each executed intent (`kind`/`name`/`sim`/`ok`/`err`) in
  `pull_and_execute_directives`, chat tool calls, zone-pulse Sim count, census
  counts and the `sw.agents` roster. Prefixed `[validate]`, gated by
  `SENSEWRIGHT_VALIDATION` (on by default; `=0` mutes without touching errors).
- **Mod â€” log rotation.** `sensewright_output.log` no longer silently stops at the
  size cap: it rotates (keeps the tail), so a late `sw.probe` dump is never lost;
  cap raised to 1 MB.
- **Sidecar â€” semantic logs (`logger.info`).** Pulse (`sims`/`sleeping`/
  `scheduled`/`seats`), stored intents (`kinds`), impulse outcome (`kind`/
  `autonomy`/`intents`/`thought`/`used_llm`), live cognition plan (`source`/
  `focus`/`goals`), event ingestion (`count`/`types`), intent pull (`count`/
  `kinds`) and census seat sync. Together with the existing uvicorn access log,
  a session can be validated from `sidecar.log` + `sensewright_output.log`.
- **Tests.** sidecar 333 â†’ **335** (pulse/intent log assertions); mod 188 â†’ **191**
  (`test_debug_log.py`: validation prefix/mute + rotation).

### Added â€” sidecar lifecycle: exits with the game
- **Game-process watchdog (`sidecar/.../lifecycle.py`).** The sidecar now shuts
  itself down when The Sims 4 exits, so it never lingers after the game closes.
  The mod passes its PID via `SENSEWRIGHT_GAME_PID` on spawn (`main._spawn_sidecar`);
  a background thread watches that PID (Windows `ctypes` `OpenProcess` +
  `GetExitCodeProcess`; `os.kill(pid, 0)` elsewhere) with a grace period and asks
  uvicorn to stop (`app.state.server.should_exit`) for a graceful shutdown
  (`graph.shutdown()` + `runtime.json` cleanup). An optional process-name watch
  is available but off by default.
- **`POST /v1/lifecycle/attach` (`routers/lifecycle.py`).** A sidecar already
  running (manual start or a previous session) can be armed at boot: the mod
  calls this when autoboot finds the sidecar up. The watcher is always created
  when `shutdown_on_game_exit` is on, so attach works even with no target at
  startup.
- **`__main__.py`** now runs a `uvicorn.Server` and exposes it on `app.state`
  (the `--reload` dev path keeps the plain runner).
- **Config.** `[runtime]` gains `shutdown_on_game_exit`, `game_pid`,
  `watch_game_process_name`, `game_process_name`, `game_watch_interval_seconds`,
  `game_watch_grace_seconds` (documented in `config.example.toml`).
- **Validated live.** With a fake "game" process: both the env-from-spawn path
  and the attach path shut the sidecar down ~5â€“6 s after the process died, with a
  clean `Application shutdown complete` and the memory DB closed.
- **Tests.** sidecar 319 â†’ **333** (`test_lifecycle.py`: PID checks, watchdog
  trigger/attach/name/stop, watcher factory, attach endpoint); mod 186 â†’ **188**
  (`attach_lifecycle` payload + autoboot attaching on an already-running sidecar).

### Added â€” v0.3 F0/F1: R1 research tooling (`sw.probe` + decompile script)
- **F1 â€” `sw.probe` (mod).** New permanent dev cheat (`mod/.../probe.py`) that
  dumps a JSON snapshot of the active Sim's autonomy surface to
  `sensewright_output.log`: the autonomy service/component, `si_state`, commodity
  (motive) values, buffs/traits, whims, relationship tracks and the interaction
  queue. It also attempts to import every module from the Â§15.7 module map and
  records which exist in the current patch plus their public names â€” the raw
  material for the R1 levers catalog. Every read is guarded; pure helpers
  (`_describe`, `_prune`, `render_probe`, `_probe_modules`) are unit-tested.
- **F0 â€” `scripts/decompile-scripts.ps1`.** Reproducible decompile step: locates
  the game, stages `Game/Bin/Python/generated.zip` +
  `Data/Simulation/Gameplay/{base,core,simulation}.zip`, verifies the 3.7
  bytecode magic (`42 0D 0D 0A`) and decompiles with a configurable unpyc37
  command into the gitignored `research/ts4/`. `-VerifyOnly` runs without a
  decompiler.
- **Docs.** Module map updated (`probe.py`); `sw.probe` added to `sw.help` and the
  `en`/`pt-BR` locale tables.
- **Tests.** mod 179 â†’ **186** (`test_probe.py`: describe/prune/render, module
  importability, no-sim snapshot, log write).

### Added â€” v0.3 R4: cognition layer (daily plan + goals at sleep)
- **Cognition (`agent/cognition.py`).** New `CognitionLayer` + `make_daily_plan`:
  at sleep one budgeted call turns recent events + profile into a compact
  **daily plan** (`day_focus` + up to 3 `goals`) stored on the profile
  (`daily_plan`/`day_focus`/`goals`), with a deterministic template fallback so
  native mode keeps planning. Absorbs the Phase 4 reflection into the sleep
  cycle; `sw.evolve` remains the manual trigger. Disabled via
  `[agents.layers] cognition = false`.
- **Graph (`agent/graph.py`).** `_sleep_consolidation` now runs the cognition
  layer after P1 absorption (one sleep = fold dialogue + drift psyche + plan the
  day); the absorbed profile is threaded through so the plan sees the latest state.
- **Prompt (`agent/initiative.py`).** Awake impulses render the stored plan
  (`render_plan`) so the Sim "adjusts the next day".
- **Tests.** sidecar 309 â†’ **319** (`test_cognition.py`: template/LLM plan,
  bad-JSON fallback, layer toggle, prompt shaping).

### Changed â€” Roadmap pivot: v0.3 "Inhabited Agents" (plan)
- **Direction.** The agency model moves from command-centric (the LLM emits tool calls that
  puppet the Sim) to **inhabitation + nudge**: a configurable **agent-seat pool** biases the
  game's **native autonomy** ("changes of route"); cognition runs mainly at **sleep**; a
  per-agent **impulse-frequency** dial is surfaced in an **agent-roster panel**; two
  agent-owned Sims get a real **simâ†”sim dialogue channel**; the God directs the **inactive
  neighbors' stories** on the free tier. Reference: *Generative Agents (Smallville)*.
- **Documented in `PLANO.md` Â§15** (bumped to v1.5): the `Â§14` per-item
  **keep/absorb/replace** map, the **L0â€“L7 layered framework** (new `CognitiveLayer`,
  `SeatManager`, `IntentBus`, `GameLever`, `LayerBudget`, `ContextForge`/`PairContext`), an
  **intent model** with lifecycle (`expires_at`), the phases **R1â€“R7**, a **fix-point map**
  of the already-implemented code, and the v0.3 risks/config draft.
- **Locked decisions.** Decompiled stubs in a gitignored `research/ts4/`; sequential internals
  reading; permanent `sw.probe` cheat; **hybrid nudge** (pure bias when available, else a
  gated candidate in the queue); simâ†”sim **speech bubble with notification fallback**; seat
  eviction **on lot exit**; God **free/slow**; idle impulses **kept as a per-agent dial**.
- **Research plan.** `F0` tooling (`unpyc37`, reproducible `scripts/decompile-scripts.ps1`),
  `F1` live probe, `F2` `docs/ts4_internals.md` (autonomy architecture + native-levers
  catalog), `F3` this registration.
- **No code change yet** â€” this entry records the approved plan; implementation starts at R1.
- `.gitignore` now excludes `research/ts4/` (proprietary EA scripts must never be committed).

### Changed â€” LLM provider strategy (OpenRouter-first, model fallback, RPM/RPD, OpenCode Zen)
- **Chain order (OpenRouter first, Gemini demoted).** `LLMConfig.chain` default and
  `config.example.toml` now order `openrouter â†’ opencode â†’ gemini`; Google AI
  Studio's free tier rate-limits aggressively, so it moves to last resort (kept, not
  removed, for a final fallback).
- **Groq provider removed.** The `GroqProvider` (class, module, registry mapping,
  discovery branch), its config block and its chain entry were removed end to end
  (code + `config.py` default + `config.example.toml` + docs).
- **OpenCode Zen provider.** New `OpenCodeZenProvider` (OpenAI-compatible, Bearer),
  registered as `opencode` and defaulting to `https://opencode.ai/zen/v1` (+ discovery in
  `registry.py` and a documented `[llm.providers.opencode]` block). It is an optional power
  tier (requires a Zen key) and never replaces the 0-key native mode; note its free tier is
  client-restricted (see the live-validation section below).
- **Per-model fallback within a provider.** `OpenAICompatProvider.complete` now walks
  `model` + `models` in order, so a 429/unavailable model falls through to the next model
  on the same provider before the chain moves on; a key-level auth error (401) stops the
  loop early while a 403 stays model-level. `LLMError` gained a `status` field to support
  this.
- **RPM/RPD rate limiting.** New `llm/limits.py:ProviderRateLimiter`; `ProviderChain`
  builds one per provider from `ProviderConfig.rpm`/`rpd` and skips a provider that would
  exceed its cap instead of burning a 429. `config.example.toml` documents realistic
  free-tier limits. The agency scheduler now paces on the chain's `primary_rpm()` (wired
  via `Agency.set_registry`), with `AGENCY_BASE_RPM` remaining only a fallback.
- **Tests.** sidecar 286 â†’ **295** (rate limiter, chain skip, `primary_rpm`, per-model
  fallback, auth short-circuit, OpenCode Zen defaults/registration, agency RPM).

### Validated â€” live provider smoke test (OpenCode Zen)
- **Zen's free tier is client-only.** Calling the Zen key from the sidecar, the free models
  `mimo-v2.6-flash-free`, `nemotron-3.5-lightning-free`, `nemotron-3-ultra-free` and
  `longcat-2.5-preview-free` return HTTP 403
  `FreeTierError: OpenCode's free tier can only be used from within OpenCode`. Only
  **`space-bunny-free`** works from an external client (validated: pt-BR text **and** a
  tool call `add_buff`), so it is the only Zen free slug the sidecar can use.
- **403 is model-level, not auth.** `_is_auth_error` now short-circuits only on 401, so a
  403 on one model makes the provider try its next model instead of aborting the whole
  provider. **Tests.** sidecar 295 â†’ **296**.

### Added â€” Free-tier billing guard + OpenRouter validation
- **`free_only` guard.** `ProviderConfig.free_only` restricts a provider to models whose id
  contains `:free`; the OpenRouter block enables it, so a misconfigured list can never call
  a paid model (no billing). With `free_only` and no free candidate left, the provider fails
  retryably and the chain moves on. **Tests.** sidecar 296 â†’ **298**.
- **OpenRouter live-validated (free models only).** With `free_only = true` the chain ran
  end-to-end: pt-BR text **and** a tool call (`add_buff`) via
  `nvidia/nemotron-3.5-lightning:free`. Free availability on this key:
  `nemotron-3.5-lightning`, `nemotron-3-ultra-550b-a55b`, `nemotron-3-super-120b-a12b` and
  `gemma-4-31b-it` answered; `qwen3.8-27b` frequently returned upstream 429 (shared pool)
  and is kept last. Note: these reasoning models sometimes answer in text under
  `tool_choice = auto` (they do call tools reliably when forced).

### Fixed â€” v1.4 live-validation pass (build 2026-09-26.6/.7)
The first live gameplay session (build `.5`) showed the collector never reaching
the sidecar and the Sim context degrading; root cause: **script mods load before
the game services exist**, so the event manager, the clock and the locale API all
failed at import and were never retried. Fixed:
- **Event/alarm bootstrap (no more dead collector).** `events.register` now
  *merges* handlers into a persistent store and flushes every handler not yet
  handed to a live manager, so a later call registers whatever was queued at
  import (`_flush`/`flush_pending`/`have_event_manager`, deduplicated). The
  collector caches its handler dict once (bound methods are fresh objects on each
  access) and `StateCollector.start()` retries each missing alarm/handler instead
  of bailing after one attempt; `ensure_started()` re-runs on the command paths
  (`main._ensure_ready`, called from `_output`) and pushes the zone **census once**
  when it first comes live. **Alarms now require a live owner** â€” `AlarmHandle`
  raises `ValueError('Alarm created without owner')`, so `events._resolve_alarm_owner`
  passes the active zone/household/client instead of `None` (build `.7`; the
  `.6` session logged `events.add_alarm deferred`). This finally wires
  `/v1/census`, `/v1/events` and `/v1/autonomy/tick`.
- **Sim context / service accessors (build `.7`).** Several reads called a service
  *accessor* or a method as if it were the value: fixed `_get_active_sim_info`
  (call `services.client_manager()` then `get_first_client()`),
  `_get_game_clock` (call the accessor), `_get_mood` (`get_mood()`),
  `_get_skills`/`_get_careers`/`_get_needs`/`_get_queue_size`/`_get_location`
  (call the method instead of returning the bound method). `_get_traits` uses
  `SimInfo.get_traits()` / `TraitTracker.equipped_traits` (the tracker has no
  `get_traits`/`traits`); `_get_relationships` uses
  `RelationshipTracker.get_target_sim_infos()` + `get_relationship_depth(id)`.
  Live check (build `.6`): `sw.chat lang='pt-BR' ... traits=65 rels=25`.
- **Save id (build `.7`).** `_get_save_id` reads the persistence service's
  `get_save_slot_proto_guid()` (stable per save) and skips `0`/empty, fixing the
  `save_id='0'` seen with `.6`.
- **Locale (Sim replied in English).** `i18n` gained `_detect_game_locale()`
  (returns availability) and `ensure_locale()`, which re-detects in `auto` mode
  until a game locale API answers, then locks. `main._get_current_lang` calls it,
  so requests carry `lang=pt-BR` when the game is Portuguese; `sw.lang` still
  forces an override.
- **Silent tool-only replies.** `main._render_response` surfaces the text of a
  `spontaneous_line`/`say_to` tool call when the model returns no reply (a
  `move_to`-only reply stays silent, as before).
- **Diagnostics.** Chat/debug logs now stamp the resolved `lang`, `save_id` and
  trait/relationship counts; the sidecar logs `lang`/`sim`/`save` per chat/hey.
- **Tests**: mod 153 â†’ **167** (deferred event flush, alarm owner, locale retry,
  tool-text render, traits/relationships/clock/mood/active-sim reads, save-id
  fallbacks, census bootstrap); sidecar **286** (chat/hey lang log only).

### Changed â€” Code review pass (mod robustness, from `code_review.md`)
- **Swallowed-exception logging (review #1).** New `sensewright_mod/debug_log.py`
  writes to `sensewright_output.log` (size-capped, de-duplicated per signature) behind a
  `DEBUG_MODE` flag (`SENSEWRIGHT_DEBUG=0` override). The `_safe_call`/`_safe_getattr`
  guards in `sim_context.py`, `state_collector.py` and `tool_executor.py` now record
  the real exception + traceback; so do the collector's alarm/registration `except`
  blocks and the tool-result post. `main.py` delegates to the shared logger.
- **Type-hint fix (review #2).** `ToolFunc = Callable[[Dict[str, Any]], Dict[str, Any]]`
  (was an invalid `lambda` alias).
- **Strict tool arguments (review #3).** Tools read only the canonical key defined in
  the sidecar's `tools/schemas.py` â€” `buff_name`, `trait_name`, `interaction_name` â€”
  with the permissive aliases removed; contracts are documented in `tool_executor.py`.
- **Exact sleep detection (review #4).** `state_collector._is_sleeping` matches whole
  buff/moodlet tuning ids (`sleeping`, `buff_sleeping`, `moodlet_sleeping`, â€¦) instead
  of substrings, so buffs like "Not sleeping well" no longer cause false positives.
- **Payload sanitization (review #5).** `http_client._sanitize_payload` recursively
  reduces every request body to primitives (non-finite floats â†’ `null`, leaked game
  objects dropped), replacing `json.dumps(..., default=str)`; `sim_context` now coerces
  `full_name`, `save_id`, `zone_id`, skills/careers/funds at the source so no legitimate
  value is lost.
- **Adjacent fixes.** `tool_say_to` derives an affordance from `tone` (the schema never
  sends `interaction_name`); `sim_context._get_sim_info_manager` now calls the accessor
  instead of returning it.
- **Tests**: mod 148 â†’ **153** (payload sanitization + non-finite floats, sleep
  substring false positives, primitive coercion).

### Added â€” v0.2 Â§14: Autonomous Sim Agents (M1, M2, A1â€“A3, P1, G1)
- **M1 â€” memory consolidation.** `memory/consolidation.py` folds a silent dialogue into
  one `consolidated_memory` event (deterministic extractive fallback + optional LLM);
  raw turns are archived (`consolidated=1`), never deleted, and leave the context.
  `graph.maybe_consolidate` runs lazily once the `dialogue_idle_seconds` window has
  passed on the next chat/hey; the sleep job consolidates too.
- **M2 â€” graded forgetting.** New `events` columns `strength`, `last_accessed_at`,
  `consolidated`, `emotion`, `salience` (additive migration). `memory/decay.py`
  computes lazy decay with `fast|normal|slow` presets; `recent_events`/`search_events`
  drop forgotten/archived rows and rank by `importance Ã— strength Ã— recency`
  (lexical) or `cosine Ã— strength` (semantic). Recalled memories are `touch`ed;
  `prune_forgotten` and a rare dÃ©jÃ  vu hint complete the lifecycle.
- **A1 â€” world context.** `POST /v1/autonomy/tick` ingests a zone pulse (active +
  nearby instanced Sims, zone context, **sleep detection** via the sleeping buff);
  the mod builder (`state_collector.sample_zone`) and the `AutonomyTickRequest` wire
  model land the snapshot in the agency world cache.
- **A2 â€” agency skeleton.** `agent/agency.py` (`Agency`) is a priority scheduler
  (reaction â†’ sleep â†’ idle) with per-Sim cooldown, quota-aware pacing and a
  pending-directive store; `GET /v1/autonomy/directives` lets the mod pull and
  execute them (reusing `/v1/tools/result`). `agent/coordinator.py` implements
  single-writer arbitration (the Sim agent wins on a played Sim; denied God
  directives are logged, never silently dropped).
- **A3 â€” LLM impulse.** `agent/initiative.py` builds a compact impulse prompt
  (profile + memories + world) and lets the model emit a bounded tool call and/or an
  internal `thought` (stored as an event, so life evolves even when unseen).
  Deterministic rule-based fallback keeps native/0-key mode alive.
- **P1 â€” living personality.** `agent/personality.py` adds `psyche`
  (traumas/baggage/aversions/attachments) + `life_story`, salience-gated absorption,
  intensity decay unless reinforced, capped blocks and prompt shaping
  (`format_life`). Sleep jobs consolidate dialogue + drift the psyche; the system
  prompt renders the shaping lines.
- **G1 â€” God scoping.** `god/world_model.aggregates()` (public population, mood
  distribution, tension and funds only) behind `GET /v1/god/aggregates`; the
  orchestrator never targets a played Sim and issues no control directive when only
  played Sims are present.
- **Wire/config.** New schemas (`ZoneContext`, `AutonomySimState`,
  `AutonomyTick*`, `DirectiveItem`, `DirectivesResponse`, `NeighborhoodAggregates`,
  `AggregatesResponse`, `EventRecord.source`, `StatusResponse.agency/personality`);
  `[memory]` consolidation/forgetting fields; `[agents.initiative]` and
  `[agents.personality]`; new initiative tools (`spontaneous_line`, `set_mood`,
  `act_out`, `socialize`, `approach`, `nearby_sims`, `world_state`, `sim_profile`)
  in `tools/schemas.py`/`registry.py`.
- **Mod.** `http_client.autonomy_tick` / `get_directives`; the zone-pulse and
  directive-pull game-clock alarms in `state_collector`; the eight new executor
  tools; `notify.autonomy.*` locale keys in `en` + `pt-BR`.
- **Tests.** sidecar 188 â†’ **286** (memory decay/consolidation, agency, coordinator,
  initiative, personality, god scoping, v0.2 graph + endpoints); mod 110 â†’ **148**
  (zone pulse/sleep, directive pull, new tools).

### Added â€” Phase 5c (God orchestration tier)
- **Sidecar â€” `god/orchestrator.py`**: `GodOrchestrator` is no longer a stub. It
  reads the world model, applies the dials (preset, `intervention_frequency`,
  `intensity`, `autonomy_degree`, `chaos_degree`, power toggles) and picks at most
  one intervention per tick from the preset deck, honoring per-intervention
  cooldowns. Cadence is `base_interval_seconds Ã— (1 âˆ’ frequency) Ã— (1 âˆ’ Â½Â·autonomy)`
  with a 30 s floor; `frequency = 0` disables it. Chaos boosts `extreme_event`/
  `spawn_npc` weights. Deterministic with an injected RNG/clock; an optional LLM
  registry adds a short in-character narration (falls back to the deck description,
  so it works in native/0-key mode).
- **Sidecar â€” `god/world_model.py`**: `WorldState.from_census()` builds the public
  world snapshot (Sims, relationships, funds, time/lot) from the cached census;
  `SimProfile`/`Directive` gained `is_player`, `narration` and `tool_call`.
- **Sidecar â€” directive mapping**: interventions become mod tool calls where the
  executor supports them (`apply_trait` â†’ `add_trait`/`add_buff` by duration,
  `force_social` â†’ `queue_interaction` with a relationship partner, `gossip` â†’
  `say_to`); `spawn_npc`/`relationship_shift`/`extreme_event` stay as broadcast
  world events (`source=god`) the Sim agents react to.
- **Sidecar â€” wire/graph**: `POST /v1/god/tick` (`GodTickRequest`/`GodDirective`/
  `GodTickResponse`) runs a tick against the last census and returns the issued
  directives. `graph.god_tick` records each directive in the target Sim's memory
  (`type=god`, importance 0.9) and `/v1/status` now exposes the orchestrator
  snapshot. `POST /v1/config/god` re-applies the dials to the live orchestrator
  (the previous forward hit a module with no `configure` and silently did nothing).
- **Config**: `[god] base_interval_seconds` (default 600), documented in
  `config.example.toml`.
- **Tests**: sidecar 167 â†’ **188** (`test_orchestrator.py` + god-tick graph/endpoint).

### Added
- **Sidecar â€” LLM tool calling**
  - `LLMToolCall` and `LLMResponse.tool_calls`; `complete(..., tools=...)` through
    `ProviderRegistry`/`ProviderChain` and the OpenAI-compatible + Gemini providers
    (schema conversion, argument parsing, `tool_choice=auto`).
- **Sidecar â€” safety rails** (`tools/rails.py`)
  - `DirectiveRails`: never-tools, per-Sim player-priority lock (10 s), rolling
    rate limit (60 s window, default 10 calls/min) and audit hooks
    (`tool_check` entries in `data/audit.log`).
  - Configurable via `[agents] tool_calls_per_minute` and `player_lock_seconds`.
- **Sidecar â€” directive round-trip**
  - Agent graph parses model tool calls, gates each through the rails, returns the
    allowed calls to the mod and stores them as pending calls per Sim.
  - `POST /v1/tools/result` now matches results to pending calls, records them in
    memory and drains the pending queue.
  - `POST /v1/events` ingests game events from the mod; `player_activity` /
    `player_interaction` events arm the player-priority lock.
  - `POST /v1/config/player-activity` arms the lock explicitly.
  - `/v1/status` exposes the rails snapshot.
  - New `add_buff` / `add_trait` tool schemas (semi + full autonomy).
- **Mod â€” DirectiveExecutor v1** (`tool_executor.py`)
  - Guarded game actions: `add_buff`, `add_trait`, `queue_interaction`, `move_to`,
    `say_to`, `cancel_current`; every call passes mod-side rails first and posts the
    result to `/v1/tools/result`.
- **Mod â€” state collector** (`state_collector.py`, `events.py`)
  - Game-clock alarm samples the active Sim every 30 sim-minutes; game-event
    handlers forward compact events to the sidecar. No per-frame work, no threads.
  - `http_client.send_events` / `send_event` / `send_player_activity`.
- **i18n**: `error.directive_denied` added to `en` and `pt-BR`.
- **Tests**: sidecar 56 â†’ **96**; mod 21 â†’ **61**.

### Added â€” Phase 2b + 5a (Census & God agent foundation)
- **Sidecar â€” memory**: `neighborhoods` and `households` tables plus async
  `upsert/get_neighborhood`, `upsert/get_household`, `list_households` and
  `set_sim_background`; reset/stats cover the new tables.
- **Sidecar â€” wire**: `SimRef.household_id`; God models (`Zeitgeist*`,
  `Background*`, `CensusSim/Household/Request/Response`, `ControlsResponse`);
  `GodConfig`/`GodConfigRequest` gained `mood_influence`, `autonomy_degree`,
  `chaos_degree` and a free-form `settings` map; `MOOD_TAGS` (7 tags).
- **Sidecar â€” `god/controls.py`**: declarative `ControlSpec` registry
  (slider/toggle/select/tags) that is the single source of truth for validation,
  `GET /v1/god/controls` and TOML defaults.
- **Sidecar â€” `god/zeitgeist.py`**: tag normalization, prompt block, deterministic
  `en`/`pt-BR` template and agent `suggest_zeitgeist` (suggest + rewrite).
- **Sidecar â€” `god/backgrounder.py`**: Sim/household background generation where
  native data is ground truth and `mood_influence` is the thermometer; deterministic
  fallbacks and `is_stale`.
- **Sidecar â€” endpoints**: `GET/POST /v1/god/zeitgeist`,
  `POST /v1/god/zeitgeist/suggest`, `POST /v1/god/background`,
  `GET /v1/god/controls`, `POST /v1/census`; `/v1/config/god` validates values
  against the ControlSpec registry (unknown keys â†’ `ok=false`).
- **Sidecar â€” agent graph**: `get/set/suggest_zeitgeist`, `generate_background`,
  `ingest_census`, `god_controls`, census cache, background staleness on zeitgeist
  change; the generated background is now rendered into the Sim prompt.
- **Mod**: census builder + `send_census`; `god_ui.py` (vanilla-dialog zeitgeist
  onboarding and household background prompt, with console fallback); `sw.zeitgeist`
  cheat and `sw.god` controls summary; 52 `god.*` + 2 `cmd.zeitgeist.*` locale keys
  in `en` and `pt-BR`.
- **Tests**: sidecar 96 â†’ **133**; mod 61 â†’ **88**.

### Added â€” Phase 5b (background batch pipeline)
- **Sidecar â€” `god/budgeter.py`**: `BackgroundBudgeter`, a sliding-window
  (per-minute) + daily quota meter dedicated to background work, kept separate
  from the chat path. Limit `0` means unlimited; injectable clocks for tests.
- **Sidecar â€” `god/scheduler.py`**: `BackgroundScheduler`, a priority queue
  (active-zone households â†’ active-zone Sims â†’ related NPCs) with key
  deduplication, bounded queue, retry-on-failure and an async loop that paces
  itself between ticks. The generation logic is injected as a `runner(job)`,
  so the scheduler is decoupled and deterministic to test.
- **Sidecar â€” agent graph**: the graph now owns the scheduler; `configure`
  drops any previous instance, `start_backgrounds`/`stop_backgrounds` manage
  its lifecycle, `process_backgrounds_once` drains a batch, `/v1/census`
  enqueues active-zone households/Sims (and relationship-discovered NPCs) and a
  zeitgeist change re-queues the save's backgrounds. `/v1/status` exposes the
  scheduler + budget snapshot. Generators now receive the registry only when a
  provider is actually available (`_effective_registry`), so native mode skips
  futile calls and the budget meters real usage only.
- **Sidecar â€” server**: the lifespan now configures the graph synchronously
  (it previously awaited the sync `configure`, which silently failed) and
  starts/stops the background scheduler.
- **Wire**: `CensusResponse.queued`.
- **Config**: `[god.backgrounds]` (`enabled`, `batch_size`, `interval_seconds`,
  `idle_seconds`, `per_minute`, `daily_limit`, `max_queue`, `max_attempts`),
  documented in `config.example.toml`.
- **Tests**: sidecar 133 â†’ **146** (budgeter, scheduler, graph integration).

### Added â€” Phase 3 (Agents): profiles, chat budget, semantic memory
- **Sidecar â€” `agent/profiler.py`**: one-sentence seed â†’ structured profile JSON
  (`name`, `backstory`, `personality`, `speech_style`, `goals`, `secrets`,
  `quirks`, `traits`) with native data as ground truth, deterministic `en`/`pt-BR`
  fallback and `normalize_profile`. Never raises.
- **Sidecar â€” chat budgeter (`llm/budgeter.py`)**: per-Sim daily request cap
  (`llm.budget_per_sim_per_day`), enforced on `/v1/chat` and `/v1/hey` only when
  a provider is available; exhausted requests return `error.budget_exhausted`.
  Exposed in `/v1/status` (`budget`).
- **Sidecar â€” semantic memory**: `MemoryConfig.embedding_provider_config`
  (Cloudflare account/token); events now store embeddings (new
  `events.embedding_json` column + additive migration) and `search_events`
  ranks by cosine similarity, falling back to lexical.
- **Sidecar â€” wire/endpoints**: `POST /v1/profile` (`ProfileRequest/Response`).
- **Mod**: `sw.profile <one sentence>` cheat + `request_profile` client.

### Added â€” Phase 4 (Evolution): reflection & personality drift
- **Sidecar â€” `agent/evolution.py`**: `reflect` (events â†’ reflection JSON +
  trait-swap proposal), `normalize_reflection`, deterministic `en`/`pt-BR`
  fallback, `should_reflect` (min events + cooldown), `propose_trait_swap`.
- **Sidecar â€” storage**: `list_profiles`, `add_reflection`,
  `recent_reflections` (SQLite + in-memory fallback).
- **Sidecar â€” agent graph**: `evolve(scope="sim"|"save")` reflects, drifts the
  profile personality, stores the reflection and a `proposed_trait_swap`;
  `evolution_speed` scales the thresholds. `POST /v1/evolve`
  (`EvolveRequest/Response`).
- **Config**: `[agents.evolution]` (`enabled`, `min_events`, `cooldown_seconds`,
  `max_reflections_per_day`, `trait_swap`, `drift_strength`).
- **Mod**: `sw.evolve [save]` cheat + `evolve` client; `error.budget_exhausted`,
  `cmd.profile.*`, `cmd.evolve.*` locale keys in `en` and `pt-BR`.
- **Tests**: sidecar 146 â†’ **167** (profiler, evolution, phase 3/4 wiring).

### Changed
- **`PLANO.md` bumped to v1.2** with a new **Â§14 "Autonomous Sim Agents (v0.2)"**: the
  per-Sim agency layer (initiative loop, `tick`/`directives`, quota-max scheduler),
  memory consolidation + graded forgetting (strength decay, touch, dÃ©jÃ  vu), a living
  personality (`psyche` blocks + `life_story`, sleep consolidation, immediate extreme
  absorption) and the God â†” Sim-agent coordination contract (single-writer, aggregates
  only, broadcast events, arbitration). Also added the v0.2 wire endpoints and config.
- Mod chat/hey only show the "brain foggy" fallback when no reply, system message
  *and* no tool calls were produced (tool effects are the response).
- `PLANO.md` Â§1/Â§2.3/Â§4/Â§7/Â§8/Â§9/Â§11/Â§14 rewritten for the God agent (zeitgeist,
  backgrounds, ControlSpec framework, 5a/5b/5c split) and the reviewer's fixes.
- `config.example.toml` documents the rails settings and the new `[god]` dials +
  `[god.settings]`.

### Fixed â€” Phase 0 spike (events & alarms wired to the real API)
- **Mod `events.py`** corrected against the scripts shipped with the live client
  (patch 1.113, extracted from `Data/Simulation/Gameplay/*.zip`):
  - `TestEvent` is an enum nested under `event_testing.test_events.TestEvent`; the
    old lookup used module-level `hasattr`, so **no event ever registered**. The
    map now reads the class members and uses the verified names:
    `BuffBeganEvent`/`BuffEndedEvent` (buff), `RelationshipChanged` (relationship),
    `InteractionComplete` (social/object), `TraitAddEvent`/`TraitRemoveEvent`,
    `SkillLevelChange`, `CareerEvent`/`CareerPromoted`, `SimDeathTypeSet`,
    `HouseholdChanged` (household), `LoadingScreenLifted`/`SimHomeZoneChanged`/
    `SimTravel` (zone load). `EVENT_SIM_SPAWN` has no native TestEvent and stays
    unmapped (census diff covers it).
  - Event manager now comes from `services.get_event_manager()` (there is no
    `sims4.event_manager` module), and unregistration passes the event type:
    `unregister_single_event(handler, event_type)`.
  - Alarms use the top-level `alarms` module (there is no `sims4.alarms`), with the
    verified signature `add_alarm(owner, time_span, callback, repeating=False,
    repeating_time_span=None, use_sleep_time=True, cross_zone=False)`.
  - Time spans use `date_and_time.create_time_span(days, hours, minutes)` (the old
    `sims4.math.TimeSpan` path never existed).
- **Mod â€” sidecar autostart from source.** With no packaged `.exe` yet (PyInstaller
  is Phase 6), `sw.start`/autoboot could not launch the sidecar, so it stayed down
  and `sw.chat`/`sw.status` reported "sidecar unreachable". `config.sidecar_launch()`
  now prefers the exe and otherwise runs the bundled source
  (`python -m sensewright_sidecar`), choosing the interpreter from
  `SENSEWRIGHT_PYTHON` â†’ the sidecar `.venv` â†’ `python`/`python3`/`py` on PATH.
- **Mod â€” chat never fails silently.** `sw.chat`/`sw.hey` now run context
  collection inside the `try` (a failure surfaces as a message instead of dying in
  the command system) and render through a shared `_render_response`: the dialog is
  tried first and the reply/fallback falls back to the cheat console. `chat_ui`
  passes the real connection to `CheatOutput` instead of only `None`.
- **Mod â€” command arguments to the real TS4 parser.** `main.py` used
  `from __future__ import annotations`, so `message: str` reached the command system
  as the *string* `'str'`; the parser (`sims4/commands.py`) does
  `isinstance(arg_type, type)`/`issubclass`, so typed args never parsed and
  `sw.chat`/`sw.profile`/`sw.zeitgeist` produced no request and no message. The
  future-import was removed (the annotations are all 3.7-safe) and the free-text
  commands now use an unannotated ``message`` + ``*args`` hybrid joined together â€”
  a lone variadic can be rejected by the console and an annotated positional
  collides with the injected ``_connection`` on multi-word input. `sw.chat` logs
  its raw args plus a `_BUILD` stamp to `sensewright_output.log` (and `sw.help` logs
  the build) so the loaded build can be confirmed; the game only loads script mods
  at startup, so a full restart is required after each install.
- **Mod â€” JSON payload with game objects (the "Internal error").** `http_client`
  called `json.dumps(payload)` *before* its request try/except, so a non-serializable
  value in the collected `context` (e.g. `relationship_track` / `full_name`)
  raised a `TypeError` that surfaced as an in-game "Internal error" **before any
  request was sent**. Serialization now uses `default=str`, and
  `sim_context._get_relationships` coerces `target_name`/`track` to `str` and
  `depth` to `float`. The chat/hey handlers also log the real exception + traceback
  to `sensewright_output.log` instead of swallowing it.
- **Mod â€” language resolved at boot (Sim replied in English).** `i18n._current_locale`
  was never set: `resolve_locale()` returned the detected locale but did not apply
  it, so every request sent `lang="en"`. Added `i18n.init_locale()` (called from
  `__init__` with `config.read_ui_language()`) which sets the active locale from the
  config override or the game language. `detect_game_language()` now reads
  `services.get_locale()` (`client.account.locale`), also consulting the enum's
  `name` and `SimSpawner.LOCALE_MAPPING`, and `_normalize_locale` matches by
  substring so `Locale.PORTUGUESE_BRAZIL`/`Language.ENGLISH` resolve correctly.
- **Tests**: mod 88 â†’ **110** (`mod/tests/test_events.py`, `test_config.py`,
  `test_chat_flow.py`, `test_http_client.py`, `test_i18n.py` lock in the validated
  enum/mapping, manager/alarm modules, sidecar launch, always-surface chat rendering,
  multi-word command parsing, non-JSON-safe payload and locale resolution).

### Fixed
- `scripts/install-mod.ps1`: `Join-Path` returns a string, so `$sidecarSrc.Path`
  was empty and the relative path chopped the drive letter, breaking the sidecar
  copy with "The given path's format is not supported".
- `server.py` lifespan awaited the synchronous `configure`, so the agent graph
  was never configured at boot (now called synchronously and the scheduler is
  started/stopped around the app lifespan).
- **Mod (found in the in-game spike):** `config.get_base_url()` already ended in
  `/v1` while every endpoint path also starts with `/v1/...`, so all requests hit
  `/v1/v1/...` and returned 404. It now returns the server root; a regression
  test asserts the prefix appears exactly once.
- **Mod (found in the in-game spike):** cheat commands produced no visible
  console output. Two causes: the connection was received in a plain
  `connection` parameter (TS4 injects a parameter named `_connection` only), and
  it was annotated `_connection: int = 0`, which made the command system treat it
  as a user argument instead of injecting the connection. Fixed by using
  `_connection=None` (unannotated) and emitting through `CheatOutput` first; a
  best-effort `sensewright_output.log` next to the mod records output for
  troubleshooting. i18n also reads locale JSON from inside the `.ts4script`.
- **Mod:** `sw.status` raised `TypeError` because `providers` is a list of dicts
  on the wire, not strings; added `_format_providers`.
- **Providers (found while configuring keys):**
  - Gemini API key was sent as a `?key=` query parameter, so httpx wrote the key
    into `sidecar.log`. It now uses the `x-goog-api-key` header, and the Gemini
    model auto-discovery does the same. *(Rotate any key exposed this way.)*
  - Gemini 2.5+ spends part of `maxOutputTokens` on internal "thinking", which
    truncated structured JSON answers; the provider now disables it
    (`thinkingConfig.thinkingBudget = 0`) for those models.
  - OpenRouter sample models were stale (`deepseek-chat-v3-0324:free` â†’ 404);
    updated to currently-free slugs (`qwen/qwen3.8-27b:free`,
    `nemotron-3-ultra-550b-a55b:free`, `gemma-4-31b-it:free`).

### Validated in-game (Phase 0 spike, live client 1.113.277.1030)
- Python 3.7 confirmed (`Game/Bin/python37_x64.dll`); `.ts4script` is a valid zip
  of 3.7 bytecode and **loads from the OneDrive `Documents` folder**.
- Mod â†’ sidecar autoboot ping reaches the sidecar; Mods had been auto-disabled by
  the game (`modsdisabled=1`) after the patch â€” re-enabling is required.
- Cheat commands now render in the console (`sw.help`), confirmed side-by-side
  with an independent reference script mod with the same pattern.
- **End-to-end LLM round-trip from inside the game**: `POST /v1/chat`,
  `POST /v1/profile` and `GET /v1/status` all returned 200 via Gemini
  (`gemini-2.5-flash`) in the sidecar logs, and the regenerated key never appears
  in the request URL (the `x-goog-api-key` header fix holds).
- **`sw.chat` works in-game (builds `2026-09-26.3`/`.4`).** After the
  command-annotation and JSON-serialization fixes above, typing `sw.chat <text>`
  reaches the sidecar (`POST /v1/chat â†’ 200`, Gemini), the reply is rendered and the
  conversation is persisted in `memory.sqlite3` (`events`: user + assistant turns,
  e.g. `olÃ¡` stored as `ol\u00e1`). The earlier `olA` seen in the debug log was only
  the terminal's display encoding, not the game's. Build `.4` additionally resolves
  the locale at boot, so requests now carry `lang` (`pt-BR` when the game is
  Portuguese) instead of always `en` â€” pending in-game confirmation.
- **Â§2.3 API validation against the shipped scripts** (`Game/Bin/Python/
  generated.zip`, `Data/Simulation/Gameplay/{base,core,simulation}.zip`):
  `TestEvent` members, `services.get_event_manager()`, the `alarms` module and
  `create_time_span`, `sim_info.add_trait/add_buff` (C-backed forwarders),
  `sim_info.genealogy`/`household`, `InteractionQueue.insert_next`/`cancel_all`,
  and `Zone.save_slot_data_id` â€” see the Fixes above for what changed.
- Background scheduler/budget defaults still need tuning against a live save.

### Pending (not yet validated in-game)
- Phase 0 spike: the event/alarm names are now validated and wired (see the Fixes
  above); still to confirm **live behavior** â€” that alarms fire on the game clock,
  that the chosen events fire as expected, and the real interaction/queue APIs
  (`push_super_affordance`, `move_to`, `say_to`) plus census cost measurements.
- Game-event driven player-activity detection (the endpoint and lock exist; wiring
  a real "player clicked" signal is still to be confirmed in-game).
- God UI: `UiDialogTextInput` / multi-choice dialog signatures and reliable
  new-household / new-Sim detection (best-effort census diff in the meantime).
- Background batch pipeline: scheduler and budgeter are unit-tested, but the
  cadence/budget defaults are not yet tuned against a live save.

---

## [0.1.0] â€” 2026-09-25 â€” Phase 1: Skeleton

First end-to-end skeleton: sidecar boots by itself, mod handshake works, all UI text is localized.

### Added
- **Foundation / wire contract**
  - `sidecar/sensewright_sidecar/schemas.py`: Pydantic v2 models for `/v1` (`ChatRequest`,
    `ChatResponse` with `message_key`/`message_args`, `ToolResultRequest`, `ResetRequest`,
    `AutonomyConfigRequest`, `LangConfigRequest`, `GodConfigRequest`, `StatusResponse`, â€¦)
    plus `normalize_lang` and `SUPPORTED_LANGS = ("en", "pt-BR")`.
  - `config.py`: `config.toml` loader with `${ENV}` expansion, `[ui].language`, platform-aware home.
  - `auth.py`: shared-token auth (`X-Sensewright-Token`), `runtime.json` writer, 0600 token file.
- **Sidecar (Python 3.10+, FastAPI)**
  - `server.py` (`create_app` + lifespan) and `__main__.py` CLI.
  - Endpoints: `GET /v1/health`, `GET /v1/status`, `POST /v1/chat`, `/v1/hey`,
    `/v1/tools/result`, `/v1/reset`, `/v1/config/{autonomy,lang,god}`.
  - `observability/`: rotating file logging + JSONL audit log.
  - LLM layer: Gemini, Groq, OpenRouter and DeepSeek providers (OpenAI-compat shared),
    fallback `ProviderChain` with per-provider circuit breaker (3 failures â†’ 60 s),
    `ProviderRegistry` + best-effort `auto_discover()`.
  - Memory: SQLite store (`sims`, `events`, `relationships`, `reflections`, `directives`)
    with async wrappers, plus embedding provider protocols (lexical default).
  - Agent graph: recall â†’ prompt â†’ model â†’ persist â†’ format, with **native fallback**
    (`message_key = notify.no_llm_native`) when no provider is configured.
  - God stub (world model, intervention presets, orchestrator) and tool JSON schemas +
    autonomyâ†’tool-set mapping.
- **In-game mod (Python 3.7, stdlib only)**
  - `i18n.py` + `locales/en.json` + `locales/pt-BR.json` (24 keys, EN reference/default,
    per-key EN fallback, defensive game-language detection).
  - `config.py` (install/sidecar discovery, `runtime.json` candidates), `http_client.py`
    (`urllib`, typed errors), `chat_ui.py` (notification â†’ command â†’ print fallback),
    `sim_context.py`, `events.py` (guarded `event_manager`/`sims4.alarms` scaffold),
    `tool_executor.py` (8 tool stubs), `main.py` (cheats `sw.chat`, `sw.hey`, `sw.status`,
    `sw.reset`, `sw.forget`, `sw.autonomy`, `sw.lang`, `sw.god`, `sw.start`, `sw.help`),
    and sidecar autoboot (`CREATE_NO_WINDOW`).
  - `mod/build.py`: compiles with Python 3.7 â†’ `dist/Sensewright.ts4script`
    (`--python`, `PY37`, `py -3.7` detection; `--allow-any-python` for dev).
- **Toolchain**
  - Root `Makefile` (`install`, `run`, `doctor`, `status`, `logs`, `build-mod`,
    `build-mod-dev`, `install-mod`, `check`, `dev`).
  - `scripts/doctor.ps1`, `scripts/dev.ps1`, `scripts/install-mod.ps1`.
  - `.gitignore`, `config.example.toml`.
- **Tests**: 56 sidecar (`pytest`) + 21 mod (locale parity, i18n, HTTP client).

### Changed
- `PLANO.md` rewritten from v1.0 (PT-BR) to **v1.1 (English)** with a new
  Â§4 *Localization (i18n)*, `lang` on the wire, and the English-everywhere convention.
- All shared foundation files converted to English.

### Fixed
- `mod/build.py`: `py -3.7` was invoked as a single string (WinError 2); `compileall -v`
  is unsupported on 3.7. Now uses a command list, cleans stale bytecode, and omits `-v`.
- `scripts/doctor.ps1`: PowerShell parse error (`$name:` drive reference) and wrong artifact path.
- `scripts/dev.ps1`: reserved `$args` variable and wrong module entry point (`-m sensewright_sidecar`).
- `scripts/install-mod.ps1`: looked for the artifact under `mod/dist` instead of `dist`.
- Sidecar `/v1/status` now returns a coherent provider list + chain health; `/v1/config/lang`
  no longer `await`s the synchronous `set_lang`.

### Environment
- Installed **Python 3.7.9** (`winget Python.Python.3.7`) for correct `.ts4script` bytecode
  (magic `42 0d 0d 0a`); sidecar runs on the existing Python 3.10.11.

### Known limitations
- No packaged `Sensewright-sidecar.exe` yet (runs from source; PyInstaller is a later phase).
- Tool execution and game events are guarded stubs; the `PLANO.md` Â§2.3 spike is not yet
  validated inside the live game.
- With no API keys the agent runs in **native mode** (no LLM), by design.

---

## Development status

| Phase | Scope | Status |
|---|---|---|
| 0 â€” Spike | Decompile stubs; validate Â§2.3 checklist in-game | â— Core event/alarm APIs validated vs shipped scripts; live measurements pending |
| 1 â€” Skeleton | Toolchain, handshake, autoboot, i18n scaffold | â˜‘ Done (0.1.0) |
| 2 â€” State & Directives | StateCollector, DirectiveExecutor v1, rails | â— Events/alarms now wired to the real API; in-game behavior pending |
| 2b â€” Census & household events | `/v1/census`, neighborhoods/households schema, events | â— Census + schema done; `HouseholdChanged` validated, live detection pending |
| 3 â€” Agents | Profiles, MemoryDB, ModelRouter + budgeter, chat | â— In-game `sw.chat` validated; provider chain live-tested (OpenRouter free + OpenCode Zen, pt-BR + tool calling); profile/memory visuals pending |
| 4 â€” Evolution | Reflection loop, personality drift, trait swaps | â— Reflection/drift/trait-swap proposal done; auto-apply pending |
| 5a â€” Zeitgeist | Onboarding, 7 tags, suggest+rewrite, ControlSpec framework | â— Sidecar + mod wiring done; in-game dialog spike pending |
| 5b â€” Backgrounds | Sim/household background writer, batch pipeline, thermometer | â— Generator + batch scheduler done; in-game validation pending |
| 5c â€” God panel | In-game sliders, DeepSeek orchestration, intervention deck | â— Orchestration tier done (`/v1/god/tick`, deck live, directives â†’ tool calls); in-game panel + wired DeepSeek provider pending |
| v0.2 M1/M2 â€” Memory | Consolidation + graded forgetting (strength decay, touch, dÃ©jÃ  vu, pruning) | â˜‘ Done (unit + graph tested); cadence tuning against a live save pending |
| v0.2 A1â€“A3 â€” Agency | Zone pulse, agency scheduler, tick/directives, LLM impulse + reactions | â˜‘ Sidecar + mod wired; live cadence/quota tuning pending |
| v0.2 P1 â€” Living personality | `psyche` + `life_story`, sleep absorption, immediate extreme path hook | â˜‘ Done (unit tested); in-game validation pending |
| v0.2 G1 â€” God scoping | Aggregates-only visibility, played-Sim protection, coordinator | â˜‘ Done (unit tested) |
| 6 â€” Publishing | Packaging, README, 0-key mode, degradation, perf | â˜ Planned |

### Verification commands
```powershell
# Sidecar tests + lint
cd sidecar; .\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check sensewright_sidecar tests

# In-game mod tests + build (requires Python 3.7)
python -m pytest mod\tests -q
python mod\build.py

# Environment health
powershell -ExecutionPolicy Bypass -File scripts\doctor.ps1
```
