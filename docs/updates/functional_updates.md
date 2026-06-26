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

- `!cap`
  - Track when the current run reaches important stat caps.
  - Difficulty cap should be user-configurable, for example `500%`.
  - The app should poll the normal live player stats and record the first run time when the configured difficulty value is reached.
  - XP gain cap should use a fixed target of `10x`.
  - The command should show whether each cap has been reached and, if so, at what run time.
  - Example output idea: `Difficulty cap 500% reached at 10:00; XP gain 10x not reached yet.`
  - Store the first reached timestamp only; do not keep updating it after the cap has already been recorded.

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

#### 3. `!powerups` Total Pickups Counter

Status: `[Open]`

Goal:

- Extend `!powerups` so it can also report end-of-run totals such as
  `Clock: 10, Shield: 8, Rage: 5, Stonks: 15`.

Why this needs special handling:

- Active status effects are not a reliable historical pickup log.
- For `Rage`, `Shield`, and likely `Stonks`, repeated pickups do not create a
  fresh status-effect instance:
  - `added_time` stays at the original value.
  - `expiration_time` is refreshed forward from "now".
- This means `added_time` is not a safe "last pickup time" signal.
- `Clock` is more complicated because the `Zawarudo` item uses the same
  `TimeFreeze` / `Clock` status effect as the normal Clock powerup.

Confirmed behavior from live validation:

- Re-taking `Rage` or `Shield` keeps the old `added_time`.
- Re-taking `Rage` or `Shield` moves `expiration_time` to a new later value.
- `Zawarudo` produces a `TimeFreeze` effect with a strict `15.0s` duration.
- A normal Clock powerup scales with `Powerup Multiplier`.
- Because `Zawarudo` and Clock share the same status effect, a pure
  `StatusEffect` read cannot always tell which source caused the effect.

Recommended counting model:

- Count pickups from transitions between snapshots, not from `added_time`.
- Maintain per-effect tracker state:
  - last seen `expiration_time`
  - last seen `remaining`
  - total pickup count per effect
- When `expiration_time` jumps upward more than normal time decay would allow,
  treat that as a new pickup / refresh event.
- This should work well for `Rage`, `Shield`, and `Stonks`.

Recommended special handling for `Clock`:

- If a new `TimeFreeze` event clearly adds more than `15s`, classify it as a
  normal Clock pickup.
- If a new `TimeFreeze` event is close to `15s`, treat it as ambiguous.
- Do not add a high-frequency inventory poll just for this edge case.
- Instead, use the existing slow live-stats item refresh as confirmation:
  - when an ambiguous `Clock` event appears, mark it as pending
  - on the next normal item snapshot, compare `Zawarudo` stack count
  - if the stack dropped, classify the event as `Zawarudo`, not Clock
  - if the stack did not drop, classify it as a real Clock pickup

Why the delayed-confirmation approach is acceptable:

- The ambiguous case mainly matters around `PM = 1x`, where Clock duration can
  look similar to a `Zawarudo` proc.
- `Zawarudo` proc duration is short (`15s`), and repeated procs inside one
  live-stats refresh window are unlikely enough to tolerate delayed
  confirmation.
- This avoids adding a dedicated fast item-inventory scan to the hot path.

Suggested implementation notes:

- Keep the current live `!powerups` output logic unchanged for active timers.
- Add a separate pickup-counter state machine to `LiveRunTracker`.
- Feed it from:
  - powerup tracking snapshots on the fast path
  - normal live item snapshots on the slow path
- Consider exposing the final totals only in chat output or end-of-run summary
  first, before adding more UI surface area.

Open product decision:

- It may be reasonable to ship counts for `Rage`, `Shield`, and `Stonks`
  first, while leaving `Clock` disabled or marked approximate until the
  delayed-confirmation path is implemented.

#### 4. `!dice` Dicehead Passive Tracker

Status: `[Open]`

Goal:

- Expand Twitch commands with `!dice` to output the accumulated stat bonuses gained from the "Dicehead" character's passive ability.
- The Dicehead passive mechanism upgrades a random stat at every level up. The command should compute and display the total stats gained this way over the current run.

Required reverse-engineering work:

- Investigate `GameAssembly.dll` to find the exact mechanism (fingerprints and formula) for how the Dicehead passive calculates and applies stat upgrades per level.
- Confirm whether these stats are stored separately or just baked into the player's stat inventory alongside other permanent changes.
- Prepare a documentation report detailing the findings, the formula, and memory paths needed to accurately track these specific level-up bonuses.
- Do not implement the tracking logic until the reverse-engineering documentation is complete and the stat fingerprints are confirmed.

