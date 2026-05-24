# Functional Updates

Date: 2026-05-24

This file tracks open and partially completed functional/runtime work that does
not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## 1. Find A Reliable Runtime Signal For True Menu / Non-Gameplay State

Status: `[Open]`

Current branch notes:

- Existing recording auto-stop logic can reliably detect full process exit, but
  not `Exit to Menu` from an active run.
- Current known run signals are not sufficient because they can remain frozen in
  memory after leaving the run.
- This needs a focused reverse pass before `Live Stats` recording auto-stop can
  be considered robust.

Reverse task:

- Find a reliable runtime signal that distinguishes active run gameplay from:
  - main menu
  - post-run / returned-to-menu state
- The signal must remain valid even if old run pointers, seed, stats, or items
  still remain in memory as a frozen snapshot.

Verified manual observations on build `2026-05-14`:

- Cold menu:
  - `map_seed = 0`
  - `current_map_ptr = 0`
  - `current_stage_ptr = 0`
  - `has_loaded_map = False`
- Active run:
  - `map_seed` is non-zero
  - `current_map_ptr` and `current_stage_ptr` are non-zero
  - `has_loaded_map = True`
- After `Exit to Menu` from a run:
  - `map_seed` stays stuck at the previous run value
  - `current_map_ptr` and `current_stage_ptr` stay stuck
  - `has_loaded_map = True`
  - `is_resetting = False`
  - player stats and items can also stay stuck as a frozen snapshot of the last
    run

What this means:

- Current known signals are not enough to reliably detect that the run has
  ended and the player has returned to menu.
- `ProcessNotFound` only covers full game exit, not `Exit to Menu`.

Primary goal:

- Find a stable memory or runtime-logic signal that reliably indicates one of:
  - the player is currently in main menu
  - an active run is no longer in progress
  - the game is currently not in gameplay state
  - post-run / menu state differs from active in-run state even when old run
    objects still remain in memory

Preferred candidate types:

- global game-state enum
- menu / open-screen state
- scene/state-machine current state
- pause/menu controller state, if it distinguishes:
  - paused during a run
  - main menu
- run/session active flag
- map/session ownership flag that resets on real run end even if old objects are
  still retained in memory

Weak signals that should not be used as the final solution without strong
confirmation:

- `map_seed` alone
- `current_map_ptr` alone
- `current_stage_ptr` alone
- `has_loaded_map` alone
- `stats stopped changing for a while`
- `items are empty`
- a generic `pause` flag that does not distinguish paused gameplay from main
  menu

Required validation states:

- cold menu after fresh game launch
- active run gameplay
- paused run
- exited from run back to menu

Extra validation states if possible:

- during death / end-run transition
- after full process exit

Expected reverse report output:

- the found entity / field / method / offset / path
- what that state actually means
- how it behaves in:
  - menu
  - active run
  - paused run
  - post-run menu
- how reliable the signal is
- whether it is safe to use for:
  - recording auto-stop on menu
  - recording keep-alive during paused run
  - recording auto-split only on true new run

Ranking guidance if multiple candidates are found:

- best primary signal
- possible fallback signal
- unsafe / weak signals that should not be used

Implementation target after reverse:

- `process gone => stop`
- `true menu / non-gameplay state => stop after grace`
- `new run state => split recording`
- `paused active run => do not stop`

Why this matters:

- This is the missing piece for making `Live Stats` recording lifecycle
  trustworthy.
- Without a true gameplay/menu discriminator, auto-stop can silently fail and
  keep recording stale snapshots from a dead run context.

## 2. Compare Runs By In-Game Time

Status: `[Partial]`

Current branch notes:

- Phase 1 is done: run timer reverse path is documented in `docs/reverse/reports/2026-05-18-current-run-time.md`.
- Phase 2 is done: recordings now store `game_time_seconds` in snapshots.
- Phase 3 is mostly done: the existing recordings viewer shows in-game time and remains backward-compatible with older recordings.
- The dedicated `Compare Runs` tab and time-synced side-by-side compare workflow are still not implemented.

Goal:

- Reverse the part of the game that tracks the run's internal elapsed time /
  current in-game time.
- Add that value into player stats recording snapshots as first-class recorded
  data.
