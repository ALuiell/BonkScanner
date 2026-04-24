## Implementation-Ready Interactable Reverse

Date: 2026-04-24

Goal: preserve the final reverse-only closure state for BonkScanner
interactable early counting before implementing hooks.

No hook implementation was done in this pass.

## Scope

This document summarizes the final implementation-ready source rules for the
current BonkScanner interactable stat set:

- `Boss Curses`
- `Challenges`
- `Charge Shrines`
- `Chests`
- `Greed Shrines`
- `Magnet Shrines`
- `Microwaves`
- `Moais`
- `Pots`
- `Shady Guy`

It also records the final status of `Bald Heads` /
`InteractableShrineBalance`, which is not currently part of the main stat set.

## Sources

Primary sources:

- `docs/memory-and-hooks-reference.md`
- `docs/interactable-reverse/final-reverse-closure-handoff-2026-04-24.md`
- `docs/interactable-reverse/spawnshrines-reverse-handoff-2026-04-24.md`
- `docs/interactable-reverse/v7-spawn-path-findings-2026-04-24.md`
- `docs/interactable-reverse/spawnother-rails-correction-findings-2026-04-24.md`
- `docs/interactable-reverse/interactable-correlation-findings-2026-04-24.md`
- `docs/interactable-reverse/v5-transform-bridge-findings-2026-04-24.md`
- `Dump/dump.cs`
- `Dump/script.json`
- `Dump/stringliteral.json`

Live/CSV sources:

- `%TEMP%\bonk_interactable_log_v7.csv`
- `%TEMP%\bonk_microwave_probe.csv`
- `%TEMP%\bonk_microwave_bridge_probe.csv`

## Latest Live State

Latest live process state used for the final checks:

- process: `Megabonk.exe`
- PID: `28492`
- `GameAssembly.dll` base: `0x7FF8255A0000`
- active breakpoints after cleanup: `0`

Two focused Cheat Engine Lua probes were used for the final `Microwaves`
closure:

- `%TEMP%\bonk_microwave_probe.csv`
  - captured `937` events
  - confirmed `InteractableMicrowave.Start -> latecall` identity
- `%TEMP%\bonk_microwave_bridge_probe.csv`
  - captured `2325` events
  - confirmed `2` `Microwaves` late rows in the captured generation
  - confirmed cleanup after probe

Important limitation:

- the MCP `list_breakpoints` view did not enumerate the Lua
  `debug_setBreakpoint` breakpoints while probes were active, so cleanup was
  verified by explicitly calling each probe's `stop()` method and then checking
  MCP active breakpoints again.

## Confirmed Module-Relative Offsets

Only offsets applied as `GameAssembly.dll + offset` are module-relative.

| Target | Offset |
| --- | ---: |
| `RandomObjectPlacer.RandomObjectSpawner` | `0x49C2A0` |
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
| late debug callsite | `0x4C0032` |
| `InteractableMicrowave.Start` | `0x4CC6A0` |
| `MapController_TypeInfo` | `0x2F58E08` |

Important correction:

- `GameAssembly.dll + 0x49DBE5` must not be used as `SpawnOther.B`.
- It is inside `SpawnRails`, not `SpawnOther`.
- Do not use it as evidence for `Shady Guy`, `Microwaves`, or `Bald Heads`.

## Current-Run Shrine Selector Path

`SpawnShrines` selector pointers are session-specific. Do not hardcode them.

Derive the current-run selector table from:

```text
GameAssembly.dll + 0x2F58E08
  -> +0xB8 class static fields
  -> +0x10 MapController.currentMap
  -> +0x88 MapData.shrines
  -> +0x18 IL2CPP array length
  -> +0x20 + index * 8 IL2CPP array elements
```

At `GameAssembly.dll + 0x49E70C`:

- before `mov rbx, rax`, `RBX` is the selected shrine prefab / selector
- `RAX` is the instantiated `GameObject*`

Latest confirmed current-run table from the previous `SpawnShrines` handoff:

| index | category |
| ---: | --- |
| 0 | `Challenges` |
| 1 | `Magnet Shrines` |
| 2 | `Moais` |
| 3 | `Shady Guy` |
| 4 | `Boss Curses` |

## Final Implementation-Ready Table

