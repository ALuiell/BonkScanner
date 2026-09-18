<div align="center">

<img src="src/media/bonkscanner_icon2.png" alt="BonkScanner" width="112">

<h1>BonkScanner</h1>

<p><strong>Automated Megabonk rerolls, live run tracking, recordings, overlays, and Twitch integration.</strong></p>

<p>
  BonkScanner is a Windows desktop companion that observes the running game locally,<br>
  evaluates each reset in real time, and can keep rerolling until it finds the map<br>
  template or score tier you selected.
</p>

<p>
  <a href="https://github.com/ALuiell/BonkScanner/releases/latest"><strong>Download for Windows</strong></a>
  ·
  <a href="#support-and-community">Support</a>
  ·
  <a href="#quick-start">Quick Start</a>
  ·
  <a href="#features">Features</a>
  ·
  <a href="#linux">Linux</a>
  ·
  <a href="#development">Development</a>
  ·
  <a href="https://discord.gg/dYkcrMCJWM">Discord</a>
</p>

<p>
  <a href="https://github.com/ALuiell/BonkScanner/releases/latest"><img alt="Latest release" src="https://img.shields.io/github/v/release/ALuiell/BonkScanner?display_name=tag&sort=semver"></a>
  <img alt="Windows 10 and 11" src="https://img.shields.io/badge/Windows-10%20%7C%2011-0078D4?logo=windows&logoColor=white">
  <img alt="Python 3.12" src="https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white">
  <a href="LICENSE"><img alt="License GPLv3" src="https://img.shields.io/badge/license-GPLv3-blue"></a>
</p>

</div>

> **Windows 10/11 x64 · Local processing · No game-file modifications**

## Download

For most users, the recommended option is the latest packaged Windows build:

### [Download BonkScanner.exe](https://github.com/ALuiell/BonkScanner/releases/latest)

Download releases only from the official GitHub Releases page or the official
Patreon linked below. Use the source setup only if you want to develop the project
or inspect it locally.

<details>
<summary><strong>Why Windows or antivirus software may show a warning</strong></summary>

BonkScanner uses global hotkeys, local process-memory reads, and a packaged `.exe`.
Some antivirus products may treat those capabilities cautiously even when the app
was downloaded from the official source.

You can review the complete source code and the [`build_exe.bat`](build_exe.bat)
script used to package the executable. Do not download builds from unofficial
mirrors.

</details>

## Support and Community

BonkScanner is free and open source. If you would like to support its continued
development, two support options are available:

