# Spike-Driven Development (SDD) Strategy

The Sims 4 Modding is inherently fragile because the EA API is undocumented, volatile, and strictly single-threaded. "Coding blind" against decompiled reference code often leads to high-latency feedback loops: building a feature, deploying it, loading the game, and watching it fail silently or crash the UI due to subtle API mismatches.

To evolve Sensewright efficiently, avoid guesswork, and eliminate repetitive attempts, we adopt **Spike-Driven Development (SDD)** for any code touching the native TS4 engine.

---

## 1. The Core Principle: Never Code Blind

Before integrating any native TS4 feature (e.g., `VisitSituation`, UI Tooltip Injection, Mailbox reading, custom Moodlets), you must **prove the EA API interaction works in isolation** inside the game engine.

No production feature is wired to the Sidecar or the `IntentBus` until its underlying "Spike" has been validated in-game.

## 2. The `sw.spike` / `sw.smoke_test` Harness

We utilize an in-game introspection harness to execute and validate spikes instantly, without restarting the game or waiting for complex LLM orchestrations.

1. **The Harness Command:** A cheat command `sw.spike <spike_name>` or `sw.smoke_test` that triggers a specific, isolated piece of code.
2. **Minimal Surface Area:** A spike script contains *only* the minimum code required to invoke the target EA API.
3. **Direct Feedback:** The harness catches all exceptions (`lastException`) locally and logs the exact outcome to a dedicated file: `mod_logs/Sensewright_Spike.log`.

## 3. The "Data Probe" Spike Philosophy

A Spike is not just a test; it is an **Observability Probe**. 

Instead of guessing what an object contains, a Spike actively triggers an event, dumps all available properties of that event into an in-game UI popup (so the human sees it instantly), and writes a deep JSON structure to a log file (so the Agent can analyze the exact engine structure).

Even for features that are theoretically "implemented" in our code, if they haven't been validated in-game, we will write a Spike for them to confirm reality.

### Step 1: Define the Probe
Identify the action to intercept (e.g., "Sim is doing an interaction").

### Step 2: Write the Spike Script
Create a script that:
1. Hooks into the event.
2. Extracts every possible piece of data (IDs, localized strings, targets, internal names).
3. Displays a summary in an in-game Notification or Dialog.
4. Serializes the raw data to `mod_logs/Sensewright_Spike.log`.

### Step 3: In-Game Validation
1. Build the mod (`make mod`) with the spike included.
2. Reload the game or run the cheat command `sw.spike visit_situation`.
3. Observe the result in-game and in `Sensewright_Spike.log`.
4. Iterate on the spike script until it works perfectly.

### Step 4: Facade Integration
Once the spike succeeds:
1. Extract the working code into a clean, defensive function inside `mod/sensewright_mod/engine_facade.py`.
2. Delete or archive the spike script.
3. Wire the `engine_facade` function to the `tool_executor` or `IntentBus`.

## 4. Strategic Benefits

- **Zero Guesswork:** You know exactly what the EA API expects before writing production logic.
- **Fast Feedback Loop:** Testing a spike via a cheat command takes 2 seconds. Testing a full feature might take 5 minutes of gameplay to set up the conditions.
- **Architectural Isolation:** All EA API idiosyncrasies are caught early and encapsulated in the `engine_facade`, protecting the rest of the Mod and the Sidecar from native engine chaos.
- **Reduced Save Bloat:** Spikes can be designed to clean up after themselves, avoiding the creation of orphan Sims or objects in the player's `.save` file during development.

## 5. Catalog of Master Spikes (Data Probes)

These are the central spikes designed to map the engine's reality. They cover both pending features and theoretically implemented ones that lack in-game confirmation.

### 1. `spike_interaction_probe` (Action & Context Reality)
**Goal:** Discover exactly what data we can extract when a Sim performs an action.
**How it works:** 
- Listens to any interaction started by the active Sim.
- Collects: The descriptive localized name of the action (from the game), the internal tuning name, the target (Sim vs Object), and the relationship bits between actors.
- **Output:** In-game popup showing `"Sim is doing: [Action] with [Target]"` + JSON log dumping the entire interaction object structure.
- **Value:** Validates if our `sim.social` context is receiving real action names or garbage.

### 2. `spike_ui_injection_probe` (Visual Capability Reality)
**Goal:** Prove exactly which UI elements can accept dynamic strings in the current patch.
**How it works:**
- Triggers a command that simultaneously attempts to:
  1. Overwrite a Moodlet/Buff text.
  2. Spawn a Sleep Balloon over the Sim.
  3. Change the tooltip of a nearby object (like a Diary or Mirror).
- **Output:** The player visually confirms what appeared + JSON log of which API calls threw exceptions.
- **Value:** Unblocks the Diary, Sleep Balloons, and dynamic Moodlets without guessing.

