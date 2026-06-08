## SpawnOther / SpawnRails Correction Findings

Date: 2026-04-24

Goal: preserve the live Cheat Engine MCP findings after re-checking the v7
`SpawnOther` assumptions, especially the discovery that one v7 "SpawnOther"
return site actually belongs to `SpawnRails`.

## Sources Used

- `docs/memory-and-hooks-reference.md`
- `docs/interactable-reverse/pre-spawn-reverse-findings-2026-04-23.md`
- `docs/interactable-reverse/interactable-correlation-findings-2026-04-24.md`
- `docs/interactable-reverse/v5-transform-bridge-findings-2026-04-24.md`
- `docs/interactable-reverse/v7-spawn-path-findings-2026-04-24.md`
- `lua/bonk_interactable_logger_v7.lua`
- `Dump/dump.cs`
- `Dump/script.json`
- `Dump/stringliteral.json`
- live Cheat Engine MCP inspection against `Megabonk.exe`

## MCP / Live Session State

Cheat Engine MCP was checked before live analysis.

Confirmed live state:

- CE MCP bridge: `v11.4.0`
- process: `Megabonk.exe`
- PID: `28492`
- `GameAssembly.dll` base: `0x7FF8255A0000`
- active breakpoints after cleanup: `0`

These absolute addresses are session-specific. Implementation and future
loggers should keep using module-relative `GameAssembly.dll + offset` addresses.

## Static Function Boundaries

From `Dump/dump.cs`:

- `SpawnInteractables.SpawnOther()` = `GameAssembly.dll + 0x49D4F0`
- `SpawnInteractables.SpawnRails()` = `GameAssembly.dll + 0x49D840`
- `BaseInteractable.Start()` = `GameAssembly.dll + 0x4BFE00`
- late category callsite remains `GameAssembly.dll + 0x4C0032`

The live disassembly confirms:

- `SpawnOther` function body runs from `GameAssembly.dll + 0x49D4F0` to the
  normal return at `GameAssembly.dll + 0x49D831`.
- `SpawnRails` starts immediately after padding/trap bytes at
  `GameAssembly.dll + 0x49D840`.

## Important Correction

The v7 logger labelled these as `SpawnOther` instantiate return sites:

- `GameAssembly.dll + 0x49D7F6`
- `GameAssembly.dll + 0x49DBE5`

This is now corrected:

- `GameAssembly.dll + 0x49D7F6` is a real `SpawnOther` instantiate return.
- `GameAssembly.dll + 0x49DBE5` is not inside `SpawnOther`; it is inside
  `SpawnRails`.

The `0x49DBE5` site should no longer be used as evidence for missing
interactable categories such as `Shady Guy`, `Microwaves`, or `Bald Heads`.
It is a rails path and should either be removed from the interactable-category
logger or explicitly renamed to `SpawnRails.instret`.

## Confirmed SpawnOther Path

Inside `SpawnOther`, the only confirmed `Object.Instantiate<object>` return
site found in this pass is:

- `GameAssembly.dll + 0x49D7F6`

The call immediately before it is:

- `GameAssembly.dll + 0x49D7F1 -> Object.Instantiate<object>`
- target: `GameAssembly.dll + 0x758AF0`

Nearby `SpawnOther` context:

- `GameAssembly.dll + 0x49D783` calls `GameObject.get_transform`
  (`GameAssembly.dll + 0x22AC8B0`) on a pre-existing object.
- `GameAssembly.dll + 0x49D79F` calls a transform/vector helper and feeds the
  resulting data into the instantiate call.
- `GameAssembly.dll + 0x49D7F6` is after instantiate, but the function then
  quickly restores registers and returns.

Current inference:

- `SpawnOther` has a real instantiate return, but it does not expose the same
  rich post-instantiate transform/component path that was seen in `SpawnChests`,
  `SpawnShrines`, or the mistakenly labelled `SpawnOther.B`/`SpawnRails` area.
- A logger that only records `SpawnOther.instret` may still be insufficient to
  close `Shady Guy` and `Microwaves`.

## Confirmed SpawnRails Path

The site formerly labelled `SpawnOther.B` is:

- `GameAssembly.dll + 0x49DBE5`

Live disassembly shows this is after:

- `GameAssembly.dll + 0x49DBE0 -> Object.Instantiate<object>`
- target: `GameAssembly.dll + 0x758AF0`

The post-instantiate path in `SpawnRails` is rich:

- `GameAssembly.dll + 0x49DBF9 -> GameObject.SetActive(bool)`
  (`GameAssembly.dll + 0x22ABD20`)
- `GameAssembly.dll + 0x49DD99 -> GameObject.get_transform`
  (`GameAssembly.dll + 0x22AC8B0`)
- `GameAssembly.dll + 0x49DE1A -> GameObject.get_transform`
  (`GameAssembly.dll + 0x22AC8B0`)
- `GameAssembly.dll + 0x49DEAB -> GameObject.GetComponentInChildren<object>`
  generic wrapper (`GameAssembly.dll + 0x723320`)
