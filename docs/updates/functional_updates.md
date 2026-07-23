# Functional Updates

Date: 2026-07-20

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Implemented]` completed and covered by automated tests
- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet


## Open Updates

### Twitch Commands

#### 1. Twitch Commons

Status: `[Partial]`

Goal:

- Expand the built-in Twitch bot with common stream commands and automatic chat announcements powered by `LiveRunTracker`.
- Keep the feature focused on local live-run data that is already needed by Twitch commands and the OBS overlay.
- Prefer configurable command names/messages where streamers may want different wording.

Remaining open work:

- `!shrines`
  - Track the player stat bonuses gained from activating shrines on the current map.
  - Build a fingerprint catalog for every stat value that each shrine type can grant, similar to the existing Chaos Tome fingerprint detection.
  - Detect shrine activations by matching newly added permanent stat modifiers against those fingerprints.
  - Associate every detected shrine-stat event with the current map seed and maintain a per-seed activation counter so the same modifier is not counted more than once.
  - Reset the current-map shrine statistics when the seed changes, while keeping enough event data to produce a compact map summary.
  - The Twitch command should report the accumulated stat gains from shrines on the current map, for example: `Shrines: DMG +20% | Luck +10% | XP +15%`.
  - Fingerprint discovery and live validation are required before implementation to distinguish shrine modifiers reliably from items, tomes, and other permanent stat sources.

#### 2. Charge Shrine Documentation and `!shrines` Groundwork

Status: `[Open]`

Goal:

- Rebuild the Charge Shrine mechanics documentation from the current game dump and verified runtime captures before implementing shrine tracking or a Twitch `!shrines` command.
- Replace speculative or incorrect fingerprint data with values derived directly from `GameAssembly.dll` and confirmed through controlled 15-shrine batches.

Confirmed runtime findings:

- Shrine rewards are written to `StatInventory.permanentChanges`.
- Charging all 15 map shrines produces exactly 15 reward modifiers after the rewards are applied.
- Luck changes the observed rarity distribution.
- Clean batches with `Beacon x0` and `Beacon x1` both produced nominal rarity values; Beacon did not increase reward magnitude in the controlled test.
- Earlier `1.075`-scaled modifiers came from an unidentified source and must not be attributed to Beacon without new evidence.
- Several values in the current reverse document were corrected by runtime tests, including Armor, Evasion, Damage, Crit Chance, Luck, Pickup Range, Projectiles, Extra Jumps, Gold Gain, and XP Gain.

Required reverse-engineering work:

- Revisit `EncounterUtility.GetRandomStatValue` and reconstruct every shrine stat case, base value, and modify type from the current assembly.
- Revisit `EncounterUtility.GetRandomStatOffers`, its rounding path, and rarity selection order.
- Revisit `EncounterData.GetOffers` and `ItemBeacon.GetRewardMultiplier`; explain why static-analysis claims about Beacon scaling conflict with the clean runtime batch.
- Confirm the exact source of the historical `1.075` multiplier.
- Verify the current address and pointer chain for `AchievementTracker.chargedShrines`; the documented TypeInfo RVA did not resolve as a valid IL2CPP class pointer in the tested build.
- Confirm whether the completion counter increments before or after offer selection and whether it is suitable as a delayed-write reward budget.

Validation requirements:

- Run controlled 15-shrine batches with low and high Luck and with Beacon absent/present.
- Snapshot permanent modifiers immediately before and after each batch.
- Require every observed modifier to match a dump-derived fingerprint within float32 tolerance.

- Keep screenshots and exact memory values as fixtures for future automated tests.
- Do not implement `!shrines` until all 28 shrine stat fingerprints and the reward-budget source are confirmed.

Documentation anchor:

- `docs/recovery/reports/2026-06-15-shrines-mechanics-and-fingerprints.md`

#### 3. The One Ring Announcer

Status: `[Open]`

Goal:

- Add an automatic announcer for the Twitch bot that triggers when the player picks up "The One Ring" (in-game name: "Golden Ring").
- Support multiple randomized messages to keep the chat reaction fresh.

Example trigger messages:

- "Ash nazg durbatulûk... One Ring to rule them all, One Ring to find them, One Ring to bring them all, and in the darkness bind them! 👁️🌋"
- "[Streamer's Name] has found The One Ring... Keep it secret, keep it safe! 🧙‍♂️"

From the perspective of Gollum (using his signature speech style):

- "Ssss... Our precioussss! [Streamer's Name] found our precious! *gollum-gollum* 🐟💍"
- "Filthy, tricksy viewerssss want to steal it... But The One Ring is ours now! 👁️" (using "tricksy" as a classic Gollum reference)

#### 4. `!chaos` / `!chaostome` Roll Frequency Statistics

Status: `[Open]`

Goal:

- Extend the existing Chaos Tome tracking so chat can see not only the accumulated total bonuses, but also which Chaos stats have rolled most often and least often.
- Reuse the current per-stat roll counters already maintained by Chaos Tome tracking rather than introducing a second counting system.
- Keep the feature focused on the existing `!chaos` / `!chaostome` command output first, with optional UI exposure later if it proves useful.

Planned implementation notes:

- `LiveRunTracker` already stores the number of tracked rolls per Chaos stat, so the new work should mainly expose and format that data instead of re-detecting rolls.
- Add a structured helper that returns Chaos stat totals together with their roll counts, sorted in the same in-game order already used by the current Chaos summary.
- Decide and document the shipped scope for the frequency window:
  - either current run only;
  - or current BonkScanner session while the app stays open.
- If both views are valuable, keep the user-facing command compact and choose one default output, while leaving room for a second variant or suffix later.
- Example direction:
  - total view: `Chaos Tome Lv37: DMG +84% | Luck +21% | XP +30%`
  - frequency view: `Most rolled: DMG x5 | Luck x3 | XP x2`
- If the command tries to show both totals and frequency data in one message, it must still stay short enough for Twitch chat limits.

Open product decision:

- Confirm whether the first shipped version should report Chaos roll frequency for:
  - the current run only;
  - the whole app session;
  - or both, with one of them clearly marked as the default/stat-friendly view.

#### 5. Free-Chest Loot Tracking and `!chestloot`

Status: `[Open]`

Goal:

- Add a Twitch command (working name: `!chestloot`) and a future in-game overlay
  widget that compare the expected and actually received Epic/Legendary loot
  from free chests dropped by enemies.
- Keep this separate from the existing `!chests` / key-proc statistics: those
  counters describe paid/key chest opens and cannot be treated as the source of
  enemy-dropped chest rewards.

Required investigation and implementation work:

- Find and validate a memory-backed source that reliably signals a *free* chest
  opening after it happens; identify its update timing, reset behavior, and
  whether it can distinguish a free chest from paid, key-proc, reward, or other
  chest-like interactions.
- Record every detected chest-open event with its classified source, at minimum
  `free` versus `paid/key`, so later loot accounting never has to infer the
  source from aggregate counters alone.
- When an item is gained, retain the item event together with its attributed
  source. Attribute it to a chest only when a validated chest-open event and
  the item gain can be matched; leave ambiguous gains explicitly unclassified
  instead of counting them as chest loot.
- Preserve the item's canonical rarity with the attributed event, allowing
  actual Epic and Legendary counts to be calculated from confirmed free-chest
  rewards.
- Capture the Luck-derived rarity probabilities at each confirmed free-chest
  open. Calculate expected Epic/Legendary counts as the sum of those per-open
  probabilities, rather than applying the current Luck value retrospectively
  to all opened chests.
- Define reset and stage-transition behavior, and ensure the command, any
  overlay widget, recordings, and later summaries consume the same event
  ledger.

Validation requirements:

- Produce controlled captures covering a free chest, a paid chest, a key-proc
  chest, and an item gain unrelated to a chest.
- Verify that each capture produces the correct source classification and that
  ambiguous timing does not inflate actual free-chest loot counts.
- Do not ship expected-versus-actual rarity output until the free-chest signal
  and item-source attribution are validated in live runs.

### In-Game Overlay

### Help & Documentation

#### 1. Contextual Help Buttons With Deep Links

Status: `[Open]`

Goal:

- Add more visible `Help` buttons near the relevant UI areas so users can open documentation from the exact place where they need it.
- Make each help button jump directly to the matching documentation section instead of only opening the generic top of the help window.
- Example target behavior: pressing `Help` from the `OBS Overlay` tab should open the help dialog directly on the `OBS Overlay` explanation.

Planned implementation notes:

- Keep the existing help dialog, but add support for opening a specific section/anchor inside the loaded help content.
- Add tab-level help entry points for the main workflow areas, especially:
  - `Templates`
  - `Scores`
  - `Session Stats`
  - `Live Stats`
  - `Recordings`
  - `Compare Runs`
  - `OBS Overlay`
  - `Twitch Bot`
- Add additional in-tab help buttons where a tab contains multiple non-obvious sub-areas or nested tabs.
- Ensure nested areas can still point to the most relevant parent documentation section even if there is not yet a one-to-one subsection for every control.
- Keep the three bundled help files (`ENG`, `UA`, `RU`) aligned so deep-link targets exist consistently across languages.

Why this helps:

- Users will not need to manually search the help text every time they forget what a tab does.
- Feature discovery should improve, especially for `OBS Overlay`, `Recordings`, `Compare Runs`, and Twitch bot setup.
- This should reduce repetitive support questions about the purpose of specific tabs, controls, and nested views.

### Future Runtime Data Collection Improvements

Status: `[Planned / Requires More Verification]`

The current runtime refresh design should preserve a small set of core run-history reads even when optional consumers are inactive. In particular, the following data should remain available for later Live Stats inspection:

- full player snapshot and actual chest/map counters on the existing `10s` cadence;
- expected chest inputs on the existing `500ms` cadence;
- Stage Summary data collected through the normal full player snapshot path.

This avoids losing useful run history merely because Live Stats, OBS, Twitch, and VOD are temporarily disabled. The first manual checks indicate that the current behavior is correct, but the always-on core demand and its exact ownership still need to be implemented and tested separately.

Chaos Tome tracking also requires a follow-up investigation. It may be possible to recover rolls from permanent modifier fingerprints during a later attach or full snapshot, making continuous `500ms` polling unnecessary. Before changing its cadence, add characterization tests for:

- attaching after the Chaos Tome has already reached a higher level;
- multiple modifiers and stacked/aggregated modifier values;
- delayed modifier writes after a level-up;
- transiently missing or failed modifier reads;
- reset at the start of a new run.

If these cases are reliably reconstructed, Chaos Tome can move from the fast lane to the `10s` core snapshot or to a separate slower core task. Until then, keep the existing `500ms` task and external behavior unchanged.

#### Core Lifecycle Probe

The future core-read implementation should resolve the game lifecycle once per `1s` scheduler cycle and reuse the result for all core task demand predicates. `RuntimeGameState.is_active_run` is the authoritative condition: both `IN_GAME` and `PAUSED_IN_GAME` keep the run active, while `GAME_OVER`, `MAIN_MENU`, and `UNKNOWN` disable core memory reads.

The core demand should enable the following existing tasks without requiring an active consumer:

- `full_player_snapshot` at `10s`;
- `expected_chest_inputs` at `500ms`.

Consumer demand remains an additional reason to run the existing optional tasks. The lifecycle probe must be performed once per scheduler cycle, not once per task. If the current runtime-state reader traverses deep memory structures, cache stable type-info, static-field, dictionary, and object pointers while continuing to read dynamic flags (`is_playing`, `is_paused`, and `is_game_over`) fresh. Cache entries must be invalidated when the process, relevant object, or run structure changes.

This is a planned change. The current intervals and lazy-demand behavior remain unchanged until the probe and cache behavior are implemented and measured in-game.

## Live Run Refactor Fixes

#### 1. Tracked Items Refresh Latency Optimization (Refactor Fixes)

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

#### 2. Stage Summary Stage-Closing Snapshot (Refactor Fixes)

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

#### 3. Game-Time Synchronized KPS Calculation (Refactor Fixes)

Status: `[Open]`

Goal:

- Replace the strict ~1-second polling window requirement in `track_ui_kps` with a KPS calculation synchronized exclusively to the continuously increasing `run_timer`. This first iteration deliberately does not cover Event Timer, `stage_timer`, map phases, or stage transitions.

Problem Analysis:

- **Rigid 0.9s–1.2s Sampling Window:** Current `track_ui_kps` evaluates consecutive samples `(run_timer, mob_kills)` and only updates KPS if the game-time delta falls strictly between 0.9 and 1.2 seconds.
- **Baseline Resets on Lag:** If fast-polling delays or timer jitter cause `time_delta` to fall outside 0.9–1.2s, the baseline sample is reset (`state.ui_kps_baseline = current_sample`), causing instant KPS to temporarily drop to zero or disappear from UI widgets.

Proposed Design: KPS Synchronized with `run_timer`

Current instant KPS is calculated from two samples `(run_timer, mob_kills)` and is accepted only when the game time difference falls within a narrow range of `0.9–1.2s`. If fast-polling is delayed or the timer updates unevenly, the time delta strays outside this window, causing the baseline to reset and KPS to temporarily disappear.

We propose abandoning the "must hit exactly one second" constraint. `run_timer` is the source of truth: while it advances, the run is active; while it remains unchanged, the game is paused and the KPS clock must not advance. Application wall-clock time is used only to decide when to perform a memory read, never in the KPS formula.

Live validation on 2026-07-23 confirms that `run_timer` is a smoothly increasing float rather than a once-per-second game value: observed updates occurred every 4.2--58.4 ms (20.8 ms median). Its integer-second boundaries were one local second apart during active gameplay, and a real ~2 s pause left the game timer frozen. Therefore the implementation must observe crossings of game-time seconds, not attempt to catch a hypothetical exact internal second tick.

Algorithm:

1. Store a valid KPS baseline `(baseline_time, baseline_kills)` and the last observed integer second `floor(run_timer)`.
2. Each fast read observes `(run_timer, mob_kills)`.
3. If `run_timer` is unchanged, treat the run as paused. Keep the last displayed KPS and do not advance the KPS baseline or the synchronized game-second cursor.
4. If `run_timer` advances and crosses one or more integer game-time seconds, emit a synchronized KPS update. Compute:
   - `elapsed = run_timer - baseline_time`;
   - `kills_delta = mob_kills - baseline_kills`;
   - `kps = round(kills_delta / elapsed)` when `elapsed > 0`.
5. Replace the baseline with the current sample only after publishing that update. If a delayed fast read skipped one or more game seconds, `elapsed` is larger than one second, but the formula still produces the correct normalized kills-per-second value instead of discarding it.
6. Reset the synchronizer and KPS state on `run_timer` rollback, `mob_kills` decrease, new run start, or game process loss.
7. The first valid sample after reset only establishes the baseline; KPS remains unavailable until enough advancing game time has elapsed to cross the next game-time second.

The initial implementation may use the existing fast-read cadence. A later optimization may schedule denser reads shortly before the predicted next integer `run_timer` boundary, but correctness must not depend on reading at an exact boundary.

Benefits:

- KPS remains strictly anchored to `run_timer` rather than application wall-clock time;
- UI updates follow the rhythm of the game's own elapsed seconds;
- missed or delayed fast-ticks no longer create empty output windows;
- if 1.3, 1.8, or 2.4 game seconds elapse between reads, the result correctly normalizes to kills per second;
- pauses preserve the last valid KPS and do not create false activity or spikes;
- the scope is isolated from stage/map logic, so it can be implemented and characterized independently.

#### 4. Event Timer: Phase-Aware Game-Time Model (Refactor Fixes)

Status: `[Planned / Requires In-Game Verification]`

Goal:

- Build a reliable Event Timer projection from the game timer that is authoritative for the currently active map phase, including normal stages, Graveyard crypts, boss/ghost phases, pauses, timer resets, and timer jumps.

Problem Analysis:

- **`stage_timer` is not a universal run clock:** Normal stages reset it to `0.0` on entry and can force it forward to approximately `530--590s` to trigger Ghost Phase. A reset or a large positive jump is therefore gameplay state, not a read failure or a clock desynchronization.
- **Graveyard has multiple timer families:** Crypt UI countdowns are backed by an upward `crypt_timer`; the main outdoor phase uses `stage_timer`; the post-boss ghost phase is most reliably represented by an upward `final_swarm_timer` that continues across boss-room and portal movement.
- **Raw room identity is insufficient:** On Graveyard, seed, map pointer, stage pointer, and raw `stage_index` remain static through internal transitions. On Forest and Desert, the Boss Room reuses the Stage 3 pointer and raw stage behavior. The active timer cannot safely be selected from pointer or index changes alone.
- **UI semantics differ from raw memory:** A UI countdown may be `duration - raw_elapsed`, while the raw timer itself only increases. Some timer values continue after the UI reaches `00:00`, and Ghost Phase uses a different display rule.

Proposed Model:

Introduce a phase-aware resolver and a per-segment game-time synchronizer:

```text
PhaseTimerResolver
  -> identifies the active phase from timer availability, timer resets/jumps,
     and map/activity context
  -> selects the authoritative raw timer and display policy for that phase
  -> begins a new segment when the phase or source changes

