# Low-Level Map Details Report

This document is designed for an in-depth, low-level analysis of map generation across 3 different maps.

## Data Extraction Mechanics
We parse the game's memory (`src/game_data.py`) to extract static addresses and structures containing map information:
- `GameManager` / `MapController` / `MapGenerationController`
- From `MapController`, we retrieve `current_map_ptr` and `current_stage_ptr`.
- Map activities are located in the `interactables_dict`, which maps string Labels to their current and max capacities.

Please fill in the data for each of the 3 maps below, including memory addresses and system variables, to analyze the generation patterns.

---

## Map 1: Graveyard

### Basic Metadata:
* **Map Seed**: 1999968532
* **Stage Index / Number**: (0 / 1)
* **Game Time (seconds)**: 7.143916606903076
* **Stage Time (seconds)**: 0.0

### Low-Level Pointers (Hex):
* **Game Manager Ptr**: 0x20f5a8fd240
* **Current Map Ptr**: 0x20f412adee0
* **Current Stage Ptr**: 0x20f412a8c60
* **Run Config Ptr**: 0x20f57971f50

### Activities (Max / Current):
* Crypt Chests: 6 / 0
* Crypt Pots: 25 / 0
* Charge Shrines: 22 / 0
* Greed Shrines: 12 / 0
* Microwaves: 8 / 0
* Pumpkin: 105 / 0
* Gravestones: 22 / 0
* Chests: 69 / 0
* Bald Heads: 6 / 0
* Challenges: 5 / 0
* Boss Curses: 4 / 0
* Moais: 4 / 0
* Magnet Shrines: 6 / 0
* Shady Guy: 3 / 0

**Unique Map Mechanics (Graveyard):**
- Standard `Pots` are completely replaced by `Crypt Pots` (25 per crypt).
- Features specialized `Crypt Chests` (6 per crypt) in addition to the standard `Chests` (69 on the main map).
- Presence of map-specific interactables: `Pumpkin` (105) and `Gravestones` (22).
- The entire progression cycle (`crypt1` -> `main map` -> `crypt2` -> `boss` -> `post-boss main map`) is loaded as a single entity into memory. The pointers remain completely static throughout all these transitions: **`Current Map Ptr` = 0x20f412adee0**, and **`Current Stage Ptr` = 0x20f412a8c60**.
- The raw `stage_index` also remains effectively useless for tracker-side phase detection here. In live validation, Graveyard continued to report raw **`stage_index = 0`** across the different sub-phases, so software should not expect a clean raw stage progression inside this map.
- **Timer Behavior**:
  - **Crypt 1 Start Room**: The timer does **not** start immediately on spawn. The crypt timer begins only after the player exits the initial room.
  - **Crypt 1 / Crypt 2**: The UI uses a reverse countdown, but the relevant memory field is a dedicated **`crypt_timer`** that ticks **upwards**. The visible countdown duration is **not fixed at 1:30**; it varies by seed. After the visible timer reaches `00:00`, the UI clamps at `00:00`, while memory `crypt_timer` continues to increase.
  - **Main Map**: The main outdoor phase uses the regular `stage_timer` path. The UI behaves like a **16:00** countdown (`960s` limit), then transitions into Ghost Phase overtime formatting.
  - **Boss Room**: On entry, the UI initially shows **16:00**, but when the final boss actually appears the displayed timer jumps down to **10:00**. This phase still reuses the same raw map/stage identity as the rest of Graveyard.
  - **Post-Boss Ghost Phase**: After the boss dies, there is a short transition (roughly `10s`) before the ghost/final swarm phase starts. The most reliable dedicated timer here is **`final_swarm_timer`**, which ticks upward and continues seamlessly even if the player stays in the boss room for a while and only later returns through the portal to the main map.
- **Crypt Boss Mechanics**: In both Crypt 1 and Crypt 2, when the countdown timer ends, a specific boss named **Spooky Steeve** spawns.
- **Final Boss Mechanics & Ghost Phase Transition**: Players must manually summon and defeat 4 mini-bosses on the Main Map to get 4 keys, unlock Crypt 2, and eventually navigate to the Final Boss room. After the boss dies, the game transitions into a shared post-boss ghost phase. The important practical detail is that this post-boss timer is **shared between the boss instance and the returned main map**; leaving through the portal does **not** restart it from zero. For tracker logic, `final_swarm_timer` is a much safer source of truth here than trying to reconstruct the phase from `stage_ptr`, `stage_index`, or raw room changes.
- **Dynamic Interactables & Object Mapping**:
  - `Crypt Pots` and `Crypt Chests` exist **only** inside the crypts. When exiting to the Main Map or entering the Boss room, they are completely removed from the memory dictionary.
  - On the Main Map, standard `Pots` are entirely replaced by **`Pumpkins`** (105).
  - In addition to standard `Greed Shrines` (12), the Main Map features **`Gravestones`** (22) which serve a similar or supplementary role.
  - The number of `Microwaves` is variable and can range from 4 to 8 per run.
  - For tracker-side Graveyard detection, the strongest practical markers are `Pumpkin`, `Gravestones`, `Crypt Chests`, `Crypt Pots`, or `Chests.max == 69`. The mere absence of standard `Pots` is **not** strong enough to use as a standalone proof.

