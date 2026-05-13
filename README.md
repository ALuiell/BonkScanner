# Megabonk Reroll (BonkScanner)

**BonkScanner** is a Windows desktop tool for automatic map rerolling in Megabonk.
It reads map stats directly from the game process, evaluates each map in real
time, and restarts the run until a selected template or score target is found.

## Quick Start on Windows
1. Install **Python 3.12 x64**.
2. Open the project folder.
3. Run `start.bat`.
4. Launch the app with `.\.venv\Scripts\python.exe main.py`.

`start.bat` is the regular setup entry point. It will:
- create `.venv` if it does not exist;
- install all runtime dependencies from `requirements.txt`;
- stop after the environment is ready.

## What The App Includes
- `Templates` mode for strict rule-based map filtering.
- `Scores` mode for flexible score/tier-based evaluation.
- colored template list with an in-app template manager;
- session stats and persistent total reroll tracking;
- live player stats recording with snapshot timeline playback;
- optional native hook restart mode;
- configurable hotkeys and timing settings in the main settings dialog.

## How It Works
1. The app attaches to the configured game process with `pymem`.
2. It reads interactable counters directly from memory through `game_data.py`.
3. The values are converted into runtime stats and evaluated by the selected mode.
4. If the map does not meet the conditions, the app restarts the run.
5. Before evaluating a new map, the app waits for a stable ready-state snapshot so dirty reads are less likely.

## Main Features
- **Templates Mode:** Use strict requirements such as `S+M`, `Microwaves`, `Boss Curses`, `Shady Guy`, and `Moais`.
- **Scores Mode:** Rate maps through weighted stats and thresholds like `Light`, `Good`, `Perfect`, and `Perfect+`.
- **Template Manager:** Open `Edit` in the `Templates` tab to browse all templates, expand one, edit values inline, and save.
- **Live Stats Recording:** Record player stats snapshots at a configurable interval and review them in the built-in timeline UI.
- **Native Hook Restart:** Optional alternate restart path that can continue working more reliably while alt-tabbed on some systems.
- **Data-Driven Settings:** Hotkeys, delays, templates, score settings, and recording settings are saved in `config.json`.

## Settings
The main `Settings` dialog includes:
- `Scan Hotkey`
- `Reset Hotkey`
- `Record Hotkey`
- `Min Reroll Delay (s)`
- `Reset Hold Duration (s)`
- `Snapshot Interval (s)`
- `Use native hook restart`

Notes:
- `Reset Hold Duration` matters for standard keyboard restart mode.
- `Snapshot Interval` controls how often live player stats recordings save a snapshot.
- `Record Hotkey` toggles player stats recording without needing to click the UI button.

## Portable Native Build

`BonkHook` is built through a project-local toolchain and does not require a
globally installed .NET SDK or Visual Studio Build Tools.

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
- `main.py` - entry point for the desktop app.
- `gui.py` - main PySide6 interface and application flow.
- `config.py` - loads `config.json` and exposes runtime settings.
- `logic.py` - template and score evaluation logic.
- `game_data.py` - reads map-ready state and interactable counters from memory.
- `memory.py` - low-level `pymem` wrappers and memory helpers.
- `runtime_stats.py` - adapts typed memory values into runtime stats.
- `vod_storage.py` - player stats recording and replay storage.
- `hook_loader.py` - native hook bootstrap, injection, restart, and cleanup logic.
- `native\BonkHook` - NativeAOT hook project.
- `requirements.txt` - Python runtime dependencies.

## Dependencies
Runtime dependencies are listed in `requirements.txt`:
- `pymem==1.14.0`
- `keyboard==0.13.5`
- `colorama==0.4.6`
- `PySide6>=6.8.0`
- `requests~=2.33.1`
- `pywin32>=306`

Note: keyboard-based restart and hotkey handling may require Administrator privileges on Windows.

## Manual Developer Setup
If you want to work manually instead of using `start.bat`:

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
1. Start the game and wait until the target scene is loaded.
2. Run `start.bat` if the environment is not ready yet.
3. Launch BonkScanner.
4. Choose `Templates` or `Scores`.
5. Configure the templates, score settings, or live stats settings you need.
6. Press `Start`, then use the scan hotkey to arm the loop.
7. When a matching map is found, the app stops and logs the result.

BonkScanner is meant to reduce repetition, speed up rerolling, and make target hunting less frustrating.
