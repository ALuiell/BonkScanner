# Megabonk Reroll (BonkScanner)

**BonkScanner** is a Windows desktop tool for Megabonk reroll automation and live run inspection.
It reads map data directly from the game process, evaluates each reset in real time, and can keep rerolling until a selected template or score tier is found.

## Quick Start on Windows
1. Install **Python 3.12 x64**.
2. Open the project folder.
3. Run `start.bat`.
4. Launch the app with `.\.venv\Scripts\python.exe main.py`.

`start.bat` is the normal setup entry point. It will:
- create `.venv` if it does not exist;
- install runtime dependencies from `requirements.txt`;
- stop after the environment is ready.

## What The App Does
- rerolls maps automatically until the current map matches selected filters;
- supports two evaluation modes: `Templates` and `Scores`;
- shows session reroll stats and persistent total reroll tracking;
- reads live player stats, passive items, weapon upgrades, and run time directly from memory;
- records live stat snapshots into saved recordings with timeline playback;
- auto-splits recordings when the detected run seed changes;
- can use standard keyboard reset or the optional native hook restart path;
- can toggle several in-game settings through dedicated hotkeys;
- stores app settings, templates, score rules, and update preferences in `config.json`.

## Main UI Areas

### Left Side
- `Templates`: strict rule-based filtering with selectable active templates.
- `Scores`: weighted score evaluation with selectable target tiers and a dedicated scores settings dialog.

### Right Side
- `Logs`: scanner activity, warnings, and result messages.
- `Session Stats`: current session counters and average rerolls per target.
- `Live Stats`: live player stats, items, chest rate, in-game time, and weapon upgrade details.
- `Recordings`: saved live-stats recordings with rename, delete, cleanup, and timeline review tools.

## How Scanning Works
1. BonkScanner attaches to the configured game process with `pymem`.
2. It reads map-ready state and interactable counters from memory.
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

## Live Stats And Recordings

### Live Stats
The `Live Stats` tab shows:
- grouped player stat cards;
- passive items list;
- average chests per minute;
- in-game timer;
- weapon list with current level and upgraded stats.

### Recording
The built-in recorder can:
- start and stop from the UI or a hotkey;
- save snapshots at a configurable interval;
- include run seed metadata when available;
- automatically stop if the run seed disappears;
- automatically split into a new file when a new run seed is detected.

### Saved Recordings
Recordings are stored in `stats_recordings\` as `.jsonl` files and can be:
- reviewed with a timeline slider;
- renamed in-app;
- deleted individually;
- batch-cleaned by minimum snapshot count.

Legacy recordings from `vods\` are still read when present.

## Settings
The main `Settings` dialog currently includes:
- `Scan Hotkey`
- `Reset Hotkey`
- `Record Hotkey`
- `Toggle Chest Skip Hotkey`
- `Toggle Auto Level-Up Hotkey`
- `Toggle Particles Opacity Hotkey`
- `Min Reroll Delay (s)`
- `Reset Hold Duration (s)`
- `Snapshot Interval (s)`
- `Use native hook restart`
- `Check for Updates`

Notes:
- `Reset Hold Duration` is used for standard keyboard reset mode.
- the app also syncs the game's `quick_reset_time` value when that setting is changed;
- toggle hotkeys update supported values inside the game's own config when available;
- native hook mode shows an extra confirmation when enabled and may work better while alt-tabbed on some systems.

## Auto-Update Behavior
- source runs (`python main.py`) do not auto-update themselves;
- packaged builds can check for updates from the settings dialog;
- skipped update versions are remembered in `config.json`.

## Portable Native Build

`BonkHook` is built through a project-local toolchain and does not require a globally installed .NET SDK or Visual Studio Build Tools.

Use these entry points on Windows x64:

```bat
tools\bootstrap_tools.bat
tools\build_native_hook.bat
build_exe.bat
```

What happens on the first run:
- `tools\bootstrap_tools.bat` downloads a pinned .NET SDK into `.tools\dotnet`;
- it downloads portable MSVC + Windows SDK into `.tools\msvc`;
- it keeps NuGet packages/cache and dotnet CLI state inside `.tools\nuget` and `.tools\dotnet-home`;
- `tools\build_native_hook.bat` publishes `native\BonkHook` with those local tools and forces NativeAOT to use the prepared linker environment;
- `build_exe.bat` reuses the published `BonkHook.dll` when packaging the app.

Requirements and constraints:
- Windows 10/11 x64;
- internet access on the first bootstrap;
- Windows PowerShell available for the helper scripts;
- downloaded `.tools\` contents are local artifacts and are not committed;
- `.tools\` will be larger because it also stores NuGet packages and dotnet CLI caches.

## Project Structure
- `main.py` - desktop app entry point.
- `gui.py` - main PySide6 UI, scanner flow, live stats UI, and recordings UI.
- `config.py` - app config, game config integration, templates, and score settings.
- `logic.py` - template and score evaluation logic.
- `game_data.py` - map-ready state, counters, and seed-related runtime reads.
- `memory.py` - low-level `pymem` wrappers and memory helpers.
- `player_stats.py` - live player stats, passive items, weapons, and chest-rate calculations.
- `vod_storage.py` - saved recordings format, metadata cache, load, rename, and cleanup helpers.
- `run_control.py` - keyboard and hook-based restart providers.
- `hook_loader.py` - native hook bootstrap, injection, restart, and cleanup logic.
- `updater.py` - packaged-build update checks and update application flow.
- `native\BonkHook` - NativeAOT hook project.

## Dependencies
Runtime dependencies are listed in `requirements.txt`:
- `pymem==1.14.0`
- `keyboard==0.13.5`
- `colorama==0.4.6`
- `PySide6>=6.8.0`
- `requests~=2.33.1`
- `pywin32>=306`

Notes:
- global hotkeys and keyboard-driven restart may require Administrator privileges on Windows;
- native hook mode may also benefit from elevated launch depending on the system and game process state.

## Manual Developer Setup
If you want to run manually instead of using `start.bat`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

To build the native hook locally, prefer:

```bat
tools\build_native_hook.bat
```

## Basic Usage
1. Start Megabonk and wait until the target scene is loaded.
2. Run `start.bat` if the environment is not ready yet.
3. Launch BonkScanner.
4. Choose `Templates` or `Scores`.
5. Configure your filters, score tiers, and optional recording settings.
6. Press `Start`.
7. Press the scan hotkey in-game to arm or pause the scanning loop.
8. When a matching map is found, the app stops and logs the result.

BonkScanner is meant to reduce repetition, speed up rerolling, and make target hunting less frustrating.
