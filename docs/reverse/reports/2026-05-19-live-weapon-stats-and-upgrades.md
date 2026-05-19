# Live Weapon Stats And Upgrade Stat Pool

Date: 2026-05-19

## Goal

Document the live memory path used to read the current run weapon inventory,
weapon levels, full effective weapon stat dictionaries, and the per-weapon
upgrade stat pool.

This report is implementation-oriented. It is intended to support future
`Live Stats` and recording features that show which weapons the player has,
their levels, and the stats that are actually upgraded by each weapon.

## Confirmed Live Root Path

The currently confirmed root path starts from the same stable player stats root
used by the live player stats tab:

```text
GameAssembly.dll + 0x02F6A4B8
-> class pointer
-> +0xB8 static fields
-> +0x0 root object
-> +0x40 PlayerStatsNew
-> +0x28 PlayerInventory
-> +0x28 WeaponInventory
-> +0x18 Dictionary<EWeapon, WeaponBase>
```

Important note:

- older inventory reports used `PlayerStatsNew +0xA0` for a related
  inventory/container path
- the dumped `PlayerStatsNew` layout identifies `playerInventory` at `+0x28`
- for live weapons, prefer `PlayerStatsNew +0x28 -> PlayerInventory`

## TypeInfo And Class Pointers

Build validated on 2026-05-19:

```text
GameAssembly.dll base: 0x7FFFA28B0000
GameAssembly.dll size: 57647104
```

Relevant type info offsets from `Dump/script.json`:

```text
PlayerInventory_TypeInfo:
  offset: 0x02F6D520
  module address: 0x7FFFA581D520
  class pointer observed: 0x22A223FD2A0

PlayerStatsNew_TypeInfo:
  offset: 0x02F6D9B8
  module address: 0x7FFFA581D9B8
  class pointer observed: 0x22A22511DB0

WeaponInventory_TypeInfo:
  offset: 0x02FA2870
  module address: 0x7FFFA5852870
  class pointer observed: 0x22A2259E5D0

WeaponBase_TypeInfo:
  offset: 0x02FA2730
  module address: 0x7FFFA5852730
  class pointer observed: 0x22A223FCC90
```

Implementation should resolve these dynamically from the current module base and
current type info object instead of hardcoding observed heap addresses.

## Field Layouts

`PlayerStatsNew`:

```text
+0x10 stats
+0x18 rawStats
+0x20 statValuesMap
+0x28 playerInventory
+0x30 queuedUpdateStats
```

`PlayerInventory`:

```text
+0x10 playerStats
+0x18 characterData
+0x20 itemInventory
+0x28 weaponInventory
+0x30 playerXp
+0x38 statusEffects
+0x40 playerHealth
+0x48 tomeInventory
+0x50 statInventory
+0x58 passiveAbility
+0x60 activeAbility
```

`WeaponInventory`:

```text
+0x10 isMaxed
+0x11 hasAimableWeapon
+0x18 weapons Dictionary<EWeapon, WeaponBase>
```

`WeaponBase`:

```text
+0x10 usedWeaponAtTime float
+0x18 weaponData
+0x20 level int
+0x28 weaponStats Dictionary<EStat, float>
+0x30 upgrades List<List<StatModifier>>
+0x38 passive
+0x40 enabled bool
```

`WeaponData`:

```text
+0x50 eWeapon
+0x68 baseStats Dictionary<EStat, float>
+0x70 damage
+0x74 knockback
+0x78 critChance
+0x80 projectiles
+0x84 projectileBounces
+0x88 attackDuration
+0x8C maxDuration
+0x90 maxSizeMultiplier
+0x98 projectileSpeed
+0xD8 upgradeData
```

`UpgradeData`:

```text
+0x18 upgradeModifiers List<StatModifier>
```

`StatModifier`:

```text
+0x10 stat EStat
+0x14 modifyType EStatModifyType
+0x18 modification float
```

`EStatModifyType`:

```text
0 Addition
1 Multiplication
2 Flat
```

## Dictionary Layouts

Generic dictionary object fields:

```text
+0x10 _buckets
+0x18 _entries
+0x20 _count int
+0x24 _freeList int
+0x28 _freeCount int
+0x2C _version int
+0x30 _comparer
+0x38 _keys
+0x40 _values
+0x48 _syncRoot
```

Array header:

```text
+0x18 max_length int
+0x20 first element
```

`Dictionary<EWeapon, WeaponBase>` entry layout observed:

```text
entry stride: 0x18
+0x00 hashCode int
+0x04 next int
+0x08 key EWeapon int
+0x10 value WeaponBase pointer
```

Only treat entries with `hashCode >= 0` and a non-null value pointer as active.

`Dictionary<EStat, float>` entry layout observed:

```text
entry stride: 0x10
+0x00 hashCode int
+0x04 next int
+0x08 key EStat int
+0x0C value float
```

## List Layouts

The upgrade stat pool uses `List<StatModifier>`.

Observed implementation-relevant fields:

```text
List<T> +0x10 _items array pointer
List<T> +0x18 _size int
```

The `_items` array stores object pointers:

```text
array +0x18 max_length int
array +0x20 first StatModifier pointer
array +0x28 second StatModifier pointer
...
```

Read `_size` entries, not the full array capacity.

## Weapon Stat Semantics

`WeaponBase.weaponStats` is the full current effective weapon stat dictionary.
It contains the complete stat set used by weapon calculations, including stats
that are not upgraded by that specific weapon's level-up pool.

For user-facing upgraded weapon details, do not show every key from
`weaponStats` by default.

Recommended display rule:

1. Read full current values from `WeaponBase.weaponStats`.
2. Read the per-weapon upgrade pool from
   `WeaponBase.weaponData.upgradeData.upgradeModifiers`.
