# `!chests` Command Detection Design

## Purpose

This document records the investigated ways to classify chest openings reported
by the Twitch Bot `!chests` command. The important distinction is between:

- a normal chest paid for with gold;
- a normal chest opened for free because the Key item proc succeeded;
- a chest that was inherently free when it spawned on the map.

The command formatter itself is in `twitch_bot.py::_handle_chests()`. Runtime
state is maintained by `LiveRunTracker`, and the cumulative counters are read
by the regular player-stat refresh in `gui_player_stats.py`.

For the raw reverse-engineering background, enum definitions, class layouts,
and chest-price formula, see
`docs/recovery/reports/2026-06-10-chests-and-keys-detection.md`.

## Relevant Game Types

### `EChest`

| Value | Name | Meaning |
| ---: | --- | --- |
| `0` | `Normal` | Normal chest that normally costs gold. A Key proc may make this opening free. |
| `1` | `Corrupt` | Corrupted chest. Keep separate unless its payment behavior is explicitly verified. |
| `2` | `Free` | Inherently free map chest. It must not be counted as a Key proc. |
| `3` | `FreeCrypt` | Inherently free Crypt chest. It must not be counted as a Key proc. |
| `4` | `Ghost` | Ghost chest. Keep separate unless its behavior is explicitly verified. |

### Important Fields

```text
InteractableChest.chestType       +0x58  EChest
InteractableChest.opening        +0x68  bool
ChestWindowUi.chestType          +0x78  EChest
DetectInteractables.currentInteractable
                                  +0x28  BaseInteractable*
PlayerInventory.goldInt          +0x70  int
```

## Option 1: Chest Count and Gold Delta

### Status

This was the original implementation. It was simple, but it could not
distinguish an inherently free chest from a successful Key proc and has now
been replaced by Option 3.

### Current Data Sources

- Opened chest count:
  `GameDataClient.get_map_stats()[MapStat.CHESTS].current`
- Current gold:
  `PlayerStatsClient.get_current_gold()`
- Key count:
  parsed from the live passive-item inventory
- Key proc probability:

```text
chance = (0.10 * key_count) / (0.10 * key_count + 1.0)
```

### Historical Algorithm

`LiveRunTracker.track_chest_opening(chests_opened, gold)` keeps the previous
chest count and gold value.

```text
if opened increased by exactly 1:
    if current_gold >= previous_gold:
        increment free opening counter
```

The historical tracker ran every `250 ms`. The replacement uses persistent
counters in the existing `10,000 ms` full player-stat refresh.

### Advantages

- Requires no new memory path.
- Correctly separates most paid openings from openings with no visible gold
  reduction.
- Low runtime cost.

### Limitations

1. An inherently free chest also increases the chest count without reducing
   gold, so it is counted as a Key proc.
2. Gold gained near the same sample can hide the cost of a paid chest. A paid
   opening may therefore look free when `gold_after >= gold_before`.
3. Sampling observes state, not the atomic purchase operation. The gold change
   and chest-count change may occur in different samples.
4. A failed gold read currently returns `0`, which can contaminate the next
   comparison if it is treated as a valid sample.
5. A chest-count jump greater than one cannot be classified safely and should
   only synchronize the baseline.

### Implementation Notes

If this option is retained by itself, it should be described as counting
"openings without detected gold loss", not strictly "Key procs". Invalid gold
reads should return `None` or another explicit unavailable state rather than
`0` for this tracker.

## Option 2: `ChestWindowUi.chestType`

### Memory Path

The `UiManager` TypeInfo address for the tested build is:

```text
GameAssembly.dll + 0x2F9A528  -> UiManager TypeInfo
  -> +0xB8                    -> static fields
  -> +0x0                     -> UiManager.Instance
  -> +0x30                    -> EncounterWindows
  -> +0x30                    -> ChestWindowUi
  -> +0x78                    -> ChestWindowUi.chestType
```

The chain was validated live by reading class names at every object:

```text
UiManager -> EncounterWindows -> ChestWindowUi
```

`EncounterWindows.activeEncounterWindow` is at `+0x48` and can theoretically
be used to confirm that the chest window is active.

### Intended Algorithm

```text
when a chest opening is detected:
    read ChestWindowUi.chestType
    0 -> normal chest; use gold delta to classify paid vs Key proc
    2 or 3 -> inherently free; do not count as Key proc
```

### Advantages

