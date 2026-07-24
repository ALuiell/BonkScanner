# Functional Updates Archive

This file archives completed, shelved, or old functional updates, helping keep `functional_updates.md` focused on active tasks.

---

## Recently Handled Items (Archived 2026-07-24)

### Live Run Refactor Fixes

#### 1. In-Game Overlay Graveyard Difficulty & XP Gain Stat Caps (Refactor Fixes)

Status: `[Implemented]`

Goal:

- Extend stat capping logic in `_build_in_game_stats_rows` (In-Game Overlay Stats widget) to include the Graveyard map, enforcing XP Gain (10x) and Difficulty (571% for first 2 minutes) stat caps.

Problem Analysis:

- **Graveyard Explicitly Excluded:** `_build_in_game_stats_rows` contains `if not is_graveyard and raw_val is not None:`, which completely bypasses stat capping and cap highlight colors when playing on the Graveyard map.
- **Missing Difficulty Cap for Graveyard:** On Graveyard, the difficulty cap for the first 2 minutes (before 2m ghost spawn) should be 571% (5.71), identical to Tier 1 Stage 0.

Planned Solution:

- Remove `not is_graveyard` exemption in `_build_in_game_stats_rows`.
- Define Graveyard difficulty capping rules (cap at 5.71 / 571% for the first 2 minutes of the stage, matching Tier 1 Stage 0 rules) and ensure XP Gain 10x capping applies to Graveyard as well.

Shipped Behavior:

- The `not is_graveyard` guard is gone, so XP Gain now shows ` / 10x` and turns
  red on Graveyard exactly as it does elsewhere. Note that the *value* was
  already clamped to `10x` there -- `_format_stats_display_value` never consulted
  `is_graveyard` -- so what was missing was only the cap suffix and the colour.
- Difficulty on Graveyard follows the Tier 1 Stage 0 rule: **5.71 / 571%** before
  the boundary, **4.95 / 495%** after it, where the boundary is
  `stage_timer >= stage_duration + 120` -- the same formula the other maps use.
- **Graveyard must not read the tier table.** Its raw `stage_index` is not a
  tier: it stays at whatever stage pointer the map reuses (observed as `2`), so
  simply deleting the exemption as originally planned would have applied the
  Stage 3 caps (457% / 381%). Graveyard gets its own branch that ignores
  `stage_index` entirely.
- The Graveyard boundary uses the fixed `_GRAVEYARD_STAGE_DURATION_SECONDS`
  (960 s) rather than the snapshot's `stage_duration_seconds`, for the reason
  already documented in `build_event_timer_overlay_html`: on Graveyard that field
  is a live timeline marker, not the map's duration. The literal in the Event
  Timer now reads from the same constant so the two schedules cannot drift.
- One rule covers the whole map -- crypts, main map and boss room alike --
  because the projection has no phase marker to distinguish them yet.

Covered by three cases in `test_in_game_overlay_render.py`: the 1079 s/1080 s
boundary pair, a subtest sweeping `stage_index` 0/1/2 to prove the tier table is
bypassed, and the Graveyard XP Gain cap.

#### 2. Stage Summary Card Ledger (Compare Runs Optimization)

Status: `[Implemented]`

Goal:

- Stop rebuilding Stage Summary from scratch on every scrub frame. Fold each
  recording once into an ordered list of per-index **stage cards**, then let
  Compare Runs, Recordings and Live Stats read the card for the selected index
  instead of re-deriving it.

Problem Analysis:

- **The only prefix-dependent section is quadratic across a drag.**
  `_build_compare_run_stage_summary_rows` (`src/projections/formatting.py:370`)
  calls `build_stage_summary(snapshots[: index + 1])`, and
  `build_stage_summary` is a pure fold over that whole prefix. Cost grows with
  the selected index, so a drag across the timeline is O(n^2).
- **The same fold is paid by two other surfaces.**
  `src/ui/tabs/player_stats/recordings.py:454` re-folds the prefix on every
  Recordings scrub, and `src/ui/tabs/player_stats/live_stats.py:420` does the
  same for the live timeline.

Solution & Implementation:

- Implemented memoisation and ledger caching for Stage Summary calculations across Compare Runs, Recordings, and Live Stats.
- Stage Summary O(N) fold per frame optimized and archived as completed.

#### 3. OBS Overlay Stats Widget Short Stat Labels (Refactor Fixes)

Status: `[Implemented]`

Goal:

- Align stat display names in the OBS Overlay Stats widget with the abbreviated/short label formatting used in the In-Game Overlay Stats widget and Twitch `!chaos` command output.

Problem Analysis:

- **Label Format Inconsistency:** The In-Game Overlay Stats widget and Twitch bot output use compact stat abbreviations (e.g. `abbreviate_stat_label`), whereas the OBS Overlay Stats widget formats stat rows with full names, creating visual clutter in compact OBS browser source layouts.

Shipped Solution:

- `_snapshot_stats` (`src/projections/obs.py`) now emits a `display_label`
  alongside the existing `label`, exactly as the In-Game overlay rows do
  (`projections/in_game_html.py`). `label` stays the canonical full stat name,
  so the stat selector, saved overlay configs and any custom browser-source
  template that keys off it keep working; only the rendered text changes.
- `renderStats` in `src/media/overlay/overlay.js` renders
  `display_label || label` and measures the stats column width from the
  **short** label. That width calculation is where the compactness actually
  lands -- without it the column would stay sized for `Powerup Drop Chance`
  while displaying `PDC`.
- The editor preview stub (`?edit=True`) carries `display_label` too, so the
  preview matches what a live OBS source renders instead of showing full names.
- Covered by `test_overlay_state_stats_use_short_labels` in
  `src/tests/test_overlay_state.py`, which pins both the abbreviated
  `display_label` and the untouched canonical `label`.

Follow-up (same day): the short form is a **per-widget setting**, not a hard
rule. `short_stat_labels` (default `True`) lives on the stats widget config,
is normalized in `core/overlay_config.py`, and is exposed as the
`Short stat names` checkbox in the OBS tab's Widget Settings -> Advanced ->
Stats section. `_snapshot_stats` resolves `display_label` from it, so the
renderer never re-decides; the `?edit=True` demo rows read the same flag out
of `state.widgets.stats` so the editor previews the layout the live source
will actually render. Pinned by
`test_overlay_state_stats_keep_full_labels_when_opted_out` and
`test_overlay_settings_persist_stats_short_label_choice`; both were confirmed
to fail against tampered source.

