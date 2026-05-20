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
| Map stats / interactables | `game_data.py`, `runtime_stats.py`, `logic.py` | `GameAssembly.dll + 0x2FB5E68` to interactables static path; related readiness controllers at `0x2F58E08` and `0x2F59000` | `game_data.py`, `AGENT.md`, future dedicated report if refreshed | medium | 2026-05-11 |
| Player stats tab | `player_stats.py`, `gui.py`, `vod_storage.py` | `GameAssembly.dll + 0x2F6A4B8` -> `class_ptr` -> `+0xB8` -> `root` -> `+0x40` -> `PlayerStatsNew` -> `+0x10` -> stats context -> `+0x18` -> entries | `docs/reverse/reports/2026-05-11-player-stats-tab-memory-path.md` | high | 2026-05-11 |
| Passive item inventory | `player_stats.py`, `gui.py`, `vod_storage.py` | same root to `PlayerStatsNew`, then `+0xA0` -> inventory object -> `+0x50` passive item dictionary | `docs/reverse/reports/2026-05-11-item-inventory-addresses.md` | high | 2026-05-11 |
| Static item catalog / item rarities | future `player_stats.py`, `gui.py`, metadata helpers | `GameAssembly.dll + 0x2F85790` -> `DataManager.Instance` -> `+0xB8 itemData` -> `ItemData +0x60 rarity`; enum names from dumped `EItem` | `docs/reverse/reports/2026-05-19-item-enum-and-rarities.md` | high | 2026-05-19 |
| Live weapon inventory / upgraded weapon stats | future `player_stats.py`, `gui.py`, `vod_storage.py` | same root to `PlayerStatsNew`, then `+0x28` -> `PlayerInventory` -> `+0x28` -> `WeaponInventory` -> `+0x18` weapons dictionary; each `WeaponBase +0x20` level, `+0x28` full stats, `+0x18 -> WeaponData +0xD8 -> UpgradeData +0x18` upgrade stat pool | `docs/reverse/reports/2026-05-19-live-weapon-stats-and-upgrades.md` | high | 2026-05-19 |
| Current run time | `player_stats.py`, `gui.py`, `vod_storage.py` | `GameAssembly.dll + 0x2F62398` -> `class_ptr` -> `+0xB8` -> `MyTime` static fields -> `+0x20` -> `runTimer` float seconds | `docs/reverse/reports/2026-05-18-current-run-time.md` | high | 2026-05-18 |
| Run kill counter | `player_stats.py`, `gui.py`, `vod_storage.py` | `GameAssembly.dll + 0x2F7A170` -> `RunStats` static fields -> `+0x0` stats dictionary -> key `kills` -> inline `float` at dictionary entry `+0x10`; stable root is the dictionary, final leaf requires key scan | `docs/reverse/reports/2026-05-20-run-kills-counter-path-details.md` | high | 2026-05-20 |
| Live player level | future `player_stats.py`, `gui.py`, `vod_storage.py` | `GameAssembly.dll + 0x2F6A4B8` -> `class_ptr` -> `+0xB8` -> `root` -> `+0x40` -> `PlayerStatsNew` -> `+0x28` -> `PlayerInventory` -> `+0x30` -> `PlayerXp` -> `+0x14` -> `level` int | `docs/reverse/reports/2026-05-20-live-player-level.md` | high | 2026-05-20 |
| Native hook readiness / AlwaysManager path | `hook_loader.py`, `native/BonkHook/*` | `GameAssembly.dll + 0x2F6BAA8` for current AlwaysManager-related path used by hook readiness | `hook_loader.py`, `docs/reverse/memory-and-hooks-reference.md` | medium | 2026-05-11 |

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

What “healthy” looks like:

- items appear after pickup
- counts change correctly
- names are readable and stable across sessions

### Static item catalog / item rarities

Risk:

- enum names can stay stable while live `ItemData` membership changes
- some enum ids may exist in dump but be absent from the current loaded catalog
- `Quest` and `Corrupted` should not be flattened into the normal four-tier UI
  without an explicit product decision

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
- current confidence is dump-strong but not CE-live-validated
- fallback `Potato.totalKills` may be debug-oriented rather than canonical HUD data

What "healthy" looks like:

- value matches the in-game kill counter during an active run
- value starts near zero on a fresh run
- value increases on enemy kills and does not drift during idle moments
- live snapshots and recordings preserve `mob_kills`

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