3. Use the `StatModifier.stat` keys from `upgradeModifiers` as the whitelist.
4. Display only `weaponStats` values whose `EStat` is in that whitelist.
5. Optionally expose the full `weaponStats` dictionary in an advanced/debug
   view.

This avoids hardcoding `EWeapon -> stat list` in the app while still keeping the
UI focused on stats that actually increase through weapon upgrades.

## Live Validation

Live CE bridge validation on 2026-05-19:

```text
Process: Megabonk.exe
PID: 8252
GameAssembly.dll: 0x7FFFA28B0000
```

Confirmed current run state:

```text
PlayerStatsNew: 0x22C374BDCC0
PlayerInventory: 0x26D3CA01D20
WeaponInventory: 0x26D3C788DE0
weapons dict: 0x22C3743B000
weapons count: 2
```

The live run had `FireStaff` and `Bone`, which matched the user's in-game state.

Decoded weapons:

```text
FireStaff
  EWeapon: 0
  WeaponBase: 0x22C3BC38640
  level: 3
  WeaponData: 0x22C2146F400
  weaponStats dict: 0x22C374BD9C0

Bone
  EWeapon: 1
  WeaponBase: 0x22C3B6F8690
  level: 3
  WeaponData: 0x22C2146A000
  weaponStats dict: 0x26D3CCA2660
```

Decoded full current `weaponStats` values:

```text
FireStaff level 3
  AttackSpeed: 1.0
  DamageMultiplier: 10.0
  KnockbackMultiplier: 1.0
  Projectiles: 2.0
  ProjectileBounces: 0.0
  DurationMultiplier: 2.0
  ProjectileSpeedMultiplier: 0.6
  SizeMultiplier: 1.16
  CritChance: 0.0
  CritDamage: 0.0

Bone level 3
  AttackSpeed: 1.0
  DamageMultiplier: 11.0
  KnockbackMultiplier: 1.5
  Projectiles: 1.0
  ProjectileBounces: 1.0
  DurationMultiplier: 3.0
  ProjectileSpeedMultiplier: 0.35
  SizeMultiplier: 1.0
  CritChance: 0.34
  CritDamage: 0.0
```

Decoded `UpgradeData.upgradeModifiers` pools:

```text
FireStaff upgrade pool
  SizeMultiplier
  Projectiles
  DamageMultiplier
  ProjectileSpeedMultiplier

Bone upgrade pool
  CritDamage
  CritChance
  ProjectileBounces
  ProjectileSpeedMultiplier
  Projectiles
  DamageMultiplier
```

This confirms that the per-weapon upgrade stat whitelist can be recovered from
live game data rather than manually maintained.

## Relevant Enum Values

`EWeapon` values observed or needed for decoding:

```text
0 FireStaff
1 Bone
2 Sword
3 Revolver
4 Aura
5 Axe
6 Bow
7 Aegis
8 Test
9 LightningStaff
10 Flamewalker
11 Rockets
12 Bananarang
13 Tornado
14 Dexecutioner
15 Sniper
16 Frostwalker
17 SpaceNoodle
18 DragonsBreath
19 Chunkers
20 Mine
21 PoisonFlask
22 BlackHole
23 Katana
24 BloodMagic
25 BluetoothDagger
26 Dice
27 HeroSword
28 CorruptSword
29 Shotgun
30 Scythe
```

Common weapon `EStat` values:

```text
9 SizeMultiplier
10 DurationMultiplier
11 ProjectileSpeedMultiplier
12 DamageMultiplier
15 AttackSpeed
16 Projectiles
18 CritChance
19 CritDamage
24 KnockbackMultiplier
45 ProjectileBounces
```

## Stale Pointer Caveat

After exiting a run, Megabonk can leave old `PlayerInventory`,
`WeaponInventory`, and `WeaponBase` objects in memory. A raw heap scan can find
valid-looking stale weapons.

Do not identify current weapons by scanning for the first matching class
pointer. Prefer the live root path:

```text
GameAssembly.dll + 0x02F6A4B8
-> static fields
-> current root
-> PlayerStatsNew
-> PlayerInventory
-> WeaponInventory
```

Then validate:

- `PlayerStatsNew.klass` matches `PlayerStatsNew_TypeInfo` class pointer
- `PlayerInventory.klass` matches `PlayerInventory_TypeInfo` class pointer
- `WeaponInventory.klass` matches `WeaponInventory_TypeInfo` class pointer
- `weapons` dictionary has a sane count and active entries
- decoded weapons match visible/current run state during validation

## Recommended Implementation Shape

Add a small reader that returns a normalized structure:

```text
WeaponSnapshot
  e_weapon: int
  name: str
  level: int
  weapon_base_address: int
  weapon_data_address: int
  full_stats: dict[int, float]
  upgrade_stat_keys: list[int]
  upgraded_stats: dict[int, float]
```

For live display:

- show `name`
- show `level`
- show `upgraded_stats`
- optionally show `full_stats` behind an advanced/debug toggle

For recordings:

- add weapon snapshots to each player stats/VOD snapshot
- preserve backward compatibility for older recordings without weapon data
- store stat ids as ids plus optional names, so old files remain parseable if
  display names are changed later

## Open Questions

- Confirm whether `UpgradeData.GetUpgradeOffer(rarity, eWeapon)` can filter or
  transform the raw `upgradeModifiers` pool for special weapons.
- Confirm all weapons' `upgradeModifiers` pools across a broader run or static
  extraction pass.
- Decide whether recording should store:
  - full `weaponStats`
  - upgraded-only stats
  - or both
- Decide UI formatting for `EStatModifyType`, percent-style stats, and flat
  stats.