GameTimerSynchronizer (one active segment)
  -> observes (local_monotonic_time, raw_timer_value)
  -> emits crossed whole game seconds while the raw timer advances
  -> treats an unchanged raw timer as pause
  -> predicts the next boundary only to improve read scheduling
  -> never uses wall-clock time as the displayed game time source

EventTimerProjection
  -> converts the synchronized raw value to elapsed / remaining / overtime UI text
```

Phase timer source and display policy should be explicit data, not inferred in rendering code:

| Phase family | Preferred raw source | Raw direction | Typical UI policy |
| --- | --- | --- | --- |
| Normal Forest/Desert stage | `stage_timer` | increasing | remaining time from stage duration, then Ghost Phase/overtime |
| Forest/Desert boss room | `stage_timer` | increasing after reset | remaining time from boss duration, then Ghost Phase/overtime |
| Graveyard crypt | `crypt_timer` | increasing | remaining time from the seed-specific crypt duration; clamp UI at `00:00` if required |
| Graveyard main map | `stage_timer` | increasing | remaining time from the 960s main-map duration, then Ghost Phase formatting |
| Graveyard post-boss swarm | `final_swarm_timer` | increasing | elapsed/phase-specific swarm presentation; preserve continuity across portal movement |

Segment lifecycle:

1. Resolve the best active timer source from map-specific timer availability, timer values, and activity-dictionary markers. Do not rely solely on `map_seed`, `stage_ptr`, or raw `stage_index`.
2. On the first valid read for a source, create a segment and establish its raw baseline; do not invent elapsed time from local clock.
3. While the selected raw timer increases normally, synchronize its integer-second boundaries exactly as in the KPS clock design. Use the local prediction only to optionally increase read frequency near the next boundary.
4. If the raw timer is unchanged, preserve the projected value and mark the segment paused. Resume from the next advancing raw value without adding local elapsed time.
5. If the selected source changes, or the phase detector observes a valid reset, known jump, or confirmed activity transition, close the current segment and start a new one. This is an expected transition, not an error.
6. If a timer rollback or jump has no matching phase evidence, mark the timer state uncertain and re-enter a short calibration/confirmation mode rather than immediately displaying a fabricated countdown.
7. Render the current segment through its explicit display policy. The resolver, not the UI layer, owns phase selection and duration semantics.

Validation Required Before Implementation:

- Capture live traces for every Forest and Desert transition: Stage 1 -> 2, Stage 2 -> 3, Stage 3 -> Boss Room, boss death -> Ghost Phase.
- Capture Graveyard Crypt 1 start/exit, main map entry, Crypt 2 entry, boss entry, boss death, and return through the portal.
- For each trace, record active timer-family values, map/stage pointers, raw `stage_index`, relevant activity dictionary changes, and the visible UI timer.
- Verify seed-specific crypt durations and the exact display behavior at `00:00`.
- Add characterization tests for pause, delayed reads, source switching, timer reset, expected timer jump, and unexplained timer discontinuity.

Benefits:

- Event Timer remains synchronized with game time even when the application is delayed or the game is paused;
- map-specific timer semantics are isolated from generic synchronization mechanics;
- expected stage resets and Ghost Phase jumps no longer appear as false desynchronizations;
- the UI uses one authoritative phase/timer projection instead of duplicating fragile map rules across overlays.

#### 5. OBS Overlay Stats Widget Short Stat Labels (Refactor Fixes)

Status: `[Open]`

Goal:

- Align stat display names in the OBS Overlay Stats widget with the abbreviated/short label formatting used in the In-Game Overlay Stats widget and Twitch `!chaos` command output.

Problem Analysis:

- **Label Format Inconsistency:** The In-Game Overlay Stats widget and Twitch bot output use compact stat abbreviations (e.g. `abbreviate_stat_label`), whereas the OBS Overlay Stats widget formats stat rows with full names, creating visual clutter in compact OBS browser source layouts.

Planned Solution:

- Apply short/abbreviated stat label formatting to `_snapshot_stats` / OBS overlay state projection to maintain visual consistency across all overlay and bot outputs.

#### 6. OBS Overlay "No Game" and Connection Status Audit (Refactor Fixes)

Status: `[Open]`

Goal:

- Audit and refine status handling (`no_game`, `waiting`, `live`) in the OBS overlay server and web frontend (`overlay.js`).

Problem Analysis:

- **Unrefined Status States:** When the game process closes (`no_game`) or waits for attach (`waiting`), OBS overlay widgets currently display generic status cards or raw string replaces, leading to awkward visual layouts when embedded in OBS stream scenes.

Planned Solution:

- Audit state transitions in `OverlayStateStore`, `projections/obs.py`, and `overlay.js` to ensure clean widget hiding, customizable status overlays, and smooth transitions when switching between active run, paused, and `no_game` states.

#### 7. In-Game Overlay Graveyard Difficulty & XP Gain Stat Caps (Refactor Fixes)

Status: `[Open]`

Goal:

- Extend stat capping logic in `_build_in_game_stats_rows` (In-Game Overlay Stats widget) to include the Graveyard map, enforcing XP Gain (10x) and Difficulty (571% for first 2 minutes) stat caps.

Problem Analysis:

- **Graveyard Explicitly Excluded:** `_build_in_game_stats_rows` contains `if not is_graveyard and raw_val is not None:`, which completely bypasses stat capping and cap highlight colors when playing on the Graveyard map.
- **Missing Difficulty Cap for Graveyard:** On Graveyard, the difficulty cap for the first 2 minutes (before 2m ghost spawn) should be 571% (5.71), identical to Tier 1 Stage 0.

Planned Solution:

- Remove `not is_graveyard` exemption in `_build_in_game_stats_rows`.
- Define Graveyard difficulty capping rules (cap at 5.71 / 571% for the first 2 minutes of the stage, matching Tier 1 Stage 0 rules) and ensure XP Gain 10x capping applies to Graveyard as well.