### 3. `spike_routing_probe` (NPC Casting & Movement Reality)
**Goal:** Prove we can instantiate an off-lot Sim and physically force them to a location.
**How it works:**
- Grabs a random townie ID not currently on the lot.
- Forces the game to spawn them and push a `RouteToTarget` (or `VisitSituation`) to the active lot's front door.
- **Output:** In-game alert `"Townie [Name] is spawning and routing!"` + JSON log of the Situation ID and routing path success/failure.
- **Value:** Validates the foundation of the God Director (`god.cast` and `god.puppeteer`).

### 4. `spike_relationship_probe` (Social Graph Reality)
**Goal:** Prove what relationship data actually exists between two Sims.
**How it works:**
- Reads the active Sim and a target Sim.
- Attempts to extract sentiments, romance, friendship, and "secrets" using EA APIs.
- **Output:** In-game Dialog listing the exact numerical values and sentiment names + JSON log of the raw `Relationship` object.
- **Value:** Confirms if our memory compaction and `sim_GetToKnow` logic is based on real EA data structures or outdated assumptions.

By executing these 4 Observability Probes, the Agent will receive a perfect map of the TS4 engine's data structures, allowing us to build the real features with surgical precision.

## 5.1. Validation status of the 4 master probes (2026-10-05)

The 4 probes were implemented (`mod/sensewright_mod/spikes.py`, console commands
`sw.spike <name>` / `sw.smoke_test`) and executed in-game (build 1.128.90.1030).
Full defect log: [`operations.md`](operations.md) + [`research/engine_api_notes.md`](../research/engine_api_notes.md) §10–§12.

| Probe | Status | Notes |
|---|---|---|
| `interaction` | ✅ validated | Reads `queue.running` + `si_state` (not `si_state.current_interaction`, which is empty during socials). |
| `ui_injection` — buff | ✅ validated | Buff roundtrip passes with an int tuning id; `mood_type` must be numeric `<T>`, not `<E>` (reversed BUG-07). |
| `ui_injection` — balloon | 🟡 best-effort | `BalloonRequest.__init__` needs the full `(icon_object, overlay, balloon_type, priority, duration, delay, …)` signature. |
| `ui_injection` — tooltip | 🟡 client-side | No server-side `TooltipComponent`; tooltip/display name come from `obj.tooltip_text`/`obj.display_name`. |
| `routing` | ✅ validated | `services.get_zone_situation_manager()` (not `get_situation_manager`) + `create_visit_situation(sim)` spawns townies with a `situation_id`. |
| `relationship` | 🟡 partial | `friendship`/`romance` read fine, but **`bits` returned `[]`** even for a high-friendship pair; sentiments are not read at all. |

## 6. Phase-2 spikes (proposed — pending implementation)

Remaining "coded blind" surfaces worth proving before building on top of them.

### 1. `relationship_bits` (Relationship bits + sentiments) — highest value
- **Goal:** read a relationship's *bits* (romantic/friend/family) and its *sentiments*
  correctly, and confirm which accessor works (`get_all_bits()`, `RelationshipTrack`,
  the sentiment tracker, `CommonRelationshipUtils`).
- **Why:** the current `relationship` probe returned `bits: []` for a pair with
  `friendship=88.81`. `sim.social` relationship tier (rival/family), `mem.relationship.review`,
  and sentiment feedback all depend on this.
- **Output:** console + JSON log of every relationship bit and sentiment between the
  active Sim and a target.

### 2. `mood_effect` (does `set_mood` actually move the needle)
- **Goal:** apply `buff_mood_happy`, then read the Sim's current mood and confirm it
  changed to happy.
- **Why:** we proved the buff *applies* without error, but not that the mood *changes*.
  This is the same "applies without effect" class as the `mood_type` bug just fixed.
- **Output:** before/after mood value + a pass/fail.

### 3. `lifecycle` (death / marriage / birth events)
- **Goal:** trigger (or observe) `S4CLSimDiedEvent`, `S4CLSimPregnancyEndedEvent`,
  `S4CLSimRelationshipBitAddedEvent` and confirm they fire with usable data
  (`death_type`, `sim_info_a/b`, `relationship_bit`).
- **Why:** `lifecycle_hooks.py` is wired but never exercised in-game; `mem.legacy`
  (P28) and `sim.lifestory` chapters depend on it.
- **Output:** JSON log of each event's payload fields.

### 4. `trait_levers` (traits + relationship-bit application) — secondary
- **Goal:** apply/remove a trait and a relationship bit via `native_hooks`
  (`set_trait`/`remove_trait`/`add_relationship_bit`) and confirm they stick.
- **Why:** `evo.trait` (P31) and relationship feedback are coded blind.

### 5. `diary_object` (custom diary placement) — secondary
- **Goal:** confirm the custom `sw_diary_object` tuning is buildable/spawnable on the
  lot (the smoke test reports `object:diary found=0`).
- **Why:** the Diary "Ler/Snoop" P2 hook currently has no target object.
