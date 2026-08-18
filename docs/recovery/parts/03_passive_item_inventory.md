# Part 3: Passive Item Inventory Recovery Guide

## Overview
This component tracks the player's current passive item inventory (e.g. Wrench, Clover, Oats) and their stack counts. It uses a primary dictionary path through `inventoryContainer`, falling back to `playerInventory.ItemInventory` if the primary dictionary is empty. It parses class names to build display names.

- **Target Files**:
  - Code: `src/infra/memory/player_stats_client.py`
  - Unit Tests: `src/tests/test_player_stats.py`

---

## Memory Chain Diagrams

### 1. Primary Path (Inventory Container)
```
owner_stats (Resolved from PlayerStatsNew, see Part 2)
  -> +0xA0 (INVENTORY_CONTAINER_OFFSET) -> [Inventory Container Pointer]
    -> +0x50 (PASSIVE_ITEM_DICT_OFFSET)  -> [Passive Item Dictionary Pointer]
```

### 2. Fallback Path (Player Inventory)
```
owner_stats
  -> +0x28 (PLAYER_INVENTORY_OFFSET)          -> [Player Inventory Pointer]
    -> +0x20 (ITEM_INVENTORY_OFFSET)            -> [Item Inventory Pointer]
      -> +0x10 (ITEM_INVENTORY_ITEMS_DICT_OFFSET) -> [Passive Item Dictionary Pointer]
```

### 3. Decoding the Passive Items Dictionary
```
passive_item_dict
  -> +0x18 (DICT_ENTRIES_OFFSET) -> [Entries Memory Base Pointer]
  -> +0x20 (DICT_COUNT_OFFSET)   -> int (count of entries)

Each Dictionary Entry:
Entries + 0x20 (DICT_ENTRY_START_OFFSET) + (Index * 0x18 (DICT_ENTRY_SIZE))
  -> +0x10 (DICT_ENTRY_VALUE_OFFSET) -> [Passive Item Value Object Pointer]
    -> +0x0 (ITEM_CLASS_META_OFFSET)     -> [Class Metadata Pointer]
      -> +0x10 (CLASS_META_NAME_PTR_OFFSET) -> [ASCII String Pointer] (e.g., "ItemWrench")
    -> +0x18 (ITEM_STACK_COUNT_OFFSET)   -> int (stack count)
```

### 4. Either path can resolve a live pointer to a drained dictionary

**Neither path is authoritative.** A non-null dictionary pointer does not mean a
live dictionary: both routes can hand back an emptied one, and which of them
does depends on run state. Measured live on 2026-08-03, mid-run, with 25 items
held:

```text
owner_stats +0xA0 -> +0x50            = 0x...EF750   count=0   version=0   entries=0x0
owner_stats +0x28 -> +0x20 -> +0x10   = 0x...57AE0   count=25  version=25
```

The Overview above already states the rule correctly -- fall back "if the
primary dictionary is **empty**". The failure was an implementation that
diverged from it: `_resolve_preferred_passive_item_dict` returned the first
*non-null* pointer, so it selected the drained dictionary and never tried the
fallback. `get_passive_items` was unaffected because it falls through on an
empty *result*, which is why the inventory kept working while other consumers
silently did not.

**This is not hypothetical.** In that state `get_expected_chest_inputs` reported
`key_count=0` for a player holding `Key x1` -- `_get_cached_key_count` resolves
the dictionary and then searches it by name, so a drained dictionary reads as
"the player owns none of it", with nothing raising anywhere.

Rules for any new consumer:

- Select the candidate that **has entries** (`DICT_ENTRIES_OFFSET` non-null *and*
  `DICT_COUNT_OFFSET > 0`), not the first non-null pointer.
- When neither has entries, that is a genuinely empty inventory, not a failure.
- Any per-dictionary cache must be validated against the quadruple (dictionary
  pointer, entries pointer, count, version) so a switch between the two routes
  rebuilds it. A cached address from one dictionary is a live pointer into an
  object that is no longer the one being read.

The observed trigger was **restarting a run without restarting the game**. A
session that plays one run from a fresh launch appears never to enter this
state, which matches the recordings: `950k.jsonl` tracks `keys_count` correctly
from 1 to 7 across 670 snapshots holding a Key. How reliably a run restart
reproduces it is not established -- only one live observation exists.

Covered by `src/tests/test_key_count_drained_dictionary.py`.

### 5. Item value objects: field layouts are per class

Beyond `ITEM_CLASS_META_OFFSET` and `ITEM_STACK_COUNT_OFFSET`, which are
`ItemBase` and therefore common, **every field is specific to the item's own
class**. Reading a field off the wrong class does not raise; it returns a
well-formed float.

A live sweep of all 27 held items for floats tracking the game clock produced
nine hits. **One was a real cooldown mark.** Seven were sub-second proc timers
-- `ItemSpikyShield` and `ItemBeefyRing` keep theirs at `0x3C`, exactly where
`ItemBobLantern` keeps `cooldown` -- one (`ItemPhantomShroud 0x5C`,
`speedResetAtTime`) was a mark of the *last* trigger and therefore always in the
past, and one was not a declared field at all: `ItemUnstableTransfusion`
declares two floats ending at `0x38`, so the "mark" read at `0x40` was memory
past the end of its layout.

