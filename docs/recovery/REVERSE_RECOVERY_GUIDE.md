# Reverse Recovery Guide

Date: 2026-05-11

## Goal

This file is the practical recovery playbook for Megabonk game updates.

Use it when:

- the game updates and memory reads start returning zeros, garbage, or stale values
- the UI stops updating correctly
- reroll automation still runs but evaluates wrong data
- native hook injection or hook readiness breaks

This guide is not meant to replace detailed reverse reports.
It exists to help quickly:

1. identify which subsystem broke
2. verify the current source of truth
3. produce a clean reverse handoff
4. update code with minimal confusion

## Main Rule

Prefer stable module-relative paths and documented root chains.

Avoid implementation based on:

- one-session live addresses
- raw Cheat Engine addresses with no stable root path
- values that look plausible but were not verified across a fresh session

If a reverse note and code disagree, the latest verified reverse report in
`docs/recovery/reports/` should be treated as the primary source of truth until
the code is updated.

## Project Surfaces That Can Break

### 1. Map stats

Code:

- `game_data.py`
- `runtime_stats.py`
- `logic.py`

Symptoms:

- shrine/map counters show `0`
- map stats never stabilize
- best/worst map tracking looks wrong
- scanner rerolls forever or accepts obviously bad maps

Most fragile pieces:

- `GameDataClient.TYPE_INFO_OFFSET`
- `MAP_CONTROLLER_TYPE_INFO_OFFSET`
- `MAP_GENERATION_CONTROLLER_TYPE_INFO_OFFSET`
- interactables dictionary layout
- label-to-stat mapping if game strings changed

### 2. Player stats tab

Code:

- `player_stats.py`
- `gui.py`
- `vod_storage.py`

Symptoms:

- `Live Stats` shows `--` or nonsense values
- recording works but snapshots are empty
- values update for some stats but not others

Most fragile pieces:

- `PlayerStatsClient.TYPE_INFO_OFFSET`
- owner/root chain to `PlayerStatsNew`
- final stats entries path
- per-stat id mapping

### 3. Passive item inventory

Code:

- `player_stats.py`
- `gui.py`
- `vod_storage.py`

Symptoms:

- items list is always empty
- item names become garbage
- stack counts are incorrect
- old items appear even in a fresh run

Most fragile pieces:

- `PlayerStatsNew + 0xA0`
- `+0x50` passive item dictionary path
- dictionary layout
- class metadata string pointers
- stack/count field

### 4. Native hook / restart flow

Code:

- `hook_loader.py`
- `native/BonkHook/*`
- `run_control.py`

Symptoms:

- hook never becomes ready
- injection fails after the game starts
- restart flow no longer works
- snapshot readiness waits forever

Most fragile pieces:

- hook target addresses in `GameAssembly.dll`
- exported hook lifecycle behavior
- runtime-safe injection timing

## Recommended Triage Order After A Game Update

Follow this order to reduce noise and isolate the first broken layer.

### Step 1. Confirm process and module attachment still works

Check:

- game process name is still correct
- `GameAssembly.dll` is still loaded
- app can still attach to the target process

If this fails, do not start deep reverse yet.
Fix the process/module layer first.

### Step 2. Check map stats root paths

Reason:

- map stats are central to reroll logic
- many other validations depend on them being sane

Check:

- current `TYPE_INFO_OFFSET` values in `game_data.py`
- whether the interactables dictionary still resolves
- whether labels still match the expected map stats

### Step 3. Check player stats root path

Reason:

- player stats and item inventory currently share the same broad root chain
- if the shared root moved, both features may break together

Check:

- `PlayerStatsClient.TYPE_INFO_OFFSET`
- `class_ptr + 0xB8`
- `root + 0x40 -> PlayerStatsNew`
- stats entries path from there

### Step 4. Check passive item inventory

Only do this after the player stats root path is confirmed.

Check:

- `PlayerStatsNew + 0xA0`
- resulting inventory-related object
- passive item dictionary at `+0x50`
- dictionary `entries`, `count`
- item object count field
- item class metadata and ASCII class name

### Step 5. Check native hook targets

Reason:

- hooks are usually more brittle than plain readers
- there is no point debugging hook targets before stable read paths are confirmed

Check:

- hook target addresses
- runtime readiness assumptions
- export invocation behavior

## Common Failure Patterns

### All values are zero

Usually means one of:

- root path moved
- class/static fields are not initialized yet
- wrong object type or stale path

### Count looks valid but entries are empty or junk

Usually means one of:

- dictionary object is stale
- the object is no longer the expected dictionary type
- entries offset changed

### Some stats work, some do not

Usually means one of:

- stat ids changed
- final/effective stats table moved
- one section of the stats layout changed while the root chain still works

### Names are garbage but counts are correct

Usually means one of:

- class metadata path changed
- string pointer field changed
- string encoding assumption is wrong

### Values look plausible but do not update correctly

Treat this as dangerous.

Possible causes:

- stale pointer from a previous run/session
- reading a cached/base object instead of final/effective runtime state
- path valid only inside the old session

## What A Good Reverse Handoff Must Include

When preparing a reverse report for implementation, include:

- goal of the reverse task
- stable root path from `GameAssembly.dll + offset`
- all dereference and field offsets in order
- what object type each hop represents
- how the path behaves across fresh sessions
- field layout for arrays/dictionaries/lists if applicable
- exact source of display name or label
- exact source of count/value
- confidence per claim
- rejected paths and why they were rejected
- implementation recommendation section

Use `docs/recovery/HANDOFF_TEMPLATE.md` for new reports.

## How To Hand Off An Update Efficiently

Best workflow:

1. create a new report in `docs/recovery/reports/`
2. use the handoff template
3. clearly mark what is confirmed vs suspected
4. tell me which code path should be updated

Good prompt example:

`Game updated. Use docs/recovery/reports/2026-05-12-player-stats-refresh.md as source of truth and update player_stats.py + related UI.`

Even better:

`Game updated. First sanity-check the report against the current code assumptions, then patch the implementation.`

## Current Canonical References

At the time of writing, these are the most useful references:

- `docs/recovery/reports/2026-05-11-player-stats-tab-memory-path.md`
- `docs/recovery/reports/2026-05-11-item-inventory-addresses.md`
- `docs/recovery/memory-and-hooks-reference.md`

## Recovery Output Checklist

Before considering a recovery pass complete, verify:

- code offsets/path were updated
- UI reads sane values again
- old stale-path assumptions were removed
- tests were updated or added where possible
- a fresh reverse report exists for the changed path
- `MEMORY_PATH_INDEX.md` was updated

