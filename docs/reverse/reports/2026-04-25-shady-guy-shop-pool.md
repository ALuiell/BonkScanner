# Shady Guy Shop Pool

Date: 2026-04-25

## Goal

Determine how to read the item offers for all `InteractableShadyGuy` vendors on a generated map, and preserve both the stable extraction rules and one confirmed live-session sample.

## Sources

- Current conversation handoff and live Cheat Engine MCP probes against the attached game process
- [Dump/dump.cs](C:\Users\Skadi\Documents\Utilities\BonkScanner\Dump\dump.cs)
- [Dump/script.json](C:\Users\Skadi\Documents\Utilities\BonkScanner\Dump\script.json)

## Findings

| Item | Status | Evidence | Notes |
| --- | --- | --- | --- |
| `InteractableShadyGuy` fields are `rarity +0x90`, `items +0x98`, `prices +0xA0`, `pricesMultipliers +0xA8`, `done +0xB0` | confirmed | `Dump/dump.cs` class layout | Safe field offsets from object base |
| `InteractableShadyGuy.FindItems` writes the chosen `List<ItemData>` to `this + 0x98` | confirmed | `FindItems` disassembly plus field layout | This is the direct read point for current vendor offers |
| `InventoryUtility.GetRandomItemsShadyGuy(EItemRarity)` exists at RVA `0x420960` and is called from `FindItems` | confirmed | `Dump/dump.cs`, `Dump/script.json`, disassembly | Static generation entrypoint |
| `RunUnlockables.availableItems` is `Dictionary<EItemRarity, List<ItemData>>` | confirmed | `Dump/dump.cs` static field list and live dictionary walk | Source pool used for Shady Guy generation |
| `ItemData.eItem` is at `+0x54`, `ItemData.rarity` is at `+0x60` | confirmed | `Dump/dump.cs` class layout and live reads | `eItem` is the stable numeric item ID |
| `EItemRarity` enum is `0 Common`, `1 Rare`, `2 Epic`, `3 Legendary`, `4 Corrupted`, `5 Quest` | confirmed | `Dump/dump.cs` enum | Stable for decoding vendor/item rarity |
| Current generated map had 4 live `InteractableShadyGuy` objects with non-empty `items` lists | confirmed | Live heap scan and object walk | Session-only object addresses listed below |
| Each live vendor in the sampled session had `items.Count == 3` | confirmed | Live `List<ItemData>` reads | Matches expected Shady Guy offer count in this session |
| `InteractableShadyGuy.currentlyInteracting` is not reliable for passive map scan | rejected | Live static read returned `null` while vendors existed on map | Useful only during active interaction |
| Naive qword scans against the class pointer can hit class metadata / method tables instead of instances | rejected | Candidate `0x138826A5150` decoded to method-address-like entries | Filter real objects by `monitor == 0`, non-null `items`, non-null `prices`, and valid list count |

## Stable Rules

| Target | Rule / Path | Stability | Risk |
| --- | --- | --- | --- |
| `InteractableShadyGuy` type info | `GameAssembly.dll + 0x2FB5928` -> dereference to class pointer | Medium | Module-relative is stable across one build; class pointer value itself is session-only |
| All generated vendors on current map | Heap scan for object layout starting with `klass` and `monitor == 0`; then validate `obj+0x98`, `obj+0xA0`, and `List.Count > 0` | Medium | Heap object addresses are session-only; filter is safer than `currentlyInteracting` |
| Vendor item list | `vendor + 0x98` -> `List<ItemData>` | High | Direct field on live object |
| `List<ItemData>` walk | `list + 0x10` -> backing array, `list + 0x18` -> count, elements from `array + 0x20 + i*8` | High | Standard IL2CPP `List<T>` / array layout in this build |
| Item ID | `ItemData + 0x54` -> `EItem` numeric ID | High | Best stable implementation output if localization is not needed |
| Item rarity | `ItemData + 0x60` -> `EItemRarity` | High | Useful for validation/debug output |
| Pool source by rarity | `RunUnlockables.availableItems` -> `Dictionary<EItemRarity, List<ItemData>>` | Medium | Good fallback/debug source, but generated vendors should still be read from `vendor.items` |

## Implementation Handoff

| Data To Read | Start Point | Path / Offset Rule | Expected Output | Confidence | Notes |
| --- | --- | --- | --- | --- | --- |
| All Shady Guy vendors on current map | `InteractableShadyGuy` class pointer from `GameAssembly.dll + 0x2FB5928` | Scan heap for candidate objects with `klass`, `monitor == 0`, `obj+0x98 != 0`, `obj+0xA0 != 0`, `List.Count > 0` | Set of live vendor object pointers | strong | Heap addresses are session-only; filtering is required |
| Offered items for one vendor | Live `InteractableShadyGuy*` | `vendor + 0x98` -> list, `list + 0x10` -> array, `list + 0x18` -> count, `array + 0x20 + i*8` -> `ItemData*` | `ItemData*[]` for that vendor | confirmed | In sampled session each vendor had 3 items |
| Stable item identifier | `ItemData*` | `item + 0x54` | `EItem` numeric ID | confirmed | Best format for later matching or localization |
| Human-readable internal label | `EItem` numeric ID | Map through dumped enum table in `Dump/dump.cs` | Names such as `GymSauce`, `Medkit`, `Beacon` | confirmed | This is not a live memory read; it is an enum mapping from dump data |
| Debug pool source by rarity | `RunUnlockables.availableItems` | Walk `Dictionary<EItemRarity, List<ItemData>>` entries and each list as above | Item pool grouped by rarity | confirmed | Useful to compare generation source vs. chosen vendor offers |

## Session Sample

Session-only live objects observed on the generated map:

| Vendor Object | Vendor Rarity | Items List | Offers (`EItem`) |
| --- | --- | --- | --- |
| `0x13B18D29CC0` | `Common (0)` | `0x13B19A65D20` | `74 GloveBlood`, `78 Beacon`, `82 OldMask` |
| `0x13B18D29D80` | `Common (0)` | `0x13B19A611E0` | `77 Wrench`, `8 PhantomShroud`, `13 MoldyCheese` |
| `0x13B18D29E40` | `Epic (2)` | `0x13B19A615D0` | `74 GloveBlood`, `57 Kevin`, `2 SpikyShield` |
| `0x13B18D29F00` | `Common (0)` | `0x13B19A61AB0` | `6 GymSauce`, `59 Medkit`, `0 Key` |

## Open Questions

- Whether vendor discovery should ultimately use a heap scan, a hook on `FindItems`, or a stronger map-object registry path for production code.
- Whether duplicate item IDs across vendors are intended game behavior or incidental to this specific session.

## Next Useful Step

Implement a production reader that enumerates all live `InteractableShadyGuy` objects after map generation and emits `vendor_address -> [EItem IDs]`, using `vendor.items` as the primary source and the `EItem` enum dump for labeling.
