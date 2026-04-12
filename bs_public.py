import time
import re
import sys
import mss
import pytesseract
import keyboard
import colorama
import ctypes
from colorama import Fore, Style
from PIL import Image, ImageEnhance, ImageOps
from difflib import get_close_matches
import os

colorama.init(autoreset=True)

if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# Ищем tesseract.exe в папке Tesseract-OCR рядом с программой
TESSERACT_PATH = os.path.join(application_path, 'Tesseract-OCR', 'tesseract.exe')

if not os.path.exists(TESSERACT_PATH):
    print(f"{Fore.RED}[ERROR] OCR engine not found!{Style.RESET_ALL}")
    print(f"Make sure the 'Tesseract-OCR' folder is located in the same directory as the program.")
    print(f"Expected path: {TESSERACT_PATH}")
    input("Press Enter to exit...")
    sys.exit(1)

pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH
print(f"{Fore.CYAN}OCR engine initialized successfully.{Style.RESET_ALL}")

# ==========================================
# USER SETTINGS (PROFILES)
# ==========================================

# Region format: {"left": X, "top": Y, "width": W, "height": H}
# Adjust these slightly if OCR is cutting off text
REGIONS = {
    "2K": {"left": 2075, "top": 900, "width": 465, "height": 375},
    "FHD": {"left": 1628, "top": 680, "width": 1908 - 1628, "height": 949 - 680}
}

MAP_LOAD_DELAY = 1.3  # Seconds to wait for the map to load after pressing 'R'
RESET_HOLD_DURATION = 0.4  # Seconds to hold the 'R' key
HOTKEY = "f6"  # Global hotkey to start/stop the script
MENU_HOTKEY = "home"  # Global hotkey to return to menu
RESET_HOTKEY = 'r'
# ==========================================
# FUZZY MATCHING SETTINGS
# ==========================================
KNOWN_KEYS = [
    "Boss Curses",
    "Challenges",
    "Charge Shrines",
    "Chests",
    "Greed Shrines",
    "Magnet Shrines",
    "Microwaves",
    "Moais",
    "Pots",
    "Shady Guy"
]

ALIASES = {
    "boss curse": "Boss Curses",
    "boss curses": "Boss Curses",

    "challenge": "Challenges",
    "challenges": "Challenges",

    "charge shrine": "Charge Shrines",
    "charge shrines": "Charge Shrines",

    "chest": "Chests",
    "chests": "Chests",

    "greed shrine": "Greed Shrines",
    "greed shrines": "Greed Shrines",

    "magnet shrine": "Magnet Shrines",
    "magnet shrines": "Magnet Shrines",

    "microwave": "Microwaves",
    "microwaves": "Microwaves",
    "microwoves": "Microwaves",
    "microwavs": "Microwaves",

    "moai": "Moais",
    "moais": "Moais",
    "maais": "Moais",
    "moals": "Moais",

    "pot": "Pots",
    "pots": "Pots",

    "shady guy": "Shady Guy",
    "shady gvy": "Shady Guy",
    "shady guv": "Shady Guy",
}


