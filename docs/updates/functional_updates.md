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

#### 7. Fix Clean Short Active Run Edge Case

Status: `[Open]`

Goal:

- Ensure the "Clean Short" recordings functionality does not crash when the current active run falls below the snapshot threshold.
- Catch the file lock exception (e.g., `WinError 32` / `PermissionError`) raised when attempting to delete the active recording file, or implement a check to explicitly skip the active run's file during iteration.
- Ensure all other short recordings are successfully deleted even if the active run is encountered and skipped.

#### 8. Harden The Live Powerup Read Pipeline

Status: `[Open]`

Goal:

- Make the full live-data path resilient to transient or incomplete memory reads:
  `memory read -> validation -> normalized snapshot -> Live Stats / OBS overlay /
  Twitch bot / in-game overlay`.
- Prevent a partially read powerup state from replacing the last known-good state
  and making an active `Clock` or `TimeFreeze` effect disappear from every consumer.

Current mitigation:

- Commit `f8b2fcb` keeps the last valid powerup snapshot for `1.5s` when the fast
  refresh path raises a read exception.
- This protects against hard read failures, but it does not protect against a
  successful-looking incomplete read. For example, `get_active_status_effects()`
  can return an empty tuple after a pointer, dictionary, count, or entry read is
  unavailable, and a failed `Powerup Multiplier` refresh can return `None`.
- `LiveRunTracker.update_powerups()` currently accepts those values and writes a
  fresh `available=True` snapshot with no active effects, so the TTL cannot help.

Refactor requirements:

- Separate raw memory reads from interpretation and consumer-facing state.
- Return an explicit read result for each data group, including at least:
  - `available` / `unavailable`
  - `complete` / `partial`
  - a machine-readable failure reason
  - capture timestamp and source/read lane
- Treat `effects=()` as authoritative only when the status-effect dictionary was
  read and validated completely. An empty result caused by a failed or suspicious
  read must not clear the previous active-effects snapshot.
- Treat `powerup_multiplier=None` as a failed dependency for powerup analysis, not
  as proof that no powerups are active. Preserve the last known-good analyzed
  state until a valid replacement arrives or an explicit run reset is detected.
- Keep the source effect model accurate: normal Clock uses the PM-scaled duration,
  while Za Warudo produces the same `TimeFreeze` / `effect_id == 4` status effect
  with a fixed `15.0s` duration. The shared effect ID is an attribution ambiguity,
  not by itself a reason to reject or hide the active effect.
- Ensure all consumers read the same normalized snapshot and do not independently
  reinterpret raw memory values or failure states.
- Add bounded diagnostics for rejected snapshots, especially:
  `status_effects_unavailable`, `status_effects_partial`,
  `powerup_multiplier_unavailable`, `effect_4_missing`, and invalid time fields.
- Add tests for hard read errors, successful-but-empty reads, partial effect lists,
  multiplier read failures, recovery after several failed polls, and explicit run
  resets. Tests should verify that all consumers observe the same last-known-good
  state.

Implementation guidance:

- Keep the current TTL fallback as a compatibility safety net during the refactor,
  but move freshness and validity decisions into the shared snapshot layer rather
  than individual UI refresh handlers.
- Do not add a separate high-frequency inventory scan only to distinguish Clock
  from Za Warudo. Attribution can remain ambiguous in the active-effect snapshot
  and be resolved later from slower item snapshots where required.
- Do not treat Alt+Tab or a single `ReadProcessMemory` failure as a Clock-specific
  diagnosis. Log the failed read category first; the same pipeline should support
  all powerups and all consumers.

#### 9. Automated IL2CPP Offset Validator and Handoff Reporter

Status: `[Open]`

Goal:

- Implement a diagnostic Python utility `tools/offset_finder.py` that verifies memory offsets against a fresh IL2CPP `dump.cs` after a game update and generates a Markdown handoff report for manual follow-up.
- Reduce repetitive VS Code and Cheat Engine audit work by comparing expected classes and fields against the dump-derived metadata without attempting to automatically rewrite the production code.

Planned future work:

- **Expectations Config**:
  - Store the expected runtime offsets in a dedicated config file instead of deriving expectations from ad-hoc scans of the Python source.
  - For each tracked entry, record the code constant id, target class name, field name, offset kind, current expected offset, source file, and optional notes.
  - Cover the classes and fields that the application relies on, such as `MapController.currentStage`, `PlayerInventory.statusEffects`, and `StatusEffect.expirationTime`.
- **IL2CPP Dump Parsing**:
  - Load the `dump.cs` file produced by the IL2CPP Dumper and extract class definitions, static fields, instance fields, and their hexadecimal offsets.
  - Prefer a small structured parser around the `dump.cs` layout instead of relying on one large fragile regular expression.
- **Verification and Audit Output**:
  - Compare the parsed offsets against the expectations config and report whether each entry is `matched`, `shifted`, `missing`, or `ambiguous`.
  - Include the old and newly observed offsets for shifted entries, and clearly flag entries that require manual review due to field removal, renaming, or multiple candidates.
  - Keep the tool strictly diagnostic for the first version; it should not patch `src/game_data.py`, `src/player_stats.py`, or other source files in-place.
- **Handoff Reporting**:
  - Generate a Markdown report summarizing all checked entries, including sections for matched offsets, shifted offsets, missing fields, ambiguous matches, and suggested manual code updates.
  - Match the report structure and wording expectations of `docs/recovery/HANDOFF_TEMPLATE.md` so the output can be reused directly for manual verification in Cheat Engine and for updating the recovery guides.

Scope guardrails:

- Treat this utility as a metadata validator and handoff generator, not as a full runtime recovery tool.
- Do not treat a `dump.cs` match as proof that the full live memory path still works at runtime; dictionary layouts, object roots, and runtime behavior may still require manual verification.
- Defer any future auto-patching work unless the project later adopts explicit, tightly controlled source annotations for safe one-to-one offset replacement.

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