- [**Patreon — Supporter Packs and monthly support**](https://www.patreon.com/cw/ALuiel)
- [**Crypto donation**](https://aluiell.github.io/BonkScanner/)

Community links:

- [Join the Discord community](https://discord.gg/dYkcrMCJWM)
- [Report a bug or request a feature](https://github.com/ALuiell/BonkScanner/issues)
- [Browse official releases](https://github.com/ALuiell/BonkScanner/releases)

## Quick Start

1. Start Megabonk and wait until the target scene is loaded.
2. Launch `BonkScanner.exe`.
3. Choose `Templates` for strict filters or `Scores` for weighted evaluation.
4. Configure the targets and optional recording, overlay, or Twitch features.
5. Press **Start**.
6. Use the configured scan hotkey in-game to arm or pause the scanner.
7. When a matching map is found, BonkScanner stops and reports the result.

BonkScanner is designed to reduce repetitive resets while also providing useful
live information for players, streamers, and run reviewers.

## Features

| Auto-Reroll & Evaluation | Live Run Tracking |
| :--- | :--- |
| Automatically rerolls until a selected target is found. Use strict `Templates` or weighted `Scores`, and change active targets while scanning. | Tracks player stats, passive items, weapons, tomes, banishes, damage sources, stages, kills, run time, powerups, and more. |
| **Recordings & Comparison** | **Streaming & Overlays** |
| Saves timeline-based `.jsonl` recordings for later review and side-by-side run comparison. | Provides a local OBS browser overlay, transparent in-game widgets, Full Map activity markers, and Twitch chat commands. |

### Auto-Reroll and Evaluation

BonkScanner connects to the running game locally, waits for a stable map-ready
state, reads the values required for evaluation, and checks them against the
active mode.

- **Templates** use strict requirements such as S+M, Microwaves, Boss Curses,
  Shady Guy, Moais, and other supported map conditions.
- **Scores** use configurable shrine points, microwave multipliers, thresholds,
  and the `Light`, `Good`, `Perfect`, and `Perfect+` target tiers.
- Active template and score-tier changes apply while the scan loop is running.
- Session statistics show rerolls, RPM, match rate, best and worst maps, tracked
  item counters, and per-target averages.
- A late-run safeguard prevents the scan hotkey from resetting Forest or Desert
  runs that have already progressed beyond Tier 1.

### Live Stats

The `Live Stats` tab provides a real-time view of the current run. Recording is
not required for live tracking.

- grouped player stat cards;
- passive items with rarity, sorting, and total count;
- current weapons, levels, upgraded stats, and supported calculated values;
- tomes, Chaos Tome data, banishes, and damage sources;
- run time, player level, kills, chest rate, and other live counters;
- stage summaries with time, kills, and item gains;
- powerups, Charge Shrine bonuses, character passives, and Dice Gamba rolls when
  available.

During loading screens, some memory pointers may not be ready yet. A temporarily
unavailable section does not necessarily indicate an error.

### Recordings and Compare Runs

The built-in recorder stores run snapshots as local `.jsonl` files. It can start
manually, from a hotkey, or automatically when a live run is detected.

- review saved runs on a timeline;
- inspect stats, items, weapons, tomes, stages, banishes, and damage sources;
- compare two runs at the nearest matching in-game time;
- compare two moments inside the same recording;
- rename, delete, and clean up recordings from the app;
- keep a run together across normal stage transitions and begin a new file when
  a genuinely new run is detected.

### OBS Overlay

The OBS module serves a transparent browser overlay from the local computer:

```text
http://127.0.0.1:17845/overlay
```

Available widgets include Stage Summary, Tracked Items, Stats, Banishes, KPS,
Luck Rarity, and Build Progression. The visual editor supports dragging, scaling,
resizing, and widget-specific browser-source URLs.

The server binds only to `127.0.0.1`, so it is not exposed to the public internet.
Recording is not required.

### In-Game Overlay

The transparent, click-through in-game overlay follows the Megabonk window and
does not require OBS or recording. Its widgets include scanner and recording
status, KPS, powerups, Luck, stats, event timers, supported item cooldowns, and
Build Progression.

`Map Activity Markers` add a separate layer anchored to the game's Full Map.
Markers can be placed with hotkeys, and supported nearby activities can be added
automatically when that option is enabled.

### Twitch Bot

The optional Twitch IRC bot connects only after browser authorization. It can
report live stats, session information, inventories, stages, builds, and other
run data directly in chat.

Command access tiers, cooldowns, enable toggles, selected stats, response
templates, and stage announcements are configurable from the app.

<details>
<summary><strong>Available Twitch commands</strong></summary>

- `!stats` / `!bonkstats` — selected live stats;
- `!session` — rerolls, match rate, map results, and tracked items;
- `!bans` / `!banishes` — banished items;
- `!disabled` — highlighted items disabled in the lobby;
- `!items` / `!tracked` — collected items;
- `!weapons`, `!tomes`, `!chaos`, `!dice`, and `!shrines` — build details;
- `!stages`, `!powerups`, `!kps`, `!build`, and `!luck` — run summaries;
- `!chests` / `!chest` — chest and Key-proc progress;
- `!scanner` — app information and the official download link;
- `!presets` / `!preset` — active templates or score targets;
- `!bonkhelp` / `!bonkcmds` — enabled command list.

</details>

## Safety and Privacy

BonkScanner is a local desktop application. By default, it does not modify
Megabonk files on disk, install game mods, or send gameplay data anywhere.

| Capability | What it means |
| :--- | :--- |
| **Memory reads** | Reads live values from the running Megabonk process for scanning, display, recording, overlays, and Twitch responses. |
| **Run restart** | Sends the configured reset hotkey, similar to pressing the key yourself. |
| **OBS server** | Listens only on `127.0.0.1`, making it available to browser sources on the same PC. |
| **Twitch authorization** | Connects only after manual authorization. Disconnecting removes the stored token and attempts to revoke it with Twitch. |
| **Local data** | Stores settings in `config.json` and recordings in `stats_recordings\`. |

Global hotkeys and keyboard-driven restarts may require Administrator privileges
on some Windows configurations.

[Report a problem](https://github.com/ALuiell/BonkScanner/issues) or
[ask for help in Discord](https://discord.gg/dYkcrMCJWM).

## Linux

The official BonkScanner release targets Windows. Linux users can try the
[unofficial community port maintained by cybWasHere](https://github.com/cybWasHere/BonkScanner).

The port is maintained independently, has not been personally tested by the
BonkScanner maintainer, and is not officially supported as part of this project.
Use its repository for installation instructions and Linux-specific issues.

Thanks to [cybWasHere](https://github.com/cybWasHere) for taking the time to
bring BonkScanner to Linux.

## Settings

The app includes settings for scanner and reset hotkeys, recording behavior,
overlay editing, reset timing, snapshot intervals, update checks, support access,
and other feature-specific options.

<details>
<summary><strong>Reset timing and configuration notes</strong></summary>

- `Reset Hotkey` and `Reset Hold Duration` control the community restart path.
- Close Megabonk before changing Reset Speed; the game reads this value on its
  next start.
- `Safety Margin` is configurable from `0.00` to `1.00` and defaults to `0.05`.
- Saving Settings verifies the scanner configuration and synchronizes the game's
  `quick_reset_time`.
- If a configuration cannot be saved or verified, Settings remains open and
  preserves the last known-good runtime values.

</details>

## Run From Source

BonkScanner requires **Python 3.12 x64** on Windows.

1. Clone or download this repository.
2. Run `start.bat` once to create `.venv` and install dependencies.
3. Run `run.bat` to launch the app.

You can also launch it manually after setup:

```bat
.\.venv\Scripts\python.exe src/main.py
```

`start.bat` creates the virtual environment, upgrades pip, and installs runtime
dependencies from [`src/requirements.txt`](src/requirements.txt).

<details>
<summary><strong>Manual PowerShell setup</strong></summary>

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r src/requirements.txt
python src/main.py
```

</details>

## Development

### Build the Windows Executable

```bat
build_exe.bat
```

The script packages the application, media, overlay files, and in-app help into
`dist\BonkScanner.exe` with PyInstaller.

### Run the Test Suite

```bat
run_tests.bat
```

Wait for the final `OK`. A partial or interrupted test run is not a pass.

<details>
<summary><strong>Project structure</strong></summary>

| Path | Responsibility |
| :--- | :--- |
| `src/main.py` | Desktop application entry point |
| `src/app/` | Application coordination, configuration, updates, and feature services |
| `src/core/` | Evaluation, tracking, summaries, and domain logic |
| `src/infra/` | Memory readers, storage, local servers, credentials, and Windows adapters |
| `src/ui/` | PySide6 layouts, tabs, dialogs, and shared widgets |
| `src/projections/` | OBS, in-game, Twitch, and presentation projections |
| `src/media/` | Icons, styles, overlay assets, and packaged help |
| `src/tests/` | Automated test suite |
| `site/crypto-support/` | Static crypto-support page |

</details>

## Updates

- Packaged builds can check for updates from Settings.
- Source runs do not update themselves.
- Skipped versions are remembered locally.
- The updater downloads newer packaged builds only from the official GitHub
  Releases page.

## License

Copyright (C) 2026 Aluiel and BonkScanner contributors.

BonkScanner's original source code and documentation in this repository are
licensed under the **GNU General Public License, version 3 only**
(`GPL-3.0-only`). You may use, study, modify, and redistribute the covered work
under the terms of the [LICENSE](LICENSE) file. Distributed modified versions
must preserve the same license and make their corresponding source available as
required by GPLv3.

The GPL does not grant permission to use the BonkScanner name or original project
logo in a way that suggests an unofficial build is maintained, endorsed, or
published by the BonkScanner project. Official hosted services, supporter keys,
and accounts are separate from the licensed client source.

Bundled dependencies and third-party names, logos, and other assets remain
subject to their respective licenses and owners' rights. See
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
