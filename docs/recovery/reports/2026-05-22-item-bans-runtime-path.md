## Goal

Document the live runtime path used to track current-run banishes in Megabonk,
including the separation between passive item bans and tome/upgradable bans.

## Current Result

Status: `[Done]`

Live banish tracking is now implemented and confirmed.

The confirmed runtime source is `RunUnlockables` static fields:

- `banishedItems: HashSet<ItemData>`
- `banishedUpgradables: HashSet<UnlockableBase>`

Those are rooted from:

```text
GameAssembly.dll + 0x02F7A210
-> RunUnlockables_TypeInfo
-> class_ptr
-> +0xB8 static fields
```

From there:

- `static_fields + 0x0` -> `banishedItems`
- `static_fields + 0x8` -> `banishedUpgradables`

Current user-facing behavior stores one merged ordered list:

- passive items from `banishedItems`
- tomes from `banishedUpgradables`

The merged display order is kept by appearance order in the app/recordings so
UI does not jitter based on raw `HashSet` slot order.

## Relevant Dump Findings

Sources:

- `F:\Python\CA_mpc_bridge\Dump\dump.cs`
- `F:\Python\CA_mpc_bridge\Dump\il2cpp.h`

Confirmed dump entries:

- `PlayerInventory` contains:
  - `banishes // 0x74`
  - `banishesUsed // 0x90`
- `ItemData` contains:
  - `inItemPool // 0x50`
  - `eItem // 0x54`
- `TomeData` contains:
  - `eTome // 0x50`
- `RunUnlockables` static fields contain:
  - `banishedItems // static HashSet<ItemData>`
  - `banishedUpgradables // static HashSet<UnlockableBase>`

`HashSet<T>` layout used by the implementation:

```text
+0x18 _slots
+0x20 _count
+0x24 _lastIndex
slots array:
  +0x20 first slot
  slot size = 0x10
  +0x0 hashCode
  +0x8 value pointer
```

Object decoding used:

- `ItemData +0x54` -> `EItem`
- `TomeData +0x50` -> `ETome`
- object `+0x0` -> `klass`
- `klass +0x10` -> ASCII class name

## Why This Path Is Correct

`ItemData.inItemPool` is part of the static catalog object layout. That can
mean:

- default catalog membership
- global availability flags
- non-run-specific setup state

By itself, that is not strong enough for a user-facing banish feature.

`banishedItems` and `banishedUpgradables` are better candidates because their
names imply a live exclusion set rather than baseline item metadata.

Live validation now confirms that those sets are the real current-run ban state.

## Live Validation

Observed on 2026-05-22:

Before banish in a fresh run:

- `banishedItems.count = 0`
- `banishedUpgradables.count = 0`

After banishing one passive item and one tome:

- `banishedItems.count = 1`
- `banishedUpgradables.count = 1`

Decoded contents:

- `banishedItems[0]`
  - class: `ItemData`
  - `eItem = 35`
  - resolved name: `Clover`
- `banishedUpgradables[0]`
  - class: `TomeData`
  - `eTome = 15`
  - resolved name: `Golden Tome`

This is strong confirmation that:

- passive item banishes are tracked in `banishedItems`
- tome banishes are tracked in `banishedUpgradables`
- the two categories are separated in runtime memory

## Implementation Shape

Implemented in:

- `src/player_stats.py`
- `src/vod_storage.py`
- `src/gui.py`

Current feature behavior:

- read both sets live
- decode passive item names using the existing item enum/name normalization
- decode tome names from `ETome`
- merge them into one `banishes` list for UI
- preserve order of appearance across snapshots
- store optional `banishes` in recordings

UI behavior:

- `Live Stats` summary shows compact `Banishes`
- `Recordings` summary shows the same field
- display is a wrapped inline string, not a vertical list
- current text shape example:
  - `Clover, Battery, Backpack, Golden Tome`

## Caveats

- `HashSet` raw slot order should not be treated as stable presentation order
- `banishedUpgradables` may later contain more than tomes if gameplay systems
  start banishing other upgradable unlockables
- the current UI intentionally merges passive items and tomes into one compact
  display because tome banishes are rare and the user preferred a single card
