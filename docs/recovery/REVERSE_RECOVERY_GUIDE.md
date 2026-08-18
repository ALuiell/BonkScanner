# Reverse Recovery Guide

Date: 2026-05-11

## Goal

This file is the practical recovery playbook for Megabonk game updates.

Use it when:

- the game updates and memory reads start returning zeros, garbage, or stale values
- the UI stops updating correctly
- reroll automation still runs but evaluates wrong data

This guide is not meant to replace detailed reverse reports.
It exists to help quickly:

1. identify which subsystem broke
2. verify the current source of truth
3. produce a clean reverse handoff
4. update code with minimal confusion

## Main Rule

Prefer stable module-relative paths and documented root chains.

Avoid implementation based on:

- one-session live addresses
- raw Cheat Engine addresses with no stable root path
- values that look plausible but were not verified across a fresh session

If a reverse note and code disagree, the latest verified reverse report in
`docs/recovery/reports/` should be treated as the primary source of truth until
the code is updated.

## Project Surfaces That Can Break

### 1. Map stats

Code:

- `src/infra/memory/game_data_client.py`
- `src/core/runtime_stats.py`
- `src/core/logic.py`

Symptoms:

- shrine/map counters show `0`
- map stats never stabilize
- best/worst map tracking looks wrong
- scanner rerolls forever or accepts obviously bad maps

Most fragile pieces:

- `GameDataClient.TYPE_INFO_OFFSET`
- `MAP_CONTROLLER_TYPE_INFO_OFFSET`
- `MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET`
- interactables dictionary layout
- label-to-stat mapping if game strings changed

### 2. Player stats tab

Code:

- `src/infra/memory/player_stats_client.py`
- `src/gui_app.py`
- `src/infra/vod_storage.py`

Symptoms:

- `Live Stats` shows `--` or nonsense values
- recording works but snapshots are empty
- values update for some stats but not others

Most fragile pieces:

- `PlayerStatsClient.TYPE_INFO_OFFSET`
- owner/root chain to `PlayerStatsNew`
- final stats entries path
- per-stat id mapping

### 3. Passive item inventory

Code:

- `src/infra/memory/player_stats_client.py`
- `src/gui_app.py`
- `src/infra/vod_storage.py`

Symptoms:

- items list is always empty
- item names become garbage
- stack counts are incorrect
- old items appear even in a fresh run

Most fragile pieces:

- `PlayerStatsNew + 0xA0`
- `+0x50` passive item dictionary path
- dictionary layout
- class metadata string pointers
- stack/count field

### 4. Player status effects and active buffs

Code:

- `src/infra/memory/player_stats_client.py`
- `src/ui/tabs/player_stats/live_stats.py`

Symptoms:

- active buffs (Rage, Haste, Shield) never appear on the overlay
- expiration timer remains static or has stale values

Most fragile pieces:

- `PLAYER_STATUS_EFFECTS_OFFSET` (offset `0x38` of `PlayerInventory`)
- status effects dictionary layout and `StatusEffect` class fields (offsets `0x10`, `0x20`, `0x24`)

### 5. Chest counters and free openings

Code:

- `src/infra/memory/player_stats_client.py`
- `src/ui/tabs/player_stats/live_stats.py`

Symptoms:

- chests purchased and chests bought remain at zero
- free openings are not registered or subtract gold from UI counters
- key stacking proc calculations show wrong percentages

Most fragile pieces:

- `MONEY_UTILITY_TYPE_INFO_OFFSET` (offset `0x02F5E0B0`)
- `MONEY_UTILITY_CHESTS_PURCHASED_OFFSET` (offset `0x48`)
- key stack and current chance offsets in `ItemKey` (`0x30`, `0x34`)

### 6. Chaos Tome tracking

Code:

- `src/infra/memory/player_stats_client.py`
- `src/core/tracker/live_run.py`

Symptoms:

- Chaos Tome upgrades or level up rolls are missing from UI
- wrong rolls are attributed to Chaos Tome upgrades

Most fragile pieces:

- `STAT_INVENTORY_OFFSET` (offset `0x50` of `PlayerStatsNew`)
- `STAT_INVENTORY_PERMANENT_CHANGES_OFFSET` (offset `0x10` of `StatInventory`)
- `permanentChanges` dictionary layout and `StatModifier` offsets

