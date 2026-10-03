# Sensewright v2 — Newly Discovered Bugs (deploy/playtest 2026-10-03)

> **Status:** ✅ CLOSED (2026-10-03) — BUG-01/02/03 fixed with regression tests
> (`sidecar/tests/test_bugs.py`, 11 tests); NOTE-01 addressed in config/docs.
> **Branch:** `v2-remake`
> **Build analysed:** hardening build installed 2026-10-03 02:19 (`.ts4script` 88,405 B).
> **Basis:** in-game session 2026-10-03 02:20–02:32 (`save 1488584711`):
> `Mods/Sensewright/sidecar/data/logs/sensewright-sidecar.log`,
> `mod_logs/Sensewright_Worker.log`, `Mods/Sensewright/sidecar/data/saves/slot_1488584711.committed.db`.

These are defects found **after** the hardening pass that were **not previously catalogued** in
[`plan.md`](plan.md), [`status.md`](status.md) or [`hardening.md`](hardening.md). They explain
why the visible gameplay features (dialogue, God Director) appear dead even though the agent
pipeline runs.

Status legend: ⬜ Pending · 🟡 In progress · ✅ Done

---

## Summary

| ID | Bug | Severity | Mapped before? | Status |
|----|-----|----------|----------------|--------|
| BUG-01 | `sim.social` never triggers — activity-based pair detection never matches | High | No (docs assumed `activity` was usable) | ✅ Fixed |
| BUG-02 | Stale duplicate `active` arcs are never cleaned; both stay at beat 0 | High | No (3.1 only prevents **new** duplicates) | ✅ Fixed |
| BUG-03 | Armed beats have no liveness/timeout — an arc stalls forever | Medium | No | ✅ Fixed |
| NOTE-01 | `sim.reaction` route points at a reasoning model (`deepseek-v4-pro`) | Low (ops) | No (config, not code) | ✅ Documented |

### Fix summary

- **BUG-01** — The Mod now reports a reliable `is_conversing` boolean and
  `social_target_sim_id` resolved from the interaction's Sim target
  (`state_collector._resolve_interaction_target_sim_id`). The sidecar prefers that
  signal, keeps the class-name markers as a fallback, and adds a conservative
  same-room/within-distance fallback (`services._find_conversational_pair` /
  `_proximity_pair`). Asymmetric routing is now wired too (`_puppeteer_context`).
- **BUG-02** — `SqliteStore.deactivate_stale_arcs(keep_id)` plus
  `god.arcs.load_active_arc` self-healing; `handle_session_start` now keeps the
  newest `active` arc and aborts the rest (`stale_arcs_deactivated` metric).
- **BUG-03** — Armed beats record `beat_armed_tick`; `god_tick` advances a beat
  older than `god.beat_timeout_sim_days` (default 1 in-game day) and marks the arc
  `ARC_DONE` when exhausted (`god_beat_timeouts` metric). Legacy armed beats
  without a stamp get a fresh window.
- **NOTE-01** — `sidecar/config.example.toml` documents per-purpose routing and
  now ships `[god] beat_timeout_sim_days`.

---

## BUG-01 — `sim.social` never triggers (pair detection never matches) ✅ FIXED

**Symptom.** No dialogues between Sims. `sim.social` = **0** in the entire sidecar log; the
worker only applied `bias_interaction` (42), `set_mood` (21) and `speak` (2, from
`sim.reaction`).

**Evidence.**
- Sidecar log: `grep -c 'sim.social'` → 0 (all sessions).
- Worker log (`02:20–02:32`): intents = `bias_interaction`, `set_mood`, `speak` only.

**Root cause.** `services._find_conversational_pair` (`services.py:648-662`) selects a pair
only when **≥2** census Sims have `activity` containing one of the markers
`("social","talk","chat","convers")` (`_CONVERSATION_MARKERS`, `_is_conversing`). The Mod
reports `activity = current_interaction.__name__` (`state_collector.py:191-199`), and EA's
social interaction classes are commonly named `MixerInteraction`, `GetToKnow`, `TellJoke`,
`ChatInteraction`… — most do **not** contain the markers. The pair is therefore never formed.

**Why it slipped through.** `plan.md:115` explicitly assumes *"`activity` is already
reported"*, and `status.md:132` marks purpose P05 `sim.social` as **Full**. No document lists
"activity string may not match the markers".

