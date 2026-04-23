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

DEFAULT_SCORES_SYSTEM = {
    "manual_thresholds": False,
    "base_target_score": 30.0,
    "weights": {
      "moais": 3.0,
      "shady": 2.0,
      "boss": 1.0,
      "magnet": 0.5
    },
    "multipliers": {
      "microwave": {
        "1": 1.0,
        "2": 1.25
      }
    },
    "thresholds": {
      "Light": 14.0,
      "Good": 20.0,
      "Perfect": 25.0,
      "Perfect+": 30.0
    },
    "active_tiers": ["Light", "Good", "Perfect", "Perfect+"]
}

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
                    # The game's config stores the time without a safety margin. In our app, we add 0.05s for reliability.
                    return float(quick_reset_time) + 0.05
    except Exception as e:
        pass
    return None

def update_game_reset_time(game_val: float):
    try:
        user_profile = os.environ.get('USERPROFILE', '')
        if not user_profile:
            return
            
        game_dir = os.path.join(user_profile, "AppData", "LocalLow", "Ved", "Megabonk", "Saves", "LocalDir")
        game_config_path = os.path.join(game_dir, "config.json")
        
        # If the folders or file don't exist, we cannot update the game's config
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
        pass

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

# Migrate from MAP_LOAD_DELAY if MIN_DELAY is not found
MIN_DELAY = user_config.get("MIN_DELAY", user_config.get("MAP_LOAD_DELAY", 0.3))
MAP_LOAD_DELAY = MIN_DELAY

# Remove MAP_LOAD_DELAY if it's still there
if "MAP_LOAD_DELAY" in user_config:
    del user_config["MAP_LOAD_DELAY"]

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
NATIVE_HOOK_ENABLED = user_config.get("NATIVE_HOOK_ENABLED", True)
NATIVE_HOOK_DLL_PATH = user_config.get("NATIVE_HOOK_DLL_PATH", "")

# Load ignored updates
SKIPPED_UPDATE_VERSION = user_config.get("SKIPPED_UPDATE_VERSION", "")

# Attempt to retrieve templates from JSON. If the file was empty or contained no TEMPLATES,
# we use the built-in templates (DEFAULT_TEMPLATES) as a fallback.
TEMPLATES = user_config.get("TEMPLATES", DEFAULT_TEMPLATES)
if not TEMPLATES:
    TEMPLATES = DEFAULT_TEMPLATES

# Load active templates, default to all if not present
ACTIVE_TEMPLATES = user_config.get("ACTIVE_TEMPLATES")
if ACTIVE_TEMPLATES is None:
    ACTIVE_TEMPLATES = [t["name"] for t in TEMPLATES]


EVALUATION_MODE = user_config.get("EVALUATION_MODE", "templates")
SCORES_SYSTEM = user_config.get("SCORES_SYSTEM", DEFAULT_SCORES_SYSTEM)
if not SCORES_SYSTEM:
    SCORES_SYSTEM = DEFAULT_SCORES_SYSTEM

# Populate missing default keys for scores system from older config versions
for key, value in DEFAULT_SCORES_SYSTEM.items():
    if key not in SCORES_SYSTEM:
        SCORES_SYSTEM[key] = value

def calculate_auto_thresholds(current_weights: dict, current_multipliers: dict) -> dict:
    """Calculate scaled thresholds based on the reference map scale factor."""
    w_moai = current_weights.get("moais", 3.0)
    w_shady = current_weights.get("shady", 2.0)
    w_boss = current_weights.get("boss", 1.0)
    w_magnet = current_weights.get("magnet", 0.5)
    
    m_2 = current_multipliers.get("microwave", {}).get("2", 1.25)
    
    # Reference map with its new score (moai=3, shady=3, boss=2, magnet=2, microwave=2)
    # min(magnet, 2) is applied within the logic. For reference, magnet=2 means 2.
    new_score_ref = (3 * w_moai + 3 * w_shady + 2 * w_boss + 2 * w_magnet) * m_2
    
    # Base score of the reference map in the old model = 22.5
    base_score_ref = 22.5
    
    # Scaling factor
    scale_factor = new_score_ref / base_score_ref
    
    return {
        "Light": round(14.0 * scale_factor, 1),
        "Good": round(20.0 * scale_factor, 1),
        "Perfect": round(25.0 * scale_factor, 1),
        "Perfect+": round(30.0 * scale_factor, 1)
    }

# Update user_config object so that mutations to it are saved properly
user_config["MIN_DELAY"] = MIN_DELAY
user_config["RESET_HOLD_DURATION"] = round(RESET_HOLD_DURATION, 2)
user_config["HOTKEY"] = HOTKEY
user_config["MENU_HOTKEY"] = MENU_HOTKEY
user_config["RESET_HOTKEY"] = RESET_HOTKEY
user_config["PROCESS_NAME"] = PROCESS_NAME
user_config["NATIVE_HOOK_ENABLED"] = NATIVE_HOOK_ENABLED
user_config["NATIVE_HOOK_DLL_PATH"] = NATIVE_HOOK_DLL_PATH
user_config["TEMPLATES"] = TEMPLATES
user_config["ACTIVE_TEMPLATES"] = ACTIVE_TEMPLATES
user_config["SKIPPED_UPDATE_VERSION"] = SKIPPED_UPDATE_VERSION
user_config["EVALUATION_MODE"] = EVALUATION_MODE
user_config["SCORES_SYSTEM"] = SCORES_SYSTEM


# If the config.json file did not exist initially (or did not contain TEMPLATES),
# we immediately save the current structure to disk so that the user has something to edit.
save_config(user_config)