def normalize_text(s: str) -> str:
    s = s.lower()
    s = re.sub(r'[^a-z0-9/ ]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def fuzzy_find_key(line: str) -> str | None:
    line_norm = normalize_text(line)

    # Убираем числа вида 0/5, чтобы сравнивать только название
    label_only = re.sub(r'\d+\s*/\s*\d+', '', line_norm).strip()

    if not label_only:
        return None

    # 1. Сначала точечные alias для типичных OCR-ошибок
    for alias, canonical in ALIASES.items():
        if alias in label_only:
            return canonical

    # 2. Потом fuzzy fallback
    normalized_map = {normalize_text(k): k for k in KNOWN_KEYS}
    # n=1: return only top match, cutoff=0.55: minimum similarity score
    match = get_close_matches(label_only, normalized_map.keys(), n=1, cutoff=0.55)

    if match:
        return normalized_map[match[0]]

    return None


# ==========================================
# HELPER FUNCTIONS & REGION SELECTION
# ==========================================
def get_screen_resolution():
    """Get the primary monitor resolution using ctypes."""
    user32 = ctypes.windll.user32
    # This prevents Windows from scaling the resolution if display scaling > 100%
    user32.SetProcessDPIAware()
    width = user32.GetSystemMetrics(0)
    height = user32.GetSystemMetrics(1)
    return width, height


def get_region_for_resolution(width, height):
    """Return the hardcoded region for the detected resolution."""
    if width == 2560 and height == 1440:
        return REGIONS["2K"], "2K"
    elif width == 1920 and height == 1080:
        return REGIONS["FHD"], "FHD"
    else:
        print(
            f"{Fore.YELLOW}Warning: Unsupported resolution ({width}x{height}) detected, defaulting to 2K coordinates.{Style.RESET_ALL}")
        return REGIONS["2K"], "2K (Fallback)"


# Dynamically calculate region based on actual screen size
SCREEN_WIDTH, SCREEN_HEIGHT = get_screen_resolution()
REGION, REGION_NAME = get_region_for_resolution(SCREEN_WIDTH, SCREEN_HEIGHT)

# ==========================================
# SCRIPT STATE
# ==========================================
is_running = False
return_to_menu = False
active_templates = []

# Define Templates
TEMPLATES = [
    {"id": 1, "name": "LIGHT", "color": Fore.WHITE, "desc": "S+M: 7, Micro: 2, Boss: 2+"},
    {"id": 2, "name": "MERCHANT", "color": Fore.CYAN, "desc": "S+M: 10+, Micro: 1, Boss: 2+"},
    {"id": 3, "name": "GOOD", "color": Fore.GREEN, "desc": "S+M: 8, Micro: 2, Boss: 1+"},
    {"id": 4, "name": "PERFECT", "color": Fore.YELLOW, "desc": "S+M: 8+, Micro: 2, Boss: 2+"},
    {"id": 5, "name": "PERFECT+", "color": Fore.LIGHTRED_EX, "desc": "S+M: 9+, Micro: 2, Boss: 3+"},
    {"id": 6, "name": "BOSS RUSH", "color": Fore.RED, "desc": "S+M: 5+, Micro: 1+, Boss: 5+"},
    {"id": 7, "name": "BOSS RUSH+", "color": Fore.MAGENTA, "desc": "Boss: 7+"}
]


def print_header():
    header = f"""
{Fore.MAGENTA}{Style.BRIGHT}
 __  __ ______ _____          ____   ____  _   _ _  __
|  \/  |  ____/ ____|   /\   |  _ \ / __ \| \ | | |/ /
| \  / | |__ | |  __   /  \  | |_) | |  | |  \| | ' / 
| |\/| |  __|| | |_ | / /\ \ |  _ <| |  | | . ` |  <  
| |  | | |___| |__| |/ ____ \| |_) | |__| | |\  | . \ 
|_|  |_|______\_____/_/    \_\____/ \____/|_| \_|_|\_\\
{Style.RESET_ALL}
"""
    print(header)


def setup_templates():
    global active_templates

    print_header()

    print(f"{Fore.BLUE}Detected Resolution: {SCREEN_WIDTH}x{SCREEN_HEIGHT}{Style.RESET_ALL}")
    print(
        f"{Fore.BLUE}Active Profile: {REGION_NAME} (L:{REGION['left']} T:{REGION['top']} W:{REGION['width']} H:{REGION['height']}){Style.RESET_ALL}\n")

    print("Available Templates:")
    for t in TEMPLATES:
        print(f"[{t['id']}] {t['color']}{t['name']}{Style.RESET_ALL} ({t['desc']})")

    print("\nEnter the numbers of templates you want to INCLUDE")
    print("(separated by space, or press Enter to include ALL):")
    print("(type 'q' or 'quit' to exit the script)")

    while True:
        user_input = input("> ").strip().lower()

        if user_input in ['q', 'quit', 'exit']:
            print("Exiting...")
            sys.exit(0)

        if not user_input:
            active_templates = [t['name'] for t in TEMPLATES]
            break

        try:
            included_ids = [int(x) for x in user_input.split()]
            active_templates = [t['name'] for t in TEMPLATES if t['id'] in included_ids]

            if not active_templates:
                print(
                    f"{Fore.RED}Error: You did not include any valid templates. Please enter valid numbers.{Style.RESET_ALL}")
                continue
            break
        except ValueError:
            print(
                f"{Fore.RED}Invalid input. Please enter numbers separated by spaces, or press Enter.{Style.RESET_ALL}")

    # Add some color to the active templates output
    colored_active_templates = []
    for temp_name in active_templates:
        for t in TEMPLATES:
            if t['name'] == temp_name:
                colored_active_templates.append(f"{t['color']}{temp_name}{Fore.GREEN}")

    print(f"\n{Fore.GREEN}Monitoring prepared! Looking for: {', '.join(colored_active_templates)}{Style.RESET_ALL}")
    print(f"Press '{HOTKEY}' to start or stop.")
    print(f"Press '{MENU_HOTKEY}' to return to this menu.")


def preprocess_image(img: Image.Image) -> Image.Image:
    """Advanced preprocessing pipeline for better OCR on small, white text over dark UI."""

    # 1. Upscale: Tesseract needs fonts to be larger (e.g., 30+ pixels high)
    upscaled = img.resize((img.width * 3, img.height * 3), Image.Resampling.LANCZOS)

    # 2. Grayscale: Remove color channels
    gray = ImageOps.grayscale(upscaled)

    # 3. Contrast Boost: Make the white pop and the background darker
    enhancer = ImageEnhance.Contrast(gray)
    high_contrast = enhancer.enhance(3.0)

    # 4. Invert: Tesseract prefers black text on white background
    inverted = ImageOps.invert(high_contrast)

    # 5. Binarization (Threshold): Pure black/white. Adjust threshold if needed.
    # Since we inverted, dark text (was bright white) is now near 0.
    threshold = 120
    binary = inverted.point(lambda p: 255 if p > threshold else 0)

    return binary


def extract_stats(text: str) -> dict:
    """Extract the total values from the OCR text using fuzzy matching."""
    stats = {
        "Boss Curses": 0, "Challenges": 0, "Charge Shrines": 0, "Chests": 0,
        "Greed Shrines": 0, "Magnet Shrines": 0, "Microwaves": 0,
        "Moais": 0, "Pots": 0, "Shady Guy": 0
    }

    lines = text.split('\n')

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue

        # 1. Сначала пытаемся понять, о каком стате идет речь в этой строке
        found_key = fuzzy_find_key(line)
        if not found_key:
            continue

        # 2. Если стат опознан, вытаскиваем из строки число, идущее после слеша
        match = re.search(r'/\s*(\d+)', line)
        if match:
            try:
                val = int(match.group(1))

                # Фильтр: отсекаем явно ошибочные значения OCR (больше 14)
                # Так как в игре физически не может быть 15 Moais или 15 Shady Guy
                if val <= 14:
                    stats[found_key] = val
            except ValueError:
                pass

    return stats


def is_near_perfect_plus(stats: dict) -> bool:
    """
    VERY broad check for 'maybe PERFECT+' maps.
    Designed to minimize false rerolls, even if OCR lost one of the key stats.
    """

    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    microwaves = stats.get("Microwaves", 0)
    boss = stats.get("Boss Curses", 0)

    sm_total = shady + moai

    # Без 2 microwaves смысла почти нет
    if microwaves < 2:
        return False

    # Без 2 boss тоже почти нет смысла
    if boss < 2:
        return False

    # -------------------------------------------------
    # 1. Очевидно сильные случаи
    # -------------------------------------------------
    if sm_total >= 8:
        return True

    if shady >= 8 or moai >= 8:
        return True

    # -------------------------------------------------
    # 2. Сильные раздельные комбинации
    # -------------------------------------------------
    strong_pairs = [
        (7, 1),
        (6, 2),
        (5, 3),
        (4, 4),
        (3, 5),
        (2, 6),
        (1, 7),
    ]

    for s_req, m_req in strong_pairs:
        if shady >= s_req and moai >= m_req:
            return True
        if shady >= m_req and moai >= s_req:
            return True

    # -------------------------------------------------
    # 3. Если boss уже 3+, можно быть еще мягче
    # -------------------------------------------------
    if boss >= 3:
        if sm_total >= 6:
            return True

        if shady >= 7 or moai >= 7:
            return True

        if shady >= 5 and moai >= 1:
            return True
        if shady >= 1 and moai >= 5:
            return True

        if shady >= 4 and moai >= 2:
            return True
        if shady >= 2 and moai >= 4:
            return True

        if shady >= 3 and moai >= 3:
            return True

        # Очень важный кейс:
        # один из двух статов мог упасть в 0 из-за OCR
        if shady == 0 and moai >= 3:
            return True
        if moai == 0 and shady >= 3:
            return True

    # -------------------------------------------------
    # 4. Если один стат очень высокий,
    #    второй мог просто потеряться OCR'ом
    # -------------------------------------------------
    if shady >= 7:
        return True
    if moai >= 7:
        return True

    if shady >= 6 and boss >= 2:
        return True
    if moai >= 6 and boss >= 2:
        return True

    # -------------------------------------------------
    # 5. Защита от случаев, когда OCR занизил total
    # -------------------------------------------------
    if sm_total >= 7 and boss >= 2:
        return True

    if sm_total >= 5 and boss >= 3:
        return True

    # -------------------------------------------------
    # 6. Подозрительные асимметричные кейсы
    # -------------------------------------------------
    if shady >= 5 and moai == 0 and boss >= 3:
        return True

    if moai >= 5 and shady == 0 and boss >= 3:
        return True

    if shady >= 4 and moai == 0 and boss >= 3:
        return True

    if moai >= 4 and shady == 0 and boss >= 3:
        return True

    return False


def conditions_met(stats: dict) -> bool:
    """Check map against active profiles."""
    shady_moai = stats.get("Shady Guy", 0) + stats.get("Moais", 0)
    microwaves = stats.get("Microwaves", 0)
    boss = stats.get("Boss Curses", 0)

    # Note: Checking the strictest conditions first is crucial, otherwise a lesser template might trigger first when both are active.

    # Check conditions only for active templates
    if "BOSS RUSH+" in active_templates and (boss >= 7):
        print(f"\n[+] Find good map! type: {Fore.MAGENTA}BOSS RUSH+{Style.RESET_ALL}")
        return True

    if "BOSS RUSH" in active_templates and (shady_moai >= 5) and (microwaves >= 1) and (boss >= 5):
        print(f"\n[+] Find good map! type: {Fore.RED}BOSS RUSH{Style.RESET_ALL}")
        return True

    if "PERFECT+" in active_templates and (shady_moai >= 9) and (microwaves >= 2) and (boss >= 3):
        print(f"\n[+] Find good map! type: {Fore.LIGHTRED_EX}PERFECT+{Style.RESET_ALL}")
        return True

    if "PERFECT" in active_templates and (shady_moai >= 8) and (microwaves >= 2) and (boss >= 2):
        print(f"\n[+] Find good map! type: {Fore.YELLOW}PERFECT{Style.RESET_ALL}")
        return True

    if "GOOD" in active_templates and (shady_moai >= 8) and (microwaves >= 2) and (boss >= 1):
        print(f"\n[+] Find good map! type: {Fore.GREEN}GOOD{Style.RESET_ALL}")
        return True

    if "MERCHANT" in active_templates and (shady_moai >= 10) and (microwaves >= 1) and (boss >= 2):
        print(f"\n[+] Find good map! type: {Fore.CYAN}MERCHANT{Style.RESET_ALL}")
        return True

    if "LIGHT" in active_templates and (shady_moai >= 7) and (microwaves >= 2) and (boss >= 2):
        print(f"\n[+] Find good map! type: {Fore.WHITE}LIGHT{Style.RESET_ALL}")
        return True

    return False


def toggle_script():
    """Toggle the running state of the loop when the hotkey is pressed."""
    global is_running
    is_running = not is_running
    status = "STARTED" if is_running else "STOPPED"
    print(f"\n[!] Script {status}")


def trigger_return_to_menu():
    """Signal the main loop to break and return to the setup menu."""
    global return_to_menu, is_running
    is_running = False
    return_to_menu = True
    print(f"\n[!] Returning to menu...")


def run_scanner():
    global is_running, return_to_menu

    # Reset state
    is_running = False
    return_to_menu = False

    # Use mss context manager for fast screenshots
    with mss.mss() as sct:
        while True:
            # Check if we need to break out to the menu
            if return_to_menu:
                break

            # If script isn't active, sleep briefly and wait
            if not is_running:
                time.sleep(0.1)
                continue

            try:
                # 1. Capture Region
                screenshot = sct.grab(REGION)
                img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")

                # 2. Preprocess Image
                processed_img = preprocess_image(img)

                # 3. OCR Text Extraction (PSM 6 assumes a uniform block of text)
                text = pytesseract.image_to_string(processed_img, config='--oem 3 --psm 6')
                stats = extract_stats(text)

                # 4. Logic & Conditions
                shady = stats.get("Shady Guy", 0)
                moai = stats.get("Moais", 0)
                microwaves = stats.get("Microwaves", 0)
                boss = stats.get("Boss Curses", 0)

                if conditions_met(stats):
                    print(f"Current Map Stats: Shady: {shady}, Moai: {moai}, Microwaves: {microwaves}, Boss: {boss}")
                    print("Target Map Found!")
                    keyboard.press_and_release('esc')  # Changed to press_and_release
                    is_running = False  # Stop the loop, wait for manual trigger
                else:
                    # Double-check logic for "near PERFECT+" to prevent false rerolls
                    if "PERFECT+" in active_templates and is_near_perfect_plus(stats):
                        print(f"Stats: S: {shady}, M: {moai}, Micro: {microwaves}, Boss: {boss}")
                        print(f"{Fore.YELLOW}Near PERFECT+ detected, rechecking...{Style.RESET_ALL}")

                        time.sleep(0.15)  # wait briefly

                        # Re-run OCR
                        screenshot2 = sct.grab(REGION)
                        img2 = Image.frombytes("RGB", screenshot2.size, screenshot2.bgra, "raw", "BGRX")
                        processed_img2 = preprocess_image(img2)
                        text2 = pytesseract.image_to_string(processed_img2, config='--oem 3 --psm 6')
                        stats2 = extract_stats(text2)

                        shady2 = stats2.get("Shady Guy", 0)
                        moai2 = stats2.get("Moais", 0)
                        microwaves2 = stats2.get("Microwaves", 0)
                        boss2 = stats2.get("Boss Curses", 0)

                        if conditions_met(stats2):
                            print(
                                f"Current Map Stats (Recheck): Shady: {shady2}, Moai: {moai2}, Microwaves: {microwaves2}, Boss: {boss2}")
                            print(f"{Fore.GREEN}Recheck confirmed! Target Map Found!{Style.RESET_ALL}")
                            keyboard.press_and_release('esc')
                            is_running = False
                            continue
                        else:
                            print(
                                f"Recheck Stats: S: {shady2}, M: {moai2}, Micro: {microwaves2}, Boss: {boss2} ... Reseting...")
                    else:
                        print(f"Stats: S: {shady}, M: {moai}, Micro: {microwaves}, Boss: {boss} ... Reseting...")

                    # Restart Macro
                    keyboard.press(RESET_HOTKEY)
                    time.sleep(RESET_HOLD_DURATION)
                    keyboard.release(RESET_HOTKEY)

                    # Wait for map load delay
                    time.sleep(MAP_LOAD_DELAY)

            except Exception as e:
                print(f"Error during execution (OCR failure?): {e}. Retrying...")
                time.sleep(1)


def main():
    # Register the hotkeys once
    keyboard.add_hotkey(HOTKEY, toggle_script)
    keyboard.add_hotkey(MENU_HOTKEY, trigger_return_to_menu)

    while True:
        # 1. Show the interactive setup menu
        setup_templates()

        # 2. Start the main scanning loop block
        # It will only exit run_scanner() if return_to_menu is triggered
        run_scanner()

        # 3. Clear the console (optional but looks cleaner when returning)
        # We print some newlines to separate the new menu from the old logs
        print("\n" * 5)


if __name__ == "__main__":
    main()