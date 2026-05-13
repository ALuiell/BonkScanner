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

