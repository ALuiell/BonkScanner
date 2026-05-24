# BonkScanner Functional Overview

Date: 2026-05-21

This document is a product-level and implementation-level map of BonkScanner.
It is meant to help future debugging, feature planning, and review of possible
logic flaws without needing to rediscover the whole codebase from scratch.

It is not a low-level reverse engineering report. For exact memory offsets and
validation notes, use `docs/reverse/MEMORY_PATH_INDEX.md` and the reports under
`docs/reverse/reports/`.

## Mental Model

BonkScanner has three major responsibilities:

1. Reroll maps until a target map is found.
2. Inspect the current run in real time through memory reads.
3. Record and replay live run snapshots for later review.

The desktop UI now uses a split GUI layout. `gui.py` is a compatibility facade,
`gui_app.py` defines `MegabonkApp`, and focused `gui_*` modules own layout,
scanner flow, run control, dialogs, live stats, and recordings behavior.
Memory-facing readers are split mostly into `game_data.py` for map/reroll data
and `player_stats.py` for run inspection. Recordings are stored and loaded
through `vod_storage.py`.

## Main Files

- `main.py` starts the desktop app.
- `gui.py` is the compatibility facade for imports/tests; `gui_app.py`,
  `gui_layout.py`, `gui_scanner.py`, `gui_run_control.py`,
  `gui_player_stats.py`, `gui_templates.py`, `gui_dialogs.py`,
  `gui_shared.py`, and `gui_styles.py` split the PySide6 responsibilities.
- `config.py` loads and saves app settings, templates, score rules, hotkeys,
  and update preferences.
- `logic.py` evaluates map stats against templates and score tiers.
- `game_data.py` reads map readiness, interactable counters, and map generation
  state from the game process.
- `player_stats.py` reads live player stats, passive items, weapons, run timer,
  stage timer, kill count, and level.
- `vod_storage.py` writes and reads `.jsonl` recordings.
- `run_control.py` abstracts keyboard restart and native hook restart.
- `hook_loader.py` injects and drives the optional native hook.
- `updater.py` handles packaged-build update checks and update application.

## Scanner Flow

Purpose:

- Automate repeated map rerolls until the current map matches selected targets.

User-facing flow:

1. User selects `Templates` or `Scores`.
2. User presses `Start`.
3. The scan hotkey arms or pauses the scan loop.
4. The app waits for a stable map-ready state.
5. Map stats are read and evaluated.
6. If the map matches, scanning stops and logs the result.
7. If not, the app restarts the run and repeats.

Implementation shape:

- UI state is centralized in `MegabonkApp`; scanner loop control mainly lives
  in `gui_scanner.py`, with run-control helpers in `gui_run_control.py`.
- Map memory reads come from `GameDataClient` in `game_data.py`.
- Runtime map stats are normalized through `runtime_stats.py`.
- Template and score decisions come from `logic.py`.
- Restart execution goes through `run_control.py`.

Important details:

- The scanner avoids using the first unstable map-load read as final truth.
- Stable snapshot reuse is important: if a readiness wait already captured a
  valid map, the scanner should not immediately reread a transient bad state.
- `Templates` and `Scores` are two evaluation modes over the same underlying
  map stats.

Risks:

- Game updates can move memory paths or change dictionary/key layouts.
- Too-low reroll delay can make the app read partial map state.
- Native hook restart and keyboard restart have different failure modes.
- If scan loop state, hotkeys, and UI buttons get out of sync, the app can look
  idle while still armed or vice versa.

Good tests/checks:

- Matching map stops the loop.
- Non-matching map triggers exactly one restart action per cycle.
- Runtime template/filter changes do not reset session stats.
- Stable snapshot path avoids extra map reads after readiness succeeds.

## Templates And Scores

Purpose:

- Decide whether the current map is good enough to stop on.

Templates:

- Strict rule-based matching.
- Good when the user knows exact requirements.
- Configured through active templates and template manager UI.

Scores:

- Weighted score-based matching.
- Good for broader "strong map" searches.
- Supports stat weights, microwave multipliers, thresholds, and active tiers.

Implementation shape:

- Defaults and persisted values live in `config.py`.
- Evaluation lives in `logic.py`.
- UI controls live across `gui_layout.py`, `gui_templates.py`, and
  `gui_dialogs.py`; runtime refresh for this area is coordinated through
  `MegabonkApp`.

Risks:

- Removing or disabling templates must not destroy historical session stats.
- Runtime filter edits during an active session must update active filters
  without resetting unrelated counters.
- Score threshold changes should not leave stale tier state in memory.

## Session Stats

Purpose:

- Show current-session and persistent reroll progress.

