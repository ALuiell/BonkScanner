# Charge Shrine Mechanics and Tracking Contract

Date: 2026-08-23

This document describes the current `GameAssembly.dll`/IL2CPP dump contract
used by BonkScanner. It distinguishes confirmed static/runtime facts from the
Luck hypothesis that still needs a controlled experiment.

## Gameplay contract

- A normal map spawns 15 Charge Shrines.
- Beacon adds two Charge Shrines to the next map. It does not increase reward
  magnitude.
- `chargedShrines` increases when charging completes, before the player chooses
  one of the three offers. The selected modifier is appended to `shownLog` only
  after that choice, so the pending selection has no timeout.
- Charging one shrine presents three stat offers; the player selects one, and
  that one choice becomes the permanent reward modifier.
- Wrench multiplies every reward by `1 + 0.075 * stack_count`.
- Luck may influence the rarity roll, but that relationship is not yet treated
  as confirmed and is not required by the tracker.

## Reward formula

For a stat base value `b`, rarity multiplier `r` and Wrench stack count `w`:

```text
rounded_rarity_value = round_float32(b * r, 3)
reward = float32(rounded_rarity_value * float32(1 + 0.075 * w))
```

Rarity multipliers are Common `1.0`, Uncommon `1.2`, Rare `1.4`, Epic `1.6`
and Legendary `2.0`.

## Rewardable stats

| Stat ID | Stat | Base | Modify type |
|---:|---|---:|---:|
| 0 | Max HP | 15 | Flat (2) |
| 1 | HP Regen | 20 | Flat (2) |
| 2 | Shield | 5 | Flat (2) |
| 3 | Thorns | 5 | Flat (2) |
| 4 | Armor | 0.05 | Flat (2) |
| 5 | Evasion | 0.05 | Flat (2) |
| 9 | Size | 0.08 | Addition (0) |
| 10 | Duration | 0.08 | Addition (0) |
| 11 | Projectile Speed | 0.10 | Addition (0) |
| 12 | Damage | 0.12 | Addition (0) |
| 15 | Attack Speed | 0.06 | Addition (0) |
| 16 | Projectile Count | 1 | Flat (2) |
| 17 | Lifesteal | 0.06 | Flat (2) |
| 18 | Crit Chance | 0.05 | Flat (2) |
| 19 | Crit Damage | 0.10 | Addition (0) |
| 23 | Damage to Elites | 0.10 | Addition (0) |
| 24 | Knockback | 0.10 | Addition (0) |
| 25 | Movement Speed | 0.08 | Addition (0) |
| 26 | Jump Height | 0.10 | Addition (0) |
| 29 | Pickup Range | 0.20 | Addition (0) |
| 30 | Luck | 0.05 | Flat (2) |
| 31 | Gold Gain | 0.075 | Addition (0) |
| 32 | XP Gain | 0.075 | Addition (0) |
| 38 | Difficulty | 0.08 | Flat (2) |
| 39 | Elite Spawn Increase | 0.15 | Addition (0) |
| 40 | Powerup Multiplier | 0.10 | Addition (0) |
| 41 | Powerup Drop Chance | 0.05 | Addition (0) |
| 46 | Extra Jumps | 1 | Flat (2) |

`EStatModifyType` is Addition `0`, Multiplication `1`, Flat `2`.

## Memory sources

All offsets are relative to the current `GameAssembly.dll` module base.

- `AchievementTracker` TypeInfo pointer: `0x02F69FE8`
  - static fields pointer: IL2CPP class `+0xB8`
  - `chargedShrines`: static fields `+0x58`
- `ShrineLogs` TypeInfo pointer: `0x02F81B18`
  - `shownLog`: static fields `+0x08`
- `StatModifier`
  - stat: `+0x10`
  - modify type: `+0x14`
  - value: `+0x18`

The charged counter resets in `AchievementTracker.OnRunStarted`. Spawn count,
map stage and Beacon state are deliberately not tracking dependencies: the
feature reports only bonuses that can be attributed to completed Charge
Shrines.

## Attribution and contamination rule

`ShrineLogs.shownLog` is a shared list, not a Charge Shrine-only log. Gritch,
Greed and other shrine effects may appear in it. Tracking therefore uses two
conditions together:

1. A rise of one in `chargedShrines` opens a budget of one selected reward entry.
2. Only a new `StatModifier` matching one of the 28 stat/modify-type/value
   fingerprints may consume that budget.

For example, Gritch Shrine writes Difficulty `0.05`; Charge Shrine Difficulty
starts at `0.08`. The Gritch entry is recorded as seen but cannot spend a
  Charge Shrine reward slot.

Object pointers deduplicate log entries. The memory reader samples `shownLog`
before `chargedShrines`: if a charge lands between those two reads, the new
counter opens a budget while the old log is safely consumed on the next tick.
The inverse ordering is also handled by leaving a fingerprint-compatible
no-budget entry unseen for one following sample. If the counter still has not
caught up, the entry is retired so old compatible effects from the shared log
cannot spend future Charge Shrine reward slots.

This one-sample grace applies only when there is no reward budget. A pending
budget created by `chargedShrines` does not expire while the player keeps the
offer window open. A fingerprint-compatible third-party effect appended during
that open pending window remains indistinguishable without reading the actual
offer objects.

The tracker reuses the once-per-second passive-item sample to obtain Wrench
stacks. Exact current-stack matching is attempted first. If the inventory and
reward writes cross the sampling boundary, the same exact formula may infer a
non-negative Wrench stack count from the stored raw float instead of leaving a
valid reward permanently pending.

## Remaining live validation

- Repeat with Wrench stack changes and retain exact raw float32 values as
  regression fixtures.
- Insert Gritch and Greed activations between Charge Shrine completions and
  verify the selected-reward budget remains intact.
- Compare low- and high-Luck batches before documenting Luck as a confirmed
  rarity input.
