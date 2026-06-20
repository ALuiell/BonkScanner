# Player Status Effects and Active Buffs

Date: 2026-06-20

## Goal

Document the reverse-engineered path and data structures used to detect active status effects (buffs/debuffs) on the player character in Megabonk.

This information is intended to allow the memory scanner to monitor if the player is currently under specific effects such as Rage, Shield, Haste, Time Freeze (Time Stomp), Stonks, or Invulnerability.

## Confirmed Stable Pointer Path

All active status effects are managed by the `PlayerStatusEffects` class, which is nested within the player's inventory.

The path starts from the base `owner_stats` pointer:

```text
owner_stats
-> +0x28  (PlayerInventory)
   -> +0x38  (PlayerStatusEffects)
      -> +0x10  (Dictionary<EStatusEffect, StatusEffect> statusEffects)
```

### Traversing the Status Effects Dictionary

The dictionary is a standard C# `.NET` / Mono dictionary structure.

1. **Get Entries and Count:**
   - `entries_array_ptr` = `read_ptr(dictionary_address + 0x18)` (offset `DICT_ENTRIES_OFFSET`)
   - `count` = `read_i32(dictionary_address + 0x20)` (offset `DICT_COUNT_OFFSET`)

2. **Get Dictionary Capacity:**
   - `capacity` = `read_i32(entries_array_ptr + 0x18)` (offset `ARRAY_LENGTH_OFFSET`)

3. **Loop through Entries:**
   - For `index` from `0` to `capacity - 1`:
     - `entry_address` = `entries_array_ptr + 0x20 + (index * 0x18)`
     - `hash_code` = `read_i32(entry_address + 0x0)`
     - If `hash_code < 0`, the slot is empty or has been deleted (skip it).
     - `effect_key` = `read_i32(entry_address + 0x8)` (corresponds to the `EStatusEffect` enum)
     - `effect_ptr` = `read_ptr(entry_address + 0x10)` (pointer to `StatusEffect` object instance)

### StatusEffect Instance Fields

Each `StatusEffect` class instance contains the following fields:

```text
StatusEffect
-> +0x10: eStatusEffect (int / EStatusEffect enum value)
-> +0x18: modifiers (pointer to StatModifier[] array)
-> +0x20: expirationTime (float, run time in seconds when effect expires)
-> +0x24: addedTime (float, run time in seconds when effect was applied)
```

## EStatusEffect Enum Values

The status effects are identified by the following integer IDs mapping to the `EStatusEffect` enum:

| ID | Enum Member | Common Name / Buff |
|---|---|---|
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

## Reverse Evidence

From `dump.cs`, the relevant structures are defined as follows:

```csharp
// Namespace: Assets.Scripts.Inventory__Items__Pickups.Stats
public enum EStatusEffect // TypeDefIndex: 5575
{
	public int value__; // 0x0
	public const EStatusEffect Haste = 0;
	public const EStatusEffect Rage = 1;
	public const EStatusEffect Shield = 2;
	public const EStatusEffect Stonks = 3;
	public const EStatusEffect TimeFreeze = 4;
	public const EStatusEffect Invulnerability = 5;
	public const EStatusEffect Slow = 6;
	public const EStatusEffect Freeze = 7;
	public const EStatusEffect Bleed = 8;
	public const EStatusEffect Poison = 9;
	public const EStatusEffect BossPoison = 10;
}

// Namespace: 
public class PlayerInventory // TypeDefIndex: 4801
{
	public PlayerStatsNew playerStats; // 0x10
	public CharacterData characterData; // 0x18
	public ItemInventory itemInventory; // 0x20
	public WeaponInventory weaponInventory; // 0x28
	public PlayerXp playerXp; // 0x30
	public PlayerStatusEffects statusEffects; // 0x38
    ...
}

// Namespace: Assets.Scripts.Inventory__Items__Pickups.Stats
public class PlayerStatusEffects // TypeDefIndex: 5577
{
	public Dictionary<EStatusEffect, StatusEffect> statusEffects; // 0x10
    ...
}

// Namespace: Assets.Scripts.Inventory__Items__Pickups.Stats
public class StatusEffect // TypeDefIndex: 5584
{
	public EStatusEffect eStatusEffect; // 0x10
	public StatModifier[] modifiers; // 0x18
	public float expirationTime; // 0x20
	public float addedTime; // 0x24
}
```

## Live Validation

A test script was run on the live `Megabonk.exe` process with the following memory verification:

- `owner_stats` pointer: `0x1b942719060`
- `player_inventory` pointer: `0x1ba3be48320`
- `statusEffects` pointer: `0x1b942711120`
- `statusEffects` dictionary pointer: `0x1b942719300`
- Current run timer observed: `731.37` seconds

Traversing the dictionary, expired/removed effects left inactive entry slots with `hash_code = -1` and `value = 0` (null), while active effects are retained with `hash_code >= 0` and point to active `StatusEffect` class objects.

## Recommended Usage

To check if the player is currently under a specific status effect (e.g., Rage):

1. Traverse the `statusEffects` dictionary.
2. Find the entry matching `key == 1` (Rage).
3. Read the `expirationTime` field at offset `0x20` of the `StatusEffect` instance.
4. Read the current game run timer using `get_run_timer()`.
5. The effect is active if:
   $$\text{expirationTime} - \text{runTimer} > 0$$
