# BonkScanner

**BonkScanner** is a Windows desktop tool for Megabonk reroll automation, live run inspection, saved-run review, OBS overlays, and Twitch chat integration.
It observes the running game locally, evaluates each reset in real time, and can keep rerolling until a selected template or score tier is found.

## Download
For most users, download the latest packaged Windows build from
[GitHub Releases](https://github.com/ALuiell/BonkScanner/releases/latest).

You can also support the project with activity and follow updates on
[Patreon](https://www.patreon.com/cw/ALuiel).

BonkScanner uses functionality such as global hotkeys, local process memory reads,
and a packaged `.exe` build. Because of that, some antivirus tools may warn about
the executable. If this happens, download only from the official releases page or
Patreon above. You can review the source code and the `build_exe.bat` script used
to package the executable if you want to verify what the app does and how the
release build is created.

Use the Python setup below only if you want to run from source or develop the
project.

## Run From Source on Windows
1. Install **Python 3.12 x64**.
2. Open the project folder.
3. Run `start.bat` once to create `.venv` and install dependencies.
4. Run `run.bat` to launch the app.

You can also launch manually after setup:

```bat
.\.venv\Scripts\python.exe main.py
```

Source runs do not build `BonkHook.dll` automatically. If you want to use
`Use native hook restart` or `Use hook for game toggles` while running from
source, build the hook once:

```bat
build_tools\bootstrap_tools.bat
build_tools\build_native_hook.bat
```

`start.bat` is the normal setup entry point. It will:
- create `.venv` if it does not exist;
- upgrade pip inside the virtual environment;
- install runtime dependencies from `requirements.txt`;
- stop after the environment is ready.

## Safety Notes
BonkScanner is a local desktop tool. It does not modify Megabonk files on disk,
install game mods, or send gameplay data anywhere by default.

Some parts of the project use technical names, so here is what they mean:

- `Memory reads`: BonkScanner reads live values from the running Megabonk process
  to detect map state, player stats, items, weapons, tomes, banishes, damage
  sources, and run time. This is used for display, recording, scoring, overlays,
  and Twitch commands.
- `Standard restart`: the default restart mode sends the configured reset hotkey,
  similar to pressing it yourself.
- `BonkHook`: an optional native helper used for the alternate restart path and
  map-ready signal. Its goal is to request a run restart and detect when a new
  map snapshot is ready. You can use BonkScanner without enabling native hook
  restart.
  When enabled, native hook restart loads `BonkHook.dll` into the running game
  process so the app can request restarts and receive map-ready signals.
  This can make restarts a little faster and lets the restart path keep working
  while the game is not focused, such as when you are alt-tabbed.
  The hook is limited to specific supported actions: restart requests,
  map-ready signaling, and supported game-setting toggles without opening the
  in-game settings menu. **It does not touch anything else beyond those listed
  actions.**
  If both `Use native hook restart` and `Use hook for game toggles`
  are disabled, BonkScanner does not load `BonkHook.dll`.
- `OBS Overlay`: runs only on `127.0.0.1`, which means it is available from the
  same PC for OBS/browser sources, not from the public internet.
- `Twitch Bot`: only connects after you authorize it manually. Disconnecting
  removes the stored token and attempts to revoke it with Twitch.

## What The App Does
- rerolls maps automatically until the current map matches selected filters;
- supports two evaluation modes: `Templates` and `Scores`;
- applies active template and score-tier changes while the scan loop is running;
- shows session reroll stats and persistent total reroll tracking;
- reads live player stats, passive items, weapons, tomes, banishes, damage sources, level, kills, and run time from the running game;
- records live stat snapshots into saved `.jsonl` recordings with timeline playback;
- tracks stage summaries for live runs and recordings, including time, kills, and item gains per stage;
- compares saved runs side by side with synced in-game time and configurable diff sections;
- serves a local OBS browser overlay with draggable/resizable widgets and widget-specific URLs;
- runs an optional Twitch chat bot with live stat commands and stage announcements;
- can use standard keyboard reset or the optional native hook restart path;
- can toggle several in-game settings through dedicated hotkeys;
- stores app settings, templates, score rules, overlay settings, Twitch bot settings, and update preferences in `config.json`.

## Main UI Areas

### Left Side
- `Templates`: strict rule-based filtering with selectable active templates.
- `Scores`: weighted score evaluation with selectable target tiers and a dedicated scores settings dialog.

### Right Side
- `Logs`: scanner activity, warnings, wait states, and result messages.
- `Session Stats`: session time, reroll count, RPM, best and worst maps, tracked item counters, and averages per target.
- `Live Stats`: current run stats, items, weapons, tomes, Chaos Tome data, banishes, damage sources, stage summary, segment compare, and recording controls.
- `Recordings`: saved recording viewer with timeline, Chaos Tome data, rename, delete, cleanup, and in-run compare tools.
- `Compare Runs`: side-by-side comparison of two saved recordings with synced in-game time, Chaos Tome diffs, and a central difference panel.
- `OBS Overlay`: local browser-source overlay controls for streaming layouts.
- `Twitch Bot`: built-in Twitch IRC bot controls and command settings.

## How Scanning Works
1. BonkScanner connects to the running game locally.
2. It reads the map-ready state, interactable counters, seeds, and other runtime values needed for scanning.
3. Runtime values are evaluated by the active `Templates` or `Scores` mode.
4. If the map does not match, the app restarts the run.
5. Before accepting a snapshot, the scanner waits for a stable ready-state so transient map-load reads are less likely.

## Evaluation Modes

### Templates Mode
Use strict requirements such as:
- `S+M`
- `Microwaves`
- `Boss Curses`
- `Shady Guy`
- `Moais`

The built-in template manager lets you:
- create custom templates;
- edit template values inline;
- enable only the templates you want the scanner to stop on;
- delete custom templates.

### Scores Mode
Use weighted scoring instead of hard requirements.

Current score configuration supports:
- configurable stat weights;
- microwave multipliers;
- auto-calculated or manual score thresholds;
- active target tiers: `Light`, `Good`, `Perfect`, `Perfect+`.

The active left-side tab decides which evaluation mode is currently used.

## Live Stats And Recordings

### Session Stats
The `Session Stats` tab shows:
- session time, reroll count, and rerolls per minute;
- best and worst map found during the current session;
- average rerolls per target;
- configurable `Tracked Items` counters for live item gains.

By default, `Tracked Items` tracks `Anvils Map 1`. Use the small settings button
on that card to search for an item, choose `Map 1 only` when needed, and add or
remove tracked rules. `Map 1 only` counts gains observed during stage 1 only.

### Live Stats
The `Live Stats` tab shows:
- grouped player stat cards;
- passive items with rarity highlighting, sorting, and total item count;
- average chests per minute;
- in-game timer;
- mob kill count with thousands separators;
- player level;
- `Stage Summary` with per-stage time, kills, and gained item counts;
- `Segment Compare` against an earlier snapshot in the same run;
- `Banishes`;
- current weapons with level and upgraded stats;
- current tomes with level and active effects;
- Chaos Tome tracking when available;
- damage sources when available.

`Live Stats` does not require recording. Recording only saves snapshots for later
playback and comparison.

Passive item reads use the normal passive inventory path first and fall back to
the main `PlayerInventory.ItemInventory` path when needed. This helps with runs
where items were added by mods or external tools.

If some live sections temporarily show unavailable data, that is not always an
error. During loading screens, some game memory pointers may not be ready yet.

### Recording
The built-in recorder can:
- start and stop from the UI or a hotkey;
- auto-start when a live run is detected, if enabled;
- save snapshots at a configurable interval;
- include run seed metadata when available;
- automatically stop if the run seed disappears and stays unavailable;
- automatically continue into a new file when a truly new run is detected;
- keep one recording together across normal stage transitions even if the map seed changes.

`Snapshot Interval (s)` in `Settings` controls how often `Live Stats` recording
saves a snapshot. Shorter intervals make the recording timeline, segment compare,
and saved-run review more precise, but create more snapshots. Longer intervals
keep recordings lighter, but changes between snapshots are captured less exactly.

### Saved Recordings
Recordings are stored in `stats_recordings\` as `.jsonl` files and can be:
- reviewed with a timeline slider;
- inspected for stats, items, weapons, tomes, Chaos Tome data, stage summary, damage sources, and banishes;
- compared against an earlier snapshot from the same recording;
- renamed in-app, including the actual file name on disk;
- deleted individually;
- batch-cleaned by minimum snapshot count.

Legacy recordings from `vods\` are still read when present.

## Compare Runs
`Compare Runs` loads two saved recordings side by side as `Run A` and `Run B`.
This is useful for checking how two runs diverged at the same in-game time.

It supports:
- guided first selection when no runs are selected yet;
- swapping selected runs;
- synced snapshot comparison by nearest in-game time;
- configurable stat selection;
- optional diff sections for stats, stage summary, items, weapons, tomes, and Chaos Tome data;
- item detail comparison for gained, broken, and lost items.

## OBS Overlay
`OBS Overlay` runs a local browser-source overlay server for stream layouts.

Default overlay URL:

```text
http://127.0.0.1:17845/overlay
```

The server binds to `127.0.0.1`, so it is intended for the same PC only.
Recording is not required; the overlay uses live stats reads.

Overlay features:
- transparent browser page for OBS;
- selectable widgets for `Stage Summary`, `Tracked Items`, `Stats`, and `Banishes`;
- tracked item rules, including map-1-only tracking;
- widget-specific URLs such as `/overlay/stats`, `/overlay/banishes`, `/overlay/tracked_items`, and `/overlay/stage_summary`;
- visual layout editor at `/overlay?edit=true`;
- draggable widget positions;
- per-widget scaling;
- widget resizing;
- configurable canvas width and height for matching OBS source dimensions;
- game preview background in edit mode only.

If OBS keeps showing an old layout after an update, refresh the browser source
cache from the OBS source properties.

## Twitch Bot
The `Twitch Bot` tab runs a built-in Twitch IRC chat bot for the configured channel.

Basic setup:
1. Open the `Twitch Bot` tab.
2. Click `Connect to Twitch`.
3. Authorize through the browser.
4. Configure target channel, access tier, cooldowns, enabled commands, and stage announcements.
5. Click `Start Bot`.

By default, `Target Channel` uses the authorized Twitch account. If you authorize
a separate bot account, set `Target Channel` to the streamer channel where the
bot should join and respond.

Available chat commands:
- `!stats` / `!bonkstats`: current selected live stats.
- `!bans` / `!banishes`: banished items.
- `!disabled`: lists highlighted items globally disabled in lobby.
- `!items` / `!tracked`: collected items, sorted by rarity and compressed when needed.
- `!weapons`: current weapons and upgraded stats.
- `!tomes`: current tomes and values.
- `!chaos` / `!chaostome`: tracked Chaos Tome level and stat roll totals.
- `!stages`: stage summary.
- `!powerups`: active powerup duration info.
- `!chests` / `!chest`: displays per-stage and total chest progress, paid openings, actual and expected Key procs, inherently free chests, and the current Key proc chance. The same data is arranged as six readable rows in the sixth Stats card and saved in recordings.
- `!scanner`: general info about the BonkScanner app and download link.
- `!presets`: active templates or score tiers and weights.
- `!bonkhelp` / `!bonkcmds` / `!bonkcommands` / `!bhelp`: list of all active Twitch bot commands.

Command settings support:
- access tiers: `Everyone`, `Mods & VIPs`, `Subs & Mods`;
- global and per-command cooldowns;
- per-command enable toggles;
- selected stats for `!stats`;
- customizable response templates;
- automatic stage transition announcements.

OAuth tokens are stored through the app's credential helper when available.
Disconnecting removes the stored token and attempts to revoke it with Twitch.

## Settings
The main `Settings` dialog currently includes:
- `Scan Hotkey`
- `Reset Hotkey`
- `Record Hotkey`
- `Auto-start recording`
- `Toggle Chest Skip Hotkey`
- `Toggle Auto Level-Up Hotkey`
- `Toggle Particles Opacity Hotkey`
- `Allowed Held Game Keys`
- `Min Reroll Delay (s)`
- `Reset Hold Duration (s)`
- `Snapshot Interval (s)`
- `Use native hook restart`
- `Use hook for game toggles`
- `Check for Updates`

Notes:
- `Reset Hold Duration` is used for standard keyboard reset mode;
- the app also syncs the game's `quick_reset_time` value when that setting is changed;
- `Use hook for game toggles` controls whether `Toggle Chest Skip`,
  `Toggle Auto Level-Up`, and `Toggle Particles Opacity` may use the hook path
  to update supported values inside the game's own config;
- `Allowed Held Game Keys` lets hotkeys fire while listed gameplay keys are
  held, but this relaxed matching is used only while the game window is active;
- native hook mode shows an extra confirmation when enabled and may work better while alt-tabbed on some systems because restarts do not depend on the game window being focused;
- hook-based game-setting hotkeys also show a confirmation when enabled;
- global hotkeys and keyboard-driven restart may require Administrator privileges on Windows.

## Auto-Update Behavior
- source runs (`python main.py`) do not auto-update themselves;
- packaged builds can check for updates from the settings dialog;
- skipped update versions are remembered in `config.json`;
- the updater checks the latest GitHub release for `ALuiell/BonkScanner` and downloads the packaged `.exe` asset when a newer version is available.

## Portable Native Build

`BonkHook` is the optional native restart helper. It is built through a project-local toolchain and does not require a globally installed .NET SDK or Visual Studio Build Tools in the normal path.

Use these entry points on Windows x64:

```bat
build_tools\bootstrap_tools.bat
build_tools\build_native_hook.bat
build_exe.bat
```

What happens on the first run:
- `build_tools\bootstrap_tools.bat` downloads a pinned .NET SDK into `.tools\dotnet`;
- it downloads portable MSVC + Windows SDK into `.tools\msvc`;
- it keeps NuGet packages/cache and dotnet CLI state inside `.tools\nuget` and `.tools\dotnet-home`;
- `build_tools\build_native_hook.bat` publishes `native\BonkHook` with those local tools and forces NativeAOT to use the prepared linker environment;
- `build_exe.bat` installs PyInstaller into `.venv` if needed;
- `build_exe.bat` publishes the hook, then packages `BonkScanner.exe` into `dist\`;
- the packaged exe includes required media, help files, overlay assets, and the published `BonkHook.dll`;
- PyInstaller is invoked with `--noupx` to avoid UPX compression.

Requirements and constraints:
- Windows 10/11 x64;
- Python 3.12 x64 for the Python app environment;
- internet access on the first bootstrap;
- Windows PowerShell available for the helper scripts;
- downloaded `.tools\` contents are local artifacts and are not committed;
- `.tools\` will be larger because it also stores NuGet packages and dotnet CLI caches.

Fallback: if portable MSVC bootstrap fails, install Visual Studio Build Tools
with the Desktop development with C++ workload, then rerun the build scripts.

## Dependencies
Runtime dependencies are listed in `requirements.txt`:
- `pymem==1.14.0`
- `keyboard==0.13.5`
- `colorama==0.4.6`
- `PySide6>=6.8.0`
- `requests~=2.33.1`
- `pywin32>=306`

`build_exe.bat` also installs `pyinstaller` into `.venv` when it is missing.

## Manual Developer Setup
If you want to run manually instead of using `start.bat`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python main.py
```

To build only the native hook locally, prefer:

```bat
build_tools\build_native_hook.bat
```

To build the packaged executable:

```bat
build_exe.bat
```

## Project Structure
- `main.py` - desktop app entry point.
- `gui_app.py` - PySide6 application class and top-level app wiring.
- `gui_layout.py` - main UI layout, tabs, and shared UI sections.
- `gui_scanner.py` - scanner loop, hotkeys, lifecycle, and shutdown flow.
- `gui_run_control.py` - run restart mode UI and provider coordination.
- `gui_player_stats.py` - live stats, recordings, compare runs, and snapshot UI.
- `gui_overlay.py` - OBS overlay controls and overlay state refresh.
- `gui_twitch.py` - Twitch authentication and bot UI orchestration.
- `gui_dialogs.py` - settings, help, score, template, and Twitch command dialogs.
- `gui_styles.py` - Qt stylesheet and item rarity styling.
- `config.py` - app config, game config integration, templates, scores, overlay, Twitch, and compare settings.
- `logic.py` - template and score evaluation logic.
- `game_data.py` - map-ready state, counters, seed-related runtime reads, and scan data.
- `memory.py` - low-level `pymem` wrappers and memory helpers.
- `player_stats.py` - live player stats, passive items, weapons, tomes, banishes, damage sources, and chest-rate calculations.
- `live_run_tracker.py` - thread-safe live run snapshot tracking for overlay and Twitch.
- `overlay_state.py` - overlay state serialization.
- `overlay_server.py` - local HTTP server for OBS/browser overlay pages.
- `twitch_auth.py` - local Twitch OAuth flow.
- `twitch_bot.py` - Twitch IRC bot worker and command handlers.
- `twitch_credentials.py` - Twitch token storage helpers.
- `vod_storage.py` - saved recording format, metadata cache, load, rename, and cleanup helpers.
- `run_summary.py` - recording and compare summary helpers.
- `run_control.py` - keyboard and hook-based restart providers.
- `hook_loader.py` - native hook loading, restart requests, and cleanup logic.
- `updater.py` - packaged-build update checks and update application flow.
- `media\overlay` - browser overlay HTML, CSS, JS, and preview asset.
- `docs\help` - in-app help text in English, Ukrainian, and Russian.
- `native\BonkHook` - NativeAOT hook project.

## Basic Usage
1. Start Megabonk and wait until the target scene is loaded.
2. Run `start.bat` if the environment is not ready yet.
3. Launch BonkScanner with `run.bat`.
4. Choose `Templates` or `Scores`.
5. Configure your filters, score tiers, and optional recording/overlay/Twitch settings.
6. Press `Start`.
7. Press the scan hotkey in-game to arm or pause the scanning loop.
8. When a matching map is found, the app stops and logs the result.

BonkScanner is meant to reduce repetition, speed up rerolling, and make target hunting less frustrating while also giving streamers and run reviewers better live data.
