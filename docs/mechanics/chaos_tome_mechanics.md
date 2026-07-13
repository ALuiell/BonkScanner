# Unified Guide on Chaos Tome Mechanics in Megabonk (Memory Layout, Formulas & Tracking)

This document consolidates reverse-engineering findings and analysis regarding the tracking of **Chaos Tome** (ID 24 / `0x18`) in Megabonk. It details where the data is stored in memory, the hidden dual-rarity logic behind stat generation, and how the fingerprint matching algorithm tracks rolls accurately without using invasive hooks.

---

## 1. Memory Layout & Offsets

All tome data and player stats are linked to the player stats manager (`PlayerStats`). Below is the pointer chain and offsets to read from memory (tested on the IL2CPP-based build of Megabonk).

### 1.1. Locating Chaos Tome Level
The Chaos Tome level is stored in the tome inventory (`TomeInventory`):

1. **Static Module Base**: `GameAssembly.dll` + `RUN_STATS_TYPE_INFO_OFFSET` (defined as `0x02F7A170` in `src/player_stats.py`).
2. **PlayerStats (ownerStats)**: `[StaticRoot + 0xB8] + 0x40` (class static fields -> `ownerStats`).
3. **PlayerInventory**: `[PlayerStats + 0x28]` (`PLAYER_INVENTORY_OFFSET`).
4. **TomeInventory**: `[PlayerInventory + 0x48]` (`TOME_INVENTORY_OFFSET`).
5. **Tome Levels Dictionary**: `[TomeInventory + 0x18]` (`TOME_LEVELS_DICT_OFFSET`).
   - Type: `Dictionary<int, int>` (TomeID -> Level).
   - Key for Chaos Tome: `24` (`0x18`).

### 1.2. Locating Permanent Modifiers
Stat improvements from the Chaos Tome are appended to the list of permanent stat changes:

1. **StatInventory**: `[PlayerInventory + 0x50]` (`STAT_INVENTORY_OFFSET`).
2. **Permanent Changes Dictionary**: `[StatInventory + 0x10]` (`STAT_INVENTORY_PERMANENT_CHANGES_OFFSET`).
   - Type: `Dictionary<int, List<StatModifier>>` (StatID -> List of modifiers).
   - Each `StatModifier` object in the list contains:
     - `stat_id` (int, offset `+0x10`): The ID of the stat.
     - `type` (int, offset `+0x14`): The modification type (`0 = Addition` / percentage, `2 = Flat` / absolute value).
     - `value` (float, offset `+0x18`): The modifier value.

---

## 2. The Hidden Dual-Rarity Formula

Unlike regular items and other tomes, the Megabonk developers implemented a dual-rarity check (rarity pass) when calculating the final Chaos Tome stat bonus.

### 2.1. Mathematical Representation
Each roll of the Chaos Tome is calculated using the following formula:

$$\text{Value} = \text{round3}\left(\text{round3}(\text{base} \times \text{rarity}_1) \times 1.4 \times \text{rarity}_2\right)$$

Where:
* **base**: The base value of the stat (see section 3).
* **1.4**: A fixed internal multiplier for the Chaos Tome (`chaosTomeMultiplier = 1.4f` from `TomeUtility`).
* **rarity₁ / rarity₂**: Rarity multipliers selected independently from the pool:
  * `1.0` (Common)
  * `1.2` (Uncommon)
  * `1.4` (Rare)
  * `1.6` (Epic)
  * `2.0` (Legendary)
