# Low-Level Map Details Report

This document is designed for an in-depth, low-level analysis of map generation across 3 different maps.

## Data Extraction Mechanics
We parse the game's memory (`src/infra/memory/game_data_client.py`) to extract static addresses and structures containing map information:
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
- **`map_seed` is static too**, across every internal transition — see the live validation below for the evidence. The consequence worth stating up front: **a seed change on Graveyard means a new run, never a phase transition**, so consumers keyed on the seed have no in-run churn to defend against here.
- The raw `stage_index` also remains effectively useless for tracker-side phase detection here. In live validation, Graveyard continued to report raw **`stage_index = 0`** across the different sub-phases, so software should not expect a clean raw stage progression inside this map.
- **Timer Behavior**:
  - **Crypt 1 Start Room**: The timer does **not** start immediately on spawn. The crypt timer begins only after the player exits the initial room.
  - **Crypt 1 / Crypt 2**: The UI uses a reverse countdown, but the relevant memory field is a dedicated **`crypt_timer`** that ticks **upwards**. The visible countdown duration is **not fixed at 1:30**; it varies by seed. After the visible timer reaches `00:00`, the UI clamps at `00:00`, while memory `crypt_timer` continues to increase.
  - **Main Map**: The main outdoor phase uses the regular `stage_timer` path. The UI behaves like a **16:00** countdown (`960s` limit), then transitions into Ghost Phase overtime formatting.
  - **Boss Room**: On entry, the UI initially shows **16:00**, but when the final boss actually appears the displayed timer jumps down to **10:00**. This phase still reuses the same raw map/stage identity as the rest of Graveyard.
  - **Post-Boss Ghost Phase**: After the boss dies, there is a short transition (roughly `10s`) before the ghost/final swarm phase starts. The most reliable dedicated timer here is **`final_swarm_timer`**, which ticks upward and continues seamlessly even if the player stays in the boss room for a while and only later returns through the portal to the main map.
- **Crypt Boss Mechanics**: In both Crypt 1 and Crypt 2, when the countdown timer ends, a specific boss named **Spooky Steeve** spawns.
- **Crypt 1 Entry & Structure**:
  - **Spawn**: The run starts directly inside Crypt 1 (`stage_index = 0`, `stage_ptr` static).
  - **Timer Initiation**: `crypt_timer` ticks upward in memory but stays paused in the initial spawn room until the player exits the room boundary.
  - **Interactables & Objects**: Crypt 1 contains `Crypt Chests` (6) and `Crypt Pots` (25) which are exclusive to crypt instances in the memory dictionary.
  - **Crypt 1 Exit**: The player exits via `InteractableCryptLeave` (memory flag `hasInteracted` at `+0x60` flips to `true`; fires static action `A_FirstDungeonCompleted`). Upon exiting, `Crypt Chests` and `Crypt Pots` disappear from memory, and outdoor `stage_timer` starts.
- **Crypt 2 Entry & Key Mechanics**:
  - **Unlocking Process**: Entering Crypt 2 from the Main Map requires acquiring 4 Crypt Keys (`EItem.CryptKey` = 81).
  - **Mini-Boss Coffins**: Keys are obtained by interacting with 4 coffins on the Main Map (`InteractableCoffin`, memory flag `interacted` at `+0xA0`, static `currentGhostIndex` tracking active fights) and defeating the summoned mini-bosses.
  - **Crypt Door Interaction**: Interacting with the Crypt 2 entrance door (`InteractableCrypt`) evaluates `IsOpen()`, flips `InteractableCrypt.isDone` (`+0x70`) to `true`, and invokes `Teleport()`.
  - **Memory Transition**: Entering Crypt 2 pauses/resets outdoor `stage_timer`, restarts `crypt_timer`, and re-injects `Crypt Chests` / `Crypt Pots` into `interactables_dict`.
