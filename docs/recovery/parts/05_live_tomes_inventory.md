# Part 5: Live Tomes Inventory Recovery Guide

## Overview
This component tracks the active run's collected tomes (e.g. Damage Tome, Agility Tome, Cooldown Tome, Chaos Tome) and their current levels. It resolves the `TomeInventory` from player inventory, queries the levels dictionary (tome ID to level), and queries the upgrades dictionary (tome ID to effective stat modifier).

- **Target Files**:
  - Code: [player_stats.py](file:///f:/Python/MegabonkReroll/player_stats.py)
  - Unit Tests: [tests/test_player_stats.py](file:///f:/Python/MegabonkReroll/tests/test_player_stats.py)

---

## Memory Chain Diagrams

### 1. Base Tome Inventory Chain
```
owner_stats
  -> +0x28 (PLAYER_INVENTORY_OFFSET) -> [Player Inventory Pointer]
    -> +0x48 (TOME_INVENTORY_OFFSET)   -> [Tome Inventory Pointer]
```

### 2. Dictionaries Inside Tome Inventory
From the `TomeInventory Pointer`:
```
TomeInventory
  -> +0x18 (TOME_LEVELS_DICT_OFFSET)   -> [Tome Levels Dictionary Pointer]
  -> +0x28 (TOME_UPGRADES_DICT_OFFSET) -> [Tome Upgrades Dictionary Pointer]
```

### 3. Tome Levels Dictionary Decoding
```
tome_levels_dict
  -> +0x18 (DICT_ENTRIES_OFFSET) -> [Entries Memory Base Pointer]
  -> +0x20 (DICT_COUNT_OFFSET)   -> int (count of entries)

Each entry (Note: Size is 0x10):
Entries + 0x20 (DICT_ENTRY_START_OFFSET) + (Index * 0x10 (STAT_DICT_ENTRY_SIZE))
  -> +0x0 (DICT_ENTRY_HASH_CODE_OFFSET)  -> int (hash code; skip if < 0)
  -> +0x8 (STAT_DICT_ENTRY_KEY_OFFSET)   -> int (tome_id)
  -> +0xC (STAT_DICT_ENTRY_VALUE_OFFSET) -> int (tome level)
```

### 4. Tome Upgrades Dictionary Decoding
```
tome_upgrades_dict
  -> +0x18 (DICT_ENTRIES_OFFSET) -> [Entries Base Pointer]
  -> +0x20 (DICT_COUNT_OFFSET)   -> int (count of entries)

Each entry (Note: Size is 0x18):
Entries + 0x20 (DICT_ENTRY_START_OFFSET) + (Index * 0x18 (DICT_ENTRY_SIZE))
  -> +0x0  (DICT_ENTRY_HASH_CODE_OFFSET)  -> int (hash code; skip if < 0)
  -> +0x8  (WEAPON_DICT_ENTRY_KEY_OFFSET) -> int (tome_id)
  -> +0x10 (WEAPON_DICT_ENTRY_VALUE_OFFSET) -> [StatModifier Object Pointer]
    -> +0x10 (STAT_MODIFIER_STAT_OFFSET)  -> int (stat ID, e.g. 12 = Damage)
    -> +0x18 (STAT_MODIFIER_VALUE_OFFSET) -> float (effective stat modifier value)
```

---

## Reversing Walkthrough (Cheat Engine & IL2CPP)

### 1. Locating Offsets using IL2CPP Dump
Search for these classes in `dump.cs`:
- **`TomeInventory`**:
  - Locate fields of type `Dictionary<int, int>` or `Dictionary<ETome, int>`. E.g., check `tomeLevels` (offset `0x18`).
  - Locate fields of type `Dictionary<int, StatModifier>` or `Dictionary<ETome, StatModifier>`. E.g., check `tomeUpgrades` (offset `0x28`).
- **`StatModifier`**:
  - Verify fields like `stat` (offset `0x10`) and `value` (offset `0x18`).

### 2. Cheat Engine Live Verification
- **Trace Tome Levels**:
  - Purchase a Tome (e.g. Cooldown Tome) in the game.
  - Trace `owner_stats -> playerInventory -> tomeInventory -> tomeLevels`.
  - Walk the dictionary and confirm that the level associated with that tome ID increases.
  - Walk the `tomeUpgrades` dictionary and verify that the `value` matches the HUD effective boost (e.g. Cooldown reduction float = -0.05).
  - Verify if standard `.NET` Dictionary structure offsets (`Count`, `Entries`, and `Entry Size`) have changed.

---

## Code Reference
Offsets are defined in `PlayerStatsClient` in `player_stats.py`:
```python
class PlayerStatsClient:
    PLAYER_INVENTORY_OFFSET = 0x28
    TOME_INVENTORY_OFFSET = 0x48
    TOME_LEVELS_DICT_OFFSET = 0x18
    TOME_UPGRADES_DICT_OFFSET = 0x28
    
    DICT_ENTRIES_OFFSET = 0x18
    DICT_COUNT_OFFSET = 0x20
    DICT_ENTRY_START_OFFSET = 0x20
    DICT_ENTRY_SIZE = 0x18
    
    STAT_DICT_ENTRY_SIZE = 0x10
    STAT_DICT_ENTRY_KEY_OFFSET = 0x8
    STAT_DICT_ENTRY_VALUE_OFFSET = 0x0C
    # ...
```

---

## Verification Steps
1. Run pytest:
   ```powershell
   pytest tests/test_player_stats.py -k "tome"
   ```
2. Verify in the overlay interface under "Live Stats" that active tomes are listed with correct level counts and effective values.
