## V7 Spawn Path Findings

Date: 2026-04-24

Goal: update the interactable reverse notes after the v6 and v7 live logging
passes, and define the remaining path toward early interactable counting.

## Sources Used

- `docs/memory-and-hooks-reference.md`
- `docs/interactable-reverse/pre-spawn-reverse-findings-2026-04-23.md`
- `docs/interactable-reverse/interactable-correlation-findings-2026-04-24.md`
- `docs/interactable-reverse/v5-transform-bridge-findings-2026-04-24.md`
- live Cheat Engine MCP inspection against `Megabonk.exe`
- captured logs:
  - `C:\Users\Skadi\AppData\Local\Temp\bonk_interactable_log_v6.csv`
  - `C:\Users\Skadi\AppData\Local\Temp\bonk_interactable_log_v7.csv`

## Current Live Session

For the inspected live process:

- process: `Megabonk.exe`
- PID: `28492`
- `GameAssembly.dll` base: `0x7FF8255A0000`

These absolute addresses are session-specific. Implementation should keep using
module-relative offsets.

## Important Module-Relative Offsets

Already known:

- `RandomObjectPlacer.RandomObjectSpawner` = `GameAssembly.dll + 0x49C2A0`
- `RandomObjectSpawner` instantiate return = `GameAssembly.dll + 0x49CA28`
- `BaseInteractable.Start` = `GameAssembly.dll + 0x4BFE00`
- late category callsite = `GameAssembly.dll + 0x4C0032`

Additional instantiate return sites confirmed in v7:

- `SpawnChests` instantiate return = `GameAssembly.dll + 0x49D3DA`
- `SpawnOther` instantiate return A = `GameAssembly.dll + 0x49D7F6`
- `SpawnOther` instantiate return B = `GameAssembly.dll + 0x49DBE5`
- `SpawnShrines` instantiate return = `GameAssembly.dll + 0x49E70C`

Useful transform return sites observed in v7:

- `SpawnChests` transform return = `GameAssembly.dll + 0x49D3F0`
- `SpawnShrines` transform returns:
  - `GameAssembly.dll + 0x49E722`
  - `GameAssembly.dll + 0x49E770`
  - `GameAssembly.dll + 0x49E77D`

## V6 Result Summary

The v6 logger added active `RandomObjectSpawner` context to instantiate and
transform rows.

Captured event counts:

- `spawner`: `26`
- `instret`: `1568`
- `inst_transform`: `1210`
- `start_transform`: `894`
- `start`: `298`
- `latecall`: `278`

The key v6 result was a proof-quality passive chain:

- `instret GameObject`
- `inst_transform Transform`
- `start_transform Transform`
- `BaseInteractable.Start component`
- `latecall category`

Strong mappings from v6:

- `0x13AB21CA660 -> Charge Shrines`
- `0x13AB21CA640 -> Greed Shrines`
- `0x13AB21CA6A0 -> Pots`
- `0x13AB21CA680 -> Pots`

This confirmed that the no-`executeCodeEx` transform bridge works and can close
real prefab/category links.

## V7 Result Summary

The v7 logger extended the bridge beyond `RandomObjectSpawner` by adding
instantiate and transform return sites from `SpawnChests` and `SpawnShrines`.

Captured event counts:

- total rows: `19756`
- `instret`: `6756`
- `inst_transform`: `6980`
- `start_transform`: `3597`
- `start`: `1199`
- `latecall`: `1119`
- `spawner`: `104`

Late category counts:

- `Pots`: `440`
- `Chests`: `369`
- `Charge Shrines`: `120`
- `Greed Shrines`: `64`
- `Boss Curses`: `34`
- `Shady Guy`: `25`
- `Challenges`: `18`
- `Moais`: `18`
- `Magnet Shrines`: `17`
- `Microwaves`: `13`
- `Bald Heads`: `1`

After deduplicating repeated transform observations for the same object, v7
produced these useful source/category links:

