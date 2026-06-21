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




#### 5. Stage Summary Must Anchor To Raw Stage Index And Treat Boss As Virtual Stage

Status: `[Open]`

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