- **Final Boss Mechanics & Ghost Phase Transition**: Players must manually summon and defeat 4 mini-bosses on the Main Map to get 4 keys, unlock Crypt 2, and eventually navigate to the Final Boss room. After the boss dies, the game transitions into a shared post-boss ghost phase. The important practical detail is that this post-boss timer is **shared between the boss instance and the returned main map**; leaving through the portal does **not** restart it from zero. For tracker logic, `final_swarm_timer` is a much safer source of truth here than trying to reconstruct the phase from `stage_ptr`, `stage_index`, or raw room changes.
- **Final Boss Room — Deterministic Memory Markers (verified live 2026-07-24)**:
  - **`MapController.isFinalBossStage` does NOT work here.** It reads `false` inside the Graveyard boss room, mid-fight. That flag belongs to the Forest/Desert stage model; Graveyard needs its own object, below. Do not reach for it on this map.
  - **`GraveyardBossRoom`**, reached through the `RsgController` singleton:

    ```
    GameAssembly.dll + 0x2F79E50      (RsgController_TypeInfo, from script.json)
      -> read_ptr                      class ptr
      -> + 0xB8                        static fields
      -> + 0x20                        RsgController.Instance
      -> + 0x48                        roomBoss  (GraveyardBossRoom)
    ```

    Corroborated in `dump.cs` (`RsgController`, TypeDefIndex 4855): `public static RsgController Instance; // 0x20` and `public GraveyardBossRoom roomBoss; // 0x48`.
  - **Flags on the `GraveyardBossRoom` instance**:
    | Offset | Field | Meaning |
    | --- | --- | --- |
    | `+0x38` | `isFightingBoss` (`bool`) | Player is in the room **and the boss is alive** |
    | `+0x4C` | `hasSpawnedBoss` (`bool`) | Final boss has spawned |
    | `+0xA0` | `isBossDefeated` (`bool`) | Boss has been killed |
    | `static fields +0x8` | `A_BossDied` (`Action`) | Static death event |
  - **Measured lifecycle** — read live through an actual fight:
    | Moment | `isFightingBoss` | `hasSpawnedBoss` | `isBossDefeated` |
    | --- | --- | --- | --- |
    | Fighting the boss | **1** | 1 | 0 |
    | Boss killed | **0** | 1 | **1** |
    | Ghost phase | 0 | 1 | 1 |
  - **Consequence for consumers**: `isFightingBoss` drops the *instant* the boss dies, so it tracks the **fight**, not the **room**. Anything that must stay in "boss room" mode through the post-boss ghost phase has to use the composite **`isFightingBoss or isBossDefeated`**, not the first flag alone.
  - **Exit portal** (from `dump.cs`, not yet read live): `InteractableGhostBossLeave`, TypeDefIndex 4787 — `+0x60 hasInteracted`, `+0x61 isBossDead`. This is the candidate signal for "player has left the boss room", which none of the `GraveyardBossRoom` flags above express.
  - **Measured timers around the kill**: `stage_timer` froze at ~592.5 for several seconds while `final_swarm_timer` stayed `0.0`; once the ghost phase proper began, `final_swarm_timer` ticked upward (observed `73.4` at `stage_timer = 673.4`, `run_timer = 778.1`).

- **Dynamic Interactables & Object Mapping**:
  - `Crypt Pots` and `Crypt Chests` exist **only** inside the crypts. When exiting to the Main Map or entering the Boss room, they are completely removed from the memory dictionary.
  - **The Graveyard boss room KEEPS the full outdoor activity set.** Verified live from inside the room: `Pumpkin 105`, `Gravestones 22`, `Chests 69`, plus the usual shrines — 12 labels in total, identical to the main map. This is a **direct contradiction of the comment in `src/core/tracker/powerups.py`**, which states the Graveyard boss room has "neither crypt nor outdoor markers" and detects the room by that absence. That elimination branch is describing something that does not hold; treat it as a known defect, not as documentation.
  - Practical consequence: on Graveyard the activity dictionary **cannot** distinguish the boss room from the main map. Only the `GraveyardBossRoom` flags above can.
  - On the Main Map, standard `Pots` are entirely replaced by **`Pumpkins`** (105).
  - In addition to standard `Greed Shrines` (12), the Main Map features **`Gravestones`** (22) which serve a similar or supplementary role.
  - The number of `Microwaves` is variable and can range from 4 to 8 per run.
  - For tracker-side Graveyard detection, the strongest practical markers are `Pumpkin`, `Gravestones`, `Crypt Chests`, `Crypt Pots`, or `Chests.max == 69`. The mere absence of standard `Pots` is **not** strong enough to use as a standalone proof.

