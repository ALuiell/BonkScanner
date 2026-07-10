# Part 7: Chaos Tome and Permanent Stat Modifiers Recovery Guide

## Overview
This component tracks the Chaos Tome level and resolves permanent stat modifier upgrades (from the Chaos Tome). When the Chaos Tome levels up, it adds a random stat modifier to the permanent stat upgrades dictionary in `StatInventory`. The tracker reads this dictionary, parses the list of `StatModifier` objects per stat, compares it with prior baselines, and resolves the exact random rolls and levels.

- **Target Files**:
  - Code: `src/player_stats.py`, `src/live_run_tracker.py`
  - Unit Tests: `src/tests/test_player_stats.py`, `src/tests/test_live_run_tracker.py`

---

## Memory Chain Diagrams

### 1. Stat Inventory Permanent Changes Chain
```
owner_stats (resolved from PlayerStatsNew, see Part 2)
  -> +0x50 (STAT_INVENTORY_OFFSET) -> [StatInventory Pointer]
    -> +0x10 (STAT_INVENTORY_PERMANENT_CHANGES_OFFSET) -> [Dictionary<int, List<StatModifier>> Pointer]
```

### 2. Traversal of the Permanent Changes Dictionary
```
permanent_changes_dict
  -> +0x18 (DICT_ENTRIES_OFFSET) -> [Entries Memory Base Pointer]
  -> +0x20 (DICT_COUNT_OFFSET)   -> int (count of entries)

Each Entry (Note: Size is 0x18, Key is stat_id, Value is List pointer):
Entries + 0x20 (DICT_ENTRY_START_OFFSET) + (Index * 0x18 (DICT_ENTRY_SIZE))
  -> +0x0  (DICT_ENTRY_HASH_CODE_OFFSET)  -> int (hash code; skip if < 0)
  -> +0x8  (WEAPON_DICT_ENTRY_KEY_OFFSET) -> int (stat_id)
  -> +0x10 (WEAPON_DICT_ENTRY_VALUE_OFFSET) -> [List<StatModifier> Pointer]
```

### 3. Traversal of List<StatModifier> per Stat
```
List<StatModifier>
  -> +0x10 (LIST_ITEMS_OFFSET)  -> [Array of StatModifier Pointers]
  -> +0x18 (LIST_SIZE_OFFSET)   -> int (size of list)

Each StatModifier Pointer in Array:
Array + 0x20 (ARRAY_DATA_OFFSET) + (Index * 0x8 (OBJECT_POINTER_SIZE))
  -> +0x10 (STAT_MODIFIER_STAT_OFFSET)  -> int (stat_id)
  -> +0x14 (STAT_MODIFIER_TYPE_OFFSET)  -> int (modifier type)
  -> +0x18 (STAT_MODIFIER_VALUE_OFFSET) -> float (modifier value)
```

### 4. Chaos Tome Level
```
owner_stats
  -> +0x28 (PLAYER_INVENTORY_OFFSET) -> [Player Inventory Pointer]
    -> +0x48 (TOME_INVENTORY_OFFSET)   -> [Tome Inventory Pointer]
      -> +0x18 (TOME_LEVELS_DICT_OFFSET)   -> [Tome Levels Dictionary Pointer]

Look up key = 24 (CHAOS_TOME_ID) to retrieve the Tome Level int (value at offset +0xC of the entry).
```

---

## Reversing Walkthrough (Cheat Engine & IL2CPP)

### 1. Locating Offsets using IL2CPP Dump
Search for these classes in `dump.cs`:
- **`StatInventory`**:
  - Find the dictionary field of permanent changes.
  - Locate `permanentChanges` (offset `0x10`).
- **`StatModifier`**:
  - Find fields like `stat` (offset `0x10`), `type` (offset `0x14`), and `value` (offset `0x18`).
- **`EStat`**:
  - Locate the enum mappings for stat IDs (e.g. `12` is Damage, `30` is Luck).

### 2. Cheat Engine Live Verification
- **Verify Permanent Changes Traversal**:
  - Level up the Chaos Tome in the game.
  - Trace `owner_stats -> statInventory -> permanentChanges`.
  - Walk the dictionary and list values. Verify that the entry counts and the `StatModifier` values match the live Chaos Tome rolls.
  - If a new game update changes the dictionary layout, verify standard `.NET` Dictionary offsets.

---

## Code Reference
Offsets are defined in `PlayerStatsClient` in `src/player_stats.py`:
```python
class PlayerStatsClient:
    STAT_INVENTORY_OFFSET = 0x50
    STAT_INVENTORY_PERMANENT_CHANGES_OFFSET = 0x10
    CHAOS_TOME_ID = 24
    
    STAT_MODIFIER_STAT_OFFSET = 0x10
    STAT_MODIFIER_TYPE_OFFSET = 0x14
    STAT_MODIFIER_VALUE_OFFSET = 0x18
    
    LIST_ITEMS_OFFSET = 0x10
    LIST_SIZE_OFFSET = 0x18
```

---

## Verification Steps
1. Run tests:
   ```powershell
   .\run_tests.bat -k "chaos" src.tests.test_player_stats
   ```
2. Verify in the overlay interface that when a Chaos Tome is leveled up, the rolls are correctly captured, resolved, and output in the panel.
