# Weapon Tracker Caps Registry

Verification date: **2026-09-02**. Status: **implementation reference;
Weapon Tracker code has not been changed**.

This document records the recommended `Projectile Count` and `Duration` caps for
every weapon present in the current game assets. The value in the `Projectile cap`
column is the last fully efficient Projectile Count. The next integer either enters
diminishing returns or is completely discarded by a hard cap.

## Summary

- Standard burst weapons use a **dynamic soft cap** that depends on global Attack
  Speed.
- `Axe` and `Bow` have a **hard cap of 80** per attack launch.
- `Chunkers` has a **hard cap of 49**.
- `Shotgun` has a special **soft cap of 18**: `P = 18` produces 20 pellets. Further
  Projectile Count no longer adds pellets, but it continues to increase the damage
  branch, so this is not a hard cap on the entire stat.
- No gameplay cap has been confirmed for `Aegis`. Its limit of 30 applies only to
  the renderer; the actual shield count continues to use the full Projectile Count.
- `Duration` uses a direct hard clamp from `WeaponData.maxDuration`. If
  `maxDuration = -1`, there is no confirmed cap.

## Terms and formulas

Definitions:

- `P = TZ(max(1, W[16] + G[16]))` is the effective Projectile Count that Weapon
  Tracker should display;
- `ASg = G[15]` is the global Attack Speed multiplier; its default value is `1.0`;
- `W[10]` is the weapon-side Duration after weapon upgrades;
- `G[10]` is the global Duration multiplier;
- `TZ` means truncation toward zero; for a positive Projectile Count, it is
  equivalent to `floor`.

For standard weapons with `burstTime > 0`:

```text
projectileSoftCap(ASg) = max(
    1,
    floor(burstTime / max(minBurstInterval, 0.02 * ASg))
)
```

Up to this value, the entire burst fits within the same time budget. Starting with
the next Projectile Count, the interval reaches either `minBurstInterval` or Unity's
`fixedDeltaTime = 0.02 s`; the attack cycle becomes longer, so every additional
projectile provides a smaller efficiency gain. The outer `max(1, ...)` is required
for the UI at very high `ASg`, because the effective Projectile Count cannot be less
than 1.

For Duration:

```text
rawDuration       = W[10] * G[10]
effectiveDuration = min(rawDuration, maxDuration)  # only when maxDuration > 0
```

The `Projectile cap @ ASg=1` column below is a convenient static UI reference. For
an accurate in-run indicator, recalculate the dynamic cap from the current `ASg`.

## Complete Projectile Count registry

| ID | Weapon | Base P | Projectile cap @ `ASg=1` | Type | Parameters / rule | Shown in Tracker |
|---:|---|---:|---:|---|---|---|
| 0 | Fire Staff | 1 | **6** | dynamic soft | `burst=1.0`, `min=0.15`; unchanged through `ASg=7.5` | yes |
| 1 | Bone | 1 | **10** | dynamic soft | `burst=1.0`, `min=0.10`; unchanged through `ASg=5` | yes |
| 2 | Sword | 1 | **5** | dynamic soft | `burst=0.5`, `min=0.10`; unchanged through `ASg=5` | yes |
| 3 | Revolver | 6 | **55** | dynamic soft | `burst=1.1`, `min=0.02`; decreases above `ASg=1` | yes |
| 4 | Aura | 0 | — | N/A | Projectile Count is unavailable | no |
| 5 | Axe | 2 | **80** | hard | zero-burst `WeaponAttack` spawn limit | yes |
| 6 | Bow | 1 | **80** | hard | zero-burst `WeaponAttack` spawn limit | yes |
| 7 | Aegis | 2 | **no confirmed cap** | none | `P` sets the maximum shield count; the renderer displays at most 30 | yes |
| 8 | Test | — | — | unsupported | the enum exists, but current `WeaponData`/`UpgradeData` assets do not | no |
| 9 | Lightning Staff | 1 | **7** | dynamic soft | `burst=0.3`, `min=0.04`; unchanged through `ASg=2` | yes |
| 10 | Flamewalker | 1 | **10** | dynamic soft | `burst=1.0`, `min=0.10`; unchanged through `ASg=5` | yes |
| 11 | Rockets | 1 | **10** | dynamic soft | `burst=1.0`, `min=0.10`; unchanged through `ASg=5` | yes |
| 12 | Bananarang | 1 | **9** | dynamic soft | `burst=0.9`, `min=0.10`; unchanged through `ASg=5` | yes |
| 13 | Tornado | 1 | **10** | dynamic soft | `burst=1.0`, `min=0.10`; unchanged through `ASg=5` | yes |
| 14 | Dexecutioner | 1 | **20** | dynamic soft | `burst=0.8`, `min=0.04`; unchanged through `ASg=2` | yes |
| 15 | Sniper | 1 | **3** | dynamic soft | `burst=1.0`, `min=0.30`; unchanged through `ASg=15` | yes |
| 16 | Frostwalker | 0 | — | N/A | Projectile Count is unavailable | no |
| 17 | Space Noodle | 0 | — | N/A | Projectile Count is unavailable | no |
| 18 | Dragon's Breath | 0 | — | N/A | Projectile Count is unavailable | no |
| 19 | Chunkers | 3 | **49** | hard | `RotatingProjectiles.SetAmount` changes every input `P >= 50` to 49 | yes |
| 20 | Mine | 1 | **4** | dynamic soft | `burst=1.0`, `min=0.25`; unchanged through `ASg=12.5` | yes |
| 21 | Poison Flask | 1 | **5** | dynamic soft | `burst=1.0`, `min=0.20`; unchanged through `ASg=10` | yes |
| 22 | Black Hole | 1 | **3** | dynamic soft | `burst=1.5`, `min=0.50`; unchanged through `ASg=25` | yes |
| 23 | Katana | 1 | **25** | dynamic soft | `burst=0.5`, `min=0.02`; decreases above `ASg=1` | yes |
| 24 | Blood Magic | 1 | **1** | dynamic soft | `burst=0.02`, `min=0.02`; every `P > 1` is already in diminishing returns | yes |
| 25 | Bluetooth Dagger | 1 | **55** | dynamic soft | `burst=1.1`, `min=0.02`; decreases above `ASg=1` | yes |
| 26 | Dice | 1 | **6** | dynamic soft | `burst=1.0`, `min=0.15`; unchanged through `ASg=7.5` | yes |
| 27 | Hero Sword | 1 | **5** | dynamic soft | `burst=0.75`, `min=0.15`; unchanged through `ASg=7.5` | yes |
| 28 | Corrupt Sword | 1 | **5** | dynamic soft | `burst=0.8`, `min=0.14`; unchanged through `ASg=7` | yes |
| 29 | Shotgun | 1 | **18** | special soft | pellets = `clamp(P + 2, 1, 20)`; damage, but not pellet count, continues to scale above 18 | yes |
| 30 | Scythe | 1 | **15** | dynamic soft | `burst=1.5`, `min=0.10`; unchanged through `ASg=5` | yes |

