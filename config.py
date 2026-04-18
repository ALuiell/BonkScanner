import os
import sys
import json
import colorama

colorama.init(autoreset=True)

# ==========================================
# CONSTANTS & SETTINGS
# ==========================================
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
# GAME CONFIG PARSER
# ==========================================
def get_game_reset_time() -> float | None:
    try:
        user_profile = os.environ.get('USERPROFILE', '')
        if not user_profile:
            return None
            
        game_config_path = os.path.join(
            user_profile, 
            "AppData", "LocalLow", "Ved", "Megabonk", "Saves", "LocalDir", "config.json"
        )
        if os.path.exists(game_config_path):
            with open(game_config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                quick_reset_time = data.get("cfGameSettings", {}).get("quick_reset_time")
                if quick_reset_time is not None:
                    # В конфиге игры хранится время без запаса. В нашей проге мы прибавляем 0.1 для надежности.
                    return float(quick_reset_time) + 0.1
    except Exception as e:
        print(f"Failed to read game config: {e}")
    return None

def update_game_reset_time(game_val: float):
    try:
        user_profile = os.environ.get('USERPROFILE', '')
        if not user_profile:
            return
            
        game_dir = os.path.join(user_profile, "AppData", "LocalLow", "Ved", "Megabonk", "Saves", "LocalDir")
        game_config_path = os.path.join(game_dir, "config.json")
        
        # Если папки или файла нет, мы не можем обновить конфиг игры
        if not os.path.exists(game_config_path):
            return
            
        with open(game_config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        if "cfGameSettings" not in data:
            data["cfGameSettings"] = {}
            
        data["cfGameSettings"]["quick_reset_time"] = game_val
        
        with open(game_config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Failed to update game config: {e}")

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

# Load RESET_HOLD_DURATION from user_config first, fallback to game config, fallback to default 0.4
RESET_HOLD_DURATION_USER = user_config.get("RESET_HOLD_DURATION")
if RESET_HOLD_DURATION_USER is not None:
    RESET_HOLD_DURATION = RESET_HOLD_DURATION_USER
else:
    game_reset_time = get_game_reset_time()
    if game_reset_time is not None:
        RESET_HOLD_DURATION = game_reset_time
    else:
        RESET_HOLD_DURATION = 0.4

HOTKEY = user_config.get("HOTKEY", "f6")
MENU_HOTKEY = user_config.get("MENU_HOTKEY", "home")
RESET_HOTKEY = user_config.get("RESET_HOTKEY", "r")
PROCESS_NAME = user_config.get("PROCESS_NAME", "Megabonk.exe")

# Load ignored updates
SKIPPED_UPDATE_VERSION = user_config.get("SKIPPED_UPDATE_VERSION", "")

# Попытка получить шаблоны из JSON. Если файл был пустой или без TEMPLATES,
# берем встроенные (DEFAULT_TEMPLATES) как резерв.
TEMPLATES = user_config.get("TEMPLATES", DEFAULT_TEMPLATES)
if not TEMPLATES:
    TEMPLATES = DEFAULT_TEMPLATES

# Load active templates, default to all if not present
ACTIVE_TEMPLATES = user_config.get("ACTIVE_TEMPLATES")
if ACTIVE_TEMPLATES is None:
    ACTIVE_TEMPLATES = [t["name"] for t in TEMPLATES]


# Update user_config object so that mutations to it are saved properly
user_config["MAP_LOAD_DELAY"] = MAP_LOAD_DELAY
user_config["RESET_HOLD_DURATION"] = round(RESET_HOLD_DURATION, 2)
user_config["HOTKEY"] = HOTKEY
user_config["MENU_HOTKEY"] = MENU_HOTKEY
user_config["RESET_HOTKEY"] = RESET_HOTKEY
user_config["PROCESS_NAME"] = PROCESS_NAME
user_config["TEMPLATES"] = TEMPLATES
user_config["ACTIVE_TEMPLATES"] = ACTIVE_TEMPLATES
user_config["SKIPPED_UPDATE_VERSION"] = SKIPPED_UPDATE_VERSION

# If the config.json file did not exist initially (or did not contain TEMPLATES),
# we immediately save the current structure to disk so that the user has something to edit.
save_config(user_config)
