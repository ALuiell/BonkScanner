# Part 8: Player Status Effects and Active Buffs Recovery Guide

## Overview
This component monitors the active status effects (buffs and debuffs) currently applied to the player character, such as Haste, Rage, Shield, Stonks, TimeFreeze, or Invulnerability. It resolves the player inventory status effects pointer and iterates over the active effects dictionary to read expiration timers and effect types.

- **Target Files**:
  - Code: `src/player_stats.py`
  - Unit Tests: `src/tests/test_player_stats.py`

---

## Memory Chain Diagrams

### 1. Base Status Effects Chain
```
owner_stats (resolved from PlayerStatsNew, see Part 2)
  -> +0x28 (PLAYER_INVENTORY_OFFSET) -> [Player Inventory Pointer]
    -> +0x38 (PLAYER_STATUS_EFFECTS_OFFSET) -> [PlayerStatusEffects Pointer]
      -> +0x10 (PLAYER_STATUS_EFFECTS_DICT_OFFSET) -> [Dictionary<EStatusEffect, StatusEffect> Pointer]
```

### 2. Traversal of the Status Effects Dictionary
```
status_effects_dict
  -> +0x18 (DICT_ENTRIES_OFFSET) -> [Entries Memory Base Pointer]
  -> +0x20 (DICT_COUNT_OFFSET)   -> int (count of entries)

Each Entry (Note: Size is 0x18, Key is effect_key, Value is StatusEffect pointer):
Entries + 0x20 (DICT_ENTRY_START_OFFSET) + (Index * 0x18 (DICT_ENTRY_SIZE))
  -> +0x0  (DICT_ENTRY_HASH_CODE_OFFSET)  -> int (hash code; skip if < 0)
  -> +0x8  (DICT_ENTRY_KEY_OFFSET)        -> int (effect_key / EStatusEffect enum ID)
  -> +0x10 (DICT_ENTRY_VALUE_OFFSET)      -> [StatusEffect Object Pointer]
```

### 3. StatusEffect Object Layout
```
StatusEffect Object Pointer
  -> +0x10 (STATUS_EFFECT_ESTATUS_OFFSET)    -> int (eStatusEffect enum ID)
  -> +0x20 (STATUS_EFFECT_EXPIRATION_OFFSET) -> float (expiration time in run seconds)
  -> +0x24 (STATUS_EFFECT_ADDED_OFFSET)      -> float (added time in run seconds)
```

---

## EStatusEffect Enum Mapping
| ID | Enum Member | Common Name / Buff |
| --- | --- | --- |
| **0** | `Haste` | Haste (Speed Powerup) |
| **1** | `Rage` | Rage (Damage Boost) |
| **2** | `Shield` | Shield |
| **3** | `Stonks` | Stonks (Money / Gold Multiplier) |
| **4** | `TimeFreeze` | Time Freeze (Time Stomp) |
| **5** | `Invulnerability` | Invulnerability |
| **6** | `Slow` | Slow (Debuff) |
| **7** | `Freeze` | Freeze (Debuff) |
| **8** | `Bleed` | Bleed (Debuff) |
| **9** | `Poison` | Poison (Debuff) |
| **10**| `BossPoison` | Boss Poison (Debuff) |

---

## Reversing Walkthrough (Cheat Engine & IL2CPP)

### 1. Locating Offsets using IL2CPP Dump
Search for these classes and enums in `dump.cs`:
- **`PlayerInventory`**: Check offset for `statusEffects` field (typically `0x38`).
- **`PlayerStatusEffects`**: Locate the dictionary of status effects (typically `0x10`).
- **`StatusEffect`**: Verify fields like `eStatusEffect` (offset `0x10`), `expirationTime` (offset `0x20`), and `addedTime` (offset `0x24`).
- **`EStatusEffect`**: Locate enum constants and verify if new effects were added.

### 2. Cheat Engine Live Verification
- **Verify Active Buffs**:
  - Pick up a Haste powerup in the game.
  - Trace `owner_stats -> playerInventory -> statusEffects -> statusEffects` dictionary.
  - Confirm entry under key `0` exists and has `hash_code >= 0`.
  - Read the float expiration time at `StatusEffect + 0x20`. Verify that `expirationTime - currentRunTime` is positive and decreases dynamically.

---

## Code Reference
Offsets are defined in `PlayerStatsClient` in `src/player_stats.py`:
```python
class PlayerStatsClient:
    PLAYER_INVENTORY_OFFSET = 0x28
    PLAYER_STATUS_EFFECTS_OFFSET = 0x38
    PLAYER_STATUS_EFFECTS_DICT_OFFSET = 0x10
    
    STATUS_EFFECT_ESTATUS_OFFSET = 0x10
    STATUS_EFFECT_EXPIRATION_OFFSET = 0x20
    STATUS_EFFECT_ADDED_OFFSET = 0x24
```

---

## Verification Steps
1. Run tests:
   ```powershell
   .\run_tests.bat -k "status_effect" src.tests.test_player_stats
   ```
2. Activate a powerup in-game and verify that the active effect shows up correctly on the overlay panel.
