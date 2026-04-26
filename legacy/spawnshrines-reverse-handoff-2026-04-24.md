## SpawnShrines Reverse Handoff

Date: 2026-04-24

Goal: preserve the partial `SpawnShrines` reverse work and leave an
implementation-ready plan for finishing early counting without hardcoding
session-specific pointers.

## Scope

This document focuses only on:

- `SpawnInteractables.SpawnShrines`
- the `SpawnShrines` selector / prefab source
- how to count `Boss Curses`, `Challenges`, `Moais`, and `Magnet Shrines`
  early

It does not continue `SpawnOther`, `Shady Guy`, or `Microwaves` reverse work.

## Sources Used

- `docs/memory-and-hooks-reference.md`
- `docs/interactable-reverse/v7-spawn-path-findings-2026-04-24.md`
- `docs/interactable-reverse/spawnother-rails-correction-findings-2026-04-24.md`
- `Dump/dump.cs`
- `Dump/script.json`
- `C:\Users\Skadi\AppData\Local\Temp\bonk_interactable_log_v7.csv`
- live Cheat Engine MCP read-only inspection against `Megabonk.exe`

## Live State Checked

Before live inspection:

- process: `Megabonk.exe`
- PID: `28492`
- `GameAssembly.dll` base: `0x7FF8255A0000`
- active breakpoints: `0`

No new breakpoints were set during this handoff pass. The inspection used
read-only disassembly and pointer reads.

## Static Facts

From `Dump/dump.cs` and `Dump/script.json`:

- `SpawnInteractables.SpawnShrines()` =
  `GameAssembly.dll + 0x49E180`
- `SpawnShrines` instantiate return =
  `GameAssembly.dll + 0x49E70C`
- useful transform returns after that instantiate:
  - `GameAssembly.dll + 0x49E722`
  - `GameAssembly.dll + 0x49E770`
  - `GameAssembly.dll + 0x49E77D`
- `MapData.shrines` field offset = `0x88`
- `MapController.currentMap` static field offset = `0x10`
- `MapController_TypeInfo` = `GameAssembly.dll + 0x2F58E08`
- class static fields offset = `0xB8`
- `SpawnInteractables.numShrines` const = `14`

Relevant methods / helpers resolved from `script.json`:

- `Method$UnityEngine.Object.Instantiate<GameObject>()`
  at `GameAssembly.dll + 0x2F785D8`
- `UnityEngine.Object.Instantiate<object>` wrapper =
  `GameAssembly.dll + 0x758AF0`
- `UnityEngine.GameObject.get_transform` =
  `GameAssembly.dll + 0x22AC8B0`
- `Method$System.Collections.Generic.List<GameObject>.get_Item()`
  at `GameAssembly.dll + 0x2F71B68`
- `Method$System.Collections.Generic.List<GameObject>.Add()`
  at `GameAssembly.dll + 0x2F71668`
- `Method$System.Collections.Generic.List<GameObject>..ctor()`
  at `GameAssembly.dll + 0x2F71488`

## Current SpawnShrines Understanding

The important correction is that the v7 "selector" values are not stable facts
by themselves. They are live-session `GameObject*` values selected from the
current map's shrine prefab list.

Observed disassembly flow:

1. `SpawnShrines` creates or fills a `List<GameObject>`.
2. It reads `MapController.currentMap`.
3. It reads `MapData.shrines` from the current map at offset `0x88`.
4. It iterates that shrine array and adds items into the local
   `List<GameObject>`.
5. Later, for each shrine spawn, it chooses a list item through
   `List<GameObject>.get_Item`.
6. The returned `GameObject*` is kept in `RBX`.
7. `RBX` is passed as the original prefab to
   `UnityEngine.Object.Instantiate<object>`.
8. The instantiate return is observed at `GameAssembly.dll + 0x49E70C`.

The key implementation lesson:

- Do not hardcode the v7 selector pointers.
- If selector identity is needed, derive it from the current run's
  `MapData.shrines` array or classify the instantiated object's component type.

## Useful Disassembly Anchors

`SpawnShrines` loop / list setup:

- `GameAssembly.dll + 0x49E262`
  - writes `0x0E`; this matches `numShrines = 14`
- `GameAssembly.dll + 0x49E306`
  - loads `MapController_TypeInfo`
- `GameAssembly.dll + 0x49E325`
  - reads class static fields at `+0xB8`
- `GameAssembly.dll + 0x49E344`
  - reads `currentMap` from static fields at `+0x10`
- `GameAssembly.dll + 0x49E390`
  - reads `MapData.shrines` from current map at `+0x88`
- `GameAssembly.dll + 0x49E3D2`
  - reads an element from the shrine array
- `GameAssembly.dll + 0x49E46C`
  - calls `List<GameObject>.Add`

`SpawnShrines` spawn loop:

- `GameAssembly.dll + 0x49E695`
  - calls `List<GameObject>.get_Item`
- `GameAssembly.dll + 0x49E69E`
  - moves returned item into `RBX`
- `GameAssembly.dll + 0x49E707`
  - calls `UnityEngine.Object.Instantiate<object>`
- `GameAssembly.dll + 0x49E70C`
  - instantiate return; `RAX` is the new `GameObject*`
- `GameAssembly.dll + 0x49E71D`
  - calls `GameObject.get_transform`
- `GameAssembly.dll + 0x49E722`
  - transform return

## V7 Evidence