* **round3**: A helper function rounding to 3 decimal places (implemented as `StatUtility.GetRarityValue(..., 3)` in C#).

### 2.2. Why Are the Rarities Independent?
The two-step calculation comes from the architecture of stat generation:
1. **First Pass (`GetRandomStatOffers`)**: The game selects a base stat and multiplies it by the first rolled rarity of the offer ($\text{rarity}_1$). The result is rounded to 3 decimals.
2. **Second Pass (`CheckSpecialTomes`)**: If the tome is a Chaos Tome, a special handler triggers, multiplying the rounded value by `1.4` and a second independently rolled rarity ($\text{rarity}_2$), then rounding the final result to 3 decimals.

This creates **25 possible rarity combinations** ($\text{rarity}_1 \times \text{rarity}_2$). Because of symmetry and rounding collisions, these map to **15 unique fingerprint values** per stat.

---

## 3. Base Stats & Modify Types Table

The Chaos Tome pool (defined by the static list `EncounterUtility.upgradableStatsChaosAndGamble`) contains **27 stats**.

| ID (EStat) | Code Name (EStat) | Modify Type | Base Value | Description |
| :---: | :--- | :---: | :---: | :--- |
| **0** | `MaxHealth` | Flat | `15` | Maximum Health |
| **1** | `HealthRegen` | Flat | `20` | Health Regeneration |
| **2** | `Shield` | Flat | `5` | Shield |
| **3** | `Thorns` | Flat | `5` | Thorns |
| **4** | `Armor` | Flat | `0.05` | Armor |
| **5** | `Evasion` | Flat | `0.05` | Evasion |
| **9** | `SizeMultiplier` | Addition | `0.08` (8%) | Character Size |
| **10** | `DurationMultiplier` | Addition | `0.08` (8%) | Effect Duration |
| **11** | `ProjectileSpeedMultiplier` | Addition | `0.10` (10%) | Projectile Speed |
| **12** | `DamageMultiplier` | Addition | `0.12` (12%) | Damage |
| **15** | `AttackSpeed` | Addition | `0.06` (6%) | Attack Speed |
| **16** | `Projectiles` | Flat | `1` | Projectile Count |
| **17** | `Lifesteal` | Flat | `0.06` | Lifesteal |
| **18** | `CritChance` | Flat | `0.05` | Critical Strike Chance |
| **19** | `CritDamage` | Addition | `0.10` (10%) | Critical Strike Damage |
| **23** | `EliteDamageMultiplier` | Addition | `0.10` (10%) | Damage to Elites |
| **24** | `KnockbackMultiplier` | Addition | `0.10` (10%) | Knockback |
| **25** | `MoveSpeedMultiplier` | Addition | `0.08` (8%) | Movement Speed |
| **29** | `PickupRange` | Addition | `0.20` (20%) | Item Pickup Range |
| **30** | `Luck` | Flat | `0.05` | Luck |
| **31** | `GoldIncreaseMultiplier` | Addition | `0.075` (7.5%) | Gold Gain Bonus |
| **32** | `XpIncreaseMultiplier` | Addition | `0.075` (7.5%) | XP Gain Bonus |
| **38** | `Difficulty` | Flat | `0.08` | Difficulty Multiplier |
| **39** | `EliteSpawnIncrease` | Addition | `0.15` (15%) | Elite Enemy Spawn Rate |
| **40** | `PowerupBoostMultiplier` | Addition | `0.10` (10%) | Powerup Effectiveness |
| **41** | `PowerupChance` | Addition | `0.05` (5%) | Powerup Drop Chance |
| **46** | `ExtraJumps` | Flat | `1` | Extra Jumps |

---

## 4. Memory Stacking & Fingerprint Matching

Because identical modifiers are stacked together in IL2CPP list collections rather than spawning separate objects, rolls are tracked by analyzing the delta of the combined value and mapping it against known fingerprints.

### 4.1. Stacking Mechanics in Memory
If the same stat is rolled multiple times (e.g., two Max Health rolls of the same or different rarities), the game adds the new roll value directly to the existing `StatModifier.value`.

To reconstruct the roll history:
1. The tracker client caches a snapshot of all permanent modifiers on every tick.
2. When a value change is detected, it calculates the difference: $\Delta = \text{value}_{\text{new}} - \text{value}_{\text{old}}$.
3. $\Delta$ is matched against individual fingerprints and, when several rolls were already stacked, combinations of valid fingerprints for the corresponding `StatID`.

### 4.2. Determining the Number of Rolls (N)
When leveling up a tome multiple levels at once, several rolls can stack simultaneously. For repeated identical fingerprints, the tracker can divide the delta by the fingerprint value and round to the nearest integer:

$$N = \text{round}\left(\frac{|\Delta|}{\text{fingerprint}}\right)$$

If the absolute difference between the actual delta and the theoretical value of $N \times \text{fingerprint}$ is within the epsilon tolerance:

$$|\Delta - (N \times \text{fingerprint})| \le 0.002 \times N$$

Then the change is successfully attributed as $N$ rolls of that specific fingerprint. If different fingerprints were combined before the first read, the tracker searches for the smallest valid combination within the same per-roll epsilon tolerance. The epsilon tolerance of `0.002` accounts for floating-point (`float32`) precision drift inside the Unity engine.

### 4.3. Late-Attach Limitation

Reconstructing Chaos rolls after BonkScanner starts in the middle of a run is best-effort. Permanent modifiers retain the final stat and value, but not the source or time at which each modifier was added. If a modifier from another source exactly matches a valid Chaos fingerprint, memory can contain more valid candidates than the Chaos Tome level allows. The tracker can still recover the correct total roll count, but it may assign one or more historical rolls to the wrong stat. Continuously tracked results are therefore more reliable than a reconstruction performed after an application restart.

---

## 5. Noise Reduction: Dice Head and Other Sources

A major challenge of tracking the Chaos Tome is that other game mechanics can also modify permanent stats. The main source of noise is the character **Dice Head** (Gamba), whose passive ability acts as a scaled-down version of the Chaos Tome.

### 5.1. Why Dice Head Does Not Cause False Positives
The Dice Head passive computes stat bonuses using a continuous randomized range:

$$\text{Value}_{\text{Gamba}} = \text{base} \times \text{upgradeMultiplier} \times \text{random}(\text{minMultiplier}, \text{maxMultiplier})$$

Since this formula uses a random continuous range, the probability of Dice Head randomly producing a value that matches one of the 15 discrete Chaos Tome fingerprints (within the `0.002` epsilon) is near zero.

### 5.2. Roll Budgeting (`_chaos_available_rolls`)
To ensure absolute reliability, the tracker implements a **roll budget** system:
* The tracker monitors the Chaos Tome level in memory.
* When the tome level increases by $+D$, the tracker increments the `_chaos_available_rolls` budget by $+D$.
* During modifier checks, the tracker only consumes matched rolls up to the remaining budget:
  
  $$\text{rolls\_to\_process} = \min(\text{\_chaos\_available\_rolls}, N)$$
  
* If the roll budget is `0`, no stat updates are recorded under the Chaos Tome. This completely ignores any outside changes from Dice Head passives, алтарей (shrines), or items.

---

## 6. Complete Fingerprint Reference Table (15 Unique Values per Stat)

Below are all mathematically possible modifier values for a **single roll** of the Chaos Tome, sorted in descending order.

```python
# Formula:
# round3(round3(base * r1) * 1.4 * r2) for r1, r2 in [2.0, 1.6, 1.4, 1.2, 1.0]
```

### 6.1. Flat Stats

* **Stat 0 (MaxHealth)** [Base: 15]
  `[84.0, 67.2, 58.8, 53.76, 50.4, 47.04, 42.0, 41.16, 40.32, 35.28, 33.6, 30.24, 29.4, 25.2, 21.0]`
* **Stat 1 (HealthRegen)** [Base: 20]
  `[112.0, 89.6, 78.4, 71.68, 67.2, 62.72, 56.0, 54.88, 53.76, 47.04, 44.8, 40.32, 39.2, 33.6, 28.0]`
* **Stat 2 (Shield)** [Base: 5]
  `[28.0, 22.4, 19.6, 17.92, 16.8, 15.68, 14.0, 13.72, 13.44, 11.76, 11.2, 10.08, 9.8, 8.4, 7.0]`
* **Stat 3 (Thorns)** [Base: 5]
  `[28.0, 22.4, 19.6, 17.92, 16.8, 15.68, 14.0, 13.72, 13.44, 11.76, 11.2, 10.08, 9.8, 8.4, 7.0]`
* **Stat 4 (Armor)** [Base: 0.05]
  `[0.28, 0.224, 0.196, 0.179, 0.168, 0.157, 0.14, 0.137, 0.134, 0.118, 0.112, 0.101, 0.098, 0.084, 0.07]`
* **Stat 5 (Evasion)** [Base: 0.05]
  `[0.28, 0.224, 0.196, 0.179, 0.168, 0.157, 0.14, 0.137, 0.134, 0.118, 0.112, 0.101, 0.098, 0.084, 0.07]`
* **Stat 16 (Projectiles)** [Base: 1]
  `[5.6, 4.48, 3.92, 3.584, 3.36, 3.136, 2.8, 2.744, 2.688, 2.352, 2.24, 2.016, 1.96, 1.68, 1.4]`
* **Stat 17 (Lifesteal)** [Base: 0.06]
  `[0.336, 0.269, 0.235, 0.215, 0.202, 0.188, 0.168, 0.165, 0.161, 0.141, 0.134, 0.121, 0.118, 0.101, 0.084]`
* **Stat 18 (CritChance)** [Base: 0.05]
  `[0.28, 0.224, 0.196, 0.179, 0.168, 0.157, 0.14, 0.137, 0.134, 0.118, 0.112, 0.101, 0.098, 0.084, 0.07]`
* **Stat 30 (Luck)** [Base: 0.05]
  `[0.28, 0.224, 0.196, 0.179, 0.168, 0.157, 0.14, 0.137, 0.134, 0.118, 0.112, 0.101, 0.098, 0.084, 0.07]`
* **Stat 38 (Difficulty)** [Base: 0.08]
  `[0.448, 0.358, 0.314, 0.287, 0.269, 0.251, 0.224, 0.22, 0.215, 0.188, 0.179, 0.161, 0.157, 0.134, 0.112]`
* **Stat 46 (ExtraJumps)** [Base: 1]
  `[5.6, 4.48, 3.92, 3.584, 3.36, 3.136, 2.8, 2.744, 2.688, 2.352, 2.24, 2.016, 1.96, 1.68, 1.4]`

### 6.2. Addition (Percentage) Stats

* **Stat 9 (SizeMultiplier)** [Base: 8%]
  `[0.448, 0.358, 0.314, 0.287, 0.269, 0.251, 0.224, 0.22, 0.215, 0.188, 0.179, 0.161, 0.157, 0.134, 0.112]` (from 11.2% to 44.8%)
* **Stat 10 (DurationMultiplier)** [Base: 8%]
  `[0.448, 0.358, 0.314, 0.287, 0.269, 0.251, 0.224, 0.22, 0.215, 0.188, 0.179, 0.161, 0.157, 0.134, 0.112]` (from 11.2% to 44.8%)
* **Stat 11 (ProjectileSpeedMultiplier)** [Base: 10%]
  `[0.56, 0.448, 0.392, 0.358, 0.336, 0.314, 0.28, 0.274, 0.269, 0.235, 0.224, 0.202, 0.196, 0.168, 0.14]` (from 14% to 56%)
* **Stat 12 (DamageMultiplier)** [Base: 12%]
  `[0.672, 0.538, 0.47, 0.43, 0.403, 0.376, 0.336, 0.329, 0.323, 0.282, 0.269, 0.242, 0.235, 0.202, 0.168]` (from 16.8% to 67.2%)
* **Stat 15 (AttackSpeed)** [Base: 6%]
  `[0.336, 0.269, 0.235, 0.215, 0.202, 0.188, 0.168, 0.165, 0.161, 0.141, 0.134, 0.121, 0.118, 0.101, 0.084]` (from 8.4% to 33.6%)
* **Stat 19 (CritDamage)** [Base: 10%]
  `[0.56, 0.448, 0.392, 0.358, 0.336, 0.314, 0.28, 0.274, 0.269, 0.235, 0.224, 0.202, 0.196, 0.168, 0.14]` (from 14% to 56%)
* **Stat 23 (EliteDamageMultiplier)** [Base: 10%]
  `[0.56, 0.448, 0.392, 0.358, 0.336, 0.314, 0.28, 0.274, 0.269, 0.235, 0.224, 0.202, 0.196, 0.168, 0.14]` (from 14% to 56%)
* **Stat 24 (KnockbackMultiplier)** [Base: 10%]
  `[0.56, 0.448, 0.392, 0.358, 0.336, 0.314, 0.28, 0.274, 0.269, 0.235, 0.224, 0.202, 0.196, 0.168, 0.14]` (from 14% to 56%)
* **Stat 25 (MoveSpeedMultiplier)** [Base: 8%]
  `[0.448, 0.358, 0.314, 0.287, 0.269, 0.251, 0.224, 0.22, 0.215, 0.188, 0.179, 0.161, 0.157, 0.134, 0.112]` (from 11.2% to 44.8%)
* **Stat 29 (PickupRange)** [Base: 20%]
  `[1.12, 0.896, 0.784, 0.717, 0.672, 0.627, 0.56, 0.549, 0.538, 0.47, 0.448, 0.403, 0.392, 0.336, 0.28]` (from 28% to 112%)
* **Stat 31 (GoldIncreaseMultiplier)** [Base: 7.5%]
  `[0.42, 0.336, 0.294, 0.269, 0.252, 0.235, 0.21, 0.206, 0.202, 0.176, 0.168, 0.151, 0.147, 0.126, 0.105]` (from 10.5% to 42%)
* **Stat 32 (XpIncreaseMultiplier)** [Base: 7.5%]
  `[0.42, 0.336, 0.294, 0.269, 0.252, 0.235, 0.21, 0.206, 0.202, 0.176, 0.168, 0.151, 0.147, 0.126, 0.105]` (from 10.5% to 42%)
* **Stat 39 (EliteSpawnIncrease)** [Base: 15%]
  `[0.84, 0.672, 0.588, 0.538, 0.504, 0.47, 0.42, 0.412, 0.403, 0.353, 0.336, 0.302, 0.294, 0.252, 0.21]` (from 21% to 84%)
* **Stat 40 (PowerupBoostMultiplier)** [Base: 10%]
  `[0.56, 0.448, 0.392, 0.358, 0.336, 0.314, 0.28, 0.274, 0.269, 0.235, 0.224, 0.202, 0.196, 0.168, 0.14]` (from 14% to 56%)
* **Stat 41 (PowerupChance)** [Base: 5%]
  `[0.28, 0.224, 0.196, 0.179, 0.168, 0.157, 0.14, 0.137, 0.134, 0.118, 0.112, 0.101, 0.098, 0.084, 0.07]` (from 7% to 28%)
