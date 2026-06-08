# Part 3: Passive Item Inventory Recovery Guide

## Overview
This component tracks the player's current passive item inventory (e.g. Wrench, Clover, Oats) and their stack counts. It uses a primary dictionary path through `inventoryContainer`, falling back to `playerInventory.ItemInventory` if the primary dictionary is empty. It parses class names to build display names.

- **Target Files**:
  - Code: [player_stats.py](file:///f:/Python/MegabonkReroll/player_stats.py)
  - Unit Tests: [tests/test_player_stats.py](file:///f:/Python/MegabonkReroll/tests/test_player_stats.py)

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

---

## Code Reference
Offsets are defined in `PlayerStatsClient` in `player_stats.py`:
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
    # ...
```

---

## Verification Steps
1. Run pytest:
   ```powershell
   pytest tests/test_player_stats.py -k "passive"
   ```
2. Verify in the overlay interface under "Live Stats" that picked up items are shown with correct counts (e.g., `Wrench x2`).
