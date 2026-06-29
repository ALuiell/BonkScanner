# Performance Updates

Date: 2026-05-24

This file tracks open and partially completed performance-focused work.

Status legend:

- `[Partial]` some meaningful work is done, but the feature is not fully complete
- `[Open]` not implemented yet

## 1. Rework Settings Save Behavior To Reduce Micro-Stutters

Status: `[Open]`

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

## 2. Performance Update

Status: `[Partial]`

Current branch notes:

- Done:
  - passive item dictionary hard cap
  - split player stat / passive item reads
  - resolve `owner_stats` once per refresh and reuse it
  - gate idle live-stats polling by visible tab or active recording
  - immediate refresh when the user opens the live stats tab
- Still open:
  - `ProcessMemory` module base caching
  - reduced VOD flush frequency and batched/final flush behavior
  - reduced config write frequency for reroll/session counters
  - hook idle atomic micro-optimizations

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
- repeated external memory reads, and global hotkey backend behavior.


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
