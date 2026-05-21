# Megabonk Item Inventory Stable Path Handoff

Date: 2026-05-11

## Goal

This note replaces the earlier session-bound inventory notes with the currently best confirmed **stable path to passive item inventory between game sessions**.

Scope of this pass:

- confirm the stable root chain again from `GameAssembly.dll`
- discard stale per-session live addresses as the primary source of truth
- identify the current best stable route to the passive item dictionary
- confirm the route across multiple fresh game sessions
- confirm where per-item stack/count lives

This handoff is intentionally focused on **passive items only**.

## Final Conclusion

The best current stable path to passive item inventory is:

1. `GameAssembly.dll + 0x2F6A4B8`
2. dereference -> `class_ptr`
3. `class_ptr + 0xB8` -> `static_fields`
4. dereference -> `root`
5. `root + 0x40` -> `PlayerStatsNew`
6. `PlayerStatsNew + 0xA0` -> inventory-related container
7. `that + 0x50` -> **passive item dictionary**

Inside the dictionary:

- dictionary `count` is at `+0x20`
- dictionary `entries` pointer is at `+0x18`
- each entry is `0x18` bytes
- entry `value` is at `entry + 0x10`
- **item stack/count** is at `entry.value + 0x18`
- item **class pointer** is at `entry.value + 0x0`

## Update 2026-05-21: PlayerInventory ItemInventory Fallback

Live testing with a modded/cheat-spawned run showed that the older
`PlayerStatsNew + 0xA0 -> +0x50` passive dictionary can be empty even while the
HUD visibly contains passive items. In that run, the active items were found in
the main `PlayerInventory` object instead:

1. resolve `PlayerStatsNew` from the same stable root
2. `PlayerStatsNew + 0x28` -> `PlayerInventory`
3. `PlayerInventory + 0x20` -> `ItemInventory`
4. `ItemInventory + 0x10` -> item dictionary

The dictionary layout and item object layout matched the existing reader:

- dictionary `count` is at `+0x20`
- dictionary `entries` pointer is at `+0x18`
- each entry is `0x18` bytes
- entry `value` is at `entry + 0x10`
- `entry.value + 0x18` is the stack/count
- `entry.value + 0x0 -> class_meta + 0x10` gives the ASCII item class name

Observed live state:

- old path: `PlayerStatsNew + 0xA0 -> +0x50` resolved to `0x0`
- new fallback: `PlayerInventory + 0x20 -> ItemInventory + 0x10`
  resolved to a dictionary with `count = 19`
- decoded examples matched the HUD:
  - `ItemBonker -> Bonker x99`
  - `ItemChonkplate -> Chonkplate x21`
  - `ItemClover -> Clover x199`
  - `ItemWrench -> Wrench x1`

Implementation guidance:

- Prefer the older `PlayerStatsNew + 0xA0 -> +0x50` path first for backward
  compatibility with previously verified sessions.
- If that dictionary is missing or decodes no items, fall back to
  `PlayerStatsNew + 0x28 -> PlayerInventory + 0x20 -> ItemInventory + 0x10`.
- Avoid broad heap scans; this fallback stays rooted in the same live
  `PlayerStatsNew` object used for weapons and player level.

## Stable Root Path

Confirmed stable root:

1. `GameAssembly.dll + 0x2F6A4B8`
2. dereference -> `class_ptr`
3. `class_ptr + 0xB8` -> `static_fields`
4. dereference -> `root`
5. `root + 0x40` -> `PlayerStatsNew`

This part remained valid while starting new runs/sessions.  
The live addresses changed, but the chain itself stayed correct.

## Passive Item Path

Current best passive item path from the stable root:

1. resolve `PlayerStatsNew`
2. `PlayerStatsNew + 0xA0` -> inventory-related object
3. `that + 0x50` -> passive item dictionary

Dictionary layout confirmed from live memory:

- `dict + 0x18` -> entries array
- `dict + 0x20` -> count

Entry layout:

- `entries + 0x20 + index * 0x18` -> entry
- `entry + 0x08` -> key
- `entry + 0x10` -> value object

Passive item object layout:

- `item_value + 0x18` -> item count / stack size

Name decoding:

1. read `item_value + 0x0` -> class metadata pointer
2. from the class metadata object:
   - `class_meta + 0x10` -> pointer to ASCII class name
   - `class_meta + 0x18` -> pointer to ASCII namespace