**Impact.** No `a_line`/`b_line`, no Compact Dialogue Card, no rumor contagion via social, and
— critically — no catalyst conversation, so `/v1/god/beat-ended` never fires and God arcs never
advance (see BUG-03).

**Proposed fix (choose and validate in-game).**
- Mod side: report a robust signal, e.g. `is_conversing: bool` and `social_target_sim_id`,
  computed from the current interaction's target (social interactions have a target) rather
  than its class name.
- Or sidecar side: relax `_is_conversing` to accept a target + proximity + matching `room_id`
  (REQ-SOC-01: same room, ≤ 4.0 m) instead of substring matching.

**Acceptance.** During an in-game conversation the sidecar logs `sim.social`; `speak` intents
are delivered; `social_sessions` becomes non-empty (after P06/`sim.social.close`).

**Files.** `mod/sensewright_mod/state_collector.py`, `sidecar/sensewright_sidecar/services.py`,
`sidecar/sensewright_sidecar/agent/social.py`.

---

## BUG-02 — Stale duplicate `active` arcs are never cleaned (both at beat 0) ✅ FIXED

**Symptom.** `arcs` table holds **2 rows, both `status=active`, both `current_beat_idx=0`**,
same theme ("O ritmo tranquilo da vizinhança"). The God Director never produces a single,
progressing narrative.

**Evidence.** `slot_1488584711.committed.db`:
```
arcs = 2
select id,status,current_beat_idx,theme from arcs
  -> ('635c25ca9ae9','active',0,'O ritmo tranquilo da vizinhanca')
  -> ('e2d57f292cee','active',0,'O ritmo tranquilo da vizinhanca')
```

**Root cause.** Hardening item 3.1 added the `arc_planning` single-flight claim, which stops
**new** duplicate `god.plan` submissions, but nothing deactivates arcs that were already
`active` in the store. `load_active_arc`/`god_tick` then operate on an orphaned duplicate.

**Impact.** The hardening Phase 6.2 acceptance "exactly 1 active arc" cannot pass; beat
progression is ambiguous; narratives stall.

**Proposed fix.** Add an idempotent cleanup on `handle_session_start` (or bootstrap
`ops.recap`), under the state lock: keep the most recent `active` arc, mark the others
`abandoned`. Prefer a store method (e.g. `deactivate_stale_arcs(save_id, keep_id)`) so it is
unit-testable. Consider doing the same on `/v1/god/direct-scene` when it replaces the arc.

**Acceptance.** After `session-start`, the store has ≤ 1 `active` arc; unit test covers two
pre-existing actives → one remains.

**Files.** `sidecar/sensewright_sidecar/services.py` (`handle_session_start`),
`sidecar/sensewright_sidecar/god/arcs.py`, `sidecar/sensewright_sidecar/memory/sqlite_store.py`.

---

## BUG-03 — Armed beats have no liveness/timeout (arcs stall at beat 0) ✅ FIXED

**Symptom.** Arcs remain at beat 0 indefinitely; `god.plan created` = 0 in the new run; no
`beat-ended` ever arrives.

**Root cause.** A beat only advances via `/v1/god/beat-ended`, fed by `catalyst_tracker` when a
catalyst conversation ends. If the catalyst never spawns/converses (blocked by BUG-01 and the
known `spawn_npc`/VisitSituation gaps), nothing ever advances or completes the arc, and no
timeout exists.

**Impact.** God Director silently stalls forever; no narration visible to the player.

**Proposed fix.** Record `beat_armed_tick` when a beat is armed; in `god_tick`, if the beat has
been armed longer than a configurable window (e.g. `god.beat_timeout_sim_days`, default 1), call
`advance_arc` (or mark `ARC_DONE`) and log the decision. This makes arcs self-healing even when
the catalyst path fails.

**Acceptance.** Unit test: an armed beat older than the timeout advances; in-game an arc never
remains on the same beat beyond the window.

**Files.** `sidecar/sensewright_sidecar/god/orchestrator.py`,
`sidecar/sensewright_sidecar/god/arcs.py`.

---

## NOTE-01 — `sim.reaction` routed to a reasoning model (ops, not code) ✅ DOCUMENTED

**Symptom.** In the 02/10 sessions, 111× `sim.reaction: all routes failed (model
deepseek/deepseek-v4-pro benched (unusable output))`. Mitigated by hardening 4.4 (per-purpose
breaker + 120 s bench): new run dropped to 2 `all routes failed`, 7 `unusable output`.