### Live Seed Invariance Validation (2026-07-16)

A live Graveyard run was monitored directly through `GameDataClient` while
checking the seed, map/stage pointers, raw stage index, timers, and activity
dictionary at each internal transition. The run reported
`map_seed = 1464264150` throughout:

| Transition | Seed result | Supporting runtime evidence |
| --- | --- | --- |
| Crypt 1 -> main map | Unchanged (`1464264150`) | `Crypt Pots` and `Crypt Chests` disappeared; `stage_timer` started. |
| Main map -> Crypt 2 | Unchanged (`1464264150`) | `stage_timer` reset to `0.0`; `crypt_timer` restarted; crypt activities returned. |
| Main map / Crypt progression -> boss phase | Unchanged (`1464264150`) | `stage_timer` jumped from about `111.8` to `600.8`; `final_swarm_timer` became active. |

Across all three transitions, `map_ptr` remained `0x23a40d06ee0`,
`stage_ptr` remained `0x23a40d01c60`, and `stage_index` remained `0`. Therefore
the Graveyard internal rooms/phases do not generate a new seed or a new raw
stage identity; phase detection must use timers and activity changes.

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
* **Miniboss & Swarm Timeline (Remaining Time)**:
  * **7:00 remaining**: 1st Miniboss spawns
  * **6:00 remaining**: 1st Mob Swarm (lasts 30 seconds)
  * **3:00 remaining**: 2nd Mob Swarm (lasts 30 seconds)
  * **2:00 remaining**: 2nd Miniboss spawns

#### Stage 2
* **Stage Index**: 1
* **Stage Ptr**: `0x20f412a8ea0` (Changed from Stage 1)
* **Interactables Shift**: Dictionary limits change dynamically (e.g. Microwaves `1 -> 2`, Boss Curses `1 -> 4`, Challenges `2 -> 7`).
* **Timer Behavior**: Base duration is **9 minutes**. Resets to `0.0` at start. Another massive jump forward (to ~530s) occurs at the end of the stage.
* **Miniboss & Swarm Timeline (Remaining Time)**:
  * **7:00 remaining**: 1st Miniboss spawns
  * **6:00 remaining**: 1st Mob Swarm (lasts 30 seconds)
  * **3:00 remaining**: 2nd Mob Swarm (lasts 30 seconds)
  * **2:00 remaining**: 2nd Miniboss spawns

#### Stage 3
* **Stage Index**: 2
* **Stage Ptr**: `0x20f412a8d80` (Changed from Stage 2)
* **Interactables Shift**: Dictionary updates again (Magnet Shrines `1 -> 4`, Shady Guy `1 -> 2`). Midway through the stage (or just before transition), `Pots` max drops from 55 to 39, and `Chests` max from 46 to 35.
* **Timer Behavior**: Base duration is **8 minutes**. Resets to `0.0` upon entering.
* **Miniboss & Swarm Timeline (Remaining Time)**:
  * **6:30 remaining**: 1st Miniboss spawns
  * **5:30 remaining**: 1st Mob Swarm (lasts 30 seconds)
  * **4:00 remaining**: 2nd Mob Swarm (lasts 30 seconds)
  * **3:00 remaining**: 2nd Miniboss spawns

#### Stage 4 (Boss Room)
* **Stage Index**: For BonkScanner's current tracking model, this should be treated as a **virtual Stage 4 layered on top of raw Stage 3 behavior**. The live tracker currently does **not** consume a distinct raw `stage_index=3` here; it promotes Stage 3 to Stage 4 via memory markers and heuristics.
* **Stage Ptr**: `0x20f412a8d80` (**CRITICAL: Identical to Stage 3!**)
* **Identification & Memory Flag**:
  - The game does *not* load a new Stage Ptr for the Boss Room. It is technically the same stage object in memory as Stage 3 (`stage_index = 2`).
  - **Deterministic Memory Flag**: **`MapController.isFinalBossStage`** (`GameAssembly.dll + 0x2F58E08` -> `static_fields + 0xB8` -> **offset `0x20`**, `bool`). This boolean flag flips from `false` to `true` atomically when entering the Boss Room, right before `reseting` (`0x21`).
