# Project Guide: Megabonk Reroll (BonkScanner)

This document provides a compact, up-to-date guide for working on the
Megabonk Reroll project. It is intended for contributors and coding agents who
need a practical map of the codebase and the project's working rules.

For subsystem-level documentation, architecture notes, and debugging details,
use the wiki under [docs/wiki](./docs/wiki/Home.md).

---

## Overview

Megabonk Reroll, also known as BonkScanner, is a desktop automation tool for
the game "Megabonk". It reads the game's memory in real time, evaluates map
quality, and automatically rerolls until a map matches user-defined criteria.

### Core goals

- Automate repetitive map rerolling.
- Prefer direct memory reads over OCR for accuracy and speed.
- Support both strict template matching and weighted score-based evaluation.
- Provide live run inspection, recording, and streamer-facing integrations.

---

## Tech Stack

- Language: `Python 3.12+`
- UI framework: `PySide6`
- Memory access: `pymem`
- Automation: `keyboard`
- Windows integration: `pywin32`
- Assets / images: `Pillow`
- Native hook: C# / .NET 8 (`BonkHook.dll`)
- Overlay server: `ThreadingHTTPServer`
- Twitch integration: IRC over sockets

---

## Code Map

### Application and UI

- `main.py`: Application entry point.
- `gui.py`: Compatibility facade for the UI layer.
- `gui_app.py`: Defines `MegabonkApp`, the main application container.
- `gui_layout.py`, `gui_scanner.py`, `gui_run_control.py`,
  `gui_player_stats.py`, `gui_templates.py`, `gui_dialogs.py`,
  `gui_shared.py`, `gui_twitch.py`, `gui_overlay.py`, `gui_styles.py`:
  Focused UI modules split by responsibility.

### Memory, evaluation, and runtime logic

- `memory.py`: Low-level process memory wrapper.
- `game_data.py`: Map and reroll-related memory reads.
- `player_stats.py`: Live player stats, items, weapons, timers, and run data.
- `runtime_stats.py`: Adapts raw map stats into logic-friendly structures.
- `logic.py`: Template matching and score evaluation.
- `live_run_tracker.py`: Tracks stage progress, item deltas, and related live
  run state.
- `run_summary.py`: Builds stage summaries and transition-derived aggregates.

### Integrations and persistence

- `config.py`: Loads and saves app settings and runtime preferences.
- `vod_storage.py`: Persists and loads `.jsonl` run recordings.
- `twitch_bot.py`: Twitch IRC integration.
- `overlay_server.py`: Local HTTP server for OBS/browser overlays.
- `hook_loader.py`: Injects and communicates with `BonkHook.dll`.
- `updater.py`: Handles packaged-app update checks and update flow.

---

## Key Features

### Evaluation modes

- Templates mode: Strict minimum requirements for selected map stats.
- Scores mode: Weighted evaluation with tiers such as `Light`, `Good`,
  `Perfect`, and `Perfect+`.

### Live inspection

- Reads map data, player stats, items, weapons, timers, and run progress
  directly from game memory.

### Recording and replay

- Stores run recordings as `.jsonl` snapshots for replay and analysis.

### Streamer tools

- Twitch chat integration for announcements and commands.
- OBS/browser overlays for stage summary, tracked items, stats, and banishes.

### Restart control

- Keyboard-based restart automation.
- Native hook restart via `BonkHook.dll` for more reliable background resets.

---

## Development Guidelines

### Memory changes

- If a game update breaks memory reads, start by reviewing offsets and pointer
  chains in `game_data.py` and `player_stats.py`.
- Do not guess memory behavior. Use the reverse-engineering notes in
  `docs/recovery/reports/` and related docs first.

### Adding a new map stat

1. Add the stat to the relevant enum or identifier set in `game_data.py`.
2. Map the game's internal label or source field to that stat.
3. Update `runtime_stats.py` so the stat reaches the evaluation layer.
4. Update `logic.py` if the stat should affect templates or scoring.
5. Update UI and docs if the stat becomes user-visible.

### UI changes

- Prefer editing the focused `gui_*` module for the feature you are touching.
- Keep `gui.py` as a compatibility facade rather than growing new logic there.
- If UI state or worker states change, make sure status and control refresh
  paths stay in sync.

### Documentation-first rule

- For mechanics, formulas, and reverse-engineered behavior, consult project
  docs before making assumptions.
- Prefer `docs/wiki/` for architecture and feature behavior.
- Prefer `docs/design/` for chosen implementation approaches, option
  comparisons, and fallback strategies for revisitable features.
- Prefer `docs/recovery/reports/` for memory paths, offsets, and validation
  notes.

---

## Constraints and Known Risks

- Admin rights may be required for keyboard automation in some setups.
- The game process name defaults to `Megabonk.exe` unless changed in config.
- Game updates can invalidate offsets, pointer chains, or hook behavior.
- Native injection paths may be affected by antivirus or OS protections.

---

## Working Rules for Agents

- Do not start editing code without explicit user approval to proceed.
- When requirements are unclear, outline the approach first and wait for a
  clear go-ahead such as "proceed", "start", or "do it".
- Before changing behavior tied to game memory or formulas, check the project
  docs instead of inferring from incomplete context.

---

## Recommended Reading

- Main wiki entry: [docs/wiki/Home.md](./docs/wiki/Home.md)
- Design notes index: [docs/design/README.md](./docs/design/README.md)
- Scanner and evaluation: [docs/wiki/Scanner_and_Evaluation.md](./docs/wiki/Scanner_and_Evaluation.md)
- Live stats and memory layout: [docs/wiki/Memory_and_Live_Stats.md](./docs/wiki/Memory_and_Live_Stats.md)
- Stage transitions: [docs/wiki/Stage_Summary_Transitions.md](./docs/wiki/Stage_Summary_Transitions.md)
- Recordings and VODs: [docs/wiki/Recordings_and_VODs.md](./docs/wiki/Recordings_and_VODs.md)
- Integrations and overlays: [docs/wiki/Integrations_and_Overlay.md](./docs/wiki/Integrations_and_Overlay.md)
- Settings and hooks: [docs/wiki/Settings_and_Hooks.md](./docs/wiki/Settings_and_Hooks.md)
- Troubleshooting: [docs/wiki/Troubleshooting_and_Diagnostics.md](./docs/wiki/Troubleshooting_and_Diagnostics.md)
- `!chests` command design: [docs/design/chests-command-detection.md](./docs/design/chests-command-detection.md)
