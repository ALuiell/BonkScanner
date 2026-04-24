# Current Interactable Hook Reverse Reference

Date: 2026-04-24

This is the implementation-facing reverse reference for interactable hook
development. It keeps the confirmed offsets, register facts, pointer paths, and
stat rules in one place.

## Source And Address Semantics

Only offsets applied as `GameAssembly.dll + offset` are module-relative.
Dictionary offsets, field offsets, array offsets, entry offsets, container
offsets, and Mono/IL2CPP string offsets are relative to the pointer read at the
previous step.

Do not hardcode absolute addresses or live heap pointers. Examples such as
`0x13A99D257C0` are current-run heap values, not stable addresses.

## Core Module-Relative Offsets

| Target | Offset |
| --- | ---: |
| `RandomObjectPlacer.GenerateInteractables(MapData)` | `0x49C020` |
| `RandomObjectPlacer.Generate(RandomMapObject[] objects, float amountMultiplier)` | `0x49C1D0` |
| `RandomObjectPlacer.RandomObjectSpawner(RandomMapObject randomObject, float amountMultiplier = 1)` | `0x49C2A0` |
| `RandomObjectSpawner` instantiate return | `0x49CA28` |
| `SpawnInteractables.SpawnChests` | `0x49CF60` |
| `SpawnChests` instantiate return | `0x49D3DA` |
| `SpawnInteractables.SpawnOther` | `0x49D4F0` |
| real `SpawnOther` instantiate return | `0x49D7F6` |
| `SpawnInteractables.SpawnRails` | `0x49D840` |
| `SpawnRails` instantiate return | `0x49DBE5` |
| `SpawnInteractables.SpawnShrines` | `0x49E180` |
| `SpawnShrines` instantiate return | `0x49E70C` |
| `BaseInteractable.Start` | `0x4BFE00` |
| late debug/category callsite | `0x4C0032` |
| `InteractablesStatus.OnInteractableSpawn(string debugName)` | `0x51B030` |
| `InteractableMicrowave.Start` | `0x4CC6A0` |
| `InteractableMicrowave.GetDebugName` | `0x4CBEC0` |
| `InteractableShrineBalance.GetDebugName` | `0x4CDCC0` |
| `InteractableShrineBalance.ShowInDebug` | `0x383DB0` |
| `UnityEngine.Object.Instantiate<object>` wrapper | `0x758AF0` |
| `UnityEngine.Object.Internal_InstantiateSingle(...)` | `0x22B31A0` |
| `UnityEngine.GameObject.get_transform` | `0x22AC8B0` |
| `UnityEngine.Component.get_gameObject` | `0x22A7010` |
| `MapController_TypeInfo` | `0x2F58E08` |

## Data Structure Offsets

`RandomObjectPlacer` fields:

| Field | Offset |
| --- | ---: |
| `center` | `0x20` |
| `size` | `0x2C` |
| `numChargeShrines` | `0x38` |
| `randomObjects` | `0x40` |
| `chargeShrineSpawns` | `0x48` |
| `greedShrineSpawns` | `0x50` |
| `index` | `0x58` |

`RandomMapObject` fields:

| Field | Offset |
| --- | ---: |
| `amount` | `0x10` |
| `maxAmount` | `0x14` |
| `checkRadius` | `0x18` |
| `scaleMin` | `0x1C` |
| `scaleMax` | `0x20` |
| `maxSlopeAngle` | `0x24` |
| `upOffset` | `0x28` |
| `prefabs` | `0x30` |
| `randomRotationVector` | `0x38` |
| `alignWithNormal` | `0x44` |

Current-map shrine selector table:

```text
GameAssembly.dll + 0x2F58E08
  -> +0xB8 class static fields
  -> +0x10 MapController.currentMap
  -> +0x88 MapData.shrines
  -> +0x18 IL2CPP array length
  -> +0x20 + index * 8 IL2CPP array elements
```

The confirmed logical index mapping for the current target stat set is:

| `MapData.shrines` index | Category |
| ---: | --- |
| `0` | `Challenges` |
| `1` | `Magnet Shrines` |
| `2` | `Moais` |
| `3` | `Shady Guy` |
| `4` | `Boss Curses` |

## Confirmed Runtime/Register Facts

At `RandomObjectPlacer.RandomObjectSpawner` entry
(`GameAssembly.dll + 0x49C2A0`):

- `RCX` = `RandomObjectPlacer*`
- `RDX` = `RandomMapObject*`
- `XMM2` = amount multiplier

At `RandomObjectSpawner` instantiate return
(`GameAssembly.dll + 0x49CA28`):

- `RAX` = instantiated `GameObject*`
- active spawner context identifies the bucket/prefab source

At `SpawnShrines` instantiate return (`GameAssembly.dll + 0x49E70C`):

- before `mov rbx, rax`, `RBX` = selected shrine prefab / selector
- `RAX` = instantiated `GameObject*`
- `RBX` should be classified against the current-run
  `MapData.shrines` table, not against hardcoded heap pointers

At `BaseInteractable.Start` (`GameAssembly.dll + 0x4BFE00`):

- `RCX` = `BaseInteractable*` component
- this component identity matches the object used by the late debug/category
  callsite

At the late category callsite (`GameAssembly.dll + 0x4C0032`):

- category identity was observed in `RAX` in the v3/v4 logging path
- `BaseInteractable.Start component == latecall late_obj` was repeatedly
  confirmed

At `InteractableMicrowave.Start` (`GameAssembly.dll + 0x4CC6A0`):

- `RCX` = `InteractableMicrowave*`
- live probes confirmed matching `Microwaves` late debug rows through the same
  component identity

## Implementation-Ready Stat Rules

| Stat | Hook/source | Offset | Register or memory rule | Count rule | Confidence |
| --- | --- | ---: | --- | --- | --- |
| `Boss Curses` | `SpawnShrines` instantiate return | `0x49E70C` | `RBX == current MapData.shrines[4]` | `+1` per matching instantiate return | confirmed |
| `Challenges` | `SpawnShrines` instantiate return | `0x49E70C` | `RBX == current MapData.shrines[0]` | `+1` per matching instantiate return | confirmed |
| `Magnet Shrines` | `SpawnShrines` instantiate return | `0x49E70C` | `RBX == current MapData.shrines[1]` | `+1` per matching instantiate return | confirmed |
| `Moais` | `SpawnShrines` instantiate return | `0x49E70C` | `RBX == current MapData.shrines[2]` | `+1` per matching instantiate return | confirmed |
| `Shady Guy` | `SpawnShrines` instantiate return | `0x49E70C` | `RBX == current MapData.shrines[3]` | `+1` per matching instantiate return | confirmed |
| `Charge Shrines` | `RandomObjectSpawner` singleton bucket | `0x49C2A0` / `0x49CA28` | entry `RDX == [RCX+0x48]`; instantiate `RAX` is `GameObject*` | `+1` per successful instantiate in charge bucket | confirmed |
| `Greed Shrines` | `RandomObjectSpawner` singleton bucket | `0x49C2A0` / `0x49CA28` | entry `RDX == [RCX+0x50]`; instantiate `RAX` is `GameObject*` | `+1` per successful instantiate in greed bucket | confirmed |
| `Pots` | `RandomObjectSpawner` bucket/prefab context | `0x49C2A0` / `0x49CA28` | active spawner context / pot prefab bucket; instantiate `RAX` is `GameObject*` | `+1` per successful instantiate in pot bucket(s) | strong |
| `Chests` | `SpawnChests` instantiate return | `0x49D3DA` | `RAX` is instantiated `GameObject*` | `+1` per successful instantiate return | strong |
| `Microwaves` | class-specific `InteractableMicrowave.Start` | `0x4CC6A0` | `RCX` is `InteractableMicrowave*` | `+1` per unique `RCX` component | confirmed |

## SpawnShrines Evidence Summary

Live/CSV evidence linked `SpawnShrines` selectors to categories through
ordinal pairing of eight groups of fourteen `SpawnShrines.instret` rows:

| Observed selector example | Category | Count |
| --- | --- | ---: |
| `0x13A99D25740` | `Boss Curses` | `34` |
| `0x13A99D257C0` | `Challenges` | `18` |
| `0x13A99D25780` | `Moais` | `18` |
| `0x13A99D257A0` | `Magnet Shrines` | `17` |
| `0x13A99D25760` | `Shady Guy` | `25` |

These selector values are examples from one run. The stable rule is the
`MapData.shrines[index]` mapping above.

`SpawnShrines` performs 14 spawn attempts per pass. In the confirmation pass,
`RDI` iterated `0x0` through `0xD`, and `RBX` values were drawn from the
current `MapData.shrines` table.

## RandomObjectSpawner Evidence Summary

The early layer is real and structured:

- `RandomObjectSpawner` receives stable `RandomMapObject` buckets before full
  object startup.
- captured arrays included 6-entry and 5-entry loops plus singleton
  `chargeShrineSpawns` and `greedShrineSpawns` calls.
- `chargeShrineSpawns` corresponds to `Charge Shrines`.
- `greedShrineSpawns` corresponds to `Greed Shrines`.
- passive bridge logging confirmed two pot prefab paths and both shrine singleton
  paths:
  - observed `0x13AB21CA6A0 -> Pots`
  - observed `0x13AB21CA680 -> Pots`
  - observed `0x13AB21CA660 -> Charge Shrines`
  - observed `0x13AB21CA640 -> Greed Shrines`

The observed prefab values above are not stable implementation constants. Use
current-run bucket/prefab context.

## Chests Evidence Summary

`SpawnChests` was confirmed as the clean source for most `Chests`.

Use:

- function: `SpawnInteractables.SpawnChests`
- instantiate return: `GameAssembly.dll + 0x49D3DA`
- count rule: `+1` per successful instantiate return

v7 source/category links showed:

- `SpawnChests.trans -> Chests`: `320`
- `SpawnChests.trans -> Magnet Shrines`: `30`
- `SpawnChests.trans -> Moais`: `17`

For hook implementation, the chest count should use the `SpawnChests`
instantiate return as the chest source. Shrine-like categories should be handled
by the stronger `SpawnShrines + RBX selector` rule.

## Microwaves Evidence Summary

`Microwaves` is confirmed for exact class-specific hook implementation:

- `InteractableMicrowave.Start` = `GameAssembly.dll + 0x4CC6A0`
- `InteractableMicrowave.GetDebugName` = `GameAssembly.dll + 0x4CBEC0`
- the `Microwaves` string literal exists

Live probes confirmed:

- `InteractableMicrowave.Start RCX` matched later `Microwaves` debug rows.
- two microwave starts in one bridge probe joined to two `Microwaves` late rows.
- the stable source clue is a `RandomObjectSpawner` amount `1` bucket, but one
  amount `1` bucket can produce two microwave components.

Implementation conclusion:

- count `Microwaves` from unique `InteractableMicrowave.Start RCX` components
- do not count exactly from `RandomObjectSpawner` amount or instantiate count
  unless a future pass proves internal child/component multiplicity

## SpawnOther / SpawnRails Correction

Current facts:

- `SpawnInteractables.SpawnOther` starts at `GameAssembly.dll + 0x49D4F0`
- real `SpawnOther` instantiate return is `GameAssembly.dll + 0x49D7F6`
- `GameAssembly.dll + 0x49DBE5` is inside `SpawnRails`, not `SpawnOther`
- `SpawnRails` starts at `GameAssembly.dll + 0x49D840`

Do not use `0x49DBE5` as evidence for:

- `Shady Guy`
- `Microwaves`
- `Bald Heads`

## Passive Bridge Lesson

The reliable reverse bridge was passive:

```text
spawner/source context
  -> instantiate return GameObject
  -> natural transform return
  -> BaseInteractable.Start component
  -> late debug/category callsite
```

Avoid calling game functions from CE Lua with `executeCodeEx` for this path.
The attempted `Component.get_gameObject(component)` approach caused nearby
allocation instability in Cheat Engine.
