## Interactable Correlation Findings

Date: 2026-04-24

Goal: finish the reverse path from early `RandomMapObject` / prefab buckets to
final interactable categories, so dry-run counting can move earlier than
`BaseInteractable.Start` and `InteractablesStatus.OnInteractableSpawn`.

## Sources Used

- `docs/memory-and-hooks-reference.md`
- `docs/pre-spawn-reverse-findings-2026-04-23.md`
- `native/BonkHook/HookExports.cs`
- `Dump/dump.cs`
- live Cheat Engine MCP inspection against `Megabonk.exe`
- CSV logs captured from CE Lua logger passes:
  - `bonk_interactable_log.csv`
  - `bonk_interactable_log_v2.csv`
  - `bonk_interactable_log_v3.csv`
  - `bonk_interactable_log_v4.csv`

## Stable Static Facts

From `Dump/dump.cs`:

- `RandomObjectPlacer.GenerateInteractables(MapData)` = RVA `0x49C020`
- `RandomObjectPlacer.Generate(RandomMapObject[] objects, float amountMultiplier)`
  = RVA `0x49C1D0`
- `RandomObjectPlacer.RandomObjectSpawner(RandomMapObject randomObject, float amountMultiplier = 1)`
  = RVA `0x49C2A0`
- `SpawnInteractables.SpawnChests()` = RVA `0x49CF60`
- `SpawnInteractables.SpawnShrines()` = RVA `0x49E180`
- `SpawnInteractables.SpawnOther()` = RVA `0x49D4F0`
- `BaseInteractable.Start()` = RVA `0x4BFE00`
- `InteractablesStatus.OnInteractableSpawn(string debugName)` = RVA `0x51B030`
- `UnityEngine.Object.Instantiate<object>` generic wrapper = RVA `0x758AF0`
- `UnityEngine.Object.Internal_InstantiateSingle(...)` = RVA `0x22B31A0`
- `Component.get_gameObject()` = RVA `0x22A7010`

Important `RandomMapObject` fields:

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

## What The Early Layer Already Proves

The earlier `2026-04-23` findings still hold:

- future interactables are already represented before full instantiation
- `RandomObjectSpawner` receives stable `RandomMapObject` buckets
- the early buckets are not noisy post-spawn data

The stable early bucket set seen across runs is:

- `GameAssembly.dll+0x49C2A0` hits from a 6-entry loop
- `GameAssembly.dll+0x49C2A0` hits from a 5-entry loop
- singleton calls for `chargeShrineSpawns`
- singleton calls for `greedShrineSpawns`

Stable prefab signatures observed across runs:

- `0x22A9480ADC0`
- `0x22A9480ADA0`
- `0x22A9480AD80`
- `0x22A9480AD60;0x22A9480AD40;0x22A9480AD20;0x22A9480AD00;0x22A9480ACE0;0x22A9480ACC0`
- `0x22A9480ACA0`
- `0x22A9480AC80`
- `0x22B136F46A0`
- `0x22B136F4680`
- `0x22A9480A620`
- `0x22B136F46E0`
- `0x22B136F46C0`
- `0x22A9480A5C0`
- `0x22A9480A5A0`

## What Each Logger Version Established

### `bonk_interactable_log.csv`

This proved the overall correlation direction was valid:

- `RandomObjectSpawner` hits were stable and bucketized
- late labels existed and could be captured
- early and late observation in one run was practical

The limitation was that the first logger only gave broad early vs late streams,
without a reliable object identity bridge.

### `bonk_interactable_log_v2.csv`

This fixed label reading and confirmed stable category identities on the late
side:

- `Pots`
- `Chests`
- `Charge Shrines`
- `Greed Shrines`
- `Boss Curses`
- `Challenges`
- `Magnet Shrines`
- `Moais`
- `Shady Guy`
- `Microwaves`

It also confirmed:

- `chargeShrineSpawns` corresponds to `15` `Charge Shrines` per run
- `greedShrineSpawns` corresponds to `8` `Greed Shrines` per run

But the late-side registers logged there were still not enough to join back to
the prefab side.

### `bonk_interactable_log_v3.csv`

This moved the late breakpoint from `OnInteractableSpawn` to the call site at
`GameAssembly.dll+0x4C0032`.

Key finding:

- the category identity at that call site is in `RAX`, not in `RCX`

Stable late-side category pointer map:

- `0x22A94BE19C0 -> Pots`
- `0x22AA75F28A0 -> Chests`
- `0x22AA780B040 -> Charge Shrines`
- `0x22AAC878300 -> Greed Shrines`
- `0x22A94C85400 -> Magnet Shrines`
- `0x22A94C85200 -> Boss Curses`
- `0x22A94776F30 -> Shady Guy`
- `0x22A94776B10 -> Moais`
- `0x22A9474A390 -> Challenges`
- `0x22A94BE14B0 -> Microwaves`

