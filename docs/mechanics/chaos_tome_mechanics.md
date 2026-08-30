# Unified Guide on Chaos Tome Mechanics in Megabonk (Memory Layout, Formulas & Tracking)

This document consolidates reverse-engineering findings and analysis regarding the tracking of **Chaos Tome** (ID 24 / `0x18`) in Megabonk. It details where the data is stored in memory, the hidden dual-rarity logic behind stat generation, and how the fingerprint matching algorithm tracks rolls accurately without using invasive hooks.

Last code-path review: 2026-08-30. Offsets remain build-specific; this review
confirmed the documented roots against the current BonkScanner source, not
against a newly launched game process.

---

## 1. Memory Layout & Offsets

All tome data and player stats are linked to the player stats manager (`PlayerStats`). Below is the pointer chain and offsets to read from memory (tested on the IL2CPP-based build of Megabonk).

### 1.1. Locating Chaos Tome Level
The Chaos Tome level is stored in the tome inventory (`TomeInventory`):

1. **Player-stats TypeInfo**: `GameAssembly.dll` + `TYPE_INFO_OFFSET` (defined as `0x02F6A4B8` in `src/infra/memory/player_stats_client.py`). `RUN_STATS_TYPE_INFO_OFFSET` (`0x02F7A170`) belongs to run counters/damage sources and is not the owner-stats root.
2. **PlayerStats (ownerStats)**: `TypeInfo -> class_ptr +0xB8 -> static_fields +0x00 -> root +0x40 -> ownerStats`.
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

$$\text{Value} = \text{round3}\left(\text{round3}(\text{base} \times \text{rarity}_{inner}) \times 1.4 \times \text{rarity}_{outer}\right)$$

Where:
* **base**: The base value of the stat (see section 3).
* **1.4**: A fixed internal multiplier for the Chaos Tome (`chaosTomeMultiplier = 1.4f` from `TomeUtility`).
* **`rarity_inner`**: The hidden rarity of the random stat offer generated specifically for the Chaos Tome effect.
* **`rarity_outer`**: The rarity of the Chaos Tome upgrade that triggered the effect.
* Both rarities use a multiplier from the same pool:
  * `1.0` (Common)
  * `1.2` (Uncommon)
  * `1.4` (Rare)
  * `1.6` (Epic)
  * `2.0` (Legendary)