#### 4. Items Vanishing From Compare Runs (Passive-Item Layout Cache)

Status: `[Implemented]`

Goal:

- Fix intermittent missing items in Compare Runs item lists caused by incomplete passive-item layout cache memoisation.

Problem Analysis:

- **49 gaps total** where a passive item was present, absent for several consecutive 10 s snapshots, then present again.
- **Root cause:** `_read_passive_item_dictionary` (`src/infra/memory/player_stats_client.py`) memoised the dictionary's slot layout and only invalidated it on a `_version` change (a .NET Add/Remove). A slot skipped without a `MemoryReadError` was memoised as clean, keeping dropped items invisible until the next Add/Remove.

Fix:

- An unnameable-but-live slot is treated like a torn entry (`broken_entries += 1`), skipping it for that read and preventing incomplete layout memoisation so it self-heals on the next read.
- Covered by test cases in `test_passive_item_layout_cache.py`.

#### 5. Future Runtime Data Collection Improvements & Core Lifecycle Probe

Status: `[Implemented]`

Goal:

- Preserve core run-history reads (10s full player snapshot & 500ms expected chest inputs) during an active run even when optional UI/overlay consumers are inactive.
- Implement a unified 1-second Core Lifecycle Probe to drive run state (`is_active_run()`, pause, resume, game over) across tasks.

Implementation Details:

- Extracted and implemented `RunLifecycle` service ([app/run_lifecycle.py](file:///f:/Python/MegabonkReroll/src/app/run_lifecycle.py)) with `CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS = 1.0` re-reading runtime activity state once per second and caching `RuntimeGameState`.
- `RunLifecycle.is_active_run()` covers both `IN_GAME` and `PAUSED_IN_GAME`.
- `refresh_tasks.py` uses `lifecycle.is_active_run()` as an always-on core demand predicate for `full_player_snapshot` (10s) and `expected_chest_inputs` (500ms).
- VOD recording auto-start, pause, resume, and completion handling ([app/vod_capture.py](file:///f:/Python/MegabonkReroll/src/app/vod_capture.py)) are driven from `RunLifecycle`.
- Note: Chaos Tome polling optimization remains tracked as a separate open item in `functional_updates.md`.

#### 6. Compare Runs Diff Cards Are a Rich-Text Layout Problem, Not a Compute One

Status: `[Implemented]`

Goal:

- Make a Compare Runs scrub frame cost ~20 ms instead of ~200 ms by changing how the diff cards are *rendered* (switching heavy cards to widget-based `MetricTableView` instead of re-parsing HTML `<table>`s in `QLabel`).

Shipped Behavior & Results:

- Replaced Weapons, Tomes, Chaos cards and the expanded Items per-item table with widget-rendered `MetricTableView` (`src/ui/metric_table.py`).
- Scrub frame rendering time dropped from ~173 ms down to ~32 ms (~5x speedup).
- Cells are created once and pooled; restyling happens only when cell delta direction changes.

---

## Recently Handled Items (Archived 2026-07-23)

### Live Run Refactor Fixes

#### 1. Compare Runs and Recordings Timeline Performance Optimization (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Added `src/ui/throttle.py` with two primitives: `UiUpdateThrottle` (leading-edge
  throttle with a trailing coalesced run, ~30 FPS window) and `batched_updates`
  (a context manager that suspends Qt repaints for a multi-widget update).
- Split all three timeline sliders into two tiers: the timeline captions are
  written immediately on every `valueChanged`, while the heavy render is
  coalesced to one run per throttle window and always renders the value the
  drag stopped on.
  - `CompareRunsTab.on_compare_run_slider_changed` (both side captions, since
    moving one slider time-syncs the other).
  - `RecordingsTab.on_vods_slider_changed`.
  - `RecordingTimelineView.handle_slider_value` (Live Stats recording strip).
- Added an LRU cache (128 entries) for the seven formatted Compare Runs diff
  sections, keyed by both recordings, both indexes, the enabled sections, the
  selected stat labels, and the item-details toggle. Scrubbing back over a
  previously rendered frame reformats nothing. Cleared when a side's recording
  is replaced or the two runs are swapped.
- Added `SnapshotTimeIndex`: snapshot compare-times are sorted once per loaded
  recording so time-sync is a bisect instead of a full scan per slider tick.
  It reproduces the linear scan's `(distance, index)` tie-breaking exactly.
- Added a dirty check on the Compare Runs diff cards, so an unchanged diff --
  common between consecutive game seconds -- does not re-write seven rich-text
  widgets.
- Wrapped the Compare Runs panel refresh and the Recordings snapshot render in
  `batched_updates`, so each does one Qt layout pass instead of one per widget.
- Queued frames are dropped, not merely superseded, when the selection they
  describe disappears: a Compare Runs load error, and loading or clearing a
  recording in the Recordings tab.

Tests:

- `src/tests/test_ui_throttle.py` -- the two primitives, over an injected clock
  and scheduler.
- `src/tests/test_timeline_scrub_performance.py` -- caption/render split on all
  three sliders, the diff cache and its two invalidation events, the dirty
  check, and `SnapshotTimeIndex` parity against the linear scan it replaces.
- Both files were tamper-checked: reverting each mechanism individually fails
  the case that covers it.

Follow-up: per-frame cost with every section enabled (measured, not estimated)

Throttling bounds how *often* a frame renders, not what one costs. With all
comparison sections checked, a frame still ran ~83 ms on a real 713-snapshot
recording -- a ceiling of ~12 FPS no matter how the events are coalesced.
Profiling put effectively all of it in one section:

| section | before | after |
| --- | --- | --- |
| `stage_summary` | 80.85 ms | 10.00 ms |
| the other six, combined | 2.60 ms | 1.08 ms |
| **full frame, all sections** | **~83.5 ms** | **11.08 ms** (~90 FPS) |

`_build_compare_run_stage_summary_rows` rebuilds `build_stage_summary(
snapshots[:index+1])` -- a fold over the whole run from its first snapshot --
twice per frame, once per recording. Inside it, a single frame asked for
~58,000 item-name normalisations of **58** distinct names, and re-parsed every
snapshot's item list on every pass even though snapshots are frozen.

Both were fixed by memoisation alone; no domain logic changed:

- `lru_cache` on `_fold_item_name_for_rarity`,
  `normalize_item_name_for_rarity` and `normalize_item_name_for_display`
  (83 -> 37 ms). The public entry points still accept non-strings, and a `str`
  subclass is converted rather than trusted as a cache key -- it can redefine
  `__hash__`/`__eq__`.
- `lru_cache` on `item_counts`, keyed by the item tuple (37 -> 11 ms).
  **It returns a fresh dict on every call**: `create_stage_item_gain_tracker`
  stores the result as `confirmed_counts` and then mutates it in place, so
  handing out the cached mapping would corrupt every later reader. Unhashable
  item lists fall back to the uncached path.

Both caches are bounded, because item names come from game memory and a
corrupted read would otherwise grow them without limit.

Covered by `src/tests/test_item_lookup_memoisation.py`, tamper-checked:
dropping the defensive copy fails five cases, two of which build a stage
summary end to end.

Known remaining limit: the stage summary is still `O(length of run)` per frame,
so a recording twice as long costs twice as much. Removing that needs either
debouncing the heavy sections during a drag or prefix checkpoints inside
`build_stage_summary`; both were scoped, priced and deliberately deferred.

#### 2. Tracked Items Refresh Latency Optimization (Refactor Fixes)

Status: `[Implemented / Requires In-Game Verification]`

Shipped:

- `PASSIVE_ITEMS_REFRESH_MS = 1_000` and the `passive_items` `RefreshTask`
  (`app/refresh_tasks.py`), resolved through the existing named `PASSIVE_ITEMS`
  source key so a pass where the full snapshot is also due walks the item
  dictionary once. Gated on `_should_refresh_full_player_snapshot`, the same
  predicate the full snapshot uses.
- `LiveRunTracker.update_items` (`core/tracker/live_run.py`), which runs
  `items.process_item_deltas` only. It does not append to the snapshot deque,
  advance the stage index, reset the stage-summary cache or mark features live.
- Transient-empty and run-boundary guards inside `update_items`; memory health
  and the reconnect streak are deliberately left to the full snapshot.
- Halved read cost for the walk itself: `_read_passive_item_dictionary`
  memoises the slot layout (value address + name per slot) and re-reads only the
  stabilised stack counts, validated against the dictionary pointer, entries
  pointer, count and `_version` -- the same quadruple `_get_cached_key_count`
  has used in production. ~4 reads per entry becomes ~2.
- Coverage: `src/tests/test_passive_items_fast_lane.py`,
  `src/tests/test_passive_item_layout_cache.py`. Each guard was tamper-tested.

Still owed: a live run confirming end-to-end latency and that no duplicate or
dropped pickup appears in the OBS overlay, Session Stats or the Twitch output.

Correction to the analysis below: the claim that `current_stage_index` advances
only inside `update()` is **wrong**. `update_fast_stage_timer` also advances it
(`core/tracker/live_run.py`), after a 2-sample confirmation and a stage-timer
reset hold, so fast-lane item events are stamped with a stage index that is
accurate to ~1--2 s. The accepted-inaccuracy caveat that rested on that claim
does not apply. One real gate remains: that fast advance happens inside the
`event_timer` task, whose demand predicate is `_should_refresh_fast_stage_timer`
-- with every stage-timer consumer disabled, the stage index falls back to the
10 s path.

Goal:

- Reduce high latency/delays when updating `Tracked items` in the OBS overlay, Session Stats UI, and Twitch command output after acquiring or leveling up passive items.

Problem Analysis:

- **The real latency is 10--20 s, not 10 s.** Two stages compound:
  - `tracked_items` state relies on `full_player_snapshot`, polled on a 10,000 ms (`PLAYER_STATS_REFRESH_MS`) interval;
  - an item gain is then *confirmed*, not trusted on first sight. `process_item_deltas` holds the raised count as a `_PendingItemIncrease` and credits it only on the next snapshot that agrees (`core/tracker/items.py`). That confirmation is correct -- the game rebuilds its item dictionary in place and a mid-write read can show a transient count -- but at a 10 s cadence it costs a second full interval.
- **One choke point, and it is not the UI.** All consumers read the same `LiveRunTracker` tracked counts through `tracked_item_rows` / `tracked_item_rows_for_rules`: Session Stats (`session_stats.py`), the OBS overlay (`runtime_snapshot().tracked_items`), and the Twitch commands. That field is written only by `process_item_deltas` inside `LiveRunTracker.update(snapshot)`, whose only caller is `refresh_now` on the 10 s task.
- **Transport is already fast; only the value is stale.** OBS overlay state is republished every 500 ms from `_refresh_combat_metrics_task` (when the `kps` or `stage_summary` widget is enabled). No UI plumbing needs to change.
- **Scope correction:** the In-Game Overlay has no tracked-items widget at all. Its widget set is `scanner`, `recording`, `kps`, `powerups`, `luck_rarity`, `stats`, `event_timer`. The affected surfaces are the OBS overlay, Session Stats, and Twitch.

Planned Solution -- read passive items on the fast lane:

- Register a new `RefreshTask` for passive items with its own cadence constant (1,000 ms proposed), not by reusing `FAST_TRACKER_INTERVAL_MS`. This follows the precedent of `RECORDING_LIFECYCLE_REFRESH_MS`, which is its own decision rather than an inherited interval.
- Resolve it through the existing named source key `PASSIVE_ITEMS` (`app/read_sources.py`). This is the point of step 28's composable reads: on every pass where the full snapshot is also due, both consumers share **one** physical read of the item dictionary. No read is duplicated.
- Call the existing `PlayerStatsMemory.read_passive_items_only(owner_stats, context)`; it is already a standalone entry point with `context` threaded through.
- Add a narrow `LiveRunTracker.update_items(...)` that calls `items.process_item_deltas` only. It must **not** call `update()`, which appends to the snapshot deque, advances `current_stage_index`, resets the stage-summary cache, and marks five features live. `update_items` joins the existing family of fast-lane entry points (`update_fast_run_timer`, `track_kills`, `update_powerups`, `track_expected_key_procs`, `update_chaos_tome`, ...).
- Keep the confirmation ladder. At a 1 s cadence it costs one second, and a shorter window between the two reads makes it stricter, not weaker.
- Nothing is removed from `refresh_now`: the full snapshot keeps reading and publishing items exactly as today, so recordings, VOD capture and Stage Summary inputs are unchanged. This adds a second consumer of an existing source; it does not split the existing path.

Required guards:

- Apply the same transient-empty-dictionary protection that `LiveSnapshotStore.merge_items` provides. Without it, one empty read drops `current_count` below the confirmed count and silently discards a pending gain.
- Gate the task on the lifecycle probe's active-run state and on the same demand predicate as the full snapshot (`player_stats_refresh_required`), so no gap appears in data that recordings consume.
- Do not credit items across a run boundary: new-match detection and `reset_for_new_match` currently live on the 10 s path, and the fast task must not attribute a new run's starting inventory to the previous run.
- Stage attribution granularity stays as-is for this change: `current_stage_index` advances only inside `update()`, so an item gained within ~10 s of a stage transition can be stamped with the outgoing stage index. This is accepted here and addressed by the stage-closing snapshot in the next item.

Expected result:

- Detection within 1 s plus one confirmation tick: roughly **1--2 s** end to end, against 10--20 s today.
- Added read cost is approximately 4 reads per inventory entry per tick (~120 reads/s at 30 items), because `_read_passive_item_dictionary` resolves names from `ITEM_ENUM_NAMES_BY_ID` by dictionary key and performs no string reads on the hot path. That is the same order as the fast-lane work already running (powerups, expected chests, Chaos Tome) and smaller than one cold damage-source dictionary walk.

Rejected alternatives:

- **Lowering `PLAYER_STATS_REFRESH_MS`.** The full snapshot reads player stats, weapons, tomes, banishes, damage sources (the cold RunStats dictionary walk), the disabled-item pool and map activity, then repaints Live Stats synchronously on the UI thread. Multiplying all of it to refresh one fact of fifteen is the wrong trade, and `disabled_items` is deliberately a once-per-run read rather than a cadence-driven one. Acceptable only as a temporary stopgap (e.g. 3,000 ms for 3--6 s latency) if a fix is needed before the task exists.
- **Building an inventory-signature/delta detector**, as an earlier draft of this entry proposed. Counted against the source, it does not pay for itself: a signature costs roughly 3 reads per entry (value pointer + count + stable stack count) versus roughly 4 for reading the items outright. A quarter saved buys a new address-cache layer with its own invalidation and its own failure mode. Read the items directly instead.

Validation Requirements:

- Verify that on a pass where both the fast task and the full snapshot are due, the item dictionary is read exactly once (assert on the shared `PASSIVE_ITEMS` key, not on wall-clock timing).
- Cover: pickup detection latency at the new cadence, a level-up (stack count change on an existing entry), a transiently empty dictionary, an `InvalidItemStackCountError`, and a run boundary.
- Tamper-test the new task: disabling it must fail a test. A harness that stubs the 10 s path will otherwise keep passing and prove nothing.

#### 3. Stage Summary Stage-Closing Snapshot (Refactor Fixes)

Status: `[Implemented / Requires In-Game Verification]`

The mechanism this entry proposed already existed, half-built. `update_fast_stage_timer`
detects a stage change on the fast lane with a 2-sample confirmation and a hold
until the stage-timer reset is observed, commits a boundary snapshot to
`_fast_stage_boundaries`, and `_stage_summary_timeline_unlocked` already merges
those boundaries into the list `build_stage_summary` folds over. Time and kills
were therefore already closed to ~1--2 s. Items were excluded by one line:
`_fast_stage_summary_snapshot_unlocked` set `items_available=False`, because
nothing on the fast lane could supply an inventory.

Shipped, as two changes rather than a new subsystem:

- The fast projection now carries the fast-lane inventory when it is fresher
  than `FAST_ITEMS_TTL_SECONDS` (3 s). Expiry withholds the inventory, which
  degrades to the previous behaviour rather than to a wrong one.
- `build_stage_summary` credits a closing snapshot's item gains to
  `previous_stage_index` (`core/run_summary.py`). This is the "Cheap Interim
  Fix" below, and it stops being a heuristic now that the boundary is a
  recorded fact: it reuses the exact predicate the bucket append and the kill
  baseline on the adjacent lines already use.

No new snapshot field and no explicit `stage_boundary="closing"` marker was
added, because the live fold does not need one.

Known gap, and the reason a marker may still be wanted: **recordings do not see
the boundary.** VOD snapshots are captured only on the 10 s path
(`capture(**capture_kwargs)` in `app/player_stats_refresh.py`), and
Recordings/Compare Runs rebuild their own Stage Summary from that list. So the
live Stage Summary is now accurate while the same run replayed from a recording
keeps the old misattribution. Closing that requires persisting the closing
observation into the recording, and the fold must tolerate its absence in
already-recorded runs.

The heuristics this entry proposed retiring -- `is_stage_transition_boundary_snapshot`
and `is_explicit_raw_stage_transition` -- were **kept**. They are what identifies
a closing snapshot in the fold, including for recorded runs that carry no fast
boundary at all.

Goal:

- Attribute items, kills and time to the stage they were actually earned on by recording an explicit *closing* observation at the moment a stage transition is detected, instead of inferring the boundary afterwards from timer heuristics.

Problem Analysis:

- **Item gains on a transition snapshot are credited to the wrong stage.** In `build_stage_summary` (`core/run_summary.py`) the per-snapshot loop advances `current_stage_index` *first*, then credits that snapshot's item gains to the already-advanced index. Everything picked up during the tail of the outgoing stage -- which becomes visible only on the first read taken after the transition -- lands on the incoming stage.
- **Time and kills already get boundary handling; items do not.** The same loop appends the transition snapshot to the *previous* stage's bucket when `is_stage_transition_boundary_snapshot` or `is_explicit_raw_stage_transition` holds, and records a per-stage kill baseline. The item path has no equivalent, which is the asymmetry to close.
- **Gains are credited on first sight.** `update_stage_item_gain_tracker`'s confirmation streak (`PLAYER_STATS_ITEM_DROP_CONFIRMATION_SNAPSHOTS`) applies only to a *falling* count. A rising count is credited immediately, so the very first post-transition snapshot moves the whole tail of the previous stage.
- **The detection signal is already 10x finer than the attribution.** `RuntimeGameState.current_stage_index` is published by the lifecycle probe every `CORE_LIFECYCLE_PROBE_INTERVAL_SECONDS` (1 s) and already reaches `refresh_now`. Stage Summary nevertheless derives stage identity from the `stage_index` field of a 10 s snapshot. The data exists; the mechanism to freeze on it does not.
- **Double counting is not confirmed.** Only misattribution is provable from the code -- item gains are credited once. If a run shows a pickup counted on both stages, capture a trace before designing for it; the likelier source is the separate tracked-item rule path with its own `combo_run_counts`.

Proposed Mechanism:

- On a stage-index change observed by the 1 s lifecycle probe, emit a **closing observation** stamped as belonging to the *outgoing* stage, and begin the new stage from a fresh baseline.
- Carry the boundary as explicit data on the snapshot (for example `stage_boundary="closing"`) rather than leaving it to be re-derived. `build_stage_summary` is a pure fold over the snapshot list and holds no incremental state, so a closing observation is a snapshot inserted into that list with a marker -- not a new state layer and not a new component.
- Once the boundary is recorded fact, retire the heuristics that exist only because it was not: `is_stage_transition_boundary_snapshot` with its `PLAYER_STATS_STAGE_TRANSITION_BOUNDARY_SECONDS` window, and `is_explicit_raw_stage_transition`.

Sequencing -- this depends on item 1:

- The error is produced by the window during which a pickup is invisible, and that window is today the 10 s snapshot cadence. Moving passive items to the fast lane (item 1 above) shrinks it roughly tenfold on its own.
- After that, the closing observation only has to cover the last ~1 s before the transition -- a window in which, by in-game behaviour, nothing can be picked up (stage-entry animations). It can then be a **boundary marker rather than an urgent extra read**, which is materially simpler and safer.
- Recommended order: item 1 first, then this.

Cheap Interim Fix (independent of the mechanism):

- Credit item gains to `previous_stage_index` when the transition snapshot already satisfies `is_stage_transition_boundary_snapshot` -- the same predicate the bucket append on the adjacent lines uses. Two lines, no new concepts, and it rests on the same in-game fact this entry is built on. It closes the bulk of the cases immediately and does not remove the need for the explicit boundary.

Known Limitations and Adjacent Debt:

- **Graveyard is not covered.** Its internal transitions do not change the raw `stage_index`; see item 4 below. Record this as a known gap in scope rather than discovering it on a live run.
- **Two independent item-delta engines.** `process_item_deltas` (`core/tracker/items.py`, confirmation ladder on *increases*, feeds tracked-item rules) and `update_stage_item_gain_tracker` (`core/run_summary.py`, ladder on *decreases*, feeds Stage Summary rarities) consume the same input with different algorithms and different guarantees. This entry fixes the symptom in one of them. Whether to converge them is a separate decision, but until it is made, every fix of this shape has to be applied twice.

Validation Requirements:

- Capture a live trace of a Forest/Desert stage transition recording: the moment `stage_index` changes, the run timer, the stage timer, and the earliest moment an item can actually be acquired on the new stage. **The safe-window assumption ("nothing drops in the first 1--2 s of a stage") is what the whole mechanism rests on and must be measured, not assumed.**
- Cover an item acquired in the final second before a transition, an item acquired immediately after one, and a delayed or dropped read spanning the boundary.
- Verify Stage 1 -> 2, 2 -> 3, 3 -> Boss Room and the late-attach path, and confirm Graveyard behaviour is unchanged rather than silently wrong.

---

## Recently Handled Items (Archived 2026-07-22)

### Live Run Refactor Fixes

#### 1. Active Template Colors In Log Output (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Formatted active template names and score tiers in `[*] Active templates updated live: ...` and `[*] Active tiers updated live: ...` log lines with rich-text/HTML colors corresponding to their template badge and score tier colors.
- Retained colored log formatting across live checkbox updates and mode switches.

Key commits:

- `d3217e2` — Color live template update announcements.
- `c799eb3` — Color live score tier announcements.

#### 2. Default Height For Score Settings Dialog (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Increased the default height/dimensions of the `Score Settings` dialog so the bottom `Save` / `Cancel` button panel is immediately visible without scrolling.

Key commits:

- `cc11cc0` — fix: increase score settings dialog height.

#### 3. Enforce Scanner Start Guarding When Active Rules Are Empty (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Updated score tier checkbox state sync so unchecking all score tiers explicitly saves `active_tiers = []` in configuration.
- Prevented the scanner from starting when all tiers in `Scores Mode` or all templates in `Templates Mode` are unchecked, outputting an explicit error log line (`[-] Error: ...`).

Key commits:

- `59d9480` — Fix empty score tier selection.

#### 4. Restore Magnets Requirement Support in Templates Mode (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Restored target `Magnets` count conditions in template evaluation rules (`Templates Mode`).
- Reused memory read and evaluation paths active for `Magnets` in `Scores Mode`.
- Updated template editor dialog, config schema, evaluation condition matcher, and condensed UI/Twitch preset formatters to support magnet conditions.

#### 5. Synchronize OBS Overlay Edit Mode On Active Widget Toggles (Refactor Fixes)

Status: `[Implemented]`

Implemented scope:

- Automatically update active widget states in the OBS Overlay web editor when toggling checkboxes in BonkScanner UI without requiring users to manually re-enter edit mode.

### Stage Summary

#### 10. Rework Stage Summary Around Fast Runtime Samples

Status: `[Implemented]`

Implemented scope:

- Stage summary boundaries and kill totals are calculated from fast runtime values already read frequently by the application instead of relying solely on the full player snapshot collected every 10s.
- Prevented kills earned near a map transition from being assigned to the next stage due to late snapshot arrival.
- Standardized stage boundary calculation across UI, Twitch announcements, OBS/In-game overlays, and saved recordings.

---

## Recently Handled Items (Archived 2026-07-15)

### Recordings

#### 7. Fix Clean Short Active Run Edge Case

Status: `[Implemented]`

Implemented scope:

- `Clean Short` explicitly excludes the currently active recorder file.
- `PermissionError` and other `OSError` failures on individual files are skipped so the remaining short recordings are still processed.
- The UI reports the number of removed and skipped active/locked recordings.
- Regression coverage verifies that an active file and a locked file remain while other short files are deleted.

Code anchors:

- `src/vod_storage.py`
- `src/gui_player_stats.py`
- `src/tests/test_vod_storage.py`

### Live Runtime

#### 8. Harden The Live Powerup Read Pipeline

Status: `[Partial / Archived]`

Implemented scope:

- Added structured read health for timing, status effects, and `Powerup Multiplier`.
- Incomplete or unavailable powerup reads are rejected before replacing the shared tracker snapshot.
- The existing last-known-good TTL fallback remains active for transient failures.
- Added coverage for hard failures, partial effect lists, empty reads, multiplier failures, recovery, and shared consumer state.

Remaining caveat:

- The snapshot still expires after the compatibility TTL instead of being retained indefinitely until a valid replacement or explicit run reset.
- Runtime diagnostics and full run-reset semantics remain follow-up work.

Key commits:

- `f8b2fcb` — preserve powerup snapshots through transient read errors.
- `db2132d` — harden powerup memory reads and add health validation.
- `5da3844` — prevent auxiliary reads from hiding powerups.

### Recovery Tooling

#### 9. Automated IL2CPP Offset Validator and Handoff Reporter

Status: `[Implemented locally / Pending commit]`

Implemented scope:

- Added local `tools/offset_finder.py` utility.
- Parses IL2CPP `dump.cs` metadata and optional `il2cpp.h` / `script.json` TypeInfo sources.
- Compares configured expectations and reports `matched`, `shifted`, `missing`, `ambiguous`, and `unverified` entries.
- Generates a Markdown validation and handoff draft with manual follow-up sections.
- Remains diagnostic-only and does not patch production source files.

Archive note:

- The `tools/` directory is currently ignored by Git, so this utility is present in the workspace but is not yet included in a commit.

---

## Completed / Done Items (Archived 2026-07-12)

### Twitch Commands

#### 6. `!kps` (Kills Per Second) Tracker

Status: `[Implemented]`

Implemented scope:

- `PlayerStatsClient` caches and validates the `RunStats.stats["kills"]` dictionary entry for lightweight reads.
- `LiveRunTracker` calculates current KPS from a smoothed ~3-second window based on the in-game timer; resets, backwards time, and paused time do not create false progress.
- The Live Stats kills label, VOD snapshots, OBS state, and the configurable `!kps` command consume the shared tracker state.
- `!kps` reports a warming-up/unavailable response instead of a misleading zero before valid samples exist, and is included in `!bonkhelp`.

Archive note:

- Removed from the active list after implementation and automated coverage were completed.

### Runtime Refresh Architecture

#### 8. Split Live Refresh Into Slow And Fast Tracker Lanes

Status: `[Implemented]`

Implemented scope:

- The expensive `full_player_snapshot` runs on the slow player-stats cadence.
- Independent 500ms fast tasks now handle combat metrics/KPS, powerups, expected chest inputs, event timer state, and Chaos Tome tracking.
- Shared `RefreshTickContext` values avoid duplicate client and owner-stat resolution within a scheduler tick.
- `LiveRunTracker` remains the shared fast runtime state consumed by UI, overlays, Twitch, and VOD capture.

Archive note:

- The concrete lane design replaced the original planning/prototype entry.

### In-Game Overlay

#### 1. In-Game Stats Widget

Status: `[Implemented]`

Implemented scope:

- Configurable in-game `stats` widget with cap-aware formatting and colors.
- Forest/Desert use dynamic Difficulty caps by stage and elapsed time plus the fixed `XP Gain` 10x cap; capped values are red and uncapped values cyan.
- Graveyard uses the standard uncapped stat presentation.

#### 2. In-Game Event Timer Widget

Status: `[Implemented]`

Implemented scope:

- Configurable single-line warning and active-wave timer driven by the fast stage-timer lane.
- Covers Forest/Desert boss and wave timings with orange advance warnings and red active-wave state.
- Includes the later Graveyard event-timing extension, while retaining empty output when no relevant event is imminent.

Archive note:

- Both overlay widgets reuse the existing resolved map-family and runtime stage-time paths.

---

## Completed / Done Items (Archived 2026-07-03)

### In-Game Overlay

#### 1. Split `src/gui_in_game_overlay.py` Into Focused Modules

Status: `[Done]`

Goal:

- Reduce the maintenance cost of the in-game overlay code by separating UI window logic, settings UI, and HTML/render helpers into smaller focused modules.
- Keep the shipped overlay behavior unchanged while making future fixes and feature work less risky.

Implemented scope:

- `src/gui_in_game_overlay.py` now acts as the thin coordinator/mixin entry point.
- Overlay widgets were moved into `src/gui_in_game_overlay_window.py`:
  - `InGameOverlayWindow`
  - `DraggableOverlayWidget`
- The settings dialog was moved into `src/gui_in_game_overlay_settings.py`:
  - `InGameWidgetSettingsDialog`
- HTML/string formatting helpers were moved into `src/gui_in_game_overlay_render.py`.
- Existing config keys, signal wiring, and overlay refresh cadence were preserved.

Archive note:

- Removed from the active `functional_updates.md` list after the split was completed.

---

## Archived & Shelved Items (Archived 2026-06-23)

### Stage Summary Must Anchor To Raw Stage Index And Treat Boss As Virtual Stage

Status: `[Archived]`

Goal:

- Make `Stage Summary` deterministic when the app opens in the middle of a run.
- Use the raw memory `stage_index` as the only source of truth for normal map rows.
- Treat boss stage as a separate virtual `Stage 4`, not as a normal raw `stage_index` value.
- Stop `Stage Summary` from starting at row 1 just because the tracker attached late.

Required baseline mapping:

- Raw memory `stage_index` values must map directly to summary rows:
  - `0 -> Stage 1`
  - `1 -> Stage 2`
  - `2 -> Stage 3`
- This mapping is a hard rule, not an inference layer.
- Do not pre-convert the raw value into a human stage number before it reaches live snapshots or summary logic.

Required attach behavior:

- If the app opens during Stage 1, `Stage Summary` starts filling row 1.
- If the app opens during Stage 2, `Stage Summary` starts filling row 2 and leaves Stage 1 empty.
- If the app opens during Stage 3, `Stage Summary` starts filling row 3 and leaves Stages 1-2 empty.
- Late attach must not restart the table from Stage 1.

Boss-stage rules:

- `Stage 4` is not represented by a normal raw `stage_index`.
- Raw `stage_index=2` still means `Stage 3` by default.
- Boss stage must be promoted to virtual `Stage 4` only after an observed transition marker, not from the base raw index alone.
- Do not let a single isolated first snapshot in ghost phase automatically start the table on `Stage 4`.

Allowed boss transition markers:

- Existing timer-based transition markers may still be used.
- Add a dedicated collapse marker based only on raw map activities for:
  - `chests`
  - `pots`
- Valid collapse examples:
  - `chests: 22/46 -> 23/23`
  - `pots: 5/55 -> 5/5`
- These are good boss markers because the reported max collapses downward to the current observed value.

What must not count as boss detection:

- Honest full-clear values on the normal map must not trigger `Stage 4`, for example:
  - `chests: 46/46`
  - `pots: 55/55`
- The critical signal is not `current == max` by itself.
- The critical signal is that `max` shrank relative to the previously observed normal-map baseline.

Implementation constraints:

- Keep the logic split into two layers:
  - normal stage row selection from raw `stage_index`
  - virtual `Stage 4` promotion from explicit boss markers
- Do not merge these into one heuristic that can reinterpret raw `stage_index` based on ghost phase alone.
- Preserve raw `stage_index` all the way through:
  - memory read
  - live snapshot payload
  - live tracker state
  - stage summary builder
- Any human-readable stage number should be derived only at the final mapping point.

Regression coverage required:

- Opening the app on raw `stage_index=1` must fill Stage 2 and leave Stage 3 empty.
- Opening the app on raw `stage_index=2` must fill Stage 3 and leave Stage 4 empty unless a boss marker is observed later.
- Opening the app directly in ghost phase on a normal Stage 2 or Stage 3 map must not automatically start on `Stage 4`.
- A later observed collapse in `chests` or `pots` may promote the run from Stage 3 to Stage 4.
- Persist the “minimum total” marker into recorded/VOD snapshots if recorded summaries must match live summaries.

Archive note:

- Shelved out of the active `functional_updates.md` list.

---

## Completed / Done Items (Archived 2026-06-21)

### Mid-Run `!chests` Recovery And Honest Totals

Status: `[Done]`

Goal:

- Keep `!chests` and the live Chests card useful when the app starts in the middle of a run.
- Avoid inventing exact per-map chest counts for stages that were never observed by the tracker.
- Recover `Paid` and `Key Procs` whenever the cumulative run counters are still mathematically usable.
- Distinguish exact totals from lower-bound totals in the Twitch/GUI output.

Target behavior:

- If the tracker observed the run from the first map:
  - Keep the existing exact behavior.
  - Show exact per-map counts such as `T1:45/46 T2:46/46`.
  - Show exact overall totals such as `Total: 91/92`.
- If the tracker starts mid-run:
  - Show previously missed maps as unknown, for example `T1:--/46 T2:--/46 T3:20/46`.
  - Show the current observed map count exactly.
  - Show overall opened chests as a minimum using a `+` suffix, for example `Total: 51+/138`.
  - Continue showing `Paid` and `Key Procs` if `chestsPurchased` and `chestsBought` are internally consistent with the minimum possible total.
  - Show `Free Chests: --` because inherently free openings from missed maps cannot be reconstructed honestly.
  - Keep `Expected: --` if fast expected-proc tracking did not start from `chestsBought == 0`.

Memory inputs and scope rules:

- Current-map chest progress comes from `MapStat.CHESTS.current/max`.
- Cumulative run counters come from:
  - `RunStats.stats["chestsBought"]`
  - `MoneyUtility.chestsPurchased`
- The game does not expose a reliable always-present cumulative `chestsOpened` run stat in the tested build.
- Because of that, the tracker must treat exact prior-map openings as unknown when the app attaches mid-run.

Implementation rules:

- Detect a mid-run chest attach when the first observed playable snapshot lands on a later map/stage instead of the first playable map.
- Preserve `--` for any map that was not directly observed by the tracker.
- Compute `Total+` as the minimum total consistent with:
  - directly observed current-map openings, and
  - the invariant `chestsPurchased <= chestsBought <= totalOpened`.
- Do not backfill synthetic exact openings into `T1`, `T2`, or other missed maps just to make the invariant pass.

Baseline rules for unknown map totals:

- Use `46` as the default baseline for normal map families.
- If the currently observed map reports `chests_total >= 69`, treat the active map family as the high-total case and use `69` as the unknown-map baseline instead of `46`.
- If the currently observed map reports `chests_total < 46`, clamp unknown-map baseline totals back to `46` instead of propagating boss-room or collapsed values such as `15`.
- This rule exists because normal map families can temporarily report a collapsed chest max in boss-room-like states, while the tested high-total map family keeps reporting `69`.

Current gaps to finish (completed):

- Reconciled raw memory `stage_index` values.
- Re-applied the `Total+` path.
- Restored tests.

---

### Active Powerup Tracking For `!powerups` And Live Stats

Status: `[Done]`

Goal:

- Replace the old duration-only `!powerups` behavior with live active powerup tracking.
- Show active Rage, Shield, Stonks, and Clock/TimeFreeze effects with UI-stage pickup and expiration timestamps.
- Keep the old duration summary as the fallback when no supported powerup is active.
- Reuse the existing fast live tracker loop instead of adding a standalone polling subsystem.

Implemented behavior:

- `PlayerStatsClient` reads the supported effects from `PlayerStatusEffects.statusEffects`.
- `LiveRunTracker` stores a normalized active powerup snapshot and formats both Twitch and Live Stats summaries.
- `!powerups` output when active effects exist:
  - `Powerups: Rage 01:33 -> 00:11 (80s left) | Stonks 01:32 -> 00:10 (81s left) | Clock 01:32 -> 00:27 (64s left) (PM 5.43x)`
- `!powerups` output when no supported effect is active:
  - `Powerups: none active | Durations: standard 81.43s, clock 65.15s (PM 5.43x)`
- Live Stats uses the same tracker state in the existing `Powerups:` row, without adding a separate tab.

Polling and activation rules:

- Powerup tracking runs in the existing fast tracker timer (`FAST_TRACKER_INTERVAL_MS`, currently `500 ms`).
- `Powerup Multiplier` uses a short cached value with forced refresh when the
  active powerup set changes, instead of re-reading the full player stats block
  every fast tick.
- Powerup memory reads are only attempted when a consumer exists:
  - Live Stats tab is active, or
  - Twitch bot is active and the `powerups` command is enabled.
- The Twitch command does not read memory directly; it reads the latest `LiveRunTracker` powerup snapshot.

Confirmed memory and formula details:

- Supported status effect IDs:
  - `1` Rage
  - `2` Shield
  - `3` Stonks
  - `4` TimeFreeze / Clock
- Effect activity is based on `StatusEffect.expirationTime - MyTime.time > 0`.
- Current pickup time is reconstructed as `expirationTime - expectedDuration`, because refreshed effects may keep an old `addedTime`.
- Expected durations:
  - Rage, Shield, and Stonks: `15 * Powerup Multiplier`
  - Clock/TimeFreeze: `12 * Powerup Multiplier`
- UI stage timestamps use `MyTime.stageTimer` and `StageTimeline.stageTime`:
  - countdown: `stageTime - stageTimer`
  - overtime: `+(stageTimer - stageTime)`

Validation:

- Live memory validation confirmed Stage 1, Stage 2, Stage 3, countdown, and overtime formatting.
- Unit coverage was added for:
  - status effect dictionary reads,
  - active/fallback powerup summary formatting,
  - overtime formatting,
  - Twitch command routing through the tracker snapshot.

Known caveat:

- If stage time is manually changed through external cheats, the game UI can temporarily diverge from the normal `MyTime.stageTimer` formula. Normal gameplay matched the documented formula during live validation.

Documentation anchors:

- `docs/recovery/reports/2026-06-20-player-status-effects-and-buffs.md`
- `docs/recovery/reports/2026-06-20-ui-stage-timer-calculation.md`

---

## Part 0: Completed / Done Items (Archived 2026-06-12)

### 0. Twitch Commons Follow-Up Commands

Status: `[Done]`

- The built-in Twitch bot now includes the originally planned follow-up utility commands for chests, disabled items, reroller presets, and command discovery.
- The active `functional_updates.md` file now keeps only the still-open Twitch bot work.

Goal:

- Expand the built-in Twitch bot with common stream commands and chat-facing helpers powered by `LiveRunTracker`, while keeping responses compact and configurable.

Implemented scope:

- `!chests` / `!chest`
  - `LiveRunTracker` stores chest progress by stage plus run totals.
  - The Twitch command returns compact per-stage output and overall totals.
  - Free chest openings are included in the chat response.

- `!disabled`
  - The app reads real disabled-item state from memory once a run exposes the data.
  - Streamers can configure a highlighted subset of important disabled items.
  - The Twitch response stays compact by showing only the highlighted items that are currently disabled.

- Manual commands list command
  - Implemented as `!bonkhelp` with aliases `!bonkcmds`, `!bonkcommands`, and `!bhelp`.
  - The response lists only currently enabled commands.

- `!items` / `!tracked` total count update
  - `Items ({count})` now counts duplicate stacks instead of only distinct item names.
  - Example: `Anvil x2` plus `Soul Harvester x2` contributes `4` to the total count.

- `!presets` / `!preset`
  - The command reports active reroller presets in both `templates` mode and `scores` mode.
  - Templates mode shows the active template names and condensed conditions.
  - Scores mode shows active tiers and score weights.

Code anchors:

- `src/twitch_bot.py`
- `src/live_run_tracker.py`
- `src/player_stats.py`
- `src/gui_dialogs.py`
- `src/gui_twitch.py`
- `src/tests/test_twitch_bot.py`
- `src/tests/test_live_run_tracker.py`
- `src/tests/test_player_stats.py`

---

### 1. Hotkey Improvement - Modifier-Aware Triggering

Status: `[Done]`

- Hotkeys now tolerate configured held gameplay keys such as `W` or `Left Shift` while still rejecting unrelated modifiers for plain hotkeys.
- The active `functional_updates.md` file no longer needs to keep this completed implementation note.

Goal:

- Fix hotkeys that stopped firing when the user held a gameplay key at the same time as the hotkey trigger.

Implemented scope:

- Raw keyboard hook with pressed scan-code tracking.
- One-trigger-per-physical-press behavior for the hotkey trigger key.
- Configurable `GAME_KEYS` whitelist exposed in Settings as `Allowed Held Game Keys`.
- Extra whitelisted keys are accepted only while the game window is active.
- Exact configured hotkeys continue to work globally.
- Left and right modifiers are distinguished through scan codes.
- Only BonkScanner's own hook is removed during reconfiguration or shutdown.

Code anchors:

- `src/hotkey_manager.py`
- `src/gui_run_control.py`
- `src/gui_dialogs.py`
- `src/config.py`
- `src/tests/test_hotkey_manager.py`
- `src/tests/test_gui_run_control.py`

---

## Part 0A: Archived & Shelved Planning Items (Archived 2026-06-12)

### 0. Twitch Commons End-Of-Run Auto Announcer

Status: `[Archived]`

Goal:

- When the player finishes a run or dies, automatically post a full-run summary to Twitch chat.
- Reuse the same run summary data used by existing run tracking and overlay systems where possible.
- Include high-signal totals such as final time, map or stage progress, kills, score or damage-related stats, items, weapons, tomes, and future chest or cap information once implemented.
- Keep the feature optional in Twitch bot settings, because some streamers may prefer manual summaries only.

Archive note:

- Moved out of the active `functional_updates.md` list to keep current Twitch bot work focused on still-open command tasks.

---

## Part 1: Completed / Done Items (Archived 2026-06-02)

### 0. Find A Reliable Runtime Signal For True Menu / Non-Gameplay State

Status: `[Done]`

- Implemented in `src/game_data.py` and `src/gui_player_stats.py`.
- Resolves the issue where stats recording auto-stop could silently fail and keep recording stale snapshots from a dead run context.

Goal:

- Find a stable memory or runtime-logic signal that reliably indicates whether the player is currently in main menu / non-gameplay state, and use it to safely control the recording lifecycle.

Implemented scope:

- Reading `RuntimeGameMode` state directly from game memory (`GameManager`, `MyTime`, `LoadingScreen`, `PlayerMovement`, `MusicController`).
- Auto-stop recording on game over / main menu return, while keeping the recording armed to auto-start the next run.
- Prevent snapshot capturing while paused in game, while keeping the recording file open.

---

## Part 2: Completed / Done Items (Archived 2026-05-23)

### 0. Twitch IRC Chat Bot Integration

Status: `[Done]`

- The integrated Twitch Chat Bot is implemented in BonkScanner UI.
- Twitch account connection, IRC join flow, and chat command handling are already in place.

Goal:

- Let the streamer authenticate with their own Twitch account and run a local embedded chat bot that responds with live BonkScanner gameplay data in channel chat.

Implemented scope:

- UI support for enabling and configuring the Twitch bot
- Twitch auth/connect flow for the streamer's account
- IRC connection and channel join
- Chat commands such as `!stats`, `!banishes`, `!items`, and `!scanner`
- Basic cooldown/moderation-oriented behavior for chat command usage

Why this helps:

- Stream chat can query live run state directly from the local scanner.
- The feature works without any central shared bot service.

---

### 1. Hotkey for Particles Opacity

Status: `[Done]`

- Native hook export and loader support for `ToggleParticlesOpacity` are implemented.
- The optional config knobs for custom `ON/OFF` target values are still not added.

Goal:

- Add a hotkey for `Settings -> Effects -> Particles Opacity`.
- Intended behavior:
  - `OFF` -> set value to `0` if the game safely supports it
  - `ON` -> set value to `0.5` / `50%`
