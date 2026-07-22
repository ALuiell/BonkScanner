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

#### 1. Active Template Colors In Log Output (Refactor Fixes)

Status: `[Open]`

Goal:

- Format template names in the `[*] Active templates updated live: ...` log line with rich-text/HTML colors corresponding to their template badge colors instead of plain white text.

#### 2. Default Height For Score Settings Dialog (Refactor Fixes)

Status: `[Open]`

Goal:

- Increase the default height/dimensions of the `Score Settings` dialog so the bottom `Save` / `Cancel` button panel is immediately visible without scrolling.

#### 3. Enforce Scanner Start Guarding When Active Rules Are Empty (Refactor Fixes)

Status: `[Open]`

Goal:

- Prevent the scanner from starting or rerolling when all tiers in `Scores Mode` or all templates in `Templates Mode` are unchecked.
- Display an explicit error log line (`[-] Error: ...`) when attempting to start with no active evaluation rules.

#### 4. Synchronize OBS Overlay Edit Mode On Active Widget Toggles (Refactor Fixes)

Status: `[Open]`

Goal:

- Automatically update active widget states in the OBS Overlay web editor when toggling checkboxes in BonkScanner UI without requiring users to manually re-enter edit mode.

#### 5. Force Cache Invalidation / Forced Sync For OBS Overlay (Refactor Fixes)

Status: `[Open]`

Goal:

- Add an automated forced sync or cache-invalidation signal so configuration changes made in BonkScanner UI update the OBS browser source without requiring a manual browser cache reset.

#### 6. Compare Runs and Recordings Timeline Performance Optimization (Refactor Fixes)

Status: `[Open]`

Goal:

- Eliminate UI lag during timeline slider movement and detail inspection (`Show Details` / `Show All`) in `Compare Runs` and `Recordings` tabs when working with large recording logs or enabling multiple comparison cards.

Problem Analysis:

- **High-frequency `valueChanged` Events:** Dragging `QSlider` triggers `on_compare_run_slider_changed` / `on_player_stats_slider_changed` per pixel of mouse movement (hundreds of events per second).
- **Synchronous Heavy Diff Calculations:** Every slider tick synchronously executes binary search time-sync (`_nearest_snapshot_index`), overview summaries, and up to 7 formatting functions (`format_compare_runs_overview_diff`, `stats_diff`, `items_diff`, `stage_summary_diff`, `weapons_diff`, `tomes_diff`, `chaos_diff`).
- **GUI Layout Thrashing:** Synchronous string/HTML updates to dozens of `QLabel` and `QTextEdit` widgets trigger continuous Qt layout passes and redraws in the main UI thread.

Planned Optimization Strategies:

1. **Slider Event Throttling & Debouncing (Rate-Limiting Updates):**
   - Update lightweight time labels (`Timeline: 01:23 / 02:45`) immediately on every slider tick for maximum responsiveness.
   - Throttle heavy Diff calculations and UI card updates to 30–60 FPS (16–33 ms interval via `QTimer.singleShot` / `QElapsedTimer`).
   - Apply debouncing during rapid continuous drag, deferring full detailed diff rendering until a brief pause in slider movement.
2. **Diff Result Caching & Memoization:**
   - Implement an LRU cache for `diff(snapshot_a_index, snapshot_b_index, active_sections_mask)`.
   - When scrubbing back and forth over previously calculated frames, return cached diff structures in $O(1)$ time without re-formatting HTML strings.
3. **Lazy Evaluation & Selective Section Updates:**
   - Skip formatting and diff calculation for sections that are collapsed, disabled, or hidden by user settings.
   - Perform dirty-checking against previous snapshot values to skip updating UI sections whose underlying domain data has not changed between consecutive seconds.
4. **Snapshot Pre-Indexing:**
   - Pre-build lookup dictionaries (e.g. item ID maps) during VOD load so snapshot diffs compare pre-indexed keys rather than traversing item lists on every slider tick.
5. **Batching Qt Layout Redraws:**
   - Wrap multi-widget updates in `setUpdatesEnabled(False)` / `setUpdatesEnabled(True)` around card updates to ensure Qt performs a single render pass per frame instead of multiple micro-updates per widget.

#### 7. Restore Magnets Requirement Support in Templates Mode (Refactor Fixes)

Status: `[Open]`

Goal:

- Restore the ability to configure target `Magnets` count conditions in template evaluation rules (`Templates Mode`).
- Reuse the existing memory read and evaluation paths already active for `Magnets` in `Scores Mode`.
- Update the template editor dialog, config schema, evaluation condition matcher, and condensed UI/Twitch preset formatters to include magnet conditions.