- Reads a single global UI object instead of searching map objects.
- The UI already receives the chest type to select the correct mesh/material.
- The pointer chain is short and easy to validate.

### Live-Test Result

This option is not reliable when the game's "Skip Chest Animation" setting is
enabled.

During live tests:

- normal paid and Key-proc openings increased the chest counter correctly;
- an inherently free chest was opened and confirmed by unchanged gold;
- `ChestWindowUi.chestType` remained `0` throughout;
- `EncounterWindows.activeEncounterWindow` remained null;
- polling as fast as approximately `2 ms` still did not observe a useful UI
  state transition.

The likely explanations are that the field is assigned and cleared within one
game frame, or that the skip path bypasses the visible chest-window lifecycle.

### Recommendation

Do not use this as the primary production source while chest-animation skip is
supported. It remains useful as a diagnostic or fallback source if a future
game update exposes a persistent active-window state.

## Option 3: Cumulative Game Counters

### Status

This is the implemented and preferred read-only option. Live tests confirmed
that two persistent game counters provide the complete breakdown without UI
hooks, interactable polling, gold deltas, or event-timing heuristics.

### Correct TypeInfo Address

The decimal address exported by the current `script.json` is `49,783,152`.
Its correct hexadecimal representation is:

```text
49,783,152 decimal = 0x2F7A170
```

Do not use `0x2F79E70`; that conversion is incorrect. The project already uses
the correct `0x2F7A170` offset in `PlayerStatsClient` to read
`RunStats.stats["kills"]`.

### Memory Path

```text
GameAssembly.dll + 0x2F7A170  -> RunStats TypeInfo
  -> +0xB8                    -> static fields
  -> +0x0                     -> Dictionary<string, float> stats
```

The dictionary layout used by the current build is:

```text
stats dictionary +0x18 -> entries array pointer
stats dictionary +0x20 -> int count

entries array +0x20 + index * 0x18 -> dictionary entry
entry +0x0  -> int hashCode
entry +0x4  -> int next
entry +0x8  -> managed string key pointer
entry +0x10 -> inline float value
```

The direct paid-purchase counter is stored separately:

```text
GameAssembly.dll + 0x2F5E0B0  -> MoneyUtility TypeInfo
  -> +0xB8                    -> static fields
  -> +0x48                    -> int chestsPurchased
```

Production reads should reject invalid counts, skip entries with a negative
hash code or null key, and cap the scan at the existing
`MAX_RUN_STATS_ENTRIES = 256`.

### Counter Semantics

The current metadata contains both enum members:

```text
EMyStat.chestsOpened = 3
EMyStat.chestsBought = 20
```

In the live dictionary inspected during this investigation,
`"chestsOpened"` was not present, but `"chestsBought"` was present. The tested
game build uses these three values:

```text
tracked_opened   = sum of MapStat.CHESTS.current across unique stage pointers
chests_bought    = RunStats.stats["chestsBought"]
chests_purchased = MoneyUtility.chestsPurchased
```

Repeated live tests confirmed the following behavior:

```text
paid normal chest       -> opened +1, chestsBought +1, chestsPurchased +1
successful Key proc     -> opened +1, chestsBought +1, chestsPurchased +0
inherently free chest   -> opened +1, chestsBought +0, chestsPurchased +0
```

`RunStats` and `MoneyUtility.chestsPurchased` persist across map transitions.
`MapStat.CHESTS.current` resets for each stage. A transition test containing an
inherently free chest followed by a paid chest produced the expected cumulative
counter changes after entering the second map.

### Classification Algorithm

```text
paid          = chestsPurchased
key_procs     = chestsBought - chestsPurchased
free_chests   = tracked_opened - chestsBought
normal_opened = paid + key_procs
```

Accept a snapshot only when all invariants hold:

```text
0 <= chestsPurchased <= chestsBought <= tracked_opened
```

If a map transition briefly exposes the cumulative counters before the new
stage appears in the tracked stage totals, the snapshot is rejected and the
last valid breakdown is retained. The next 10-second refresh self-heals once
the stage pointer and map count are available.

### Stage and Run Scope

`MapStat.CHESTS.current` is associated with the current unique stage pointer.
The tracker stores the maximum observed count and total for every unique stage,
then sums those values for the run-wide command output. A stage without a valid
pointer is not added, preserving the command's existing map-index behavior.
All chest state is reset when `LiveRunTracker` detects a new run.

### Sampling Frequency

