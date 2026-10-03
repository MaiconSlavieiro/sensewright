# Sensewright v2 — Changelog

> **Branch:** `v2-remake`

Reverse-chronological record of what **changed** per session, plus the **open items**
that remain. Complements [`status.md`](status.md) (spec↔code gap) and [`bugs.md`](bugs.md)
(playtest findings) — this file records the actual edits, not the plan.

---

## 2026-10-03 — Playtest #4 fixes: personas, relationships, catalyst gating, census hygiene

Closed **BUG-11/12/13/14/15/16/17** and addressed **NOTE-02** (see [`bugs.md`](bugs.md)).

### A. `sim.profile` actually runs (BUG-11)

| # | Change | Files |
|---|--------|-------|
| 1 | `handle_census` schedules a bounded background `sim.profile` for household sims whose stored profile is still a template (deduped + RAM-guarded per session). | `services.py`, `state.py` |
| 2 | `handle_profile` regenerates when the profile is a template (empty persona), not just when it is `None`; generated personas are tagged `source="llm"`. | `services.py`, `agent/profile.py` |
| 3 | `handle_chat` kicks off a one-shot fallback generation when the persona is still empty. | `services.py` |

### B. Player confidant dedupe (BUG-12)

- `get_or_create_player_confidant` searches the hidden household for an existing member
  (name marker, then first member) before spawning a new `SimInfo`. | `native_hooks.py` |

### C. Relationship graph collection (BUG-13)

- `collect_full_census` collects edges via S4CL `CommonRelationshipUtils.get_relationships_gen`
  + `get_friendship_level`/`get_romance_level`; the engine's `Relationship` exposes
  `sim_id_a`/`sim_id_b`/`get_other_sim_id`, not `target_sim_id`/`friendship`/`romance`. | `state_collector.py` |

### D. Catalyst gate on `beat-ended` (BUG-14)

- The Mod reports the conversation peer (`target_sim_id`) with `beat-ended`.
- The sidecar gates `run_react` on whether either participant is the catalyst (leased
  puppeteer NPC or a resolved cast member); ambient chatter no longer advances the arc. | `catalyst_tracker.py`, `god/react.py`, `god/orchestrator.py`, `services.py` |

### E. Census hygiene (BUG-15/16/17)

- `age_stage` reported via `Age.name` (stripping an `Age.` prefix); sidecar normalizes legacy
  stored values in `normalize_age_stage`. | `state_collector.py`, `agent/profile.py`, `services.py` |
- `http_client._make_request` no longer sends a JSON body on GET (moves the payload into the
  query string), fixing the mailbox `/world/neighborhood` WinError 10053. | `http_client.py` |
- `gender` (`M`/`F`/`N`) collected via S4CL `CommonGenderUtils` and threaded into `sim.chat`,
  `sim.social` and `sim.profile` contexts. | `state_collector.py`, `agent/chat.py`, `agent/social.py`, `services.py` |

### F. LLM routing (NOTE-02, ops)

- `config.example.toml` documents JSON-only routing + the groq 403 user-agent issue; the
  installed `config.toml` routes JSON-only purposes to a JSON-capable free model and keeps
  `deepseek` disabled. | `config.example.toml`, `config.toml` |

### Verification

- `cd sidecar && python -m pytest -q` → **671 passed** (16 new in `test_playtest4.py`, plus
  the updated catalyst-gate assertions in `test_p2_infra.py`).
- `py -3.7 -m compileall -q mod/sensewright_mod` → clean.
- `python mod/build_package.py` → `Sensewright.package` (16,864 B, 43 resources).
- `python mod/build.py` → `Sensewright.ts4script` (100,257 B, 3.7 bytecode).
- Deployed with `scripts/install-mod.ps1`.

---

## 2026-10-03 — Chat grounding + context-aware dialogue + native relationship feedback

Requirement review: "any interaction must consider context", plus the native
relationship feedback of a sim↔sim interaction, must be grounded into the LLM prompt.
Closed **BUG-08/09/10** (see [`bugs.md`](bugs.md)).

### A. Chat grounding (player↔sim `sim.chat`)