* **Interactables Shift**: To clear the room for the boss, the game drastically modifies the dictionary: `Pots` max drops to **0**, and `Chests` max drops to **4** (presumably boss rewards). Observed values vary between runs — one trace showed `Chests 46 -> 4` / `Pots 55 -> 6`, another `46 -> 0` / `55 -> 0`. Treat the exact numbers as "small", not as constants.
* **Timer Behavior**: Base duration is **10 minutes**. `Stage Time` resets to `0.0` when entering the boss room. Upon killing the boss (or triggering the phase), `Stage Time` jumps instantly (to ~590s) to trigger the Ghost Phase.

##### Boundary Micro-Behaviour (measured, 0.25 s per-tick trace)

These three facts are why every side-effect heuristic for this transition is
fragile, and why the `isFinalBossStage` flag is the signal to prefer:

1. **The dictionary wipe leads the timer reset by ~250 ms.** One sample carries the wiped dictionary (`Chests 4`, `Pots 6`) while `stage_time` still reads the *old* Stage 3 value (`97.09`). The reset to `0.0` lands on the following sample.
2. **The run clock is not monotonic across the boundary.** It rewinds a fraction (`game_time 286.086 -> 286.000`) and then **freezes at exactly `286.0` for ~7 s** during the boss intro, while `stage_time` sits at `0.0`. A strict "run time must advance" guard silently discards the single sample where the stage-timer collapse is visible, and the collapse window never reopens because `previous_stage_time` is already ~0 afterwards.
3. **A boss room can be entered very early in Stage 3.** Observed at `stage_time = 11.6 s` (cheat-assisted, but a genuine memory read). Any "nothing reaches the boss room before N seconds" assumption needs data behind it; a 15 s floor was tried and disproved by exactly this.

##### Dead End: `CurrentStage.Timeline`

`StageData +0xD0 -> Timeline`, with `stageTime` at `+0x10`, looks promising —
it holds real stage durations (`480.0` on Stage 3, matching the 8-minute
schedule) and the UI shows the boss room as 10 minutes. **It does not work as a
phase marker.** Read live inside a boss room, `stageTime` stays `480.0`, the
`Timeline` pointer is unchanged, and the first `0x80` bytes are byte-identical to
the Stage 3 reading — including across two *different runs with different seeds*.
`Timeline` is static configuration loaded from assets, not runtime state, so the
game never writes phase information into it. The UI's 10-minute value comes from
somewhere else. Do not re-investigate this path.

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
* **Miniboss & Swarm Timeline (Remaining Time)**:
  * **7:00 remaining**: 1st Miniboss spawns
  * **6:00 remaining**: 1st Mob Swarm (lasts 30 seconds)
  * **3:00 remaining**: 2nd Mob Swarm (lasts 30 seconds)
  * **2:00 remaining**: 2nd Miniboss spawns

#### Stage 2
* **Stage Index**: 1
* **Stage Ptr**: `0x20f411fe360` (Changed from Stage 1)
* **Interactables Shift**: Minor dictionary reshuffles.
* **Timer Behavior**: Base duration is **9 minutes**. Timer resets to `0.0`. Upon completion, timer jumps to ~530s.
* **Miniboss & Swarm Timeline (Remaining Time)**:
  * **7:00 remaining**: 1st Miniboss spawns
  * **6:00 remaining**: 1st Mob Swarm (lasts 30 seconds)
  * **3:00 remaining**: 2nd Mob Swarm (lasts 30 seconds)
  * **2:00 remaining**: 2nd Miniboss spawns