**Action.** In the installed `sidecar/config.toml`, route `sim.reaction` (and any JSON-only
purpose) to a JSON-capable model. Not a code defect; no engineering item required.

---

## Baseline that already works (do not regress)

- Hardening fixes verified in the new run: `rewind` = 0 (was 18), `ignoring tick drift` present,
  `stale_epoch` = 36 (stale callbacks dropped), `unusable output` 159 → 7,
  `mem.consolidate` fired (1) and `consolidated` rows exist.
- Agent pipeline works: DB `memories` = 300 (`thought` 282, `sleep_reflection` 5, `dream` 5,
  `legacy` 4, `diary` 3, `consolidated` 1).
- `sim.impulse` intentionally never speaks (REQ-IMP-01); its visible output is
  `set_mood`/`bias_interaction` (moodlets/buffs).

---

## Verification performed (2026-10-03)

- `cd sidecar && python -m pytest -q` → **623 passed** (11 new in `test_bugs.py`).
- `py -3.7 -m compileall -q mod/sensewright_mod` → clean.
- `python mod/build_package.py` → `Sensewright.package` (17,037 B, 44 resources).
- `python mod/build.py` → `Sensewright.ts4script` (91,397 B, 3.7 bytecode).
- **Still pending:** the in-game playtest (Phase 6.2 in [`hardening.md`](hardening.md))
  to confirm `sim.social` fires, `speak` intents arrive, `social_sessions` fills and
  exactly one arc progresses. Deploy with `scripts/install-mod.ps1` then play.

## How to inspect a session (if a regression appears)

1. With the game closed:
   - Sidecar log: `%USERPROFILE%\OneDrive\Documents\Electronic Arts\The Sims 4\Mods\Sensewright\sidecar\data\logs\sensewright-sidecar.log`
   - Worker log: `%USERPROFILE%\OneDrive\Documents\Electronic Arts\The Sims 4\mod_logs\Sensewright_Worker.log`
   - DB: `...\Mods\Sensewright\sidecar\data\saves\slot_<save>.committed.db`
2. Look for `sim.social`, `sim.social.close`, `god_beat_timeouts`,
   `stale_arcs_deactivated` and the `arcs` table (exactly one `active` row).

---

# Post-deploy playtest #2 (2026-10-03 12:34–12:44) — observability pass + BUG-04..07

> **Status:** ✅ CLOSED — BUG-04/05/06/07 fixed with regression tests/asserts.
> **Basis:** first in-game session after the observability instrumentation
> (`.ts4script` 95,687 B). Logs: `mod_logs/Sensewright_Worker.log` (12:34–12:44),
> `sidecar/data/logs/sensewright-sidecar.log`, `lastUIException.txt`.

This playtest used the instrumented build and, for the first time, produced
**deterministic evidence** for why four previously-unmapped features were dead.
The observability pass added a "heartbeat" log line to every feature path so a
session log now shows, per feature, whether it fired and what it did (see the
"Observability coverage" table at the end).

## Summary

| ID | Bug | Severity | Evidence (this session) | Status |
|----|-----|----------|--------------------------|--------|
| BUG-04 | Object interactions never appear: `_object_name` returns `<definition: NNNN>` | High | `mirror handler first object name="<definition: 30457>"` | ✅ Fixed |
| BUG-05 | `sim.social` never fires: `Sim` has no `social_group` attr | High | `delta: 12 sims, 0 conversing, 12 activity-idle` | ✅ Fixed |
| BUG-06 | Chat shows "not delivered": `handle_chat` omits `ok` | High | sidecar `sim.chat tokens=317` + pt-BR `chat.error_failed` | ✅ Fixed |
| BUG-07 | `lastUIException` flood: `BuffInfo/MoodKey()` null (mood_type `<T>` not `<E>`) | Medium | `Error #1009 ... BuffInfo/MoodKey()` (force-close) | ✅ Fixed |

## BUG-04 — object menus (mirror/diary/mailbox) never appear ✅

**Symptom.** Right-clicking a mirror/diary/mailbox shows no Sensewright option.

**Evidence.**
```
object_interactions: mirror handler first object name="<definition: 30457>"
object_interactions: diary  handler first object name="<definition: 30457>"
object_interactions: mailbox handler first object name="<definition: 30457>"
```

