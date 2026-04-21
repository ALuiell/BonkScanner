# Project Wiki: Megabonk Reroll (BonkScanner)

This document serves as a comprehensive guide for the Megabonk Reroll project. It describes the architecture, key components, and logic to provide context for future development and maintenance.

---

## 📌 Overview
**Megabonk Reroll** (also known as **BonkScanner**) is an automation tool (macro) for the game "Megabonk". It monitors the game's memory in real-time to detect map statistics and automatically performs rerolls until a map satisfies user-defined criteria.

### Key Goals:
- **Automation:** Automate the tedious process of rerolling maps.
- **Accuracy:** Use direct memory reading instead of OCR for 100% accuracy.
- **Flexibility:** Support both hard-coded templates and a weighted scoring system.

---

## 🛠 Tech Stack
- **Language:** Python 3.12+
- **UI Framework:** `customtkinter` (modern look for Tkinter).
- **Memory Access:** `pymem` for process attachment and memory reading.
- **Automation:** `keyboard` for simulating key presses (requires Admin rights).
- **Other Libs:** `Pillow` (icons), `pywin32` (window focus detection).

---

## 🏗 Architecture & Project Structure

### Core Files:
- **`main.py`**: The application entry point. Initializes the GUI.
- **`gui.py`**: Contains the `MegabonkApp` class. Manages the main window, log output, session statistics, and configuration dialogs.
- **`game_data.py`**: High-level memory client (`GameDataClient`). Defines offsets for the interactables dictionary in the game memory and maps them to readable stats.
- **`logic.py`**: Evaluation engine.
    - `find_matching_template`: Logic for "Templates" mode.
    - `evaluate_map_by_scores`: Logic for "Scores" mode (weighted calculations).
- **`config.py`**: Handles `config.json`. Loads settings, handles default templates, and synchronizes with the game's own configuration (reset timings).
- **`memory.py`**: Low-level wrapper around `pymem`. Provides a `ProcessMemory` class with methods to read pointers, integers, and Mono strings.
- **`runtime_stats.py`**: Bridges raw `StatValue` objects from `game_data.py` to the simple dictionary format used by `logic.py`.
- **`updater.py`**: Handles version checks against a remote source (typically GitHub).

---

## 🚀 Key Features

### 1. Evaluation Modes
- **Templates Mode:** Maps are matched against specific minimum requirements (e.g., "S+M: 7, Micro: 2").
- **Scores Mode:** A weighted system where different stats (Moais, Shady Guy, Boss Curses, Magnets) contribute points. The total is multiplied by a factor based on the number of Microwaves.
    - **Tiers:** Light, Good, Perfect, Perfect+.
    - **Scaling:** Automatically adjusts thresholds based on weights.

### 2. Direct Memory Reading
The tool reads from `GameAssembly.dll` using static offsets (e.g., `TYPE_INFO_OFFSET = 0x2FB5E68`). It traverses the game's internal `Interactables` dictionary to find counts for:
- Shady Guy
- Moais
- Microwaves
- Boss Curses
- Magnet Shrines
- And more (Pots, Chests, etc.)

### 3. Smart Rerolling
- **Confirmation Read:** When a candidate map is found, the script performs a second read after a short delay to confirm the stats haven't changed or were read mid-update.
- **Focus Detection:** Pauses automation if the game window is not in the foreground.
- **Game Config Sync:** Can read and write the game's `quick_reset_time` in its local AppData folder to ensure the macro timing matches the game settings.

---

## 📜 Development Guidelines

### Memory Offsets
If the game updates, the `TYPE_INFO_OFFSET` in `game_data.py` is the most likely value to change. This offset points to the static class metadata for the interactables system.

### Adding New Stats
1.  Add the stat to `MapStat` enum in `game_data.py`.
2.  Add the game's internal string label to `LABEL_TO_STAT`.
3.  Update `adapt_map_stats` in `runtime_stats.py`.
4.  Update `logic.py` to include the new stat in scoring or template matching.

### UI Modifications
The project uses a grid layout. Most UI changes should happen in `gui.py`. Remember to update `update_status_ui` if adding new states to the background loop.

---

## ⚠️ Constraints & Known Issues
- **Admin Rights:** Required to simulate keyboard input in most games.
- **Process Name:** Defaults to `Megabonk.exe`. Can be changed in `config.json`.
- **Game Updates:** Any major update to the game's engine or code may break memory offsets.

---

## 🗺 Roadmap / Future Ideas
- [ ] Support for multiple game versions/offsets.
- [ ] Exporting session stats to CSV for long-term analysis.
- [ ] Visual overlay on top of the game window.
