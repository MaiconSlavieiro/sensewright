# Stack migration: S4CL + Lot 51 Core

Sensewright's in-game layer is now **based on two community libraries** instead of
raw game APIs alone:

| Library | Role in Sensewright |
|---|---|
| **Lot 51 Core Library** (`lot51_core`) | Event bus (zone load/unload, game tick, save, build/buy, object added/destroyed), custom service manager, logger/config helpers. Replaces the fragile native alarm owner + `zone.Zone.update` heartbeat as the **primary** cadence. |
| **Sims 4 Community Library** (`sims4communitylib`, S4CL) | Notifications, native dialogs (ok/cancel, option/choose), the immediate-super-interaction base class used by the pie menu, and (forward) vanilla tuning-id utilities. |

The sidecar, the wire contract (`schemas.py`), the safety rails and the
**data-driven locale system** are unchanged. The player must install both libraries
at the Mods **root** (top level or one folder deep).

## What changed

| Area | Before | Now |
|---|---|---|
| Pie menu | tuning XML + DBPF `.package` + **XmlInjector** | tuning XML + `.package` (**kept** — S4CL needs a tuning per custom interaction) + S4CL `CommonInteractionRegistry` handler (`pie_menu.install`) |
| Pulse loop | `Zone.update` wrapper (native) | **Lot 51 `CoreEvent.GAME_TICK`** first, native wrapper as fallback (`state_collector.install_zone_hook`) |
| Notifications | native `UiDialogNotification` | **S4CL `CommonBasicNotification`** first, native path as fallback (`chat_ui.show_notification`) |
| Confirmation | native ok/cancel | **S4CL ok/cancel** first, native path as fallback (`dialogs.confirm`) |
| Config panel (R7/P2) | `sw.uitest` spike | real `panel_ui.open_panel` over `GET /v1/god/controls`; `sw.panel` cheat + pie-menu entry |
| Collector lifecycle | command paths + `Zone.update` start | **Lot 51 custom service** (`stack_service.py`: `on_zone_load` → `ensure_started`, `stop` → `stop`), native hook as fallback |
| Collector reads (Fase E) | raw game objects | **S4CL utilities first** (`CommonTraitUtils`/`CommonBuffUtils`/`CommonSimCareerUtils`/`CommonAgeUtils`/`CommonGenderUtils`), native paths as fallback |
| Retired | XmlInjector, `ui_probe.py`, `sw.uitest` | removed (the tuning `.package` is retained) |

All library lookups live in **`mod/sensewright_mod/integrations.py`** — the single
seam. Every helper is guarded and returns `None`/`False` when a library (or the
game) is absent, so the offline test suite runs on plain CPython and the game stays
safe if a patch changes an import path.

## Libraries and locale

The data-driven locale system is **preserved**: `locales/manifest.json` + `i18n.t`
feed the S4CL dialog/notification text (via
`integrations.native_localized_string`), and pie-menu display names resolve at
interaction time so `sw.lang` still switches language at runtime.

## API surface used (verified against the library sources)

> The paths below were checked against the cloned S4CL / Lot 51 Core sources
> (`research/ui-refs/`). **Live validation in the game is still required** to
> confirm they resolve on the installed releases.

| Used by | Library API | Status |
|---|---|---|
| `integrations.lot51_events` | `lot51_core.services.events.{event_handler, CoreEvent}` | ✅ source-verified |
| `integrations.register_lot51_tick` | `CoreEvent.GAME_TICK` (= `'game.update'`) | ✅ source-verified |
| `integrations.lot51_register_service` | `lot51_core.services.service_manager.service_manager` + `sims4.service_manager.Service` | ✅ source-verified |
| `integrations.lot51_logger` / `lot51_config` | `lot51_core.utils.log.Logger` / `lot51_core.utils.config.Config` | ✅ source-verified |
| `integrations.s4cl_notification` | `sims4communitylib.notifications.common_basic_notification.CommonBasicNotification` (`show(icon=None, secondary_icon=None)`) | ✅ source-verified |
| `integrations.s4cl_ok_cancel` | `sims4communitylib.dialogs.ok_cancel_dialog.CommonOkCancelDialog` (`show(on_ok_selected=, on_cancel_selected=)`) | ✅ source-verified |
| `integrations.s4cl_choose_option` | `sims4communitylib.dialogs.common_choose_response_dialog.CommonChooseResponseDialog` + `...common_ui_dialog_response.CommonUiDialogResponse` | ✅ source-verified |
| `integrations.s4cl_interaction_base` | `sims4communitylib.classes.interactions.common_immediate_super_interaction.CommonImmediateSuperInteraction` | ✅ source-verified |
| `integrations.s4cl_interaction_registry` / `s4cl_register_interaction_handler` | `sims4communitylib.services.interactions.interaction_registration_service.{CommonInteractionRegistry, CommonInteractionType, CommonScriptObjectInteractionHandler}` | ✅ source-verified |
| `integrations.s4cl_type_utils` / `s4cl_object_tag_utils` / `s4cl_game_tag` | `...utils.common_type_utils.CommonTypeUtils`, `...utils.objects.common_object_tag_utils.CommonObjectTagUtils`, `...enums.tags_enum.CommonGameTag` | ✅ source-verified |

### Pie menu wiring (S4CL + tuning package)

S4CL does **not** register custom interaction *classes*; it adds interaction
*tuning ids* to script objects (`CommonInteractionRegistry.register_handler`). A
custom interaction therefore needs a tuning resource, which
`mod/build_package.py` builds into `dist/Sensewright.package` from
`mod/tuning/interactions/*.xml` (class path given by `m`/`c`). `pie_menu.install`
registers:

- a `CommonScriptObjectInteractionHandler` adding all four tuning ids to Sims
  (`CommonTypeUtils.is_sim_instance`);
- a second handler adding the panel id to objects tagged `Func_Computer`
  (`CommonGameTag.FUNC_COMPUTER`).

## Live-validation checklist (in order)

1. Game loads with **S4CL + Lot 51 Core** at the Mods root and
   `Sensewright.package` + `Sensewright.ts4script` in `Mods\Sensewright\`;
   `sensewright_output.log` shows no import errors from `integrations`.
2. `lot51_status()` (via `sw.probe`) reports `available=true`, `tick=true`.
3. The pulse heartbeat appears without the native `Zone.update` wrapper
   (`zone hook: driven by Lot 51 game tick`).
4. Notifications render through S4CL (`show_notification` layer 0).
5. The pie menu shows the 4 Sensewright items (tuning package + S4CL
   `CommonInteractionRegistry`, no XmlInjector).
6. Pie-menu display names follow the packaged STBL and, when `get_name` resolves,
   switch with `sw.lang` (en ⇄ pt-BR).
7. `sw.panel` opens the panel; sections come from `GET /v1/god/controls`.
8. The Lot 51 **custom service** registers (`stack_service.registered()`); the
   collector starts on zone load through it, and object events resolve
   (`OBJECT_ADDED`/`OBJECT_DESTROYED`, corrected against the sources).

## Rollback

The pre-migration state is preserved on branch `main` and tag `pre-migracao`.
The migration lives on `migrate-s4cl-lot51`.
