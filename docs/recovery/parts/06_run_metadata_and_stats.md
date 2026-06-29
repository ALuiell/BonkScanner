# Part 6: Run Metadata and Stats Recovery Guide

## Overview
This component reads overall run metadata and analytics from memory, including:
- In-game timers (Run Timer and Stage Timer)
- Mob Kills Counter (by parsing `RunStats.stats` dictionary)
- Damage Sources list (by parsing `RunStats.damageSources` dictionary)
- Player Level (via `PlayerXp` in `PlayerInventory`)
- Banished Items and Tomes (by decoding the `RunUnlockables` hashsets)

- **Target Files**:
  - Code: `src/player_stats.py`
  - Unit Tests: `src/tests/test_player_stats.py`

---

## Memory Chain Diagrams

### 1. In-game Timers (MyTime Class)
```
GameAssembly.dll + RUN_TIMER_TYPE_INFO_OFFSET (0x02F62398)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x1C (STAGE_TIMER_OFFSET) -> float (stage_timer)
      -> +0x20 (RUN_TIMER_OFFSET)   -> float (run_timer)
```

### 2. Mob Kills Counter (RunStats Class)
```
GameAssembly.dll + RUN_STATS_TYPE_INFO_OFFSET (0x02F7A170)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x0 (RUN_STATS_DICT_OFFSET)       -> [Run Stats Dictionary Pointer]
```
Decoding the `run_stats_dict`:
```
run_stats_dict
  -> +0x18 (DICT_ENTRIES_OFFSET) -> [Entries Memory Base Pointer]
  -> +0x20 (DICT_COUNT_OFFSET)   -> int (count of entries)

Each Entry:
Entries + 0x20 (DICT_ENTRY_START_OFFSET) + (Index * 0x18 (DICT_ENTRY_SIZE))
  -> +0x8  (DICT_ENTRY_KEY_OFFSET)            -> [MonoString Pointer] (Key name)
  -> +0x10 (RUN_STATS_ENTRY_VALUE_OFFSET)     -> float (kill count)
```
*Note: To extract kills, iterate through entries, read the MonoString key, and look for `"kills"`.*

### 3. Damage Sources (RunStats Class)
```
GameAssembly.dll + RUN_STATS_TYPE_INFO_OFFSET (0x02F7A170)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x8 (RUN_DAMAGE_SOURCES_DICT_OFFSET) -> [Damage Sources Dictionary Pointer]
```
Decoding the `damage_sources_dict` (maps key to `DamageSource` object):
```
damage_sources_dict
  -> +0x18 (DICT_ENTRIES_OFFSET) -> [Entries Memory Base Pointer]
  -> +0x20 (DICT_COUNT_OFFSET)   -> int (count of entries)

Each Entry:
Entries + 0x20 (DICT_ENTRY_START_OFFSET) + (Index * 0x18 (DICT_ENTRY_SIZE))
  -> +0x8  (DICT_ENTRY_KEY_OFFSET)   -> [MonoString Pointer] (Damage source key)
  -> +0x10 (DICT_ENTRY_VALUE_OFFSET) -> [DamageSource Object Pointer]
    -> +0x10 (DAMAGE_SOURCE_NAME_OFFSET)          -> [MonoString Pointer] (display name)
    -> +0x18 (DAMAGE_SOURCE_ADDED_AT_TIME_OFFSET) -> float (timestamp added)
    -> +0x1C (DAMAGE_SOURCE_DAMAGE_OFFSET)        -> float (damage value)
```

### 4. Player Level
```
owner_stats (resolved from PlayerStatsNew, see Part 2)
  -> +0x28 (PLAYER_INVENTORY_OFFSET) -> [Player Inventory Pointer]
    -> +0x30 (PLAYER_XP_OFFSET)        -> [PlayerXp Object Pointer]
      -> +0x14 (PLAYER_XP_LEVEL_OFFSET) -> int (level)
```

### 5. Run Banishes (RunUnlockables Class)
```
GameAssembly.dll + RUN_UNLOCKABLES_TYPE_INFO_OFFSET (0x02F7A210)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x0 (RUN_UNLOCKABLES_BANISHED_ITEMS_OFFSET)       -> [HashSet<ItemData> Pointer]
      -> +0x8 (RUN_UNLOCKABLES_BANISHED_UPGRADABLES_OFFSET) -> [HashSet<UnlockableBase> Pointer]
```
Decoding a `.NET HashSet`:
```
hashset_ptr
  -> +0x18 (HASHSET_SLOTS_OFFSET)      -> [Slots Memory Base Pointer]
  -> +0x20 (HASHSET_COUNT_OFFSET)      -> int (count)
  -> +0x24 (HASHSET_LAST_INDEX_OFFSET) -> int (last index)

Each Slot:
Slots + 0x20 (HASHSET_SLOT_START_OFFSET) + (Index * 0x10 (HASHSET_SLOT_SIZE))
  -> +0x0 (HASHSET_SLOT_HASH_CODE_OFFSET) -> int (hash code; skip if < 0)
  -> +0x8 (HASHSET_SLOT_VALUE_OFFSET)     -> [Object Pointer] (ItemData or TomeData)
```
Decoding the values:
- **For Items** (from `banishedItems`):
  ```
  ItemData Object Pointer
    -> +0x54 (ITEM_DATA_ENUM_OFFSET) -> int (enum ID, mapped using ITEM_ENUM_NAMES_BY_ID)
  ```
