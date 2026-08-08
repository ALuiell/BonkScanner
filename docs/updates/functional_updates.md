# Functional Updates

Date: 2026-07-20

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Implemented]` completed and covered by automated tests
- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet


## Open Updates

### Map Scanner and Scores

#### 1. Optional Stop-on-Player-Movement Safety Guard

Status: `[Implemented]`

Goal:

- Add an optional safety setting that pauses auto-reroll as soon as the player
  presses a movement key after a generated map has been read.
- Prevent a delayed readiness check, long restart, or timeout-recovery path from
  restarting a run after the user has already accepted the map and started
  playing.

Expected behavior:

- Expose a checkbox named `Stop scanning when player moves` in the Auto-Reroll
  settings or another scanner-adjacent location where its current state is easy
  to discover.
- Apply the guard only while auto-reroll is actively scanning. Movement before
  scanning starts, during ordinary gameplay, or while the scanner is already
  paused must have no effect.
- Treat `W`, `A`, `S`, `D`, and `Space` key-down events as player movement.
  Repeated key-down events from a held key must produce only one pause. A key
  that is already held when the map becomes ready must also pause the scan.
- Listen only while the Megabonk window is active, so typing in BonkScanner or
  another application has no effect.
- Arm movement detection only after the current map is confirmed ready, so
  movement input during loading cannot cancel a scan before the map is ready.
- When movement is detected, clear/pause the active scan instead of destroying
  the scanner worker or disconnecting the game client. The user must be able to
  resume deliberately through the existing scan controls.
- Emit an explicit log/status reason:
  `[SAFETY] Player movement detected. Auto-reroll paused.`
- Show `PAUSED — PLAYER MOVEMENT` in the scanner status while this pause is
  active.
- Persist the checkbox choice across launches and enable it by default.
- If the global keyboard hook cannot be registered while the option is enabled,
  fail closed and do not start auto-reroll without the promised guard.

Validation requirements:

- Normal stationary reroll sessions must continue unchanged.
- Deliberate movement input after map readiness must cancel the pending reroll
  before another restart action can be sent.
- Pausing from movement must remain distinguishable in the UI and logs from a
  manual pause, focus loss, connection loss, and `Map took too long` recovery.
- Resuming after a movement pause must discard the previous identity/stats cache
  and read the current map again before evaluation.

#### 2. Signed Shrine Points and Challenge Penalties in Scores Mode

Status: `[Implemented]`

Goal:

- Extend Scores mode from positive rewards only to signed shrine points, so a
  generated map can compensate for undesirable shrines with a sufficiently
  strong Moai/Shady/Boss distribution.
- Keep penalties soft: a negative shrine value lowers the score but does not
  impose a hard maximum or categorically reject the map.

Implemented scoring behavior:

- Add `Challenges` to the configurable Scores fields with a default value of
  `0`, preserving current behavior for existing users.
- Support negative values for every Shrine Points field: `Moais`, `Shady`,
  `Boss`, `Magnet`, and `Challenges`.
- Define signed values consistently:
  - positive value: the shrine adds score;
  - `0`: the shrine count does not affect Score;
  - negative value: each counted shrine subtracts score.
- Keep Moai, Shady Guy, Boss Curses, and the Microwave multiplier as the main
  positive map-value controls.
- Sum rewards and penalties into the base score before applying the Microwave
  multiplier. With example settings, the intended formula is:

```text
Base Score =
    (Moais * 3)
  + (Shady * 2)
  + (Boss * 1)
  - (counted Magnets * 1)
  - (Challenges * 3)