In `bonk_interactable_log_v7.csv`, `SpawnShrines` emitted 8 groups of
14 instantiate rows. Each group corresponds to one `SpawnShrines` pass.

The `RDI` value at `SpawnShrines.instret` behaves like a per-pass loop index:

- first group: `0x0` through `0xD`
- each group count: `14`

Observed v7 selector candidates:

- `0x13A99D25740`
- `0x13A99D25760`
- `0x13A99D25780`
- `0x13A99D257A0`
- `0x13A99D257C0`

These are session-specific `GameObject*` values from the current map shrine
list and must not be hardcoded.

The older v7 findings linked four of those selectors strongly:

- `0x13A99D25740 -> Boss Curses`
- `0x13A99D257C0 -> Challenges`
- `0x13A99D25780 -> Moais`
- `0x13A99D257A0 -> Magnet Shrines`

This handoff pass found one additional selector in v7:

- `0x13A99D25760`

It appears repeatedly in `SpawnShrines`, but its final category still needs a
clean proof-quality join. Based on prior context it may correspond to
`InteractableShrineBalance` / `Bald Heads`, but that should be treated as
unconfirmed until a targeted probe verifies it.

## Why The Old Transform Join Is Not Enough

The passive transform bridge is valid, but the old broad transform join is too
noisy for proving the fifth selector.

Reason:

- transform pointers can be reused
- `SpawnShrines` rows are followed by many `Chests` and other late rows
- simple "nearest matching transform" joins can over-link to unrelated objects

This is why implementation should not rely on the raw v7 transform join alone
for final selector classification.

## Confirmed / Strong / Open

Confirmed:

- `SpawnShrines` is the correct source for shrine-like special interactables.
- `SpawnShrines` performs 14 spawn attempts per pass.
- the prefab/selector used for instantiate is in `RBX` at
  `GameAssembly.dll + 0x49E70C`.
- the selector comes from a `List<GameObject>` derived from
  `MapController.currentMap.shrines`.
- v7 selector addresses are session-specific.

Strong but should be re-confirmed cleanly:

- current-map shrine prefab identity can be turned into category identity by
  either:
  - reading `MapData.shrines` and classifying each prefab/component, or
  - observing class-specific `Start` / `GetDebugName` on spawned components
    during a targeted run.

Open:

- exact stable classification of the fifth `MapData.shrines` entry
  (`0x13A99D25760` in v7)
- whether that fifth entry should be ignored, exposed as `Bald Heads`, or
  treated as `InteractableShrineBalance` outside the main BonkScanner stat set
- best production strategy for category derivation:
  - current-map `MapData.shrines` table + current-run pointer mapping
  - or class-specific component hooks

## Recommended Minimal Next Probe

Create a focused `SpawnShrines` v8 logger. It should not call game code from
Lua.

Log these streams:

- `SpawnShrines` entry: `GameAssembly.dll + 0x49E180`
- shrine array element read: around `GameAssembly.dll + 0x49E3D2`
- `List<GameObject>.Add` return or pre-call context around
  `GameAssembly.dll + 0x49E46C`
- `List<GameObject>.get_Item` return / post-call:
  `GameAssembly.dll + 0x49E69E`
- instantiate return:
  `GameAssembly.dll + 0x49E70C`
- `BaseInteractable.Start`:
  `GameAssembly.dll + 0x4BFE00`
- late category callsite:
  `GameAssembly.dll + 0x4C0032`

Because there are only four hardware breakpoint slots, the logger should use a
CE Lua breakpoint set only if CE can manage more software breakpoints safely.
Otherwise split into two passes:

Pass A:

- `SpawnShrines` entry
- `0x49E3D2`
- `0x49E69E`
- `0x49E70C`

Pass B:

- `0x49E70C`
- `BaseInteractable.Start`
- `0x4C0032`
- one type-specific / component bridge point if needed

Fields to record:

- current map pointer
- `MapData.shrines` array pointer
- shrine array length
- shrine array index
- shrine array element pointer
- local list index
- `RBX` selector after `List<GameObject>.get_Item`
- instantiated `GameObject*`
- component pointer at `BaseInteractable.Start`
- late category label
- `late_obj_deref`

Expected proof target:

- `MapData.shrines[index] -> RBX selector -> instantiated GameObject -> Start
  component -> late category`

If the fifth selector resolves to `InteractableShrineBalance` / `Bald Heads`,
do not add it to the main BonkScanner category set unless that is an explicit
product decision.

## Implementation Direction After Probe

For production early counting, prefer:

1. Hook or observe `SpawnShrines` at `GameAssembly.dll + 0x49E70C`.
2. Read the current selector/prefab from `RBX`.
3. Classify the selector using a current-run table derived from
   `MapController.currentMap.shrines`.
4. Count only main BonkScanner shrine-like categories:
   - `Boss Curses`
   - `Challenges`
   - `Moais`
   - `Magnet Shrines`
5. Exclude `InteractableShrineBalance` / `Bald Heads` unless separately
   approved.

Fallback if selector classification remains awkward:

- hook class-specific `Start` methods for the shrine-like classes instead of
  trying to classify `SpawnShrines` purely at prefab time.
- this is slightly later than `SpawnShrines.instret`, but still source-specific
  and avoids session pointer hardcoding.

## Stop Point

Work was intentionally stopped here before running a new live probe or writing
any logger code.

No implementation changes were made.
