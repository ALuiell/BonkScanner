import os
import sys
import json
import colorama
import threading

colorama.init(autoreset=True)
config_lock = threading.RLock()

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

DEFAULT_HOTKEY_GAME_KEY_WHITELIST = [
    "w", "a", "s", "d", "up", "down", "left", "right",
    "q", "e", "r", "f", "g", "t", "z", "x", "c", "v", "b",
    "space", "left shift",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    "tab",
]

DEFAULT_OVERLAY = {
    "schema_version": 4,
    "enabled": False,
    "auto_start": False,
    "host": "127.0.0.1",
    "port": 17845,
    "template": "compact",
    "poll_ms": 500,
    "canvas_width": 1920,
    "canvas_height": 1080,
    "widgets": [
        {"id": "stage_summary", "enabled": True, "mode": "compact", "order": 40, "max_rows": 4, "background_opacity": 0.4, "show_border": True},
        {"id": "tracked_items", "enabled": True, "mode": "compact", "order": 50, "background_opacity": 0.0, "show_border": False},
        {"id": "stats", "enabled": False, "mode": "compact", "order": 55, "max_rows": 40, "selected_stats": ["Damage", "Attack Speed", "Luck", "XP Gain"], "background_opacity": 0.0, "show_border": False, "show_header": True},
        {"id": "banishes", "enabled": False, "mode": "compact", "order": 80, "max_rows": 40, "background_opacity": 0.0, "show_border": False, "show_header": True},
    ],
    "tracked_items": [
        {
            "id": "anvils_map_1",
            "label": "Anvils Map 1",
            "item_names": ["Anvil"],
            "mode": "map_1_only",
        }
    ],
    "style": {
        "scale": 1.0,
        "accent_color": "#F6C453",
        "background_opacity": 0.22,
        "stage_background_opacity": 0.15,
    },
}

DEFAULT_SESSION_TRACKED_ITEMS = {
    "tracked_items": [
        {
            "id": "session_anvils_map_1",
            "label": "Anvils Map 1",
            "item_names": ["Anvil"],
            "mode": "map_1_only",
        }
    ],
}

ALL_STAT_LABELS = [
    "Max HP", "HP Regen", "Overheal", "Shield", "Armor", "Evasion", "Lifesteal", "Thorns",
    "Damage", "Crit Chance", "Crit Damage", "Attack Speed", "Projectile Count", "Projectile Bounces",
    "Size", "Projectile Speed", "Duration", "Damage to Elites", "Knockback", "Movement Speed",
    "Extra Jumps", "Jump Height", "Luck", "Difficulty",
    "Pickup Range", "XP Gain", "Gold Gain", "Elite Spawn Increase", "Powerup Multiplier", "Powerup Drop Chance"
]

DEFAULT_TWITCH_BOT = {
    "enabled": False,
    "auto_connect": False,
    "username": "",
    "target_channel": "",
    "access_tier": "Everyone",
    "global_cooldown_seconds": 5,
    "cooldown_seconds": 5,
    "stage_announcements": True,
    "commands_announcements": False,
    "commands_announcement_interval_minutes": 30,
    "commands": {
        "stats": True,
        "bans": True,
        "items": True,
        "weapons": True,
        "tomes": True,
        "chaos": True,
        "stages": True,
        "powerups": True,
        "scanner": True,
        "chests": False,
        "presets": False,
        "commands": False,
        "disabled": False
    },
    "selected_stats": [
        "Damage", "XP Gain", "Luck", "Difficulty",
        "Powerup Drop Chance", "Elite Spawn Increase",
        "Powerup Multiplier", "Size"
    ],
    "highlighted_disabled_items": [],
    "templates": {
        "stats": "Live Stats: DMG: {Damage} | XP: {XP Gain} | Luck: {Luck} | Size: {Size}",
        "bans": "Bans ({count}): {items}",
        "items": "Items ({count}): {items}",
        "weapons": "Weapons: {weapons}",
        "tomes": "Tomes: {tomes}",
        "chaos": "Chaos Tome Lv{level}: {chaos}",
        "stages": "{stages}",
        "powerups": "Powerups: Rage/Shield/Coin/Speed {standard_duration}s | Clock {clock_duration}s (PM {pm})",
        "scanner": "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} | Try !stats, !bans, !items, !weapons, !tomes, !chaos, !stages, !powerups, !chests. Aliases: !bonkstats, !banishes, !tracked, !chaostome.",
        "chests": "Chests: {stages} | Total: {opened}/{total} | Paid: {paid} | Key Procs: {procs}/{normal} ({proc_rate}) | Expected: {expected} | Free Chests: {free} | Keys: {keys} ({chance})",
        "disabled": "Disabled Items: {items}",
        "stage_announcement": "🚩 Stage {stage} completed! Kills: {kills} | Time: {time}. Moving to Stage {next_stage}! 🚩",
        "stage_announcement_simple": "🚩 Moving to Stage {next_stage}! 🚩"
    }
}

