# Megabonk Reroll (BonkScanner)

**Megabonk Reroll** is a Python-based reroll macro that reads map stats directly from the game's process memory. It evaluates the current map in real time and decides whether to keep it or reroll using a customizable data-driven template system.

## Quick Start on Windows
1. Install **Python 3.12 x64**.
2. Open the project folder.
3. Run `start.bat`.
4. Start the app manually with `.\.venv\Scripts\python.exe main.py`.

`start.bat` is the main entry point for regular use. It will:
- create `.venv` automatically if it does not exist;
- install all dependencies from `requirements.txt`;
- stop after the environment is ready, without starting `main.py`.

## Portable Native Build

`BonkHook` is built through a project-local toolchain and no longer expects a
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
- `.tools\` will be larger now because it also stores NuGet packages and dotnet CLI caches.

If bootstrap fails, inspect the `.NET SDK` or `MSVC bootstrap` step output
instead of running bare `dotnet publish`.

Important: on Windows, NativeAOT does not automatically trust a toolchain that
only exists in `PATH`. The portable scripts prepare the MSVC/Windows SDK
environment and explicitly tell NativeAOT to use it. Running bare
`dotnet publish native\BonkHook -c Release -r win-x64` from a normal shell is
not the supported workflow and may use machine/user NuGet caches instead of the
repo-local `.tools` cache layout.

## How It Works
1. The script attaches to the configured game process using `pymem`.
2. It reads interactable counters directly from memory through `game_data.py` and converts them into the runtime stat dictionary used by the template logic.
3. The data is compared against your active templates in `config.json`.
4. If the stats do not meet the criteria, the script automatically presses the `R` key to reroll.

## Core Features
- **Data-Driven Architecture:** All hotkeys, delays, and templates are saved in `config.json`. You do not need to edit the code to change settings.
- **Interactive CLI (CRUD):** Create your own custom templates or delete old ones directly from the console menu. The menu updates in real time.
- **Direct Memory Reads:** Stats are read straight from the game's in-memory interactables dictionary instead of being inferred from screen text.
- **Confirmation Reread:** A matching map is verified with one additional memory read before the macro stops.
- **Portable Runtime Logic:** No screen region calibration, OCR engine, or image preprocessing pipeline is required.

## Project Structure
- `main.py` - Entry point and controller of the application.
- `config.py` - Loads `config.json` and exposes runtime settings such as hotkeys, delays, templates, and `PROCESS_NAME`.
- `config.json` - Auto-generated settings file containing hotkeys, timings, and custom templates.
- `ui.py` - Interactive console menu for creating, deleting, and selecting templates.
- `game_data.py` - Reads interactable counters from memory and returns typed stat values.
- `memory.py` - Wraps `pymem` and low-level memory access helpers.
- `runtime_stats.py` - Adapts typed memory stats into the runtime dictionary used by the template matcher.
- `logic.py` - Template evaluation logic used to decide whether to keep or reroll a map.
- `requirements.txt` - Runtime dependencies used by the project.
- `start.bat` - Windows launcher that prepares `.venv` and installs dependencies.

## Dependencies
Runtime dependencies are pinned in `requirements.txt`:
- `pymem==1.14.0`
- `keyboard==0.13.5`
- `colorama==0.4.6`

Note: to intercept and simulate keyboard presses through the `keyboard` module, run the script with Administrator privileges.

## Manual Developer Setup
If you want to work with the environment manually instead of using `start.bat`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

The `.venv/` directory is local to your machine, should not be committed to git, and is already ignored in `.gitignore`.

To build the NativeAOT hook locally, prefer the portable entrypoint:

```bat
tools\build_native_hook.bat
```

This wrapper prepares the Windows-native linker environment and passes the
NativeAOT switch required to use it.

## Usage
1. Set the game process name in `config.json` through the `PROCESS_NAME` field.
2. Start the game and wait until the target scene is fully loaded.
3. Run `start.bat` to prepare `.venv` and install dependencies.
4. Launch the scanner with `.\.venv\Scripts\python.exe main.py` or run `python main.py` inside the activated virtual environment.
5. In the interactive console menu, choose the templates you want to search for or create new ones.
6. Press `F6` to start the scanner.
7. Press `Home` at any time to stop the loop and return to the menu.

Developed to save time, automate repetition, and reduce frustration while hunting for the ideal map.
