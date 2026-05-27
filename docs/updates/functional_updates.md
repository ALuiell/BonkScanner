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

## 4. Overlay Upgrade

Status: `[Open]`

Goal:

- Improve the current local OBS overlay tab and browser-source output so it is
  more compact, clearer, easier to configure, and more practical for stream
  layouts.

Requirements:

1. `Tracked Items` should become collapsible in the app UI.
   - The section should default to a compact collapsed presentation or otherwise
     behave in a clearly space-saving way.
   - When the OBS Overlay tab is shown in a narrow window, the tracked-items
     area must not collapse into an unusable squeezed layout.
   - Prioritize a small-window-friendly layout similar to the requested mockup.

2. Simplify the overlay server status row to remove duplicated wording.
   - Replace the current pattern similar to `OBS Overlay server OBS Overlay running | live/stop`.
   - Use a layout in this spirit:
     - `OBS Overlay server | status: live/stop`
     - `Start/Stop` button
   - The final wording can vary slightly, but the row must be shorter, cleaner,
     and free from duplicated status labels.

3. Change overlay items from a vertical list to a horizontal row-based
   presentation where appropriate.
   - This applies to the visible overlay output for item widgets.
   - The result should stay readable in stream usage and avoid unnecessary
     height growth.

4. Add a new collapsible widget named `Stats`.
   - The user must be able to choose which stats are included in this widget.
   - The selected stats should appear inside the widget in a compact list.
   - The presentation should be lightweight and readable for stream overlays,
     using small thumbnail-style entries or similarly compact stat rows.

5. Support direct widget-specific overlay URLs so each widget can be added to
   OBS as a separate browser source.
   - Today the full overlay is exposed through a single route like
     `http://127.0.0.1:17845/overlay`.
   - Add per-widget routes in the spirit of
     `http://127.0.0.1:17845/overlay/<widget_name>`.
   - Streamers should be able to place, scale, and position each widget
     independently in OBS by using those dedicated URLs.

Implementation notes:

- Preserve the current local overlay architecture unless there is a clear
  technical reason to change it.
- Reasonable improvements beyond the exact checklist are welcome if they improve
  clarity, compactness, maintainability, or stream usability.
- Keep the result lightweight and consistent with the existing app.

