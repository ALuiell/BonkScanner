# Reverse Engineering Report: Charge Shrine Mechanics and Fingerprints

This report documents the confirmed Charge Shrine reward pipeline, rarity behavior, permanent-modifier fingerprints, and a candidate tracking source for a future `!shrines` command.

## 1. Shrine and Beacon Mechanics

Each map spawns 15 Charge Shrines by default. The Beacon passive item (`EItem.Beacon = 78`) increases shrine availability. A clean 15-shrine control test found no reward-value scaling from Beacon.

### 1.1. ItemBeacon

`ItemBeacon` inherits from `ItemBase`. Relevant fields include:

```csharp
private int extraShrinesPerAmount;         // +0x30
private float healingRadiusPerAmount;      // +0x34
private float healingFractionPerInterval;  // +0x38
```

Relevant methods:

- `GetExtraShrines()` controls the additional shrine count.
- `GetRewardMultiplier()` at RVA `0x462D90` controls reward magnitude.

The active ScriptableObject preset sets `healingRadiusPerAmount` to `0.075f`, despite its constructor default of `0.18f`.

The initial static-analysis interpretation was `1.0 + BeaconStacks * 0.075`. Live testing disproved the stack-scaling part in the current build: with the inventory reporting `Beacon x3`, new offers and selected modifiers still used exactly `1.075`, not `1.225`.

Earlier runs contained a shared `1.075` modifier, but a controlled `Beacon x1` test later produced 15 nominal rewards with no multiplier. Therefore, the source of `1.075` is unknown and must not be attributed to Beacon.

Confirmed runtime behavior:

```text
Beacon absent: 1.0
Beacon x1: 1.0 in a clean 15-shrine test
```

The interpretation of RVA `0x462D90` and the earlier `1.075` samples requires another disassembly pass.

Examples:

| Displayed Beacon stacks | Observed reward multiplier |
| ---: | ---: |
| 0 | `1.0` |
| 1 | `1.0` in clean control |
| 2 | not independently tested |
| 3 | inconclusive: earlier run had an unidentified `1.075` source |

Beacon does not determine rarity. Luck is passed to `Rarity.GetEncounterOfferRarity(luck)`.

## 2. Charge Shrine Reward Flow

`ChargeShrine.Reward()` calls `EncounterUtility.GetRandomStatOffers(3, ..., useShrineStats = true)`.

- Exactly three stat offers are generated.
- The player selects exactly one offer.
- Only the selected `StatModifier` is applied.
- Rarity is rolled independently for each of the three offers.
- A golden shrine sets `forceLegendary`, making all three offers Legendary.

Relevant `ChargeShrine` fields:

```csharp
private bool <isGolden>k__BackingField;  // +0x108
private bool completed;                  // +0x124
private float rewardTime;                // +0x128
private bool rewardGiven;                // +0x12C
private bool charging;                   // +0x12D
```

Relevant methods and events:

```csharp
private void Complete();  // RVA 0x4C1F00
private void Reward();    // RVA 0x4C28D0

public static Action A_ChargeShrineSpawned;
public static Action<bool> A_Charged;
public static ChargeShrine lastRewardShrine;
```

## 3. Exact Value Pipeline

### 3.1. Rarity

`Rarity.GetEncounterOfferRarity(luck)` at RVA `0x42D2C0` returns:

| ERarity | Value | Multiplier |
| :--- | ---: | ---: |
| Common | 1 | `1.0` |
| Uncommon | 2 | `1.2` |
| Rare | 3 | `1.4` |
| Epic | 4 | `1.6` |
| Legendary | 5 | `2.0` |

### 3.2. Calculation Order

`EncounterUtility.GetRandomStatOffers` at RVA `0x436720` calculates:

```text
OfferValue = round3(BaseValue * RarityMultiplier)
```

The three-decimal rounding helper is at RVA `0x436390`. The rounded value is written to `statModifier.modification`.

Static analysis suggested an additional pass in `EncounterData.GetOffers()` at RVA `0x3DED80`, but clean runtime testing did not observe Beacon scaling. The confirmed stored-value formula for clean runs is:

```text
StoredValue = OfferValue
```

