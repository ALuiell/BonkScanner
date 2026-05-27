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

## 8. Manual Snapshot-To-Snapshot Compare In Recordings Viewer

Status: `[Done]`

Current branch notes:

- The `Recordings` viewer now supports setting a selected snapshot as the
  compare start and clearing/replacing that compare start.
- The old `New Items` card was replaced with a compact `Segment Compare` card.
- The compact card shows:
  - item gains by rarity as colored dot totals
  - `Items Total`
  - broken `Za Warudo` count when the item was consumed after being acquired
  - lost item count when non-breakable item stacks disappear
  - segment time delta
  - mob kill delta
  - level delta
- A collapsible `Compare Details` section shows the full item-gain list grouped
  by rarity, with one colored dot per rarity row and item gains inline.
- `Compare Details` separates `Gained`, `Broken`, and `Lost` item changes so
  consumed `Za Warudo` stacks remain visible in run analysis instead of silently
  disappearing from the comparison.
- Without a pinned compare start, recordings still compare the selected snapshot
  against the previous snapshot.
- With a pinned compare start, recordings compare the selected snapshot against
  that pinned baseline.
- The `Live Stats` summary row now uses the same compact `Segment Compare`
  card style for recorded snapshot deltas, without the recordings-only details
  panel.

Goal:

- Let the user compare any two chosen snapshots from the same recording instead
  of always comparing only current vs previous.

Why this helps:

- Makes it easy to inspect item gains across a specific segment of a run.
- Makes level and kill deltas more useful than strict previous-snapshot
  comparison.
- Creates reusable snapshot-delta formatting that can later support the
  dedicated `Compare Runs` tab.

Implementation note:

- This remains separate from time-synced `Compare Runs`.
- The details panel is intentionally recordings-only; `Live Stats` keeps only a
  compact summary card for now.



## 4. Add A Local OBS Overlay Builder Backed By A Live Run Tracker

Status: `[Open]`

Owner-facing summary:

- Build this as a local `OBS` / `Streamlabs` browser-source overlay, not as a
  Twitch API integration.
- The overlay should be configurable from a new `Overlay` tab.
- The overlay must work without `.jsonl` recording enabled.
- Any metric that needs history, such as `Stage Summary` or `Anvils on map 1`,
  should be powered by a new in-memory live run tracker.

### Recommended Decision

Implement the feature as three separate layers:

1. `Live snapshot source`
   - The existing live stats refresh already reads the game process and
     produces the raw ingredients.
   - The implementation should normalize those values once per refresh.
   - The normalized snapshot should then feed both recording and overlay
     analytics.

2. `Live run tracker`
   - A new in-memory object that stores short current-run history.
   - It computes stage summary, tracked item counters, item gains, per-stage
     kills, and other stream-facing derived metrics.
   - It never writes files and does not depend on recording state.

3. `Overlay server + UI builder`
   - A local loopback HTTP server serves browser overlay HTML and JSON state.
   - The desktop `Overlay` tab controls enabled widgets, tracked items, and
     display options.
   - `OBS` consumes the overlay URL as a Browser Source.

This is the cleanest implementation because it avoids turning `vod_storage.py`
into a live analytics dependency. Recording remains persistence. Overlay
tracking becomes live analytics.

### Non-Goals For The First Version

- Do not integrate with Twitch API, chat, EventSub, OAuth, or cloud services.
- Do not require a public web server.
- Do not require users to enable player stats recording.
- Do not implement WebSocket first. Polling a local JSON endpoint every
  `250-500ms` is enough for MVP and is easier to debug in `OBS`.
- Do not build a full drag-and-drop layout editor in the first pass.
- Do not try to count every possible advanced metric before the tracker shape is
  stable.

### Existing Code Anchors

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
  - `refresh_live_player_stats_now()` is the best first integration point for
    feeding the live tracker.
  - Current non-recording UI path passes `stage_summary_rows=None`.
  - Current recording path builds stage summary from
    `self.player_stats_vod_snapshots`.

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
  - Add the new `Overlay` tab near `Live Stats`, `Recordings`, and
    `Compare Runs`.

- `config.py`
  - Add default config loading/persistence helpers for overlay settings.

### New Files To Add

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
  - Uses only stdlib first: `http.server`, `socketserver`, `threading`,
    `json`, `mimetypes`, `pathlib`.
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

Alternative:

- If the project owner wants fewer files, `overlay_state.py` can be folded into
  `live_run_tracker.py` at first. Keep `overlay_server.py` separate.

### Data Model

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