LEGACY_TWITCH_SCANNER_TEMPLATES = {
    "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} | Try !stats, !bans, !items, !weapons, !tomes, !stages, !powerups.",
    "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} | Try !stats, !bans, !items, !weapons, !tomes, !chaos, !stages, !powerups.",
    "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} | Try !stats, !bans, !items, !weapons, !tomes, !chaos, !stages, !powerups. Aliases: !bonkstats, !banishes, !tracked, !chaostome.",
}

LEGACY_TWITCH_CHESTS_TEMPLATES = {
    "Chests opened: {opened}/{total} | Keys: {keys} (Proc Chance: {chance})",
    "Chests opened: {opened}/{total} | Keys: {keys} (Proc Chance: {chance}) | Free chest: {procs}",
    "Chests: {stages} | Total: {opened}/{total} | Paid: {paid} | Key Procs: {procs}/{normal} ({proc_rate}) | Free Chests: {free} | Keys: {keys} ({chance})",
    "Chests: {stages} | Total: {opened}/{total} | Paid: {paid} | Key Procs: {procs}/{normal} ({proc_rate}) | Expected: {expected} | Free Chests: {free} | Keys: {keys} ({chance})",
}



PATREON_SUPPORT_URL = "https://www.patreon.com/cw/ALuiel"
KOFI_SUPPORT_URL = "https://ko-fi.com/s/34dc062a82"

# ==========================================
# GAME CONFIG PARSER
# ==========================================
def get_game_config_path() -> str | None:
    user_profile = os.environ.get('USERPROFILE', '')
    if not user_profile:
        return None
    return os.path.join(
        user_profile,
        "AppData",
        "LocalLow",
        "Ved",
        "Megabonk",
        "Saves",
        "LocalDir",
        "config.json",
    )


