# Functional Updates Archive

This file archives completed, shelved, or old functional updates, helping keep `functional_updates.md` focused on active tasks.

---

## Recently Handled Items (Archived 2026-07-15)

### Recordings

#### 7. Fix Clean Short Active Run Edge Case

Status: `[Implemented]`

Implemented scope:

- `Clean Short` explicitly excludes the currently active recorder file.
- `PermissionError` and other `OSError` failures on individual files are skipped so the remaining short recordings are still processed.
- The UI reports the number of removed and skipped active/locked recordings.
- Regression coverage verifies that an active file and a locked file remain while other short files are deleted.

Code anchors:

- `src/vod_storage.py`
- `src/gui_player_stats.py`
- `src/tests/test_vod_storage.py`

### Live Runtime

#### 8. Harden The Live Powerup Read Pipeline

Status: `[Partial / Archived]`

Implemented scope:

- Added structured read health for timing, status effects, and `Powerup Multiplier`.
- Incomplete or unavailable powerup reads are rejected before replacing the shared tracker snapshot.
- The existing last-known-good TTL fallback remains active for transient failures.
- Added coverage for hard failures, partial effect lists, empty reads, multiplier failures, recovery, and shared consumer state.

Remaining caveat:

- The snapshot still expires after the compatibility TTL instead of being retained indefinitely until a valid replacement or explicit run reset.
- Runtime diagnostics and full run-reset semantics remain follow-up work.

Key commits:

- `f8b2fcb` — preserve powerup snapshots through transient read errors.
- `db2132d` — harden powerup memory reads and add health validation.
- `5da3844` — prevent auxiliary reads from hiding powerups.

### Recovery Tooling

#### 9. Automated IL2CPP Offset Validator and Handoff Reporter

Status: `[Implemented locally / Pending commit]`

Implemented scope:

- Added local `tools/offset_finder.py` utility.
- Parses IL2CPP `dump.cs` metadata and optional `il2cpp.h` / `script.json` TypeInfo sources.
- Compares configured expectations and reports `matched`, `shifted`, `missing`, `ambiguous`, and `unverified` entries.
- Generates a Markdown validation and handoff draft with manual follow-up sections.
- Remains diagnostic-only and does not patch production source files.

Archive note:

- The `tools/` directory is currently ignored by Git, so this utility is present in the workspace but is not yet included in a commit.

---

## Completed / Done Items (Archived 2026-07-12)

### Twitch Commands

#### 6. `!kps` (Kills Per Second) Tracker

Status: `[Implemented]`

Implemented scope:

- `PlayerStatsClient` caches and validates the `RunStats.stats["kills"]` dictionary entry for lightweight reads.
- `LiveRunTracker` calculates current KPS from a smoothed ~3-second window based on the in-game timer; resets, backwards time, and paused time do not create false progress.
- The Live Stats kills label, VOD snapshots, OBS state, and the configurable `!kps` command consume the shared tracker state.
- `!kps` reports a warming-up/unavailable response instead of a misleading zero before valid samples exist, and is included in `!bonkhelp`.

Archive note:

- Removed from the active list after implementation and automated coverage were completed.

### Runtime Refresh Architecture

#### 8. Split Live Refresh Into Slow And Fast Tracker Lanes

Status: `[Implemented]`

Implemented scope:

- The expensive `full_player_snapshot` runs on the slow player-stats cadence.
- Independent 500ms fast tasks now handle combat metrics/KPS, powerups, expected chest inputs, event timer state, and Chaos Tome tracking.
- Shared `RefreshTickContext` values avoid duplicate client and owner-stat resolution within a scheduler tick.
- `LiveRunTracker` remains the shared fast runtime state consumed by UI, overlays, Twitch, and VOD capture.

Archive note:

- The concrete lane design replaced the original planning/prototype entry.

### In-Game Overlay

#### 1. In-Game Stats Widget

Status: `[Implemented]`

Implemented scope:

- Configurable in-game `stats` widget with cap-aware formatting and colors.
- Forest/Desert use dynamic Difficulty caps by stage and elapsed time plus the fixed `XP Gain` 10x cap; capped values are red and uncapped values cyan.
- Graveyard uses the standard uncapped stat presentation.

