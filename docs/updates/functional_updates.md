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

#### 5.1. Overlay Chests & Luck-Rarity Widgets Implementation Blueprint

Status: `[Open / Designed]`

Implementation details for future overlay widgets:

- **Chest Overlay Widget (`!chests` live format)**:
  - Displays live total opened chests (`MoneyUtility.chestsPurchased` + free chests), paid openings, free key procs, and inherent free chests.
  - Computes expected key procs cumulatively for each paid attempt $i$ using `ItemKey` hyperbolic probability:
    $$\text{ExpectedFree} = \sum_{i=1}^{N_{\text{paid}}} \frac{0.10 \cdot \text{KeyStacks}_i}{0.10 \cdot \text{KeyStacks}_i + 1.0}$$
- **Luck & Rarity Distribution Widget**:
  - Monitors `PlayerStatsNew` / `StatValue` Luck stat (ID `30`).
  - Records acquired items grouped by `ItemData.rarity` (`1` = Common, `2` = Uncommon, `3` = Rare, `4` = Epic, `5` = Legendary).
  - Computes cumulative expected rarity distribution $E[R_k] = \sum_{j} P(R_k \mid \text{Luck}_j)$ and compares observed item counts against expected values.
- **Dropped Chest & Item Source Classification**:
  - Dropped chests (from Mobs, Bosses, Cacti, Eggs) instantiate standard `InteractableChest` prefabs (`EffectManager.SpawnChest`).
  - Animation skip ("Skip Chest Animation") invokes `ChestUtility.OpenChestNoAnimation()`, which updates memory structures (`chestsPurchased`, `gold`, `ItemInventory.items`) **instantaneously** within a single frame.
  - Item acquisition sources are classified via the **Item Source Elimination Algorithm** (see reverse engineering report [2026-06-10-chests-and-keys-detection.md](file:///f:/Python/MegabonkReroll/docs/recovery/reports/2026-06-10-chests-and-keys-detection.md)), ensuring dropped chests are credited correctly without requiring high-frequency memory polling.

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

### Items Vanishing From Compare Runs (Passive-Item Layout Cache)

Status: `[Fixed / Requires In-Game Verification]`

The report was that some items disappear from the Compare Runs item list for a
stretch and then come back, when a passive item is permanent and should always
be there. It was not a rendering bug -- the holes are in the recorded data.

Evidence (offline audit over four real recordings, scratchpad):

- 49 gaps total where a passive item was present, absent for several consecutive
  10 s snapshots, then present again. One example: `Old Mask` missing for 49
  snapshots (~8 min of game time) in `885к.jsonl`, returning at snapshot 494 in
  a *different* list position than it left -- so the dictionary entry really
  left the read, it was not merely renamed.
- **36 of 49 gaps (73%) end on a snapshot where an unrelated item was
  added/removed**, against an 8% base rate of such snapshots -- ~9x chance. In
  the worst recording, 32 of 33.

Root cause: `_read_passive_item_dictionary` (`src/infra/memory/player_stats_client.py`)
memoises the dictionary's slot layout and only invalidates it on a `_version`
change (a .NET Add/Remove). A slot could be skipped **without** a
`MemoryReadError` -- an unknown enum id plus a class-meta/name pointer that read
as zero that pass makes `_format_item_name` return `None`, and the old code
`continue`d without counting it as a broken entry. That incomplete walk was then
memoised as clean, so the dropped item stayed invisible until the next
Add/Remove moved `_version` -- exactly the 73%/9x signal.

`merge_items` in `src/app/snapshot_store.py` cannot mask this: it only substitutes
the last-known inventory for an *empty* read, and these reads are non-empty (they
are missing one item out of ~40).

Fix: an unnameable-but-live slot is now treated like a torn entry
(`broken_entries += 1`), which both skips it for that read *and* prevents the
incomplete layout from being memoised, so it self-heals on the very next read
instead of on the next Add/Remove. A genuinely free slot (null value pointer)
stays a silent skip, so a normal removal does not disable the layout cache.
Covered by two new cases in `test_passive_item_layout_cache.py`, one of which
fails on the pre-fix code.

Still owed: confirm in a live run that the intermittently-missing item is an
ordinary passive (not a disabled/blessing item read through a different path),
and that the fix holds across an attach mid-run.

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

#### 1. Game-Time Synchronized KPS Calculation (Refactor Fixes)

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

#### 4. OBS Overlay "No Game" and Connection Status Audit (Refactor Fixes)

Status: `[Implemented / Live Verification Owed]`

Goal:

- Audit and refine status handling (`no_game`, `waiting`, `live`) in the OBS overlay server and web frontend (`overlay.js`).

Problem Analysis (what the audit actually found):

The reported symptom was overlay widgets disappearing from the OBS scene during
game restarts. Four separate causes, in descending order of impact:

1. **A single failed poll wiped the whole overlay.** `overlay.js`'s `refresh()`
   catch block replaced `root.innerHTML` with one status card on *any* fetch
   failure, with no retry tolerance. One dropped request -- a server restart, a
   closed keep-alive, a browser-source reload -- emptied the scene and rebuilt
   it from scratch on the next success.
2. **The status card was in the document flow.** `.status-panel` had no CSS rule
   at all, so it rendered as an ordinary `.panel`: in the grid layout it pushed
   every widget down, and in the absolute layout it landed on top of whatever
   occupied the corner. It appears for one or two polls during a restart, and
   that flicker was the visible break.
3. **`stale` fired 5 s into every restart.** `LiveRunTracker._status_unlocked`
   had no grace window between `live` and `stale`, so a routine restart was
   reported the same way as a genuinely stuck feed -- and then hit cause 2.
4. **Non-`live` payloads blanked the widgets to `--`.** The frontend rendered
   whatever the current payload held, with no memory of the last good frame.

Also found: **`no_game` is unreachable in production.** Both production callers
of `mark_overlay_read_failed` pass `no_game=False` hard-coded
(`app/player_stats_refresh.py`), so `_last_no_game_at` is only ever set by
tests. The statuses a user can actually see are `waiting`, `live`,
`reconnecting`, and `stale`. `no_game` handling is kept and logged, but the
original framing of this item as a `no_game` audit was misdirected.

Shipped Solution:

- `LiveRunTracker` gained `reconnect_grace_seconds` (default `10.0`) and a new
  `reconnecting` status between `live` and `stale`. A restart now reads as a
  known-frozen feed rather than an error. `stale` is reserved for silence past
  the grace window.
- `overlay.js` holds the last good frame: run-data fields (`kps`, `stats`,
  `tracked_items`, `stage_summary`, `banishes`, timers, counters) are replayed
  from the last `live` payload while the status is not `live`. Layout fields
  (`widgets`, canvas, `style`) always come from the fresh payload, so the
  overlay editor keeps working.
- `overlay.js` tolerates `OVERLAY_FAILURE_GRACE_POLLS` (6, ~3 s) consecutive
  failed polls without touching the DOM. Past the threshold it only adds an
  `overlay-degraded` class (a slight dim); it never empties the scene again. The
  one remaining case that draws a card is a cold overlay that has never
  rendered, where there is no frame to hold.
- The status card is out of flow (`position: absolute`) and off by default,
  behind `OVERLAY.style.show_status` (default `false`). It cannot move a widget
  under any layout.
- Because the overlay is now deliberately silent, `Overlay` logs one app-log
  line per *transition* into `stale`/`no_game` and one on recovery, and
  `overlay.js` writes one `console.error` when it crosses the failure threshold.
  `reconnecting` is never logged -- it is the expected shape of a restart.

Coverage:

- `src/tests/test_live_run_tracker.py` -- grace window, boundaries, and that
  `no_game` is never masked by `reconnecting`.
- `src/tests/test_overlay_state.py` -- `show_status` default and migration of an
  older `style` block; the status-transition logging rules.
- `src/tests/test_overlay_js.py` + `src/tests/support/overlay_js_check.mjs` --
  the browser behaviour, evaluated under node against a DOM stub. Skips when
  node is absent, so a green suite on a machine without node does not mean the
  frontend was checked.

Remaining work:

- Live verification in OBS across a real game restart: confirm no widget moves,
  no scene empties, and exactly one app-log line appears if the feed stays down.
- No UI control exists for `show_status`; it is config-file only. Add a checkbox
  to the OBS Overlay tab if streamers ask for it.


#### 5. Compare Runs Diff Cards Are a Rich-Text Layout Problem, Not a Compute One

Status: `[Step 1 Implemented / Requires In-Game Verification]`

Shipped: the Weapons, Tomes and Chaos cards, and the Items card's expanded
per-item table, are widget-rendered (`src/ui/metric_table.py`) from `MetricTable`
models built in `projections/formatting.py`.

Before/after, measured **on the real Windows platform plugin** by running the
same benchmark against a pristine worktree at `HEAD` and against the working
tree -- two real recordings, 60 frames at the end of the timeline:

| Frame | before | after |
| --- | --- | --- |
| all sections, Stage Summary on, items collapsed | 153 ms | **68 ms** |
| all sections, Stage Summary off, items collapsed | 165 ms | **34 ms** |
| all sections, Stage Summary off, items **expanded** | 173 ms | **32 ms** |
| everything off but Overview + Stats (the floor) | 24 ms | 25 ms |

The Stage Summary row is item 7's: at the end of a long timeline that card
re-folds the whole snapshot prefix, and the ~34 ms it adds is compute, not
paint.

**The floor is now the dominant term.** With every heavy card off, a frame still
costs ~24 ms, and that is unchanged by this work: it is the whole-tab repaint
`batched_updates` forces plus the two side panels. At 34 ms the frame is also
sitting exactly on `DEFAULT_UI_THROTTLE_MS` (33 ms, ~30 FPS), so the next
worthwhile move is step 2 below plus an attribution of that floor -- not more
card work.

Step 3 is **not** done and is no longer urgent at these numbers.

Measurement caveat, learned the hard way: the per-card attributions further down
were taken with the **offscreen** platform and a standalone label. Offscreen and
Windows agree closely on the full-frame numbers (217/186 vs 153/165 for the same
before-configurations), but a standalone card measured on Windows costs
~0.5 ms -- the cost only appears when the card is inside the tab's scroll area
and its siblings relayout. Treat the per-card table as a **ranking**, and trust
the full-frame numbers for magnitudes.

Two things found while implementing, both worth keeping in mind for any future
widget card:

- The app stylesheet carries a global `QWidget { background: #10141B; }`, and
  giving a widget its own stylesheet routes it through `QStyleSheetStyle`,
  which then paints that background. Every cell must declare
  `background: transparent;` or it tiles its own rectangle over the container's
  painted zebra, leaving a seam in each gap between columns.
- `_format_metric_delta_rich_text` special-cases the exact string `"--"` before
  its sign test. A reimplementation that only checks `startswith("-")` paints
  every missing value red; `delta_direction` in `projections/metric_table.py`
  mirrors the original ordering, and a test pins it.

Goal:

- Make a Compare Runs scrub frame cost ~20 ms instead of ~200 ms by changing how
  the diff cards are *rendered*, not what is computed for them.

Measurements (2026-07-23, the real `CompareRunsTab` built against a real
`QApplication`, offscreen platform, two real recordings of 713 and 744
snapshots; each sample is one `refresh_compare_runs_ui` plus the event-loop pump
that lays out and paints it):

| Frame | median | p90 |
| --- | --- | --- |
| all sections on, Stage Summary **on** | 210 ms | 324 ms |
| all sections on, Stage Summary **off** | 186 ms | 284 ms |
| Stage Summary off, **all other sections off** | 17 ms | 20 ms |

Turning Stage Summary off saves ~24 ms of a ~200 ms frame. Turning the other
four sections off saves ~170 ms. Splitting one such frame:

| Phase | Cost |
| --- | --- |
| `refresh_compare_runs_ui`, Python only | **0.26 ms** |
| the same frame's layout + paint | **14--200 ms** |

Attributed per card (rewrite one card, then pump the loop; offscreen, so read
this as a ranking -- see the caveat above):

| Card | HTML size | Write + relayout + paint |
| --- | --- | --- |
| Items, **expanded** | 19.3 KB, 37 rows, 1 table | **69.8 ms** |
| Chaos | 15.6 KB, 2 tables, 128 cells | **64.9 ms** |
| Weapons | 12.1 KB, 3 tables, 84 cells | **62.9 ms** |
| Tomes | 7.1 KB | **23.3 ms** |
| Stats | 0.5 KB | 2.7 ms |
| Items, collapsed | 1.1 KB | 1.3 ms |
| Overview | 0.4 KB | 0.01 ms |
| A card that is **hidden** | any | **0.00 ms** |
| Side items view (44 items) | -- | 0.09 ms |
| Side snapshot summary | -- | 0.56 ms |

The Items card is the reason a card's *collapsed* cost says nothing about its
expanded one: folded away it is a flowing summary line and among the cheapest
cards; with `Show Item Details` on it becomes a 37-row table and the single most
expensive card of the seven. It is now split accordingly -- the summary line
stays rich text, the table is a `MetricTableView`.

Problem Analysis:

- **The cost is `QLabel` + `Qt.RichText` + `<table>`.** The diff cards are
  `QLabel`s holding HTML built by `_format_compare_metric_table` and
  `_format_grouped_compare_table` (`src/projections/formatting.py`). Qt re-parses
  the whole document and re-lays-out every table cell on each `setText`.
- **Table markup is what costs, not the text.** Re-rendering the same Chaos
  content with the tables flattened to `<br>` rows: **75 ms -> 5.4 ms (~14x)**,
  and the HTML shrinks 15.6 KB -> 2.8 KB. `wordWrap=False` alone gives 75 -> 51 ms,
  so it is the tables, not the wrapping.
- **Cost scales with tables.** Weapons: 1 table 18.6 ms, 2 tables 32.8 ms,
  3 tables 54.8 ms. Chaos's second table (32 stat rows) alone takes it from
  7.6 ms to 75 ms.
- **A hidden card is free; a scrolled-out-of-view card is not.** Setting text on
  a hidden label costs 0.00 ms -- which is why the section checkboxes help so
  much. But the diff column is a `QScrollArea`, and a card that is *visible* yet
  scrolled outside the viewport still pays full layout. In practice only one or
  two cards are on screen while six are being laid out.
- **`batched_updates` is earning its place.** The same frame without it:
  76 ms vs 46 ms. Keep it.
- **The existing dirty checks are already working.** `_set_compare_runs_diff_cards`
  compares the whole payload, and `QLabel::setText` early-returns on identical
  text, so an unchanged card is free. The problem is the frames where the text
  *does* change -- which, mid-drag, is most of them.

Renderer comparison (same content -- 32 rows x 4 columns, header, zebra
striping, right-aligned numbers, coloured delta -- re-rendered once per frame):

| Renderer | Update per frame | Keeps the look? |
| --- | --- | --- |
| A. `QLabel` + `<table>` (as shipped) | 67.3 ms | yes |
| B. `QLabel` + flat `<br>` rows | 6.7 ms | **no** -- loses column alignment and zebra |
| C. Pooled `QGridLayout` of plain `QLabel`s | **3.7 ms** | yes |
| D. `QTreeWidget` | **2.0 ms** | yes |

Collapsed to the 6 rows a folded card would show: A 11.9 ms, C 0.7 ms, D 0.5 ms.
One-off first fill of 32 rows: C 20.7 ms, D 8.9 ms.

**The look does not have to be traded away.** Flattening the markup (B) is the
only option that costs visual quality, and it is also the *slowest* of the three
alternatives. A widget-based table is 18--33x faster than the shipped table and
renders real aligned columns rather than an HTML approximation of them.

Planned Solution, in measured-impact order:

1. **Replace the three heavy cards with a widget-based metric table.** `[Done]`
   Shipped as `MetricTableView` over the pooled-`QGridLayout` variant rather
   than `QTreeWidget`: the cards sit inside a `QScrollArea` already, and a tree
   brings its own scroll area and header into it, plus a stylesheet the app does
   not have. The grid needs no new stylesheet and keeps the column proportions
   the HTML tables used (52/16/16/16), so every card's columns line up with
   every other card's -- which the old markup did not manage between the
   mini-cards and the Chaos tables.
   `formatting.py` keeps producing rows and stops producing markup for these
   cards; `_weapon_compare_metric_rows`, `_tome_compare_metric_rows` and
   `_chaos_compare_overview_rows` were extracted so the HTML formatters (still
   used by `format_compare_runs_diff`) and the models fold over the same rows.
   The two rules that keep it fast: cells are created once and pooled, and a
   cell's colour is restyled **only when it changes** -- the delta by direction,
   and the Items card's label by item colour.
   The Items card is split rather than converted: its summary line (rarity
   delta, and the inline "A/B has more" lists while collapsed) stays a rich-text
   `QLabel`, and only the per-item table underneath is a `MetricTableView`. An
   empty `MetricTable` with an empty caption renders as nothing at all, which is
   what the folded state writes.
2. **Do not write cards that are outside the scroll viewport.** A hidden card
   costs 0.00 ms, but a card that is visible and merely scrolled out of the
   `QScrollArea` viewport pays full layout. Write only the cards intersecting the
   viewport, mark the rest dirty, and flush a dirty card when it scrolls into
   view. The correctness risk is a card left stale after a scroll, so cover the
   scroll-into-view flush explicitly.
3. **Optional after 1: collapse-by-default for Weapons and Chaos.** Items
   already has `Show Item Details`; these two render every weapon and all 32
   Chaos stats unconditionally. Worth much less once the renderer is a widget
   table (0.5 ms collapsed vs 2.0 ms expanded), so treat it as a readability
   choice rather than a performance one.
4. **Rejected: flattening the markup.** Slower than both widget renderers *and*
   the only option that degrades the look. Recorded so it is not re-proposed.

Validation Requirements:

- Re-run the frame measurement above after each step and record the numbers
  here; a step that does not move the median is not worth its diff. `[Done for
  step 1]`
- Verify against a **real** window, not only the offscreen platform: offscreen
  performs the same document layout but not the platform blit, so treat the
  numbers above as a floor. **Still owed:** the shipped numbers were taken
  offscreen, and the look was checked from a real-backend screenshot rather
  than from the running app.
- Assert the rendered *content* is unchanged by step 1 -- same values, same
  ordering, same signs. The row tuples are the contract; test those, not the
  widget, so the renderer stays swappable between the tree and the grid.
- Confirm the delta colour is restyled only on a sign change, by counting
  restyle calls across a scrub. A per-frame `setStyleSheet` would silently undo
  most of the win.
- Check the same rich-text-table shape in the other tabs before assuming it is
  local to Compare Runs: the same formatters back the Recordings and Live Stats
  cards.

