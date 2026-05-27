# Functional Updates

Date: 2026-05-24

This file tracks open and partially completed functional/runtime work that does
not fit cleanly into UI-only or performance-only buckets.

Status legend:

- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## 1. Find A Reliable Runtime Signal For True Menu / Non-Gameplay State

Status: `[Open]`

Current branch notes:

- Existing recording auto-stop logic can reliably detect full process exit, but
  not `Exit to Menu` from an active run.
- Current known run signals are not sufficient because they can remain frozen in
  memory after leaving the run.
- This needs a focused reverse pass before `Live Stats` recording auto-stop can
  be considered robust.

Reverse task:

- Find a reliable runtime signal that distinguishes active run gameplay from:
  - main menu
  - post-run / returned-to-menu state
- The signal must remain valid even if old run pointers, seed, stats, or items
  still remain in memory as a frozen snapshot.

Verified manual observations on build `2026-05-14`:

- Cold menu:
  - `map_seed = 0`
  - `current_map_ptr = 0`
  - `current_stage_ptr = 0`
  - `has_loaded_map = False`
- Active run:
  - `map_seed` is non-zero
  - `current_map_ptr` and `current_stage_ptr` are non-zero
  - `has_loaded_map = True`
- After `Exit to Menu` from a run:
  - `map_seed` stays stuck at the previous run value
  - `current_map_ptr` and `current_stage_ptr` stay stuck
  - `has_loaded_map = True`
  - `is_resetting = False`
  - player stats and items can also stay stuck as a frozen snapshot of the last
    run

What this means:

- Current known signals are not enough to reliably detect that the run has
  ended and the player has returned to menu.
- `ProcessNotFound` only covers full game exit, not `Exit to Menu`.

Primary goal:

- Find a stable memory or runtime-logic signal that reliably indicates one of:
  - the player is currently in main menu
  - an active run is no longer in progress
  - the game is currently not in gameplay state
  - post-run / menu state differs from active in-run state even when old run
    objects still remain in memory

Preferred candidate types:

- global game-state enum
- menu / open-screen state
- scene/state-machine current state
- pause/menu controller state, if it distinguishes:
  - paused during a run
  - main menu
- run/session active flag
- map/session ownership flag that resets on real run end even if old objects are
  still retained in memory

Weak signals that should not be used as the final solution without strong
confirmation:

- `map_seed` alone
- `current_map_ptr` alone
- `current_stage_ptr` alone
- `has_loaded_map` alone
- `stats stopped changing for a while`
- `items are empty`
- a generic `pause` flag that does not distinguish paused gameplay from main
  menu

Required validation states:

- cold menu after fresh game launch
- active run gameplay
- paused run
- exited from run back to menu

Extra validation states if possible:

- during death / end-run transition
- after full process exit

Expected reverse report output:

- the found entity / field / method / offset / path
- what that state actually means
- how it behaves in:
  - menu
  - active run
  - paused run
  - post-run menu
- how reliable the signal is
- whether it is safe to use for:
  - recording auto-stop on menu
  - recording keep-alive during paused run
  - recording auto-split only on true new run

Ranking guidance if multiple candidates are found:

- best primary signal
- possible fallback signal
- unsafe / weak signals that should not be used

Implementation target after reverse:

- `process gone => stop`
- `true menu / non-gameplay state => stop after grace`
- `new run state => split recording`
- `paused active run => do not stop`

Why this matters:

- This is the missing piece for making `Live Stats` recording lifecycle
  trustworthy.
- Without a true gameplay/menu discriminator, auto-stop can silently fail and
  keep recording stale snapshots from a dead run context.

## 2. Compare Runs By In-Game Time

Status: `[Partial]`

Current branch notes:

- Phase 1 is done: run timer reverse path is documented in `docs/reverse/reports/2026-05-18-current-run-time.md`.
- Phase 2 is done: recordings now store `game_time_seconds` in snapshots.
- Phase 3 is mostly done: the existing recordings viewer shows in-game time and remains backward-compatible with older recordings.
- The dedicated `Compare Runs` tab and time-synced side-by-side compare workflow are still not implemented.

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

## 3. Add Run Damage Breakdown To Live Stats, Recordings, And Compare Runs

Status: `[Open]`

Current reverse result:

- The game already tracks current-run damage split by source in
  `RunStats.damageSources`.
- This is a better source than trying to reconstruct damage from weapon stats,
  enemy health deltas, or UI text.
- The damage data appears to be the same conceptual data used by the in-game
  game-over damage breakdown UI.