---

## Map 2: Forest

### Basic Metadata
* **Map Seed**: 1103147420
* **Game Manager Ptr**: 0x20fc8eaff30
* **Current Map Ptr**: 0x20f41233000 (Remains static across all 4 stages)
* **Run Config Ptr**: 0x20fc8cb7280

### Stage Breakdown & Progression

#### Stage 1
* **Stage Index**: 0
* **Stage Ptr**: `0x20f411fe000`
* **Interactables (Baseline)**: 55 Pots, 46 Chests, 15 Charge Shrines, 8 Greed Shrines.
* **Timer Behavior**: Base duration is **10 minutes**. Ticks normally from `0.0`. Upon stage completion/transition, `Stage Time` forcefully jumps forward (to ~590s) to artificially trigger the Ghost Phase.

#### Stage 2
* **Stage Index**: 1
* **Stage Ptr**: `0x20f412a8ea0` (Changed from Stage 1)
* **Interactables Shift**: Dictionary limits change dynamically (e.g. Microwaves `1 -> 2`, Boss Curses `1 -> 4`, Challenges `2 -> 7`).
* **Timer Behavior**: Base duration is **9 minutes**. Resets to `0.0` at start. Another massive jump forward (to ~530s) occurs at the end of the stage.

#### Stage 3
* **Stage Index**: 2
* **Stage Ptr**: `0x20f412a8d80` (Changed from Stage 2)
* **Interactables Shift**: Dictionary updates again (Magnet Shrines `1 -> 4`, Shady Guy `1 -> 2`). Midway through the stage (or just before transition), `Pots` max drops from 55 to 39, and `Chests` max from 46 to 35.
* **Timer Behavior**: Base duration is **8 minutes**. Resets to `0.0` upon entering.

#### Stage 4 (Boss Room)
* **Stage Index**: For BonkScanner's current tracking model, this should be treated as a **virtual Stage 4 layered on top of raw Stage 3 behavior**. The live tracker currently does **not** consume a distinct raw `stage_index=3` here; it promotes Stage 3 to Stage 4 via heuristics.
* **Stage Ptr**: `0x20f412a8d80` (**CRITICAL: Identical to Stage 3!**)
* **Identification**: The game does *not* load a new Stage Ptr for the Boss Room. It is technically the same stage object in memory as Stage 3, so the tracker must detect boss-room entry from resets/anomalies rather than from a clean pointer transition.
* **Interactables Shift**: To clear the room for the boss, the game drastically modifies the dictionary: `Pots` max drops to **0**, and `Chests` max drops to **4** (presumably boss rewards).
* **Timer Behavior**: Base duration is **10 minutes**. `Stage Time` resets to `0.0` when entering the boss room. Upon killing the boss (or triggering the phase), `Stage Time` jumps instantly (to ~590s) to trigger the Ghost Phase.

---

## Map 3: Desert

### Basic Metadata
* **Map Seed**: 1103147420 (Same run/seed assumption)
* **Game Manager Ptr**: 0x20fc5fc99b0
* **Current Map Ptr**: 0x20f412331c0 (Remains static across all stages)
* **Run Config Ptr**: 0x20fc5fc99b0

### Stage Breakdown & Progression

#### Stage 1
* **Stage Index**: 0
* **Stage Ptr**: `0x20f411fe480`
* **Interactables (Baseline)**: 55 Pots, 46 Chests, 15 Charge Shrines, 8 Greed Shrines.
* **Timer Behavior**: Base duration is **10 minutes**. Upon completion, timer artificially jumps to ~590s (triggering Ghost Phase).

#### Stage 2
* **Stage Index**: 1
* **Stage Ptr**: `0x20f411fe360` (Changed from Stage 1)
* **Interactables Shift**: Minor dictionary reshuffles.
* **Timer Behavior**: Base duration is **9 minutes**. Timer resets to `0.0`. Upon completion, timer jumps to ~530s.

