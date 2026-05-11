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

