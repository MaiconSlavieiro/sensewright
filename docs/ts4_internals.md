# TS4 Internals — validated findings (R1 / F2)

Facts confirmed by reading the **shipped scripts** (decompiled with `decompyle3`
into the gitignored `research/ts4/`) and by live runs. Use these as the source of
truth when wiring game APIs in the mod. Module paths are the import roots the
game exposes to script mods.

## Autonomy (R1 levers)

| Module | Key names |
|---|---|
| `autonomy.autonomy_service` | `AutonomyService`, `choose_best_interaction`, `find_best_action`, `_select_best_result`, `_create_autonomy_request` |
| `autonomy.autonomy_component` | `AutonomyComponent`, `_create_autonomy_request`, `_push_interaction`, `_attempt_full_autonomy_gen` |
| `autonomy.autonomy_modifier` | `AutonomyModifier`, `BaseGameEffectModifier`, `GameEffectType`, `TunableAutonomyModifier`, `SuperAffordanceSuppression`, `StatisticCategoryModifierMapping` |
| `game_effect_modifier.mood_effect_modifier` | `MoodEffectModifier` |
| `game_effect_modifier.affordance_reference_scoring_modifier` | `AffordanceReferenceScoringModifier` |
| `interactions.si_state` | `SIState` |

The whole §15.7 module map imports successfully except
`relationships.sentiment_tracker` (`ModuleNotFoundError`).

## Buffs / mood (sleep detection)

- **`sims.sim_info.SimInfo.Buffs`** is a **property** returning the
  `objects.components.buff_component.BuffComponent`
  (`self.get_component(objects.components.types.BUFF_COMPONENT)`).
  There is **no** `sim_info.buff_component` (this was the bug).
- `BuffComponent`: `_active_buffs` (handle id → `Buff`), `buffs`, `has_buff`,
  `add_buff`/`remove_buff*`, `_active_mood`, `_active_mood_intensity`.
- `buffs.buff.Buff`: `buff_type` / `_buff_type` (the tuning; its `__name__` is the
  id, e.g. `buff_Sleeping`), `buff_reason`, `_handle_id`, `mood_type`, `mood_weight`.
- Sleep check: match `buff_type.__name__` against **exact** ids (`buff_Sleeping`,
  `moodlet_sleeping`, …) — never substrings.
- `SimInfo.get_mood()` returns the current mood tuning (e.g. `Mood_Fine`).

## Alarms

- Module `alarms`: `add_alarm(owner, time_span, callback, repeating=False,
  repeating_time_span=None, use_sleep_time=True, cross_zone=False)`,
  `cancel_alarm`; classes `Alarm`, `RepeatingAlarm`, `AlarmElement`,
  `RepeatingAlarmElementCrossZone`; fields `_owner_ref`,
  `_owner_destroyed_callback` (the alarm is cancelled when the owner is destroyed).
- **Live finding:** alarms with `owner=object_sim` **and** `owner=Zone` registered
  but did **not** fire during a session. Do not build the loop on alarms alone.

## Zone lifecycle (the reliable heartbeat)

- **`zone.Zone.update`** is called every frame while the zone is live. Wrapping it
  is the dependable heartbeat: start the collector once the **active Sim is
  instanced**, then drive a wall-clock-throttled pulse/pull.
- Do **not** start when only `services.current_zone()` exists (no Sim yet): the
  alarms then get `owner=Zone` and the census is `0 sims` (observed in build `.6`).
- Other hooks: `Zone.start_services`, `Zone.do_zone_spin_up`, `Zone._set_zone_state`,
  `ZoneState`, `Zone.register_callback`.

## Events

- Manager: `services.get_event_manager()` → `event_testing.event_manager_service`
  (`EventManagerService`); `register_single_event(handler, event_type)` /
  `unregister_single_event(handler, event_type)`.
- `TestEvent` members live under `event_testing.test_events.TestEvent`
  (`BuffBeganEvent`/`BuffEndedEvent`, `RelationshipChanged`, `InteractionComplete`,
  `HouseholdChanged`, `LoadingScreenLifted`, …).
- The manager is **not** available at script-mod import; register only after the
  services are up (the collector does this at start).

## Active Sim / services

- `services.client_manager().get_first_client()` → `client.active_sim` (the Sim
  **instance**) / `client.active_sim_info`; `sim_info.get_sim_instance()`.
- `services.current_zone()`, `services.active_household()`.

## Notifications (debug HUD / chat)

- **Runtime text:** `sims4.localization.LocalizationHelperTuning.get_raw_text(text)`
  returns a `LocalizedString` from a plain string (`RAW_TEXT =
  TunableLocalizedStringFactory(...)`). This is the correct way to pass runtime
  text to a dialog — wrapping it in `TunableLocalizedStringFactory(...)` is wrong
  (that is a *tunable type*, not a string).
- **Notification dialog:** `ui.ui_dialog_notification.UiDialogNotification` (a
  `UiDialog`). Its tunables are `title`, `subtitle`, `text`, `expand_behavior`,
  `urgency`, `information_level`, `visual_type`, … (`urgency` is an enum; there
  is **no** `urgent` kwarg). Show it with:
  ```python
  from ui.ui_dialog_notification import UiDialogNotification
  from sims4.localization import LocalizationHelperTuning
  dialog = UiDialogNotification.TunableFactory().default(
      owner,  # Sim instance (or SimInfo); community also passes the active client
      title=LocalizationHelperTuning.get_raw_text(title),
      text=LocalizationHelperTuning.get_raw_text(text),
  )
  dialog.show_dialog()
  ```
- Owner resolution: `services.client_manager().get_first_client()` →
  `client.active_sim` / `active_sim_info`; prefer a **Sim instance** when the
  SimInfo has `get_sim_instance()`.
- Implemented in `mod/sensewright_mod/chat_ui.py` (`show_notification`) and used by
  the debug HUD (`hud.py`).

## Status

- **Code-confirmed:** `SimInfo.Buffs._active_buffs` (implemented), module map
  (probe), zone heartbeat (implemented), notification API (implemented).
- **Still to runtime-validate:** whether the zone heartbeat cadence is smooth in
  long sessions, that notifications/HUD actually render in the live client, and
  the interaction-queue APIs (`push_super_affordance`, `move_to`, `say_to`).
