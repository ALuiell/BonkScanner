# Completed Updates Archive

Date: 2026-05-23

This file archives completed items from the old future-updates notes, which are
now split across the files in `F:\Python\MegabonkReroll\docs\updates\`.

Status legend:

- `[Done]` implemented in the current branch at the time of archive

## 1. Hotkey for Particles Opacity

Status: `[Done]`

Current branch notes:

- Native hook export and loader support for `ToggleParticlesOpacity` are implemented.
- The optional config knobs for custom `ON/OFF` target values are still not added.

Goal:

- Add a hotkey for `Settings -> Effects -> Particles Opacity`.
- Intended behavior:
  - `OFF` -> set value to `0` if the game safely supports it
  - `ON` -> set value to `0.5` / `50%`

Notes:

- Before implementation, confirm the exact internal setting name, target config
  object, field offset, and value type.
- This may be an `int 0..100`, `int 1..100`, or `float 0.0..1.0`.
- If the game slider is truly clamped to `1..100`, `OFF = 1` may be safer than
  `OFF = 0`.
- Preferred path should match the current safe settings flow:
  `CurrentSettings.BetterUpdateCfSettings(...)` on the main thread.
- Fallback should remain a raw write + `SaveConfig` only if the field path and
  type are confirmed.
- Reverse doc F:\Python\MegabonkReroll\docs\reverse\reports\2026-05-13-particles-opacity-settings.md

Possible improvement:

- Add config values for the two hotkey targets instead of hardcoding them.
- Example:
  - `PARTICLES_OPACITY_HOTKEY_ON = 50`
  - `PARTICLES_OPACITY_HOTKEY_OFF = 0`
- That gives flexibility if `0` turns out unsafe and we need to switch to `1`
  without touching code again.

## 2. Auto-Split Player Stats Recording By Run

Status: `[Done]`

Current branch notes:

- Recording now tracks run seed changes and auto-splits into a new file when the seed changes.
- Missing seed is handled with a grace window and auto-stop after the run ends.
- The suggested config knobs are still not exposed as user-facing settings.

Goal:

- If the user starts player stats recording and forgets to stop it, the program
  should automatically split recordings across separate runs.

Proposed behavior:

- While recording is active, monitor the current run seed.
- If the seed changes:
  - finish the current recording
  - immediately start a new recording
- If the seed becomes unavailable / absent:
  - treat that as run end, exit to menu, or invalid state
  - stop the current recording cleanly

Why this helps:

- Prevents one very long recording file from containing multiple unrelated
  runs.
- Makes recorded stat timelines line up with actual runs even when the user
  forgets to toggle recording off manually.

Possible improvement:

- Add a short grace window before splitting or stopping.
- Example:
  - if seed is missing for less than `N` seconds, keep current recording alive
  - if still missing after `N` seconds, stop it
- This avoids accidental splits during short transition moments.

Suggested config knobs:

- `PLAYER_STATS_AUTO_SPLIT_BY_SEED = true/false`
- `PLAYER_STATS_MISSING_SEED_GRACE_SECONDS = 3`

## 3. Built-In Help / Guide Dialog

Status: `[Done]`

Current branch notes:

- Main UI now includes a compact `?` help button next to the settings button.
- Help opens as an in-app dialog instead of relying only on external docs.
- The dialog currently exposes language tabs for `ENG`, `UA`, and `RU`.
- Help content is stored in `docs/help/` as separate text files instead of being hardcoded in `gui.py`.
- Packaged builds include those help files through the current PyInstaller paths.

Goal:

- Add an in-app help / guide button so common workflow notes and edge cases are
  explained directly inside BonkScanner.

Why this helps:

- Reduces repeated user questions.
- Makes the app feel more self-explanatory.
- Avoids relying only on external README/manual files for operational details.

Recommended format:

- Add a `Help` or `Guide` button in the main UI.
- Open a compact dialog with short practical sections instead of one long wall
  of text.

Suggested sections:

- `Reroll`
- `Templates`
- `Hotkeys`
- `Recording`
- `Native Hook`
- `Known Notes`

Examples of notes to include:

- If templates are changed during an active reroll cycle, press `Stop` and then
  `Start` again so the new templates are applied cleanly.
- Some hotkey setting changes apply to gameplay immediately, but the in-game
  settings UI may only visually refresh after reopening that menu.
- Native hook restart can only attach after the game reaches a safe initialized
  runtime state.
- Player stats recording continues until it is stopped manually, unless future
  auto-split logic is added.

Possible improvement:

- Add a small `Common Questions` or `Important Notes` section for the most
  frequent confusion points.
- Keep entries short and practical, focused on user action rather than deep
  technical explanations.

## 4. Decouple Live Stats From Passive Item Reads

Status: `[Done]`

Current branch notes:

- Live stats and passive item reads are now split into separate calls.
- Passive item read failure no longer resets valid player stats and instead falls back to `Items unavailable`.
- The live stats tab also refreshes immediately when opened instead of waiting only for the background timer.

Current issue:

- The `Live Stats` refresh path currently reads player stats and passive items
  as one combined operation.
- If the passive item inventory path is temporarily unavailable, stale, or not
  initialized yet, the whole `Live Stats` update falls back to waiting state
  even when the core player stat table is already readable.
- This makes the tab feel inconsistent at run start because stats may be ready
  before the item dictionary is stable.

Goal:

- Decouple core stat reads from passive item reads so the tab can show live
  stats as soon as stats are available.
- Treat items as optional / best-effort data instead of a hard requirement for
  the entire refresh cycle.

Recommended behavior:

- Read player stats first.
- If stats fail, keep the current `Waiting for game/player stats...` behavior.
- If stats succeed, update the stat rows immediately.
- Read passive items separately:
  - if item read succeeds, update the items section normally
  - if item read fails, keep the stat values visible and show a safe fallback in
    the items area such as `--` or `Items unavailable`
- Do not let a passive item read failure reset already-good stat values.

Why this helps:

- Removes a false dependency between two different memory paths.
- Makes `Live Stats` appear to start faster and more reliably.
- Reduces the chance that short inventory initialization gaps make the whole tab
  look broken.

Possible implementation shape:

- Split the current combined helper into separate calls, such as:
  - `read_player_stats_only()`
  - `read_passive_items_only()`
- Keep player stat failure as the only condition that fully blocks the live
  stats panel.
- Handle passive item read errors locally with a narrow fallback instead of
  bubbling them up to the full refresh handler.

Nice-to-have follow-up:

- Consider forcing an immediate refresh when the user switches to the
  `Live Stats` tab instead of waiting for the next background timer tick.

## 5. Add Upgraded Weapon Details To Live Stats And Recordings

Status: `[Done]`

Current branch notes:

- Reverse research is done and documented in `docs/reverse/reports/2026-05-19-live-weapon-stats-and-upgrades.md`.
- Upgraded weapon details are shown in `Live Stats`.
- Recordings store weapon snapshots and the viewer remains compatible with older files that do not contain weapon data.

Goal:

- Add current run weapons to `Live Stats`.
- Show each weapon's level.
- Show the weapon-specific stats that are actually upgraded by that weapon.
- Store the same weapon details in player stats / VOD recordings.

Why this helps:

- Current `weaponStats` in memory contains all effective weapon stats, including
  stats that are not part of that weapon's own level-up pool.
- For user-facing build review, the useful view is usually:
  - weapon name
  - weapon level
  - upgraded stat values for that weapon
- Recordings become much more useful for comparing build progression across
  runs, because weapon power spikes can be lined up with player stats, items,
  and run time.

Confirmed reverse source:

- Reverse doc:
  `F:\Python\MegabonkReroll\docs\reverse\reports\2026-05-19-live-weapon-stats-and-upgrades.md`
- Stable path:
  `GameAssembly.dll + 0x2F6A4B8` -> static root -> `PlayerStatsNew +0x28`
  -> `PlayerInventory +0x28` -> `WeaponInventory +0x18`
  -> `Dictionary<EWeapon, WeaponBase>`
- Per weapon:
  - `WeaponBase +0x20` -> `level`
  - `WeaponBase +0x28` -> full `Dictionary<EStat, float>` current stats
  - `WeaponBase +0x18` -> `WeaponData`
  - `WeaponData +0xD8` -> `UpgradeData`
  - `UpgradeData +0x18` -> `List<StatModifier> upgradeModifiers`

Recommended behavior:

- Parse the full `weaponStats` dictionary for each live weapon.
- Parse `upgradeModifiers` for the same weapon.
- Use `upgradeModifiers[*].stat` as the whitelist for default UI display.
- Show only whitelisted stats in the normal `Live Stats` weapon section.
- Optionally expose the complete `weaponStats` dictionary in an advanced/debug
  view.
- In recordings, store enough data to reconstruct both views later:
  - weapon id / name
  - level
  - full stats
  - upgrade stat ids
  - upgraded-only stat values

Suggested snapshot schema:

```text
weapons: [
  {
    "id": 0,
    "name": "FireStaff",
    "level": 3,
    "full_stats": {
      "12": 10.0,
      "16": 2.0
    },
    "upgrade_stat_ids": [9, 16, 12, 11],
    "upgraded_stats": {
      "9": 1.16,
      "16": 2.0,
      "12": 10.0,
      "11": 0.6
    }
  }
]
```

Implementation order:

- Add a dedicated memory reader for live weapons.
- Return a normalized weapon snapshot structure.
- Add a compact weapon section to `Live Stats`.
- Extend VOD/player stats snapshot writing with optional `weapons`.
- Update recording viewer to tolerate old recordings without `weapons`.
- Add comparison UI later if useful.

Caveats:

- Avoid heap scans as the primary source because old run weapon objects can
  remain in memory.
- Always resolve weapons through the live `PlayerStatsNew -> PlayerInventory`
  chain.
- `UpgradeData.GetUpgradeOffer(rarity, eWeapon)` may still apply offer-time
  rarity scaling or special selection behavior; `upgradeModifiers` is the
  confirmed source for the weapon's upgrade stat pool, not necessarily the exact
  currently offered upgrade roll.

## 6. Track Tomes In Live Stats And Recordings

Status: `[Done]`

Current branch notes:

- Live tome tracking is implemented.
- The rooted runtime path is confirmed:
  `PlayerStatsNew +0x28 -> PlayerInventory +0x48 -> TomeInventory`.
- The implementation uses:
  - `TomeInventory +0x18` -> `tomeLevels`
  - `TomeInventory +0x28` -> `tomeUpgrade`
- `Live Stats` and `Recordings` now show tome cards with name, level, and live
  effective modifier.
- Recordings store optional `tomes` and remain backward-compatible with older
  files.

Goal:

- Add tome tracking to `Live Stats`.
- Store tome snapshots in recordings.
- Show tome progression in playback, similar to weapons/items.

Why this helps:

- Tomes are a major part of run scaling and build identity.
- Current recordings can show player stats, items, and weapons, but not the
  tome layer that may explain why stats changed.
- Tome snapshots would make later run review much easier, especially for
  comparing build paths.

Likely implementation shape:

- Confirm the live `tomeInventory` layout from
  `PlayerInventory +0x48`.
- Identify whether tomes are stored as:
  - a dictionary keyed by tome id,
  - a list of active tome objects,
  - or a custom inventory structure.
- Decode per tome:
  - tome id / name
  - level or stack count, if applicable
  - rarity, if stored
  - upgraded stat/effect, if available
- Add a normalized `TomeSnapshot` data structure in `player_stats.py`.
- Extend `vod_storage.py` snapshot schema with optional `tomes`.
- Add a compact UI section or card under `Live Stats` / `Recordings`.

Questions to answer:

- Are all tome effects represented in one inventory object, or are special
  tomes like Chaos stored/applied through separate state?
- Does tome data contain final applied stat modifiers, or only source tome ids?
- Are tome effects already reflected in player stats only, or can we show the
  exact tome source of each stat change?

Caveats:

- Some tome data may be static catalog data while live inventory only stores ids.
- Chaos Tome may need special handling because its stat selection and scaling
  path differs from normal tome data.
- Avoid heap scans; prefer rooted `PlayerStatsNew -> PlayerInventory` paths.

## 7. Track Item Bans

Status: `[Done]`

Current branch notes:

- Live banish tracking is implemented and CE-validated.
- The confirmed rooted source is:
  `GameAssembly.dll + 0x2F7A210 -> RunUnlockables static fields`.
- Runtime separation is now confirmed:
  - `banishedItems` -> passive item banishes
  - `banishedUpgradables` -> tome/upgradable banishes
- The app merges both into one compact `Banishes` UI card in appearance order,
  per user preference.
- Recordings store optional `banishes` and older files remain loadable.

Goal:

- Detect which items are currently banned/removed from the item pool.
- Show banned items in the UI.
- Store ban state in recordings so item pool decisions can be reviewed later.

Why this helps:

- Item bans affect future chest/shop/item offer quality.
- Reviewing a run without knowing the ban list can make item progression harder
  to explain.
- For build analysis, bans are useful context next to `Items`, `New Items`, and
  `Stage Summary`.

Likely implementation shape:

- Start from the static item catalog:
  `DataManager.Instance -> itemData Dictionary<EItem, ItemData>`.
- Investigate whether live bans mutate:
  - `ItemData.inItemPool`,
  - a player-specific banned item set/list,
  - an encounter/shop offer filter,
  - or another runtime item pool structure.
- Decode banned item ids into display names using the existing item enum/name
  normalization.
- Add a `Banned Items` card or a collapsible section near the item list.
- Store optional `banned_items` in VOD snapshots.

Questions to answer:

- Are bans global for the run, character-specific, or offer-source-specific?
- Does the game keep original item catalog state and overlay bans elsewhere?
- Are temporary exclusions and permanent bans represented in the same structure?
- Do mods/cheats update the same ban path as normal gameplay?

Caveats:

- Raw `HashSet` slot order should not be used as the presentation order.
- `banishedUpgradables` currently decodes tomes correctly, but should be
  re-checked if the game later banishes other upgradable types through the same
  structure.
