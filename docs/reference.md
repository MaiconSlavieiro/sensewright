# Reference

Look-up material for contributors: the canonical catalog of the 33 purposes and the localization engine / translation contribution guide.

**On this page**

- [Purpose Catalog](#purpose-catalog)
- [Localization and Translation](#localization-and-translation)

---

## Purpose Catalog

Each purpose has a stable ID, a tier (driving SLO + token budget + concurrency), input/output
token budgets, a trigger, a SQLite artifact, and an in-game consumer. All 33 have deterministic
0-key fallbacks.

> For the current wiring status of each purpose (Full / Partial / Fallback-only), see
> [`project-status.md`](project-status.md).

### Domain: `sim` (13)

| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `sim.chat` | interactive | Phone / PC (`sw.chat`) | memory thought + speech + intents | Chat card + Hidden SimInfo |
| `sim.profile` | bg / interactive | New seat (bg) / chat (int) | `sims.profile` (PROFILE_SHAPE) | All sim prompts + GetToKnow |
| `sim.impulse` | realtime | Zone pulse (full tier) | memory thought + 1 non-verbal intent | Sim mood/action on lot |
| `sim.reaction` | realtime | Event salience ≥ 1.5 | memory thought + speak intent | Immediate reaction to causer |
| `sim.social` | realtime | Pair in conversation (pre-flight ok) | `{a_line, b_line, topic, impact}` | Compact dialogue card |
| `sim.social.close` | bg | End of ConversationSession | social memory + rumor contagion | Social history + world.gossip |
| `sim.dream` | deep | Start of sleep (1×/night) | dream memory + dream_urge | Sleep balloons + morning moodlet tooltip |
| `sim.cognition` | deep | Post-dream / bootstrap | `profile.daily_plan` + biases | Commodity buffs + Web Studio |
| `sim.sleep` | deep | Sleep (if salient event) | `profile.psyche_blocks` | Sim prompts + evo.trait trigger |
| `sim.diary` | bg | Write diary / end of day | diary memory (1st person) | Diary tooltip + Snoop |
| `sim.lifestory` | deep | Every 7 sim days / mem.legacy | `profile.life_story` | ContextAssembler + physical book |
| `sim.aspiration` | deep | Aspiration change/milestone | `profile.ambition` | Mid-term goals in cognition |
| `sim.background.expand` | bg | 1× for family/close friends | 3 backstory memories | Revealed via GetToKnow |

### Domain: `god` (8)

| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `god.zeitgeist` | bg | Onboarding / panel edit | `neighborhoods.zeitgeist` | Dreams, weather, god.plan |
| `god.plan` | deep | No arc / end of arc | `arcs` (beats + god_whisper_hint) | god.scene + dream whispers |
| `god.cast` | bg | Beat needs catalyst NPC | `arcs.cast` (NpcSheet) | spawn_npc lever (VisitSituation) |
| `god.scene` | bg | Beat enters armed | `beat.scene_draft` + scene_subtext | Prep catalyst objective for P18 |
| `god.puppeteer` | realtime | Catalyst NPC + target on lot | lease + approach + objective | Controls catalyst + subtext |
| `god.react` | realtime | End of beat interaction | branched next beat (pivot) | Adapt arc to agent's choice |
| `god.narration` | realtime | Beat start / intervention | 1 atmospheric line (≤80 tok) | SPECIAL_MOMENT banner |
| `god.background` | bg | BackgroundScheduler queue | `sims.background` | Scene context + chronicles |

### Domain: `world` (4)

| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `world.npc.backstory` | bg | Recurring townie without story | `sims.background` (NPC) | Seed for profile + god.cast |
| `world.household.chronicle` | bg | End of in-game day | `neighborhoods.chronicles` | Mailbox + ops.recap + god.plan |
| `world.gossip` | bg | Public salient event / snoop | RumorNode in neighborhoods | Social dialogues + phone SMS |
| `world.aftermath` | bg | Post-climax (salience ≥ 2.0) | durable intents + zeitgeist shift | Alters relations and weather |

### Domain: `mem` (4)

| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `mem.consolidate` | bg | 300s chat silence / zone change | consolidated memory + player_facts | FTS5 index + player bond |
| `mem.compact` | deep | ≥ 20 consolidated memories | compact memory (archive 15) | Keeps context window lean |
| `mem.legacy` | deep | Death, marriage, birth | legacy memory (immune to decay) | sim.lifestory + epitaph |
| `mem.relationship.review` | deep | Deep window (active edges) | `relationships.qualitative_note` | Native sentiments + chat/social |

### Domain: `evo` (2)

| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `evo.reflect` | deep | Sleep (≥8 ev) / mirror | updates `current_demeanor` | Phase shift preserving `core_personality` |
| `evo.trait` | deep | Trauma/belief > 0.85 / habit | likes/dislikes / trait swap | trait_tracker + Accept banner |

### Domain: `ops` (2)

| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `ops.recap` | bg | `lifecycle/session-start` | `{headline, recap_text}` | "Previously on..." banner |
| `ops.panel.summary` | bg | State change / panel open | 2-line diagnostic summary | Quick Menu header + Web Studio |


---

## Localization and Translation

Sensewright uses a **manifest-driven, zero-hardcode i18n engine** with a 4-layer cascade:

```
User Overlay (data/locales/) → Active Locale (sidecar/locales/) → Base Subtag (e.g., pt) → Manifest Default (en-US)
```

The engine itself is documented in [`architecture.md`](architecture.md) §6.

### File Topology

```
PlaintextMods/Sensewright/
├── Sensewright.ts4script          # Embedded fallback locales/
├── Sensewright.package            # Compiled STBLs from locales/stbl/
├── data/
│   └── locales/                   # [LAYER 1 — USER/COMMUNITY OVERLAY]
│       ├── manifest.override.json # Optional: register new languages
│       ├── ui/                    # Drop-in: <locale>.json (overrides Mod UI)
│       └── content/               # Drop-in: <locale>.json (overrides Prompts/Fallbacks)
└── sidecar/
    └── locales/                   # [LAYER 2 — OFFICIAL BUNDLE]
        ├── manifest.json          # Single source of truth
        ├── ui/
        │   ├── en-US.json
        │   └── pt-BR.json
        └── content/
            ├── en-US.json
            └── pt-BR.json
```

### Manifest Contract (`manifest.json`)

```json
{
  "schema_version": 2,
  "default_locale": "en-US",
  "locales": [
    {
      "code": "en-US",
      "base_subtag": "en",
      "display_name": "English (US)",
      "llm_language_name": "English",
      "ts4_stbl_byte": "0x00",
      "ts4_client_tokens": ["eng_us", "en_us", "en-us", "en"],
      "direction": "ltr"
    },
    {
      "code": "pt-BR",
      "base_subtag": "pt",
      "display_name": "Português (Brasil)",
      "llm_language_name": "Português do Brasil (pt-BR)",
      "ts4_stbl_byte": "0x11",
      "ts4_client_tokens": ["por_br", "pt_br", "pt-br", "pt"],
      "direction": "ltr"
    }
  ]
}
```

### Contributing a Translation

1. Fork the repo.
2. Add `<new-locale>.json` under `sidecar/locales/ui/` and `sidecar/locales/content/`.
3. Add the locale entry to `manifest.json` (copy an existing entry, adjust `code`, `base_subtag`, `ts4_stbl_byte`, `ts4_client_tokens`, `llm_language_name`).
4. Run `make package` to compile STBLs into `.package`.
5. Submit PR.

### Gender Inflection & List Rotation

- **Gender macro**: `{g:masculine|feminine|neutral}` in any string. At runtime, the engine picks the correct form based on the Sim's gender (`M`/`F`/`N`).
- **List rotation**: Any string value can be a `list[str]`. The engine picks one deterministically via `hash(seed + key) % len(list)`. Seed defaults to `sim_id:sim_hour`.