Tracks:

- Total rerolls.
- Session rerolls.
- Rerolls since each target was last found.
- Average rerolls per target.

Implementation shape:

- Runtime state is mostly in `MegabonkApp`.
- Persistent total rerolls and template stats are saved through `config.py`.

Risks:

- Template deletion or deactivation can accidentally drop useful historical
  counters if cleanup is too aggressive.
- Runtime mode changes must preserve session history where possible.

## Live Stats

Purpose:

- Inspect the current run without relying on OCR or game UI scraping.

Shown data:

- Player stat cards.
- Passive items with rarity colors and total item count.
- Average chests per minute estimate.
- In-game run timer.
- Mob kill count.
- Player level.
- Stage Summary.
- Weapon cards with level and upgraded stats.

Implementation shape:

- `PlayerStatsClient` in `player_stats.py` reads memory.
- `MegabonkApp.refresh_live_player_stats_now()` coordinates reads.
- `MegabonkApp.display_player_stats()` updates the UI.
- Passive item formatting, coloring, counting, and sorting are handled in
  `gui_player_stats.py` and style constants from `gui_styles.py`.

Passive item logic:

- Primary path: `PlayerStatsNew +0xA0 -> +0x50` passive item dictionary.
- Fallback path: `PlayerStatsNew +0x28 -> PlayerInventory +0x20
  -> ItemInventory +0x10`.
- The fallback exists because modded or externally added items can appear in
  `PlayerInventory.ItemInventory` while the older passive path is empty.
- Item counts use stack values, so `Anvil x3` counts as three items.

Item display sorting:

- `Default` keeps the input order.
- `Rarity ↓` shows highest rarity first.
- `Rarity ↑` shows lowest rarity first.
- Sorting is stable inside each rarity group to preserve as much original order
  as possible.

Risks:

- Passive item memory paths can be initialized later than stats.
- Mods/cheats can populate a different inventory path than normal gameplay.
- Dictionary counts need hard caps to avoid walking garbage memory.
- Rarity lookup depends on normalized display names and aliases.

## Stage Summary

Purpose:

- Show per-stage run progress in live stats and recordings.

Displayed per stage:

- Stage number.
- Time.
- Kills.
- Items gained.

Core idea:

- Stage transitions are detected from snapshot metadata, not from the visual HUD.
- For stages 1-3, a stage pointer or seed change indicates a real stage change.
- Stage 4 may reuse stage 3 pointer/seed, so stage timer behavior is used as a
  fallback signal.

Time logic:

- Time is boundary-based using `game_time_seconds` / run timer.
- Stage 1 starts from run time `0` when run timer data is available, even if the
  first recording snapshot starts later.
- Stage 1-3 time does not depend on `stage_time_seconds`, because boss time-skip
  mechanics can make stage timer jump.
- `stage_time_seconds` is kept mostly as a transition hint for Stage 4.

Kills logic:

- Kills are calculated from cumulative mob kill deltas.
- If the first snapshot of a new stage happens within the first few seconds of
  that stage, it is also used as a boundary snapshot to close the previous
  stage. This reduces undercounting when the last pre-transition snapshot was
  too early.
- The boundary window is intentionally small to avoid stealing real kills from
  the new stage.

Items logic:

- Items are summed from per-snapshot deltas.
- If an item appears between the previous stage snapshot and the first new-stage
  snapshot, that item delta is attributed to the new stage.
- Duplicate stacks count. Example: `Wrench x1 -> Wrench x3` adds two items.

Risks:

- Long snapshot intervals reduce transition precision.
- If a player kills many mobs immediately after entering a new stage, the
  boundary rule can slightly over-assign kills to the previous stage.
- If Stage 4 detection misses both reset and timer jump signals, Stage 4 can be
  merged with Stage 3.

Good tests/checks:

- Stage 1 starts at `00:00` even if first snapshot is late.
- Boss timer skips do not inflate or shrink Stage 1-3 time.
- Early new-stage boundary snapshots close previous-stage kills/time.
- Item deltas at stage transition go to the new stage.

## Recordings

Purpose:

- Persist live run snapshots and replay them later.

Format:

- `.jsonl` files in `stats_recordings/`.
- Metadata record first.
- Snapshot records next.
- Summary record at stop.

Snapshot data can include:

- Player stats.
- Passive items.
- Weapons.
- Chests per minute.
- In-game time.
- Mob kills.
- Player level.
- Map seed.
- Current stage pointer.
- Stage timer.

Recording behavior:

- User can start/stop from UI or hotkey.
- Snapshot interval is configurable.
- Recordings can be replayed with a timeline slider.
- Renaming a recording also renames the file on disk.
- Short recordings can be cleaned up by snapshot count.