- `GameAssembly.dll + 0x49DEB0` is the return after
  `GetComponentInChildren<object>`, with the returned component in `RAX`.

Related static names:

- `GameAssembly.dll + 0x22B57F0` = `UnityEngine.Random.Range(float,float)`
- `GameAssembly.dll + 0x2294210` = `Quaternion.LookRotation(Vector3, Vector3)`
- `GameAssembly.dll + 0x22DBB30` = `Transform.set_rotation(Quaternion)`
- `GameAssembly.dll + 0x22D9410` = `Transform.Rotate(Vector3, float, Space)`
- `GameAssembly.dll + 0x49BA80` = `Rail.IsValidPosition()`

Current inference:

- This path is useful for understanding rails, but it should not be treated as a
  missing interactable category source.
- Any category joins previously produced through `0x49DBE5` should be reviewed
  as likely rail noise unless independently linked to `BaseInteractable.Start`
  and the late category callsite.

## Live Breakpoint Probe

A short non-breaking breakpoint probe was run after the static correction.

Breakpoints set:

- `GameAssembly.dll + 0x49D4F0` as `SpawnOther` entry
- `GameAssembly.dll + 0x49D7F6` as real `SpawnOther` instantiate return
- `GameAssembly.dll + 0x49DBE5` as corrected `SpawnRails` instantiate return
- `GameAssembly.dll + 0x4BFE00` as `BaseInteractable.Start`

The late category callsite at `GameAssembly.dll + 0x4C0032` could not be added
at the same time because only four hardware debug register slots were available.

Observed result:

- no hits on any of the four breakpoints during the short probe window
- all four breakpoints were removed afterwards
- final active breakpoint count was confirmed as `0`

Interpretation:

- The current live game state did not pass through generation/spawn during the
  probe window.
- This does not contradict the static findings; it only means a new run or map
  generation event is needed for live category correlation.

## Effect On V7 Conclusions

Still valid from v7:

- Passive transform bridging remains the safest direction.
- `BaseInteractable.Start component == latecall late_obj` remains the solved
  late-side identity join.
- `RandomObjectSpawner`, `SpawnChests`, and `SpawnShrines` remain the strongest
  solved spawn sources.

Needs correction:

- Do not describe `GameAssembly.dll + 0x49DBE5` as `SpawnOther.B`.
- Do not use `0x49DBE5` as evidence that `SpawnOther` covers missing categories.
- Treat `SpawnOther` as having only one confirmed instantiate return for now:
  `GameAssembly.dll + 0x49D7F6`.

Open categories after this correction:

- `Shady Guy`
- `Microwaves`
- `Bald Heads`

`Bald Heads` appears in string literals, but this pass did not prove whether it
is a true interactable category, a debug label from another system, or incidental
noise in previous late-category logs.

## Recommended Next Reverse Step

The next pass should be a targeted corrected logger, not a direct continuation
of the old v7 labels.

Recommended logger changes:

- Keep the known stable streams:
  - `BaseInteractable.Start` at `GameAssembly.dll + 0x4BFE00`
  - `start_transform` return sites inside `BaseInteractable.Start`
  - late category callsite at `GameAssembly.dll + 0x4C0032`
- Keep solved source streams:
  - `RandomObjectSpawner`
  - `SpawnChests`
  - `SpawnShrines`
- Correct the old `SpawnOther` streams:
  - keep `GameAssembly.dll + 0x49D7F6` as `SpawnOther.instret`
  - remove `GameAssembly.dll + 0x49DBE5` from `SpawnOther`
  - optionally log `GameAssembly.dll + 0x49DBE5` as `SpawnRails.instret`
    separately, for control/noise analysis only

Suggested extra live probes for missing categories:

- Look for direct calls or references around `InteractableMicrowave.Start`,
  `InteractableMicrowave.GetDebugName`, `InteractableShadyGuy.Start`, and
  `InteractableShadyGuy.GetDebugName` from `Dump/script.json`.
- Search for spawn-time callsites that instantiate prefabs whose later
  `BaseInteractable.Start` category becomes `Shady Guy` or `Microwaves`.
- Prefer passive return-site logging over Lua `executeCodeEx`, consistent with
  the v5/v7 transform bridge lesson.

Concrete validation target:

- Run the corrected logger during a fresh generation/restart cycle.
- Confirm whether `SpawnOther.instret` at `0x49D7F6` can be joined to any later
  `BaseInteractable.Start`/late category row.
- If `0x49D7F6` does not join to `Shady Guy` or `Microwaves`, stop treating
  `SpawnOther` as the likely missing path and search class-specific or
  encounter-specific spawn functions instead.

## Implementation Direction After Confirmation

Do not implement hardcoded session pointers.

Prefer:

- module-relative hook targets
- corrected source labels
- passive object/transform/component joins
- category confirmation through `BaseInteractable.Start -> latecall`
- source-specific counting paths for already solved categories

The implementation should wait for one more corrected live capture if complete
coverage for `Shady Guy`, `Microwaves`, and `Bald Heads` is required.