Goal:

- Add a first-class run field that shows how much damage each source has dealt
  during the current run.
- Use the same structure in:
  - `Live Stats`
  - saved `Recordings`
  - `Compare Runs`
- Preserve enough detail that future UI can show both compact totals and more
  advanced compare views without requiring another reverse pass.

Why this helps:

- It makes build analysis much more useful than only showing inventory,
  weapons, tomes, or total kills.
- It becomes much easier to answer:
  - which weapon is actually carrying the run
  - whether an item proc is overperforming or underperforming
  - when a source starts contributing meaningful damage
  - how two runs differ in real output, not just build shape
- It gives a natural post-hoc analysis feature for routing, balancing, and
  debugging scanner correctness.

## Confirmed Runtime Source

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

- `RunStats.damageSources` is a current-run dictionary keyed by damage source
  name string.
- Each value is a `DamageSource` object that stores:
  - `damageSource`
  - `addedAtTime`
  - `damage`
- Combat hits use `DamageContainer.damageSource`, and the run stat system adds
  damage into the matching `RunStats.damageSources` bucket.

This strongly suggests the feature should be implemented as a direct runtime
read of `RunStats.damageSources`, not as a derived estimate.

## Important Dump References

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
- the game-over screen is already a good behavioral reference for how this data
  should look when sorted and displayed

## Rooted Memory Shape

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
- Like `RunStats.stats["kills"]`, this should be treated as a dictionary scan
  problem, not a fixed final pointer.
- The exact `Dictionary.Entry<string, DamageSource>` value layout should be
  confirmed live before implementation is locked in.

## Expected Read Strategy

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
- `level` is not directly stored in `DamageSource`; if later desired, it will
  need a separate mapping step for weapons/items that expose current level.
- `source_kind` is optional future metadata such as `weapon`, `item`,
  `passive`, `proc`, or `unknown`.

## Proposed Feature Scope

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

## Suggested UI Shape

For `Live Stats`:

- Add a `Damage Sources` section or tab.
- Show a sorted list by descending total damage.
- Initial compact rows can include:
  - source name
  - total damage
  - share of total damage

For `Recordings`:

- Show the same structure for the selected snapshot.
- If compare-start snapshot is pinned, optionally show segment delta for damage
  sources between two snapshots in the same run.

For `Compare Runs`:

- Side-by-side source tables for `Run A` and `Run B`
- One central diff panel or inline delta columns
- Useful fields:
  - source present on both sides
  - total damage difference
  - percent share difference

## Recording Schema Recommendation

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

## Validation Checklist

Live validation before implementation is considered safe:

1. Confirm the rooted `RunStats.damageSources` pointer is stable across:
   - fresh run start
   - stage transition
   - death / end-run flow
2. Confirm dictionary entries update live as damage is dealt.
3. Confirm at least one weapon source and one item/proc source appear in the
   dictionary during a real run.
4. Confirm the top sources and totals broadly match the in-game game-over
   damage breakdown UI.
5. Confirm values reset correctly on a true new run.
6. Confirm stale previous-run data does not leak into a new recording after run
   split.

Nice-to-have validation:

- confirm whether `addedAtTime` reflects first-seen run time for that source
- confirm whether non-damaging equipped items stay absent
- confirm how summons, chain effects, thorns, bleed, poison, or reflection
  sources are named
- confirm whether source names are stable internal identifiers across builds

## Risks And Caveats

- The rooted class path is good, but dictionary entry layout still needs live
  confirmation for `Dictionary<string, DamageSource>`.
- The source keys may be internal ids rather than polished user-facing names.
- Some sources may be ambiguous without extra mapping:
  - proc effects
  - debuffs
  - item-triggered secondary damage
- `DamageSource` does not directly store source level, so `Lv.` style detail is
  not free for this feature.
- If source names are localized only through game methods, pure memory reads
  may initially show raw keys until we add our own mapping layer or hook-based
  helper.

## Implementation Handoff Notes

When this feature is picked up later, start here:

1. Reconfirm `RunStats.damageSources` root on the current game build.
2. Document the live `Dictionary.Entry<string, DamageSource>` layout in a
   dedicated reverse report.
3. Implement a Python normalizer in the same style as existing live
   item/weapon/tome snapshot readers.
4. Store the normalized list into recordings as an optional field.
5. Add UI in `Live Stats` first, then `Recordings`, then `Compare Runs`.

This is a high-value feature because it converts the scanner from a build-state
viewer into an actual run-output analysis tool.

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