The exact factual counters are persistent totals and remain in the existing
full player-stat refresh every `10,000 ms`.

Expected Key procs require the historical Key chance at the time each normal
chest is opened. The existing `250 ms` Chaos Tome loop therefore performs two
additional narrow reads while `!chests` is enabled:

```text
RunStats.stats["chestsBought"]
current Key stack count
```

When `chestsBought` increases by `delta`, the tracker adds:

```text
expected += delta * sampled_key_chance
key_chance = (0.10 * keys) / (1.0 + 0.10 * keys)
```

If the Key stack changed inside the same sampling window, the sampled chance is
the mean of the previous and current chances. This avoids systematically
assuming that the Key pickup happened either before or after every chest in an
otherwise ambiguous `250 ms` window.

No `25 ms` interactable monitor is required.

Expected tracking is shared run telemetry. It is shown by `!chests`, displayed
in the sixth Stats card in Live Stats and Recordings, and serialized into
recording snapshots together with the per-stage chest breakdown. The two narrow
`250 ms` reads therefore run whenever live run tracking is active, while the UI
card itself refreshes on the regular 10-second player-stat update.

### Advantages

- No high-frequency `25 ms` polling is required.
- No dependency on chest UI or animation lifetime.
- No dependency on the player hovering the chest long enough to capture an
  interactable pointer.
- Uses two counters maintained directly by game logic.
- The dictionary path is already implemented and tested for the `kills` key.
- Produces exact paid, Key-proc, and inherently free totals by subtraction.
- Merchant spending and simultaneous gold income cannot affect classification.
- Expected procs account for Key-stack changes during the run instead of
  applying the final chance retroactively to every chest.

### Limitations and Open Questions

1. The TypeInfo offsets and field layouts are build-specific and must be
   revalidated after game updates.
2. Special chest types such as `Corrupt`, `FreeCrypt`, and `Ghost` were not
   individually validated.
3. A missing `chestsBought` entry is treated as zero before the first normal
   opening. Invalid pointer chains still fail the whole read rather than
   publishing a false snapshot.
4. If tracking begins after normal chests have already been opened, historical
   Expected cannot be reconstructed and the command reports `Expected: --`
   until the next run.
5. A Key pickup and chest opening inside the same `250 ms` interval have unknown
   ordering. Averaging the before/after chances minimizes bias but cannot recover
   the exact event order.

## Option 4: `DetectInteractables.currentInteractable`

### Status

This was the recommended approach before the `RunStats.chestsBought` discovery.
It remains the strongest fallback and an excellent diagnostic source. It reads
the actual interactable selected by the player before interaction and therefore
does not depend on chest-opening animation or UI lifetime.

### Memory Path

The `MyPlayer` TypeInfo address for the tested build is:

```text
GameAssembly.dll + 0x2F620F8  -> MyPlayer TypeInfo
  -> +0xB8                    -> static fields
  -> +0x8                     -> MyPlayer.Instance
  -> +0x48                    -> MyPlayer.playerInput
  -> +0x20                    -> PlayerInput.detectInteractables
  -> +0x28                    -> DetectInteractables.currentInteractable
```

For a chest, continue with:

```text
currentInteractable
  -> object class name must be "InteractableChest"
  -> +0x58 -> EChest chestType
```

The class-name validation path used during testing was:

```text
object +0x0 -> Il2CppClass*
class  +0x10 -> ASCII class-name pointer
```

Class validation prevents interpreting another `BaseInteractable` subclass's
field at `+0x58` as an `EChest` value.

### Live Validation

On a newly generated map, while the player stood inside the interaction range
of an inherently free chest:

```text
currentInteractable class = InteractableChest
currentInteractable + 0x58 = 2 (EChest.Free)
ChestWindowUi + 0x78 = 0
```

The value remained stable across repeated reads before the chest was opened.
This directly confirmed that the interactable path works while the UI path does
not.

### Recommended Sampling Model

Use three independent frequencies:

| Interval | Work |
| ---: | --- |
| `25 ms` | Read only `currentInteractable`, validate its class, and cache `chestType` plus object pointer and timestamp. |
| `250 ms` | Read chest count and gold, detect the opening, and consume the cached chest candidate. |
| `10,000 ms` | Existing full player/map-stat refresh and key-count synchronization. |

The `25 ms` loop is intentionally lightweight. It performs only a short pointer
chain, a class-name check, and one integer read. It does not scan collections or
enumerate all map chests.

