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
| Pie menu | tuning XML + DBPF `.package` + **XmlInjector** | S4CL `CommonImmediateSuperInteraction` registered in Python (`pie_menu.install`) |
| Pulse loop | `Zone.update` wrapper (native) | **Lot 51 `CoreEvent.GAME_TICK`** first, native wrapper as fallback (`state_collector.install_zone_hook`) |
| Notifications | native `UiDialogNotification` | **S4CL `CommonBasicNotification`** first, native path as fallback (`chat_ui.show_notification`) |
| Confirmation | native ok/cancel | **S4CL ok/cancel** first, native path as fallback (`dialogs.confirm`) |
| Config panel (R7/P2) | `sw.uitest` spike | real `panel_ui.open_panel` over `GET /v1/god/controls`; `sw.panel` cheat + pie-menu entry |
| Retired | `mod/tuning/**`, `mod/build_package.py`, `ui_probe.py`, `sw.uitest` | removed |

All library lookups live in **`mod/sensewright_mod/integrations.py`** — the single
seam. Every helper is guarded and returns `None`/`False` when a library (or the
game) is absent, so the offline test suite runs on plain CPython and the game stays
safe if a patch changes an import path.

## Libraries and locale

The data-driven locale system is **preserved**: `locales/manifest.json` + `i18n.t`
feed the S4CL dialog/notification text (via
`integrations.native_localized_string`), and pie-menu display names resolve at
interaction time so `sw.lang` still switches language at runtime.

## API surface used (live-validation status)

> The libraries are not present on the dev/test host, so these paths were written
> defensively (several candidate import paths per call). **Live validation in the
> game is required** to confirm the exact paths on the current S4CL/Lot 51
> releases.

| Used by | Library API (tried) | Status |
|---|---|---|
| `integrations.lot51_events` | `lot51_core.services.events.{event_handler, CoreEvent}` | ⬜ live check |
| `integrations.register_lot51_tick` | `CoreEvent.GAME_TICK` / `GAME_UPDATE` | ⬜ live check |
| `integrations.lot51_register_service` | `lot51_core.services.service_manager.service_manager` + `sims4.service_manager.Service` | ⬜ live check |
| `integrations.s4cl_notification` | `sims4communitylib.notifications.common_basic_notification.CommonBasicNotification` | ⬜ live check |
| `integrations.s4cl_ok_cancel` | `sims4communitylib.dialogs.ok_cancel_dialog.CommonOkCancelDialog` | ⬜ live check |
| `integrations.s4cl_choose_option` | `sims4communitylib.dialogs.option_dialogs.common_choose_option_dialog.CommonChooseOptionDialog` | ⬜ live check |
| `integrations.s4cl_interaction_base` | `...classes.interactions.common_immediate_super_interaction.CommonImmediateSuperInteraction` | ⬜ live check |
| `integrations.s4cl_register_interaction` | `...classes.interactions.common_interaction_registry.CommonInteractionRegistry` | ⬜ live check (display-name localization is the known risk) |

## Live-validation checklist (in order)

1. Game loads with **S4CL + Lot 51 Core** at the Mods root; `sensewright_output.log`
   shows no import errors from `integrations`.
2. `lot51_status()` (via `sw.probe`) reports `available=true`, `tick=true`.
3. The pulse heartbeat appears without the native `Zone.update` wrapper
   (`zone hook: driven by Lot 51 game tick`).
4. Notifications render through S4CL (`show_notification` layer 0).
5. The pie menu shows the 4 Sensewright items (no XmlInjector, no `.package`).
6. Pie-menu display names switch with `sw.lang` (en ⇄ pt-BR).
7. `sw.panel` opens the panel; sections come from `GET /v1/god/controls`.

## Rollback

The pre-migration state is preserved on branch `main` and tag `pre-migracao`.
The migration lives on `migrate-s4cl-lot51`.