Final Score = Base Score * Microwave Multiplier
```

- Preserve the existing Perfect/Perfect+ Microwave eligibility rules unless a
  separate change explicitly redesigns score tiers.
- Keep Templates maximum conditions separate from score penalties; the former
  are hard filters and are specified in the Templates update below.

Threshold rules:

- Automatic threshold calculation must not lower thresholds merely because a
  penalty became more negative; doing so would partially cancel the penalty the
  user just configured.
- Negative contributions are excluded from automatic threshold scaling.
- Configurations where all Shrine Points are zero or negative require Manual
  Thresholds; the settings dialog rejects them in automatic mode.

Magnet counting rule:

- Positive Magnet points retain the existing cap and count at most two Magnet
  Shrines. Negative Magnet points penalize every counted Magnet Shrine. This is
  stated explicitly in the Scores help dialog.

Validation:

- Automated coverage verifies signed points for every shrine type, uncapped
  negative Magnet penalties, Challenge penalties before the Microwave
  multiplier, zero-value Challenges, and penalty-safe automatic thresholds.

Example target:

- With `Perfect+ = 30`, `Moai = 3`, `Shady = 2`, `Boss = 1`, `Magnet = -1`,
  `Challenge = -3`, and the two-Microwave multiplier at `1.25`, the base score
  must reach `24` before the multiplier. A map with 4 Moais, 5 Shady Guys,
  3 Boss Curses, 1 Magnet, no Challenges, and 2 Microwaves reaches exactly 30:
  `(12 + 10 + 3 - 1) * 1.25 = 30`.

#### 3. Scores Explanation and Configuration UI Revision

Status: `[Open]`

Goal:

- Make Scores understandable without requiring users to reverse-engineer the
  formula, hidden tier rules, or automatic threshold scaling.
- Let a user predict why a map passes or fails before starting a long reroll
  session.

Copy and naming changes:

- Rename `Weights` to `Shrine Points` or another label that communicates that
  the values are added to/subtracted from the map score.
- Add concise inline guidance:
  `Positive values reward a shrine. Zero ignores it. Negative values penalize it.`
- Explain that map generation has a limited shrine-point pool. Challenges and
  other zero/negative-value shrines therefore reduce the useful allocation
  directly or indirectly, without requiring a hard maximum.
- State the Magnet counting rule beside the Magnet field instead of leaving the
  cap implicit.
- Rename or explain `Microwave Multipliers` as a whole-map bonus applied after
  shrine points are summed.
- Explain that the scanner stops when a map reaches any enabled tier. In
  particular, enabling Light allows every Light-or-better map to stop the scan;
  enabling all tiers does not mean the scanner continues until Perfect+.
- Display the additional Perfect and Perfect+ Microwave requirements wherever
  tier thresholds are configured or summarized.
- Explain the difference between automatic and manual thresholds, including
  how automatic thresholds react to changed positive shrine values.

Score preview:

- Add a compact worked example or live preview that lists each contribution,
  the Microwave multiplier, the final score, the selected threshold, and the
  resulting tier.
- Make negative contributions visually distinct and show ignored fields as
  `0`/`ignored` rather than omitting them silently.
- Prefer allowing the preview to use the last scanned map when one is available,
  while retaining a deterministic built-in example for first-time setup.
- When a map reaches the numeric score but fails a hidden tier requirement, show
  that requirement directly, for example:
  `Score reached, but Perfect+ requires 2 Microwaves.`

Validation and compatibility:

- Existing positive-only Scores configurations must keep their current scoring
  results after migration.
- The main Scores tab, settings dialog, scanner log, Session Stats, and Twitch
  preset output should use the same shared terminology and formula summary.
- Numeric inputs must reject invalid/non-finite values instead of silently
  converting them into a different scoring configuration.

Out of scope for this update:

- hard exclusion of every map containing a specific shrine in Scores mode;
- scanning Shady Guy or Microwave visual variants/positions.

#### 4. Maximum Shrine Conditions in Templates Mode

Status: `[Open]`

Goal:

- Allow a template to reject maps containing more than a chosen number of a
  shrine, including a strict `0` maximum for unwanted shrine types.
- Support players who prefer an explicit hard filter over the softer
  trade-off of negative points in Scores mode.

Planned behavior:

- Add optional maximum fields alongside the existing minimum conditions for
  the random shrine counters relevant to Templates: Moais, Shady Guys, Boss
  Curses, Magnet Shrines, Challenges, Microwaves, and Bald Heads where
  applicable.
- Add Challenges as a Template counter so a user can express cases such as
  `Challenges: max 0`.
- An empty maximum means no upper restriction. A maximum of `0` means that
  the map must contain none of that shrine type.
- A template matches only when every configured minimum and maximum condition
  passes. Thus `Moais: min 9` plus `Magnets: max 1` requires both conditions;
  no scoring or compensation is involved.
- Do not expose maximum controls for fixed Grid or Charge Shrine counts.
- Preserve current template behavior for existing saved templates: missing
  maximum fields migrate to unset/no limit.

Validation requirements:

- Reject invalid ranges where a configured minimum exceeds its maximum.
- Show configured maximum conditions in template summaries, export/import,
  scanner target logs, and any UI preview that currently lists minimums.
- Verify OR behavior across active templates remains unchanged: a map is
  accepted when it matches at least one active template in full.
- Verify `max 0` for Challenges and Magnets correctly rejects maps containing
  one or more of the respective shrine.

#### 5. First-Launch Auto-Reroll Setup Guide

Status: `[Done]`

Goal:

- Show every new user a short, one-time setup guide that explains the game
  options required for reliable Auto-Reroll before they attempt to scan maps.
- Prevent hidden or poorly documented setup requirements from making the
  scanner appear slow or unreliable.

Planned behavior:

- Display the guide once on the first application launch and persist its
  acknowledgement so it does not interrupt later launches.
- Keep it focused on Auto-Reroll rather than presenting a full-product
  tutorial.
- Tell the user to open `Settings -> Game` in Megabonk and enable all of:
  - `Quick Reset` — ON;
  - `Skip Portal Animation` — ON;
  - `Super Quick Resets` — ON.
- Explain `Reset Hold Duration` in plain language: it is how long BonkScanner
  holds the configured reset key.
- State that saving `Reset Hold Duration` in BonkScanner writes the matching
  `quick_reset_time` to the game config. BonkScanner keeps a 0.05-second
  safety margin between them for a reliable reset.
- Include a concrete example:

```text
Scanner Reset Hold Duration: 0.26
Game quick_reset_time:       0.21
```

- State prominently that the game must be restarted after changing Reset Hold
  Duration, because it reads `quick_reset_time` when it launches.
- State that the minimum Reset Hold Duration exposed by Settings is `0.10`
  seconds.
- Keep the default `0.05` safety margin configurable for advanced users through
  `RESET_HOLD_SAFETY_MARGIN` in the BonkScanner config. Accept finite values from
  `0.00` through `1.00` and fall back to `0.05` for invalid values.
- Provide a single acknowledgement action such as `Got it`; detailed help may
  remain accessible elsewhere, but the first-launch guide itself must not be
  shown again after acknowledgement.

Validation requirements:

- A clean config shows the guide exactly once.
- Acknowledging the guide persists across application restarts.
- Existing users with an established config do not receive the new-user dialog
  repeatedly after upgrading.
- The wording matches actual configuration behavior: scanner hold duration is
  0.05 seconds higher than the game `quick_reset_time` written by the app.

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