| # | Change | Files |
|---|--------|-------|
| 1 | The Mod now sends `player_name` (hidden confidant) + `friendship` (sim↔confidant) on `/chat` and `/hey`, so the prompt no longer renders "Trust with : 1" / "Message from : …". | `mod/sensewright_mod/http_client.py`, `chat_ui.py` |
| 2 | `handle_chat` prefers the wire friendship, falls back to census, and passes the short-term chat buffer (`state.chat_turns`) as `history`. | `sidecar/.../services.py` |
| 3 | `build_chat_context` accepts `history`/`family`/`location`/`action`; `sim.chat` prompt now includes history + memories for all channels. | `agent/chat.py`, `llm/context.py`, `locales/content/*.json` |

### B. Family-tree grounding (BUG-09)

- `_collect_full_sim_census` read nonexistent `Relationship.target_sim_id`/`relationship_bits`;
  replaced with S4CL `CommonRelationshipUtils` + `CommonRelationshipBitId` (stable, instanced=False).
- `services._resolve_family` + `agent.chat.family_relation_label` inject a localized
  `family_hint` ("Sua família: … Nunca invente parentes…"). `background_scheduler._family_link_ids`
  now accepts both dict and legacy int shapes (was `int(dict)` crash). | `state_collector.py`, `services.py`, `agent/chat.py`, `god/background_scheduler.py` |

### C. Scene context (BUG-10) — location / relationship / selected action

- Mod collects `is_outside`/`is_at_home`, localized `interaction_text`
  (`LocalizationHelperTuning.get_raw_text(display_name)`) and `queued_interaction_texts`,
  plus zone `venue_type`/`is_residential` (sent on the autonomy tick). | `state_collector.py`, `http_client.py`, `main.py` |
- Sidecar adds `location_context`/`relationship_context`/`action_context` +
  `relationship_tier`; `sim.social`, `sim.chat` and `god.puppeteer.run_puppeteer` now carry
  the scene context. `llm/context.py` renders `location_hint`/`relationship_hint`/`action_hint`
  and the previously-unused `asymmetric_directive`. | `agent/social.py`, `services.py`, `god/puppeteer.py`, `llm/context.py`, `state.py`, `locales/content/*.json` |

### D. Native relationship feedback (friendship/rivalry delta)

- Mod reports fresh `social_friendship`/`social_romance` when a social target is resolved.
- `relationship_context` derives `friendship_delta`/`romance_delta` vs the census baseline;
  `relationship_tier` maps negative friendship to `rival`; the prompt renders
  e.g. `Relação: amigos, amizade 45 (+5)` / `Relação: rivais, amizade -22 (-8)`. | `state_collector.py`, `agent/social.py`, `llm/context.py`, `locales/content/*.json` |

### Verification

- `cd sidecar && python -m pytest -q` → **656 passed** (19 new across the three waves).
- `py -3.7 -m py_compile` over changed Mod files → clean.
- `python -m py_compile` over changed Sidecar files → clean.

---

## 2026-10-03 — Review hardening + Web Studio / Director / background fixes

### A. Code-review hardening (review of `a314bbf`)

| # | Change | Files |
|---|--------|-------|
| 1 | Panic state is now **readable**: added `GET /v1/config/panic` (`handle_config_panic_state`). The Web Studio previously polled a POST-only route (405 → always "not paused"). | `routers/health.py`, `services.py` |
| 2 | `priority_class` docstring corrected — the active sim is classified *before* the household check; ranking still follows `PRIORITY_ORDER` (`HOUSEHOLD > ACTIVE`). Behavior unchanged. | `god/background_scheduler.py` |
| 3 | Mods-folder detection is no longer a single `sims4.paths` guess: `_resolve_mods_folder()` walks up from `__file__`, then tries S4CL path utils, then game `paths` — all guarded. | `mod/sensewright_mod/state_collector.py` |
| 4 | Idle intent pull moved off the outbound worker onto a dedicated thread (`_intent_pull_loop`), so a slow `GET /autonomy/intents` can no longer delay lifecycle/chat/event dispatch. | `mod/sensewright_mod/http_client.py` |
| 5 | TPM pre-check is now atomic: `try_accept_and_record` reserves the estimate; `settle_reservation`/`release_reservation` reconcile it (fixes a concurrent overshoot). | `llm/limits.py`, `llm/chain.py` |
| 6 | `/v1/status` exposes a flat `limits` map again (it was shadowed by the nested `chain` dict); Web Studio "Rate Limits" restored. | `services.py`, `webui/app.js` |
| 7 | `mem.relationship.review` cadence advances only inside its callback, so a stale-epoch-dropped job retries instead of skipping a whole sim-day. | `services.py` |
| 8 | `LLMScheduler.shutdown()` releases the realtime pool on interpreter exit. | `llm/scheduler.py` |

