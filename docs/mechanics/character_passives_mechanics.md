# Character Passives and Dice (Dicehead/Gamba) Mechanics

Date: 2026-08-30

This document describes the current character-passive contract used by
BonkScanner: how the selected character and passive are identified, which
passives can be calculated, and how Dice's random `Gamba` bonuses are generated
and attributed. The offsets and enum values are current-build facts and must be
revalidated after a game update.

## Terminology

- **Dice** is the public name used by BonkScanner.
- **Dicehead** is the internal `ECharacter` name used by the game.
- **Gamba** is Dice's passive (`PassiveAbilityGamba`).
- **Character level** is the level shown for the current run.
- **Gamba `currentLevel`** is the passive's authoritative roll counter. It is
  used as the Dice roll budget and is not inferred from permanent stats.
- A **linear passive** grants a fixed amount of one stat per character level.
- A **permanent roll** is a random modifier written to
  `StatInventory.permanentChanges`.

## Current support scope

BonkScanner always tries to read the selected character, passive enum and
runtime class. It calculates bonuses only when the passive has a confirmed
runtime contract. Unsupported characters still report their identity instead
of being treated as an unknown game build.

The current catalog contains 21 character/passive pairs:

| Character | Passive | Tracking | Tracked rule |
|---|---|---|---|
| Fox | RNG Blessing | Complete | Luck `+0.015` per level |
| Calcium | Speed Demon | Identity only | No verified adapter |
| Sir Oofie | Reinforced | Complete | Armor `+0.01` per level |
| Cl4nk | Crit Happens | Complete | Crit Chance `+0.01` per level |
| Megachad | Flex | Identity only | No verified adapter |
| Ogre | Warrior | Complete | Damage `+0.015` per level |
| Robinette | Stonks | Identity only | No verified adapter |
| Athena | Lock In | Identity only | No verified adapter |
| Birdo | Float | Identity only | No verified adapter |
| Bush | Bullseye | Identity only | No verified adapter |
| Bandit | Flowstate | Complete | Attack Speed `+0.01` per level |
| Monke | Wall Climb | Complete | Max Health `+2` per level |
| Noelle | Enduring | Identity only | No verified adapter |
| Tony McZoom | Zap | Identity only | No verified adapter |
| Amog | Plague | Identity only | No verified adapter |
| Spaceman | Quantum | Complete | XP Gain `+0.01` per level |
| Ninja | Shadowstep | Identity only | No verified adapter |
| Vlad | Vampire | Complete | Lifesteal `+0.01` per level |
| Dice | Gamba | Complete or partial | One random permanent stat roll per passive level |
| Sir Chadwell | Curse | Complete | Difficulty `+0.01` per level |
| Roberto | Hoarder | Identity only | No verified adapter |

Ten passives currently have bonus tracking: nine confirmed linear rules and
Dice's Gamba adapter.

"Identity only" means that BonkScanner knows which character and passive are
active, but deliberately does not estimate the bonus. These passives depend on
mechanics that have not been proven safe to represent as `level * constant`.
They require a separate verified adapter before bonus tracking can be enabled.

## Common identity and memory path

The character-passive reader starts from the current player's `owner_stats`:

```text
owner_stats
  -> +0x28 PlayerInventory
      -> +0x18 CharacterData
          -> +0x50 character_id
          -> +0x88 PassiveData
              -> +0x28 passive_id
      -> +0x58 PassiveAbility runtime object
      -> +0x30 PlayerXP
          -> +0x14 character level
```

The reader also resolves the runtime object's IL2CPP class name. For every
known character, BonkScanner requires all three identifiers to agree:

1. character enum;
2. passive enum;
3. runtime class.

A mismatch fails closed with unavailable data. This prevents an old build
contract from silently calculating the wrong passive after a game update. A
future character enum that is not in the catalog is reported as `Unknown`
rather than being assigned to an existing character.

## Linear passives

For a confirmed linear passive, the expected bonus is:

```text
expected_bonus = float32(float32(character_level) * float32(per_level))
```

The runtime `perLevel` field is read from the passive object at `+0x18` and is
validated against the catalog constant. The passive-owned stat modifier is
read separately and must use the expected stat ID and Flat modify type.

