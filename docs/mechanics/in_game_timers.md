# Megabonk In-Game Timers

This document describes the timer fields BonkScanner reads from memory and the rules for choosing the correct source for UI, tracking, and the in-game overlay. Map-level observations are documented separately in [map_details_report.md](./map_details_report.md).

## 1. Data Sources

The timer fields live in the static fields of the `MyTime` class. `PlayerStatsClient` and `GameDataClient` read the following `float` values:

| Code field | Offset from `MyTime` static fields | Purpose |
| --- | ---: | --- |
| `stage_timer_seconds` / `STAGE_TIMER_OFFSET` | `0x1C` | Regular timer for the current map or main phase. Counts upward. |
| `run_timer_seconds` / `RUN_TIMER_OFFSET` | `0x20` | Total run time. Counts upward. |
| `final_swarm_timer_seconds` / `FINAL_SWARM_TIMER_OFFSET` | `0x24` | Dedicated final-swarm / ghost-phase timer. Counts upward. |
| `difficulty_timer_seconds` / `MY_TIME_DIFFICULTY_TIMER_OFFSET` | `0x28` | Separate difficulty timer; currently unused by the event overlay. |
| `crypt_timer_seconds` / `CRYPT_TIMER_OFFSET` | `0x2C` | Graveyard crypt-phase timer. Counts upward. |

`stage_index` and `CurrentStage.Timeline.stageTime` are read separately through `MapController`. They are useful context, but neither is a universal source of truth for the current map phase or countdown duration.

## 2. Time Direction

Memory fields generally represent **elapsed** time and increase from zero, while the in-game UI normally renders a countdown:

```text
remaining_seconds = canonical_duration_seconds - elapsed_timer_seconds
```

`canonical_duration_seconds` is the known duration of the specific phase. It must not be substituted with an arbitrary `Timeline.stageTime` value.

### Standard Maps

| Raw stage index | Duration | Display formula |
| ---: | ---: | --- |
| 0 | 600 s (10:00) | `600 - stage_timer` |
| 1 | 540 s (9:00) | `540 - stage_timer` |
| 2 | 480 s (8:00) | `480 - stage_timer` |

On Forest and Desert, `stage_timer` and the stage timeline may jump sharply at the end of a stage to force the ghost phase. Treat those jumps as transitions, not ordinary timer progression.

## 3. Graveyard: Four Time Domains

Graveyard cannot be modeled from `stage_index` alone: live observations show it remains `0`, while the map and stage pointers remain unchanged between crypt, main map, boss, and post-boss phases.

| Phase | Timer for logic | In-game display | Reliable phase marker |
| --- | --- | --- | --- |
| Crypt 1 / Crypt 2 | `crypt_timer` | Reverse crypt countdown | `Crypt Chests` or `Crypt Pots` exists in the activity dictionary. |
| Main map | `stage_timer` | Countdown from 16:00 | No crypt activities; `Pumpkin`, `Gravestones`, or `Chests.max == 69` is present. |
| Boss room | `stage_timer` before transition | Starts at 16:00; changes to 10:00 when the final boss appears | Use transition context and the activity dictionary; raw stage identity does not change. |
| Post-boss ghost / final swarm | `final_swarm_timer` | Ghost / overtime | `final_swarm_timer > 0`; this timer is shared by the boss room and the returned main map. |

### Important `crypt_timer` Limitation

`crypt_timer > 0` **does not prove** that the player is still in a crypt. It may retain a non-zero value after leaving. A live read on the Graveyard main map returned:

```text
stage_timer        = 170.768 s
Timeline.stageTime = 960.0 s
crypt_timer        = 20.301 s
final_swarm_timer  = 0.0 s
activities         = Pumpkin, Gravestones, Chests.max = 69
crypt activities   = absent
```

When the activity dictionary is available, `Crypt Chests` and `Crypt Pots` therefore take priority. `crypt_timer` is only a fallback when activity data is unavailable.

## 4. Event Timer Overlay

`build_event_timer_overlay_html()` uses `stage_timer_seconds` and a canonical phase duration. It does not use `stage_time_seconds` as the event duration because that field is a changing timeline marker and can represent a current marker instead of the full map limit.

For standard maps:

```text
remaining = {stage 0: 600, stage 1: 540, stage 2: 480}[stage_index] - stage_timer
```

For the Graveyard main phase:

```text
remaining = 960 - stage_timer
```

Before displaying Graveyard events, the overlay must confirm:

```text
Graveyard map
AND not in crypt
AND final_swarm_timer is not active
AND player is not beyond the first crypt/main-map progression branch
```

### Graveyard Event Schedule

The schedule stores seconds remaining until the end of the phase. For the 16:00 Graveyard main map:

| Event | In-game countdown time | Duration |
| --- | ---: | ---: |
| Boss | 13:00 | — |
| Wave | 12:00 | 30 s |
| Boss | 9:00 | — |
| Wave | 8:00 | 30 s |
| Boss | 6:00 | — |
| Wave | 5:00 | 30 s |
| Boss | 3:00 | — |
| Wave | 2:00 | 30 s |

Warnings appear strictly within the configured `warning_seconds` window. The warning window must not be widened to match the wave duration: with a value of `15`, a wave warning appears at most 15 seconds before its start.

During an active wave, the overlay intentionally displays the static text `Wave Active: 30s` rather than a locally computed countdown. This avoids visual desynchronization until the exact wave-start moment has a confirmed memory signal.

## 5. Rules for New Features

1. Do not determine a Graveyard sub-phase from `stage_index`, the `CurrentStage` pointer, or the `CurrentMap` pointer; they may stay unchanged for the entire run.
2. Do not use a non-zero `crypt_timer` as the only crypt detector.
3. For events and countdowns, always use the timer for the relevant phase and an explicit canonical duration.
4. Detect transitions using the timer family together with the activity dictionary: additions/removals of `Crypt Chests`, `Crypt Pots`, `Pumpkin`, `Gravestones`, and changes to `Chests.max`.
5. Validate every new timing assumption in a live run and record it in a test with concrete input values.

## 6. Items Requiring Live Validation

- The exact point at which `stage_timer` changes semantics in the Graveyard boss room (16:00 → 10:00).
- `crypt_timer` behavior immediately after each crypt exit and during loading transitions.
- How to distinguish the boss room from the second crypt after crypt activities disappear but before `final_swarm_timer` becomes non-zero.
- The exact wave-start moment relative to `stage_timer`; do not artificially shift the schedule by one second without a confirmed separate signal.