- `RandomObjectSpawner.trans2 -> Pots`: `465`
- `SpawnChests.trans -> Chests`: `320`
- `SpawnChests.trans -> Magnet Shrines`: `30`
- `SpawnChests.trans -> Moais`: `17`
- `SpawnShrines.trans -> Boss Curses`: `34`
- `SpawnShrines.trans -> Challenges`: `18`
- `SpawnShrines.trans -> Moais`: `18`
- `SpawnShrines.trans -> Magnet Shrines`: `15`

## Confirmed Facts

High confidence:

- The passive transform bridge is viable and safer than Lua-side
  `executeCodeEx`.
- `BaseInteractable.Start component == latecall late_obj` remains stable.
- `RandomObjectSpawner` is sufficient for early `Pots` and singleton shrine
  buckets.
- `SpawnChests` is the correct path for most `Chests`.
- `SpawnShrines` is the correct path for `Boss Curses`, `Challenges`, `Moais`,
  and `Magnet Shrines`.

Strong `SpawnShrines` selector candidates from v7:

- `0x13A99D25740 -> Boss Curses`
- `0x13A99D257C0 -> Challenges`
- `0x13A99D25780 -> Moais`
- `0x13A99D257A0 -> Magnet Shrines`

These selector values are live-session pointers and should not be hardcoded
directly. The implementation should either derive them from stable source data
or use the spawn path/category behavior rather than absolute pointer identity.

## Inferences

The strongest implementation shape is now mixed-source early counting:

- count `Pots` and basic random buckets around `RandomObjectSpawner`
- count `Charge Shrines` and `Greed Shrines` from their singleton
  `RandomObjectSpawner` paths
- count `Chests` around the `SpawnChests` instantiate path
- count `Boss Curses`, `Challenges`, `Moais`, and `Magnet Shrines` around the
  `SpawnShrines` selector/spawn path

Trying to solve every category through a single `RandomObjectSpawner`
prefab/category table is no longer the best direction. The game uses multiple
spawn paths, and v7 shows that some categories are more cleanly counted at their
own spawn functions.

## Remaining Gaps

Not fully solved:

- `Shady Guy`
- `Microwaves`
- rare or newly observed categories such as `Bald Heads`
- exact stable derivation for `SpawnShrines` selector values
- whether `SpawnOther` covers the missing categories in this build/session

Important v7 limitation:

- `SpawnOther.A` and `SpawnOther.B` did not produce useful events in the captured
  run, despite their instantiate return sites being identified.

## Recommended Next Reverse Step

Run a targeted `SpawnOther` logger.

Focus points:

- `GameAssembly.dll + 0x49D7F6`
- `GameAssembly.dll + 0x49DBE5`
- nearby calls after each instantiate return that may expose:
  - `GameObject.get_transform`
  - component lookup
  - category/debug identity

Keep logging:

- `BaseInteractable.Start`
- `start_transform`
- late category callsite at `GameAssembly.dll + 0x4C0032`

Desired result:

- close `Shady Guy`
- close `Microwaves`
- explain whether `Bald Heads` is a true category or incidental/noisy label

## Implementation Direction After Remaining Gaps

Once `SpawnOther` is resolved, implement an early counting system with separate
hook/read paths by spawn source:

- `RandomObjectSpawner` bucket counting for random objects and singleton shrine
  buckets
- `SpawnChests` counting for chests
- `SpawnShrines` counting for special shrine-like interactables
- `SpawnOther` counting for the remaining special interactables, if confirmed

Avoid hardcoding session-specific pointers. Prefer:

- `GameAssembly.dll + offset` hook targets
- stable function-local control flow
- stable object/source context
- derived bucket or selector identity from live objects in the current run

## Practical Status

The reverse effort is close to implementation-ready.

Estimated status:

- core feasibility: solved
- main counting sources: mostly solved
- common categories: mostly solved
- rare categories: still need targeted confirmation
- implementation plan: clear, but should wait for `SpawnOther` confirmation if
  complete category coverage is required