### 7. Keyboard restart control

Code:

- `src/core/run_control.py`
- `src/infra/keyboard_run_control.py`
- `src/infra/process.py`
- `src/gui_run_control.py`

Symptoms:

- restart hotkey hold does not register
- restart fails to press correct key combinations

Most fragile pieces:

- hotkey bindings and hold duration config
- keyboard simulation helper library compatibility

## Recommended Triage Order After A Game Update

Follow this order to reduce noise and isolate the first broken layer.

### Step 1. Confirm process and module attachment still works

Check:

- game process name is still correct
- `GameAssembly.dll` is still loaded
- app can still attach to the target process

If this fails, do not start deep reverse yet.
Fix the process/module layer first.

### Step 2. Check map stats root paths

Reason:

- map stats are central to reroll logic
- many other validations depend on them being sane

Check:

- current `TYPE_INFO_OFFSET` values in `src/infra/memory/game_data_client.py`
- whether the interactables dictionary still resolves
- whether labels still match the expected map stats

### Step 3. Check player stats root path

Reason:

- player stats and item inventory currently share the same broad root chain
- if the shared root moved, both features may break together

Check:

- `PlayerStatsClient.TYPE_INFO_OFFSET`
- `class_ptr + 0xB8`
- `root + 0x40 -> PlayerStatsNew`
- stats entries path from there

### Step 4. Check passive item inventory

Only do this after the player stats root path is confirmed.

Check:

- `PlayerStatsNew + 0xA0`
- resulting inventory-related object
- passive item dictionary at `+0x50`
- dictionary `entries`, `count`
- item object count field
- item class metadata and ASCII class name

### Step 5. Check status effects and active buffs path

Only do this after player inventory is verified.

Check:

- `PlayerInventory + 0x38`
- `statusEffects` dictionary at `+0x10`
- individual entries and key matching

### Step 6. Check chest counters and MoneyUtility offsets

Check:

- `MONEY_UTILITY_TYPE_INFO_OFFSET`
- `chestsPurchased` at `static_fields + 0x48`
- `ItemKey` proc probability field `currentChance` at `+0x34`

### Step 7. Check Chaos Tome tracking and permanent changes dictionary

Check:

- `StatInventory` at `PlayerStatsNew + 0x50`
- `permanentChanges` dictionary at `+0x10`
- array size and `StatModifier` elements

### Step 8. Check keyboard restart control config

Check:

- hotkey assignments in UI settings
- layout delays and hold durations in `src/infra/keyboard_run_control.py`

## Common Failure Patterns

### All values are zero

Usually means one of:

- root path moved
- class/static fields are not initialized yet
- wrong object type or stale path

### Count looks valid but entries are empty or junk

Usually means one of:

- dictionary object is stale
- the object is no longer the expected dictionary type
- entries offset changed

### Some stats work, some do not

Usually means one of:

- stat ids changed
- final/effective stats table moved
- one section of the stats layout changed while the root chain still works

### Names are garbage but counts are correct

Usually means one of:

- class metadata path changed
- string pointer field changed
- string encoding assumption is wrong

### Values look plausible but do not update correctly

Treat this as dangerous.

Possible causes:

- stale pointer from a previous run/session
- reading a cached/base object instead of final/effective runtime state
- path valid only inside the old session

## What A Good Reverse Handoff Must Include

When preparing a reverse report for implementation, include:

- goal of the reverse task
- stable root path from `GameAssembly.dll + offset`
- all dereference and field offsets in order
- what object type each hop represents
- how the path behaves across fresh sessions
- field layout for arrays/dictionaries/lists if applicable
- exact source of display name or label
- exact source of count/value
- confidence per claim
- rejected paths and why they were rejected
- implementation recommendation section

Use `docs/recovery/HANDOFF_TEMPLATE.md` for new reports.

## How To Hand Off An Update Efficiently

Best workflow:

1. create a new report in `docs/recovery/reports/`
2. use the handoff template
3. clearly mark what is confirmed vs suspected
4. tell me which code path should be updated

Good prompt example:

`Game updated. Use docs/recovery/reports/2026-05-12-player-stats-refresh.md as source of truth and update src/infra/memory/player_stats_client.py + related UI.`

Even better:

`Game updated. First sanity-check the report against the current code assumptions, then patch the implementation.`