This still did not close the bridge, but it isolated the late category identity
cleanly.

### `bonk_interactable_log_v4.csv`

This added four streams in one log:

- `spawner`
- `instret`
- `start`
- `latecall`

This produced the most important current result:

- `BaseInteractable.Start` and `latecall` match on the same object identity

In practice:

- `start_instance == late_obj`
- therefore `BaseInteractable.Start -> category` is already solved

Examples directly seen in the log:

- `start_instance=0x22AAD00A140` later matches
  `late_obj=0x22AAD00A140 -> Charge Shrines`
- `start_instance=0x22B13C97DC0` later matches
  `late_obj=0x22B13C97DC0 -> Greed Shrines`
- `start_instance=0x22B12F2D990` later matches
  `late_obj=0x22B12F2D990 -> Microwaves`
- `start_instance=0x22B13087DC0` later matches
  `late_obj=0x22B13087DC0 -> Pots`

Late-side exact matches from `start -> latecall` totalled `1563`, with counts:

- `Pots: 621`
- `Chests: 548`
- `Charge Shrines: 165`
- `Greed Shrines: 90`
- `Shady Guy: 35`
- `Boss Curses: 34`
- `Challenges: 29`
- `Magnet Shrines: 17`
- `Microwaves: 16`
- `Moais: 8`

## The Key Remaining Gap

`instret` does not match `start` directly.

Observed in `v4`:

- `instret` gives `prefab=...; instance=...; instance_deref=0x228D0952A30`
- `start` gives `start_instance=...; instance_deref=<category-specific vtable/class ptr>`
- exact `instret.instance == start_instance` matches: `0`

Main conclusion:

- the object returned at `GameAssembly.dll+0x49CA28` is the instantiated
  `GameObject*`
- `BaseInteractable.Start` receives the later `BaseInteractable*` component
- therefore the missing bridge is:
  - `instantiated GameObject -> BaseInteractable component`

This is why `v4` still does not directly produce `prefab -> category`, even
though both ends are now individually understood.

## What Is Already Safe To Treat As Confirmed

High confidence confirmed mappings:

- `0x22B136F46A0 -> Charge Shrines`
- `0x22B136F4680 -> Greed Shrines`

Strong but still best labelled as inference until the final bridge is logged:

- `0x22A9480A620 -> Microwaves`

Other prefab-to-category mappings are not yet fully closed in a proof-quality
sense, even when counts strongly suggest candidates.

## Current Process State Note

The user restarted the game after earlier runs.

Because of that:

- absolute addresses from `2026-04-23` logs are session-specific only
- current live session must use `GameAssembly.dll + offset`

For the live process inspected on `2026-04-24`:

- `Megabonk.exe` PID = `30156`
- `GameAssembly.dll` base = `0x7FF8255A0000`

Any future logging or breakpoint work should continue to use module-relative
offsets instead of old absolute addresses from the previous session.

## Recommended Next Step

The next reverse step should be a `v5` logger that records the `GameObject`
belonging to the component seen in `BaseInteractable.Start`.

Use `Component.get_gameObject()` at:

- `GameAssembly.dll + 0x22A7010`

The goal is to close:

- `spawner prefab -> instret GameObject -> Start component -> late category`

Specifically, at `BaseInteractable.Start` log:

- `component = RCX`
- `gameObject = Component.get_gameObject(component)`
- `component_deref`
- `gameObject_deref`

Keep logging:

- `instret` at `GameAssembly.dll + 0x49CA28`
- `latecall` at `GameAssembly.dll + 0x4C0032`

Then join on:

- `instret.instance(GameObject)` == `Start.gameObject`
- `Start.component` == `latecall.late_obj`

Once that is captured, the reverse target should finally be complete:

- `prefab -> category`

## Practical End State To Aim For

The final output of this reverse effort should be a stable mapping table such
as:

- `prefab A -> Pots`
- `prefab B -> Chests`
- `prefab C -> Moais`
- `prefab D -> Shady Guy`
- `prefab E -> Boss Curses`
- `prefab F -> Challenges`
- `prefab G -> Magnet Shrines`
- `prefab H -> Microwaves`
- plus the already-closed shrine singleton paths

At that point the strongest implementation direction remains:

- count early around `RandomObjectSpawner` or the arrays feeding it
- stop relying on `BaseInteractable.Start`
- stop relying on `InteractablesStatus.OnInteractableSpawn`