#### 2. In-Game Event Timer Widget

Status: `[Implemented]`

Implemented scope:

- Configurable single-line warning and active-wave timer driven by the fast stage-timer lane.
- Covers Forest/Desert boss and wave timings with orange advance warnings and red active-wave state.
- Includes the later Graveyard event-timing extension, while retaining empty output when no relevant event is imminent.

Archive note:

- Both overlay widgets reuse the existing resolved map-family and runtime stage-time paths.

---

## Completed / Done Items (Archived 2026-07-03)

### In-Game Overlay

#### 1. Split `src/gui_in_game_overlay.py` Into Focused Modules

Status: `[Done]`

Goal:

- Reduce the maintenance cost of the in-game overlay code by separating UI window logic, settings UI, and HTML/render helpers into smaller focused modules.
- Keep the shipped overlay behavior unchanged while making future fixes and feature work less risky.

Implemented scope:

- `src/gui_in_game_overlay.py` now acts as the thin coordinator/mixin entry point.
- Overlay widgets were moved into `src/gui_in_game_overlay_window.py`:
  - `InGameOverlayWindow`
  - `DraggableOverlayWidget`
- The settings dialog was moved into `src/gui_in_game_overlay_settings.py`:
  - `InGameWidgetSettingsDialog`
- HTML/string formatting helpers were moved into `src/gui_in_game_overlay_render.py`.
- Existing config keys, signal wiring, and overlay refresh cadence were preserved.

Archive note:

- Removed from the active `functional_updates.md` list after the split was completed.

---

## Archived & Shelved Items (Archived 2026-06-23)

### Stage Summary Must Anchor To Raw Stage Index And Treat Boss As Virtual Stage

Status: `[Archived]`

Goal:

- Make `Stage Summary` deterministic when the app opens in the middle of a run.
- Use the raw memory `stage_index` as the only source of truth for normal map rows.
- Treat boss stage as a separate virtual `Stage 4`, not as a normal raw `stage_index` value.
- Stop `Stage Summary` from starting at row 1 just because the tracker attached late.

Required baseline mapping:

- Raw memory `stage_index` values must map directly to summary rows:
  - `0 -> Stage 1`
  - `1 -> Stage 2`
  - `2 -> Stage 3`
- This mapping is a hard rule, not an inference layer.
- Do not pre-convert the raw value into a human stage number before it reaches live snapshots or summary logic.

Required attach behavior:

- If the app opens during Stage 1, `Stage Summary` starts filling row 1.
- If the app opens during Stage 2, `Stage Summary` starts filling row 2 and leaves Stage 1 empty.
- If the app opens during Stage 3, `Stage Summary` starts filling row 3 and leaves Stages 1-2 empty.
- Late attach must not restart the table from Stage 1.

Boss-stage rules:

- `Stage 4` is not represented by a normal raw `stage_index`.
- Raw `stage_index=2` still means `Stage 3` by default.
- Boss stage must be promoted to virtual `Stage 4` only after an observed transition marker, not from the base raw index alone.
- Do not let a single isolated first snapshot in ghost phase automatically start the table on `Stage 4`.

Allowed boss transition markers:

- Existing timer-based transition markers may still be used.
- Add a dedicated collapse marker based only on raw map activities for:
  - `chests`
  - `pots`
- Valid collapse examples:
  - `chests: 22/46 -> 23/23`
  - `pots: 5/55 -> 5/5`
- These are good boss markers because the reported max collapses downward to the current observed value.

What must not count as boss detection:

- Honest full-clear values on the normal map must not trigger `Stage 4`, for example:
  - `chests: 46/46`
  - `pots: 55/55`
- The critical signal is not `current == max` by itself.
- The critical signal is that `max` shrank relative to the previously observed normal-map baseline.

Implementation constraints:

- Keep the logic split into two layers:
  - normal stage row selection from raw `stage_index`
  - virtual `Stage 4` promotion from explicit boss markers
- Do not merge these into one heuristic that can reinterpret raw `stage_index` based on ghost phase alone.
- Preserve raw `stage_index` all the way through:
  - memory read
  - live snapshot payload
  - live tracker state
  - stage summary builder
- Any human-readable stage number should be derived only at the final mapping point.

Regression coverage required:

- Opening the app on raw `stage_index=1` must fill Stage 2 and leave Stage 3 empty.
- Opening the app on raw `stage_index=2` must fill Stage 3 and leave Stage 4 empty unless a boss marker is observed later.
- Opening the app directly in ghost phase on a normal Stage 2 or Stage 3 map must not automatically start on `Stage 4`.
- A later observed collapse in `chests` or `pots` may promote the run from Stage 3 to Stage 4.
- Persist the “minimum total” marker into recorded/VOD snapshots if recorded summaries must match live summaries.

Archive note:

- Shelved out of the active `functional_updates.md` list.

---

## Completed / Done Items (Archived 2026-06-21)

### Mid-Run `!chests` Recovery And Honest Totals

Status: `[Done]`

Goal:

- Keep `!chests` and the live Chests card useful when the app starts in the middle of a run.
- Avoid inventing exact per-map chest counts for stages that were never observed by the tracker.
- Recover `Paid` and `Key Procs` whenever the cumulative run counters are still mathematically usable.
- Distinguish exact totals from lower-bound totals in the Twitch/GUI output.

Target behavior:

- If the tracker observed the run from the first map:
  - Keep the existing exact behavior.
  - Show exact per-map counts such as `T1:45/46 T2:46/46`.
  - Show exact overall totals such as `Total: 91/92`.
- If the tracker starts mid-run:
  - Show previously missed maps as unknown, for example `T1:--/46 T2:--/46 T3:20/46`.
  - Show the current observed map count exactly.
  - Show overall opened chests as a minimum using a `+` suffix, for example `Total: 51+/138`.
  - Continue showing `Paid` and `Key Procs` if `chestsPurchased` and `chestsBought` are internally consistent with the minimum possible total.
  - Show `Free Chests: --` because inherently free openings from missed maps cannot be reconstructed honestly.
  - Keep `Expected: --` if fast expected-proc tracking did not start from `chestsBought == 0`.

Memory inputs and scope rules:

- Current-map chest progress comes from `MapStat.CHESTS.current/max`.
- Cumulative run counters come from:
  - `RunStats.stats["chestsBought"]`
  - `MoneyUtility.chestsPurchased`
- The game does not expose a reliable always-present cumulative `chestsOpened` run stat in the tested build.
- Because of that, the tracker must treat exact prior-map openings as unknown when the app attaches mid-run.

Implementation rules:

- Detect a mid-run chest attach when the first observed playable snapshot lands on a later map/stage instead of the first playable map.
- Preserve `--` for any map that was not directly observed by the tracker.
- Compute `Total+` as the minimum total consistent with:
  - directly observed current-map openings, and
  - the invariant `chestsPurchased <= chestsBought <= totalOpened`.
- Do not backfill synthetic exact openings into `T1`, `T2`, or other missed maps just to make the invariant pass.

Baseline rules for unknown map totals:

- Use `46` as the default baseline for normal map families.
- If the currently observed map reports `chests_total >= 69`, treat the active map family as the high-total case and use `69` as the unknown-map baseline instead of `46`.
- If the currently observed map reports `chests_total < 46`, clamp unknown-map baseline totals back to `46` instead of propagating boss-room or collapsed values such as `15`.
- This rule exists because normal map families can temporarily report a collapsed chest max in boss-room-like states, while the tested high-total map family keeps reporting `69`.

Current gaps to finish (completed):

- Reconciled raw memory `stage_index` values.
- Re-applied the `Total+` path.
- Restored tests.

---

### Active Powerup Tracking For `!powerups` And Live Stats

Status: `[Done]`

Goal:

- Replace the old duration-only `!powerups` behavior with live active powerup tracking.
- Show active Rage, Shield, Stonks, and Clock/TimeFreeze effects with UI-stage pickup and expiration timestamps.
- Keep the old duration summary as the fallback when no supported powerup is active.
- Reuse the existing fast live tracker loop instead of adding a standalone polling subsystem.

Implemented behavior:

- `PlayerStatsClient` reads the supported effects from `PlayerStatusEffects.statusEffects`.
- `LiveRunTracker` stores a normalized active powerup snapshot and formats both Twitch and Live Stats summaries.
- `!powerups` output when active effects exist:
  - `Powerups: Rage 01:33 -> 00:11 (80s left) | Stonks 01:32 -> 00:10 (81s left) | Clock 01:32 -> 00:27 (64s left) (PM 5.43x)`