#### Stage 3
* **Stage Index**: 2
* **Stage Ptr**: `0x20f411fe240` (Changed from Stage 2)
* **Interactables Shift**: Dictionary reshuffles dynamically upon entry.
* **Timer Behavior**: Base duration is presumably **8 minutes**. Timer resets to `0.0` at start. Notably, there was *no* artificial jump at the end of this stage in the log; it simply reset to `0.0` for the Boss Room.
* **Miniboss & Swarm Timeline (Remaining Time)**:
  * **6:30 remaining**: 1st Miniboss spawns
  * **5:30 remaining**: 1st Mob Swarm (lasts 30 seconds)
  * **4:00 remaining**: 2nd Mob Swarm (lasts 30 seconds)
  * **3:00 remaining**: 2nd Miniboss spawns

#### Stage 4 (Boss Room)
* **Stage Index**: For BonkScanner's current tracking model, this should be treated as a **virtual Stage 4 layered on top of raw Stage 3 behavior**. The live tracker currently does **not** consume a distinct raw `stage_index=3` here; it promotes Stage 3 to Stage 4 via memory markers and heuristics.
* **Stage Ptr**: `0x20f411fe240` (**CRITICAL: Identical to Stage 3!**)
* **Identification & Memory Flag**:
  - Exactly like Forest, the Boss Room is not a new Stage in memory. It uses the Stage 3 pointer (`stage_index = 2`).
  - **Deterministic Memory Flag**: **`MapController.isFinalBossStage`** (`GameAssembly.dll + 0x2F58E08` -> `static_fields + 0xB8` -> **offset `0x20`**, `bool`) flips to `true` upon loading the Boss Room.