Auto-split behavior:

- The recorder should split when a genuinely new run starts.
- It should not split on normal stage transitions.
- Seed changes alone are not enough to split if stage pointer changes and run
  timer continues.
- Missing seed has a grace window before auto-stop.

Risks:

- Old recordings may lack newer fields.
- Snapshot interval affects Stage Summary precision.
- Seed or stage metadata can be unavailable during loading screens.
- Renaming must avoid filename collisions and invalid filesystem characters.

## Weapons

Purpose:

- Show current run weapons, levels, and upgraded stats.

Implementation shape:

- Read through `PlayerStatsNew -> PlayerInventory -> WeaponInventory`.
- Each weapon stores:
  - weapon id and display name
  - level
  - full weapon stat dictionary
  - upgrade stat ids
  - upgraded-only stat values

Display rule:

- UI defaults to upgraded stats, not every full effective weapon stat.
- This avoids showing unrelated inherited/global stats as if they came from
  that weapon's level-ups.

Risks:

- Old `WeaponInventory` objects can remain in memory after a run.
- Full weapon stats contain more than the upgraded stat pool.
- Some weapon upgrade pools may need special handling after more validation.

## Hotkeys And Settings

Purpose:

- Keep common actions fast without requiring constant UI focus.

Main hotkeys:

- Scan hotkey.
- Reset hotkey.
- Record hotkey.
- Toggle chest skip.
- Toggle auto level-up.
- Toggle particles opacity.

Implementation shape:

- Settings are stored in `config.json`.
- Game config edits use the game's config file where possible.
- Native hook settings use `hook_loader.py` and the BonkHook DLL.

Risks:

- Global hotkeys may need elevated privileges.
- Game config layout can change.
- Native hook mode can fail if injection, process bitness, or permissions are
  wrong.

## Native Hook Restart

Purpose:

- Provide an alternative restart path that can work better while alt-tabbed or
  when keyboard input is unreliable.

Implementation shape:

- NativeAOT DLL lives under `native/BonkHook`.
- `hook_loader.py` injects and calls exported hook actions.
- Build uses project-local toolchain scripts under `tools/`.

Risks:

- Native injection is more fragile than keyboard input.
- Antivirus or OS policy can interfere.
- Game updates can break hook-ready paths.

## Update System

Purpose:

- Allow packaged builds to check for newer releases.

Implementation shape:

- `updater.py` handles version checks and update application.
- Source runs should not auto-update themselves.
- Skipped versions are remembered in `config.json`.

Risks:

- Update behavior differs between source and packaged builds.
- Failed updates must not leave the app half-replaced.

## Cross-Cutting Design Rules

- Prefer rooted memory paths over broad heap scans.
- Keep memory read failures local when possible. A passive item failure should
  not blank working player stats.
- Preserve backward compatibility with older recording files.
- Keep UI defaults conservative. New display modes should usually default to the
  old behavior.
- Add tests around boundary cases, not just happy paths.
- When a feature depends on live memory behavior, document the verified path and
  the observed failure mode.

## Common Debugging Questions

If map rerolling behaves wrong:

- Is the map-ready state stable before evaluation?
- Are map counters non-zero and plausible?
- Did active templates or score tiers update at runtime?
- Is the reset provider keyboard or native hook?

If live stats are blank:

- Does `PlayerStatsNew` resolve?
- Do core stats read while items fail, or does everything fail?
- Is the game in a loading/menu state?

If items are missing:

- Does the old passive path resolve?
- Does the `PlayerInventory.ItemInventory` fallback resolve?
- Is the dictionary count plausible?
- Are entries broken, or are names failing normalization?

If recordings split incorrectly:

- Did seed change because of a new run or a stage transition?
- Did run timer continue or reset?
- Did current stage pointer change?
- Was seed missing long enough to hit the grace window?

If Stage Summary looks wrong:

- What is the snapshot interval?
- Are `game_time_seconds`, `stage_ptr`, `map_seed`, and `stage_time_seconds`
  present in the recording?
- Did the transition happen between two distant snapshots?
- Did Stage 4 reuse the same stage pointer/seed as Stage 3?

## Suggested Future Improvements

- Persist item sort mode in `config.json` if users expect it to survive restarts.
- Add an optional debug view for snapshot stage metadata.
- Add a recording analyzer command/tool that prints Stage Summary, item deltas,
  and transition boundaries for a selected `.jsonl`.
- Add UI hints when item reads are using the fallback inventory path.
- Consider displaying both total item count and unique item count if users ask
  for build-density analysis.