So: confirm a class in `dump.cs` before reading a byte of it, key any offset
table by **item enum id** rather than by name, and verify the class metadata
name before trusting the offsets.

Note the two naming spaces do not agree. `ITEM_ENUM_NAMES_BY_ID[85]` is
`BobsLantern` while the IL2CPP class is `ItemBobLantern`; `74` is `GloveBlood`
against `ItemGlovesBlood`. A lookup keyed on a name built from the enum table
misses silently.

`tools/scan_timed_items.py` parses `dump.cs` and lists every `ItemBase`
subclass owning a timing-shaped float. Of 86 subclasses, 33 have one and 30
carry an absolute mark, but almost all are sub-second tick timers -- a name says
what a field *is*, never whether its period is worth displaying.

---

## Reversing Walkthrough (Cheat Engine & IL2CPP)

### 1. Locating Offsets using IL2CPP Dump
Search for these classes in `dump.cs`:
- **`InventoryContainer`**:
  - Find fields containing dictionaries of items.
  - E.g., check `passiveItems` (offset `0x50`).
- **`ItemInventory`**:
  - Check fields for item dictionaries (offset `0x10`).
- **Passive Item Value Class** (e.g. `PassiveItem` / `ItemSlot` / `InventoryItem`):
  - Find fields like `stackCount` or `count` (offset `0x18`).
  - Note how it references the item configuration or class metadata name.

### 2. Cheat Engine Live Verification
- **Trace Passive Items**:
  - Buy or pick up a passive item in the game (e.g. Clover).
  - Walk the pointer from `owner_stats` to the passive item dictionary.
  - Verify that the count of entries increases.
  - Locate the entries array in memory and view the ASCII string pointed to by `class_meta + 0x10`. It should match `"ItemClover"`.
  - Verify that the integer count at `item_value + 0x18` changes as you pick up duplicate items.
  - If the dictionary layout changes, verify the standard `.NET` dictionary offsets for keys and values.

### 5. Timed Passive Items & Cooldown Tracking (Bob's Light)

Timed passive items (such as Bob's Light) store active trigger countdowns inside their item value instances.
The cooldown calculation requires reading `nextTriggerTime` from the item instance and pairing it synchronously with `MyTime.time` from the same memory pass:

```
item_value (from Dictionary Entry Value Object Pointer)
  -> +0x0  (ITEM_CLASS_META_OFFSET)     -> [Class Metadata Pointer] ("ItemBobLantern")
  -> +0x18 (ITEM_STACK_COUNT_OFFSET)   -> int (stack count)
  -> +0x3C (cooldown_offset)           -> float (base cooldown duration in seconds)
  -> +0x40 (next_trigger_offset)       -> float (absolute next trigger timestamp on game clock)

MyTime (paired clock reference)
GameAssembly.dll + RUN_TIMER_TYPE_INFO_OFFSET (0x02F62398)
  -> [Class Pointer] -> +0xB8 -> static_fields
    -> +0x04 (MY_TIME_TIME_OFFSET)     -> float (current game time)
```

At rendering time, the in-game overlay calculates:
`remaining_seconds = max(0.0, next_trigger_time - my_time)`
Freezing game clock (pausing) automatically freezes the displayed countdown.

---

## Code Reference
Offsets are defined in `PlayerStatsClient` in `src/infra/memory/player_stats_client.py`:
```python
class PlayerStatsClient:
    INVENTORY_CONTAINER_OFFSET = 0xA0
    PASSIVE_ITEM_DICT_OFFSET = 0x50
    PLAYER_INVENTORY_OFFSET = 0x28
    ITEM_INVENTORY_OFFSET = 0x20
    ITEM_INVENTORY_ITEMS_DICT_OFFSET = 0x10
    
    DICT_ENTRIES_OFFSET = 0x18
    DICT_COUNT_OFFSET = 0x20
    DICT_ENTRY_START_OFFSET = 0x20
    DICT_ENTRY_SIZE = 0x18
    DICT_ENTRY_VALUE_OFFSET = 0x10
    
    ITEM_CLASS_META_OFFSET = 0x0
    ITEM_STACK_COUNT_OFFSET = 0x18
    CLASS_META_NAME_PTR_OFFSET = 0x10

    MY_TIME_TIME_OFFSET = 0x04
    # ItemCooldownLayout for Bob's Light (ItemBobLantern):
    # cooldown_offset = 0x3C, next_trigger_offset = 0x40
```

---

## Verification Steps
1. Run tests:
   ```powershell
   .\run_tests.bat src.tests.test_player_stats
   .\run_tests.bat src.tests.test_item_cooldowns
   .\run_tests.bat src.tests.test_item_cooldown_overlay
   ```
2. Verify in the overlay interface under "Live Stats" that picked up items are shown with correct counts (e.g., `Wrench x2`) and the Item Cooldowns widget shows the active countdown for Bob's Light.