Do not reuse `VodSnapshot` directly as the main live model because it carries
recording-specific concepts such as elapsed recording time and file schema
compatibility.

Recommended tracker-owned state:

```python
@dataclass(frozen=True)
class TrackedItemRule:
    id: str
    label: str
    item_names: tuple[str, ...]
    mode: str  # "all_run", "map_1_only", "before_stage", "before_time", "first_n"
    before_stage: int | None = None
    before_seconds: float | None = None
    max_copies: int | None = None
```

```python
@dataclass(frozen=True)
class TrackedItemEvent:
    rule_id: str
    item_name: str
    gained_count: int
    game_time_seconds: float | None
    stage_index: int
    map_seed: int | None
    captured_at: float
```

```python
@dataclass(frozen=True)
class OverlayState:
    status: str  # "waiting", "live", "stale", "no_game"
    updated_at: float
    run_id: str | None
    current_stage: int
    run_timer_label: str
    mob_kills: int | None
    player_level: int | None
    chests_per_minute: float | None
    widgets: dict[str, Any]
    tracked_items: list[dict[str, Any]]
    stage_summary: list[dict[str, str]]
```

`OverlayState` should be converted to JSON-friendly plain dicts before it is
given to `overlay_server.py`.

### Live Tracker Responsibilities

`LiveRunTracker` should:

- Accept `LiveRunSnapshot` every time live stats refresh succeeds.
- Keep a bounded list of snapshots for the current run.
- Reset when a true new run is detected.
- Compute current stage index.
- Compute stage summary rows.
- Compute tracked item counters from item deltas.
- Expose a JSON-friendly `OverlayState`.
- Continue working while recording is off.

Suggested constructor:

```python
class LiveRunTracker:
    def __init__(
        self,
        *,
        tracked_item_rules: Iterable[TrackedItemRule] = (),
        max_snapshots: int = 3600,
        stale_after_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        ...
```

`max_snapshots=3600` is enough for one hour at one snapshot per second. If live
refresh is more frequent, either raise the cap or coalesce tracker captures to
one accepted snapshot every `0.5-1.0s`.

### Feeding The Tracker

In `gui_player_stats.py`, change `refresh_live_player_stats_now()` so it builds
one `LiveRunSnapshot` after `chests_per_minute` and `banishes` are resolved.

Recommended order:

1. `_read_live_player_stats_data()` reads raw live data.
2. `refresh_live_player_stats_now()` calculates `chests_per_minute`.
3. Build `LiveRunSnapshot`.
4. Feed `self.live_run_tracker.update(snapshot)`.
5. Feed `self.overlay_state` from tracker output.
6. If recorder should capture, write to `VodRecorder`.
7. Render the visible PySide UI.

Important:

- Feed the live tracker before the recording branch returns.
- Today, the recording capture branch returns early after `display_player_stats_snapshot()`.
- If the tracker is fed after that branch, overlay state will silently stop
  updating while recording is active.

Current code problem to fix:

- Non-recording path currently calls:

```python
stage_summary_rows=None
```

- After tracker implementation, use:

```python
stage_summary_rows=self.live_run_tracker.stage_summary_rows()
```

or pass the already computed rows from `OverlayState`.

### Run Identity And Reset Detection

Use conservative run identity for MVP:

- Primary active-run identity:
  - non-zero `map_seed`
  - non-zero `stage_ptr`
  - `game_time_seconds` present
- New run signal:
  - `game_time_seconds` decreases by more than
    `PLAYER_STATS_RUN_TIMER_RESET_TOLERANCE_SECONDS`, or
  - `map_seed` changes while run time also resets/near-resets, or
  - previous tracker state had no active run and current snapshot becomes
    active.

Do not reset only because `map_seed` changes.

Reason:

- Existing recording notes say map seed can change on stage transitions.
- Stage transitions must not split or reset tracker history.

When active-run confidence is missing:

- If no valid snapshot has been seen yet, overlay status should be `waiting`.
- If a valid snapshot was seen recently but the latest read failed, status
  should be `stale`.
- If process/game is unavailable, status should become `no_game` after a short
  grace period.

Known caveat:

- The project still has a separate open task for a reliable menu /
  non-gameplay signal.
- Until that is solved, the overlay tracker should use the same conservative
  run-lifecycle assumptions as recording and avoid destructive resets on weak
  signals.

### Stage Index And Stage Summary

Best implementation:

- Extract the stage-summary logic from `PlayerStatsMixin.build_stage_summary()`
  into a pure helper module, for example `run_summary.py`.
- Make both GUI recordings and live tracker call the same helper.

Why:

- The current implementation is useful and already handles important edge cases.
- Keeping it inside a GUI mixin makes it awkward for the overlay tracker to use
  without importing UI code.

Suggested extraction:

- Move these class/static methods out of `gui_player_stats.py` if practical:
  - `build_stage_summary`
  - `_resolve_next_stage_index`
  - `_is_stage_transition_boundary_snapshot`
  - `_looks_like_stage_four_transition`
  - item-count helpers needed by summary
  - format helpers needed for stage rows
- Keep backward-compatible wrappers on `PlayerStatsMixin` if tests expect those
  methods to exist.

Minimum acceptable MVP:

- Let `LiveRunTracker` use simple objects with the same attributes as
  `VodSnapshot` and call `PlayerStatsMixin.build_stage_summary()` through the
  app for the first pass.
- This is acceptable only as a temporary bridge. The cleaner follow-up is
  extracting pure summary logic.

Stage summary output for overlay:

```json
[
  {"stage": "1", "time": "03:22", "kills": "1,420", "items": "R:2 E:1"},
  {"stage": "2", "time": "--", "kills": "--", "items": "--"}
]
```

Overlay templates should not need to know how stage logic works.

### Tracked Items

Tracked items are the most valuable overlay-specific feature. Implement them as
rules over item gain events, not as a scan of the final inventory.

Why:

- `Anvils total` at the end of a successful run is not very interesting.
- `Anvils on map 1` is interesting because it describes early luck and build
  acceleration.
- To know whether an item was early, the tracker must remember when the item
  was gained.

Item parsing:

- Reuse or extract the existing item count logic from `PlayerStatsMixin`.
- Current item strings look like display names with optional stack suffixes,
  for example:
  - `Anvil x1`
  - `Anvil x3`
- Normalize to:
  - base display name: `Anvil`
  - count: `3`
- Matching should be case-insensitive and should ignore common apostrophe/name
  normalization differences where the project already has such helpers.

Event generation:

1. Compare previous snapshot item counts with current snapshot item counts.
2. For every positive delta, create a `TrackedItemEvent`.
3. Attach the resolved stage index and game time to that event.
4. Evaluate each configured rule against the event.

Rule modes:

- `all_run`
  - Count every matched item gain in the current run.
- `map_1_only`
  - Count only matched gains assigned to stage `1`.
- `before_stage`
  - Count only matched gains before the configured stage starts.
- `before_time`
  - Count only matched gains when `game_time_seconds <= before_seconds`.
- `first_n`
  - Count only the first `N` matched copies for that rule.

Recommended default tracked rules:

```json
[
  {
    "id": "anvils_map_1",
    "label": "Anvils Map 1",
    "item_names": ["Anvil"],
    "mode": "map_1_only"
  },
  {
    "id": "anvils_total",
    "label": "Anvils",
    "item_names": ["Anvil"],
    "mode": "all_run"
  }
]
```

Important `Anvils on map 1` behavior:

- Count item gains, not final inventory.
- If the player has `Anvil x3`, do not assume all three were map 1 unless the
  tracker observed those gains during stage 1.
- If the tracker starts late and sees `Anvil x2` on the first snapshot, mark
  those as `unknown_starting_inventory` unless run time is very early.
- Recommended MVP rule for first snapshot:
  - If first valid snapshot has `game_time_seconds <= 10.0` and current stage is
    `1`, accept initial item counts as stage 1 gains.
  - Otherwise, do not count initial inventory toward `map_1_only`; expose it as
    `unknown` or ignore it for early counters.

Stage-transition ambiguity:

- If an item delta appears on the first snapshot after a stage transition, the
  safest default is to assign it to the new stage.
- This may undercount a very late stage 1 pickup if the refresh interval missed
  the exact gain.
- For overlay, this is acceptable because refresh should be frequent and the
  rule is easier to explain.

### Overlay Widgets

MVP widgets:

- `run_timer`
  - Display current in-game run timer.
- `level`
  - Display current player level.
- `kills`
  - Display current mob kill count.
- `current_stage`
  - Display current stage index.
- `stage_summary`
  - Display compact table of stage time, kills, and item gains.
- `weapons`
  - Display current weapons with level and compact upgraded stat summary.
- `items`
  - Display current items with max visible count and sort mode.
- `tracked_items`
  - Display configured counters such as `Anvils Map 1`.

Later widgets:

- `damage_sources`
- `tomes`
- `banishes`
- `recent_gains`
- `pace_vs_target`
- `build_tags`

Widget config should be data-driven:

```json
{
  "id": "stage_summary",
  "enabled": true,
  "mode": "compact",
  "order": 40,
  "max_rows": 4
}
```

The overlay page should render only enabled widgets sorted by `order`.

### Config Additions

Add a top-level `OVERLAY` object or equivalent config fields in `config.json`.

Recommended shape:

```json
{
  "OVERLAY": {
    "enabled": false,
    "host": "127.0.0.1",
    "port": 17845,
    "template": "compact",
    "poll_ms": 500,
    "widgets": [
      {"id": "run_timer", "enabled": true, "mode": "compact", "order": 10},
      {"id": "level", "enabled": true, "mode": "compact", "order": 20},
      {"id": "kills", "enabled": true, "mode": "compact", "order": 30},
      {"id": "stage_summary", "enabled": true, "mode": "compact", "order": 40},
      {"id": "tracked_items", "enabled": true, "mode": "compact", "order": 50}
    ],
    "tracked_items": [
      {
        "id": "anvils_map_1",
        "label": "Anvils Map 1",
        "item_names": ["Anvil"],
        "mode": "map_1_only"
      }
    ],
    "style": {
      "scale": 1.0,
      "accent_color": "#F6C453",
      "background_opacity": 0.35
    }
  }
}
```

`config.py` should:

- Provide a default overlay config.
- Merge missing keys when loading old configs.
- Validate port as an integer in a safe local range.
- Force default host to `127.0.0.1`.
- Save user edits through the same config persistence pattern as other
  settings.

### Local HTTP Server

Use stdlib first:

- `ThreadingHTTPServer`
- custom `BaseHTTPRequestHandler`
- one background thread
- lock-protected state provider

Routes:

- `/overlay`
  - Serves default overlay HTML.
- `/overlay/compact`
  - Serves compact template. Can be same file with query/template setting.
- `/api/overlay-state`
  - Serves latest JSON state.
- `/assets/...`
  - Serves local CSS/JS from `media/overlay/`.

Server safety:

- Bind to `127.0.0.1` by default.
- Do not bind to `0.0.0.0` in MVP.
- Return `Cache-Control: no-store` for JSON.
- Return a small error JSON if state is unavailable.
- Stop server on app shutdown.

Threading rule:

- The HTTP request handler must never call Qt widgets directly.
- It should read from a thread-safe state provider only.
- Store the latest overlay state as a plain dict protected by `threading.Lock`.

Suggested `OverlayStateStore`:

```python
class OverlayStateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {"status": "waiting"}

    def set_state(self, state: dict[str, Any]) -> None:
        with self._lock:
            self._state = dict(state)

    def get_state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)
```

### Overlay HTML Template

MVP can be plain static files:

- `index.html`
- `overlay.css`
- `overlay.js`

Behavior:

- Fetch `/api/overlay-state` every `poll_ms`.
- Render enabled widgets.
- Keep layout stable when fields are unavailable.
- Show placeholder values such as `--`, not error stacks.
- Avoid animation-heavy rendering; OBS browser sources should stay cheap.

Recommended visual style:

- Transparent page background.
- Individual compact overlay panels with configurable opacity.
- High contrast text.
- No reliance on system fonts only; pick a readable bundled/web-safe fallback.
- Avoid huge UI; default should fit in a small stream corner.

OBS notes:

- Suggested browser source size:
  - `800x600` for full overlay
  - `520x220` for compact overlay
- Enable transparent background support by leaving body transparent.

### Overlay Tab UX

Add a new `Overlay` tab.

MVP controls:

- `Enable overlay server` checkbox.
- Read-only OBS URL field:
  - `http://127.0.0.1:17845/overlay`
- `Start/Stop` button if not auto-starting with checkbox.
- Template selector:
  - `Compact`
  - `Full`
- Widget checkboxes:
  - run timer
  - level
  - kills
  - current stage
  - stage summary
  - weapons
  - items
  - tracked items
- Tracked item list:
  - label
  - item name(s)
  - rule mode
  - optional threshold field
- Small live status label:
  - `Overlay running`
  - `Overlay stopped`
  - `Port unavailable`
  - `Waiting for live stats`

Do not build a heavy visual editor first. The most important first version is:

- choose metrics
- configure tracked items
- copy OBS URL
- see whether the server is running

### Implementation Steps

Phase 1: pure data and tracker

1. Add `live_run_tracker.py`.
2. Add `LiveRunSnapshot`, `TrackedItemRule`, `TrackedItemEvent`, and
   `LiveRunTracker`.
3. Add unit tests for:
   - reset on run timer reset
   - no reset on seed-only stage transition
   - item delta counting
   - `Anvils Map 1`
   - first snapshot late-start behavior