**Root cause.** `_object_name` read `script_object.definition.name`, which is
`None` for these base-game objects, then fell back to `str(definition)` →
`"<definition: 30457>"`. The `mirror`/`diary`/`mailbox` markers therefore never
matched and `should_add` always returned `False`.

**Fix.** Prefer the Python class name (`script_object.__class__.__name__` →
`Mirror`, `Mailbox`, …), which is stable and contains the marker; keep the
definition-name path as a fallback. Also added a per-handler diagnostic that logs
the first object seen + the first match, and a tuning-load check
(`tuning interaction.mirror_reflect ... loaded=True/False`).

**Files.** `mod/sensewright_mod/object_interactions.py`.

## BUG-05 — `sim.social` never fires ✅

**Symptom.** No Sim-to-Sim dialogue; `sim.social` = 0 all session.

**Evidence.**
```
delta: 12 sims, 0 conversing, 5 room_id, 0 sleeping, 12 activity-idle
```

**Root cause.** The conversation signal read `sim.social_group`, but `Sim` has no
such attribute (the S4CL source only ever reads `si.social_group` on each social
*interaction* in `sim.si_state`). The social peer therefore always resolved to 0.

**Fix.** `_resolve_social_group_peer` now iterates `sim.si_state` and `sim.queue`,
reading `social_group` off each social interaction and returning the first other
Sim id. `room_id` was already correct (5/12 instanced sims had a valid id).

**Files.** `mod/sensewright_mod/state_collector.py`.

## BUG-06 — chat shows "not delivered" despite a successful sidecar reply ✅

**Symptom.** Player message → "A mensagem não pôde ser entregue" even though the
sidecar answered.

**Evidence.** Sidecar: `llm.route purpose=sim.chat ... tokens=317` (a real reply);
mod side rendered `t('chat.error_failed')`.

**Root cause.** `handle_chat` returned `{"response": ..., "deferred": ...}` without
an `ok` key, but `chat_ui._handle_chat_response` gates on `response.get('ok', False)`
→ always `False` → error path. No test asserted `ok`, so it regressed silently.

**Fix.** `handle_chat` returns `"ok": True` on both the normal and deferred paths.
`tests/test_services_endpoints.py` now asserts `data["ok"] is True` on `/chat` and
`/hey`.

**Files.** `sidecar/sensewright_sidecar/services.py`, `sidecar/tests/test_services_endpoints.py`.

## BUG-07 — `lastUIException` flood: `BuffInfo/MoodKey()` null ✅

**Symptom.** Client throws `TypeError: Error #1009 ... BuffInfo/MoodKey()` repeatedly
(the session ended with a force-close).

**Root cause.** The emotion buffs wrote `mood_type` as a plain numeric tunable
(`<T n="mood_type">14632</T>`), but `mood_type` is a `TunableEnumEntry` — the XML
must use `<E n="mood_type">ANGRY</E>` (the same `<E>` element used by `buff_type`).
The misparse made the buff resolve to `Mood.FINE`, which has no client `MoodKey`.

**Fix.** All 12 `buff_mood_*.xml` now use `<E n="mood_type">ANGRY|BORED|CONFIDENT|DAZED|
ENERGIZED|FLIRTY|FOCUSED|HAPPY|INSPIRED|SAD|STRESSED|UNCOMFORTABLE</E>`
(enum member names from S4CL `CommonMoodId`). `buff_mood_fine` was already removed in
the previous wave (Mood_Fine has no MoodKey).

**Files.** `mod/tuning/buffs/buff_mood_*.xml`.

---

## Observability coverage (added across this + previous wave)

Every feature now logs a decisive line to `Sensewright_Worker.log` (success *and*
failure paths), so a single session pinpoints any dead feature:

| Feature | Log line |
|---|---|
| Mod loaded / tunings | `tuning interaction.chat ... loaded=True/False` |
| Pie menu reachable | `pie menu: interaction hook reached a Sim instance` |
| Chat entry / submit / reply | `chat entry point` · `chat submitted` · `chat response` / `chat response FAILED` |
| Sim-to-Sim dialogue | `delta: N sims, M conversing, K room_id` + sidecar `sim.social pair ... gate=...` |
| Reaction speech / mood | `intent ... [speak]/[set_mood] ... success=True` |
| Intent TTL loss | `intent bus: expired N intents ...` |
| God/catalyst | sidecar `god.plan created` / `god.puppeteer` / `god beat timeout` · mod `catalyst tracker: ... -> beat-ended` · `visit_situation: started native visit` |
| Object interactions | `tuning interaction.mirror_reflect ... loaded=` · `mirror handler first object name` · `mirror MATCHED` · `mirror reflect clicked` |
| Lifecycle events | `lifecycle: suppressing events until first autonomy pulse` → `lifecycle event posted` |
| Save/Shadow DB | sidecar `committed save ... at tick` |

