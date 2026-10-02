# The 33 Purposes (Canonical Catalog)

Each purpose has a stable ID, a tier (driving SLO + token budget + concurrency), input/output
token budgets, a trigger, a SQLite artifact, and an in-game consumer. All 33 have deterministic
0-key fallbacks.

> For the current wiring status of each purpose (Full / Partial / Fallback-only), see
> [`status.md`](status.md).

## Domain: `sim` (13)

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

## Domain: `god` (8)

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

## Domain: `world` (4)

| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `world.npc.backstory` | bg | Recurring townie without story | `sims.background` (NPC) | Seed for profile + god.cast |
| `world.household.chronicle` | bg | End of in-game day | `neighborhoods.chronicles` | Mailbox + ops.recap + god.plan |
| `world.gossip` | bg | Public salient event / snoop | RumorNode in neighborhoods | Social dialogues + phone SMS |
| `world.aftermath` | bg | Post-climax (salience ≥ 2.0) | durable intents + zeitgeist shift | Alters relations and weather |

## Domain: `mem` (4)

| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `mem.consolidate` | bg | 300s chat silence / zone change | consolidated memory + player_facts | FTS5 index + player bond |
| `mem.compact` | deep | ≥ 20 consolidated memories | compact memory (archive 15) | Keeps context window lean |
| `mem.legacy` | deep | Death, marriage, birth | legacy memory (immune to decay) | sim.lifestory + epitaph |
| `mem.relationship.review` | deep | Deep window (active edges) | `relationships.qualitative_note` | Native sentiments + chat/social |

## Domain: `evo` (2)

| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `evo.reflect` | deep | Sleep (≥8 ev) / mirror | updates `current_demeanor` | Phase shift preserving `core_personality` |
| `evo.trait` | deep | Trauma/belief > 0.85 / habit | likes/dislikes / trait swap | trait_tracker + Accept banner |

## Domain: `ops` (2)

| ID | Tier | Trigger | Artifact | Consumer |
|----|------|---------|----------|----------|
| `ops.recap` | bg | `lifecycle/session-start` | `{headline, recap_text}` | "Previously on..." banner |
| `ops.panel.summary` | bg | State change / panel open | 2-line diagnostic summary | Quick Menu header + Web Studio |
