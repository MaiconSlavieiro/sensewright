# TS4 Engine API Notes (decompilation study)

Ground-truth facts extracted from the decompiled TS4 server scripts (Python 3.7
bytecode, `42 0d 0d 0a`). Source: `research/ts4/` (gitignored, decompiled with
`decompyle3` via `scripts/decompile_ts4.py`). These notes exist to stop the
"coding blind" rework loop documented in `docs/operations.md` (D2) — every
statement here was read from the decompiled source, not guessed.

> **Regenerate:** `python scripts\decompile_ts4.py` then re-verify the line
> references below against the decompiled `.py` files (they drift on every patch).

---

## 1. Console commands (the `sw.spike` / `sw.smoke_test` harness)

File: `research/ts4/core/sims4/commands.py`

- `Command(*aliases, command_type=CommandType.DebugOnly, command_restrictions=…,
  pack=None, console_type=None)` — decorator (line 205).
- **`CommandType.DebugOnly` commands are never registered** (`is_valid_command()`
  returns `False` for `DebugOnly`, lines 215–217). To expose a command through the
  in-game cheat console you must use `command_type=sims4.commands.CommandType.Live`
  (matching the existing `sw.chat` / `sw.panel` commands).
- Handler signature: `def handler(<args>, _connection=None)`. Print to the cheat
  console with `sims4.commands.output("text", _connection)` (or
  `sims4.commands.CheatOutput(_connection)`).
- The mod already registers `sw.chat`, `sw.chat_picker`, `sw.panel`, `sw.panic`,
  `sw.resume`, `sw.pie_*` this way — the harness must follow the same pattern.

## 2. Situations / NPC spawning (routing probe)

File: `research/ts4/simulation/situations/situation_manager.py`

- `services.get_zone_situation_manager()` is the singleton (used across the
  decompiled source — `situation_manager.py:135`). **Note:** there is **no**
  `services.get_situation_manager()`; the spike `sw.spike routing` confirmed the
  wrong accessor raises `AttributeError: module 'services' has no attribute
  'get_situation_manager'` in game build 1.128.90.1030.
- `create_situation(situation_type, guest_list=None, user_facing=True,
  duration_override=None, custom_init_writer=None, zone_id=0, scoring_enabled=True,
  spawn_sims_during_zone_spin_up=False, creation_source=None, …)` (line 337).
- `create_visit_situation(sim, duration_override=None, visit_type_override=None)`
  (line 408) — the native "NPC visits the lot" situation, directly relevant to
  `god.cast` / the VisitSituation hook.
- `create_visit_situation_for_unexpected(sim)` (line 402).
- `destroy_situation_by_id(situation_id)` (line 631).
- `get_situations_sim_is_in(sim, stage=SituationStage.RUNNING)` (line 950).

## 3. Relationships (relationship probe)

File: `research/ts4/simulation/relationships/relationship_service.py`

- The `Relationship` class exposes **`sim_id_a`** and **`sim_id_b`** (lines 105–106).
  There is **no `target_sim_id`** (the earlier bug BUG-09/13 was caused by assuming
  otherwise). Use `get_other_sim_id(sim_id)` / `get_all_bits()`.
- `RelationshipService.create_relationship(sim_id_a, sim_id_b)` (line 264);
  `destroy_relationship(sim_id_a, sim_id_b, notify_client=True)` (line 267).
- `SimInfo.relationship_tracker` returns the per-Sim `RelationshipTracker`
  (`sims/sim_info.py:1244-1245`); `RelationshipTracker` (in
  `relationships/relationship_tracker.py`) is the per-Sim edge container.

## 4. Social group (interaction probe / `sim.social`)

File: `research/ts4/simulation/socials/group.py`

- `class SocialGroup(ComponentContainer, …)` at line 88. Managed via
  `services.get_instance_manager(resources.Types.SOCIAL_GROUP)`.
