## Pre-Spawn Reverse Findings

Date: 2026-04-23

Goal: determine whether interactable categories can be counted before full
instantiation, instead of relying on `BaseInteractable.Start` and
`InteractablesStatus.OnInteractableSpawn`.

## Sources Used

- `docs/memory-and-hooks-reference.md`
- `native/BonkHook/HookExports.cs`
- `Dump/dump.cs`
- live Cheat Engine MCP inspection against `Megabonk.exe`

## Key Static Facts

From `Dump/dump.cs`:

- `RandomObjectPlacer` fields:
  - `center` at `0x20`
  - `size` at `0x2C`
  - `numChargeShrines` at `0x38`
  - `randomObjects` at `0x40`
  - `chargeShrineSpawns` at `0x48`
  - `greedShrineSpawns` at `0x50`
  - `index` at `0x58`
- `RandomObjectPlacer.GenerateInteractables(MapData)` is at RVA `0x49C020`.
- `RandomObjectPlacer.Generate(RandomMapObject[] objects, float amountMultiplier)`
  is at RVA `0x49C1D0`.
- `RandomObjectPlacer.RandomObjectSpawner(RandomMapObject randomObject, float amountMultiplier = 1)`
  is at RVA `0x49C2A0`.
- `SpawnInteractables.SpawnChests()` is at RVA `0x49CF60`.
- `SpawnInteractables.SpawnShrines()` is at RVA `0x49E180`.
- `SpawnInteractables.SpawnOther()` is at RVA `0x49D4F0`.
- `BaseInteractable.Start()` is at RVA `0x4BFE00`.
- `InteractablesStatus.OnInteractableSpawn(string debugName)` is at RVA `0x51B030`.

`RandomMapObject` structure from `Dump/dump.cs`:

- `amount` at `0x10`
- `maxAmount` at `0x14`
- `checkRadius` at `0x18`
- `scaleMin` at `0x1C`
- `scaleMax` at `0x20`
- `maxSlopeAngle` at `0x24`
- `upOffset` at `0x28`
- `prefabs` at `0x30`
- `randomRotationVector` at `0x38`
- `alignWithNormal` at `0x44`

`HookExports.cs` already confirms the current dry-run path:

- `MapGenerator.GenerateMap`
- `RandomObjectPlacer.GenerateInteractables`
- `SpawnInteractables.SpawnChests`
- `SpawnInteractables.SpawnShrines`
- `SpawnInteractables.SpawnOther`

Current dry-run result accumulation in `HookExports.cs` counts these labels only:

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

## Live Session Facts

In the inspected session on 2026-04-23:

- `GameAssembly.dll` base was `0x7FF81F920000`
- absolute hook addresses were:
  - `RandomObjectPlacer.GenerateInteractables`: `0x7FF81FDBC020`
  - `RandomObjectSpawner`: `0x7FF81FDBC2A0`
  - `SpawnChests`: `0x7FF81FDBCF60`
  - `SpawnShrines`: `0x7FF81FDBE180`
  - `SpawnOther`: `0x7FF81FDBD4F0`
  - `BaseInteractable.Start`: `0x7FF81FDDFE00`
  - `InteractablesStatus.OnInteractableSpawn`: `0x7FF81FE3B030`

These absolute addresses are session-specific. Prefer the module-relative form
`GameAssembly.dll + offset` after future restarts.

## What Was Confirmed Live

### 1. Pre-spawn structures are real

`RandomObjectSpawner` was hit successfully, and the live register state matched
the expected calling convention:

- `RCX` = `RandomObjectPlacer*`
- `RDX` = `RandomMapObject*`
- `XMM2` = amount multiplier

One captured `RandomMapObject` at `RDX = 0x22A9479D0F0` decoded correctly:

- `amount = 300`
- `maxAmount = 0`
- `checkRadius = 1.0`
- `prefabs = 0x22A94BFA960`
- `prefabs.length = 1`
- `prefab[0] = 0x22A9480ADC0`

This confirms that category-relevant spawn data exists before final
instantiation.

### 2. `RandomObjectSpawner` is called from multiple pre-spawn buckets

Live hits showed at least two distinct caller patterns.

Pattern A:

- caller array at `RSI = 0x22A94BE8B40`
- length = `6`
- current hits iterated with `RBX = 0..5`

This strongly looks like a `MapData.randomObjectsOverride` style path.

Pattern B:

- caller array at `RSI = 0x22B1319BBE0`
- length = `5`

This strongly looks like `RandomObjectPlacer.randomObjects`.

Separately, there were also hits consistent with singleton `RandomMapObject`
entries matching:

- `chargeShrineSpawns`
- `greedShrineSpawns`

### 3. The early arrays are structured and stable

For the length-6 pre-spawn array, captured entries looked like this:

- element 0: `amount=300`, `prefabs.len=1`
- element 1: `amount=40`, `prefabs.len=1`
- element 2: `amount=100`, `prefabs.len=1`
- element 3: `amount=150`, `prefabs.len=6`
- element 4: `amount=100`, `prefabs.len=1`
- element 5: `amount=8`, `prefabs.len=1`

This is not noisy post-spawn state. It is a clean early bucketized
representation of future interactable groups.

### 4. Late-stage debug labels were captured successfully

Using a non-breaking breakpoint on `InteractablesStatus.OnInteractableSpawn`,
the following debug labels were read live from IL2CPP strings:

- `Charge Shrines`
- `Greed Shrines`
- `Pots`
- `Chests`
- `Challenges`
- `Moais`
- `Shady Guy`
- `Boss Curses`
- `Magnet Shrines`

`Microwaves` did not appear in this specific run, but the label is known to be
handled by current code.

## Main Conclusion

The pre-spawn direction is confirmed viable.

There is already an early, structured layer where the game knows about future
interactable buckets before `BaseInteractable.Start` and before final
`InteractablesStatus.OnInteractableSpawn` accounting.

This means a faster approach than the current dry-run is realistic:

- read or hook `RandomMapObject` buckets early
- map them to final interactable categories
- count categories before full object startup

## What Is Not Yet Fully Solved

The missing correlation is still:

- `RandomMapObject / prefab pointer -> final debug category`

What is already known is:

- early bucket arrays exist
- bucket entries are stable enough to inspect
- final debug labels exist and are readable
- both ends of the pipeline can be observed in the same run

## Recommended Next Step

Run a correlation pass rather than more broad exploration.

Best next target:

- keep non-breaking logging on `RandomObjectSpawner`
- keep non-breaking logging on `InteractablesStatus.OnInteractableSpawn`
- for each `RandomObjectSpawner` hit, record:
  - `RDX`
  - `amount`
  - `prefabs[0]`
  - `prefabs.length`
  - caller array base and index
- for each `OnInteractableSpawn` hit, record:
  - `debugName`
  - caller identity / repeating group

Desired end result:

- a stable mapping table such as:
  - `prefab X -> Moais`
  - `prefab Y -> Shady Guy`
  - `prefab Z -> Boss Curses`
  - etc.

Once that mapping is known, the strongest implementation candidate is an early
counting path around `RandomObjectSpawner` or the arrays feeding it, rather than
continuing to depend on `BaseInteractable.Start`.
