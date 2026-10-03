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
