# Functional Updates

Date: 2026-08-10

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Implemented]` completed and covered by automated tests
- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet


## Open Updates

### Build Progression Overlay Widget

Status: `[Open]`

Goal:

- Add a compact `Build Progression` widget to the OBS Overlay and In-Game Overlay.
- Let each user configure one personal build checklist from scratch. BonkScanner will not ship predefined builds, progression presets, or Early/Mid/Late phases.
- Answer the two questions that matter during a run: what is still missing from the finished build, and whether each timed requirement is still on schedule.

Build definition:

- An item requirement contains an item name, the required copy count, and an optional target game time.
- A stat requirement contains a player-stat name, a minimum target value, and an optional target game time.
- Requirements without a target time remain neutral until completed and still count toward overall build completion.
- The build is complete only while every configured requirement is currently satisfied:
  - current item copies are greater than or equal to the configured count;
  - current stat values are greater than or equal to the configured threshold.
- If an item disappears or a stat falls below its threshold, the build returns to an incomplete state.

Run lifecycle:

- The configured checklist persists between launches and runs.
- Runtime progress, completion timestamps, deadline state, and the `BUILD COMPLETE` state reset for every new game/run.
- Runtime progress must be keyed to the tracker's run identity and must never be written back into `config.json`.

Compact display behavior:

- Show a one-line header with completed/total requirements and the current game time.
- Hide completed rows by default and replace them with a compact `+N completed` summary.
- Sort unfinished timed requirements by the nearest deadline; untimed requirements follow them.
- Support a configurable maximum row count so the widget cannot grow across a large part of the OBS or game canvas.
- When every requirement is satisfied, collapse the widget to `BUILD COMPLETE` with the completion time.
- Keep OBS and In-Game presentation settings independent while both surfaces consume the same configured checklist and evaluated runtime state.

Status semantics:

- neutral/gray: incomplete, but not yet inside the warning window, or no deadline is configured;
- yellow: incomplete and inside the warning window;
- red: incomplete after its target time;
- green: currently satisfied;
- color must always be paired with a symbol or label so status is not communicated by color alone.

Configuration UI:

- Expose one shared `Configure Build Progression` editor from both overlay settings areas instead of maintaining two copies of the build.
- Keep only presentation controls local to each overlay: enabled state, scale, maximum rows, completed-row visibility, target-time visibility, and optional section headings.
- The editor should support adding, removing, and reordering item/stat requirements without introducing build presets.

Runtime and architecture notes:

- Evaluate the widget in a Qt-free build-progression domain/projection layer so OBS, In-Game Overlay, and a future Live Stats preview cannot drift in their completion or deadline rules.
- Reuse `RuntimeStateSnapshot.fast_items` for the freshest available inventory and fall back to `latest_snapshot.items` only when the fast reading is unavailable.
- Reuse `latest_snapshot.stats` initially, but note that the current Stats widget receives those values on the slower snapshot cadence. True real-time stat progress requires a narrow fast path for only the stats selected by Build Progression.
- Publish a fresh run-time value on the runtime snapshot so item counts, deadlines, and displayed time are evaluated from one coherent runtime boundary.
- Add tests for item-copy counting, stat thresholds, optional deadlines, warning/overdue transitions, row ordering, disappearing requirements, run reset, and the all-requirements-complete collapse.

Proposed layouts:

- [Interactive layout comparison](../../ui_mockups/build_progression/build_progression_overlay_options.html) — switch between in-progress, overdue, and complete states and optionally show completed rows.
- [OBS readable compact card](../../ui_mockups/build_progression/build_progression_overlay_options.fragment.html#bonk-obs-title) — bounded translucent card intended to remain legible on stream.
- [In-Game minimal HUD list](../../ui_mockups/build_progression/build_progression_overlay_options.fragment.html#bonk-ingame-title) — frameless, shadowed text intended to stay out of the player's way.
- [Ultra-compact urgent target](../../ui_mockups/build_progression/build_progression_overlay_options.fragment.html#bonk-focus-title) — only the next urgent missing requirement plus overall progress.

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


### Chaos Tome Fingerprint Tracking Optimization

Status: `[Planned / Requires More Verification]`

Goal:

- Explore recovering Chaos Tome rolls from permanent modifier fingerprints during attach or full snapshots, potentially moving Chaos Tome tracking from the continuous `500ms` fast poll lane to the `10s` core snapshot.

Required Characterization Tests Before Implementation:

- Attaching after the Chaos Tome has already reached a higher level;
- Multiple modifiers and stacked/aggregated modifier values;
- Delayed modifier writes after a level-up;
- Transiently missing or failed modifier reads;
- Reset at the start of a new run.

Until these cases are reliably validated, keep the existing `500ms` task and external behavior unchanged.

## Live Run Refactor Fixes

#### 3. Event Timer: Phase-Aware Game-Time Model (Refactor Fixes)

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
3. While the selected raw timer increases normally, synchronize its integer-second boundaries exactly as in the KPS clock design. Use the local prediction only to optionally increase read frequency near the next boundary. Measured constraints for that fine window are recorded in [functional_updates_archive.md](functional_updates_archive.md), under the archived KPS item's "Considered and rejected: chasing the boundary with a variable interval" — a ~7 ms floor from the game's per-frame write, a 13 µs read, and Windows' 15.6 ms timer resolution, which together mean this needs its own thread rather than a faster `QTimer`.
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

#### 4. Reject Partial Passive-Inventory Reads Before Item-Delta Tracking

Status: `[Implemented]`

Goal:

- Prevent transient or partial memory reads from being interpreted as real item losses followed by new pickups.
- Keep legitimate stack increases and genuine remove/re-acquire sequences countable without inflating Session Stats, OBS, or Twitch tracked-item totals.

Problem Analysis:

- `_read_passive_item_dictionary` previously returned the successfully decoded entries even when one or more live dictionary entries could not be decoded. The resulting tuple was a partial inventory, but downstream code received it as an available, authoritative sample.
- An unreadable stack count previously degraded to `x1` on both the full-walk and cached-layout paths. For a real stack such as `Anvil x4`, two consecutive failed reads could therefore appear as a stable decrease to `Anvil x1`.
- `process_item_deltas` deliberately confirms a decrease after a second agreeing sample and lowers its baseline so a genuinely removed item can be counted when it is acquired again. This is correct only when both samples are complete inventory reads.
- Combining those behaviors created phantom pickups. For example, `x4 -> x1 -> x1 -> x4 -> x4` confirmed a loss of three and then credited the same three copies again. Likewise, an entry omitted from two partial dictionary walks was confirmed as removed and credited again when decoding recovered.
- This failure shape has been observed in recorded data: individual items have temporarily disappeared from otherwise non-empty inventories. The existing whole-inventory empty guard cannot protect against a partial tuple that still contains other items.

Implemented Behavior:

1. Treat any walk with `broken_entries > 0` as an unavailable inventory sample. Do not publish the successfully decoded subset as a complete inventory.
2. Treat an unreadable stack count as an unavailable inventory sample instead of fabricating `x1`.
3. Preserve the last confirmed inventory and item-delta baseline when a sample is unavailable. A failed read must produce neither a loss nor a gain candidate.
4. Apply the same validity rule to the uncached dictionary walk, cached-layout path, 1-second passive-item lane, and 10-second full snapshot path.
5. Continue accepting a genuinely empty, successfully read dictionary as an empty inventory where run lifecycle logic requires it; distinguish this from a failed or incomplete walk.
6. Keep actual stack increases countable by `gained_count`, including multiple copies obtained during one run.
7. Keep genuine item removal and later re-acquisition countable once both sides are supported by complete inventory samples.

Implementation:

- The entire passive-inventory read now fails at the memory-client boundary, before it reaches `LiveSnapshotStore` or `LiveRunTracker`. Downstream consumers never receive a tuple with omitted entries.
- An incomplete walk or failed cached stack read invalidates the passive-item layout so the next pass performs a clean rebuild.
- `MemoryReadError` from a stack address now propagates through the existing refresh error path instead of becoming a plausible-looking `x1`.
- Fast and slow consumers share the same source-validity contract, so one lane cannot confirm a decrease produced by a bad sample from the other.
- Rejected samples follow the existing refresh failure path and never reach the tracker, so they cannot create loss or gain candidates.

Regression Coverage:

- A broken entry in an otherwise valid dictionary rejects the entire sample and preserves the previous tracked-item baseline.
- Two consecutive partial reads omitting the same item, followed by recovery, produce no loss event and no additional tracked pickup.
- Two consecutive unreadable stack counts for a real `x4` stack, followed by recovery, leave the tracked total unchanged.
- A torn stack read where the two stabilizing reads disagree remains rejected on both cached and uncached paths.
- A genuine `x1 -> x2 -> x2` increase is still credited once, while holding `x2` produces no further increments.
- A genuine, completely read decrease followed by a completely read re-acquisition remains countable according to the existing tracked-item rules.
- Fast and slow item lanes observing the same rejected sample cannot jointly confirm a false decrease.