BonkScanner publishes the runtime modifier value rather than only displaying
its own multiplication. The calculated value is used as validation: the
runtime value must be within two float32 ULPs of the expected result. This
handles normal float32 rounding without accepting a materially different
formula.

The game may briefly update the character level before it updates the passive
modifier. During that writer window, BonkScanner keeps the last valid effect
and reports `Updating` instead of publishing a temporary incorrect value.

## Dice/Gamba gameplay mechanic

Dice acts like a smaller, single-rarity version of the Chaos Tome:

1. `PassiveAbilityGamba.OnLevelup` processes every passive level that has not
   yet been applied.
2. For each level, `EncounterUtility.GetRandomStatOffers(1, false, false)`
   selects one stat from `upgradableStatsChaosAndGamble` and rolls its rarity.
3. The stat's base value is multiplied by that rarity and rounded to three
   decimal places.
4. A nonlinear level-dependent decay is applied.
5. The result is written as a permanent `StatModifier` through
   `StatInventory.ChangeStat(..., permanent=true, ...)`.
6. Gamba increments `currentLevel` after writing the modifier.

Therefore, `currentLevel` is the exact number of Dice rolls that should exist.
It is the tracker's source budget even if BonkScanner starts after the run has
already begun or several levels are gained between samples.

### Runtime fields

`PassiveAbilityGamba` exposes four fields used by the tracker:

| Offset | Field | Confirmed value or meaning |
|---:|---|---|
| `+0x18` | `upgradeMultiplier` | `0.75` |
| `+0x1C` | `minMultiplier` | `0.06` |
| `+0x20` | `maxMultiplier` | `1.0` |
| `+0x24` | `currentLevel` | Number of applied Gamba rolls |

BonkScanner validates all three constants before attributing any roll. A
changed constant is treated as a game-build mismatch rather than being ignored.

### Rarity multipliers

Dice uses one rarity result per roll:

| Rarity | Multiplier |
|---|---:|
| Common | `1.0` |
| Uncommon | `1.2` |
| Rare | `1.4` |
| Epic | `1.6` |
| Legendary | `2.0` |

The random offer follows the game's normal encounter-offer rarity path, which
uses the player's current Luck. Dice does not have Chaos Tome's second,
independent outer rarity roll.

### Exact roll formula

For zero-based Gamba roll index `n`, stat base value `b`, and rarity multiplier
`r`:

```text
inner(n) = round3(float32(b) * float32(r))

decay(n) = clamp(
    0.75 / (1 + (n / 50) ^ 1.5),
    0.06,
    1.0
)

value(n) = float32(round3(inner(n) * 1.0) * decay(n))
```

Production matching reproduces the intermediate float32 operations, not only
the mathematical real-number result. `round3` is the game's three-decimal
rarity rounding step.

The decay is **not linear**:

| Roll index `n` | Decay multiplier |
|---:|---:|
| `0` | `0.750000` |
| `1` | `0.747885` |
| `10` | `0.688425` |
| `25` | `0.554097` |
| `50` | `0.375000` |
| `100` | `0.195903` |
| `150` | `0.121043` |
| `200` | `0.083333` |
| `254` | `0.060242` |
| `255` and later | `0.060000` |

The first 255 rolls have level-specific values. Starting with roll index 255,
the minimum clamp is active, so every later level uses the same five rarity
fingerprints for a given stat.

For example, Damage has base value `0.12`:

| Roll index | Common Damage | Legendary Damage |
|---:|---:|---:|
| `0` | about `+9%` | about `+18%` |
| `50` | about `+4.5%` | about `+9%` |
| `100` | about `+2.35%` | about `+4.70%` |
| `255+` | about `+0.72%` | about `+1.44%` |

This is why later character levels grant smaller bonuses. The rarity is still
rolled, but the result is multiplied by a much smaller decay value.

### Random stat pool

Dice and Chaos Tome share the 27-stat
`EncounterUtility.upgradableStatsChaosAndGamble` pool:

| Stat ID | Stat | Base value | Modify type |
|---:|---|---:|---|
| 0 | Max Health | `15` | Flat |
| 1 | Health Regen | `20` | Flat |
| 2 | Shield | `5` | Flat |
| 3 | Thorns | `5` | Flat |
| 4 | Armor | `0.05` | Flat |
| 5 | Evasion | `0.05` | Flat |
| 9 | Size | `0.08` | Addition |
| 10 | Duration | `0.08` | Addition |
| 11 | Projectile Speed | `0.10` | Addition |
| 12 | Damage | `0.12` | Addition |
| 15 | Attack Speed | `0.06` | Addition |
| 16 | Projectile Count | `1` | Flat |
| 17 | Lifesteal | `0.06` | Flat |
| 18 | Crit Chance | `0.05` | Flat |
| 19 | Crit Damage | `0.10` | Addition |
| 23 | Damage to Elites | `0.10` | Addition |
| 24 | Knockback | `0.10` | Addition |
| 25 | Movement Speed | `0.08` | Addition |
| 29 | Pickup Range | `0.20` | Addition |
| 30 | Luck | `0.05` | Flat |
| 31 | Gold Gain | `0.075` | Addition |
| 32 | XP Gain | `0.075` | Addition |
| 38 | Difficulty | `0.08` | Flat |
| 39 | Elite Spawn Increase | `0.15` | Addition |
| 40 | Powerup Multiplier | `0.10` | Addition |
| 41 | Powerup Drop Chance | `0.05` | Addition |
| 46 | Extra Jumps | `1` | Flat |

