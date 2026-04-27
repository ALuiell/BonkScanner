## V5 Transform Bridge Findings

Date: 2026-04-24

Goal: continue the `prefab -> category` correlation without relying on
`executeCodeEx`, after the previous `Component.get_gameObject` approach caused
Cheat Engine instability and a nearby allocation error.

## Context

The earlier v5 idea was:

- `spawner prefab -> instret GameObject -> Start component -> late category`
- use `Component.get_gameObject(component)` to bridge from `BaseInteractable`
  component back to the instantiated `GameObject`

That was conceptually correct, but unsafe in practice. Calling
`executeCodeEx(Component.get_gameObject)` from Lua caused Cheat Engine to try a
near allocation and show:

- `Nearby allocation error`
- target was not designed for allocation outside reach of 2GB

This means the script should not call game code from Lua for this task.

## Logger Change

`lua/bonk_interactable_logger_v5.lua` was changed to avoid `executeCodeEx`
entirely.

Instead of forcing `Component.get_gameObject`, the logger now captures natural
game execution:

- `instret`: return from the instantiate path, with prefab and GameObject
- `inst_transform`: natural `GameObject.get_transform` return after instantiate
- `start`: `BaseInteractable.Start` entry, with component pointer
- `start_transform`: natural `Component.get_transform` returns inside
  `BaseInteractable.Start`
- `latecall`: final debug category callsite

The intended join is now:

- `spawner prefab -> instret GameObject -> inst_transform Transform`
- `start_transform Transform -> start component -> latecall category`

This keeps the original reverse goal but removes all Lua-side calls into game
code.

## Captured CSV

Source file:

- `C:\Users\Skadi\AppData\Local\Temp\bonk_interactable_log_v5.csv`

File metadata from the analyzed capture:

- size: `3443017` bytes
- last write time: `2026-04-24 08:35:57`
- final logger state checked through MCP:
  - `active=false`
  - `seq=11608`
  - active breakpoints: `0`

Event counts:

- `instret`: `3924`
- `inst_transform`: `3924`
- `start_transform`: `2247`
- `start`: `749`
- `latecall`: `699`
- `spawner`: `65`
- `marker`: `1`

Late category counts:

- `Pots`: `275`
- `Chests`: `230`
- `Charge Shrines`: `75`
- `Greed Shrines`: `40`
- `Boss Curses`: `20`
- `Magnet Shrines`: `13`
- `Moais`: `13`
- `Shady Guy`: `13`
- `Challenges`: `11`
- `Microwaves`: `9`

## Confirmed Stable Pieces

### `start -> latecall`

The late category side remains clean.

All `latecall` rows matched a `BaseInteractable.Start` component:

- `latecalls = 699`
- `matched_start = 699`
- `unmatched = 0`

This means:

- `Start.component == latecall.late_obj` is still confirmed.
- `BaseInteractable.Start -> category` remains solved.

### Transform events are captured

The new bridge events are present:

- `inst_transform = 3924`
- `start_transform = 2247`

This confirms the non-`executeCodeEx` strategy is viable at the logging level:
the game naturally exposes Transform pointers on both sides.

## Strong Confirmations

The cleanest mappings from this run are:

- `0x13AB21CA660 -> Charge Shrines`
- `0x13AB21CA640 -> Greed Shrines`

These are supported by both bucket shape and category join evidence.

Spawner rows:

- `seq=1407`
  - prefab: `0x13AB21CA660`
  - `amount=15`
  - `prefabs_len=1`
  - category signal: `Charge Shrines`
- `seq=1438`
  - prefab: `0x13AB21CA640`
  - `amount=8`
  - `prefabs_len=1`
  - category signal: `Greed Shrines`

This agrees with previous confirmed knowledge that charge and greed shrine
singletons are structurally distinct and countable early.

## Partial / Noisy Findings

A raw Transform join can produce links such as:

- `0x13AB21CA6A0 -> Pots`
- `0x13AB21CA680 -> Pots`
- `0x13AB21CA660 -> Charge Shrines`
- `0x13AB21CA640 -> Greed Shrines`

However, only the shrine singleton mappings should be treated as strong from
this run.

Reason: Transform addresses can be reused, and some `start_transform` rows occur
far later than their nearest earlier `inst_transform` candidate. Simple matching
by Transform across the whole file can therefore over-join unrelated objects.

Observed with a nearest-prior Transform join:

- total linked rows: `269`
- components considered: `452`
- late components: `427`
- unique instantiate transforms: `3078`

Dominant raw links:

- `94`: `0x13AB21CA6A0 -> Pots`
- `46`: `0x13AB21CA680 -> Pots`
- `35`: `0x13AB21CA660 -> Charge Shrines`
- `33`: `0x13AB21CA640 -> Greed Shrines`

After filtering by closer sequence distance:

- `delta <= 200`
  - `21`: `0x13AB21CA660 -> Charge Shrines`
- `delta <= 500`
  - `94`: `0x13AB21CA6A0 -> Pots`
  - `46`: `0x13AB21CA680 -> Pots`
  - `35`: `0x13AB21CA660 -> Charge Shrines`
  - `33`: `0x13AB21CA640 -> Greed Shrines`

The `delta <= 500` results are useful clues, but not proof-quality for the
non-shrine categories yet.

## Why Transform Join Is Better Than `get_gameObject`

The previous `get_gameObject` path required Cheat Engine Lua to execute game
code. That caused allocation problems and could hang CE.

The Transform path does not call game code from Lua. It only observes return
values from calls the game already makes:

- instantiated GameObject naturally calls `GameObject.get_transform`
- `BaseInteractable.Start` naturally calls `Component.get_transform`

So the new strategy is safer for CE and closer to passive observation.

## Current Risk

The Transform bridge proves the idea, but current matching is still too broad.

Main risk:

- `Transform*` values can be reused or can match outside the active
  `RandomObjectSpawner` bucket window.

This creates plausible but noisy mappings, especially for:

- Pots
- Chests
- non-shrine special interactables

The current run should therefore be used as:

- confirmation that the no-`executeCodeEx` bridge is viable
- proof for shrine singleton mappings
- input for the next, cleaner logger

## Recommended Next Logger

The next logger should carry the current `RandomObjectSpawner` context forward
into instantiate events.

Recommended additions:

- Track `active_spawner_seq`
- Track `active_spawner_label`
- Track `active_randomObject`
- Track `active_prefabs_len`
- Track `active_caller_index`
- Add those fields to every `instret` and `inst_transform`

Then join only within that active bucket context:

- `spawner label/context -> instret GameObject`
- `instret GameObject -> inst_transform Transform`
- `inst_transform Transform -> start_transform Transform`
- `start component -> latecall category`

This should avoid matching reused Transform addresses from unrelated buckets and
should make `prefab -> category` proof-quality for more categories.

## Practical Status

Safe to keep:

- no `executeCodeEx`
- no `resolveGameObjects`
- Transform return breakpoints
- `start -> latecall` component identity

Treat as confirmed:

- `0x13AB21CA660 -> Charge Shrines`
- `0x13AB21CA640 -> Greed Shrines`

Treat as promising but unresolved:

- `0x13AB21CA6A0 -> Pots`
- `0x13AB21CA680 -> Pots`
- other non-shrine prefab/category candidates

