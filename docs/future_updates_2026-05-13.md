# Future Updates Notes

Date: 2026-05-13

This file is a small backlog of product and hook ideas that came up during
testing. The goal is to keep them in one place with a short description of
expected behavior, likely implementation shape, and any obvious caveats.

## 1. Hotkey for Particles Opacity

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

## 3. Rework Settings Save Behavior To Reduce Micro-Stutters

Current issue:

- Hotkey setting changes are applied immediately and also saved immediately.
- Immediate `SaveConfig` can sometimes cause a small gameplay stutter.

Important constraint:

- Do not remove saving entirely.
- Runtime change and persistence should be treated as separate concerns.

Recommended direction:

- Keep immediate runtime apply through `CurrentSettings.BetterUpdateCfSettings(...)`.
- Replace immediate `SaveConfig` with deferred save logic.

Best candidate design:

- When a hotkey changes a setting:
  - apply it immediately
  - mark settings as dirty
- Save later using one of these triggers:
  - debounce timer after the last hotkey change
  - `RequestRestartRun`
  - `Uninitialize`
- Whichever trigger happens first performs one save for the latest state.

Why this is likely best:

- Gameplay effect stays instant.
- Fewer writes means fewer visible micro-stutters.
- Users who only use hotkeys still get persistence because save is not tied only
  to reroll / next-map search.

Alternative that is weaker:

- Save only when starting next map search / reroll.
- This helps the reroll workflow, but is worse for users who only toggle
  settings and do not run the search loop.

Suggested config knobs:

- `HOTKEY_SETTINGS_SAVE_MODE = immediate | deferred`
- `HOTKEY_SETTINGS_SAVE_DEBOUNCE_MS = 3000`

## 4. Built-In Help / Guide Dialog

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

## 5. Compare Runs By In-Game Time

Goal:

- Reverse the part of the game that tracks the run's internal elapsed time /
  current in-game time.
- Add that value into player stats recording snapshots as first-class recorded
  data.
- Add a new tab such as `Compare Runs` for loading and comparing two recorded
  runs side by side at the same gameplay moment.

Why this helps:

- Snapshot index and wall-clock capture time are useful, but they do not always
  represent the same gameplay stage across different runs.
- In-game elapsed time would let the app align two runs by actual run progress.
- This would make it much easier to compare stats, item progression, and build
  state at the same point in a run.
- This is especially valuable for:
  - comparing early-game routing
  - checking when a build starts to spike
  - seeing how item and stat progression differs between good vs bad runs
  - reviewing why one run stabilized faster than another

Proposed behavior:

- Find and confirm the in-memory value the game uses for current run time.
- Store that value in each recorded snapshot together with the existing player
  stats and items data.
- In `Compare Runs`, let the user load two `.jsonl` recordings.
- Synchronize both timelines by the recorded in-game elapsed time instead of
  only by snapshot position.
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
- When the user moves to `02:30`, both runs should snap to the nearest recorded
  snapshot for that in-game time.
- The compare tab should clearly display:
  - recorded in-game time for each side
  - actual selected snapshot timestamp
  - whether one side had to snap forward / backward because an exact time match
    was unavailable

Recommended implementation shape:

- First finish reverse work and document:
  - exact source object / path
  - value type
  - units used by the game
  - whether the value pauses in menus / loading / death states
- Extend the VOD snapshot schema with a dedicated field for in-game elapsed
  time.
- Keep backward compatibility for older `.jsonl` recordings that do not contain
  this field.
- Build the compare UI as a separate tab instead of overloading the current
  single-run recordings viewer.
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
- If the timer is affected by pause states, loading, or special slow/fast game
  states, compare logic should document that clearly.
- Old recordings without the new field should either:
  - disable time-synced compare mode
  - or fall back to simple snapshot-based comparison with a visible note
- Comparison should be based on nearest available snapshot, so large snapshot
  intervals may reduce comparison precision.
- If this feature becomes important, we may want lower recording intervals for
  runs intended specifically for analysis.

Possible improvements:

- Add a delta view showing stat differences between the two runs at the same
  in-game time.
- Add quick jump buttons such as `30s`, `1m`, `2m`, `5m`.
- Add highlighting for missing / changed items between the two compared runs.
- Add an option to pin one run as a reference and quickly cycle through many
  other runs against it.
- Add export of comparison summaries for sharing and debugging.