* **round3**: A helper function rounding to 3 decimal places (implemented as `StatUtility.GetRarityValue(..., 3)` in C#).

### 2.2. Why Are the Rarities Independent?
The two rarity inputs come from different stages of stat generation:
1. **Outer rarity**: The upgrade system rolls the rarity of the Chaos Tome upgrade before applying it. `TomeInventory.AddTome(..., ERarity rarity)` passes that already-rolled value to `TomeUtility.CheckSpecialTomes(tomeData, rarity)`.
2. **Inner rarity (`GetRandomStatOffers`)**: The Chaos branch calls `EncounterUtility.GetRandomStatOffers(1, false, false)`. This generates a new random stat offer with its own rarity, applies that rarity to the stat's base value, and rounds the result to 3 decimals.
3. **Final Chaos pass (`CheckSpecialTomes`)**: The handler multiplies the inner offer value by `chaosTomeMultiplier` (`1.4`) and applies the **outer rarity passed into the function**, then rounds the final result to 3 decimals. `CheckSpecialTomes` does not perform another rarity RNG call at this point.

The inner and outer rarities come from two separate rarity events. This creates **25 possible rarity combinations** ($\text{rarity}_{inner} \times \text{rarity}_{outer}$). Because of symmetry and rounding collisions, these map to **15 unique fingerprint values** per stat.

### 2.3. Luck Affects Both Rarities

Both rarity events are affected by the player's current **Luck**:

* The outer Chaos Tome upgrade uses the normal Luck-dependent upgrade-offer rarity path.
* For the inner hidden roll, `GetRandomStatOffers` reads `GetStat(EStat.Luck)` (`EStat` ID `30`) and passes the result to `Rarity.GetEncounterOfferRarity(luck)` before constructing the stat offer.

Therefore, the hidden secondary rarity roll is **not** a fixed or Luck-independent roll. Increasing Luck shifts both the visible outer upgrade rarity and the hidden inner stat-offer rarity toward higher tiers. The two results remain independent draws even though they use the same current Luck value and rarity-weight function.

This distinction does not affect the tracker's fingerprint matching: the tracker needs the complete set of possible values, not the probability of each combination.

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
1. The tracker client maintains an immutable snapshot of all permanent
   modifiers. Every one-second tick still validates the permanent dictionary
   and each list's pointer, size, and version, but a settled tick reuses the
   ready snapshot without re-reading `value` and `modifyType` from every
   `StatModifier` object.
2. A dictionary/list structural change refreshes the affected snapshot. A
   Chaos Tome level transition invalidates every cached modifier value and also
   arms one settling refresh on the following tick, so a sample taken inside
   the game's level/modifier writer window cannot remain stale.
3. When a value change is detected, the tracker calculates the difference:
   $\Delta = \text{value}_{\text{new}} - \text{value}_{\text{old}}$.
4. $\Delta$ is matched against individual fingerprints and, when several rolls
   were already stacked, combinations of valid fingerprints for the
   corresponding `StatID`.

Live stress validation on 2026-08-23 advanced Dice from level `81` to `4108`
and Chaos Tome from level `0` to `531`, growing the shared dictionary to `4657`
modifier objects. Cached samples were compared with independent full reads on
every stress tick and had zero persistent mismatches. At the settled endpoint,
the hot cached read averaged `0.740 ms` versus `114.098 ms` for a full read;
cached and uncached recovery produced identical complete Dice `4108/4108` and
Chaos `531/531` snapshots with zero ambiguous rolls.

### 4.2. Determining the Number of Rolls (N)
When leveling up a tome multiple levels at once, several rolls can stack simultaneously. For repeated identical fingerprints, the tracker can divide the delta by the fingerprint value and round to the nearest integer:

$$N = \text{round}\left(\frac{|\Delta|}{\text{fingerprint}}\right)$$

If the absolute difference between the actual delta and the theoretical value of $N \times \text{fingerprint}$ is within the epsilon tolerance:

$$|\Delta - (N \times \text{fingerprint})| \le 0.002 \times N$$

Then the change is successfully attributed as $N$ rolls of that specific fingerprint. If different fingerprints were combined before the first read, the tracker searches for the smallest valid combination within the same per-roll epsilon tolerance. The epsilon tolerance of `0.002` accounts for floating-point (`float32`) precision drift inside the Unity engine.

### 4.3. Late-Attach Limitation

Reconstructing Chaos rolls after BonkScanner starts in the middle of a run is best-effort. Permanent modifiers retain the final stat and value, but not the source or time at which each modifier was added. If a modifier from another source exactly matches a valid Chaos fingerprint, memory can contain more valid candidates than the Chaos Tome level allows. The tracker can still recover the correct total roll count, but it may assign one or more historical rolls to the wrong stat. Continuously tracked results are therefore more reliable than a reconstruction performed after an application restart.

---

## 5. Noise Reduction: Dice and Other Sources

A major challenge of tracking the Chaos Tome is that other game mechanics can also modify permanent stats. The main source of noise is the character **Dice** (internally `Dicehead`, passive `Gamba`), whose passive ability acts as a scaled-down version of the Chaos Tome.

The complete character-passive catalog, Dice formula, runtime fields, recovery
rules and UI contract are documented separately in
[Character Passives and Dice mechanics](./character_passives_mechanics.md).

### 5.1. Why Dice Requires Shared Source Attribution
Dice does **not** use a continuous random multiplier. For zero-based passive
roll index $n$, it chooses one of five discrete rarity multipliers and applies a
level-dependent decay:

$$
\begin{aligned}
\text{inner}(n) &= \operatorname{round3}(\text{base} \times \text{rarity}) \\
\text{decay}(n) &= \operatorname{clamp}\left(
\frac{0.75}{1 + (n / 50)^{1.5}}, 0.06, 1.0
\right) \\
\text{Value}_{\text{Gamba}}(n) &= \operatorname{float32}(
\operatorname{round3}(\text{inner}(n) \times 1.0) \times \text{decay}(n)
)
\end{aligned}
$$

The lower clamp begins at $n=255$, so later Dice rolls use a fixed discrete
fingerprint set. Early Dice values can also collide with, or fall inside the
old tolerance around, valid Chaos values. Numeric matching alone is therefore
not a safe separator.

Production tracking keeps the `StatModifier` object pointer and modification
type. Charge Shrine pointers are reserved exactly from `ShrineLogs.shownLog`;
Dice and Chaos budgets are then considered against the remaining shared
candidate set. A pointer claimed by Dice is hidden from Chaos, and a candidate
valid for both sources during the same budget window remains ambiguous rather
than being assigned by polling order.

### 5.2. Roll Budgeting (`_chaos_available_rolls`)
To ensure absolute reliability, the tracker implements a **roll budget** system:
* The tracker monitors the Chaos Tome level in memory.
* When the tome level increases by $+D$, the tracker increments the `_chaos_available_rolls` budget by $+D$.
* During modifier checks, the tracker only consumes matched rolls up to the remaining budget:
  
  $$\text{rolls\_to\_process} = \min(\text{\_chaos\_available\_rolls}, N)$$
  
* If the roll budget is `0`, no stat updates are recorded under the Chaos Tome.
* A positive budget is necessary but not sufficient for ownership. Exact
  Shrine reservations, Dice claims, and cross-source collisions are excluded
  before a Chaos candidate may consume the budget.

---

## 6. Complete Fingerprint Reference Table (15 Unique Values per Stat)

Below are all mathematically possible modifier values for a **single roll** of the Chaos Tome, sorted in descending order.

```python
# Formula:
# round3(round3(base * rarity_inner) * 1.4 * rarity_outer)
# for rarity_inner, rarity_outer in [2.0, 1.6, 1.4, 1.2, 1.0]
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