| Stat | Source / function path | Module-relative offset | Register / memory path | Counting rule | Confidence | More live confirmations |
| --- | --- | ---: | --- | --- | --- | --- |
| `Boss Curses` | `SpawnInteractables.SpawnShrines` instantiate return | `0x49E70C` | `RBX == current MapData.shrines[4]` | count `+1` per matching `SpawnShrines` instantiate return | confirmed | no |
| `Challenges` | `SpawnInteractables.SpawnShrines` instantiate return | `0x49E70C` | `RBX == current MapData.shrines[0]` | count `+1` per matching `SpawnShrines` instantiate return | confirmed | no |
| `Magnet Shrines` | `SpawnInteractables.SpawnShrines` instantiate return | `0x49E70C` | `RBX == current MapData.shrines[1]` | count `+1` per matching `SpawnShrines` instantiate return | confirmed | no |
| `Moais` | `SpawnInteractables.SpawnShrines` instantiate return | `0x49E70C` | `RBX == current MapData.shrines[2]` | count `+1` per matching `SpawnShrines` instantiate return | confirmed | no |
| `Shady Guy` | `SpawnInteractables.SpawnShrines` instantiate return | `0x49E70C` | `RBX == current MapData.shrines[3]` | count `+1` per matching `SpawnShrines` instantiate return | confirmed | no |
| `Charge Shrines` | `RandomObjectPlacer.RandomObjectSpawner` / instantiate return | `0x49C2A0` / `0x49CA28` | entry `RDX == RandomObjectPlacer.chargeShrineSpawns` (`[RCX+0x48]`); instantiate `RAX` is `GameObject*` | count `+1` per successful instantiate in the charge singleton bucket | confirmed | no |
| `Greed Shrines` | `RandomObjectPlacer.RandomObjectSpawner` / instantiate return | `0x49C2A0` / `0x49CA28` | entry `RDX == RandomObjectPlacer.greedShrineSpawns` (`[RCX+0x50]`); instantiate `RAX` is `GameObject*` | count `+1` per successful instantiate in the greed singleton bucket | confirmed | no |
| `Pots` | `RandomObjectPlacer.RandomObjectSpawner` / instantiate return | `0x49C2A0` / `0x49CA28` | active spawner bucket / prefab context; instantiate `RAX` is `GameObject*` | count `+1` per successful instantiate in pot bucket(s) | strong | no, unless proof-only capture is desired |
| `Chests` | `SpawnInteractables.SpawnChests` instantiate return | `0x49D3DA` | `RAX` is instantiated `GameObject*` | count `+1` per successful `SpawnChests` instantiate return | strong | no |
| `Microwaves` | exact class-specific path: `InteractableMicrowave.Start` | `0x4CC6A0` | `RCX` is `InteractableMicrowave*` | count `+1` per unique `RCX` component | confirmed | no for hooks; only needed if strict pre-Start counting is mandatory |

## Shady Guy Status

`Shady Guy` is closed.

Evidence:

- the current-run shrine table contains `Shady Guy` at
  `MapData.shrines[3]`
- v7 ordinal pairing linked the fifth selector to `Shady Guy` `25` times
- the selector is observed in `RBX` at `GameAssembly.dll + 0x49E70C`

Implementation rule:

- derive the current-run selector table from `MapController.currentMap`
- count `Shady Guy` when `RBX == MapData.shrines[3]`
- do not hardcode session selector pointers

## Microwaves Status

`Microwaves` is closed for exact hook implementation.

Static facts:

- `InteractableMicrowave.Start` = `GameAssembly.dll + 0x4CC6A0`
- `InteractableMicrowave.GetDebugName` = `GameAssembly.dll + 0x4CBEC0`
- `InteractableMicrowave` has static `debugName`
- the `Microwaves` string literal exists in `Dump/stringliteral.json`

Live facts from `%TEMP%\bonk_microwave_probe.csv`:

- one `InteractableMicrowave.Start` hit was captured
- `InteractableMicrowave.Start RCX = 0x13B1A7B5220`
- the immediately following late debug row was `Microwaves`
- late debug `RBX = 0x13B1A7B5220`
- therefore `InteractableMicrowave.Start RCX == latecall late_obj`

Live facts from `%TEMP%\bonk_microwave_bridge_probe.csv`:

- two `InteractableMicrowave.Start` hits were captured
- both joined to `Microwaves` late rows through the same component identity
- both microwave starts happened after the `RandomObjectSpawner` amount `1`
  bucket with session prefab `0x13A9997A5A0`

Important implementation conclusion:

- the stable spawn source clue is `RandomObjectSpawner` bucket index `4`,
  session prefab `0x13A9997A5A0`, amount `1`
- however, the final exact count can exceed that bucket's `amount`
- in the bridge probe, one amount `1` bucket was followed by two
  `InteractableMicrowave.Start` components
- therefore, do not count `Microwaves` exactly from `RandomObjectSpawner`
  bucket amount or instantiate count alone

Recommended implementation rule:

- hook `InteractableMicrowave.Start` at `GameAssembly.dll + 0x4CC6A0`
- count unique `RCX` component pointers
- this is class-specific, exact, and avoids relying on the old
  `SpawnOther.B` / `SpawnRails` confusion

If strict pre-`Start` microwave counting becomes a future product requirement,
then a separate pass is needed to understand the prefab's internal child
component multiplicity.

## Bald Heads / InteractableShrineBalance Status

`Bald Heads` is not part of the current BonkScanner main stat set.

Confirmed facts:

- `Bald Heads` is a real debug string
- it belongs to `InteractableShrineBalance.debugName`
- `InteractableShrineBalance.GetDebugName` =
  `GameAssembly.dll + 0x4CDCC0`
- `InteractableShrineBalance.ShowInDebug` =
  `GameAssembly.dll + 0x383DB0`

Observed behavior:

- `Bald Heads` appeared once as a late debug row in v7
- it did not participate in the 14-row `SpawnShrines` ordinal selector mapping
- it is not one of the current BonkScanner target stats

Implementation decision:

- do not add `Bald Heads` to the main stat set
- keep it as future product scope or separate debug-only/rare-extra audit item
  unless explicitly requested

## Readiness Summary

Reverse coverage is sufficient to move to hook implementation for the current
BonkScanner interactable stats.

Implementation should use mixed source paths:

- `SpawnShrines + RBX selector` for:
  - `Boss Curses`
  - `Challenges`
  - `Magnet Shrines`
  - `Moais`
  - `Shady Guy`
- `RandomObjectSpawner` singleton buckets for:
  - `Charge Shrines`
  - `Greed Shrines`
- `SpawnChests` for:
  - `Chests`
- `RandomObjectSpawner` bucket/prefab mapping for:
  - `Pots`
- class-specific `InteractableMicrowave.Start` for:
  - `Microwaves`

No additional live confirmations are required before implementing hooks,
unless the product goal changes to require strict pre-`Start` counting for
`Microwaves`.
