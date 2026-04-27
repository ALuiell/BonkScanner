# Current Interactable Reverse Goals And Plan

Date: 2026-04-24

This is the current planning handoff for interactable hook development. Use
this document for intent and implementation shape, then use
`current-hook-reverse-reference-2026-04-24.md` for concrete offsets and rules.

## Why This Reverse Work Exists

The original BonkScanner dry-run/interactable path depended too much on late
game signals:

- `BaseInteractable.Start`
- `InteractablesStatus.OnInteractableSpawn`
- final debug strings/categories after objects were already mostly spawned

The goal of the reverse work was to find earlier and more reliable source
points for interactable counts, so hooks can count categories closer to their
spawn source and avoid waiting for broad late-stage accounting.

The target BonkScanner stat set is:

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

`Bald Heads` / `InteractableShrineBalance` is a real observed debug label, but
it is not part of the current main BonkScanner stat set.

## Main Direction That Survived The Reverse Passes

Use mixed source-specific counting paths. Do not try to force every stat
through a single `RandomObjectSpawner` prefab table.

The current implementation direction is:

| Stat group | Source path | Why |
| --- | --- | --- |
| `Boss Curses`, `Challenges`, `Magnet Shrines`, `Moais`, `Shady Guy` | `SpawnInteractables.SpawnShrines` instantiate return | The selected current-map shrine prefab is available in `RBX` and maps cleanly through `MapData.shrines`. |
| `Charge Shrines`, `Greed Shrines` | singleton buckets in `RandomObjectPlacer.RandomObjectSpawner` | The buckets are structurally distinct at `[RCX+0x48]` and `[RCX+0x50]`. |
| `Pots` | `RandomObjectPlacer.RandomObjectSpawner` bucket/prefab context | Passive transform bridging confirmed pot prefabs through this path. |
| `Chests` | `SpawnInteractables.SpawnChests` instantiate return | The chest source is separate and much cleaner than late debug accounting. |
| `Microwaves` | `InteractableMicrowave.Start` | Exact class-specific hook is confirmed; strict pre-Start counting is not solved or required for current hooks. |

## Important Design Constraints

- Only `GameAssembly.dll + offset` hook targets are stable enough for code.
- Do not hardcode live heap pointers, selector pointers, prefab pointers, or
  absolute addresses from a specific Cheat Engine session.
- Derive `SpawnShrines` selector identity from the current run's
  `MapController.currentMap.shrines` table.
- Treat `GameAssembly.dll + 0x49DBE5` as `SpawnRails`, not `SpawnOther`.
- Avoid Lua-side `executeCodeEx` calls into game code for this reverse path.
  The passive transform bridge was created specifically because direct calls
  such as `Component.get_gameObject` caused Cheat Engine allocation instability.

## High-Level Hook Plan

1. On map/dry-run start, resolve `GameAssembly.dll` base and read the current
   `MapData.shrines` selector table.
2. Hook `SpawnShrines` instantiate return at `GameAssembly.dll + 0x49E70C`.
   Use `RBX` to classify the selected shrine prefab against the current
   `MapData.shrines` entries.
3. Hook `RandomObjectSpawner` / its instantiate return for random-object
   buckets, especially singleton shrine buckets and pots.
4. Hook `SpawnChests` instantiate return at `GameAssembly.dll + 0x49D3DA`.
5. Hook `InteractableMicrowave.Start` at `GameAssembly.dll + 0x4CC6A0` and
   count unique `RCX` component pointers.
6. Keep late `BaseInteractable.Start` / debug callsite logic only as an
   optional validation or fallback path, not the main counting design.

## Recommended LLM Implementation Order

1. Implement the shared hook bookkeeping first:
   - module-relative target resolution
   - per-dry-run counters
   - duplicate suppression where a hook can fire more than once for the same
     component/object
2. Implement `SpawnShrines` selector-table reading and counting. This closes
   five stats with one source path.
3. Implement singleton `RandomObjectSpawner` buckets for `Charge Shrines` and
   `Greed Shrines`.
4. Implement `SpawnChests`.
5. Implement `Pots` from the confirmed `RandomObjectSpawner` bucket/prefab
   path.
6. Implement `Microwaves` through the class-specific `Start` hook.
7. Leave `Bald Heads` out unless there is an explicit product decision to add
   it as a user-facing stat.
