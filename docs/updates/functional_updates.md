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

#### 4. Powerup Timing: Repeat Pickups and Multiplier Stability (Refactor Fixes)

Status: `[Partial]`

Goal:

- Keep an active powerup's pickup and expiry marks stable while the buff is refreshed by repeat pickups of the same type.
- Stop the Twitch `!powerups` command from reporting `none active` when the reader is merely a tick behind rather than genuinely empty.

Problem Analysis:

- **The game keeps `added_time` at the first pickup.** Re-picking an active buff rewrites `expiration_time` but leaves `added_time` untouched, so `expiration_time - added_time` grows on every refresh. The sanity window that exists to reject records surviving a timer epoch eventually rejected a mark that had been observed continuously, and the pickup mark jumped.
- **The expiry mark is coupled to the pickup mark.** `raw_expiration` looks independent of duration, but `resolve_ui_context` is resolved *from* `pickup_time = expiration_time - duration`. On Graveyard the `pickup_time >= my_time - final_swarm_timer` branch switches the timer between `stage_timer` and the final-swarm clock, so any wobble in the computed duration throws the expiry mark across a phase boundary.
- **The multiplier is not a trustworthy duration source at a repeat pickup.** It is served from a `5s` cache whose only force-refresh trigger is a change in the *set* of active effect ids, and re-picking an already active buff does not change that set.
- **A missed read is not an empty read.** `POWERUPS_SNAPSHOT_TTL_SECONDS` (`1.5s`) empties the snapshot on the first missed tick, and the Twitch handler converted that into the literal string `none active`, which is indistinguishable from a successful read that found nothing.
- **Ruled out:** sampling skew between `stage_timer` and `my_time` was investigated and is not a factor. `get_powerup_tracking_snapshot` reads both back-to-back from the same already-resolved `MyTime` static block, so the pair inside one snapshot is coherent. The `250ms` fast lane publishes a separate `FastStageTimerContext` that `apply_snapshot` never consumes.

Implemented:

- Per-effect observation history in `_PowerupState`, reconstructing "still the same buff" from `added_time`, clock direction, and expiry monotonicity, since the game exposes no instance id.
- An effect's duration is frozen while nothing about it moves, so a single bad multiplier read cannot re-time a buff the game already committed to.
- When the pickup itself is caught, the duration is taken as `expiration_time - added_time`, which the game writes in one frame and which no multiplier read can distort.
- At a repeat pickup the duration is bounded by the game's own numbers rather than by the multiplier: the pickup happened between the previous read and this one, so `expiration_time - my_time <= D <= expiration_time - previous_my_time`. The multiplier is believed only inside that one-tick-wide window.
- A *changed* multiplier must be read twice before it is published, so a one-frame misread never reaches the duration maths.
- `powerups.recent_snapshot` keeps the last read past the strict TTL and marks it `stale`; the Twitch handler now separates fresh, stale, and absent, and never invents `none active`.

Live validation on 2026-07-24:

- 353 ticks over 176s, 10 repeat pickups across 4 effect types.
- `added_time` never moved on a repeat pickup and the pickup mark never jumped; zero reads were rejected. One capture reached `expiration_time - added_time` of 252s against a 224s window, which the previous logic would have rejected.
- One repeat pickup recorded 98.07s for a buff the game had granted 111.6s of, caused by the multiplier cache being a full TTL behind. Replaying the capture through the new bound reduces the worst repeat-pickup duration error from `13.50s` to `0.48s`.
- The maximum gap between reads was `0.505s`, with none above `0.7s`. The powerup snapshot therefore never went stale during the capture, so the Twitch stale and absent branches were never exercised by it.

Second live capture on 2026-07-24, with `Powerup Multiplier` deliberately raised immediately before each repeat pickup:

- 152 ticks over 76s, 3 repeat pickups. `added_time` never moved and the pickup mark never jumped.
- One repeat pickup landed on the last tick before the multiplier cache caught up: memory held `9.136` while the published value was still `8.576`. The bound recorded the granted `136.63s` exactly, where `base * multiplier` would have recorded `128.64s`. Replaying the same capture with the bound removed reproduces that `-7.99s` error, so the branch is confirmed rather than merely unexercised.
- Worst repeat-pickup duration error across the capture: `0.33s`.
- This closes live verification for the repeat-pickup duration bound. The Twitch branches remain unexercised; the maximum read gap was again `0.504s`.

Remaining open work:

- Live-verify the Twitch stale and absent branches. Waiting for a natural stall is impractical at the observed read cadence; this needs `POWERUPS_SNAPSHOT_TTL_SECONDS` and `POWERUPS_SNAPSHOT_GRACE_SECONDS` temporarily shrunk so the branches are reached deliberately.
- The multiplier display and `standard_duration_seconds` can still lag up to the cache TTL at a repeat pickup, for the same force-refresh reason. Effect durations no longer depend on it, so this is cosmetic. The proper fix is to include expiration times, not just effect ids, in `active_signature`.