- `!powerups` output when no supported effect is active:
  - `Powerups: none active | Durations: standard 81.43s, clock 65.15s (PM 5.43x)`
- Live Stats uses the same tracker state in the existing `Powerups:` row, without adding a separate tab.

Polling and activation rules:

- Powerup tracking runs in the existing fast tracker timer (`FAST_TRACKER_INTERVAL_MS`, currently `500 ms`).
- `Powerup Multiplier` uses a short cached value with forced refresh when the
  active powerup set changes, instead of re-reading the full player stats block
  every fast tick.
- Powerup memory reads are only attempted when a consumer exists:
  - Live Stats tab is active, or
  - Twitch bot is active and the `powerups` command is enabled.
- The Twitch command does not read memory directly; it reads the latest `LiveRunTracker` powerup snapshot.

Confirmed memory and formula details:

- Supported status effect IDs:
  - `1` Rage
  - `2` Shield
  - `3` Stonks
  - `4` TimeFreeze / Clock
- Effect activity is based on `StatusEffect.expirationTime - MyTime.time > 0`.
- Current pickup time is reconstructed as `expirationTime - expectedDuration`, because refreshed effects may keep an old `addedTime`.
- Expected durations:
  - Rage, Shield, and Stonks: `15 * Powerup Multiplier`
  - Clock/TimeFreeze: `12 * Powerup Multiplier`
- UI stage timestamps use `MyTime.stageTimer` and `StageTimeline.stageTime`:
  - countdown: `stageTime - stageTimer`
  - overtime: `+(stageTimer - stageTime)`

Validation:

- Live memory validation confirmed Stage 1, Stage 2, Stage 3, countdown, and overtime formatting.
- Unit coverage was added for:
  - status effect dictionary reads,
  - active/fallback powerup summary formatting,
  - overtime formatting,
  - Twitch command routing through the tracker snapshot.

Known caveat:

- If stage time is manually changed through external cheats, the game UI can temporarily diverge from the normal `MyTime.stageTimer` formula. Normal gameplay matched the documented formula during live validation.

Documentation anchors:

- `docs/recovery/reports/2026-06-20-player-status-effects-and-buffs.md`
- `docs/recovery/reports/2026-06-20-ui-stage-timer-calculation.md`

---

## Part 0: Completed / Done Items (Archived 2026-06-12)

### 0. Twitch Commons Follow-Up Commands

Status: `[Done]`

- The built-in Twitch bot now includes the originally planned follow-up utility commands for chests, disabled items, reroller presets, and command discovery.
- The active `functional_updates.md` file now keeps only the still-open Twitch bot work.

Goal:

- Expand the built-in Twitch bot with common stream commands and chat-facing helpers powered by `LiveRunTracker`, while keeping responses compact and configurable.

Implemented scope:

- `!chests` / `!chest`
  - `LiveRunTracker` stores chest progress by stage plus run totals.
  - The Twitch command returns compact per-stage output and overall totals.
  - Free chest openings are included in the chat response.

- `!disabled`
  - The app reads real disabled-item state from memory once a run exposes the data.
  - Streamers can configure a highlighted subset of important disabled items.
  - The Twitch response stays compact by showing only the highlighted items that are currently disabled.

- Manual commands list command
  - Implemented as `!bonkhelp` with aliases `!bonkcmds`, `!bonkcommands`, and `!bhelp`.
  - The response lists only currently enabled commands.

- `!items` / `!tracked` total count update
  - `Items ({count})` now counts duplicate stacks instead of only distinct item names.
  - Example: `Anvil x2` plus `Soul Harvester x2` contributes `4` to the total count.

- `!presets` / `!preset`
  - The command reports active reroller presets in both `templates` mode and `scores` mode.
  - Templates mode shows the active template names and condensed conditions.
  - Scores mode shows active tiers and score weights.

Code anchors:

- `src/twitch_bot.py`
- `src/live_run_tracker.py`
- `src/player_stats.py`
- `src/gui_dialogs.py`
- `src/gui_twitch.py`
- `src/tests/test_twitch_bot.py`
- `src/tests/test_live_run_tracker.py`
- `src/tests/test_player_stats.py`

