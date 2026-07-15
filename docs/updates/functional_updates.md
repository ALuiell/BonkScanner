# Functional Updates

Date: 2026-06-04

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Implemented]` completed and covered by automated tests
- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet


## Open Updates

#### 6. Extend Scores For The 69-Chest Map Family

Status: `[Open]`

Goal:

- Keep current legacy score behavior stable while planning a dedicated score extension for the 69-chest map family.
- Extend score mode later with raw `Microwaves` and `Bald Heads` for the map family that actually exposes those values in memory.

Planned future work:

- Add a dedicated score path for the 69-chest map family instead of reusing the legacy OCR-era microwave normalization everywhere.
- Decide whether the 69-chest map family should use distinct score weights, thresholds, or both.
- Add `Bald Heads` as a score input only for the map family where it exists.
- Keep legacy score tiers backward-compatible for older maps unless there is an explicit rebalance pass.

#### 10. Rework Stage Summary Around Fast Runtime Samples

Status: `[Open]`

Goal:

- Rework the Stage Summary card so stage boundaries are calculated from runtime
  values that the application already reads frequently, instead of relying only
  on the full player snapshot collected every `10s`.
- Prevent kills earned near a map transition from being assigned to the next
  stage merely because the first snapshot after the transition arrived late.

Planned future work:

- Make the existing fast kill counter the shared source of truth for Stage
  Summary totals and stage-transition boundaries.
- Evaluate using the already available fast run timer and stage timer/index reads
  to record a precise boundary sample when the player enters the next stage.
- Keep slower snapshot data for values that are not already available through a
  fast read, such as the detailed item summary.
- Avoid adding duplicate memory reads: reuse the fast values already collected
  for KPS and event timing, and inject their latest valid values into recordings
  and other consumers where needed.
- Ensure the Stage Summary card, Twitch stage announcements, OBS/In-Game
  overlays, and saved recordings all use the same stage-boundary result.
- Add transition tests where the last `10s` snapshot is taken shortly before the
  player changes maps and the next full snapshot is already several seconds into
  the following stage.

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
