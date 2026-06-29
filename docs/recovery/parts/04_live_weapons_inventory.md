# Part 4: Live Weapons Inventory Recovery Guide

## Overview
This component reads the active run's weapons, their levels, and their stats. It parses the weapons dictionary, gets the level, extracts the weapon configuration, and parses the weapon stats dictionary. It also decodes the upgrade stat modifiers to distinguish between the weapon's base stats and stats upgraded by the weapon's level-up pool.

- **Target Files**:
  - Code: `src/player_stats.py`
  - Unit Tests: `src/tests/test_player_stats.py`

---

## Memory Chain Diagrams

### 1. Base Weapon Inventory Chain
```
owner_stats
  -> +0x28 (PLAYER_INVENTORY_OFFSET) -> [Player Inventory Pointer]
    -> +0x28 (WEAPON_INVENTORY_OFFSET) -> [Weapon Inventory Pointer]
      -> +0x18 (WEAPONS_DICT_OFFSET)   -> [Weapons Dictionary Pointer]
```

### 2. Weapons Dictionary Decoding
```
weapons_dict
  -> +0x18 (DICT_ENTRIES_OFFSET) -> [Entries Memory Base Pointer]
  -> +0x20 (DICT_COUNT_OFFSET)   -> int (count of entries)

Each Weapon Entry:
Entries + 0x20 (DICT_ENTRY_START_OFFSET) + (Index * 0x18 (WEAPON_DICT_ENTRY_SIZE))
  -> +0x0  (DICT_ENTRY_HASH_CODE_OFFSET)  -> int (hash code; skip if < 0)
  -> +0x8  (WEAPON_DICT_ENTRY_KEY_OFFSET) -> int (weapon_id)
  -> +0x10 (WEAPON_DICT_ENTRY_VALUE_OFFSET) -> [WeaponBase Object Pointer]
```

### 3. WeaponBase Structure
From the `WeaponBase Object Pointer`:
```
WeaponBase
  -> +0x20 (WEAPON_LEVEL_OFFSET)      -> int (weapon level)
  -> +0x28 (WEAPON_STATS_DICT_OFFSET) -> [Weapon Stats Dictionary Pointer]
  -> +0x18 (WEAPON_DATA_OFFSET)       -> [WeaponData Object Pointer]
    -> +0x50 (WEAPON_ID_OFFSET)           -> int (resolved weapon ID)
    -> +0xD8 (WEAPON_UPGRADE_DATA_OFFSET) -> [WeaponUpgradeData Pointer]
      -> +0x18 (UPGRADE_MODIFIERS_OFFSET)   -> [List of UpgradeModifiers Pointer]
        -> +0x10 (LIST_ITEMS_OFFSET)          -> [Array of UpgradeModifier Pointers]
        -> +0x18 (LIST_SIZE_OFFSET)           -> int (size of list)
```

Each UpgradeModifier Pointer in Array:
`Array + 0x20 (ARRAY_DATA_OFFSET) + (Index * 0x8 (OBJECT_POINTER_SIZE))`
  -> +0x10 (STAT_MODIFIER_STAT_OFFSET) -> int (stat ID, e.g., 12 = Damage)

### 4. Weapon Stats Dictionary Decoding
From the `Weapon Stats Dictionary Pointer`:
```
weapon_stats_dict
  -> +0x18 (DICT_ENTRIES_OFFSET) -> [Entries Memory Base Pointer]
  -> +0x20 (DICT_COUNT_OFFSET)   -> int (count of entries)

Each Stat Entry (Note: Size is 0x10, not 0x18):
Entries + 0x20 (DICT_ENTRY_START_OFFSET) + (Index * 0x10 (STAT_DICT_ENTRY_SIZE))
  -> +0x0 (DICT_ENTRY_HASH_CODE_OFFSET)  -> int (hash code; skip if < 0)
  -> +0x8 (STAT_DICT_ENTRY_KEY_OFFSET)   -> int (stat ID)
  -> +0xC (STAT_DICT_ENTRY_VALUE_OFFSET) -> float (stat value)
```

---

## Reversing Walkthrough (Cheat Engine & IL2CPP)

### 1. Locating Offsets using IL2CPP Dump
Search for these classes and structures in `dump.cs`:
- **`WeaponInventory`**:
  - Look for fields of type `Dictionary<int, WeaponBase>` or `Dictionary<EWeapon, WeaponBase>`.
  - E.g., check `weapons` (offset `0x18`).
- **`WeaponBase`**:
  - Find fields like `level` (offset `0x20`), `weaponData` (offset `0x18`), and `weaponStats` (offset `0x28`).
- **`WeaponData`**:
  - Find fields like `weaponId` (offset `0x50`) and `upgradeData` (offset `0xD8`).
- **`UpgradeData`**:
  - Find fields of type `List<StatModifier>` (offset `0x18`).
- **`StatModifier`**:
  - Find fields like `stat` (offset `0x10`), `type` (offset `0x14`), and `value` (offset `0x18`).

### 2. Cheat Engine Live Verification
- **Verify Weapon Levels**:
  - Pick up a weapon (e.g. Fire Staff) or level it up.
  - Trace `owner_stats -> playerInventory -> weaponInventory -> weapons`.
  - Verify that the weapon entry level at `weapon_base + 0x20` matches the level shown in the game HUD.
- **Verify Stats**:
  - Walk the `weaponStats` dictionary. Verify that the float values at `Entries + 0xC` match HUD stats (e.g. Damage = 10.0, Attack Speed = 1.16).
  - Verify if standard `.NET` Dictionary offsets for `Count`, `Entries`, and `Entry Size` have changed.

---

## Code Reference
Offsets are defined in `PlayerStatsClient` in `src/player_stats.py`:
```python
class PlayerStatsClient:
    PLAYER_INVENTORY_OFFSET = 0x28
    WEAPON_INVENTORY_OFFSET = 0x28
    WEAPONS_DICT_OFFSET = 0x18
    WEAPON_LEVEL_OFFSET = 0x20
    WEAPON_DATA_OFFSET = 0x18
    WEAPON_STATS_DICT_OFFSET = 0x28
    WEAPON_ID_OFFSET = 0x50
    WEAPON_UPGRADE_DATA_OFFSET = 0xD8
    UPGRADE_MODIFIERS_OFFSET = 0x18
    
    WEAPON_DICT_ENTRY_SIZE = 0x18
    WEAPON_DICT_ENTRY_KEY_OFFSET = 0x8
    WEAPON_DICT_ENTRY_VALUE_OFFSET = 0x10
    
    STAT_DICT_ENTRY_SIZE = 0x10
    STAT_DICT_ENTRY_KEY_OFFSET = 0x8
    STAT_DICT_ENTRY_VALUE_OFFSET = 0x0C
    # ...
```

---

## Verification Steps
1. Run pytest:
   ```powershell
   pytest src/tests/test_player_stats.py -k "weapon"
   ```
2. Verify in the overlay interface under "Live Stats" that active weapons appear with correct names (e.g. "Fire Staff"), levels, and stat matrices.