### B. Playtest fixes (found while testing the Web Studio in-game)

- **Director Quick Menu sent wrong control keys/values.** `director_preset` → `preset`;
  `director_mode` values now uppercased (`AUTONOMOUS`/`CO_DIRECTOR`/`SANDBOX`). In-game
  theme/mode changes now persist and reach the Web Studio (it re-reads `/v1/god/controls`
  every 15 s). (`mod/sensewright_mod/panel_ui.py`)
- **Web Studio Sims tab rendered "Sim <id>" with empty profiles.** Seats only carried
  `sim_id/role/tier/lease`. `handle_seats_get` now merges census identity, stored profile,
  background and relationship edges; added a "Background" field + locale keys.
  (`services.py`, `webui/index.html`, `webui/app.js`, `webui/locales/*`)
- **Reasoning-model output rejected as "unusable".** `_extract_json` now strips
  `<thinking>/<reasoning>/<thought>` tags and falls back to the last balanced JSON object
  (deepseek-v4-pro emits prose/thinking around the payload). (`llm/scheduler.py`)

### Verification

- `cd sidecar && python -m pytest -q` → **635 passed** (12 new regression tests).
- `py -3.7 -m py_compile` over `mod/sensewright_mod/*.py` → clean (20 files).
- `python mod/build_package.py` → `Sensewright.package` (17,037 B, 44 resources).
- `python mod/build.py` → `Sensewright.ts4script` (92,361 B, Python 3.7 bytecode).
- Deployed via `scripts/install-mod.ps1` (OneDrive Mods folder).

---

## Open items (still to do)

- [ ] **`autonomy_mode` (Quick Menu "Autonomia") is unwired.** `panel_ui._set_autonomy` posts an
      `autonomy_mode` key the sidecar has no control for. Decide the mapping
      (full/reactive/off → a dial or a pause-like switch) or remove the button.
- [ ] **`deepseek-v4-pro` (reasoning model) still returns non-JSON for some purposes.** The JSON
      extractor is more tolerant now, but the durable fix is config: route JSON-only purposes to
      a JSON-capable model (OpenRouter `nemotron` free models work) or set `free_only = true` to
      block the paid deepseek provider. See `docs/bugs.md` NOTE-01.
- [ ] **Load-time event ordering.** Lifecycle events (death/marriage) fire *before*
      `session-start`, so their reactions/aftermath are scheduled at epoch 0 and dropped by the
      epoch bump (`stale_epoch_dropped epoch=0 current=1`), and the realtime lane saturates at
      load (`Realtime lane saturated; dropping event`). Start the marriage snapshot earlier, or
      buffer events until session-start.
- [ ] **Web Studio UX gaps.** The Sims tab has no auto-refresh (manual "Refresh Sims" only), and
      the God tab does not render `director_mode` (only the preset dropdown).
- [ ] **In-game Phase 6.2 validation still pending** — see [`hardening.md`](hardening.md).
- [ ] **Playtest #4 follow-up playtest.** BUG-11..17 + NOTE-02 are now fixed in code/config
      (see [`bugs.md`](bugs.md) → "Playtest #4 — diagnosis — FIXED"), but the in-game
      confirmation is still pending: `sim.profile` should run (`purpose=sim.profile` > 0),
      exactly one confidant should persist, `relationships` should fill, and only catalyst
      conversations should advance an arc. Re-verify with `scripts/install-mod.ps1` + play.

---

## Earlier waves

For P0–P4, the hardening pass, and BUG-01/02/03, see `git log` and [`bugs.md`](bugs.md).