## Verification performed (2026-10-03)

- `cd sidecar && python -m pytest -q` → **637 passed** (regression: reaction `sim_id`
  in `test_bugs.py`, `ok` asserts in `test_services_endpoints.py`).
- `py -3.7 -m py_compile` on all changed Mod files → clean.
- `python mod/build_package.py` → `Sensewright.package` (16,864 B, 43 resources, mood_type `<E>`).
- `python mod/build.py` → `Sensewright.ts4script` (95,981 B, 3.7 bytecode).
- Deployed with `scripts/install-mod.ps1`.
- Installed sidecar boot-tested (`/v1/health` 200, `handle_chat` returns `ok`).

---

# Playtest #3 (2026-10-03) — chat grounding & family-tree hallucination

> **Status:** ✅ CLOSED — BUG-08/09 fixed with regression tests.
> **Basis:** sidecar log `llm.route purpose=sim.chat ... tokens≈600` with every reply
> generic, plus an SMS chat in which a Sim mentioned a brother absent from the
> genealogy. Root causes traced from the wire contract, the prompt templates and the
> census family-link collection.

## Summary

| ID | Bug | Severity | Status |
|----|-----|----------|--------|
| BUG-08 | Chat replies are generic/repetitive — `player_name`, `friendship` and the conversation history never reach the LLM | High | ✅ Fixed |
| BUG-09 | Sims hallucinate relatives (a "brother") — the family tree is collected but never grounded into the prompt | High | ✅ Fixed |

## BUG-08 — chat context was almost empty (player name, trust, history) ✅

**Symptom.** Every SMS reply looked like the same generic greeting.

**Root cause.** Four independent gaps made the `sim.chat` prompt degenerate:
1. The Mod never sent `player_name` — `post_chat`/`post_hey` omitted it, so the prompt
   rendered `"Trust with : 1"` / `"Message from : ..."`.
2. `friendship` was never available — the full census (`_collect_full_sim_census`)
   does not emit a per-sim friendship and the Mod did not send one, so
   `sim.get("friendship", 0.0)` was always `0.0` → `trust` pinned at the lowest tier.
3. The short-term chat buffer (`state.chat_buffers`) was written by
   `append_chat_turn` but **never read** by `handle_chat`, so every message was
   processed as a standalone greeting with no prior turns.
4. The `user_phone_sms` prompt dropped `memories_text` (only `pc_chat` had it), so SMS
   had no memory/backstory grounding.

**Fix.**
- Mod (`http_client.py`, `chat_ui.py`): resolve the hidden confidant's name and the
  `sim ↔ confidant` friendship track and send both as `player_name`/`friendship`.
- Sidecar (`services.handle_chat`): prefer the wire `friendship`, fall back to census;
  pass `state.chat_turns(sim_id)` as `history` and the resolved family as `family`.
- `llm/context.py` renders `history_hint` and `family_hint`; the locale `sim.chat`
  templates now include history + memories for all three channels.

## BUG-09 — relatives hallucinated because the family tree never reached the LLM ✅

**Symptom.** An SMS Sim mentioned a brother that does not exist in the family tree.

**Root cause.** `_collect_full_sim_census` attempted to read `rel.target_sim_id` and
`rel.relationship_bits`, neither of which exists on TS4's `Relationship` object (it
exposes `sim_id_a`/`sim_id_b` and `get_all_bits`). The `family_links` list was
therefore always empty, and nothing in `build_chat_context`/`handle_chat` ever fed
family data into the prompt — the model, asked to roleplay a real person with no
family grounding, invented a sibling. (A second latent crash: `background_scheduler.
priority_class` treated `family_links` as `list[int]` and would `int(dict)` on the
real dict shape.)