Base values are stored in game units; the presentation layer applies each
stat's configured percentage, multiplier or flat-value format. The shared
Chaos pool and its base values are also documented in
[Chaos Tome mechanics](./chaos_tome_mechanics.md#3-base-stats--modify-types-table).

## Dice tracking and source attribution

Dice does not own a separate modifier collection. Its rolls are stored in the
shared permanent dictionary:

```text
PlayerInventory
  -> +0x50 StatInventory
      -> +0x10 Dictionary<int, List<StatModifier>> permanentChanges

StatModifier
  -> +0x10 stat ID
  -> +0x14 modify type
  -> +0x18 float value
```

The same dictionary also contains Chaos Tome, Charge Shrine, item and other
permanent effects. A numeric value by itself is therefore not proof that a
modifier belongs to Dice.

### Fingerprint generation

For every Dice stat, BonkScanner generates the exact float32 fingerprints for:

- all five rarity multipliers;
- roll indices `0` through `255`;
- the expected stat ID and modify type.

Index 255 represents the clamped fingerprint shared by every later roll. A
runtime value may differ by at most two float32 ULPs from a generated
fingerprint.

### Budget and pointer rules

Attribution combines several signals:

1. `currentLevel` provides the number of roll indices that must be resolved.
2. Stable `StatModifier` object pointers identify individual permanent objects
   and prevent the same object from being counted twice.
3. Charge Shrine pointers from `ShrineLogs.shownLog` are reserved first and
   cannot be claimed by Dice.
4. A candidate must belong to the shared Dice/Chaos pool and have the expected
   modify type.
5. When Dice and Chaos can both validly claim a new modifier in the same budget
   window, the pointer is kept contested instead of being assigned by polling
   order.

The reader samples permanent modifier objects before reading Gamba
`currentLevel`. This matches the game's write order: the modifier is written
first and the counter is incremented second. If a read lands inside that short
window, the object remains pending and can be resolved on the next sample.

### Ambiguous matching

For early rolls, one float value may match more than one nearby roll index due
to decay, rarity and float32 collisions. The tracker builds a bipartite graph
between unresolved roll indices and candidate object pointers, finds maximum
matchings, and accepts only pairs that are present in every maximum solution.
It does not guess between equally valid histories.

At the decay floor, exact ordering is no longer observable or useful because
all indices use the same fingerprints. The tracker assigns the aggregate set
only when it fits within the remaining roll budget. If there are more valid
candidates than available rolls, the result stays ambiguous.

## Late attach and recovery

Starting BonkScanner after the run has begun can still recover Dice data:

- `currentLevel` reveals how many historical rolls should exist;
- retained permanent modifier objects provide their stat, value and pointer;
- the fingerprint solver reconstructs every assignment that is uniquely
  supported by the retained state.

Recovery is best-effort because the permanent dictionary does not store the
source name or timestamp. Exact collisions with Chaos Tome or another
compatible source may be impossible to separate after the fact. In that case,
BonkScanner reports `Partial` and leaves the uncertain rolls unresolved.
Continuous tracking is more reliable because pointer chronology and source
budgets are observed as they change.

Large cold recovery runs in a background worker so opening the Twitch bot or a
recording does not block the Qt UI. The shared permanent-modifier reader caches
immutable snapshots and normally rereads only structurally changed stat lists.
Dice, Chaos and Shrine attribution runs on a one-second cadence; the cache
keeps that cadence inexpensive even when thousands of modifiers exist.

## Published snapshot and statuses

All passives use one generic `CharacterPassiveSnapshot` boundary. It contains:

- character/passive identity and runtime class;
- character level;
- status and coverage;
- zero or more stat effects;
- unresolved/ambiguous and pending counts.

Dice effects additionally contain the accumulated bonus and tracked roll count
for each stat. Individual roll history and rarity are not exposed in the
published snapshot.

| Status | Meaning |
|---|---|
| `Supported` | The known passive was fully resolved. |
| `Updating` | A runtime write or background recovery is still settling. |
| `Partial` | Some Dice rolls cannot be attributed without guessing. |
| `Unsupported` | Identity is known, but no bonus adapter exists. |
| `Unavailable` | Required runtime data failed validation. |
| `Unknown` | The character is absent from the current-build catalog. |

The snapshot is used by Live Stats, Recordings and Compare Runs. Recording
frames persist the character-passive snapshot, so replay uses the data captured
at that point rather than rereading the game. Twitch command `!dice` reports
Dice totals and explicitly reports partial or unavailable tracking states.

### Why Dice has no roll-quality color

Chaos Tome and Charge Shrine cards can compare rolls against a stable range.
Dice values shrink with the roll index, so an unadjusted average would mostly
measure whether the rolls happened early or late rather than how lucky they
were. The published Dice snapshot also stores only accumulated totals and roll
counts, not the level and rarity of every individual roll. An accurate quality
score would require extending tracking and persistence with per-roll history.
BonkScanner therefore displays Dice totals and counts without a quality color.

## Validation evidence

The current contract was recovered from the IL2CPP dump and
`GameAssembly.dll`, then verified against read-only live memory. A stress run on
2026-08-23 advanced Dice from level `81` to `4108` while Chaos Tome advanced
from `0` to `531`. Cached and independent full permanent-modifier reads had no
persistent mismatches, and both recovery paths produced complete Dice
`4108/4108` and Chaos `531/531` snapshots with zero ambiguous rolls.

## Revalidation checklist

After a game update:

1. Verify character and passive enum mappings and runtime class names.
2. Verify the common identity offsets and each supported linear `perLevel`
   constant.
3. Verify Gamba fields at `+0x18`, `+0x1C`, `+0x20` and `+0x24`.
4. Recheck `PassiveAbilityGamba.OnLevelup`, the stat pool, rarity path, rounding
   order and decay formula.
5. Rebuild fingerprints and run focused linear/Gamba attribution tests.
6. Run a live mixed Dice + Chaos Tome + Charge Shrine stress test and compare
   cached reads with independent full reads.

## Code and related documentation

- Catalog and snapshot types: `src/core/character_passives.py`
- Passive adapters and Dice solver: `src/core/tracker/passives.py`
- Runtime memory reader: `src/infra/memory/player_stats_client.py`
- Shared source orchestration: `src/core/tracker/live_run.py`
- Refresh/recovery scheduling: `src/app/refresh_tasks.py`
- VOD persistence: `src/infra/vod_storage.py`
- Live/recording cards: `src/ui/tabs/player_stats/stat_cards.py`
- [Chaos Tome mechanics](./chaos_tome_mechanics.md)
- [Charge Shrine mechanics](./charge_shrines_mechanics.md)
- [Chaos Tome recovery guide](../recovery/parts/07_chaos_tome_tracking.md)
