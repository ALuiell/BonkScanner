# 🔨 Megabonk Reroll (BonkScanner)

**Megabonk Reroll** is a Python-based reroll macro that reads map stats directly from the game's process memory. It evaluates the current map in real time and decides whether to keep it or reroll using a customizable data-driven template system.

## 🚀 How It Works
1. The script attaches to the configured game process using `pymem`.
2. It reads interactable counters directly from memory through `game_data.py` and converts them into the runtime stat dictionary used by the template logic.
3. The data is compared against your active templates in `config.json`.
4. If the stats do not meet the criteria, the script automatically presses the `R` key to reroll.
5. If the stats match a selected template, the script performs one confirmation reread and then presses `Esc` to stop on the target map.

## ⚙️ Core Features
- **Data-Driven Architecture:** All hotkeys, delays, and templates are saved in `config.json`. You don't need to edit the code to change settings.
- **Interactive CLI (CRUD):** Create your own custom templates or delete old ones directly from the console menu. The menu updates in real-time.
- **Direct Memory Reads:** Stats are read straight from the game's in-memory interactables dictionary instead of being inferred from screen text.
- **Confirmation Reread:** A matching map is verified with one additional memory read before the macro stops.
- **Portable Runtime Logic:** No screen region calibration, OCR engine, or image preprocessing pipeline is required.

## 📁 Project Structure (Modular)
* `main.py` — The entry point and controller of the application. Run this file to start.
* `config.py` — Loads `config.json` and exposes runtime settings such as hotkeys, delays, templates, and `PROCESS_NAME`.
* `config.json` — The auto-generated settings file containing your hotkeys, timings, and custom templates.
* `ui.py` — Manages the interactive console menu (Create, Delete, Select templates).
* `game_data.py` — Reads interactable counters from the game's memory and returns typed stat values.
* `memory.py` — Wraps `pymem` and low-level memory access helpers.
* `runtime_stats.py` — Adapts typed memory stats into the runtime dictionary used by the template matcher.
* `logic.py` — The template evaluation logic used to decide whether to keep or reroll a map.

## 🛠 Requirements & Dependencies
The project is written in Python. To run from source, the following libraries are required:
```bash
pip install pymem keyboard colorama
```
*Note: To intercept and simulate keyboard presses (`keyboard` module), the script must be run with Administrator privileges.*

## 🕹 Использование
1. Укажите имя процесса игры в `config.json` через поле `PROCESS_NAME`.
2. Запустите игру и дождитесь полной загрузки сцены, где доступны нужные interactables.
3. Запустите `main.py`.
4. В интерактивном консольном меню выберите нужные шаблоны поиска или создайте собственный.
5. Нажмите горячую клавишу `F6` для запуска сканера.
6. Нажмите `Home` в любой момент, чтобы остановить цикл и вернуться в меню.

---

*Разработано для экономии времени геймеров, автоматизации рутины и сохранения нервных клеток при поиске идеальной карты.*