def load_game_config() -> dict | None:
    try:
        game_config_path = get_game_config_path()
        if not game_config_path or not os.path.exists(game_config_path):
            return None
        with open(game_config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def save_game_config(data: dict) -> bool:
    try:
        game_config_path = get_game_config_path()
        if not game_config_path:
            return False
        game_dir = os.path.dirname(game_config_path)
        if not os.path.isdir(game_dir):
            return False
        with open(game_config_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def get_game_settings() -> dict | None:
    data = load_game_config()
    settings = (data or {}).get("cfGameSettings")
    return settings.copy() if isinstance(settings, dict) else None


def get_game_setting(name: str, default=None):
    settings = get_game_settings()
    if not isinstance(settings, dict):
        return default
    return settings.get(name, default)


def update_game_setting(name: str, value) -> bool:
    try:
        data = load_game_config()
        if data is None:
            return False
        if "cfGameSettings" not in data or not isinstance(data["cfGameSettings"], dict):
            data["cfGameSettings"] = {}
        data["cfGameSettings"][name] = value
        return save_game_config(data)
    except Exception:
        return False


def toggle_game_setting(name: str) -> bool | None:
    current_value = get_game_setting(name)
    if current_value is None:
        return None

    enabled = bool(current_value)
    toggled = not enabled

    if isinstance(current_value, bool):
        stored_value = toggled
    elif isinstance(current_value, int):
        stored_value = 1 if toggled else 0
    elif isinstance(current_value, float):
        stored_value = 1.0 if toggled else 0.0
    else:
        stored_value = 1 if toggled else 0

    if not update_game_setting(name, stored_value):
        return None
    return toggled


def get_game_reset_time() -> float | None:
    try:
        data = load_game_config()
        if data is not None:
            quick_reset_time = data.get("cfGameSettings", {}).get("quick_reset_time")
            if quick_reset_time is not None:
                # The game's config stores the time without a safety margin. In our app, we add 0.05s for reliability.
                return float(quick_reset_time) + 0.05
    except Exception as e:
        pass
    return None

def update_game_reset_time(game_val: float):
    try:
        data = load_game_config()
        if data is None:
            return
        if "cfGameSettings" not in data:
            data["cfGameSettings"] = {}
        data["cfGameSettings"]["quick_reset_time"] = game_val
        save_game_config(data)
    except Exception as e:
        pass

# ==========================================
# LOAD JSON CONFIG
# ==========================================
config_path = os.path.join(application_path, "config.json")

def load_config():
    with config_lock:
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

def save_config(cfg_dict):
    with config_lock:
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(cfg_dict, f, indent=4)
        except Exception:
            pass

user_config = load_config()

def coerce_nonnegative_int(value, default=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)


def normalize_hotkey_game_key_whitelist(value) -> list[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        value = DEFAULT_HOTKEY_GAME_KEY_WHITELIST

    normalized: list[str] = []
    seen: set[str] = set()
    for key_name in value:
        key_name = str(key_name).strip().lower()
        if key_name and key_name not in seen:
            normalized.append(key_name)
            seen.add(key_name)
    return normalized


def _merge_dict_defaults(value, defaults):
    result = {}
    source = value if isinstance(value, dict) else {}
    for key, default_value in defaults.items():
        if isinstance(default_value, dict):
            result[key] = _merge_dict_defaults(source.get(key), default_value)
        elif isinstance(default_value, list):
            saved_value = source.get(key)
            result[key] = saved_value if isinstance(saved_value, list) else list(default_value)
        else:
            result[key] = source.get(key, default_value)
    for key, saved_value in source.items():
        if key not in result:
            result[key] = saved_value
    return result


def normalize_overlay_config(value):
    overlay = _merge_dict_defaults(value, DEFAULT_OVERLAY)
    saved_schema_version = coerce_nonnegative_int((value or {}).get("schema_version"), 1) if isinstance(value, dict) else 0
    if saved_schema_version < DEFAULT_OVERLAY["schema_version"]:
        overlay["style"] = _merge_dict_defaults(overlay.get("style"), DEFAULT_OVERLAY["style"])
    
    overlay["widgets"] = _normalize_overlay_widgets(overlay.get("widgets"))

    # We forcefully reset max_rows to 40 for stats and banishes in case they were saved as 8/12 in the past
    # so that the grid can expand properly without backend limitation.
    for widget in overlay["widgets"]:
        if widget.get("id") in {"stats", "banishes"}:
            if coerce_nonnegative_int(widget.get("max_rows"), 0) < 40:
                widget["max_rows"] = 40

    # Remove deleted widgets from the normalized list
    kept_widgets = []
    for widget in overlay["widgets"]:
        if widget.get("id") not in {"items", "weapons"}:
            # Migrate stage_summary background_opacity: CSS previously hardcoded 0.4,
            # so configs saved with the old default 0.15 never actually displayed at 0.15.
            if widget.get("id") == "stage_summary" and widget.get("background_opacity") == 0.15:
                widget["background_opacity"] = 0.4
            kept_widgets.append(widget)
    overlay["widgets"] = kept_widgets

    overlay["schema_version"] = DEFAULT_OVERLAY["schema_version"]
    overlay["enabled"] = bool(overlay.get("enabled", False))
    overlay["auto_start"] = bool(overlay.get("auto_start", False))
    overlay["host"] = "127.0.0.1"
    overlay["template"] = str(overlay.get("template") or "compact")
    overlay["poll_ms"] = max(250, min(coerce_nonnegative_int(overlay.get("poll_ms"), 500) or 500, 5000))
    overlay["canvas_width"] = coerce_nonnegative_int(overlay.get("canvas_width"), 1920) or 1920
    overlay["canvas_height"] = coerce_nonnegative_int(overlay.get("canvas_height"), 1080) or 1080
    port = coerce_nonnegative_int(overlay.get("port"), DEFAULT_OVERLAY["port"])
    if port < 1024 or port > 65535:
        port = DEFAULT_OVERLAY["port"]
    overlay["port"] = port
    if not isinstance(overlay.get("tracked_items"), list):
        overlay["tracked_items"] = list(DEFAULT_OVERLAY["tracked_items"])
    if not isinstance(overlay.get("style"), dict):
        overlay["style"] = dict(DEFAULT_OVERLAY["style"])
    return overlay


def normalize_session_tracked_items_config(value):
    session_cfg = _merge_dict_defaults(value, DEFAULT_SESSION_TRACKED_ITEMS)
    if not isinstance(session_cfg.get("tracked_items"), list):
        session_cfg["tracked_items"] = list(DEFAULT_SESSION_TRACKED_ITEMS["tracked_items"])
    normalized_rules = []
    for raw_rule in session_cfg.get("tracked_items") or ():
        if not isinstance(raw_rule, dict):
            continue
        item_names = [str(name) for name in raw_rule.get("item_names") or () if str(name).strip()]
        if not item_names:
            continue
        mode = str(raw_rule.get("mode") or "all_run")
        normalized_rules.append(
            {
                "id": str(raw_rule.get("id") or "_".join(item_names).lower()),
                "label": str(raw_rule.get("label") or ", ".join(item_names)),
                "item_names": item_names,
                "mode": mode,
            }
        )
    session_cfg["tracked_items"] = normalized_rules
    return session_cfg


def normalize_twitch_bot_config(value):
    bot_cfg = _merge_dict_defaults(value, DEFAULT_TWITCH_BOT)
    bot_cfg["enabled"] = bool(bot_cfg.get("enabled", False))
    bot_cfg["auto_connect"] = bool(bot_cfg.get("auto_connect", False))
    bot_cfg["username"] = str(bot_cfg.get("username") or "")
    target_channel = str(bot_cfg.get("target_channel") or "").strip().lstrip("#")
    bot_cfg["target_channel"] = target_channel.lower()
    
    # Actively cleanse oauth_token from older configs
    bot_cfg.pop("oauth_token", None)
    
    tier = str(bot_cfg.get("access_tier") or "Everyone")
    if tier not in {"Everyone", "Subs & Mods", "Mods & VIPs"}:
        tier = "Everyone"
    bot_cfg["access_tier"] = tier
    
    bot_cfg["global_cooldown_seconds"] = max(0, coerce_nonnegative_int(bot_cfg.get("global_cooldown_seconds"), 5))
    bot_cfg["cooldown_seconds"] = max(0, coerce_nonnegative_int(bot_cfg.get("cooldown_seconds"), 5))
    bot_cfg["stage_announcements"] = bool(bot_cfg.get("stage_announcements", True))
    bot_cfg["commands_announcements"] = bool(bot_cfg.get("commands_announcements", False))
    bot_cfg["commands_announcement_interval_minutes"] = min(
        1440,
        max(1, coerce_nonnegative_int(bot_cfg.get("commands_announcement_interval_minutes"), 30)),
    )
    bot_cfg.pop("chests_expected_enabled", None)
    
    if not isinstance(bot_cfg.get("commands"), dict):
        bot_cfg["commands"] = dict(DEFAULT_TWITCH_BOT["commands"])
    for cmd, default_enabled in DEFAULT_TWITCH_BOT["commands"].items():
        bot_cfg["commands"][cmd] = bool(bot_cfg["commands"].get(cmd, default_enabled))
        
    # Normalize selected_stats
    if not isinstance(bot_cfg.get("selected_stats"), list):
        bot_cfg["selected_stats"] = list(DEFAULT_TWITCH_BOT["selected_stats"])
    else:
        allowed_stats = set(ALL_STAT_LABELS)
        bot_cfg["selected_stats"] = [
            str(stat) for stat in bot_cfg["selected_stats"] if str(stat) in allowed_stats
        ]
        if not bot_cfg["selected_stats"]:
            bot_cfg["selected_stats"] = list(DEFAULT_TWITCH_BOT["selected_stats"])

    # Normalize highlighted_disabled_items
    if not isinstance(bot_cfg.get("highlighted_disabled_items"), list):
        bot_cfg["highlighted_disabled_items"] = list(DEFAULT_TWITCH_BOT["highlighted_disabled_items"])
    else:
        bot_cfg["highlighted_disabled_items"] = [
            str(item).strip() for item in bot_cfg["highlighted_disabled_items"] if item
        ]

    # Normalize templates
    if not isinstance(bot_cfg.get("templates"), dict):
        bot_cfg["templates"] = dict(DEFAULT_TWITCH_BOT["templates"])
    else:
        bot_cfg["templates"] = _merge_dict_defaults(bot_cfg["templates"], DEFAULT_TWITCH_BOT["templates"])
        for k in DEFAULT_TWITCH_BOT["templates"]:
            bot_cfg["templates"][k] = str(bot_cfg["templates"].get(k, DEFAULT_TWITCH_BOT["templates"][k]))
    if bot_cfg["templates"].get("scanner") in LEGACY_TWITCH_SCANNER_TEMPLATES:
        bot_cfg["templates"]["scanner"] = DEFAULT_TWITCH_BOT["templates"]["scanner"]
    if bot_cfg["templates"].get("chests") in LEGACY_TWITCH_CHESTS_TEMPLATES:
        bot_cfg["templates"]["chests"] = DEFAULT_TWITCH_BOT["templates"]["chests"]

    return bot_cfg



def _normalize_overlay_widgets(value):
    default_widgets = [dict(widget) for widget in DEFAULT_OVERLAY["widgets"]]
    if not isinstance(value, list):
        return default_widgets

    saved_by_id = {}
    extra_widgets = []
    for raw_widget in value:
        if not isinstance(raw_widget, dict):
            continue
        widget_id = str(raw_widget.get("id") or "").strip()
        if not widget_id:
            continue
        widget = dict(raw_widget)
        widget["id"] = widget_id
        if widget_id in saved_by_id:
            saved_by_id[widget_id].update(widget)
        else:
            saved_by_id[widget_id] = widget

    normalized = []
    default_ids = set()
    for default_widget in default_widgets:
        widget_id = str(default_widget.get("id") or "")
        default_ids.add(widget_id)
        merged = dict(default_widget)
        merged.update(saved_by_id.get(widget_id, {}))
        normalized.append(merged)

    for widget_id, widget in saved_by_id.items():
        if widget_id not in default_ids:
            extra_widgets.append(widget)
    normalized.extend(extra_widgets)
    return normalized

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
HOTKEY_GAME_KEY_WHITELIST = normalize_hotkey_game_key_whitelist(
    user_config.get("HOTKEY_GAME_KEY_WHITELIST", DEFAULT_HOTKEY_GAME_KEY_WHITELIST)
)
PLAYER_STATS_RECORD_HOTKEY = user_config.get("PLAYER_STATS_RECORD_HOTKEY", "f8")
PLAYER_STATS_RECORD_INTERVAL_SECONDS = coerce_nonnegative_int(
    user_config.get("PLAYER_STATS_RECORD_INTERVAL_SECONDS", 30),
    30,
) or 30
CHAOS_TOME_TRACKER_INTERVAL_MS = max(
    100,
    coerce_nonnegative_int(user_config.get("CHAOS_TOME_TRACKER_INTERVAL_MS", 250), 250) or 250,
)
AUTO_START_RECORDING = bool(user_config.get("AUTO_START_RECORDING", False))
MENU_HOTKEY = user_config.get("MENU_HOTKEY", "home")
RESET_HOTKEY = user_config.get("RESET_HOTKEY", "r")
TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY = user_config.get("TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY", "f11")
TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY = user_config.get("TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY", "f10")
TOGGLE_PARTICLES_OPACITY_HOTKEY = user_config.get("TOGGLE_PARTICLES_OPACITY_HOTKEY", "f7")
PROCESS_NAME = user_config.get("PROCESS_NAME", "Megabonk.exe")
NATIVE_HOOK_ENABLED = user_config.get("NATIVE_HOOK_ENABLED", False)
NATIVE_HOOK_GAME_SETTING_HOTKEYS_ENABLED = user_config.get("NATIVE_HOOK_GAME_SETTING_HOTKEYS_ENABLED", False)
TOTAL_REROLLS = coerce_nonnegative_int(user_config.get("TOTAL_REROLLS", 0))

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
OVERLAY = normalize_overlay_config(user_config.get("OVERLAY"))
SESSION_TRACKED_ITEMS = normalize_session_tracked_items_config(user_config.get("SESSION_TRACKED_ITEMS"))
TWITCH_BOT = normalize_twitch_bot_config(user_config.get("TWITCH_BOT"))

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
user_config["HOTKEY_GAME_KEY_WHITELIST"] = HOTKEY_GAME_KEY_WHITELIST
user_config["PLAYER_STATS_RECORD_HOTKEY"] = PLAYER_STATS_RECORD_HOTKEY
user_config["PLAYER_STATS_RECORD_INTERVAL_SECONDS"] = PLAYER_STATS_RECORD_INTERVAL_SECONDS
user_config["CHAOS_TOME_TRACKER_INTERVAL_MS"] = CHAOS_TOME_TRACKER_INTERVAL_MS
user_config["AUTO_START_RECORDING"] = AUTO_START_RECORDING
user_config["MENU_HOTKEY"] = MENU_HOTKEY
user_config["RESET_HOTKEY"] = RESET_HOTKEY
user_config["TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY"] = TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY
user_config["TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY"] = TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY
user_config["TOGGLE_PARTICLES_OPACITY_HOTKEY"] = TOGGLE_PARTICLES_OPACITY_HOTKEY
user_config["PROCESS_NAME"] = PROCESS_NAME
user_config["NATIVE_HOOK_ENABLED"] = NATIVE_HOOK_ENABLED
user_config["NATIVE_HOOK_GAME_SETTING_HOTKEYS_ENABLED"] = NATIVE_HOOK_GAME_SETTING_HOTKEYS_ENABLED
user_config["TOTAL_REROLLS"] = TOTAL_REROLLS
user_config["TEMPLATES"] = TEMPLATES
user_config["ACTIVE_TEMPLATES"] = ACTIVE_TEMPLATES
user_config["SKIPPED_UPDATE_VERSION"] = SKIPPED_UPDATE_VERSION
user_config["EVALUATION_MODE"] = EVALUATION_MODE
user_config["SCORES_SYSTEM"] = SCORES_SYSTEM
user_config["OVERLAY"] = OVERLAY
user_config["SESSION_TRACKED_ITEMS"] = SESSION_TRACKED_ITEMS
user_config["TWITCH_BOT"] = TWITCH_BOT
user_config.pop("NATIVE_HOOK_DLL_PATH", None)


# If the config.json file did not exist initially (or did not contain TEMPLATES),
# we immediately save the current structure to disk so that the user has something to edit.
save_config(user_config)
