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

- `services.get_situation_manager()` is the singleton (used across the decompiled
  source).
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
- `mood_type` is an enum-reference tunable → the tuning XML must use `<E
  n="mood_type">ANGRY</E>`, **not** `<T>…</T>` (confirms BUG-07).
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
- **routing probe** → `services.get_situation_manager().create_situation(...)` /
  `create_visit_situation(sim)`.
- **relationship probe** → `sim_info.relationship_tracker` edges, `sim_id_a/sim_id_b`,
  `get_all_bits()`.
