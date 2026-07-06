# Memory Path Index

Date: 2026-05-11

## Goal

This file is the compact index of implementation-relevant memory paths.

Use it as the first stop after a game update to answer:

- what memory-backed features exist
- where their code lives
- which reverse report is the source of truth
- which path is most likely to need refresh

Update this file whenever a path is meaningfully changed or newly confirmed.

## Index

| Feature | Code | Stable Root / Path Summary | Source Of Truth | Confidence | Last Verified |
| --- | --- | --- | --- | --- | --- |
| Map stats / interactables | `src/game_data.py`, `src/runtime_stats.py`, `src/logic.py` | `GameAssembly.dll + 0x2FB5E68` to interactables static path; related readiness controllers at `0x2F58E08` and `0x2F59000` | [01_map_generation_and_stats.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/01_map_generation_and_stats.md) | medium | 2026-05-11 |
| Player stats tab | `src/player_stats.py`, `src/gui_player_stats.py`, `src/vod_storage.py` | `GameAssembly.dll + 0x2F6A4B8` -> `class_ptr` -> `+0xB8` -> `root` -> `+0x40` -> `PlayerStatsNew` -> `+0x10` -> stats context -> `+0x18` -> entries | [02_player_stats.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/02_player_stats.md), [reports/2026-05-11-player-stats-tab-memory-path.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-05-11-player-stats-tab-memory-path.md) | high | 2026-05-11 |
| Passive item inventory | `src/player_stats.py`, `src/gui_player_stats.py`, `src/vod_storage.py` | same root to `PlayerStatsNew`; primary `+0xA0` -> inventory object -> `+0x50` passive item dictionary; fallback `+0x28` -> `PlayerInventory` -> `+0x20` `ItemInventory` -> `+0x10` item dictionary | [03_passive_item_inventory.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/03_passive_item_inventory.md), [reports/2026-05-11-item-inventory-addresses.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-05-11-item-inventory-addresses.md) | high | 2026-05-21 |
| Static item catalog / item rarities / item names | future `src/player_stats.py`, `src/gui_player_stats.py`, metadata helpers | `GameAssembly.dll + 0x2F85790` -> `DataManager.Instance` -> `+0xB8 itemData` -> `ItemData +0x54 eItem` and `+0x60 rarity`; enum names from known `EItem`; UI names from Unity Localization string tables | [reports/2026-06-09-item-name-mapping.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-06-09-item-name-mapping.md) | high | 2026-06-09 |
| Live weapon inventory / upgraded weapon stats | `src/player_stats.py`, `src/gui_player_stats.py`, `src/vod_storage.py` | same root to `PlayerStatsNew`, then `+0x28` -> `PlayerInventory` -> `+0x28` -> `WeaponInventory` -> `+0x18` weapons dictionary; each `WeaponBase +0x20` level, `+0x28` full stats, `+0x18 -> WeaponData +0xD8 -> UpgradeData +0x18` upgrade stat pool | [04_live_weapons_inventory.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/04_live_weapons_inventory.md), [reports/2026-05-19-live-weapon-stats-and-upgrades.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-05-19-live-weapon-stats-and-upgrades.md) | high | 2026-05-19 |
| Live tome inventory / effective tome upgrades | `src/player_stats.py`, `src/gui_player_stats.py`, `src/vod_storage.py` | same root to `PlayerStatsNew`, then `+0x28` -> `PlayerInventory` -> `+0x48` -> `TomeInventory`; `+0x18` `tomeLevels` dictionary and `+0x28` `tomeUpgrade` dictionary | [05_live_tomes_inventory.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/05_live_tomes_inventory.md), [reports/2026-05-22-live-tomes.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-05-22-live-tomes.md) | high | 2026-05-22 |
| Current run time | `src/player_stats.py`, `src/gui_player_stats.py`, `src/vod_storage.py` | `GameAssembly.dll + 0x2F62398` -> `class_ptr` -> `+0xB8` -> `MyTime` static fields -> `+0x20` -> `runTimer` float seconds | [06_run_metadata_and_stats.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/06_run_metadata_and_stats.md), [reports/2026-05-18-current-run-time.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-05-18-current-run-time.md) | high | 2026-05-18 |
| Run kill counter | `src/player_stats.py`, `src/gui_player_stats.py`, `src/vod_storage.py` | `GameAssembly.dll + 0x2F7A170` -> `RunStats` static fields -> `+0x0` stats dictionary -> key `kills` -> inline `float` at dictionary entry `+0x10`; stable root is the dictionary, final leaf requires key scan | [06_run_metadata_and_stats.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/06_run_metadata_and_stats.md), [reports/2026-05-20-run-kills-counter-path-details.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-05-20-run-kills-counter-path-details.md) | high | 2026-05-20 |
| Live run banishes (items + tomes) | `src/player_stats.py`, `src/gui_player_stats.py`, `src/vod_storage.py` | `GameAssembly.dll + 0x2F7A210` -> `RunUnlockables` static fields; `+0x0` `banishedItems` `HashSet<ItemData>` and `+0x8` `banishedUpgradables` `HashSet<UnlockableBase>` | [06_run_metadata_and_stats.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/06_run_metadata_and_stats.md), [reports/2026-05-22-item-bans-runtime-path.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-05-22-item-bans-runtime-path.md) | high | 2026-05-22 |
| Disabled items pool | `src/player_stats.py`, future config / overlay | `GameAssembly.dll + 0x02F7A210` -> `RunUnlockables` static fields -> `+0x10` `availableItems` dictionary; compare with `DataManager.Instance.unsortedItems` (`0x2F85790` +0x8 +0x60) | [09_disabled_items_pool.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/09_disabled_items_pool.md), [reports/2026-06-09-disabled-items-detection.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-06-09-disabled-items-detection.md) | high | 2026-07-06 |
| Live player level | `src/player_stats.py`, `src/gui_player_stats.py`, `src/vod_storage.py` | `GameAssembly.dll + 0x2F6A4B8` -> `class_ptr` -> `+0xB8` -> `root` -> `+0x40` -> `PlayerStatsNew` -> `+0x28` -> `PlayerInventory` -> `+0x30` -> `PlayerXp` -> `+0x14` -> `level` int | [06_run_metadata_and_stats.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/06_run_metadata_and_stats.md), [reports/2026-05-20-live-player-level.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-05-20-live-player-level.md) | high | 2026-05-20 |
| Player status effects / active buffs | `src/player_stats.py`, `src/gui_player_stats.py` | `owner_stats` -> `+0x28` `PlayerInventory` -> `+0x38` `PlayerStatusEffects` -> `+0x10` `statusEffects` dictionary; read keys (`EStatusEffect` enum) and objects (expiration float at `+0x20`) | [08_player_status_effects.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/08_player_status_effects.md), [reports/2026-06-20-player-status-effects-and-buffs.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-06-20-player-status-effects-and-buffs.md) | high | 2026-07-06 |
| Chest counters and free openings | `src/player_stats.py`, `src/gui_player_stats.py` | `GameAssembly.dll + 0x02F5E0B0` -> `MoneyUtility` -> `+0xB8` -> static fields -> `+0x48` -> `chestsPurchased` int; track gold at `PlayerInventory + 0x70` for free openings; item keys at passive dictionary | [10_chests_purchased_and_counters.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/10_chests_purchased_and_counters.md), [reports/2026-06-10-chests-and-keys-detection.md](file:///F:/Python/MegabonkReroll/docs/recovery/reports/2026-06-10-chests-and-keys-detection.md) | high | 2026-07-06 |
| Chaos Tome tracking / permanent stat modifiers | `src/player_stats.py`, `src/live_run_tracker.py` | `owner_stats` -> `+0x50` `StatInventory` -> `+0x10` `permanentChanges` dictionary -> list of `StatModifier` elements; tome levels dictionary at `TomeInventory +0x18` | [07_chaos_tome_tracking.md](file:///F:/Python/MegabonkReroll/docs/recovery/parts/07_chaos_tome_tracking.md) | high | 2026-07-06 |

## Notes Per Feature

### Map stats / interactables

Risk:

- likely first thing to break after major assembly layout shifts
- label strings or dictionary path can change even if higher-level controllers still look valid

What “healthy” looks like:

- map counters become non-zero on valid maps
- readiness stabilizes
- scanner decisions look sane

### Player stats tab

Risk:

- stat ids and the final/effective entries table can drift
- path may still resolve but point to base or stale data

What “healthy” looks like:

- values match the in-game stats panel
- values update during the run
- VOD snapshots capture the same numbers seen live

### Passive item inventory

Risk:

- easiest place to get fooled by stale session pointers
- dictionary layout and metadata name path are both possible failure points
- older `PlayerStatsNew +0xA0 -> +0x50` path can be empty while live items are
  present in `PlayerInventory.ItemInventory`

What “healthy” looks like:

- items appear after pickup
- counts change correctly
- names are readable and stable across sessions

### Static item catalog / item rarities

Risk:

- enum names can stay stable while live `ItemData` membership changes
- some enum ids may exist but be absent from the current loaded catalog
- `Quest` should not be flattened into the normal rarity UI without an explicit
  product decision

What "healthy" looks like:

- `EItem` ids resolve to stable names
- item rarities match the game's actual `ItemData.rarity`
- unresolved ids are handled explicitly instead of guessed silently

### Live weapon inventory / upgraded weapon stats

Risk:

- stale post-run `WeaponInventory` and `WeaponBase` objects can remain in memory
- raw heap scans can find old weapons from the previous run
- `weaponStats` contains full effective stats, not only stats upgraded by the
  weapon's level-up pool

What "healthy" looks like:

- weapon keys match the visible current run weapons
- levels match the in-game weapon levels
- `WeaponData.upgradeData.upgradeModifiers` filters display stats to the
  weapon-specific upgraded stat pool
- recordings can store weapon snapshots without breaking old files

### Live tome inventory / effective tome upgrades

Risk:

- stale post-run `TomeInventory` objects may remain in memory
- special tome internals can be more complex than the single live modifier we
  currently display
- future builds may keep the same rooted path but change dictionary/value
  layouts

What "healthy" looks like:

- tome names match the current run tomes
- levels match the in-game tome levels
- the displayed stat/value reflects the live effective modifier
- recordings can store tome snapshots without breaking old files

### Current run time

Risk:

- relatively low as long as the `MyTime` static utility class survives with the
  same layout
- still vulnerable to IL2CPP type layout shifts after updates

What “healthy” looks like:

- value matches the top-left HUD timer within normal sub-second float precision
- value starts near zero on new run
- value increases during active gameplay
- VOD snapshots include `in_game_elapsed_seconds`

### Run kill counter

Risk:

- primary path depends on boxed-value decoding inside `RunStats.stats`
- current confidence is static-analysis-strong but not live-validated
- fallback `Potato.totalKills` may be debug-oriented rather than canonical HUD data

What "healthy" looks like:

- value matches the in-game kill counter during an active run
- value starts near zero on a fresh run
- value increases on enemy kills and does not drift during idle moments
- live snapshots and recordings preserve `mob_kills`

### Live run banishes

Risk:

- `HashSet` slot order is not a safe user-facing order by itself
- `banishedUpgradables` may later include more than tomes
- stale post-run static state should be re-checked after game updates

What "healthy" looks like:

- fresh run starts with empty banish sets
- passive item banish appears in `banishedItems`
- tome banish appears in `banishedUpgradables`
- live UI and recordings preserve banishes in stable appearance order

### Player status effects / active buffs

Risk:

- status effects dictionary entries are cleaned up dynamically; checking expired values or traversing uninitialized status effects memory can return stale or corrupted slots
- status effect IDs or timers might shift offset inside `StatusEffect` class

What "healthy" looks like:

- active powerups (Haste, Rage, Shield) show up on the HUD overlay when picked up
- the expiration time decreases matching the game run time and disappears immediately upon expiration

### Chest counters and free openings

Risk:

- chest price increases can mismatch piecewise-linear formula due to copy-paste bugs in new game versions
- key stack proc rate calculation might shift from hyperbolic stacking model

What "healthy" looks like:

- chests bought and chests purchased counters update dynamically upon opening chests
- opening a chest with a key proc doesn't subtract gold, and is successfully registered as a free opening

### Chaos Tome tracking

Risk:

- permanent changes dictionary requires scanning list elements per stat; dictionary structure shifts or modifier offset changes can break list traversal
- resolving random rolls requires precise delta matching against baseline values; changes to baseline increments can throw off the count of rolls

What "healthy" looks like:

- Chaos Tome upgrades appear with accurate delta values and count of rolls on level-up
- no false rolls are detected when leveling up other standard stats

### Native hook

Risk:

- hook targets are brittle across game builds
- runtime-safe injection point can shift

What “healthy” looks like:

- hook initializes cleanly
- restart and snapshot-ready flow still work

## Update Rules

Whenever you confirm a new path:

1. add or update the row above
2. change `Last Verified`
3. update `Confidence`
4. link the latest detailed reverse report in `Source Of Truth`
5. remove ambiguity from outdated notes instead of letting conflicting paths coexist silently