**Fix.**
- Mod (`state_collector._collect_family_links`): use S4CL
  `CommonRelationshipUtils.get_sim_info_of_all_sims_with_relationship_bit_generator`
  with `instanced_only=False` and `CommonRelationshipBitId` to build a stable,
  language-independent `[{target_sim_id, relationship}]` list.
- Sidecar (`services._resolve_family` + `agent.chat.family_relation_label`): resolve
  each edge to `{name, relation}` and inject a localized `family_hint`
  ("Sua família: … Nunca invente parentes que não estejam listados aqui.").
- Sidecar (`god.background_scheduler._family_link_ids`): accept both the canonical dict
  shape and the legacy bare-int shape.

## Verification performed (2026-10-03)

- `cd sidecar && python -m pytest -q` → **647 passed** (10 new: chat history/family,
  `family_relation_label`, dict-shape `family_links`, `services._resolve_family`).
- `py -3.7 -m py_compile` on changed Mod files → clean.
- `python -m py_compile` on changed Sidecar files → clean.

---

# Context-awareness pass (2026-10-03) — every interaction carries scene context

> **Status:** ✅ CLOSED — the scene context (location / relationship / selected action)
> is now collected and grounded into every dialogue path.
> **Basis:** requirement review — "any interaction must consider context". Validated the
> three paradigms (sim↔sim `sim.social`, player↔sim `sim.chat`, god↔sim `god.puppeteer`)
> and found the setting, the pair relationship and the chosen interaction text were never
> sent to the LLM.

## BUG-10 — dialogues ignored location, relationship and the selected action ✅

**Symptom.** The tone never changed between "chatting on a sofa at home" vs "outdoors in
a public park with a stranger"; the specific pie-menu action (tell a joke / complain about
the weather / kiss) and the queued follow-up action against the same Sim were invisible to
the model, so dialogue could not reference what was actually happening.

**Root cause.** The wire + prompt carried only mood/activity class-names:
- The Mod reported `activity = interaction.__name__` (a Python class name, e.g.
  `MixerInteraction`), never the localized menu title.
- No venue / indoor-outdoor / home-away signals were collected.
- No per-pair friendship/romance was read from the imported relationship edges.
- `build_social_context`/`build_chat_context`/`run_puppeteer` never carried any of this.

**Fix.**
- Mod (`state_collector`): collect per-Sim `is_outside`/`is_at_home`, the localized
  `interaction_text` (via `LocalizationHelperTuning.get_raw_text(display_name)`), and
  `queued_interaction_texts`; collect zone `venue_type`/`is_residential`.
- Mod (`http_client`/`main`): send `venue` on the autonomy tick; store it in
  `state.zone_context`.
- Sidecar (`agent.social`): add `location_context` / `relationship_context` /
  `action_context` + `relationship_tier` (stranger→acquaintance→friend→close→family).
- Sidecar (`services`): `sim.social` now passes location + relationship + action;
  `sim.chat` passes location + action (on top of family/history/trust from BUG-08/09).
- Sidecar (`god.puppeteer.run_puppeteer`): ground the orchestrated approach in the same
  scene context.
- `llm/context.py`: renders `location_hint` / `relationship_hint` / `action_hint` (and the
  previously-unused `asymmetric_directive` for catalyst puppeteering) into the prompts.
- Locales: added `enums.inside_outside`/`home_away`/`relationship`/`venue` and the hint
  anchors in en-US + pt-BR.

### Native relationship feedback (friendship/rivalry delta)

The in-game outcome of an interaction (friendship up/down, rivalry up) is read **before**
the prompt is sent, so the tone follows the real feedback:

- Mod (`state_collector`): when a social target is resolved, read the fresh
  `social_friendship`/`social_romance` via `CommonRelationshipUtils` and report them in
  the delta.
- Sidecar (`agent.social.relationship_context`): compare the fresh value against the census
  baseline and derive `friendship_delta`/`romance_delta`; `relationship_tier` now maps
  negative friendship to `rival`.
- `llm/context.py`: renders the delta, e.g. `Relação: amigos, amizade 45 (+5)` or
  `Relação: rivais, amizade -22 (-8)`.

## Verification performed (2026-10-03)

- `cd sidecar && python -m pytest -q` → **656 passed** (9 new: scene-context helpers,
  `build_social_context` location/relationship/action, native feedback delta).
- `py -3.7 -m py_compile` on changed Mod files → clean.
- `python -m py_compile` on changed Sidecar files → clean.