- **For Upgradables** (from `banishedUpgradables`):
  Read the class type first:
  ```
  Object Pointer
    -> +0x0 (OBJECT_KLASS_OFFSET) -> [Class Metadata Pointer]
      -> +0x10 (KLASS_NAME_PTR_OFFSET) -> [ASCII String Pointer] (e.g. "TomeData")
  ```
  If class name is `"TomeData"`:
  ```
  TomeData Object Pointer
    -> +0x50 (TOME_DATA_ENUM_OFFSET) -> int (tome ID, mapped using TOME_NAMES_BY_ID)
  ```

---

## Reversing Walkthrough (Cheat Engine & IL2CPP)

### 1. Locating Offsets using IL2CPP Dump
Search for these classes in `dump.cs`:
- **`MyTime`**: Find timer offsets like `runTimer` and `stageTimer`.
- **`RunStats`**: Find fields like `stats` (offset `0x0`) and `damageSources` (offset `0x8`).
- **`DamageSource`**: Check field offsets for `name`, `addedAtTime`, and `damage`.
- **`PlayerXp`**: Locate the `level` field (offset `0x14`).
- **`RunUnlockables`**: Find `banishedItems` (offset `0x0`) and `banishedUpgradables` (offset `0x8`).
- **`ItemData`**: Find item ID enum field offset (offset `0x54`).
- **`TomeData`**: Find tome ID enum field offset (offset `0x50`).

### 2. Cheat Engine Live Verification
- **Verify Timers**:
  - Scan for a running float value that matches the game timer. Search for "increased value" or scan for specific timer value. Trace pointers back to `MyTime` static class.
- **Verify Banishes**:
  - Banish an item in the game. Trace `RunUnlockables.banishedItems` and check that the set size becomes non-zero. Walk the HashSet slots, read the ItemData enum ID, and verify the mapped name matches.
  - Repeat for Tome banishes, confirming class metadata detection.

---

## Code Reference
Offsets are defined in `PlayerStatsClient` in `src/player_stats.py`:
```python
class PlayerStatsClient:
    RUN_TIMER_TYPE_INFO_OFFSET = 0x02F62398
    RUN_STATS_TYPE_INFO_OFFSET = 0x02F7A170
    RUN_UNLOCKABLES_TYPE_INFO_OFFSET = 0x02F7A210
    
    STAGE_TIMER_OFFSET = 0x1C
    RUN_TIMER_OFFSET = 0x20
    PLAYER_INVENTORY_OFFSET = 0x28
    PLAYER_XP_OFFSET = 0x30
    PLAYER_XP_LEVEL_OFFSET = 0x14
    
    RUN_STATS_DICT_OFFSET = 0x0
    RUN_STATS_ENTRY_VALUE_OFFSET = 0x10
    RUN_DAMAGE_SOURCES_DICT_OFFSET = 0x8
    
    DAMAGE_SOURCE_NAME_OFFSET = 0x10
    DAMAGE_SOURCE_ADDED_AT_TIME_OFFSET = 0x18
    DAMAGE_SOURCE_DAMAGE_OFFSET = 0x1C
    
    HASHSET_SLOTS_OFFSET = 0x18
    HASHSET_COUNT_OFFSET = 0x20
    HASHSET_LAST_INDEX_OFFSET = 0x24
    HASHSET_SLOT_START_OFFSET = 0x20
    HASHSET_SLOT_SIZE = 0x10
    HASHSET_SLOT_HASH_CODE_OFFSET = 0x0
    HASHSET_SLOT_VALUE_OFFSET = 0x8
    ITEM_DATA_ENUM_OFFSET = 0x54
    TOME_DATA_ENUM_OFFSET = 0x50
    # ...
```

---

## Verification Steps
1. Run pytest:
   ```powershell
   pytest src/tests/test_player_stats.py -k "timer or kills or level or banish"
   ```
2. Verify that in-game timers, mob kills, and damage sources updates match the HUD/overlay panel live outputs.