## 6. Decouple Live Stats From Passive Item Reads

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

## 7. Performance Update

Scope:

- Focus on extra impact outside the expected active map scan / reroll path.
- Do not treat `wait_for_map_ready`, map-stat polling during reroll, or restart
  timing as a problem by itself; that load is part of the tool's intended work.
- Primary target is reducing rare frametime spikes, micro-stutters, and input
  latency risk while the game is already running and BonkScanner is attached.

Current assessment:

- Average FPS impact is likely low in idle / connected states.
- Frametime / micro-stutter risk is mostly low, with a few moderate-risk burst
  paths.
- The riskiest areas are native hook live-setting saves, synchronous disk writes,
  repeated external memory reads, and global hotkey backend behavior.

Native hook priorities:

- Keep the current immediate runtime apply path through
  `CurrentSettings.BetterUpdateCfSettings(...)`.
- Defer persistence instead of calling `SaveConfig()` in the same hooked
  `AlwaysManager.Update` frame.
- Treat runtime apply and persistence as separate concerns:
  - apply setting immediately
  - mark setting state dirty
  - save later through a debounce, shutdown/uninitialize, or another safe
    non-gameplay moment
- Avoid adding any file I/O, sleeps, blocking waits, heap-heavy work, or logging
  inside the hooked `Update` path.
- Replace always-on `Interlocked.Exchange` checks in idle with a cheaper
  `Volatile.Read` fast path before exchanging, so frames with no pending request
  avoid unnecessary atomic writes.
- Consider making toggle requests a tiny queue or guarded single-flight request
  instead of a single overwriteable `_toggleSettingRequest` slot.

External memory-reading priorities:

- Cache `GameAssembly.dll` base address in `ProcessMemory` and invalidate it only
  when the process handle is recreated.
- Reduce repeated root-chain reads in `PlayerStatsClient`:
  - resolve `owner_stats` once per refresh
  - reuse it for both stats and passive item reads
- Batch player stat reads where practical:
  - read the stat entries block once
  - decode individual stat values from the local buffer
- Add a hard cap for passive item dictionary count, similar to the map-stat
  `MAX_DICT_ENTRIES` guard.
- Keep passive item reads best-effort so a temporary item-path failure does not
  force the whole live stats panel into a waiting state.

Idle / UI / recording priorities:

- Do not read live player stats every 10 seconds when the stats UI is not visible
  and recording is not active.
- Trigger an immediate stats refresh when the user opens the relevant tab, then
  keep the background timer quiet while the tab is hidden.
- Keep VOD metadata and summary writes reliable, but avoid flushing every
  snapshot record immediately.
- Prefer batched or periodic VOD flushes, plus a final flush/close on stop.
- Keep recordings list refresh gated by visible tab and signature checks.

Disk-write priorities:

- Avoid writing `config.json` on every reroll; keep `TOTAL_REROLLS` in memory and
  flush it periodically, on stop, or on clean shutdown.
- Keep immediate config saves for user-facing settings dialogs, where a short UI
  pause is less likely to affect gameplay.
- Avoid synchronous writes from paths that can be triggered while the game is in
  active combat or while the hook is running on the game main thread.

Hotkey / input priorities:

- Keep hotkey callbacks short and continue forwarding work to the UI thread with
  `after(0, ...)`.
- Avoid heavy logic directly inside keyboard callbacks.
- If users report input latency while the game is focused, add an option to
  disable nonessential global hotkeys or switch to app-focused shortcuts.

Implementation order:

- Phase 1: defer native hook `SaveConfig()` and keep runtime setting apply
  immediate.
- Phase 2: cache module bases and add passive item count caps.
- Phase 3: split / batch player stats and passive item reads.
- Phase 4: gate idle player-stats polling by visible tab or active recording.
- Phase 5: reduce VOD/config write frequency and add final flush points.
- Phase 6: micro-optimize idle hook atomics after the higher-impact items are
  done.

Validation plan:

- Measure idle CPU usage with game focused and game backgrounded.
- Measure player-stats refresh duration and number of external memory reads.
- Compare frametime before/after deferred hook saving by toggling each live
  setting during active gameplay.
- Verify VOD files remain valid after normal stop, app close, and unexpected
  recording auto-stop.

## 8. Add Upgraded Weapon Details To Live Stats And Recordings

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

