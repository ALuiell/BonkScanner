# Low-Level Map Details Report

This document is designed for an in-depth, low-level analysis of map generation across 3 different maps.

## Data Extraction Mechanics
We parse the game's memory (`game_data.py`) to extract static addresses and structures containing map information:
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
- The entire progression cycle (`crypt1` -> `main map` -> `crypt2` -> `boss`) is loaded as a single entity into memory. The pointers remain completely static throughout all these transitions: **`Current Map Ptr` = 0x20f412adee0**, and **`Current Stage Ptr` = 0x20f412a8c60**.
- **Timer Behavior**: 
  - **Crypt 1**: UI reverse countdown lasts **1:30**. Memory `Stage Time` stays frozen at `0.0`.
  - **Main Map**: Memory `Stage Time` ticks upwards normally. UI shows a 16-minute countdown. Once the 16 minutes elapse, a "Ghost Phase" begins and the UI timer starts counting upwards.
  - **Boss Room**: Memory `Stage Time` resets and ticks upwards from `0.0`. The UI displays a 16-minute countdown to defeat the final boss.
- **Crypt Boss Mechanics**: In both Crypt 1 and Crypt 2, when the countdown timer ends, a specific boss named **Spooky Steeve** spawns.
- **Final Boss Mechanics & Ghost Phase Transition**: Players must manually summon and defeat 4 mini-bosses on the Main Map to get 4 keys, unlock Crypt 2, and eventually navigate to the Final Boss room. Upon entering, players are given 16 minutes (UI countdown) to kill the boss. Once defeated, the player is dropped back onto the Main Map, and the memory variable `Stage Time` is forcefully **fast-forwarded** (e.g., jumping directly to ~597 seconds, which is ~10 minutes). This artificial jump actually causes `Stage Time` to exceed the total `Game Time`! This jump intentionally triggers the Ghost Phase (hard mode) to start almost immediately (in ~3-8 seconds) upon returning to the main map. This is a core map mechanic that seamlessly transitions the player into the ghost phase without making them wait.
- **Dynamic Interactables & Object Mapping**: 
  - `Crypt Pots` and `Crypt Chests` exist **only** inside the crypts. When exiting to the Main Map or entering the Boss room, they are completely removed from the memory dictionary.
  - On the Main Map, standard `Pots` are entirely replaced by **`Pumpkins`** (105).
  - In addition to standard `Greed Shrines` (12), the Main Map features **`Gravestones`** (22) which serve a similar or supplementary role.
  - The number of `Microwaves` is variable and can range from 4 to 8 per run.

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
* **Transitions**: Progression is entirely illusionary. You never leave the stage; the game simply teleports you and violently hot-swaps the memory dictionary (injecting/removing `Crypt Pots` and `Crypt Chests` dynamically).
* **Timers**: Timers are completely non-linear. They freeze at `0.0` inside crypts, count down via UI but tick up in memory, and jump to artificial values (~597s) upon boss death.

### 2. The False Climax (Forest & Desert)
* **Structure**: Stages 1, 2, and 3 behave like normal sequential levels. For tracker purposes, the raw progression cleanly reaches Stage 3, and the Boss Room is then inferred as a virtual `Stage 4`.
* **The Boss Room Trap**: The transition to the Boss Room (tracker-side `Stage 4`) is a trap. The game **does not load a new stage**. It keeps the `Stage Ptr` from Stage 3 exactly the same, but triggers a dictionary wipe (reducing `Pots` and `Chests` max counts to near 0) and resets the `Stage Time` to `0.0`.
* **Timers**: Timers are mostly standard but feature massive artificial "fast-forwards" at the end of each stage (jumping to ~590s or ~530s) to force the Ghost Phase if the player lingers too long or kills the boss.

### Conclusion for Tracking Software (`live_run_tracker.py`)
Any tracker relying on `Current Stage Ptr` changes to detect room transitions will completely fail to see the boss room in Forest/Desert, and will fail to see *any* transitions in Graveyard. In the current BonkScanner model, Stage 4 is a **derived tracker state**, not a directly trusted raw `stage_index` value. Robust tracking must monitor `Stage Time` resets to `0.0`, ghost-phase timer jumps, and activity-dictionary collapses rather than relying solely on `Stage Ptr`.


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
