# Part 9: Disabled Items Pool Recovery Guide

## Overview
This component detects which items have been globally disabled (excluded from the drop pool) by the player in lobby settings. It does this by comparing the global catalog of item templates in `DataManager` against the run-specific active pool in `RunUnlockables` and the banished items.

- **Target Files**:
  - Code: `src/player_stats.py`
  - Unit Tests: `src/tests/test_player_stats.py`

---

## Memory Chain Diagrams

### 1. Global Catalog (DataManager List)
```
GameAssembly.dll + DATA_MANAGER_TYPE_INFO_OFFSET (0x02F85790)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x8 (First field - DataManager instance pointer) -> [DataManager Object]
        -> +0x60 -> [unsortedItems List Pointer]
```
To decode the `unsortedItems` List:
```
unsortedItems
  -> +0x10 (LIST_ITEMS_OFFSET) -> [Array Base Pointer]
  -> +0x18 (LIST_SIZE_OFFSET)  -> int (size of list)

Each Item Data element in Array:
Array + 0x20 (ARRAY_DATA_OFFSET) + (Index * 0x8 (OBJECT_POINTER_SIZE))
  -> [ItemData Object Pointer]
    -> +0x54 (ITEM_DATA_ENUM_OFFSET) -> int (EItem enum ID)
```

### 2. Run Active Pool (RunUnlockables Dictionary)
```
GameAssembly.dll + RUN_UNLOCKABLES_TYPE_INFO_OFFSET (0x02F7A210)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x10 (availableItems offset) -> [availableItems Dictionary Pointer]
```
To decode the `availableItems` Dictionary (keys are rarities, values are lists of active `ItemData`):
```
availableItems
  -> +0x18 (DICT_ENTRIES_OFFSET) -> [Entries Memory Base Pointer]
  -> +0x20 (DICT_COUNT_OFFSET)   -> int (count of entries)

Each Entry (Note: Size is 0x18, Key is rarity enum, Value is List pointer):
Entries + 0x20 (DICT_ENTRY_START_OFFSET) + (Index * 0x18 (DICT_ENTRY_SIZE))
  -> +0x0  (DICT_ENTRY_HASH_CODE_OFFSET) -> int (hash code; skip if < 0)
  -> +0x10 (DICT_ENTRY_VALUE_OFFSET)     -> [List<ItemData> Pointer]
```
*(The inner `List<ItemData>` is traversed using the standard List layout described in Global Catalog)*

### 3. Difference Logic
The set of disabled items is resolved as:
$$\text{disabled\_item\_ids} = \text{global\_item\_ids} \setminus (\text{available\_item\_ids} \cup \text{banished\_item\_ids})$$

---

## Reversing Walkthrough (Cheat Engine & IL2CPP)

### 1. Locating Offsets using IL2CPP Dump
Search for these classes in `dump.cs`:
- **`DataManager`**:
  - Find the static instance field (usually `+0x8` of static class).
  - Find the `unsortedItems` field (offset `0x60`).
- **`RunUnlockables`**:
  - Find the static fields class.
  - Locate `availableItems` dictionary (offset `0x10`).
- **`ItemData`**:
  - Locate `eItem` enum ID (offset `0x54`).

### 2. Cheat Engine Live Verification
- **Why Check Active Pool Instead of Template Fields?**
  - Attempting to inspect `ItemData.isEnabled` or `ItemData.inItemPool` directly on the `ScriptableObject` templates in `DataManager` will fail. These templates are loaded directly from game assets and are read-only; their state does not change when the player toggles them in the settings lobby.
  - The game constructs the active pool `RunUnlockables.availableItems` at run start by including only enabled items. Comparing the global catalog against this active pool is the only reliable way to check if an item has been disabled.

---

## Code Reference
Offsets are defined in `PlayerStatsClient` in `src/player_stats.py`:
```python
class PlayerStatsClient:
    DATA_MANAGER_TYPE_INFO_OFFSET = 0x02F85790
    RUN_UNLOCKABLES_TYPE_INFO_OFFSET = 0x02F7A210
    
    LIST_ITEMS_OFFSET = 0x10
    LIST_SIZE_OFFSET = 0x18
    ARRAY_DATA_OFFSET = 0x20
    OBJECT_POINTER_SIZE = 0x8
    
    DICT_ENTRIES_OFFSET = 0x18
    DICT_COUNT_OFFSET = 0x20
    DICT_ENTRY_START_OFFSET = 0x20
    DICT_ENTRY_SIZE = 0x18
    DICT_ENTRY_VALUE_OFFSET = 0x10
    
    ITEM_DATA_ENUM_OFFSET = 0x54
```

---

## Verification Steps
1. Run tests:
   ```powershell
   .\run_tests.bat -k "disabled_items" src.tests.test_player_stats
   ```
2. Disable several items in the lobby menu, start a run, and verify that the correct disabled items list is displayed in the overlay or log panel.