---

### 1. Hotkey Improvement - Modifier-Aware Triggering

Status: `[Done]`

- Hotkeys now tolerate configured held gameplay keys such as `W` or `Left Shift` while still rejecting unrelated modifiers for plain hotkeys.
- The active `functional_updates.md` file no longer needs to keep this completed implementation note.

Goal:

- Fix hotkeys that stopped firing when the user held a gameplay key at the same time as the hotkey trigger.

Implemented scope:

- Raw keyboard hook with pressed scan-code tracking.
- One-trigger-per-physical-press behavior for the hotkey trigger key.
- Configurable `GAME_KEYS` whitelist exposed in Settings as `Allowed Held Game Keys`.
- Extra whitelisted keys are accepted only while the game window is active.
- Exact configured hotkeys continue to work globally.
- Left and right modifiers are distinguished through scan codes.
- Only BonkScanner's own hook is removed during reconfiguration or shutdown.

Code anchors:

- `src/hotkey_manager.py`
- `src/gui_run_control.py`
- `src/gui_dialogs.py`
- `src/config.py`
- `src/tests/test_hotkey_manager.py`
- `src/tests/test_gui_run_control.py`

---

## Part 0A: Archived & Shelved Planning Items (Archived 2026-06-12)

### 0. Twitch Commons End-Of-Run Auto Announcer

Status: `[Archived]`

Goal:

- When the player finishes a run or dies, automatically post a full-run summary to Twitch chat.
- Reuse the same run summary data used by existing run tracking and overlay systems where possible.
- Include high-signal totals such as final time, map or stage progress, kills, score or damage-related stats, items, weapons, tomes, and future chest or cap information once implemented.
- Keep the feature optional in Twitch bot settings, because some streamers may prefer manual summaries only.

Archive note:

- Moved out of the active `functional_updates.md` list to keep current Twitch bot work focused on still-open command tasks.

---

## Part 1: Completed / Done Items (Archived 2026-06-02)

### 0. Find A Reliable Runtime Signal For True Menu / Non-Gameplay State

Status: `[Done]`

- Implemented in `src/game_data.py` and `src/gui_player_stats.py`.
- Resolves the issue where stats recording auto-stop could silently fail and keep recording stale snapshots from a dead run context.

Goal:

- Find a stable memory or runtime-logic signal that reliably indicates whether the player is currently in main menu / non-gameplay state, and use it to safely control the recording lifecycle.

Implemented scope:

- Reading `RuntimeGameMode` state directly from game memory (`GameManager`, `MyTime`, `LoadingScreen`, `PlayerMovement`, `MusicController`).
- Auto-stop recording on game over / main menu return, while keeping the recording armed to auto-start the next run.
- Prevent snapshot capturing while paused in game, while keeping the recording file open.

---

## Part 2: Completed / Done Items (Archived 2026-05-23)

### 0. Twitch IRC Chat Bot Integration

Status: `[Done]`

- The integrated Twitch Chat Bot is implemented in BonkScanner UI.
- Twitch account connection, IRC join flow, and chat command handling are already in place.

Goal:

- Let the streamer authenticate with their own Twitch account and run a local embedded chat bot that responds with live BonkScanner gameplay data in channel chat.

Implemented scope:

- UI support for enabling and configuring the Twitch bot
- Twitch auth/connect flow for the streamer's account
- IRC connection and channel join
- Chat commands such as `!stats`, `!banishes`, `!items`, and `!scanner`
- Basic cooldown/moderation-oriented behavior for chat command usage

Why this helps:

- Stream chat can query live run state directly from the local scanner.
- The feature works without any central shared bot service.

---

### 1. Hotkey for Particles Opacity

Status: `[Done]`

- Native hook export and loader support for `ToggleParticlesOpacity` are implemented.
- The optional config knobs for custom `ON/OFF` target values are still not added.

Goal:

- Add a hotkey for `Settings -> Effects -> Particles Opacity`.
- Intended behavior:
  - `OFF` -> set value to `0` if the game safely supports it
  - `ON` -> set value to `0.5` / `50%`
