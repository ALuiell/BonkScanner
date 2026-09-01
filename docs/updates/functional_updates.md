# Functional Updates

Last reviewed: 2026-09-01

This file tracks open and partially completed functional/runtime work that does not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Implemented]` completed and covered by automated tests
- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## Open Updates

### Engineering & Delivery

#### 1. Windows CI and Release Automation

Status: `[Open]`

Goal:

- Add a GitHub Actions workflow for the Windows application so pull requests and
  changes on `main` run the same meaningful checks used locally before release.
- Turn the current manual EXE/release procedure into an observable, repeatable
  release path without changing the application's runtime behavior.

Planned implementation notes:

- Run the unit and architecture-ratchet suites on a Windows runner, including
  bootstrap/config import-safety checks and the shutdown/VOD compatibility set.
- Keep desktop-only WinAPI/game integration tests outside ordinary hosted CI;
  expose them as a documented manual or self-hosted validation stage instead.
- Add a release job that uses the repository's existing build entry point,
  validates the produced `BonkScanner.exe`, publishes checksums and attaches the
  verified artifact to a tagged GitHub release.
- Pin Python and build dependencies deliberately, cache only reproducible inputs,
  and make failures retain useful test/build diagnostics.
- Add signing as a separate gated step once certificate ownership and secret
  storage are decided; do not silently publish an unsigned artifact as signed.
- Keep the existing crypto-support Pages deployment independent from the desktop
  application CI/release workflow.

Acceptance direction:

- pull requests cannot merge with failing application tests;
- a tagged release produces one traceable artifact from a clean checkout;
- the release reports test, build, checksum and signing status explicitly;
- packaged-EXE smoke validation remains visible as either verified or pending,
  never inferred from a successful source test run.

#### 2. Behavior-Preserving Decomposition of Large Modules

Status: `[Open]`

Goal:

- Split the remaining oversized production and test modules along the ownership
  boundaries established by the runtime/config/shutdown refactor.
- Improve navigation and reviewability without combining the work with feature
  changes or another architectural rewrite.

Planned implementation notes:

- Re-measure the largest modules after the current architectural cycle lands and
  prioritize files with multiple independent responsibilities or very broad test
  fixtures.
- Extract cohesive components behind the existing typed ports and DTOs; preserve
  public imports through explicit compatibility exports only where callers still
  require them.
- Move tests with their owning subsystem and replace monolithic shared fixtures
  with focused builders, while retaining the current architecture ratchets.
- Perform the work in small, behavior-neutral steps with targeted tests after
  every extraction and the full suite at the end.
- Do not use line-count reduction alone as success: ownership, dependency
  direction and discoverability must improve, with no new ambient state or
  owner-based service resolution.

Acceptance direction:

- each extracted module has one clear responsibility and an explicit owner;
- no user-visible behavior, config/VOD format or refresh cadence changes;
- architecture ratchets and the full Windows test suite remain green;
- compatibility facades introduced for migration are tracked for later removal.

### Native In-Game Overlay

#### 1. Upgradeable Weapon Stat Tracker

Status: `[Open]`

Research baseline:

- The formulas and current-build memory semantics are confirmed in
  [the Weapon Tracker formula report](../recovery/reports/2026-09-01-weapon-tracker-stat-formulas.md).
- The first implementation must use that report as its formula source instead of
  re-deriving weapon behavior or expanding the list of supported stats.
- The accepted refresh cadence is the existing full player snapshot, currently
  up to 10 seconds. A new 500 ms or 1-second weapon memory lane is not part of
  this update.

Goal:

- Add one movable `Weapon Tracker` widget to the native In-Game Overlay.
- Show the final effective values of selected upgradeable stats for every
  currently acquired weapon.
- Combine each weapon-side value with the matching general player stat exactly
  once.
- Keep the widget useful when Scanner, Live Stats, recording, OBS Overlay and
  Twitch are all disabled.
- Keep the feature deliberately narrow: it is a compact player-facing stat
  display, not a simulation of every weapon's attacks.

Confirmed product scope:

- This update is for the native In-Game Overlay only.
- Live Stats, recordings/VOD playback, OBS/browser overlays and Twitch commands
  must not gain a new Weapon Tracker surface in this implementation.
- Use one draggable block containing all matching acquired weapons. Do not
  create a separately positioned widget for every weapon.
- Show weapon names; do not add icons.
- Use the reader's existing stable `weapon_id` ordering. Do not add sorting,
  pinning, per-weapon selection or row-limit settings.
- Show only final values. Do not show `weapon + global = final` breakdowns.
- Do not highlight changed values.
- The only supported metrics are:
  - `Damage`;
  - `Projectile Count`;
  - `Size`;
  - `Duration`;
  - `Crit Chance`;
  - `Crit Damage`.
- Explicitly exclude Projectile Speed, Attack Speed, Knockback, Projectile
  Bounces, pellet counts, burst counts, secondary-hit multipliers, DoT ticks,
  attack cadence, DPS and other weapon-specific behavior.

Visibility rule:

- A metric is eligible only when all of the following are true:
  1. the user enabled it in Weapon Tracker settings;
  2. its stat ID exists in `weapon.upgrade_stat_ids`;
  3. `weapon.full_stats[stat_id]` and every required general component are
     readable and finite.
- `weapon.upgraded_stats` is not the numeric source. It is a filtered view of the
  upgrade pool; the current weapon-side value must come from `full_stats`.
- Hide an unavailable metric instead of inventing `0`, `1` or `--`.
- Hide the entire weapon when no metric remains after filtering.
- If no weapon remains, hide the whole widget outside Edit Layout.

Configuration contract:

```python
"weapon_tracker": {
    "enabled": False,
    "x": 10,
    "y": 220,
    "scale": 1.0,
    "layout": "compact",
    "selected_stats": [
        "damage",
        "projectile_count",
        "size",
    ],
}
```

- The widget itself is disabled by default, like other optional native-overlay
  widgets.
- `Damage`, `Projectile Count` and `Size` are selected by default.
- `Duration`, `Crit Chance` and `Crit Damage` are available but off by default.
- All six checkboxes are independent; `Crit Chance` and `Crit Damage` are not a
  single combined toggle.
- An explicitly saved empty `selected_stats` list is valid and means that the
  user disabled every metric. Config normalization must not replace it with the
  default list.
- Missing `selected_stats` in an old config receives the three defaults.
- Normalize the list by dropping unknown keys and duplicates, then restore the
  canonical display order:
  `damage`, `projectile_count`, `size`, `duration`, `crit_chance`,
  `crit_damage`.
- Supported layouts are `compact` and `detailed`. Missing or invalid values
  normalize to `compact`.
- Reuse the existing `enabled`, `x`, `y` and `scale` normalization and
  persistence path.

Expected rendering:

- `Compact` is the default. Each weapon occupies one line, the weapon level is
  omitted, and selected metrics follow the name:

  `Katana  DMG 100 · PROJ 2 · SIZE ×1.4`

- `Detailed` renders the weapon name and `Lv.N` first, then its metrics on
  separate lines below it.
- Use short English labels:
  `DMG`, `PROJ`, `SIZE`, `DUR`, `CRIT` and `CRIT DMG`.
- Format values as:
  - Damage: ordinary number;
  - Projectile Count: integer;
  - Size: multiplier, for example `×1.4`;
  - Duration: seconds, for example `3.5s`;
  - Crit Chance: percentage, for example `25%`;
  - Crit Damage: multiplier, for example `×2`.
- Keep at most two useful decimal places and remove insignificant trailing
  zeroes.
- Do not clamp Crit Chance to 100%; values above 100% are valid in the game.
- Escape weapon names and all dynamic text before inserting them into Qt rich
  text.

Edit Layout and empty states:

- Outside Edit Layout, do not render the `Weapons` heading.
- In Edit Layout, keep a visible draggable block headed `Weapons` even when no
  weapon rows can be rendered.
- Use these exact status messages under that heading:
  - `No Weapon Stats Selected` when `selected_stats` is empty;
  - `Waiting for Weapon Data` before the first successful weapon sample;
  - `No Matching Weapon Stats` after data is available but filtering produces
    no rows.
- A temporary read failure after a successful sample keeps the last confirmed
  values without adding a `STALE` badge.
- Death/completed-run state keeps the last confirmed values.
- A confirmed new run clears the previous run's last-known weapon state and
  returns to waiting until the new run provides data.
- Preserve the overlay's existing focus behavior: when other native-overlay
  widgets are hidden with the game window, Weapon Tracker is hidden with them.

Effective-stat formulas:

| Metric | IDs and inputs | Final value |
| --- | --- | --- |
| Damage | weapon `W[12]`, general Damage `G[12]` | `W[12] * G[12]` |
| Aegis Damage | Aegis ID `7`, `W[12]`, general Thorns `G[3]` and Damage `G[12]` | `(W[12] + G[3]) * G[12]` |
| Projectile Count | `W[16]` and general Projectile Count `G[16]` | `trunc(max(1, W[16] + trunc(G[16])))`, with truncation toward zero |
| Size | `W[9]` and general Size `G[9]` | `W[9] * G[9]`, then `min(value, maxSizeMultiplier)` when the weapon cap is greater than `1` |
| Duration | `W[10]` and general Duration `G[10]` | `W[10] * G[10]` seconds, then `min(value, maxDuration)` when the weapon cap is greater than `0` |
| Crit Chance | `W[18]` and general Crit Chance `G[18]` | `W[18] + G[18]`; multiply by `100` only for percentage display |
| Crit Damage | `W[19]` and general Crit Damage `G[19]` | `2 * (W[19] + G[19])` |

Formula boundaries:

- Weapon `full_stats` already contains base weapon values, accepted level-up
  modifiers and weapon-passive modifiers such as Dice Crit Chance. Do not add
  any of those a second time.
- General player stats are not already included in `full_stats` and must be
  applied exactly once.
- For Shotgun ID `29`, show the same underlying Projectile Count formula as
  every other weapon. Do not display its hardcoded attack quantity, pellet
  burst count or damage-distribution term.
- Damage is the stable non-crit weapon hit stat. Do not fold Crit Chance, Crit
  Damage, target context, execute chance, big hits or secondary effects into it.
- Size and Duration caps are internal calculation details. Do not add cap
  labels, warnings or settings to the widget.

Planned implementation:

1. Shared calculation model

- Add a Qt-free module such as `src/core/stats/weapon_tracker.py`.
- Define the six stable metric keys, stat IDs, short labels, display formats,
  canonical order and default-selected set in one registry.
- Add immutable projection values for one calculated metric and one weapon row.
  A row should carry `weapon_id`, `name`, `level` and an ordered tuple of final
  metrics; it should not carry HTML.
- Implement one pure function that accepts a `WeaponSnapshot`, coherent general
  stats and selected metric keys, applies the visibility rule and returns either
  a row or `None`.
- Keep formula dispatch explicit by metric key/stat ID. Do not implement a
  generic “multiply every weapon stat by the general stat” rule.
- Reject missing and non-finite operands locally. One unavailable metric must
  not discard other valid metrics for the same weapon.
- Put tracker-specific display formatting beside the calculation/projection
  model or in `src/projections/weapon_tracker.py`. Do not reuse a generic
  multiplier formatter for Duration because the final unit is seconds.

2. Weapon cap acquisition

- Extend `WeaponSnapshot` in `src/core/stats/types.py` with optional
  `max_duration` and `max_size_multiplier` values, defaulting to `None` for
  compatibility with old constructors and recordings.
- In `PlayerStatsClient._read_weapon_snapshot()`, read both floats from the
  already resolved `WeaponData` object:
  - `maxDuration` at offset `0x8C`;
  - `maxSizeMultiplier` at offset `0x90`.
- Validate the reads as finite floats. Preserve negative sentinel values because
  they mean “cap disabled”; do not convert them to zero.
- Do not add another weapon dictionary walk. The cap reads belong to the
  existing full weapon sample.
- Update WeaponSnapshot serialization/deserialization to round-trip the two
  optional fields without exposing Weapon Tracker in recordings. Older records
  without the keys must continue loading as `None`.
- A failed weapon entry must not be published as a confidently complete new
  inventory. Propagate an unavailable weapon pass so the existing last-known
  merge can retain the previous complete sample instead of temporarily dropping
  one weapon.

3. Snapshot and refresh demand

- Continue using the coherent full sample already carried through:

  `PlayerStatsClient -> FullPlayerSample -> LiveRunSnapshot -> RuntimeStateSnapshot -> InGameOverlayProjection`.

- Do not read process memory from `QTimer` callbacks, the HTML builder or the
  draggable widget.
- Extend `in_game_overlay_requires_player_stats_refresh()` in
  `src/app/refresh_tasks.py` so an enabled `weapon_tracker` with at least one
  selected metric requests the existing full player refresh.
- Extend the optional weapon-read gate in
  `src/app/player_stats_memory.py` so native Weapon Tracker alone requests
  `get_live_weapons()`. It must not depend on recording, Live Stats, OBS or
  Twitch being active.
- When the master In-Game Overlay is disabled, the widget is disabled, or
  `selected_stats` is empty, Weapon Tracker must not create weapon-read demand.
- Reuse the 10-second full-snapshot cadence and the same-pass global/weapon
  values. Do not combine faster general stats from one capture with weapons from
  a different capture.
- Reuse `LiveSnapshotStore.merge_weapons()` and its new-run reset behavior for
  the agreed last-known policy. Ensure the projected snapshot exposes the
  effective last-known tuple even when the newest physical read is unavailable.

4. Configuration and settings UI

- Add the `weapon_tracker` default entry in `src/app/config.py`.
- Extend `normalize_in_game_overlay_config()` with the metric-list and layout
  rules above while preserving an explicit empty selection.
- Register `Weapon Tracker` in `src/gui_in_game_overlay_settings.py` and reuse
  the existing enabled checkbox and scale control.
- Add a focused Weapon Tracker options dialog rather than adding its controls
  to the general player-stat picker.
- The dialog contains six independent metric checkboxes with normal Save/Cancel
  behavior consistent with the other overlay dialogs.
- Put the `Layout` choice with `Compact` and `Detailed` directly in the Weapon
  Tracker row on the In-Game Overlay tab rather than inside the dialog.
- Show a compact selected-stat summary beside it, for example `3 stats`.
- Coalesce rapid layout changes before repainting and persisting so repeatedly
  switching the inline choice cannot queue full settings refreshes.
- Metric selections and inline layout changes should repaint the widget promptly
  and persist through restart.

5. Native overlay widget and renderer

- Add `weapon_tracker` to the hard-coded widget registry in
  `src/gui_in_game_overlay_window.py`.
- Use the existing `DraggableOverlayWidget` and one Qt rich-text `QLabel`. A
  custom painted widget is not required for names and text-only stats.
- Add `build_weapon_tracker_overlay_html()` to
  `src/projections/in_game_html.py`, or keep the row projection in
  `src/projections/weapon_tracker.py` and the final Qt HTML assembly in
  `in_game_html.py`.
- Use tables and inline styles supported by Qt Rich Text; do not rely on CSS
  Grid or Flexbox.
- In `InGameOverlay._overlay_fast_tick_once()`:
  - read the latest immutable runtime projection;
  - calculate/filter rows from the snapshot and saved options;
  - select compact, detailed or one of the Edit Layout status projections;
  - update text only when it changed;
  - explicitly control widget visibility for normal and Edit Layout modes.
- Let `DraggableOverlayWidget.set_text()` perform resize and reclamp from the
  saved position when weapon count, selected metrics or layout changes.
- Do not clear the widget merely because `run_completed` is true.

6. Scope protection for later consumers

- Keep the calculation registry Qt-free so Live Stats and Twitch can reuse it
  in a later update.
- Do not add Live Stats cards, Twitch commands, OBS routes, browser-overlay
  state, recording timeline UI or VOD playback rendering now.
- Do not create configuration keys for the four excluded stats “for later”.
  Adding a future metric should require an explicit product decision and a
  registry/config migration.

Recommended implementation order:

1. Add the pure six-metric registry, formulas and unit tests.
2. Add cap fields to the weapon snapshot/read path and preserve last-known
   behavior on failed reads.
3. Add config defaults, normalization and settings-dialog tests.
4. Add compact/detailed HTML renderers and their snapshot tests.
5. Register the draggable widget and connect fast-tick visibility/state logic.
6. Add native-overlay refresh demand and prove that overlay-only usage reads
   weapons at the accepted 10-second cadence.
7. Run focused tests, then the complete Windows suite and manual in-game QA.

Automated validation plan:

- Add `src/tests/test_weapon_tracker_projection.py` covering:
  - every supported formula;
  - Aegis Damage;
  - Shotgun's underlying Projectile Count;
  - Size and Duration caps;
  - Crit Chance above 100%;
  - the default `×2` Crit Damage baseline;
  - missing/non-finite operands;
  - selected-stat and upgrade-pool intersection;
  - hidden weapons and deterministic ordering;
  - formatting and trailing-zero removal.
- Extend `src/tests/test_player_stats.py` for cap offsets, sentinel values and
  coherent failure of a partial weapon read.
- Extend `src/tests/test_vod_storage.py` only for backward-compatible optional
  cap-field round trips; do not add a recording UI feature.
- Extend `src/tests/test_config_cleanup.py` for defaults, old configs, unknown
  metric keys, duplicates, invalid layout and preservation of an explicit empty
  selection.
- Add settings-dialog coverage in
  `src/tests/test_gui_in_game_overlay_settings.py`.
- Extend `src/tests/test_in_game_overlay_render.py` for:
  - compact and detailed layouts;
  - level hidden/shown by layout;
  - HTML escaping;
  - all three Edit Layout status messages;
  - no `Weapons` heading in normal mode.
- Extend `src/tests/test_gui_in_game_overlay_window.py` for widget registration,
  drag persistence and reclamping while rows/layout change size.
- Extend `src/tests/test_player_stats_memory.py` and refresh-task coverage to
  prove:
  - Weapon Tracker alone requests weapons;
  - a disabled widget requests nothing;
  - an empty metric selection requests nothing;
  - one full refresh performs only one weapon walk;
  - temporary failure retains the last confirmed rows;
  - a new run clears them.
- Extend the existing In-Game Overlay fast-tick tests in
  `src/tests/test_gui_run_control.py` for normal-mode hiding, Edit Layout
  placeholders, option changes, death retention and focus behavior.
- After focused tests, run:
  - `python -m compileall src`;
  - `git diff --check`;
  - `cmd.exe /d /c run_tests.bat` and wait for the final `OK`.

Manual acceptance checklist:

- Enable only the master In-Game Overlay and Weapon Tracker; leave Scanner,
  Live Stats, recording, OBS and Twitch off. Weapon values still appear.
- Confirm the first update arrives within the accepted full-snapshot interval.
- Confirm the default view shows only Damage, Projectile Count and Size.
- Independently toggle Duration, Crit Chance and Crit Damage, including a saved
  state with all six toggles off.
- Verify Compact omits levels and Detailed shows `Lv.N`.
- Verify a weapon is hidden when none of its upgradeable stats are selected.
- Verify one movable block grows and shrinks without losing its saved position
  or escaping the game window.
- Verify normal mode has no `Weapons` heading and hides the empty widget.
- Verify all three approved Edit Layout messages.
- Level up a weapon and increase a general stat; verify the displayed final
  value changes on the next full snapshot.
- Verify Aegis Damage includes Thorns and Shotgun Projectiles shows the
  underlying count rather than pellet/burst values.
- Verify Duration/Size caps where applicable.
- Cause a temporary read failure and confirm the last values remain without a
  stale badge.
- Die and confirm the values remain; start a new run and confirm the old
  weapons clear before the new sample arrives.
- Restart BonkScanner and confirm enabled state, position, scale, layout and
  selected metrics persist.

Acceptance direction:

- the widget is independently usable with only native In-Game Overlay enabled;
- every displayed value follows the six confirmed formulas and upgrade-pool
  visibility rule;
- the approved defaults, layouts, formatting and empty states match this plan;
- temporary failures and death do not erase confirmed values, while a new run
  does;
- disabled or empty-configured Weapon Tracker adds no unnecessary memory work;
- no excluded metric or additional Live Stats/OBS/Twitch/recording surface is
  introduced;
- focused tests and the full Windows suite pass.

### Twitch Commands

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

### Recordings & Build Progression

#### 1. Record Active Build Progression in the Recording Timeline

Status: `[Open]`

Goal:

- Add an optional synchronization setting that records the existing active `Build Progression` together with a run recording.
- Show how the selected build was assembled over time: when each requirement was completed, when a deadline was missed, and when the full build was completed.
- Keep this as a recording/history extension of the existing `Build Progression`, not as a separate challenge assistant or recommendation system.

Planned implementation notes:

- When synchronization is enabled, save a frozen copy of the active build definition at recording start so later edits or deletion of that build cannot change historical recordings.
- Record exact Build Progression transition events with their in-game time and stage context instead of reconstructing them only from the normal recording snapshots, whose sampling interval can make completion and deadline times inaccurate.
- Reuse the current `BuildProgressionService` state and transitions; this feature should not require additional game-memory reads or a second progression evaluator.
- Add a dedicated `Build` lane to the recording timeline with:
  - a step progression such as `2/8 -> 3/8 -> 4/8`;
  - markers for completed requirements, banishes, missed deadlines, tracked caps, and full-build completion;
  - tooltips showing the requirement, in-game time, stage, and deadline timing where relevant.
- When the recording playhead moves, allow the existing Build Progression view to display the recorded state at that point in time.
- Keep a recording bound to the build captured at its start if the user changes the active build during the run; do not silently mix multiple build definitions into one timeline.
- Show the recorded build name in the recording details/library, and hide the Build lane for older recordings that do not contain Build Progression data.

Initial delivery scope:

- opt-in synchronization;
- frozen build definition in the recording;
- requirement and full-completion events;
- Build timeline lane and playhead-aware historical state;
- backward-compatible loading of existing recordings.

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
