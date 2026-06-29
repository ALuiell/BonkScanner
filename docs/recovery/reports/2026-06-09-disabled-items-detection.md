## Goal

Document the live runtime memory paths and logic used to detect which items are disabled (excluded from the active pool) by the player in Megabonk, resolving the difference between static catalog assets and live run-specific item pools.

## Current Result

Status: `[Done]`

Detecting disabled items is now verified and documented.

The correct method to identify disabled items is by comparing the static global catalog against the run-specific active pool:

1. **Global Catalog**: Rooted from `DataManager.Instance.unsortedItems` (`List<ItemData>`):
   ```text
   GameAssembly.dll + 0x2F85790
   -> DataManager_TypeInfo
   -> class_ptr
   -> +0xB8 static fields
   -> static_fields + 0x8 -> DataManager Instance
   -> instance + 0x60 -> unsortedItems List
   ```

2. **Active Pool**: Rooted from `RunUnlockables.availableItems` (`Dictionary<EItemRarity, List<ItemData>>`):
   ```text
   GameAssembly.dll + 0x02F7A210
   -> RunUnlockables_TypeInfo
   -> class_ptr
   -> +0xB8 static fields
   -> static_fields + 0x10 -> availableItems Dictionary
   ```

3. **Logic**: Items present in the **Global Catalog** but missing from the **Active Pool** are either disabled by the player in the settings/lobby or excluded by game design (like unique items).

## Relevant Layout Findings

Confirmed offsets and layout details:
- `DataManager.Instance` is at `static_fields + 0x8`
- `DataManager.unsortedItems` is at `instance + 0x60`
- `RunUnlockables.availableItems` is at `static_fields + 0x10`
- `ItemData.eItem` is at `item_data_ptr + 0x54` (`EItem` enum ID)
- C# `List<T>` layout:
  - `+0x10` -> `_items` array
  - `+0x18` -> `_size` (int32)
  - Array data starts at `array_ptr + 0x20` with pointer size `0x8`
- C# `Dictionary<TKey, TValue>` layout:
  - `+0x18` -> `entries` array
  - `+0x20` -> `count` (int32)
  - Dictionary entry size: `0x18`
  - Entry key (rarity index) at `entry + 0x8`
  - Entry value (List pointer) at `entry + 0x10`

## Item Name Mapping For UI

The live memory path should only be responsible for resolving item identity:

```text
ItemData + 0x54 -> EItem enum ID
```

Do **not** call `ItemData.GetName()` or rely on a live string field for the UI
name unless a future feature explicitly needs localized game strings. The app
already has the correct item-name mapping layers:

- `src/player_stats.py`
  - `ITEM_ENUM_NAMES_BY_ID`: maps live `EItem` IDs to the known internal enum
    names, for example `33 -> SuckyMagnet`.
- `src/gui_styles.py`
  - `ITEM_RARITY_BY_NAME`: contains the canonical display names already used by
    the UI/rarity styling, for example `Sucky Magnet`, `Golden Sneakers`,
    `Forbidden Juice`.
  - This table can also be used as the known canonical-name set when converting
    enum names from PascalCase to display names.
- `docs/recovery/reports/2026-06-09-item-name-mapping.md`
  - Canonical reference for `EItem` IDs, game UI localization names, current
    BonkScanner compatibility names, rarities, colors, and legacy aliases.

Recommended UI mapping pipeline:

```text
live ItemData pointer
-> read EItem ID at +0x54
-> player_stats.ITEM_ENUM_NAMES_BY_ID[id]
-> localization key / game UI name from 2026-06-09-item-name-mapping.md
-> fallback to current BonkScanner compatibility name when needed
```

This keeps memory detection stable while reusing the program's existing naming
rules for presentation.

For the full item mapping table, see
`docs/recovery/reports/2026-06-09-item-name-mapping.md`.

## Why This Path Is Correct

Initial attempts to detect disabled items by checking `ItemData.isEnabled` (offset `0x18`) or `ItemData.inItemPool` (offset `0x50`) on objects inside `DataManager.Instance.unsortedItems` returned `True` for all standard items, even when they were disabled in the user's lobby menu.

This happens because the items in `DataManager.Instance.unsortedItems` are Unity `ScriptableObject` assets loaded from the game bundle. They function as read-only templates and their fields are not modified at runtime when the player toggles items in the lobby settings.

Instead, when a run is initialized, the game copies the unlocked and enabled items into the run-specific active dictionary: `RunUnlockables.availableItems`. Hence, comparing the global template catalog against `RunUnlockables.availableItems` is the only reliable way to retrieve the exact runtime pool of enabled/disabled items.

## Live Validation

Observed on 2026-06-09 with `megabonk.exe`:
- Global Catalog count from `DataManager.Instance.unsortedItems`: **87** items.
- Active items count in `RunUnlockables.availableItems`: **50** items.
- Resulting missing (disabled) items: **37** items.

The list of disabled items retrieved matches the user's custom settings (~42% of items disabled).

### Special Cases
- **GoldenRing (ID: 79)**: This item is a unique item that is permanently enabled in the player's progression settings. However, it always appears as "disabled" under this logic because `GoldenRing` has `inItemPool = False` hardcoded by the game design to exclude it from standard random drop tables (chests/mobs).
  BonkScanner intentionally displays it as `The One Ring`; keep `Golden Ring`
  as the canonical matching name.

## Disabled Items List (Validation Example)

The following items were detected as disabled during validation:

| ID | Enum name | UI/canonical display name |
| --- | --- | --- |
| 7 | Battery | Battery |
| 62 | BloodyCleaver | Bloody Cleaver |
| 46 | BobDead | Bob (Dead) |
| 85 | BobsLantern | Bob's Light |
| 65 | BossBuster | Boss Buster |
| 55 | BrassKnuckles | Brass Knuckles |
| 68 | Cactus | Cactus |
| 10 | DemonBlade | Demonic Blade |
| 19 | DemonicBlood | Demonic Blood |
| 20 | DemonicSoul | Demonic Soul |
| 22 | Dragonfire | Dragonfire |
| 39 | EagleClaw | Eagle Claw |
| 44 | EnergyCore | Energy Core |
| 9 | ForbiddenJuice | Forbidden Juice |
| 60 | GamerGoggles | Gamer Goggles |
| 52 | Gasmask | Gasmask |
| 28 | Ghost | Ghost |
| 75 | GloveCurse | Glove Curse / Gloves Cursed |
| 73 | GlovePoison | Glove Poison / Gloves Poison |
| 79 | GoldenRing | The One Ring |
| 14 | GoldenSneakers | Golden Sneakers |
| 11 | GrandmasSecretTonic | Grandmas Secret Tonic |
| 70 | IceCrystal | Ice Crystal |
| 49 | JoesDagger | Joes Dagger |
| 66 | LeechingCrystal | Leeching Crystal |
| 86 | Pumpkin | Pumpkin |
| 80 | QuinsMask | Quins Mask |
| 37 | Rollerblades | Rollerblades |
| 31 | ShatteredWisdom | Shattered Wisdom |
| 29 | SluttyCannon | Slutty Cannon |
| 83 | Snek | Snek |
| 47 | SoulHarvester | Soul Harvester |
| 51 | SpeedBoi | Speed Boi |
| 33 | SuckyMagnet | Sucky Magnet |
| 67 | TacticalGlasses | Tactical Glasses |
| 53 | ToxicBarrel | Toxic Barrel |
| 30 | TurboSocks | Turbo Socks |