### Why `25 ms`

Live sampling produced the following results:

- At `250 ms`, the selected chest type was captured for only `5/10` openings.
- At `50 ms`, it was captured for `19/20` openings.
- At `25 ms`, it was captured for `15/15` openings observed after the monitor
  started.

The missed event at `50 ms` demonstrates that the interaction target can exist
for less than one polling period during fast movement and immediate interaction.

### Candidate State

Suggested tracker state:

```python
@dataclass(frozen=True)
class ChestInteractionCandidate:
    object_ptr: int
    chest_type: int
    observed_at: float
```

Update it whenever the current interactable is a valid `InteractableChest`.
Do not clear it immediately when `currentInteractable` becomes null; interaction
itself may clear the target before the `250 ms` chest-count sample observes the
opening.

Expire candidates after a short window. Live tests used `3 seconds`, but a
tighter production value such as `1-2 seconds` should be evaluated. The cache
must also be cleared on:

- run reset;
- stage transition;
- chest-count rollback;
- `MyPlayer.Instance` replacement;
- successful consumption by a single chest-opening event.

### Classification Algorithm

```text
every 25 ms:
    resolve currentInteractable
    if class is InteractableChest:
        cache pointer, chestType, and timestamp

every 250 ms:
    read opened chest count and gold

    if opened_count == previous_count + 1:
        candidate = recent cached candidate

        if candidate.chestType in {Free, FreeCrypt}:
            increment inherent-free counter

        elif candidate.chestType == Normal:
            if gold_after < gold_before:
                increment paid counter
            elif gold_after >= gold_before:
                increment Key-proc counter
            else:
                increment unknown counter

        else:
            increment unknown/other counter

        consume candidate

    elif opened_count > previous_count + 1:
        synchronize count without classifying individual openings
```

### Important Race: Candidate Replacement

The player may briefly hover a second chest before the `250 ms` count sample
processes the first opening. A single "latest candidate" can therefore be
replaced too early.

For the most robust implementation, keep a small ordered queue of recently seen
unique chest pointers rather than only one value:

```text
deque(maxlen=4): [candidate A, candidate B, ...]
```

When the chest count increases, consume the oldest recent candidate that has
not already been consumed. Deduplicate repeated observations by object pointer.
This also handles two rapidly opened adjacent chests more safely.

### Gold-Delta Limitation Still Applies

The interactable path perfectly solves the distinction between a normal chest
and an inherently free chest. It does not make gold-delta classification atomic.

A normal paid chest can still be misclassified as a Key proc if unrelated gold
income arrives in the same `250 ms` sample and offsets the chest cost. Therefore:

- `chestType in {2, 3}` is a strong inherent-free classification;
- `chestType == 0` with a visible gold decrease is a strong paid classification;
- `chestType == 0` without a visible decrease is the best available read-only
  Key-proc inference, but not a mathematical guarantee.

## Recommended Production Design

1. Read `chestsBought` through the reusable `RunStats.stats` dictionary reader.
2. Read `MoneyUtility.chestsPurchased` from its static fields.
3. Refresh both counters with the map chest total every 10 seconds.
4. Publish a structured `ChestStatsSnapshot` from `LiveRunTracker` while
   preserving the legacy tuple getter for compatibility.
5. Reject snapshots that violate the counter invariants and keep the previous
   valid values until the next refresh.
6. Accumulate Expected Key procs in the existing `250 ms` loop using the Key
   chance observed around each increase of `chestsBought`.
7. Format the Twitch response with separate paid, Key-proc, expected, and free
   totals:

```text
Chests: {stages} | Total: {opened}/{total} | Paid: {paid} |
Key Procs: {procs}/{normal} ({proc_rate}) | Expected: {expected} |
Free Chests: {free} | Keys: {keys} ({chance})
```

8. Keep `currentInteractable` as a diagnostic fallback only; it is not required
   by the production command.

## Final Recommendation

Use Option 3 as the production implementation. It was validated across paid
opens, Key procs, inherently free chests, merchant spending, and a stage
transition. Keep Option 4 as a diagnostic fallback. Do not rely on Option 2
while skip animation is enabled.

The combined production rule is:

```text
paid        = MoneyUtility.chestsPurchased
key procs   = RunStats.chestsBought - MoneyUtility.chestsPurchased
free chests = tracked map openings - RunStats.chestsBought
```