- Add a new tab such as `Compare Runs` for loading and comparing two recorded
  runs side by side at the same gameplay moment.

Why this helps:

- Snapshot index and wall-clock capture time are useful, but they do not always
  represent the same gameplay stage across different runs.
- In-game elapsed time would let the app align two runs by actual run progress.
- This would make it much easier to compare stats, item progression, and build
  state at the same point in a run.
- This is especially valuable for:
  - comparing early-game routing
  - checking when a build starts to spike
  - seeing how item and stat progression differs between good vs bad runs
  - reviewing why one run stabilized faster than another

Proposed behavior:

- Find and confirm the in-memory value the game uses for current run time.
- Store that value in each recorded snapshot together with the existing player
  stats and items data.
- In `Compare Runs`, let the user load two `.jsonl` recordings.
- Synchronize both timelines by the recorded in-game elapsed time instead of
  only by snapshot position.
- Show both runs side by side so the user can compare:
  - player stats
  - items
  - overall build state
  - the same gameplay phase across both runs

Suggested UX:

- Left side: `Run A`
- Right side: `Run B`
- Shared top controls:
  - load first run
  - load second run
  - jump to time
  - scrub both timelines together
- When the user moves to `02:30`, both runs should snap to the nearest recorded
  snapshot for that in-game time.
- The compare tab should clearly display:
  - recorded in-game time for each side
  - actual selected snapshot timestamp
  - whether one side had to snap forward / backward because an exact time match
    was unavailable

Recommended implementation shape:

- First finish reverse work and document:
  - exact source object / path
  - value type
  - units used by the game
  - whether the value pauses in menus / loading / death states
- Extend the VOD snapshot schema with a dedicated field for in-game elapsed
  time.
- Keep backward compatibility for older `.jsonl` recordings that do not contain
  this field.
- Build the compare UI as a separate tab instead of overloading the current
  single-run recordings viewer.
- Suggested implementation order:
  - phase 1: reverse and validate in-game time source
  - phase 2: record the value into snapshots / `.jsonl`
  - phase 3: expose it in the existing recordings viewer
  - phase 4: build dedicated `Compare Runs` tab
  - phase 5: add comparison-specific quality-of-life features

Important caveats:

- We need to verify whether the game time value is:
  - real gameplay time
  - scaled time
  - paused in menus
  - reset correctly on new runs
- If the timer is affected by pause states, loading, or special slow/fast game
  states, compare logic should document that clearly.
- Old recordings without the new field should either:
  - disable time-synced compare mode
  - or fall back to simple snapshot-based comparison with a visible note
- Comparison should be based on nearest available snapshot, so large snapshot
  intervals may reduce comparison precision.
- If this feature becomes important, we may want lower recording intervals for
  runs intended specifically for analysis.

Possible improvements:

- Add a delta view showing stat differences between the two runs at the same
  in-game time.
- Add quick jump buttons such as `30s`, `1m`, `2m`, `5m`.
- Add highlighting for missing / changed items between the two compared runs.
- Add an option to pin one run as a reference and quickly cycle through many
  other runs against it.
- Add export of comparison summaries for sharing and debugging.

## 3. Manual Snapshot-To-Snapshot Compare In Recordings Viewer

Status: `[Open]`

Goal:

- Let the user compare any two chosen snapshots from the same recording instead
  of always comparing only current vs previous.

Proposed UX:

- User selects a snapshot on the recordings timeline.
- User presses a button such as `Set First Snapshot`.
- User moves to another snapshot on the same timeline.
- The viewer compares the selected second snapshot against the stored first
  snapshot.

Why this helps:

- Makes it easy to inspect item gains across a specific segment of a run.
- Makes stat, level, and kill deltas more useful than strict previous-snapshot
  comparison.
- Fits the current recordings viewer without requiring the full multi-run
  compare tab first.

Suggested behavior:

- Show a visible indicator for the stored first snapshot.
- Keep normal snapshot browsing intact.
- Display deltas for:
  - items gained
  - stat changes
  - level change
  - mob kill change
- Allow clearing or replacing the first snapshot without reloading the
  recording.

Implementation note:

- This should remain a separate feature from time-synced `Compare Runs`, even
  if both eventually share delta-formatting helpers.
