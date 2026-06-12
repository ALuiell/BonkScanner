# Functional Updates Archive

This file archives completed, shelved, or old functional updates, helping keep `functional_updates.md` focused on active tasks.

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

- `twitch_bot.py`
- `live_run_tracker.py`
- `player_stats.py`
- `gui_dialogs.py`
- `gui_twitch.py`
- `tests/test_twitch_bot.py`
- `tests/test_live_run_tracker.py`
- `tests/test_player_stats.py`

---

## Part 1: Completed / Done Items (Archived 2026-06-02)

### 0. Find A Reliable Runtime Signal For True Menu / Non-Gameplay State

Status: `[Done]`

- Implemented in [game_data.py](file:///f:/Python/MegabonkReroll/game_data.py) and [gui_player_stats.py](file:///f:/Python/MegabonkReroll/gui_player_stats.py).
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

Notes:

- Before implementation, confirm the exact internal setting name, target config object, field offset, and value type.
- This may be an `int 0..100`, `int 1..100`, or `float 0.0..1.0`.
- If the game slider is truly clamped to `1..100`, `OFF = 1` may be safer than `OFF = 0`.
- Preferred path should match the current safe settings flow: `CurrentSettings.BetterUpdateCfSettings(...)` on the main thread.
- Fallback should remain a raw write + `SaveConfig` only if the field path and type are confirmed.
- Reverse doc F:\Python\MegabonkReroll\docs\reverse\reports\2026-05-13-particles-opacity-settings.md

Possible improvement:

- Add config values for the two hotkey targets instead of hardcoding them.
- Example:
  - `PARTICLES_OPACITY_HOTKEY_ON = 50`
  - `PARTICLES_OPACITY_HOTKEY_OFF = 0`
- That gives flexibility if `0` turns out unsafe and we need to switch to `1` without touching code again.

---

### 2. Auto-Split Player Stats Recording By Run

Status: `[Done]`

- Recording now tracks run seed changes and auto-splits into a new file when the seed changes.
- Missing seed is handled with a grace window and auto-stop after the run ends.
- The suggested config knobs are still not exposed as user-facing settings.

Goal:

- If the user starts player stats recording and forgets to stop it, the program should automatically split recordings across separate runs.

Proposed behavior:

- While recording is active, monitor the current run seed.
- If the seed changes:
  - finish the current recording
  - immediately start a new recording
- If the seed becomes unavailable / absent:
  - treat that as run end, exit to menu, or invalid state
  - stop the current recording cleanly

Why this helps:

- Prevents one very long recording file from containing multiple unrelated runs.
- Makes recorded stat timelines line up with actual runs even when the user forgets to toggle recording off manually.

Possible improvement:

- Add a short grace window before splitting or stopping.
- Example:
  - if seed is missing for less than `N` seconds, keep current recording alive
  - if still missing after `N` seconds, stop it
- This avoids accidental splits during short transition moments.

Suggested config knobs:

- `PLAYER_STATS_AUTO_SPLIT_BY_SEED = true/false`
- `PLAYER_STATS_MISSING_SEED_GRACE_SECONDS = 3`

---

### 3. Built-In Help / Guide Dialog

Status: `[Done]`

- Main UI now includes a compact `?` help button next to the settings button.
- Help opens as an in-app dialog instead of relying only on external docs.
- The dialog currently exposes language tabs for `ENG`, `UA`, and `RU`.
- Help content is stored in `docs/help/` as separate text files instead of being hardcoded in `gui.py`.
- Packaged builds include those help files through the current PyInstaller paths.

Goal:

- Add an in-app help / guide button so common workflow notes and edge cases are explained directly inside BonkScanner.

Why this helps:

- Reduces repeated user questions.
- Makes the app feel more self-explanatory.
- Avoids relying only on external README/manual files for operational details.

Recommended format:

- Add a `Help` or `Guide` button in the main UI.
- Open a compact dialog with short practical sections instead of one long wall of text.

Suggested sections:

- `Reroll`
- `Templates`
- `Hotkeys`
- `Recording`
- `Native Hook`
- `Known Notes`

Examples of notes to include:

- If templates are changed during an active reroll cycle, press `Stop` and then `Start` again so the new templates are applied cleanly.
- Some hotkey setting changes apply to gameplay immediately, but the in-game settings UI may only visually refresh after reopening that menu.
- Native hook restart can only attach after the game reaches a safe initialized runtime state.
- Player stats recording continues until it is stopped manually, unless future auto-split logic is added.

Possible improvement:

- Add a small `Common Questions` or `Important Notes` section for the most frequent confusion points.
- Keep entries short and practical, focused on user action rather than deep technical explanations.

---

### 4. Decouple Live Stats From Passive Item Reads

Status: `[Done]`

- Live stats and passive item reads are now split into separate calls.
- Passive item read failure no longer resets valid player stats and instead falls back to `Items unavailable`.
- The live stats tab also refreshes immediately when opened instead of waiting only for the background timer.

Current issue:

- The `Live Stats` refresh path currently reads player stats and passive items as one combined operation.
- If the passive item inventory path is temporarily unavailable, stale, or not initialized yet, the whole `Live Stats` update falls back to waiting state even when the core player stat table is already readable.
- This makes the tab feel inconsistent at run start because stats may be ready before the item dictionary is stable.

Goal:

- Decouple core stat reads from passive item reads so the tab can show live stats as soon as stats are available.
- Treat items as optional / best-effort data instead of a hard requirement for the entire refresh cycle.

Recommended behavior:

- Read player stats first.
- If stats fail, keep the current `Waiting for game/player stats...` behavior.
- If stats succeed, update the stat rows immediately.
- Read passive items separately:
  - if item read succeeds, update the items section normally
  - if item read fails, keep the stat values visible and show a safe fallback in the items area such as `--` or `Items unavailable`
- Do not let a passive item read failure reset already-good stat values.

Why this helps:

- Removes a false dependency between two different memory paths.
- Makes `Live Stats` appear to start faster and more reliably.
- Reduces the chance that short inventory initialization gaps make the whole tab look broken.

Possible implementation shape:

- Split the current combined helper into separate calls, such as:
  - `read_player_stats_only()`
  - `read_passive_items_only()`
- Keep player stat failure as the only condition that fully blocks the live stats panel.
- Handle passive item read errors locally with a narrow fallback instead of bubbling them up to the full refresh handler.

Nice-to-have follow-up:

- Consider forcing an immediate refresh when the user switches to the `Live Stats` tab instead of waiting for the next background timer tick.

---

### 5. Add Upgraded Weapon Details To Live Stats And Recordings

Status: `[Done]`

- Reverse research is done and documented in `docs/reverse/reports/2026-05-19-live-weapon-stats-and-upgrades.md`.
- Upgraded weapon details are shown in `Live Stats`.
- Recordings store weapon snapshots and the viewer remains compatible with older files that do not contain weapon data.

Goal:

- Add current run weapons to `Live Stats`.
- Show each weapon's level.
- Show the weapon-specific stats that are actually upgraded by that weapon.
- Store the same weapon details in player stats / VOD recordings.

Why this helps:

- Current `weaponStats` in memory contains all effective weapon stats, including stats that are not part of that weapon's own level-up pool.
- For user-facing build review, the useful view is usually:
  - weapon name
  - weapon level
  - upgraded stat values for that weapon
- Recordings become much more useful for comparing build progression across runs, because weapon power spikes can be lined up with player stats, items, and run time.

Confirmed reverse source:

- Reverse doc: `F:\Python\MegabonkReroll\docs\reverse\reports\2026-05-19-live-weapon-stats-and-upgrades.md`
- Stable path: `GameAssembly.dll + 0x2F6A4B8` -> static root -> `PlayerStatsNew +0x28` -> `PlayerInventory +0x28` -> `WeaponInventory +0x18` -> `Dictionary<EWeapon, WeaponBase>`
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
- Optionally expose the complete `weaponStats` dictionary in an advanced/debug view.
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

- Avoid heap scans as the primary source because old run weapon objects can remain in memory.
- Always resolve weapons through the live `PlayerStatsNew -> PlayerInventory` chain.
- `UpgradeData.GetUpgradeOffer(rarity, eWeapon)` may still apply offer-time rarity scaling or special selection behavior; `upgradeModifiers` is the confirmed source for the weapon's upgrade stat pool, not necessarily the exact currently offered upgrade roll.

---

### 6. Track Tomes In Live Stats And Recordings

Status: `[Done]`

- Live tome tracking is implemented.
- The rooted runtime path is confirmed: `PlayerStatsNew +0x28 -> PlayerInventory +0x48 -> TomeInventory`.
- The implementation uses:
  - `TomeInventory +0x18` -> `tomeLevels`
  - `TomeInventory +0x28` -> `tomeUpgrade`
- `Live Stats` and `Recordings` now show tome cards with name, level, and live effective modifier.
- Recordings store optional `tomes` and remain backward-compatible with older files.

Goal:

- Add tome tracking to `Live Stats`.
- Store tome snapshots in recordings.
- Show tome progression in playback, similar to weapons/items.

Why this helps:

- Tomes are a major part of run scaling and build identity.
- Current recordings can show player stats, items, and weapons, but not the tome layer that may explain why stats changed.
- Tome snapshots would make later run review much easier, especially for comparing build paths.

Likely implementation shape:

- Confirm the live `tomeInventory` layout from `PlayerInventory +0x48`.
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

- Are all tome effects represented in one inventory object, or are special tomes like Chaos stored/applied through separate state?
- Does tome data contain final applied stat modifiers, or only source tome ids?
- Are tome effects already reflected in player stats only, or can we show the exact tome source of each stat change?

Caveats:

- Some tome data may be static catalog data while live inventory only stores ids.
- Chaos Tome may need special handling because its stat selection and scaling path differs from normal tome data.
- Avoid heap scans; prefer rooted `PlayerStatsNew -> PlayerInventory` paths.

---

### 7. Track Item Bans

Status: `[Done]`

- Live banish tracking is implemented and CE-validated.
- The confirmed rooted source is: `GameAssembly.dll + 0x2F7A210 -> RunUnlockables static fields`.
- Runtime separation is now confirmed:
  - `banishedItems` -> passive item banishes
  - `banishedUpgradables` -> tome/upgradable banishes
- The app merges both into one compact `Banishes` UI card in appearance order, per user preference.
- Recordings store optional `banishes` and older files remain loadable.

Goal:

- Detect which items are currently banned/removed from the item pool.
- Show banned items in the UI.
- Store ban state in recordings so item pool decisions can be reviewed later.

Why this helps:

- Item bans affect future chest/shop/item offer quality.
- Reviewing a run without knowing the ban list can make item progression harder to explain.
- For build analysis, bans are useful context next to `Items`, `New Items`, and `Stage Summary`.

Likely implementation shape:

- Start from the static item catalog: `DataManager.Instance -> itemData Dictionary<EItem, ItemData>`.
- Investigate whether live bans mutate:
  - `ItemData.inItemPool`,
  - a player-specific banned item set/list,
  - an encounter/shop offer filter,
  - or another runtime item pool structure.
- Decode banned item ids into display names using the existing item enum/name normalization.
- Add a `Banned Items` card or a collapsible section near the item list.
- Store optional `banned_items` in VOD snapshots.

Questions to answer:

- Are bans global for the run, character-specific, or offer-source-specific?
- Does the game keep original item catalog state and overlay bans elsewhere?
- Are temporary exclusions and permanent bans represented in the same structure?
- Do mods/cheats update the same ban path as normal gameplay?

Caveats:

- Raw `HashSet` slot order should not be used as the presentation order.
- `banishedUpgradables` currently decodes tomes correctly, but should be re-checked if the game later banishes other upgradable types through the same structure.

---

### 8. Manual Snapshot-To-Snapshot Compare In Recordings Viewer

Status: `[Done]`

- The `Recordings` viewer now supports setting a selected snapshot as the compare start and clearing/replacing that compare start.
- The old `New Items` card was replaced with a compact `Segment Compare` card.
- The compact card shows:
  - item gains by rarity as colored dot totals
  - `Items Total`
  - broken `Za Warudo` count when the item was consumed after being acquired
  - lost item count when non-breakable item stacks disappear
  - segment time delta
  - mob kill delta
  - level delta
- A collapsible `Compare Details` section shows the full item-gain list grouped by rarity, with one colored dot per rarity row and item gains inline.
- `Compare Details` separates `Gained`, `Broken`, and `Lost` item changes so consumed `Za Warudo` stacks remain visible in run analysis instead of silently disappearing from the comparison.
- Without a pinned compare start, recordings still compare the selected snapshot against the previous snapshot.
- With a pinned compare start, recordings compare the selected snapshot against that pinned baseline.
- The `Live Stats` summary row now uses the same compact `Segment Compare` card style for recorded snapshot deltas, without the recordings-only details panel.

Goal:

- Let the user compare any two chosen snapshots from the same recording instead of always comparing only current vs previous.

Why this helps:

- Makes it easy to inspect item gains across a specific segment of a run.
- Makes level and kill deltas more useful than strict previous-snapshot comparison.
- Creates reusable snapshot-delta formatting that can later support the dedicated `Compare Runs` tab.

Implementation note:

- This remains separate from time-synced `Compare Runs`.
- The details panel is intentionally recordings-only; `Live Stats` keeps only a compact summary card for now.

---

## Part 2: Archived & Shelved Planning Items (Archived 2026-05-29)

### 9. Compare Runs By In-Game Time

Status: `[Archived]`

Goal:

- Reverse the part of the game that tracks the run's internal elapsed time / current in-game time.
- Add that value into player stats recording snapshots as first-class recorded data.
- Add a new tab such as `Compare Runs` for loading and comparing two recorded runs side by side at the same gameplay moment.

Why this helps:

- Snapshot index and wall-clock capture time are useful, but they do not always represent the same gameplay stage across different runs.
- In-game elapsed time would let the app align two runs by actual run progress.
- This would make it much easier to compare stats, item progression, and build state at the same point in a run.
- This is especially valuable for:
  - comparing early-game routing
  - checking when a build starts to spike
  - seeing how item and stat progression differs between good vs bad runs
  - reviewing why one run stabilized faster than another

Proposed behavior:

- Find and confirm the in-memory value the game uses for current run time.
- Store that value in each recorded snapshot together with the existing player stats and items data.
- In `Compare Runs`, let the user load two `.jsonl` recordings.
- Synchronize both timelines by the recorded in-game elapsed time instead of only by snapshot position.
- Show both runs side by side so the user can compare:
  - player stats
  - items
  - overall build state
  - the same gameplay phase across both runs

Suggested UX:

- Left side: `Run A`
- Right side: `Run B`
- Shared top controls:
  - load first run
  - load second run
  - jump to time
  - scrub both timelines together
- When the user moves to `02:30`, both runs should snap to the nearest recorded snapshot for that in-game time.
- The compare tab should clearly display:
  - recorded in-game time for each side
  - actual selected snapshot timestamp
  - whether one side had to snap forward / backward because an exact time match was unavailable

Recommended implementation shape:

- First finish reverse work and document:
  - exact source object / path
  - value type
  - units used by the game
  - whether the value pauses in menus / loading / death states
- Extend the VOD snapshot schema with a dedicated field for in-game elapsed time.
- Keep backward compatibility for older `.jsonl` recordings that do not contain this field.
- Build the compare UI as a separate tab instead of overloading the current single-run recordings viewer.
- Suggested implementation order:
  - phase 1: reverse and validate in-game time source
  - phase 2: record the value into snapshots / `.jsonl`
  - phase 3: expose it in the existing recordings viewer
  - phase 4: build dedicated `Compare Runs` tab
  - phase 5: add comparison-specific quality-of-life features

Important caveats:

- We need to verify whether the game time value is:
  - real gameplay time
  - scaled time
  - paused in menus
  - reset correctly on new runs
- If the timer is affected by pause states, loading, or special slow/fast game states, compare logic should document that clearly.
- Old recordings without the new field should either:
  - disable time-synced compare mode
  - or fall back to simple snapshot-based comparison with a visible note
- Comparison should be based on nearest available snapshot, so large snapshot intervals may reduce comparison precision.
- If this feature becomes important, we may want lower recording intervals for runs intended specifically for analysis.

Possible improvements:

- Add a delta view showing stat differences between the two runs at the same in-game time.
- Add quick jump buttons such as `30s`, `1m`, `2m`, `5m`.
- Add highlighting for missing / changed items between the two compared runs.
- Add an option to pin one run as a reference and quickly cycle through many other runs against it.
- Add export of comparison summaries for sharing and debugging.

---

### 10. Add Run Damage Breakdown To Live Stats, Recordings, And Compare Runs

Status: `[Archived]`

Goal:

- Add a first-class run field that shows how much damage each source has dealt during the current run.
- Use the same structure in:
  - `Live Stats`
  - saved `Recordings`
  - `Compare Runs`
- Preserve enough detail that future UI can show both compact totals and more advanced compare views without requiring another reverse pass.

Why this helps:

- It makes build analysis much more useful than only showing inventory, weapons, tomes, or total kills.
- It becomes much easier to answer:
  - which weapon is actually carrying the run
  - whether an item proc is overperforming or underperforming
  - when a source starts contributing meaningful damage
  - how two runs differ in real output, not just build shape
- It gives a natural post-hoc analysis feature for routing, balancing, and debugging scanner correctness.

#### Confirmed Runtime Source

Canonical runtime owner:

- `Assets.Scripts.Saves___Serialization.Progression.Stats.RunStats`

Relevant fields from dump:

- `private static Dictionary<string, float> stats; // 0x0`
- `public static Dictionary<string, DamageSource> damageSources; // 0x8`

Relevant related types:

- `Assets.Scripts.Saves___Serialization.Progression.Stats.DamageSource`
- `Assets.Scripts.Actors.DamageContainer`
- `WeaponData.damageSourceName`

What the data means:

- `RunStats.damageSources` is a current-run dictionary keyed by damage source name string.
- Each value is a `DamageSource` object that stores:
  - `damageSource`
  - `addedAtTime`
  - `damage`
- Combat hits use `DamageContainer.damageSource`, and the run stat system adds damage into the matching `RunStats.damageSources` bucket.

This strongly suggests the feature should be implemented as a direct runtime read of `RunStats.damageSources`, not as a derived estimate.

#### Important Dump References

Primary reverse files:

- `F:\Python\CA_mpc_bridge\Dump\dump.cs`
- `F:\Python\CA_mpc_bridge\Dump\il2cpp.h`
- `F:\Python\CA_mpc_bridge\Dump\script.json`

Most useful symbols:

- `RunStats.damageSources`
- `RunStats.OnEnemyDamaged(Enemy enemy, DamageContainer dc)`
- `DamageSource`
- `DamageContainer.damageSource`
- `WeaponData.damageSourceName`
- `WeaponUtility.GetDamageContainer(..., string damageSourceName, ...)`
- `GameOverDamageSourcesUi`
- `DamageSourceEntry`
- `LocalizationUtility.GetLocalizedDamageSource`

Useful UI confirmation symbols:

- `GameOverDamageSourcesUi.Start()`
- `DamageSourceEntry.Set(DamageSource dmgSource)`
- `DamageSourceEntry` fields:
  - `t_sourceName`
  - `t_lvl`
  - `t_dmg`
  - `t_dps`

This is useful because it confirms:

- the game already expects `DamageSource` as a user-facing summary object
- the source names can be localized
- the game-over screen is already a good behavioral reference for how this data should look when sorted and displayed

#### Rooted Memory Shape

Class root:

```text
GameAssembly.dll + <RunStats_TypeInfo_Offset>
-> [read qword] RunStats class ptr
-> +0xB8
-> [read qword] static fields
-> +0x8
-> [read qword] Dictionary<string, DamageSource> damageSources
```

Static field layout from dump:

```text
RunStats static fields
+0x0 stats Dictionary<string, float>
+0x8 damageSources Dictionary<string, DamageSource>
+0x10 achievements
+0x18 A_StatChange
```

`DamageSource` object layout from dump:

```text
DamageSource
+0x10 string damageSource
+0x18 float addedAtTime
+0x1C float damage
```

`DamageContainer` object layout from dump:

```text
DamageContainer
+0x1C float damage
+0x40 string damageSource
```

Implementation note:

- The last stable rooted object is the dictionary itself.
- Like `RunStats.stats["kills"]`, this should be treated as a dictionary scan problem, not a fixed final pointer.
- The exact `Dictionary.Entry<string, DamageSource>` value layout should be confirmed live before implementation is locked in.

#### Expected Read Strategy

Recommended first implementation:

1. Resolve `RunStats.damageSources` from the rooted static field path.
2. Read dictionary `count` and `entries`.
3. Iterate entries.
4. For each valid entry:
   - read key string
   - read value object pointer
   - dereference `DamageSource`
   - read `damageSource`, `addedAtTime`, `damage`
5. Normalize into a Python-side list sorted by descending damage.

Recommended normalized runtime structure:

```text
DamageSourceSnapshot(
  source_key,
  source_name,
  localized_name,
  damage,
  added_at_time,
  level=None,
  source_kind=None,
)
```

Notes:

- `source_key` should preserve the raw internal key exactly as read from memory.
- `source_name` may duplicate the raw key at first.
- `localized_name` can be added later if we implement source-name localization.
- `level` is not directly stored in `DamageSource`; if later desired, it will need a separate mapping step for weapons/items that expose current level.
- `source_kind` is optional future metadata such as `weapon`, `item`, `passive`, `proc`, or `unknown`.

#### Proposed Feature Scope

Phase 1:

- Read `RunStats.damageSources` live.
- Show a compact sorted list in `Live Stats`.
- Store optional `damage_sources` in recording snapshots.

Phase 2:

- Show the same snapshot data in `Recordings`.
- Keep backward compatibility for old recordings without `damage_sources`.

Phase 3:

- Add `Compare Runs` damage comparison views:
  - current total per source at selected synced time
  - damage delta between `Run A` and `Run B`
  - added/removed source highlighting

Phase 4:

- Improve source labeling:
  - localized source names
  - optional source kind tagging
  - optional source level reconstruction for weapons/items

#### Suggested UI Shape

For `Live Stats`:

- Add a `Damage Sources` section or tab.
- Show a sorted list by descending total damage.
- Initial compact rows can include:
  - source name
  - total damage
  - share of total damage

For `Recordings`:

- Show the same structure for the selected snapshot.
- If compare-start snapshot is pinned, optionally show segment delta for damage sources between two snapshots in the same run.

For `Compare Runs`:

- Side-by-side source tables for `Run A` and `Run B`
- One central diff panel or inline delta columns
- Useful fields:
  - source present on both sides
  - total damage difference
  - percent share difference

#### Recording Schema Recommendation

Add an optional snapshot field such as:

```json
"damage_sources": [
  {
    "source_key": "string",
    "source_name": "string",
    "localized_name": "string or null",
    "damage": 12345.0,
    "added_at_time": 12.34
  }
]
```

Compatibility rules:

- old recordings without `damage_sources` must continue to load normally
- missing field should display as unavailable rather than zero
- snapshot compare code should tolerate different source sets between snapshots

#### Validation Checklist

Live validation before implementation is considered safe:

1. Confirm the rooted `RunStats.damageSources` pointer is stable across:
   - fresh run start
   - stage transition
   - death / end-run flow
2. Confirm dictionary entries update live as damage is dealt.
3. Confirm at least one weapon source and one item/proc source appear in the dictionary during a real run.
4. Confirm the top sources and totals broadly match the in-game game-over damage breakdown UI.
5. Confirm values reset correctly on a true new run.
6. Confirm stale previous-run data does not leak into a new recording after run split.

Nice-to-have validation:

- confirm whether `addedAtTime` reflects first-seen run time for that source
- confirm whether non-damaging equipped items stay absent
- confirm how summons, chain effects, thorns, bleed, poison, or reflection sources are named
- confirm whether source names are stable internal identifiers across builds

#### Risks And Caveats

- The rooted class path is good, but dictionary entry layout still needs live confirmation for `Dictionary<string, DamageSource>`.
- The source keys may be internal ids rather than polished user-facing names.
- Some sources may be ambiguous without extra mapping:
  - proc effects
  - debuffs
  - item-triggered secondary damage
- `DamageSource` does not directly store source level, so `Lv.` style detail is not free for this feature.
- If source names are localized only through game methods, pure memory reads may initially show raw keys until we add our own mapping layer or hook-based helper.

#### Implementation Handoff Notes

When this feature is picked up later, start here:

1. Reconfirm `RunStats.damageSources` root on the current game build.
2. Document the live `Dictionary.Entry<string, DamageSource>` layout in a dedicated reverse report.
3. Implement a Python normalizer in the same style as existing live item/weapon/tome snapshot readers.
4. Store the normalized list into recordings as an optional field.
5. Add UI in `Live Stats` first, then `Recordings`, then `Compare Runs`.

This is a high-value feature because it converts the scanner from a build-state viewer into an actual run-output analysis tool.

---

### 11. Overlay Upgrade

Status: `[Archived]`

Goal:

- Improve the current local OBS overlay tab and browser-source output so it is more compact, clearer, easier to configure, and more practical for stream layouts.

Requirements:

1. `Tracked Items` should become collapsible in the app UI.
   - The section should default to a compact collapsed presentation or otherwise behave in a clearly space-saving way.
   - When the OBS Overlay tab is shown in a narrow window, the tracked-items area must not collapse into an unusable squeezed layout.
   - Prioritize a small-window-friendly layout similar to the requested mockup.

2. Simplify the overlay server status row to remove duplicated wording.
   - Replace the current pattern similar to `OBS Overlay server OBS Overlay running | live/stop`.
   - Use a layout in this spirit:
     - `OBS Overlay server | status: live/stop`
     - `Start/Stop` button
   - The final wording can vary slightly, but the row must be shorter, cleaner, and free from duplicated status labels.

3. Change overlay items from a vertical list to a horizontal row-based presentation where appropriate.
   - This applies to the visible overlay output for item widgets.
   - The result should stay readable in stream usage and avoid unnecessary height growth.

4. Add a new collapsible widget named `Stats`.
   - The user must be able to choose which stats are included in this widget.
   - The selected stats should appear inside the widget in a compact list.
   - The presentation should be lightweight and readable for stream overlays, using small thumbnail-style entries or similarly compact stat rows.

5. Support direct widget-specific overlay URLs so each widget can be added to OBS as a separate browser source.
   - Today the full overlay is exposed through a single route like `http://127.0.0.1:17845/overlay`.
   - Add per-widget routes in the spirit of `http://127.0.0.1:17845/overlay/<widget_name>`.
   - Streamers should be able to place, scale, and position each widget independently in OBS by using those dedicated URLs.

Implementation notes:

- Preserve the current local overlay architecture unless there is a clear technical reason to change it.
- Reasonable improvements beyond the exact checklist are welcome if they improve clarity, compactness, maintainability, or stream usability.
- Keep the result lightweight and consistent with the existing app.

---

### 12. Add A Local OBS Overlay Builder Backed By A Live Run Tracker

Status: `[Archived]`

Owner-facing summary:

- Build this as a local `OBS` / `Streamlabs` browser-source overlay, not as a Twitch API integration.
- The overlay should be configurable from a new `Overlay` tab.
- The overlay must work without `.jsonl` recording enabled.
- Any metric that needs history, such as `Stage Summary` or `Anvils on map 1`, should be powered by a new in-memory live run tracker.

#### Recommended Decision

Implement the feature as three separate layers:

1. `Live snapshot source`
   - The existing live stats refresh already reads the game process and produces the raw ingredients.
   - The implementation should normalize those values once per refresh.
   - The normalized snapshot should then feed both recording and overlay analytics.

2. `Live run tracker`
   - A new in-memory object that stores short current-run history.
   - It computes stage summary, tracked item counters, item gains, per-stage kills, and other stream-facing derived metrics.
   - It never writes files and does not depend on recording state.

3. `Overlay server + UI builder`
   - A local loopback HTTP server serves browser overlay HTML and JSON state.
   - The desktop `Overlay` tab controls enabled widgets, tracked items, and display options.
   - `OBS` consumes the overlay URL as a Browser Source.

This is the cleanest implementation because it avoids turning `vod_storage.py` into a live analytics dependency. Recording remains persistence. Overlay tracking becomes live analytics.

#### Non-Goals For The First Version

- Do not integrate with Twitch API, chat, EventSub, OAuth, or cloud services.
- Do not require a public web server.
- Do not require users to enable player stats recording.
- Do not implement WebSocket first. Polling a local JSON endpoint every `250-500ms` is enough for MVP and is easier to debug in `OBS`.
- Do not build a full drag-and-drop layout editor in the first pass.
- Do not try to count every possible advanced metric before the tracker shape is stable.

#### Existing Code Anchors

Start implementation from these places:

- `gui_player_stats.py`
  - `_read_live_player_stats_data()` already reads:
    - stats
    - items
    - weapons
    - tomes
    - banishes
    - damage sources
    - run timer
    - stage timer
    - mob kills
    - player level
    - map seed
    - current stage pointer
  - `refresh_live_player_stats_now()` is the best first integration point for feeding the live tracker.
  - Current non-recording UI path passes `stage_summary_rows=None`.
  - Current recording path builds stage summary from `self.player_stats_vod_snapshots`.

- `gui_app.py`
  - `MegabonkApp.__init__()` owns long-lived runtime state.
  - Add tracker/server references here, for example:
    - `self.live_run_tracker`
    - `self.overlay_state`
    - `self.overlay_server`

- `vod_storage.py`
  - Keep this focused on saved `.jsonl` recordings.
  - Do not make overlay analytics depend on `VodRecorder`.

- `player_stats.py`
  - Has snapshot-like dataclasses and runtime reader types.
  - Avoid putting overlay-specific UI or server logic here.

- `gui_layout.py`
  - Add the new `Overlay` tab near `Live Stats`, `Recordings`, and `Compare Runs`.

- `config.py`
  - Add default config loading/persistence helpers for overlay settings.

#### New Files To Add

Recommended files:

- `live_run_tracker.py`
  - Owns in-memory run history and derived metrics.
  - Pure Python, no Qt imports, no HTTP imports.
  - Unit-testable without the GUI.

- `overlay_state.py`
  - Defines overlay-facing dataclasses and JSON serialization.
  - Pure Python.
  - May include config normalization for widget settings.

- `overlay_server.py`
  - Owns local HTTP server lifecycle.
  - Uses only stdlib first: `http.server`, `socketserver`, `threading`, `json`, `mimetypes`, `pathlib`.
  - Binds to `127.0.0.1` by default.

- `gui_overlay.py`
  - `OverlayMixin` for the new tab and controls.
  - Keeps UI code out of tracker/server modules.

- `media/overlay/`
  - Static overlay assets:
    - `index.html`
    - `overlay.css`
    - `overlay.js`
  - Use plain browser code first. No build step.

#### Data Model

Add a normalized snapshot model that is independent from recording:

```python
@dataclass(frozen=True)
class LiveRunSnapshot:
    captured_at: float
    stats: dict[str, PlayerStatValue]
    items: tuple[str, ...] = ()
    items_available: bool = True
    weapons: tuple[WeaponSnapshot, ...] = ()
    weapons_available: bool = False
    tomes: tuple[TomeSnapshot, ...] = ()
    tomes_available: bool = False
    banishes: tuple[str, ...] = ()
    damage_sources: tuple[DamageSourceSnapshot, ...] = ()
    damage_sources_available: bool = False
    chests_per_minute: float | None = None
    game_time_seconds: float | None = None
    stage_time_seconds: float | None = None
    mob_kills: int | None = None
    player_level: int | None = None
    map_seed: int | None = None
    stage_ptr: int = 0
```

#### Live Tracker Responsibilities

- Accept `LiveRunSnapshot` every time live stats refresh succeeds.
- Keep a bounded list of snapshots for the current run.
- Reset when a true new run is detected.
- Compute stage summary rows.
- Compute tracked item counters from item deltas.
- Expose a JSON-friendly `OverlayState`.

#### Local HTTP Server

- Serve `/overlay`.
- Serve `/api/overlay-state`.
- Bind only to `127.0.0.1`.
- Stop cleanly on app shutdown.

#### MVP Acceptance Criteria

- Overlay renders in `OBS` via a local browser URL.
- Overlay state updates without recording enabled.
- Stage summary works without recording.
- At least one tracked-item metric works.