- `SocialGroup.member_sim_ids_gen()` (line 307) enumerates member sim ids.
- On `Sim` (`sims/sim.py`): social groups live in `sim._social_groups` (list, line
  215); `sim.get_main_group()` returns the primary group; `sim.get_groups_for_sim_gen()`
  iterates them. **`Sim` has no `social_group` attribute** (confirms BUG-05).

## 5. Interactions & the social interaction state

File: `research/ts4/simulation/interactions/base/interaction.py`
(partial decompile — the file is 207 KB and decompyle3 stubbed it; cross-check
`interactions/context.py` and `interactions/choices.py` which decompiled cleanly)

- Per-interaction state lives on `sim.si_state`; `sim.si_state.sis_actor_gen()`
  yields the running social interactions (see `sims/sim.py:1142`).
- `sim.queue.running` is the queued interaction (see `sims/sim.py:815`).
- The earlier `sim.social` fix already reads the social peer from
  `si.social_group` on the interaction — the probes must read `si.social_group`
  **off the interaction**, not off the `Sim`.

## 6. Buffs & mood (UI-injection probe / `set_mood`)

File: `research/ts4/simulation/buffs/buff.py`

- `class Buff(…)` at line 91. Tuning fields `mood_type` (a `TunableReference` to a
  Mood, line 157) and `mood_weight` (a `TunableRange`, line 166).
- ⚠️ **`mood_type` is a `TunableReference` (manager=`Types.MOOD`, `allow_none=True`),
  NOT a `TunableEnumEntry`.** The tuning XML must therefore use the **numeric
  instance ID** (`<T n="mood_type">14640</T>` for happy), not the enum name
  (`<E n="mood_type">HAPPY</E>`). This **corrects BUG-07**, whose `<E>` "fix" was
  based on a mis-diagnosis and reintroduced `BuffInfo/MoodKey()` null client errors
  (confirmed in-game 2026-10-05: applying `buff_mood_happy` with `<E>HAPPY</E>`
  logged `TypeError: Error #1009 … BuffInfo/MoodKey()`). Vanilla mood instance ids
  (from S4CL `CommonMoodId`): HAPPY=14640, SAD=14643, ANGRY=14632, STRESSED=14645,
  FLIRTY=14638, INSPIRED=14641, FOCUSED=14639, DAZED=14644, BORED=14633,
  UNCOMFORTABLE=14646, CONFIDENT=14634, ENERGIZED=14636, PLAYFUL=14642,
  EMBARRASSED=14635, SCARED=251719.
- Buffs are applied via `sim.add_buff(buff_type, buff_reason)` (see `Buff.__init__`
  line 65). `buff_reason` is a localized reason string.

## 7. Objects (mirror / diary / mailbox)

File: `research/ts4/simulation/objects/game_object.py`, `objects/definition.py`

- `Definition.name` is **not** reliable for base-game objects (confirms BUG-04);
  the mod's fix prefers `script_object.__class__.__name__` (`Mirror`, `Mailbox`, …).

## 8. SimInfo (confidant, census)

File: `research/ts4/simulation/sims/sim_info.py`

- `SimInfo.sim_id`, `.gender` (enum), `.age` (`Age` enum — use `.name` to strip the
  `Age.` prefix, confirms BUG-15), `.household_id`, `.household`, `.relationship_tracker`.
- `SimInfo.is_player_sim()` (line 473) → `services.active_household_id() !=
  self.household_id`.

## 9. Key implications for the 4 data probes

- **interaction probe** → read `sim.si_state` / `sim.queue.running`; target via the
  interaction's `target`, group via `si.social_group`.
- **ui-injection probe** → buff text via `sim.add_buff(type, reason)`; balloons via
  `balloon/balloon_request.py`; tooltips via `objects/definition.py`/`ui/`.
- **routing probe** → `services.get_zone_situation_manager().create_situation(...)` /
  `create_visit_situation(sim)`.
- **relationship probe** → `sim_info.relationship_tracker` edges, `sim_id_a/sim_id_b`,
  `get_all_bits()`.