### Dynamic recalculation examples

For weapons with `minBurstInterval = 0.02`, the cap starts decreasing immediately
above `ASg = 1`:

| Weapon | `ASg=1.0` | `ASg=1.5` | `ASg=2.0` | `ASg=3.0` |
|---|---:|---:|---:|---:|
| Katana | 25 | 16 | 12 | 8 |
| Revolver | 55 | 36 | 27 | 18 |
| Bluetooth Dagger | 55 | 36 | 27 | 18 |

For example, Katana's `P=25` is fully efficient at `ASg=1`. At `ASg=2`, `P=12`
is already the last fully efficient value, while `P=13+` makes the burst longer.

## Complete Duration registry

`Tracker = no` means that stat ID `10` is absent from the weapon's
`upgrade_stat_ids`. The gameplay clamp remains real and can still affect global
Duration bonuses, but Weapon Tracker should not add a hidden row without an explicit
product decision.

| ID | Weapon | Base Duration | Duration cap | Type | Shown in Tracker |
|---:|---|---:|---:|---|---|
| 0 | Fire Staff | 2.0 s | **5.0 s** | hard | no |
| 1 | Bone | 3.0 s | **10.0 s** | hard | no |
| 2 | Sword | 0.5 s | **0.5 s** | hard; already reached at base | no |
| 3 | Revolver | 1.0 s | **5.0 s** | hard | no |
| 4 | Aura | 0 s | none | none | no |
| 5 | Axe | 0.82 s | **8.0 s** | hard | **yes** |
| 6 | Bow | 0.5 s | **1.0 s** | hard | no |
| 7 | Aegis | 0 s | none | none | no |
| 8 | Test | — | — | unsupported | no |
| 9 | Lightning Staff | 1.0 s | **1.0 s** | hard; already reached at base | no |
| 10 | Flamewalker | 1.5 s | **8.0 s** | hard | **yes** |
| 11 | Rockets | 5.0 s | **5.0 s** | hard; already reached at base | no |
| 12 | Bananarang | 3.0 s | **10.0 s** | hard | no |
| 13 | Tornado | 1.2 s | **5.0 s** | hard | no |
| 14 | Dexecutioner | 0.5 s | **0.5 s** | hard; already reached at base | no |
| 15 | Sniper | 1.0 s | **1.0 s** | hard; already reached at base | no |
| 16 | Frostwalker | 1.6 s | none | none | **yes** |
| 17 | Space Noodle | 4.0 s | none | none | **yes** |
| 18 | Dragon's Breath | 1.5 s | none | none | **yes** |
| 19 | Chunkers | 3.0 s | none | none | no |
| 20 | Mine | 4.0 s | none | none | **yes** |
| 21 | Poison Flask | 3.0 s | **5.0 s** | hard | **yes** |
| 22 | Black Hole | 2.0 s | **7.0 s** | hard | **yes** |
| 23 | Katana | 0.5 s | **0.5 s** | hard; already reached at base | no |
| 24 | Blood Magic | 0.75 s | **0.75 s** | hard; already reached at base | no |
| 25 | Bluetooth Dagger | 2.5 s | **8.0 s** | hard | no |
| 26 | Dice | 2.0 s | **5.0 s** | hard | no |
| 27 | Hero Sword | 0.5 s | **5.0 s** | hard | no |
| 28 | Corrupt Sword | 0.5 s | **5.0 s** | hard | no |
| 29 | Shotgun | 0.8 s | **0.8 s** | hard; already reached at base | no |
| 30 | Scythe | 0.5 s | **0.5 s** | hard; already reached at base | no |