## Rapid TypeInfo & Offset Extraction Guide

When a game update drops, run this standard reverse workflow to extract updated static offsets within 5–10 minutes:

### 1. Dump Metadata & Symbols via Il2CppDumper
1. Locate the game directory: `<GameDir>/Megabonk_Data/il2cpp_data/Metadata/global-metadata.dat` and `<GameDir>/GameAssembly.dll`.
2. Run Il2CppDumper:
   ```cmd
   Il2CppDumper.exe GameAssembly.dll global-metadata.dat output_dir/
   ```
3. This produces:
   - `dump.cs`: C# pseudo-code containing class definitions, field offsets (`// 0x10`), and method addresses.
   - `script.json`: metadata mapping containing `ScriptMetadata` and `AddressRef` tables.
   - `ida_with_struct.py` / `ghidra_with_struct.py`: symbol loading scripts.

### 2. Finding TypeInfo Offsets (Static Class Roots)
In Unity IL2CPP 64-bit Windows builds, static class pointers (`Il2CppClass*`) live in the `.data` / `.bss` section of `GameAssembly.dll`.
To find them:
- **Option A: Search in `script.json` / `dump.cs`**:
  Search for the class name in `script.json` under `ScriptMetadata` (e.g. `"PlayerStatsNew"`, `"MapController"`, `"RSGController"`). The `Address` field gives the RVA (Relative Virtual Address) to `GameAssembly.dll`.
- **Option B: In IDA Pro / Ghidra**:
  After running the symbol script, search for symbol names matching:
  - `PlayerStatsNew_c*` or `PlayerStatsNew_TypeInfo`
  - `MapController_TypeInfo`
  - `MapGenerationController_TypeInfo`
  - `MyTime_TypeInfo`
  - `RunStats_TypeInfo`
  - `RunUnlockables_TypeInfo`
  - `MoneyUtility_TypeInfo`
  - `DataManager_TypeInfo`
  - `RSGController_TypeInfo`
  - `GameManager_TypeInfo`
  - `MusicController_TypeInfo`
  - `LoadingScreen_TypeInfo`
  - `PlayerMovement_TypeInfo`
- **Option C: Static Fields Offset (`0xB8`)**:
  In standard Unity 2021/2022 IL2CPP x64, `ClassPointer + 0xB8` points to the static fields memory block (`static_fields`).

### 3. Finding Class Field Offsets in `dump.cs`
Inside `dump.cs`, search for the target class name. Field comments provide direct hex offsets:
```csharp
// Namespace:
public class PlayerInventory // TypeDefIndex: ...
{
    // Fields
    public ItemInventory itemInventory; // 0x20
    public WeaponInventory weaponInventory; // 0x28
    public PlayerXp playerXp; // 0x30
    public PlayerStatusEffects playerStatusEffects; // 0x38
    public TomeInventory tomeInventory; // 0x48
    public int gold; // 0x70
}
```

---

## Current Canonical References

At the time of writing, these are the most useful references:

- [MEMORY_PATH_INDEX.md](./MEMORY_PATH_INDEX.md)
- [01_map_generation_and_stats.md](./parts/01_map_generation_and_stats.md)
- [02_player_stats.md](./parts/02_player_stats.md)
- [03_passive_item_inventory.md](./parts/03_passive_item_inventory.md)
- [04_live_weapons_inventory.md](./parts/04_live_weapons_inventory.md)
- [05_live_tomes_inventory.md](./parts/05_live_tomes_inventory.md)
- [06_run_metadata_and_stats.md](./parts/06_run_metadata_and_stats.md)
- [07_chaos_tome_tracking.md](./parts/07_chaos_tome_tracking.md)
- [08_player_status_effects.md](./parts/08_player_status_effects.md)
- [09_disabled_items_pool.md](./parts/09_disabled_items_pool.md)
- [10_chests_purchased_and_counters.md](./parts/10_chests_purchased_and_counters.md)
- [11_game_lifecycle_and_bosses.md](./parts/11_game_lifecycle_and_bosses.md)

## Recovery Output Checklist

Before considering a recovery pass complete, verify:

- code offsets/path were updated
- UI reads sane values again
- old stale-path assumptions were removed
- tests were updated or added where possible
- a fresh reverse report exists for the changed path
- `MEMORY_PATH_INDEX.md` was updated

