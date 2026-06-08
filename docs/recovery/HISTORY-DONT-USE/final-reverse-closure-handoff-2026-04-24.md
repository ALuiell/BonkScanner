## Final Interactable Reverse Closure Handoff

Date: 2026-04-24

Goal: preserve the latest `SpawnShrines` live confirmation and provide a
single prompt for the final reverse-only pass before hook implementation.

## Scope

This document is for the last reverse pass before implementing early hooks.

It should not start implementation. The remaining work is to close source rules
and confidence for all BonkScanner interactable stats, especially the pieces
that are still not fully implementation-ready.

## Required Sources

Start from:

- `docs/memory-and-hooks-reference.md`
- `docs/interactable-reverse/spawnshrines-reverse-handoff-2026-04-24.md`
- `docs/interactable-reverse/v7-spawn-path-findings-2026-04-24.md`
- `docs/interactable-reverse/spawnother-rails-correction-findings-2026-04-24.md`

Useful supporting files:

- `docs/interactable-reverse/interactable-correlation-findings-2026-04-24.md`
- `docs/interactable-reverse/v5-transform-bridge-findings-2026-04-24.md`
- `lua/bonk_interactable_logger_v7.lua`
- `Dump/dump.cs`
- `Dump/script.json`
- `Dump/stringliteral.json`
- `%TEMP%\bonk_interactable_log_v7.csv`

## Latest Live State

Latest Cheat Engine MCP state checked during the confirmation pass:

- process: `Megabonk.exe`
- PID: `28492`
- `GameAssembly.dll` base: `0x7FF8255A0000`
- active breakpoints before probe: `0`
- active breakpoints after cleanup: `0`

Four non-breaking/logging hardware breakpoints were used:

- `ss_entry`: `GameAssembly.dll + 0x49E180`
- `ss_instret`: `GameAssembly.dll + 0x49E70C`
- `base_start`: `GameAssembly.dll + 0x4BFE00`
- `latecall`: `GameAssembly.dll + 0x4C0032`

They were removed after the restart/generation probe.

## Confirmed SpawnShrines Rule

`SpawnShrines` is now implementation-ready for:

- `Boss Curses`
- `Challenges`
- `Moais`
- `Magnet Shrines`

The production rule should not hardcode session pointers.

Read current-run selectors from:

- `MapController_TypeInfo` = `GameAssembly.dll + 0x2F58E08`
- class static fields offset = `0xB8`
- `MapController.currentMap` static field offset = `0x10`
- `MapData.shrines` field offset = `0x88`
- IL2CPP array length at `+0x18`
- IL2CPP array elements at `+0x20 + index * 8`

Then classify `RBX` at:

- `SpawnShrines` instantiate return = `GameAssembly.dll + 0x49E70C`

Important register fact:

- at `GameAssembly.dll + 0x49E70C`, before `mov rbx, rax`, `RBX` is the
  selected shrine prefab / selector and `RAX` is the instantiated
  `GameObject*`.

Latest current-run `MapData.shrines` table:

| index | selector | category |
| ---: | --- | --- |
| 0 | `0x13A99D257C0` | `Challenges` |
| 1 | `0x13A99D257A0` | `Magnet Shrines` |
| 2 | `0x13A99D25780` | `Moais` |
| 3 | `0x13A99D25760` | `Shady Guy` |
| 4 | `0x13A99D25740` | `Boss Curses` |

Latest breakpoint pass after restart confirmed:

- `SpawnShrines.instret` hit at `GameAssembly.dll + 0x49E70C`
- `RDI` iterated `0x0` through `0xD`
- exactly 14 spawn attempts were observed in the first pass
- `RBX` values were drawn from the current `MapData.shrines` table

First captured selector sequence after restart:

```text
0x13A99D257C0
0x13A99D25760
0x13A99D25740
0x13A99D25740
0x13A99D25780
0x13A99D25760
0x13A99D25740
0x13A99D25780
0x13A99D25760
0x13A99D25740
0x13A99D257C0
0x13A99D25740
0x13A99D257A0
0x13A99D25780
```

## SpawnShrines Category Evidence

From `bonk_interactable_log_v7.csv`, ordinal pairing of 8 groups of 14
`SpawnShrines.instret` rows against the corresponding late category rows gives:

| selector | category | count |
| --- | --- | ---: |
| `0x13A99D25740` | `Boss Curses` | 34 |
| `0x13A99D257C0` | `Challenges` | 18 |
| `0x13A99D25780` | `Moais` | 18 |
| `0x13A99D257A0` | `Magnet Shrines` | 17 |
| `0x13A99D25760` | `Shady Guy` | 25 |

This resolves the old fifth selector question: in the captured run it is
`Shady Guy`, not `InteractableShrineBalance`.

## Bald Heads / InteractableShrineBalance Status

`Bald Heads` is a real debug string for `InteractableShrineBalance`.

Live reads confirmed:

- `0x13A998E6F30` = `Shady Guy`
- `0x13A998E6F00` = `Bald Heads`
- `InteractableShrineBalance.debugName` points to `Bald Heads`

In v7, `Bald Heads` appeared once as an extra late category row after a
`SpawnShrines` group, but it did not participate in the 14-row ordinal mapping.

Current status:

- do not treat `Bald Heads` as one of the main BonkScanner target stats
  without a product decision
- still audit it in the final reverse pass so its source/status is explicit

## Current Reverse Coverage

Implementation-ready or very close:

| stat | current source status |
| --- | --- |
| `Boss Curses` | ready via `SpawnShrines + RBX selector` |
| `Challenges` | ready via `SpawnShrines + RBX selector` |
| `Moais` | ready via `SpawnShrines + RBX selector` |
| `Magnet Shrines` | ready via `SpawnShrines + RBX selector` |
| `Charge Shrines` | ready via singleton `RandomObjectSpawner` bucket |
| `Greed Shrines` | ready via singleton `RandomObjectSpawner` bucket |
| `Chests` | strong source via `SpawnChests`; final table should restate rule |
| `Pots` | strong source via `RandomObjectSpawner`; final table should restate rule |
| `Shady Guy` | strong as `SpawnShrines` index `3`; needs final reverse signoff |
| `Microwaves` | unresolved source; main missing stat |

The main missing stat is `Microwaves`.

The main non-target audit item is `Bald Heads` / `InteractableShrineBalance`.

## Recommended Final Reverse Work

Use one final reverse-only pass with these phases:

1. Confirm `Shady Guy` as `SpawnShrines` index `3`.
2. Close `Microwaves` spawn source without relying on the old
   `SpawnOther.B` label, because `GameAssembly.dll + 0x49DBE5` is
   `SpawnRails`.
3. Audit `Bald Heads` / `InteractableShrineBalance` and decide whether it is
   debug-only, rare extra, separate source, or future product scope.
4. Produce a final implementation-ready table:
   `stat -> source hook -> offset -> register/rule -> confidence -> open risk`.