## 10. In-game spike validation (2026-10-05, build 1.128.90.1030)

First `sw.smoke_test` / `sw.spike` run against the real engine confirmed 4 facts
and exposed 4 defects (all now fixed in `engine_facade.py`/`spikes.py`):

- **✅ Confirmed:** `SimInfo.age` → `Age` enum (`age=CHILD`); `SimInfo.gender`; 
  `SimInfo.relationship_tracker` exists; mirror/mailbox resolve by class name
  (mirror ×7, mailbox ×1); S4CL `CommonRelationshipUtils.get_friendship_level`/
  `get_romance_level` return real floats (friendship=88.81).
- **🐛 Defect 1 (routing):** `services.get_situation_manager()` does not exist →
  `get_zone_situation_manager()` (see §2).
- **🐛 Defect 2 (buff):** `InstanceManager.types.keys()` yields raw `_resourceman.Key`
  objects, NOT int tuning ids. Passing a `Key` to S4CL `add_buff` raises
  `'_resourceman.Key' object has no attribute 'can_add'`. Convert with
  `int(key.instance)`.
- **🐛 Defect 3 (spike log):** probe payloads can carry `Key` objects → `json.dumps`
  needs `default=str`.
- **🐛 Defect 4 (tuning key):** the owned-name key is `trait_hidden_no_walkby`
  (with underscore); the smoke test typo'd it as `trait_hidden_nowalkby` → id=0.
- **⚠️ Open:** `_MOOD_BUFFS` is a reassigned global — spikes.py imported it by value
  (empty dict) and always fell through to the broken `Key` fallback; fixed by
  accessing `native_hooks._MOOD_BUFFS` via the module. Re-run `sw.smoke_test` to
  confirm the buff roundtrip now passes.
- **Note:** diary/journal objects resolve to 0 on the test lot (no such object
  placed) — expected, not a defect.

## 11. In-game spike validation #2 (2026-10-05, second run)

After the §10 fixes, the probes re-ran and confirmed the routing + buff fixes, and
exposed three more findings:

- **✅ Routing fixed:** `sw.spike routing` spawned 3 townies (Fátima Belem, Bob
  Pancakes, Eliza Pancakes) with valid `situation_id` (`get_zone_situation_manager`
  + `create_visit_situation` works).
- **✅ Buff fixed:** `sw.spike ui_injection` applied `buff_mood_happy` via an int id
  (`buff_reason.ok=true`); `_MOOD_BUFFS` module access fixed.
- **✅ Conversations:** `delta: N sims, 6 conversing` + `catalyst tracker:
  beat-ended posted decision=accept` — `sim.social` pair detection and the God
  Director `beat-ended` flow fire on real conversations.
- **🐛 Defect 5 (mood_type format):** applying `buff_mood_happy` still logged
  `BuffInfo/MoodKey()` null → root cause is that `mood_type` was written as
  `<E n="mood_type">HAPPY</E>` (enum name), but `mood_type` is a `TunableReference`
  → must be `<T n="mood_type">14640</T>` (numeric instance id). **This reverses
  BUG-07's `<E>` "fix"** (which was based on a wrong `TunableEnumEntry` diagnosis).
  All 34 buffs (15 mood + 14 bias + 4 dream + 1 missing_player) were reverted to
  the numeric form (see §6).
- **🐛 Defect 6 (balloon module):** the module is `balloon` (singular), not
  `balloons`. `BalloonRequest.__init__` takes `(sim, icon, icon_object, overlay,
  balloon_type, priority, duration, delay, delay_randomization, category_icon, …)`
  — no simple text constructor. Sleep-balloon injection remains best-effort.
- **🐛 Defect 7 (tooltip):** there is **no server-side `TooltipComponent`** (it is a
  client concept). Server-side object tooltip/display text comes from
  `obj.tooltip_text`/`obj.display_name` accessors, not `get_component(TooltipComponent)`.
