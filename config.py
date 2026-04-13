import os
import sys
import json
import pytesseract
import ctypes
from ctypes import wintypes
from colorama import Fore, Style
import colorama

colorama.init(autoreset=True)

def get_short_path_name(long_name):
    """
    Gets the Windows 8.3 short path name (ASCII only).
    This completely bypasses the 'utf-8 codec can't decode byte' error 
    caused by Cyrillic characters in the user's folder path.
    """
    try:
        _GetShortPathNameW = ctypes.windll.kernel32.GetShortPathNameW
        _GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        _GetShortPathNameW.restype = wintypes.DWORD

        output_buf_size = _GetShortPathNameW(long_name, None, 0)
        if output_buf_size == 0:
            return long_name
        output_buf = ctypes.create_unicode_buffer(output_buf_size)
        _GetShortPathNameW(long_name, output_buf, output_buf_size)
        return output_buf.value
    except Exception:
        return long_name

# ==========================================
# CONSTANTS & SETTINGS
# ==========================================
# Region format: {"left": X, "top": Y, "width": W, "height": H}
# Adjust these slightly if OCR is cutting off text
REGIONS = {
    "2K": {"left": 2075, "top": 900, "width": 465, "height": 375},
    "FHD": {"left": 1628, "top": 680, "width": 1908 - 1628, "height": 949 - 680}
}

# Dynamic path resolution
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

DEFAULT_TEMPLATES = [
    {"id": 1, "name": "LIGHT", "color": "WHITE", "desc": "S+M: 7, Micro: 2, Boss: 2+", "sm_total": 7, "micro": 2, "boss": 2},
    {"id": 2, "name": "MERCHANT", "color": "CYAN", "desc": "S+M: 10+, Micro: 1, Boss: 2+", "sm_total": 10, "micro": 1, "boss": 2},
    {"id": 3, "name": "GOOD", "color": "GREEN", "desc": "S+M: 8, Micro: 2, Boss: 1+", "sm_total": 8, "micro": 2, "boss": 1},
    {"id": 4, "name": "PERFECT", "color": "YELLOW", "desc": "S+M: 8+, Micro: 2, Boss: 2+", "sm_total": 8, "micro": 2, "boss": 2},
    {"id": 5, "name": "PERFECT+", "color": "LIGHTRED_EX", "desc": "S+M: 9+, Micro: 2, Boss: 3+", "sm_total": 9, "micro": 2, "boss": 3},
    {"id": 6, "name": "BOSS RUSH", "color": "RED", "desc": "S+M: 5+, Micro: 1+, Boss: 5+", "sm_total": 5, "micro": 1, "boss": 5},
    {"id": 7, "name": "BOSS RUSH+", "color": "MAGENTA", "desc": "Boss: 7+", "boss": 7}
]

# ==========================================
# LOAD JSON CONFIG
# ==========================================
config_path = os.path.join(application_path, "config.json")

def load_config():
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_config(cfg_dict):
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(cfg_dict, f, indent=4)

user_config = load_config()

MAP_LOAD_DELAY = user_config.get("MAP_LOAD_DELAY", 1.3)
RESET_HOLD_DURATION = user_config.get("RESET_HOLD_DURATION", 0.4)
HOTKEY = user_config.get("HOTKEY", "f6")
MENU_HOTKEY = user_config.get("MENU_HOTKEY", "home")
RESET_HOTKEY = user_config.get("RESET_HOTKEY", "r")

# Попытка получить шаблоны из JSON. Если файл был пустой или без TEMPLATES,
# берем встроенные (DEFAULT_TEMPLATES) как резерв.
TEMPLATES = user_config.get("TEMPLATES", DEFAULT_TEMPLATES)
if not TEMPLATES:
    TEMPLATES = DEFAULT_TEMPLATES

# Update user_config object so that mutations to it are saved properly
user_config["MAP_LOAD_DELAY"] = MAP_LOAD_DELAY
user_config["RESET_HOLD_DURATION"] = RESET_HOLD_DURATION
user_config["HOTKEY"] = HOTKEY
user_config["MENU_HOTKEY"] = MENU_HOTKEY
user_config["RESET_HOTKEY"] = RESET_HOTKEY
user_config["TEMPLATES"] = TEMPLATES

# Если изначально файла config.json не было (или в нем не было TEMPLATES),
# мы сразу сохраняем актуальную структуру на диск, чтобы пользователю было что редактировать.
save_config(user_config)

# ==========================================
# OCR ENGINE PATH LOGIC (FIX FOR CYRILLIC & TESSDATA)
# ==========================================
# Ищем tesseract.exe в папке Tesseract-OCR рядом с программой
TESSERACT_PATH = os.path.join(application_path, 'Tesseract-OCR', 'tesseract.exe')
TESSDATA_DIR = os.path.join(application_path, 'Tesseract-OCR', 'tessdata')

if not os.path.exists(TESSERACT_PATH):
    print(f"{Fore.RED}[ERROR] OCR engine not found!{Style.RESET_ALL}")
    print(f"Make sure the 'Tesseract-OCR' folder is located in the same directory as the program.")
    print(f"Expected path: {TESSERACT_PATH}")
    input("Press Enter to exit...")
    sys.exit(1)

# Преобразуем пути в короткий формат Windows 8.3 (убирает все русские буквы и пробелы из пути)
# Это решает проблему "'utf-8' codec can't decode byte 0xcd" при вызове subprocess в pytesseract.
SHORT_TESSERACT_PATH = get_short_path_name(TESSERACT_PATH)
SHORT_TESSDATA_DIR = get_short_path_name(TESSDATA_DIR)

# Явно указываем системной переменной TESSDATA_PREFIX путь к папке tessdata без русских символов.
# Это решает проблему "Failed loading language 'eng'" и игнорирует захардкоженные пути Linux-компилятора.
os.environ["TESSDATA_PREFIX"] = SHORT_TESSDATA_DIR

pytesseract.pytesseract.tesseract_cmd = SHORT_TESSERACT_PATH
print(f"{Fore.CYAN}OCR engine initialized successfully.{Style.RESET_ALL}")
