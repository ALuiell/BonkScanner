# Functional Updates

Date: 2026-06-04

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

#### 3. Active Powerup Tracking For `!powerups` And Live Stats

Status: `[Implemented]`

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

- Powerup tracking runs in the existing fast tracker timer (`CHAOS_TOME_TRACKER_INTERVAL_MS`, currently `250 ms`).
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