#### Stage 3
* **Stage Index**: 2
* **Stage Ptr**: `0x20f411fe240` (Changed from Stage 2)
* **Interactables Shift**: Dictionary reshuffles dynamically upon entry.
* **Timer Behavior**: Base duration is presumably **8 minutes**. Timer resets to `0.0` at start. Notably, there was *no* artificial jump at the end of this stage in the log; it simply reset to `0.0` for the Boss Room.

#### Stage 4 (Boss Room)
* **Stage Index**: For BonkScanner's current tracking model, this should be treated as a **virtual Stage 4 layered on top of raw Stage 3 behavior**. The live tracker currently does **not** consume a distinct raw `stage_index=3` here; it promotes Stage 3 to Stage 4 via heuristics.
* **Stage Ptr**: `0x20f411fe240` (**CRITICAL: Identical to Stage 3!**)
* **Identification**: Exactly like Forest, the Boss Room is not a new Stage in memory. It uses the Stage 3 pointer, so tracker-side Stage 4 detection depends on resets/jumps rather than on a new raw stage identity.
* **Interactables Shift**: To clear the room, `Chests` max drops to **0**, and `Pots` max drops to **1**.
* **Timer Behavior**: Base duration is **10 minutes**. Timer resets to `0.0` when entering. After the boss kill, the timer instantly jumps to ~591s to trigger the Ghost Phase.

---

## Grover's Bird's-Eye View: Map Comparative Analysis

Looking across **Graveyard**, **Forest**, and **Desert**, the game employs distinct architectural tricks to handle map progression and timer logic. A tracker looking for standard Stage ID increments will fail if it doesn't account for these three paradigms:

### 1. The Monolith (Graveyard)
* **Structure**: The entire run (Crypts, Main Map, Boss) is a single, static `Stage Ptr`.
* **Transitions**: Progression is entirely illusionary. You never leave the stage in raw memory terms; the game teleports the player and violently hot-swaps the memory dictionary (injecting/removing `Crypt Pots` and `Crypt Chests` dynamically).
* **Raw IDs**: `Current Stage Ptr`, `Current Map Ptr`, and even raw `stage_index` are not reliable sub-phase separators here.
* **Timers**: Timers are completely non-linear. Crypt UI uses a reverse countdown while memory `crypt_timer` ticks upward and continues past `00:00`. The main outdoor phase uses `stage_timer` with a `960s` limit. The post-boss ghost phase is best modeled with a dedicated `final_swarm_timer` that continues across the boss room and the returned main map.

### 2. The False Climax (Forest & Desert)
* **Structure**: Stages 1, 2, and 3 behave like normal sequential levels. For tracker purposes, the raw progression cleanly reaches Stage 3, and the Boss Room is then inferred as a virtual `Stage 4`.
* **The Boss Room Trap**: The transition to the Boss Room (tracker-side `Stage 4`) is a trap. The game **does not load a new stage**. It keeps the `Stage Ptr` from Stage 3 exactly the same, but triggers a dictionary wipe (reducing `Pots` and `Chests` max counts to near 0) and resets the `Stage Time` to `0.0`.
* **Timers**: Timers are mostly standard but feature massive artificial "fast-forwards" at the end of each stage (jumping to ~590s or ~530s) to force the Ghost Phase if the player lingers too long or kills the boss.

### Conclusion for Tracking Software (`src/live_run_tracker.py`)
Any tracker relying on `Current Stage Ptr` changes to detect room transitions will completely fail to see the boss room in Forest/Desert, and will fail to see *any* meaningful sub-phase transitions in Graveyard. In the current BonkScanner model, Stage 4 is a **derived tracker state**, not a directly trusted raw `stage_index` value. Robust tracking must monitor timer-family changes (`stage_timer` vs `crypt_timer` vs `final_swarm_timer`), `Stage Time` resets/jumps, and activity-dictionary collapses rather than relying solely on `Stage Ptr`.


---

## Comparative Analysis (Bird's-Eye View)

*This section will be populated after data from all 3 maps has been gathered.*

### 1. Identical Mechanics
*(What remains consistent across all maps? E.g., baseline number of certain shrines, pointer behavior, timer resets)*
-

### 2. Key Differences
*(What changes drastically? E.g., pot/chest limits used for stage detection, seed generation behavior, absence of specific activities)*
-

### 3. Conclusion & Integration Notes
*(How should we adapt our codebase/logic to handle these map variations safely?)*
-