Observed example:

- class name: `ItemWrench`
- namespace: `Assets.Scripts.Inventory__Items__Pickups.Items.ItemImplementation`

For implementation, the class name is currently the cleanest source of truth for item identity.

## Confirmation Across Sessions

### Session A

State:

- one item picked up

Resolved addresses:

- `root` = `0x11EBE626750`
- `PlayerStatsNew` = `0x15FC86C99C0`
- `PlayerStatsNew + 0xA0` = `0x15FC84776A0`
- `+0x50` dictionary = `0x15FC86C9DE0`

Dictionary state:

- `count = 1`
- row:
  - `key = 0x23`
  - `value = 0x15FC6FA8640`
  - `value + 0x18 = 1`

### Session A after second item

Same path, same resolved dictionary object for that session:

- dictionary = `0x15FC86C9DE0`

Dictionary state:

- `count = 2`
- rows:
  - `key = 0x23`, `count = 1`
  - `key = 0x0D`, `count = 1`

This confirmed the path reacts correctly as items are added.

### Session B

State:

- fresh new game session
- one item picked up

Resolved addresses:

- `root` = `0x15FC79513F0`
- `PlayerStatsNew` = `0x11EBE2F0C60`
- `PlayerStatsNew + 0xA0` = `0x11EBE0A0BE0`
- `+0x50` dictionary = `0x11EBE29E0C0`

Dictionary state:

- `count = 1`
- row:
  - `key = 0x4D`
  - `value = `0x15FC7AC9FC0`
  - `value + 0x18 = 1`
  - `value + 0x0` -> class metadata
  - `class_meta + 0x10` -> `ItemWrench`
  - `class_meta + 0x18` -> `Assets.Scripts.Inventory__Items__Pickups.Items.ItemImplementation`

This confirmed the **same path works across a new session even though all live addresses changed**.

## What Was Rejected

The older route documented earlier in the day used per-session live objects such as:

- `PlayerInventory = 0x15FC7B2FE60`
- `ItemInventory = 0x15FC6D91C80`
- `ItemInventory + 0x18 = 0x11EBDC2C8A0`

That route was useful inside one live run, but it did **not** hold across new sessions:

- some old objects remained readable but stale
- some counts looked plausible while entries were empty or garbage
- some addresses became zeroed

Therefore these older live addresses should be treated as **historical session artifacts only**, not as the implementation path.

## Implementation Shape

Recommended reader flow:

1. resolve `PlayerStatsNew` from the stable `GameAssembly.dll + 0x2F6A4B8` chain
2. read pointer at `PlayerStatsNew + 0xA0`
3. read pointer at `that + 0x50`
4. if missing or empty, read fallback:
   - `PlayerStatsNew + 0x28` -> `PlayerInventory`
   - `PlayerInventory + 0x20` -> `ItemInventory`
   - `ItemInventory + 0x10` -> item dictionary
5. treat the resolved object as the passive item dictionary
6. read:
   - `entries = dict + 0x18`
   - `count = dict + 0x20`
7. for each entry:
   - read `value` from `entry + 0x10`
   - read `item_count` from `value + 0x18`
   - read `class_meta` from `value + 0x0`
   - read ASCII class name from `[class_meta + 0x10]`
   - optionally strip the `Item` prefix for UI display

## Best Current Source Of Truth

Use this path:

- `GameAssembly.dll + 0x2F6A4B8`
- deref
- `+0xB8`
- deref
- `+0x40`
- `+0xA0`
- `+0x50`

And for each item:

- `entry.value + 0x18` = count
- `entry.value + 0x0` = class metadata pointer
- `[class_meta + 0x10]` = ASCII class name
- `[class_meta + 0x18]` = ASCII namespace

## Confidence

Current confidence:

- stable root path to `PlayerStatsNew`: **high**
- `PlayerStatsNew + 0xA0 -> +0x50` as passive item dictionary: **medium-high**
- `PlayerStatsNew + 0x28 -> PlayerInventory + 0x20 -> ItemInventory + 0x10`
  as runtime item dictionary fallback: **high**
- `item_value + 0x18` as item count: **high**
- `item_value + 0x0 -> class_meta + 0x10` as item name source: **high**

The current implementation should use both rooted paths: old passive container
first, then the `PlayerInventory.ItemInventory` fallback.