#### 5. The One Ring Announcer

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

#### 6. `!kps` (Kills Per Second) Tracker

Status: `[Open]`

Goal:

- Implement real-time Kills Per Second (KPS) tracking to be displayed in the Live Stats panel and via a new Twitch bot command (`!kps`).
- Ensure the tracker updates rapidly (every 500ms) without causing memory reading lag or UI stuttering.
- Use the in-game run timer as the authoritative time base for KPS calculations so pauses and timer freezes do not distort the metric.

Implementation details:

- **Pointer Caching (`player_stats.py`)**:
  - To poll the kill count rapidly without CPU overhead, the pointer to the `"kills"` value inside the `RunStats.stats` dictionary will be cached.
  - Will introduce `_cached_kills_dict`, `_cached_kills_entries`, `_cached_kills_version`, and `_cached_kills_address` instance variables in `PlayerStatsClient`.
  - A new method `_get_cached_killed_mobs()` will verify the cache validity (by comparing the dictionary address, the entries array pointer, and the version integer). If valid, it reads the float value directly from `_cached_kills_address` and casts it to an integer. If invalid, it falls back to `_find_run_stat_value_address` to re-resolve the offset.
  - The existing `get_killed_mobs()` method will be updated to route through `_get_cached_killed_mobs()`.

- **Moving Window Calculation (`live_run_tracker.py`)**:
  - The `LiveRunTracker` will house a short ~3-second moving window `_recent_kills_history` that stores `(game_time_seconds, current_kills)` pairs gathered from the existing 500ms live polling path.
  - A new `track_kills(self, game_time_seconds: float | None, current_kills: int | None)` method will append only valid readings and trim stale samples so the tracker always reflects the most recent ~3 seconds of in-game time.
  - The primary displayed metric will be a smoothed current KPS, computed from the kill delta across the oldest and newest valid samples in that ~3-second window rather than from a single 1-second bucket. This avoids noisy spikes while still reflecting the current live pace much better than a full-run average.
  - **Resets & Pauses Handling**: If `current_kills` drops below the previously recorded value, or if `game_time_seconds` moves backward, the history is instantly cleared as a new run/reset signal. If the game is paused and the in-game timer stops advancing, the tracker must not invent time progress from wall-clock time; KPS should remain based on valid in-game-time deltas only.
  - A new `current_kps(self) -> int | None` method will return the rounded smoothed KPS value when at least two valid samples exist; otherwise it returns `None`.
  - A secondary internal helper or bucketed history may be kept later if needed for debugging or future analytics, but the shipped product metric should remain the smoothed ~3-second KPS.

- **Fast UI Updates (`gui_player_stats.py`)**:
  - The kills read operation and UI label update will be injected directly into the `refresh_chaos_tome_tracker_now` loop, which fires every 500ms.
  - Inside the loop, it will read both `game_time_seconds` and `client.get_killed_mobs()`, update the tracker, and format the string as `Mob Kills: 12,345 (150/s)` once KPS becomes available.
  - Before the tracker has enough history to compute KPS, the label should remain in its plain form (`Mob Kills: 12,345`) rather than showing a fake `0/s` or placeholder suffix.
  - To prevent "blinking" caused by the slower live stats refresh path blindly overwriting the label, the shared mob-kills formatter must be updated so every writer uses the same KPS-aware output.
  - The KPS display is intended for live stats only; it should not be injected into the stage summary rows, which represent aggregate stage totals rather than short-window live pace.

- **VOD Snapshot Capture (`vod_storage.py` / `gui_player_stats.py`)**:
  - Recorded VOD snapshots are too sparse to reconstruct a trustworthy live KPS curve after the fact because the recorder captures on a much slower interval than the 500ms live polling path.
  - Instead of recomputing KPS from VOD snapshots later, the recorder should persist the current live-tracker value at capture time as a dedicated field such as `kps_at_capture`.
  - Snapshot playback can then display the stored KPS value for that capture if desired, without pretending it was derived from the sparse VOD timeline itself.

- **Twitch Bot Command (`twitch_bot.py`)**:
  - The command `!kps` will be registered in `_handle_line` and tied to a configuration check `commands_cfg.get("kps", True)`.
  - The `_handle_kps(self, channel: str)` callback will invoke `self.run_tracker.current_kps()` and output exclusively the KPS metric (e.g., `@User, 150 kills/sec.`) to keep chat noise minimal.
  - If KPS is not available yet because the run has just started or live reads are not ready, the command should return a short unavailable/warming-up response rather than a misleading `0 kills/sec`.
  - The command will be automatically appended to the output of the `!bonkhelp` message.
