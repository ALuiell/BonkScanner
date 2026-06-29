# Part 2: Player Stats Recovery Guide

## Overview
This component reads the active player's stats (e.g. Max HP, Damage, Crit Chance, Luck, XP Gain, etc.) from the in-game player stats tab. It resolves the primary `PlayerStatsNew` static instance, traverses to the stats context entries, and extracts values for predefined stat IDs.

- **Target Files**:
  - Code: `src/player_stats.py`
  - UI Overlay: `src/gui_player_stats.py`
  - Unit Tests: `src/tests/test_player_stats.py`

---

## Memory Chain Diagram

```
GameAssembly.dll + TYPE_INFO_OFFSET (0x02F6A4B8)
  -> [Class Pointer]
    -> +0xB8 (CLASS_STATIC_FIELDS_OFFSET) -> [Static Fields Pointer]
      -> +0x0 (STATIC_ROOT_OFFSET)        -> [Root Object Pointer] (e.g., PlayerStatsManager)
        -> +0x40 (OWNER_STATS_OFFSET)      -> [PlayerStatsNew Object Pointer]
          -> +0x10 (STATS_CONTEXT_OFFSET)  -> [StatsContext Object Pointer]
            -> +0x18 (STATS_ENTRIES_OFFSET) -> [Entries Memory Base Pointer]
```

### Reading Individual Stats
Once `Entries Memory Base Pointer` is retrieved:
```
Stat Offset = STAT_VALUE_BASE_OFFSET (0x2C) + (Stat ID * STAT_SLOT_SIZE (0x10))
Stat Float Value = read_float(Entries + Stat Offset)
```

### Predefined Stat IDs & Formats
| Stat Name | Stat ID | Value Format |
| --- | --- | --- |
| Max HP | 0 | FLAT |
| HP Regen | 1 | FLAT |
| Shield | 2 | FLAT |
| Thorns | 3 | FLAT |
| Armor | 4 | PERCENT |
| Evasion | 5 | PERCENT |
| Size | 9 | MULTIPLIER |
| Duration | 10 | MULTIPLIER |
| Projectile Speed | 11 | MULTIPLIER |
| Damage | 12 | MULTIPLIER |
| Attack Speed | 15 | PERCENT |
| Projectile Count | 16 | FLAT |
| Lifesteal | 17 | PERCENT |
| Crit Chance | 18 | PERCENT |
| Crit Damage | 19 | MULTIPLIER |
| Damage to Elites | 23 | MULTIPLIER |
| Knockback | 24 | MULTIPLIER |
| Movement Speed | 25 | MULTIPLIER |
| Pickup Range | 29 | FLAT |
| Luck | 30 | PERCENT |
| Gold Gain | 31 | MULTIPLIER |
| XP Gain | 32 | MULTIPLIER |
| Difficulty | 38 | PERCENT |
| Elite Spawn Increase | 39 | MULTIPLIER |
| Powerup Multiplier | 40 | MULTIPLIER |
| Powerup Drop Chance | 41 | MULTIPLIER |
| Extra Jumps | 46 | FLAT |

*Note: Overheal, Projectile Bounces, and Jump Height do not use direct stat ID offsets in `PLAYER_STAT_GROUPS` (mapped as `None`).*

---

## Reversing Walkthrough (Cheat Engine & IL2CPP)

### 1. Locating Offsets using IL2CPP Dump
Search for `PlayerStatsNew` or the class that controls it (e.g. `PlayerStatsClient` or `PlayerStatsManager`) in `dump.cs`:
- Identify the class with static instance fields representing player stats.
- Look at the fields in `PlayerStatsNew`:
  - `statsContext` (offset `0x10`)
  - `playerInventory` (offset `0x28`)
  - `inventoryContainer` (offset `0xA0`)
- Look at `StatsContext` fields to find the entries table (offset `0x18`).
- Verify if `STAT_VALUE_BASE_OFFSET` (`0x2C`) or `STAT_SLOT_SIZE` (`0x10`) changed by reviewing the struct layout of stat entry objects or arrays.

### 2. Cheat Engine Live Verification
- **Find Root Instance**:
  - Filter for `PlayerStatsNew` instances or start a memory scan for the active player's max health (e.g., 200).
  - Modify stats in-game (by leveling up or selecting upgrade tomes) and scan for changes.
  - Trace pointers to find the stable static pointer from `GameAssembly.dll`.
- **Confirm Stat Slots**:
  - Verify that the floating-point values at `Entries + 0x2C` matches max HP, `Entries + 0x2C + 0x10` matches HP regen, and so forth. If the slot size changed from `0x10` or base from `0x2C`, map it accordingly.

---

## Code Reference
Offsets are defined in `PlayerStatsClient` in `src/player_stats.py`:
```python
class PlayerStatsClient:
    TYPE_INFO_OFFSET = 0x02F6A4B8
    CLASS_STATIC_FIELDS_OFFSET = 0xB8
    STATIC_ROOT_OFFSET = 0x0
    OWNER_STATS_OFFSET = 0x40
    STATS_CONTEXT_OFFSET = 0x10
    STATS_ENTRIES_OFFSET = 0x18
    STAT_VALUE_BASE_OFFSET = 0x2C
    STAT_SLOT_SIZE = 0x10
    # ...
```

---

## Verification Steps
1. Run pytest:
   ```powershell
   pytest src/tests/test_player_stats.py
   ```
2. Launch the overlay and verify that "Live Stats" tab outputs matches the values in the in-game stats UI.