Phase 2: wire tracker into live stats

1. Instantiate tracker in `MegabonkApp.__init__()`.
2. Build a normalized snapshot in `refresh_live_player_stats_now()`.
3. Feed tracker on every successful live stats refresh.
4. Replace non-recording `stage_summary_rows=None` with tracker-derived rows.
5. Verify Live Stats can show stage summary without recording.

Phase 3: overlay state

1. Add `overlay_state.py` or equivalent serializer.
2. Convert tracker output into JSON-friendly state.
3. Add tests for JSON shape and missing-data behavior.

Phase 4: local server

1. Add `overlay_server.py`.
2. Serve `/api/overlay-state`.
3. Serve static overlay HTML/CSS/JS.
4. Add app startup/shutdown lifecycle.
5. Confirm server stops cleanly when app closes.

Phase 5: UI builder

1. Add `gui_overlay.py`.
2. Add `OverlayMixin` to `MegabonkApp`.
3. Add the `Overlay` tab in `gui_layout.py`.
4. Add config load/save for overlay settings.
5. Add widget toggles and tracked-item rule controls.

Phase 6: polish and docs

1. Add help text to existing help docs if desired.
2. Add a short README section with OBS URL instructions.
3. Add screenshots or a sample overlay state if useful.

### Tests To Add

New test file suggestions:

- `tests/test_live_run_tracker.py`
- `tests/test_overlay_state.py`
- `tests/test_overlay_server.py`

Important tracker tests:

- `test_tracker_counts_anvil_map_one_only_before_stage_transition`
- `test_tracker_does_not_count_late_anvil_as_map_one`
- `test_tracker_counts_stack_delta_as_multiple_items`
- `test_tracker_ignores_late_first_snapshot_for_map_one_counter`
- `test_tracker_accepts_early_first_snapshot_for_map_one_counter`
- `test_tracker_does_not_reset_on_seed_change_when_run_time_continues`
- `test_tracker_resets_when_run_time_resets`
- `test_tracker_marks_state_stale_after_missing_updates`

Important server tests:

- `/api/overlay-state` returns valid JSON.
- JSON response uses `Cache-Control: no-store`.
- unknown route returns `404`.
- server binds to loopback host from config.

Important GUI-ish behavior to manually verify:

- Overlay state updates while recording is off.
- Overlay state updates while recording is on.
- Recording still works and writes snapshots.
- Stage summary in Live Stats does not disappear when recording is off.
- Closing the app stops the local server thread.

### Edge Cases

- Game not running:
  - overlay JSON should return `status: "no_game"` or `waiting`.
  - overlay page should show placeholders.

- Stats read succeeds but items fail:
  - raw stats widgets should continue updating.
  - tracked item counters should not reset.
  - mark item-dependent widgets as unavailable/stale.

- Items appear before tracker starts:
  - count as early only if first snapshot is clearly early in stage 1.
  - otherwise do not claim `map 1` credit.

- Stage transition with seed change:
  - do not reset tracker if run timer continues.

- User changes tracked item config mid-run:
  - simplest MVP behavior: rebuild counters from stored current-run snapshots.
  - if that is too much for first pass, reset only tracked counters and show
    current-run counters from that moment onward.
  - Preferred behavior is rebuilding from history because it feels less
    surprising.

- Port already in use:
  - show `Port unavailable` in the Overlay tab.
  - do not crash app startup.

- OBS keeps old cached JS:
  - serve static files with conservative cache headers during development, or
    add a simple `?v=<app-version>` to asset URLs.

### MVP Acceptance Criteria

The feature is MVP-complete when:

- The app has an `Overlay` tab.
- The user can enable a loopback overlay server.
- `http://127.0.0.1:<port>/overlay` renders in a browser/OBS browser source.
- `/api/overlay-state` returns live JSON.
- Overlay state updates without `.jsonl` recording enabled.
- Live Stats can show stage summary without recording enabled.
- At least one tracked-item metric works, preferably `Anvils Map 1`.
- Recording still works exactly as before.
- Tests cover tracker reset behavior and tracked item counting.

### Recommended First PR Scope

Keep the first implementation PR narrow:

- Add live tracker.
- Feed it from live stats refresh.
- Make non-recording `Stage Summary` work.
- Add tracked item counting tests for `Anvils Map 1`.

Then make a second PR for:

- HTTP server.
- HTML overlay.
- `Overlay` tab UI.

This reduces risk because the hardest part is not the browser page. The hardest
part is getting live in-memory run analytics correct without recording.