* **Interactables Shift**: To clear the room, `Chests` max drops to **0**, and `Pots` max drops to **1**.
* **Timer Behavior**: Base duration is **10 minutes**. Timer resets to `0.0` when entering. After the boss kill, the timer instantly jumps to ~591s to trigger the Ghost Phase.
* **Boundary Micro-Behaviour**: identical to Forest — see [Boundary Micro-Behaviour](#boundary-micro-behaviour-measured-025-s-per-tick-trace) under Forest Stage 4. The dictionary wipe leads the timer reset, the run clock rewinds and freezes across the boundary, and `CurrentStage.Timeline` is a dead end on this map too.

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
* **The Boss Room Trap & Resolution**: The transition to the Boss Room (tracker-side `Stage 4`) keeps the `Stage Ptr` from Stage 3 exactly the same. However, the game sets **`MapController.isFinalBossStage`** (`0x2F58E08 +0xB8 +0x20`) to `true`, triggers an interactables dictionary wipe (reducing `Pots` and `Chests` max counts to near 0), and resets `Stage Time` to `0.0`.
* **Timers**: Timers are mostly standard but feature massive artificial "fast-forwards" at the end of each stage (jumping to ~590s or ~530s) to force the Ghost Phase if the player lingers too long or kills the boss.

### Conclusion for Tracking Software (`src/core/tracker/live_run.py`)

Any tracker relying solely on `Current Stage Ptr` changes will fail to detect the
boss room in Forest/Desert and sub-phase transitions in Graveyard.

**Each map family has its own boss-room flag, and they are not interchangeable.**

| Map family | Boss-room signal | Notes |
| --- | --- | --- |
| Forest / Desert | `MapController.isFinalBossStage` (`0x2F58E08 -> +0xB8 -> +0x20`) | Flips atomically on entry. Reads `true` for the whole room including the ghost phase. |
| Graveyard | `RsgController.Instance.roomBoss` flags (`0x2F79E50 -> +0xB8 -> +0x20 -> +0x48`) | `isFinalBossStage` is **`false`** here. Use `isFightingBoss or isBossDefeated` — the first alone drops at the kill. |

Both flags live in the same static block the tracker already reads for
`stage_index`, so each is **exactly as reliable as the stage detection it
completes**. That is the argument for keeping the surrounding logic thin: layering
elaborate fallbacks beneath a signal of equal reliability buys nothing. Stages 1–3
come from `stage_index`; Stage 4 comes from the flag; the side-effect heuristics
(activity collapse, timer reset) are a last resort for when the flag cannot be
read, and are deliberately left unelaborated.

For Graveyard sub-phases *other than* the boss room, tracking still relies on
timer families (`stage_timer` vs `crypt_timer` vs `final_swarm_timer`) and crypt
activity presence — note that the activity dictionary cannot separate the boss
room from the main map on this map, since the outdoor set stays loaded in both.

### Tooling for Re-verification

Both live in gitignored `tools/`:
- **`record_stage4_transition.py`** — dense 0.25 s JSONL trace of every field the
  Stage 4 detector consumes, replayed through the real `run_summary` predicates
  each tick. Run it ~30 s before the boss room and keep it running through the
  ghost phase. This is what produced the boundary micro-behaviour above.
- **`probe_stage_timeline.py`** — dumps the `CurrentStage.Timeline` object
  uncached; kept as the record of that dead end.


---

## Quick Reference

### Memory Offsets Used for Phase Detection

| What | Chain | Verified |
| --- | --- | --- |
| `MapController` static block | `GameAssembly.dll + 0x2F58E08` -> `read_ptr` -> `+0xB8` | yes |
| ├ `stageIndex` (`i32`) | `+0x08` | yes |
| ├ `currentMap` (ptr) | `+0x10` | yes |
| ├ `currentStage` (ptr) | `+0x18` | yes |
| ├ **`isFinalBossStage`** (`bool`) | **`+0x20`** | yes — `true` in Forest/Desert boss room, `false` on Graveyard |
| └ `reseting` (`bool`) | `+0x21` | yes |
| `RsgController` static block | `GameAssembly.dll + 0x2F79E50` -> `read_ptr` -> `+0xB8` | yes |
| └ `Instance` -> `roomBoss` | `+0x20` -> `+0x48` = `GraveyardBossRoom` | yes |
| &nbsp;&nbsp;├ `isFightingBoss` | `+0x38` | yes |
| &nbsp;&nbsp;├ `hasSpawnedBoss` | `+0x4C` | yes |
| &nbsp;&nbsp;└ `isBossDefeated` | `+0xA0` | yes |
| `InteractableGhostBossLeave` | TypeDefIndex 4787; `+0x60 hasInteracted`, `+0x61 isBossDead` | **from dump only, not read live** |

TypeInfo addresses come from `.tools/il2cppdump_out/script.json`
(`ScriptMetadata` entries, `*_TypeInfo`); field offsets from `dump.cs`.

### Identical Across All Maps
- `MapController` static block layout and the `stage_index` ordinal.
- Baseline outdoor interactables on Forest/Desert Stage 1: 55 Pots, 46 Chests, 15 Charge Shrines, 8 Greed Shrines.
- Boss room never advances `stage_index` and never loads a new `Stage Ptr` on **any** map.
- The ghost/final-swarm phase is best read from `final_swarm_timer` everywhere.

### Key Differences

| | Graveyard | Forest / Desert |
| --- | --- | --- |
| Structure | Monolith: one `Stage Ptr` for the whole run | Three real stages + a virtual 4th |
| `stage_index` | Stuck at `0` throughout | Advances `0 -> 1 -> 2`, then stays `2` |
| Boss-room flag | `GraveyardBossRoom.*` | `MapController.isFinalBossStage` |
| Activities in boss room | **Full outdoor set stays loaded** | Wiped to near-zero |
| Crypt phases | Yes, with dedicated `crypt_timer` | None |
| Pots | Replaced by `Pumpkin` (105) | Standard `Pots` (55) |

### Integration Notes
1. **Never infer a boss room from the activity dictionary on Graveyard** — the outdoor set is present in both the main map and the boss room.
2. **Never treat an absent/partial activity read as a signal.** A dictionary mid-rebuild reports real but tiny values (`max = 1/1`) that are shaped exactly like a boss-room wipe. This has caused a live false Stage 4 at a stage boundary.
3. **Read boss-room flags as positive-only.** `false` means "not the boss room" *or* "the read failed", and those must not be told apart — promote on the flag, never demote.
4. **Prefer signals that persist over signals that are edges.** The flags above stay true for the whole room; the timer collapse is a single sample that a frozen run clock can swallow entirely.
