# UI Updates

Date: 2026-05-24

This file tracks open and partially completed UI-focused work.

Status legend:

- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## 1. Compare Runs By In-Game Time

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

## 2. Manual Snapshot-To-Snapshot Compare In Recordings Viewer

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

## 3. Preserve Template Colors In Runtime Active-Templates Log

Status: `[Open]`

Current issue:

- When templates are added or updated during scanner runtime, the `Active templates updated live` log output shows template names as plain text.
- In the main templates list, those same templates already have distinct colors.
- This makes the runtime log harder to scan quickly, especially when several
  templates are active at once.

Goal:

- When runtime log lines list active templates, render each template name using
  the same color that template already has in the templates UI.

Example target:

- Current:
  - `Active templates updated live: LIGHT, MERCHANT, GOOD, PERFECT`
- Desired:
  - `LIGHT`, `MERCHANT`, `GOOD`, and `PERFECT` should each reuse their existing
    template color in the runtime scanner log/output.

Why this helps:

- Makes runtime updates easier to parse at a glance.
- Keeps visual language consistent between the template list and the live log.
- Reduces the chance of misreading a long active-template set during reroll
  setup changes.

Suggested behavior:

- Reuse the existing template-to-color mapping instead of introducing a second
  color definition source.
- Apply color only to the template names, not necessarily to commas or the full
  line prefix.
- Keep plain-text fallback safe in any output path that does not support rich
  text coloring.

Implementation note:

- Prefer using the same helper/constants already used by the templates list so
  log coloring stays in sync automatically if template colors ever change.

## 4. Make Recordings List Narrower And Keep Stats Cards Static In Size

Status: `[Open]`

Current issue:

- In the `Recordings` tab, the recordings list takes more horizontal space than
  needed.
- That leaves less room for run stats and detail cards.
- Stat/info cards can also visually change size as item count or text amount
  changes, which makes the layout feel jumpy.

Goal:

- Reduce the width of the recordings list panel.
- Give more horizontal room to the stats/details area.
- Keep stats/info cards at a stable size so the layout does not shift when
  recording content changes.

Desired UX:

- The recordings list should be compact but still comfortably readable.
- The stats/details section should have more room for long item lists and run
  information.
- Cards should already be expanded to a size that fits their maximum expected
  content footprint, or at least a stable upper-bound layout, so switching
  snapshots does not keep resizing the UI.

Why this helps:

- Makes the recordings tab easier to read during run review.
- Reduces distracting layout movement when item counts or snapshot content
  change.
- Gives more of the screen to the information the user is actually analyzing.

Suggested behavior:

- Narrow the left recordings list pane relative to the details pane.
- Review minimum/maximum/fixed widths for the list so it does not overgrow.
- Set stable sizing rules for key stat/info cards in the recordings view.
- Prefer a fixed or strongly bounded card layout for sections whose content
  changes often, especially items, stats, and summary panels.

Implementation note:

- The goal is visual stability, not clipping useful information. If some areas
  need scrolling or wrapping inside a fixed-size card, that is preferable to the
  whole layout constantly resizing.