## Recommended implementation data model

A single number is not sufficient for Projectile Count. The minimum safe format is:

```text
kind: dynamic_soft | hard | special_soft | none | unavailable
cap_at_default_attack_speed: int | null
burst_time: float | null
min_burst_interval: float | null
note: str | null
```

Display rules:

1. `dynamic_soft`: calculate the cap from the current `ASg`; do not store only the
   static value.
2. `hard`: values above the cap provide no additional projectile effect.
3. `special_soft`: use a weapon-specific formula; currently this is `Shotgun`.
4. `none`: the row exists, but no cap has been confirmed; do not display a false
   green cap.
5. `unavailable`: the stat ID is absent from `upgrade_stat_ids`; hide the row.
6. Consider a cap reached when `effective_value >= cap`. For a dynamic soft cap,
   recalculate the cap from the current `ASg` first.

For Duration, `maxDuration` is sufficient, but only when it is strictly greater than
zero. A value of `-1` means that no clamp is present.

## Special cases

### Axe and Bow

Both have `burstTime = 0`, so the cadence soft cap does not apply. The standard
`WeaponAttack` stores `maxNumProjectilesWithoutInterval = 80`, and its zero-interval
branch stops the spawn loop at 80. This is an exact hard cap, not an estimate.

### Chunkers

`Chunkers` does not use the standard burst spawner. `RotatingProjectiles.SetAmount`
preserves values up to and including 49, but writes 49 for every input value `>= 50`.
The player-facing Projectile Count cap is therefore **49**, despite the internal
constant being named `maxQuantity = 50`.

### Aegis

`AegisAttack.GetMaxShields` returns the full attack quantity, and the gameplay logic
increases `currentAmount` until it reaches that value. `AegisRenderer` separately caps
the number of visual objects at 30. This is a rendering optimization, not a gameplay
cap; Weapon Tracker must not use 30 as the Projectile Count cap.

### Shotgun

Shotgun has several distinct quantities:

```text
displayed Projectile Count = P
attack quantity             = 2
physical/visual pellets     = clamp(P + 2, 1, 20)
raw damage term             = P - 1
```

`P = 18` saturates the pellet count at 20. Projectile Count still participates in
the damage branch above this value, so **18 is a pellet soft cap**, not a complete
hard cap on the stat.

### Pool size 250

`WeaponUtility.GetMaxProjectilesPoolSize` returns 250, but this is a shared runtime
pool limit that depends on the number of simultaneously active objects. It is not a
static Projectile Count cap for an individual weapon and must not be shown as a
weapon-specific cap.

## Verification and sources

- Base formulas and visibility rules: [Weapon Tracker stat formulas](../recovery/reports/2026-09-01-weapon-tracker-stat-formulas.md).
- Current `GameAssembly.dll`:
  `SHA-256 4350A7AE25BA7AEC35677C213FDCEABBB638676BB00AB59131D7D9C37B6E3D9E`.
- All 30 sets of `projectiles`, `projectileBounces`, `attackDuration`, `maxDuration`,
  `maxSizeMultiplier`, `effectDuration`, `projectileSpeed`, `endCooldown`, `burstTime`,
  and `minBurstInterval` were matched byte-for-byte against the corresponding
  `WeaponData` objects in the current `sharedassets1.assets`.
- Key current RVAs: `GetAttackQuantity 0x4346F0`, `GetBurstInterval 0x434840`,
  `GetDuration 0x435630`, `GetWeaponCooldown 0x435A20`,
  `WeaponAttack.FixedUpdate 0x450150`, `WeaponAttack..ctor 0x4515D0`,
  `RotatingProjectiles.SetAmount 0x35F060`, and
  `AegisAttack.GetMaxShields 0x4A4590`.
- The `lukeod/megabonk_research` repository was used as a convenient initial index,
  but the final values above rely on the current local assets and native code.

## What to recheck after a game update

1. The SHA-256 of `GameAssembly.dll`.
2. Every `WeaponData` object's `burstTime`, `minBurstInterval`, `maxDuration`, and
   base values.
3. The constants 80, 49, and 30, plus Shotgun's pellet clamp of 20, in native code.
4. The `upgrade_stat_ids` list, because it controls Tracker row visibility.
5. `Time.fixedDeltaTime`; the formula above assumes the current value of `0.02 s`.