There is no observed second rounding pass. The raw float is added to `StatInventory.permanentChanges`. UI formatting performs display rounding only.

## 4. Base Values and Nominal Fingerprints

The table contains values after `round3(BaseValue * RarityMultiplier)`.

| ID | Stat | Type | Base | Common | Uncommon | Rare | Epic | Legendary |
| ---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | MaxHealth | Flat | `15` | `15` | `18` | `21` | `24` | `30` |
| 1 | HealthRegen | Flat | `20` | `20` | `24` | `28` | `32` | `40` |
| 2 | Shield | Flat | `5` | `5` | `6` | `7` | `8` | `10` |
| 3 | Thorns | Flat | `5` | `5` | `6` | `7` | `8` | `10` |
| 4 | Armor | Flat | `0.05` | `0.05` | `0.06` | `0.07` | `0.08` | `0.10` |
| 5 | Evasion | Flat | `0.05` | `0.05` | `0.06` | `0.07` | `0.08` | `0.10` |
| 9 | SizeMultiplier | Addition | `0.08` | `0.08` | `0.096` | `0.112` | `0.128` | `0.16` |
| 10 | DurationMultiplier | Addition | `0.08` | `0.08` | `0.096` | `0.112` | `0.128` | `0.16` |
| 11 | ProjectileSpeedMultiplier | Addition | `0.10` | `0.10` | `0.12` | `0.14` | `0.16` | `0.20` |
| 12 | DamageMultiplier | Addition | `0.12` | `0.12` | `0.144` | `0.168` | `0.192` | `0.24` |
| 15 | AttackSpeed | Addition | `0.20` | `0.20` | `0.24` | `0.28` | `0.32` | `0.40` |
| 16 | Projectiles | Flat | `1` | `1` | `1.2` | `1.4` | `1.6` | `2` |
| 17 | Lifesteal | Flat | `0.06` | `0.06` | `0.072` | `0.084` | `0.096` | `0.12` |
| 18 | CritChance | Flat | `0.05` | `0.05` | `0.06` | `0.07` | `0.08` | `0.10` |
| 19 | CritDamage | Addition | `0.10` | `0.10` | `0.12` | `0.14` | `0.16` | `0.20` |
| 23 | EliteDamageMultiplier | Addition | `0.10` | `0.10` | `0.12` | `0.14` | `0.16` | `0.20` |
| 24 | KnockbackMultiplier | Addition | `0.10` | `0.10` | `0.12` | `0.14` | `0.16` | `0.20` |
| 25 | MoveSpeedMultiplier | Addition | `0.08` | `0.08` | `0.096` | `0.112` | `0.128` | `0.16` |
| 26 | JumpHeight | Addition | `0.10` | `0.10` | `0.12` | `0.14` | `0.16` | `0.20` |
| 29 | PickupRange | Addition | `0.20` | `0.20` | `0.24` | `0.28` | `0.32` | `0.40` |
| 30 | Luck | Flat | `0.05` | `0.05` | `0.06` | `0.07` | `0.08` | `0.10` |
| 31 | GoldIncreaseMultiplier | Addition | `0.075` | `0.075` | `0.09` | `0.105` | `0.12` | `0.15` |
| 32 | XpIncreaseMultiplier | Addition | `0.075` | `0.075` | `0.09` | `0.105` | `0.12` | `0.15` |
| 38 | Difficulty | Addition | `0.08` | `0.08` | `0.096` | `0.112` | `0.128` | `0.16` |
| 39 | EliteSpawnIncrease | Addition | `0.15` | `0.15` | `0.18` | `0.21` | `0.24` | `0.30` |
| 40 | PowerupBoostMultiplier | Addition | `0.10` | `0.10` | `0.12` | `0.14` | `0.16` | `0.20` |
| 41 | PowerupChance | Addition | `0.05` | `0.05` | `0.06` | `0.07` | `0.08` | `0.10` |
| 46 | ExtraJumps | Flat | `1` | `1` | `1.2` | `1.4` | `1.6` | `2` |

The values are derived from the switch in `EncounterUtility.GetRandomStatValue` at RVA `0x436B10`.

## 5. Live Memory Validation

### 5.1. Historical Run With an Unidentified 1.075 Factor

