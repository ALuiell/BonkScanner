# 🔨 Megabonk Reroll (BonkScanner)

**Megabonk Reroll** is an advanced, Python-based modular macro script designed to automatically reroll maps in the game using Optical Character Recognition (OCR). The script analyzes the screen in real-time, reads the stats, and autonomously decides whether to keep the map or keep rolling based on a fully customizable Data-Driven template system.

## 🚀 How It Works
1. The script captures a specific area of the screen (supports **2K** and **Full HD** resolutions dynamically).
2. Using machine vision (`Tesseract OCR`), the program converts pixels into text and extracts game stats (Shady Guy, Microwaves, Boss Curses, etc.).
3. The text goes through a **Fuzzy Matching** algorithm to correct any OCR typos (e.g., reading "maais" instead of "Moais").
4. The extracted data is compared against your active templates in `config.json`.
5. If the stats don't meet the criteria, the script automatically presses the `R` key to reroll.
6. If a map is "almost perfect" (Near PERFECT+), the script pauses and does a **Double-Check (Recheck)** to ensure it doesn't accidentally skip a god-tier map due to a 1-frame OCR glitch.
7. Once the desired map appears, the script presses `Esc` and stops, securing the perfect map for the player.

## ⚙️ Core Features
- **Data-Driven Architecture:** All hotkeys, delays, and templates are saved in `config.json`. You don't need to edit the code to change settings.
- **Interactive CLI (CRUD):** Create your own custom templates or delete old ones directly from the console menu. The menu updates in real-time.
- **Fuzzy OCR Parsing:** Built-in alias dictionaries and `difflib` algorithms fix common Tesseract misreads instantly.
- **High-Speed Screen Capture:** Uses the `mss` library to take instant screenshots without performance loss.
- **Advanced Image Processing:** The script dynamically upscales (3x LANCZOS), boosts contrast, inverts colors, and binarizes the image using `Pillow`.
- **Cyrillic Path Protection:** Uses Windows API short paths (`GetShortPathNameW`) to guarantee Tesseract works even if the game is installed in a folder with Russian characters.
- **Sanity Filter:** Automatically ignores impossible stat values (like 15+ Boss Curses) to prevent false positives.

## 📁 Project Structure (Modular)
* `main.py` — The entry point and controller of the application. Run this file to start.
* `config.py` — Handles dynamic path resolution, loads `config.json`, and manages the Tesseract OCR engine connection.
* `config.json` — The auto-generated settings file containing your hotkeys, timings, and custom templates.
* `ui.py` — Manages the interactive console menu (Create, Delete, Select templates).
* `scanner.py` — Handles screen capture (`mss`), image preprocessing (`Pillow`), and raw text extraction (`pytesseract`).
* `logic.py` — The brain of the script. Handles Fuzzy Matching, Regex stat extraction, and Template validation.
* `Tesseract-OCR/` — A portable version of the Tesseract engine required for text recognition (must be located in the same directory as the script).

## 🛠 Requirements & Dependencies
The project is written in Python. To run from source, the following libraries are required:
```bash
pip install mss pytesseract keyboard colorama pillow
```
*Note: To intercept and simulate keyboard presses (`keyboard` module), the script must be run with Administrator privileges.*

## 🕹 Использование
1. Убедитесь, что папка `Tesseract-OCR` находится в одной директории со скриптом `main.py` (или скомпилированным `.exe`).
2. Запустите `main.py`. 
3. В интерактивном консольном меню выберите нужные шаблоны поиска (введите их номера через пробел) или создайте свой собственный (нажмите `N`).
4. Откройте игру, перейдите в меню реролла карты.
5. Нажмите горячую клавишу (по умолчанию `F6`) для запуска сканера.
6. Нажмите `Home` в любой момент, чтобы приостановить сканирование и вернуться в главное меню настроек.

---

*Разработано для экономии времени геймеров, автоматизации рутины и сохранения нервных клеток при поиске идеальной карты.*