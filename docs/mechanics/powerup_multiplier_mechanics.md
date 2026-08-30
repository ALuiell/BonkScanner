# Powerup Multiplier and Timed Powerups

Date: 2026-08-30

This document describes the current-build gameplay contract for the
`Powerup Multiplier` player stat and the timed powerups shown by BonkScanner.
The mechanic is already used by the Powerups card in Live Stats, recordings,
OBS/Twitch projections and the live powerup tracker.

## Core mechanic

`Powerup Multiplier` is `EStat.PowerupBoostMultiplier` (stat ID `40`). It is a
direct multiplier on the base duration of a timed powerup:

```text
granted_duration = base_duration * Powerup Multiplier
```

There is no secondary curve or cap in this duration calculation. For the four
timed effects currently displayed by BonkScanner:

| Powerup | `EStatusEffect` | Base duration | Duration formula |
|---|---:|---:|---|
| Rage | `1` | `15 s` | `15 * PM` |
| Shield | `2` | `15 s` | `15 * PM` |
| Stonks | `3` | `15 s` | `15 * PM` |
| Clock / Time Freeze | `4` | `12 s` | `12 * PM` |

For example, at `Powerup Multiplier = 2.0x`, Rage, Shield and Stonks last
`30 seconds`, while Clock lasts `24 seconds`.

Health, Nuke and Magnet pickups are immediate effects rather than timed status
effects, so this duration formula does not apply to them.

## Native confirmation

The current `GameAssembly.dll` confirms the same calculation:

- `PowerupConstants.GetMultiplier` at RVA `0x44A690` reads stat ID `40`.
- `PowerupConstants.GetFreezeTime` at RVA `0x44A630` multiplies that stat by
  the float constant `12.0`.
- `PowerupConstants.GetRageTime`, `GetShieldTime` and `GetStonksTime` share RVA
  `0x44A6E0` and multiply the stat by `15.0`.

The analyzed binary has SHA-256:

```text
4350A7AE25BA7AEC35677C213FDCEABBB638676BB00AB59131D7D9C37B6E3D9E
```

The values have also been repeatedly checked through the existing Powerups
widget and Live Stats behavior.

## Haste scope caveat

The game still declares `EStatusEffect.Haste = 0` and
`EPickup.Haste = 7`. Its separate native method
`PowerupConstants.GetHasteTime` at RVA `0x44A670` currently calculates:

```text
haste_duration = 20 * Powerup Multiplier
```

Haste is not part of BonkScanner's current `POWERUP_STATUS_EFFECT_NAMES` map
and is not displayed by the Powerups card. Therefore the verified scanner
contract should be stated as "Rage, Shield and Stonks use 15 seconds; Clock
uses 12 seconds", rather than applying the 15-second base blindly to every
timed enum value. If Haste becomes obtainable or is added to tracking, it needs
its own 20-second duration rule.

## Runtime and recording behavior

BonkScanner publishes both derived durations in `PowerupsSnapshot`:

```text
standard_duration_seconds = 15 * PM
clock_duration_seconds    = 12 * PM
```

The live tracker also reads each active status effect's `addedTime` and
`expirationTime`. When the pickup itself is observed, their difference is the
exact duration granted by the game and provides an independent runtime check.

An already-active effect must not be retrospectively retimed merely because a
later memory sample reports a different Powerup Multiplier. The expiration was
committed when the effect was granted. The tracker therefore preserves the
observed duration for the same effect instance unless the game moves its
expiration, such as after another pickup.

Recordings persist the Powerups snapshot, so replay and comparison use the
duration and active-effect state captured during the run rather than deriving
it from the current game process.

## Verifier implications

Powerup Multiplier is mechanically simple, but verifying its *origin* is a
separate problem:

1. Recalculate the final stat from `base`, `flat`, `addition` and
   `multiplication` components.
2. Reconcile those components with the legitimate modifier sources: Chaos
   Tome, Charge Shrines, Dice/Gamba, items, passives and any other active
   source used by `PlayerStatsNew.UpdateStat`.
3. When a timed pickup is observed, compare its granted duration with the
   multiplier captured at the pickup moment.

For the four currently tracked effects, a newly granted duration should obey:

```text
Rage/Shield/Stonks: expirationTime - addedTime = 15 * PM_at_pickup
Clock:              expirationTime - addedTime = 12 * PM_at_pickup
```

This duration check is useful corroborating evidence, but it cannot replace
source reconciliation: a run may contain no observed timed pickup, and repeat
pickups can extend an existing effect rather than create a clean new interval.

## Code references

- Stat and status-effect IDs: `src/core/stats/types.py`
- Runtime calculation and active-effect tracking:
  `src/core/tracker/powerups.py`
- Snapshot contract: `src/core/tracker/snapshots.py`
- Memory reader: `src/infra/memory/player_stats_client.py`
- Live Stats Powerups card: `src/ui/tabs/player_stats/live_stats.py`
- Recording/OBS formatting: `src/projections/formatting.py`
- Twitch formatting and command: `src/projections/twitch.py`,
  `src/twitch_bot.py`
- Focused UI tests: `src/tests/test_powerups_card.py`

## Revalidation checklist

After a game update:

1. Verify stat ID `40` and the timed `EStatusEffect` enum values.
2. Recheck `PowerupConstants.GetMultiplier`, `GetFreezeTime`,
   `GetRageTime`, `GetShieldTime`, `GetStonksTime` and `GetHasteTime`.
3. Confirm the base float constants and multiplication order.
4. Run the Powerups card and live tracker tests.
5. Observe at least one standard powerup and one Clock pickup in live memory,
   comparing `expirationTime - addedTime` with the captured multiplier.