The following six new permanent modifiers were observed while Chaos Tome remained at level `547`. They represent six selected shrine rewards, because each completed standard shrine applies only one selected offer.

| Stat | Stored value | Rarity | Beacon stacks | Reconstruction |
| :--- | ---: | :---: | ---: | :--- |
| MaxHealth | `32.25` | Legendary | 1 | `round3(15 * 2.0) * 1.075` |
| SizeMultiplier | `0.172` | Legendary | 1 | `round3(0.08 * 2.0) * 1.075` |
| Lifesteal | `0.1032` | Epic | 1 | `round3(0.06 * 1.6) * 1.075` |
| EliteDamageMultiplier | `0.215` | Legendary | 1 | `round3(0.10 * 2.0) * 1.075` |
| PowerupBoostMultiplier | `0.172` | Epic | 1 | `round3(0.10 * 1.6) * 1.075` |
| PowerupChance | `0.1075` | Legendary | 1 | `round3(0.05 * 2.0) * 1.075` |

All six share an additional `1.075` factor. The later clean Beacon control proves that Beacon alone does not explain it.

### 5.2. Same Historical Run at Beacon x3

The inventory stack field changed from `Beacon x1` to `Beacon x3`. Two subsequent selected rewards were read from `permanentChanges`:

| Selected stat | Rarity | Stored modifier | x1 prediction | x3 stack prediction |
| :--- | :---: | ---: | ---: | ---: |
| HealthRegen | Legendary | `43.0` | `40 * 1.075 = 43.0` | `40 * 1.225 = 49.0` |
| DamageMultiplier | Epic | `0.2064` | `0.192 * 1.075 = 0.2064` | `0.192 * 1.225 = 0.2352` |

Both values retain the unidentified `1.075` factor and reject a stack-scaled `1.225` multiplier. This remains evidence about that run, not evidence that Beacon caused the factor.

The unselected offers also validate several bases:

| Offer | UI value | Reconstruction |
| :--- | ---: | :--- |
| Legendary JumpHeight | `21.5%` | `0.10 * 2.0 * 1.075 = 0.215` |
| Epic Knockback | `17.2%` | `0.10 * 1.6 * 1.075 = 0.172` |
| Legendary HealthRegen | `43` | `20 * 2.0 * 1.075 = 43` |
| Legendary Gold Gain | `16.1%` | `0.075 * 2.0 * 1.075 = 0.16125` |
| Epic Evasion | `8.6%` | `0.05 * 1.6 * 1.075 = 0.086` |
| Epic Damage | `20.6%` | `0.12 * 1.6 * 1.075 = 0.2064` |

### 5.3. Zero-Beacon Control at 15% Luck

Three shrine offer screens were captured in a new run with no Beacon and 15% Luck. All nine offers used the nominal multiplier `1.0`:

| Shrine | Rarity | Stat | UI value | Reconstruction |
| ---: | :---: | :--- | ---: | :--- |
| 1 | Common | XP Gain | `7.5%` | `0.075 * 1.0` |
| 1 | Common | Knockback | `10%` | `0.10 * 1.0` |
| 1 | Common | Powerup Multiplier | `10%` | `0.10 * 1.0` |
| 2 | Rare | Elite Spawn Increase | `21%` | `0.15 * 1.4` |
| 2 | Common | Projectile Count | `+1` | `1.0 * 1.0` |
| 2 | Common | Crit Damage | `10%` | `0.10 * 1.0` |
| 3 | Common | Pickup Range | `20%` | `0.20 * 1.0` |
| 3 | Common | HP Regen | `+20` | `20 * 1.0` |
| 3 | Common | Crit Damage | `10%` | `0.10 * 1.0` |

This control confirms nominal `1.0` values without Beacon. It also corrects the Pickup Range base from `0.075` to `0.20`.

### 5.4. Zero-Beacon Control at 1007% Luck

Three unique shrine screens were captured without Beacon at approximately 1007% Luck.

