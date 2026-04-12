# 🔨 Megabonk Reroll (BonkScanner)

**Megabonk Reroll** is a Python-based macro script designed to automatically reroll maps in the game using Optical Character Recognition (OCR). The script analyzes the screen in real-time, reads the stats, and autonomously decides whether to keep the map or keep rolling.

## 🚀 How It Works
1. The script captures a specific area of the screen (supports 2K and Full HD resolutions).
2. Using machine vision (`Tesseract OCR`), the program converts pixels into text and extracts game stats (Shady Guy, Microwaves, Boss Curses, etc.).
3. The extracted data is compared against user-selected presets (LIGHT, PERFECT, BOSS RUSH, etc.).
4. If the stats don't meet the criteria, the script automatically presses the `R` key to reroll.
5. Once the desired map appears, the script presses `Esc` and stops, securing the perfect map for the player.

## ⚙️ Core Features
- **High-Speed Screen Capture:** Uses the `mss` library to take instant screenshots without performance loss.
- **Advanced Image Processing:** The script dynamically boosts contrast, inverts colors, and binarizes the image using `Pillow`, allowing `Tesseract OCR` to flawlessly read even tiny white text on a dark UI background.
- **Preset System:** A flexible template system lets you search for "average" (GOOD/LIGHT) or "perfect" (PERFECT+) rolls.
- **Hotkeys:** Full macro control without needing to minimize the game (Start/Stop, return to menu).

## 📁 Project Structure
* `bs_main.py` / `bs_public.py` — The main executable macro scripts containing the processing and OCR logic.
* `Tesseract-OCR/` — A portable version of the Tesseract engine required for text recognition (must be located in the same directory as the script).

## 🛠 Requirements & Dependencies
The project is written in Python. To run from source, the following libraries are required:
```bash
pip install mss pytesseract keyboard colorama pillow
```
*Примечание: для перехвата нажатий клавиатуры (модуль `keyboard`) скрипт необходимо запускать с правами администратора.*

## 🕹 Использование
1. Убедитесь, что папка `Tesseract-OCR` находится в одной директории с запускаемым файлом.
2. Запустите скрипт. В консоли выберите нужные шаблоны поиска.
3. Откройте игру, перейдите в меню реролла карты.
4. Нажмите горячую клавишу (по умолчанию `F6`) для запуска сканера.

---

*Разработано для экономии времени геймеров и автоматизации рутины.*