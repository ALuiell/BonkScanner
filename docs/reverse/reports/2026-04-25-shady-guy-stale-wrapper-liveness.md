# Shady Guy Stale Wrapper Liveness

Date: 2026-04-25

## Goal

Confirm whether destroyed `InteractableShadyGuy` managed wrappers remain in the heap with stale `items` and `prices` after Unity native liveness is lost, and determine whether `m_CachedPtr != 0` is strong enough to use as the current/live vendor filter.

## Sources

- Conversation handoff for the targeted destruction-to-respawn repro
- [docs/memory-and-hooks-reference.md](C:\Users\Skadi\Documents\Utilities\BonkScanner\docs\memory-and-hooks-reference.md)
- [game_data.py](C:\Users\Skadi\Documents\Utilities\BonkScanner\game_data.py)
- [docs/interactable-reverse/current-hook-reverse-reference-2026-04-24.md](C:\Users\Skadi\Documents\Utilities\BonkScanner\docs\interactable-reverse\current-hook-reverse-reference-2026-04-24.md)
- [Dump/dump.cs](C:\Users\Skadi\Documents\Utilities\BonkScanner\Dump\dump.cs)
- Live Cheat Engine MCP probe against attached `Megabonk` process `PID 31120`

## Findings

| Item | Status | Evidence | Notes |
| --- | --- | --- | --- |
| `InteractableShadyGuy.items` is at `+0x98` and `prices` is at `+0xA0` | confirmed | `Dump/dump.cs` field layout | Safe managed-field offsets from object base |
| Unity `Object.m_CachedPtr` is at `+0x10` | confirmed | `Dump/dump.cs` `UnityEngine.Object` field layout | Best native-liveness signal tested in this pass |
| Current reader in `game_data.py` heap-scans `InteractableShadyGuy` wrappers without checking `m_CachedPtr` | confirmed | `GameDataClient.get_shady_guy_vendor_items()` and `_read_shady_guy_vendor_items()` | Existing filter only checks `monitor == 0`, pointer presence, and list shape |
| Current live session returns `4` Shady Guy vendors through the existing reader | confirmed | Live call to `GameDataClient.get_shady_guy_vendor_items()` | This is the inflated count in the sampled run |
| The same sampled set drops from `4` to `3` when filtered by `vendor + 0x10 != 0` | confirmed | Live re-check of returned vendor set with `m_CachedPtr` gate | Direct evidence that one returned wrapper is stale/destroyed |
| Session-only wrapper `0x1ADE4F39F00` has `m_CachedPtr == 0` while still decoding `items.Count == 3` and `prices.Count == 3` | confirmed | Live heap candidate walk | Retained offers were `CursedDoll(38)`, `MoldyCheese(16)`, `Oats(28)` |
| Destroyed Shady Guy managed wrappers can survive in heap with old offers after native object death | strong | Live stale-wrapper observation above | Strongly supported by direct observation even though the same address was not watched across a full destroy/respan transition in this pass |
| Historical `6 vs 3` inflation is not reproduced by this run | open | Current run reproduced `4 vs 3` | Root cause appears the same, but the exact earlier count was not recreated |
| `m_CachedPtr != 0` is strong enough to ship as the primary live/current split for heap-scanned Shady Guy wrappers | strong | Live `4 -> 3` correction plus stale object retaining valid offers | Keep existing structural validation on top of the liveness gate |

## Stable Rules

| Target | Rule / Path | Stability | Risk |
| --- | --- | --- | --- |
| `InteractableShadyGuy` type info | `GameAssembly.dll + 0x2FB5928` -> dereference to class pointer | medium | Module-relative offset is stable per build; resolved class pointer is session-only |
| Unity native liveness | `vendor + 0x10` -> `m_CachedPtr` must be nonzero | medium-high | Based on Unity object layout and direct live repro; should be revalidated after major game updates |
| Vendor item list | `vendor + 0x98` -> `List<ItemData>` | high | Direct managed field on wrapper |
| Vendor price list | `vendor + 0xA0` -> `List<int>` | high | Direct managed field on wrapper |
| List count | `list + 0x18` | high | Standard IL2CPP `List<T>` layout in this build |
| List backing array | `list + 0x10` then elements at `array + 0x20 + index * stride` | high | Standard IL2CPP `List<T>` / array layout in this build |
| Existing shape checks to keep | `monitor == 0`, `items != 0`, `prices != 0`, `prices.Count == items.Count`, `items.Count > 0` | medium-high | These checks reject metadata/garbage hits that still match the raw class-pointer scan |

## Implementation Handoff

| Data To Read | Start Point | Path / Offset Rule | Expected Output | Confidence | Notes |
| --- | --- | --- | --- | --- | --- |
| Candidate Shady Guy wrappers | `InteractableShadyGuy` class pointer | Heap-scan object layout matching `klass` and `monitor == 0` | Candidate wrapper pointers | confirmed | Candidate heap addresses are session-only |
| Live/current vendor filter | Candidate wrapper pointer | Require `vendor + 0x10 != 0` before accepting `items/prices` | Live vendor set only | strong | This is the main result of this report |
| Vendor offers | Live wrapper pointer | `vendor + 0x98` -> `List<ItemData>`, `vendor + 0xA0` -> `List<int>`, require `items.Count > 0` and `prices.Count == items.Count` | Offer item IDs and matching prices | confirmed | Existing reader already decodes this correctly for both live and stale wrappers |
| Session-only stale proof sample | `0x1ADE4F39F00` | `m_CachedPtr == 0`, `items.Count == 3`, `prices.Count == 3` | Example stale wrapper retaining old offers | confirmed | Session-only evidence; do not hardcode the address |

## Open Questions

- The same wrapper address was not captured through an explicit `before destroy -> after destroy -> after new spawn` lifecycle in this pass.
- This run reproduced `4 vs 3`, not the earlier inferred `6 vs 3`, so the magnitude of inflation remains session-dependent.

## Next Useful Step

Implement the Shady Guy reader update so heap-scanned candidates must satisfy `m_CachedPtr != 0` before `items/prices` are accepted, then re-run one live scan to confirm the exported count matches the visible vendor count.