| Shrine | Rarity | Stat | UI value | Reconstruction |
| ---: | :---: | :--- | ---: | :--- |
| 1 | Rare | Luck | `7%` | `0.05 * 1.4` |
| 1 | Legendary | JumpHeight | `20%` | `0.10 * 2.0` |
| 1 | Legendary | SizeMultiplier | `16%` | `0.08 * 2.0` |
| 2 | Legendary | CritChance | `10%` | `0.05 * 2.0` |
| 2 | Epic | KnockbackMultiplier | `16%` | `0.10 * 1.6` |
| 2 | Uncommon | Difficulty | `9.6%` | `0.08 * 1.2` |
| 3 | Common | XP Gain | `7.5%` | `0.075 * 1.0` |
| 3 | Uncommon | Powerup Multiplier | `12%` | `0.10 * 1.2` |
| 3 | Rare | Powerup Drop Chance | `7%` | `0.05 * 1.4` |

This series confirms that high Luck substantially shifts the observed offers toward higher rarity while still allowing lower tiers. It also corrects the shrine bases for Luck and Crit Chance to `0.05`.

### 5.5. Clean Beacon x1 Batch at 15% Luck

A new run was tested with `Beacon x1`, 15% Luck, no Chaos Tome, and all 15 shrines applied together. Excluding three unrelated `Stat 49` entries, exactly 15 shrine modifiers were present:

```text
Thorns +6
Armor +6%
Size +8%
Projectile Speed +10%
Projectile Count +1
Crit Damage +10%, +12%
Elite Damage +12%
Knockback +10%
Pickup Range +20%
XP Gain +7.5%, +7.5%
Difficulty +8%, +8%
Extra Jumps +1.4
```

Every value is a nominal rarity fingerprint with multiplier `1.0`. This directly disproves Beacon as the cause of the earlier `1.075` samples.

Distribution: 10 Common, 4 Uncommon, 1 Rare.

## 6. Runtime Fingerprint Generation

Fingerprints should currently be generated without Beacon scaling:

```python
RARITY_MULTIPLIERS = (1.0, 1.2, 1.4, 1.6, 2.0)


def round3(value: float) -> float:
    return round(value, 3)


def shrine_fingerprints(base: float) -> tuple[float, ...]:
    return tuple(
        round3(base * rarity)
        for rarity in RARITY_MULTIPLIERS
    )
```

Float32 memory reads require an epsilon. Start with `0.0005` for a single modifier and increase proportionally when identical modifiers are stacked into one value.

## 7. Candidate Tracking Budget

Static analysis identifies a possible completed-shrine counter on `AchievementTracker`:

- TypeInfo RVA: `0x02F66AE8`.
- Static field: `chargedShrines`.
- Static-fields offset: `0x58`.
- Expected to reset to zero when a new run starts.
- Expected to increment when a Charge Shrine is completed.

The documented TypeInfo RVA did not resolve as a valid IL2CPP class pointer in the tested build, so this path is not runtime-confirmed and must not be used for production tracking yet. If the address and behavior are revalidated, the counter could provide the reward budget as follows:

1. Snapshot permanent modifiers and `chargedShrines`.
2. When the counter increases by `N`, open `N` pending shrine rewards.
3. Diff `StatInventory.permanentChanges` until the selected modifiers arrive.
4. Generate nominal rarity fingerprints. Do not apply Beacon scaling unless future reverse engineering explains and reproduces it in a clean control.
5. Consume at most one matched modifier per pending shrine reward.
6. Keep shrine totals separate from Chaos Tome and other permanent changes.

The increment timing is also unconfirmed. If the counter increments before the player selects an offer, pending budgets must survive delayed modifier writes.

## 8. Confirmed Addresses

| Symbol | RVA / offset |
| :--- | :--- |
| `ItemBeacon.GetRewardMultiplier()` | `0x462D90` |
| `EncounterUtility.GetRandomStatOffers()` | `0x436720` |
| Three-decimal rounding helper | `0x436390` |
| `EncounterData.GetOffers()` | `0x3DED80` |
| `Rarity.GetEncounterOfferRarity(luck)` | `0x42D2C0` |
| `EncounterUtility.GetRandomStatValue()` | `0x436B10` |
| `AchievementTracker` TypeInfo | `0x02F66AE8` |
| `AchievementTracker.chargedShrines` | static fields `+0x58` |
