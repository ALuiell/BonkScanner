import os
import json
import math
import shutil
import colorama
import threading
from uuid import uuid4
from dataclasses import dataclass

from core.build_progression import PROGRESS_TARGETS
from infra import paths

colorama.init(autoreset=True)
config_lock = threading.RLock()

# ==========================================
# CONSTANTS & SETTINGS
# ==========================================
# Dynamic path resolution. Anchored in infra/paths.py, not here: these were
# derived from this file's own __file__, so moving this file moved the user's
# config.json and recordings with it. Step 10b did exactly that.
source_path = paths.source_path()
application_path = paths.application_path()

DEFAULT_TEMPLATES = [
    {"id": 1, "name": "LIGHT", "color": "WHITE", "desc": "S+M: 7, Micro: 2, Boss: 2+", "sm_total": 7, "micro": 2, "boss": 2},
    {"id": 2, "name": "MERCHANT", "color": "CYAN", "desc": "S+M: 10+, Micro: 1, Boss: 2+", "sm_total": 10, "micro": 1, "boss": 2},
    {"id": 3, "name": "GOOD", "color": "GREEN", "desc": "S+M: 8, Micro: 2, Boss: 1+", "sm_total": 8, "micro": 2, "boss": 1},
    {"id": 4, "name": "PERFECT", "color": "YELLOW", "desc": "S+M: 8+, Micro: 2, Boss: 2+", "sm_total": 8, "micro": 2, "boss": 2},
    # ORANGE rather than LIGHTRED_EX: the tag had to change because the two
    # colours are wanted apart -- LIGHTRED_EX is still the *Perfect+ score tier*
    # in `_tier_color` and the scanner's log. See `core/template_colors.py`, and
    # `_migrate_template_colors` below for the saved configs that carry the old
    # tag. The other three defaults keep their tags and change meaning through
    # the template palette instead, so they need no migration at all.
    {"id": 5, "name": "PERFECT+", "color": "ORANGE", "desc": "S+M: 9+, Micro: 2, Boss: 3+", "sm_total": 9, "micro": 2, "boss": 3},
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
      "magnet": 0.5,
      "challenges": 0.0
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
    "schema_version": 5,
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
        {"id": "stats", "enabled": False, "mode": "compact", "order": 55, "max_rows": 40, "selected_stats": ["Damage", "Attack Speed", "Luck", "XP Gain"], "background_opacity": 0.0, "show_border": False, "show_header": True, "short_stat_labels": True},
        {"id": "kps", "enabled": False, "mode": "compact", "order": 60, "selected_kps_metrics": ["current", "minute_avg", "five_minute_avg", "run_avg"], "background_opacity": 0.0, "show_border": False, "show_header": False},
        {"id": "build_progression", "enabled": False, "order": 65, "max_rows": 6, "scale": 1.0, "show_completed": False, "background_opacity": 0.4, "show_border": True, "show_header": False},
        {"id": "banishes", "enabled": False, "mode": "compact", "order": 80, "max_rows": 40, "background_opacity": 0.0, "show_border": False, "show_header": True},
        # Its own copy of both toggles rather than mirroring the in-game
        # widget's. Not duplication: "show it to chat but not to me" has to be
        # expressible, and a stream scene and a game HUD have genuinely
        # different space budgets, so the layout choice cannot be shared either.
        {"id": "luck_rarity", "enabled": False, "mode": "compact", "order": 70, "background_opacity": 0.0, "show_border": False, "show_header": True, "show_bar": True, "show_expected": True, "expected_layout": "column"},
    ],
    "tracked_items_source": "custom",
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
        # Off by default: on a stream scene the status card is noise. When the
        # game is restarting the overlay holds the last good frame instead, and
        # the app log carries the line a streamer would actually act on.
        "show_status": False,
    },
}

DEFAULT_IN_GAME_OVERLAY = {
    "enabled": False,
    "auto_start": False,
    "widgets": {
        "scanner": {"enabled": True, "x": 10, "y": 10, "scale": 1.0},
        "item_cooldowns": {"enabled": False, "x": 10, "y": 190, "scale": 1.0},
        "recording": {"enabled": True, "x": 150, "y": 10, "scale": 1.0},
        "kps": {"enabled": True, "x": 10, "y": 40, "scale": 1.0, "metrics": ["instant"]},
        "powerups": {"enabled": True, "x": 10, "y": 70, "scale": 1.0},
        # `show_expected` and `expected_layout` have a deliberate twin on the
        # OBS overlay's `luck_rarity` widget above rather than one shared
        # setting: "show it to chat but not to me" has to be expressible, and
        # the two surfaces have different space budgets. `column` is the
        # default on both, because someone
        # enabling the frame for the first time should meet the readable form --
        # a cramped first impression gets the whole frame switched back off.
        "luck_rarity": {
            "enabled": True,
            "x": 10,
            "y": 100,
            "scale": 1.0,
            "show_bar": True,
            "show_expected": False,
            "expected_layout": "column",
        },
        "stats": {"enabled": False, "x": 10, "y": 130, "scale": 1.0, "selected_stats": ["Damage", "Difficulty", "XP Gain", "Luck"]},
        "event_timer": {"enabled": False, "x": 10, "y": 160, "scale": 1.0, "warning_seconds": 15},
        "build_progression": {"enabled": False, "x": 10, "y": 190, "scale": 1.0, "max_rows": 5, "show_completed": False},
    }
}


DEFAULT_BUILD_PROGRESSION = {
    "schema_version": 3,
    "builds": [],
    "active_build_id": None,
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
    # Opt-in, like `luck`, `chests` and `presets` below. This one writes in a
    # voice -- a streamer should choose that deliberately rather than discover
    # their bot doing Gollum in chat.
    "one_ring_announcements": False,
    "commands_announcements": False,
    "commands_announcement_interval_minutes": 30,
    "commands": {
        "stats": True,
        "session": True,
        "bans": True,
        "items": True,
        "weapons": True,
        "tomes": True,
        "chaos": True,
        "stages": True,
        "powerups": True,
        "kps": True,
        "build": True,
        "scanner": True,
        "chests": False,
        # Opt-in like the three above it. `!luck` answers nothing at all unless
        # the app was attached from the run's start, so a streamer who has not
        # chosen it would meet it as a command that mostly says half a line.
        "luck": False,
        "presets": False,
        "bonkhelp": True,
        "disabled": False
    },
    "selected_stats": [
        "Damage", "XP Gain", "Luck", "Difficulty",
        "Powerup Drop Chance", "Elite Spawn Increase",
        "Powerup Multiplier", "Size"
    ],
    "highlighted_disabled_items": [],
    "tracked_items_source": "custom",
    "tracked_items": [],
    "templates": {
        "stats": "Live Stats: DMG: {Damage} | XP: {XP Gain} | Luck: {Luck} | Size: {Size}",
        "session": "{resets} resets, {seeds} seeds found ({seed_rate}%) | Tracked Items: {items}",
        "bans": "Bans ({count}): {items}",
        "items": "Items ({count}): {items}",
        "weapons": "Weapons: {weapons}",
        "tomes": "Tomes: {tomes}",
        "chaos": "Chaos Tome Lv{level}: {chaos}",
        "stages": "{stages}",
        "powerups": "Powerups: {powerups} (PM {pm})",
        "kps": "KPS: {kps} | 60s Avg: {minute_avg} | 5m Avg: {five_minute_avg} | Run Avg: {run_avg}",
        "build": "{name} · {progress}{requirements}{remaining_suffix}",
        "scanner": "Download it here: {github_url} | Support the creator here: {patreon_url} | Try !bonkhelp.",
        "chests": "Chests: {stages} | Total: {opened}/{total} | Paid: {paid} | Key Procs: {procs}/{normal} ({proc_rate}) | Expected: {expected} | Free Chests: {free} | Keys: {keys} ({chance})",
        "luck": "Luck: {tiers}",
        "bonkhelp": "Available commands: {commands_list}",
        "disabled": "Disabled Items: {items}",
        "stage_announcement": "🚩 Stage {stage} completed! Kills: {kills} | Time: {time}. Moving to Stage {next_stage}! 🚩",
        "stage_announcement_simple": "🚩 Moving to Stage {next_stage}! 🚩",
        # The two One Ring pools: one phrase per line, drawn from a shuffle bag
        # so a repeat cannot land next to itself. Newline-separated rather than
        # a list because every template here is coerced with `str()` below, and
        # a one-line value -- which is what shipped first -- is a valid pool of
        # one, so no migration is needed.
        #
        # Tags: {streamer}, {stage}, {time}, {count}. Unknown tags render as
        # `--` through `SafeFormatter` rather than breaking the announcement.
        # `{streamer}` is deliberately kept in most of these even though the bot
        # usually posts from the streamer's own account (`target_channel` falls
        # back to `username`), which makes a third-person line read as the
        # streamer describing themselves. Every line that uses it here is in
        # Gollum's voice, where naming the ring-bearer is the character talking
        # rather than self-reference; the two lines that had a plain narrator
        # say it were cut for exactly that reason.
        "one_ring_announcement": (
            "Filthy, tricksy viewerssss want to steal it... But The One Ring is ours now!\n"
            "Ssss... our precioussss! {streamer} found our precious! *gollum-gollum*\n"
            "Ash nazg durbatuluk... One Ring to rule them all, One Ring to find them!\n"
            "We wants it. We needs it. We must has the precious... and {streamer} has it.\n"
            "The Ring has left Gollum. It has left Bilbo. It has chosen {streamer} on Stage {stage}.\n"
            "It does not stay lost. It wanted to be found -- and at {time} it found {streamer}."
        ),
        # Every line here must hold for *any* count above one. "A second
        # precious" reads as a bug on the third ring, so a line either says
        # {count} or says nothing about the number at all.
        "one_ring_duplicate_announcement": (
            "Another precious?! There is only supposed to be ONE, that is the whole name!\n"
            "Ring number {count}. At this point Sauron should file a complaint.\n"
            "We has {count} preciouseses now. Greedy, greedy {streamer}.\n"
            "{count} Rings to rule them all. The lore is ruined and {streamer} does not care.\n"
            "The precious has friends now. We does not like friends."
        )
    },
    # Which announcer lines were used most recently, per template key. Runtime
    # state rather than a setting, and persisted deliberately: the pools exist
    # so a phrase does not repeat, and The One Ring turns up about once a
    # session -- an in-memory memory would be cleared before it was ever
    # consulted, leaving a plain uniform draw.
    "announcer_recent_lines": {}
}

# Superseded One Ring pools. A config holding exactly one of these was written
# by a build rather than edited by hand, so it is upgraded to the current pool
# instead of pinning old wording -- and, for the first entry, instead of leaving
# a pool of one, which reads as "the randomiser does not work".
#
# **Every entry here predates the first release of this announcer** and exists
# only for configs written by development builds. They can all be deleted the
# release after this one ships; a genuinely edited pool is never byte-identical
# to a default.
LEGACY_ONE_RING_TEMPLATES = {
    # v1: one phrase, before the field became a pool.
    "Filthy, tricksy viewerssss want to steal it... But The One Ring is ours now!",
    # v2: the first eight-line pool.
    (
        "Filthy, tricksy viewerssss want to steal it... But The One Ring is ours now!\n"
        "Ssss... our precioussss! {streamer} found our precious! *gollum-gollum*\n"
        "Ash nazg durbatuluk... One Ring to rule them all, One Ring to find them!\n"
        "{streamer} has found The One Ring. Keep it secret. Keep it safe.\n"
        "We wants it. We needs it. We must has the precious... and {streamer} has it.\n"
        "Not with ten thousand viewers could you do this. It must be {streamer}.\n"
        "The Ring has left Gollum. It has left Bilbo. It has chosen {streamer} on Stage {stage}.\n"
        "It does not stay lost. It wanted to be found -- and at {time} it found {streamer}."
    ),
    # v3: the same pool with {streamer} written out of it.
    (
        "Filthy, tricksy viewerssss want to steal it... But The One Ring is ours now!\n"
        "Ssss... our precioussss! {streamer} found our precious! *gollum-gollum*\n"
        "Ash nazg durbatuluk... One Ring to rule them all, One Ring to find them!\n"
        "The One Ring. Keep it secret. Keep it safe. Especially from chat.\n"
        "We wants it. We needs it. We must has the precious... and now we HAS it.\n"
        "Not with ten thousand viewers could you take it from us.\n"
        "The Ring has left Gollum. It has left Bilbo. On Stage {stage} it chose us.\n"
        "It does not stay lost. It wanted to be found -- and at {time} it was."
    ),
}

LEGACY_ONE_RING_DUPLICATE_TEMPLATES = {
    # v2: the pool with {streamer} written out of it. The v1 text is the
    # current default again, so it is deliberately absent -- listing it would
    # make the upgrade a no-op that reads as a rule.
    (
        "Another precious?! There is only supposed to be ONE, that is the whole name!\n"
        "Ring number {count}. At this point Sauron should file a complaint.\n"
        "We has {count} preciouseses now. Greedy, greedy.\n"
        "{count} Rings to rule them all. The lore is ruined and nobody cares.\n"
        "The precious has friends now. We does not like friends."
    ),
}

LEGACY_TWITCH_SCANNER_TEMPLATES = {
    "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} | Try !stats, !bans, !items, !weapons, !tomes, !stages.",
    "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} | Try !stats, !bans, !items, !weapons, !tomes, !stages, !powerups.",
    "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} | Try !stats, !bans, !items, !weapons, !tomes, !chaos, !stages, !powerups.",
    "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} | Try !stats, !bans, !items, !weapons, !tomes, !chaos, !stages, !powerups. Aliases: !bonkstats, !banishes, !tracked, !chaostome.",
    "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} | Try !stats, !bans, !items, !weapons, !tomes, !chaos, !stages, !powerups, !chests. Aliases: !bonkstats, !banishes, !tracked, !chaostome.",
    "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} | Try !stats, !session, !bans, !items, !weapons, !tomes, !chaos, !stages, !powerups, !chests, !presets, !disabled, !bonkhelp.",
    "This channel is using BonkScanner for live gameplay stats tracking! Download it here: {patreon_url} or GitHub: {github_url} | Try !stats, !session, !bans, !items, !weapons, !tomes, !chaos, !stages, !powerups, !chests, !presets, !disabled, !bonkhelp.",
}

LEGACY_TWITCH_CHESTS_TEMPLATES = {
    "Chests opened: {opened}/{total} | Keys: {keys} (Proc Chance: {chance})",
    "Chests opened: {opened}/{total} | Keys: {keys} (Proc Chance: {chance}) | Free chest: {procs}",
    "Chests: {stages} | Total: {opened}/{total} | Paid: {paid} | Key Procs: {procs}/{normal} ({proc_rate}) | Free Chests: {free} | Keys: {keys} ({chance})",
    "Chests: {stages} | Total: {opened}/{total} | Paid: {paid} | Key Procs: {procs}/{normal} ({proc_rate}) | Expected: {expected} | Free Chests: {free} | Keys: {keys} ({chance})",
}

LEGACY_TWITCH_POWERUPS_TEMPLATES = {
    "Powerups: Rage/Shield/Coin/Speed {standard_duration}s | Clock {clock_duration}s (PM {pm})",
    "Powerups: none active | Durations: standard {standard_duration}s, clock {clock_duration}s (PM {pm})",
    "Powerups: {powerups} | Durations: standard {standard_duration}s, clock {clock_duration}s (PM {pm})",
}



PATREON_SUPPORT_URL = "https://www.patreon.com/cw/ALuiel"
# The profile, not the shop item it used to be. `/s/34dc062a82` is a
# pay-what-you-want listing and did work, but a button captioned "Ko-fi"
# under the words "if it is useful to you" opening a product page reads as
# a purchase rather than a tip -- and the footer popup put those two things
# side by side, which the settings card never did.
KOFI_SUPPORT_URL = "https://ko-fi.com/aluiel"
GITHUB_REPOSITORY_URL = "https://github.com/ALuiell/BonkScanner/releases"
DISCORD_SUPPORT_URL = "https://discord.gg/dYkcrMCJWM"

# ==========================================
# GAME CONFIG PARSER
# ==========================================
@dataclass(frozen=True)
class GameConfigUpdateResult:
    success: bool
    reason: str = ""


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


#: How much longer than the game's own `quick_reset_time` we hold the key. The
#: game stores the bare threshold; holding for exactly that races input and
#: animation timing at the boundary, so every value crossing this seam carries
#: the margin. Read adds it (`get_game_reset_time`), write removes it
#: (`reset_hold_duration_to_game_value`) -- they are one pair and must not drift
#: apart. Advanced users may override the shared value in BonkScanner's config.
DEFAULT_RESET_HOLD_SAFETY_MARGIN = 0.05
MIN_RESET_HOLD_DURATION = 0.10
MAX_RESET_HOLD_SAFETY_MARGIN = 1.00
RESET_HOLD_SAFETY_MARGIN = DEFAULT_RESET_HOLD_SAFETY_MARGIN


def get_game_reset_time() -> float | None:
    """The game's `quick_reset_time`, plus the safety margin. None if unreadable."""
    try:
        data = load_game_config()
        if data is not None:
            quick_reset_time = data.get("cfGameSettings", {}).get("quick_reset_time")
            if quick_reset_time is not None:
                return float(quick_reset_time) + RESET_HOLD_SAFETY_MARGIN
    except Exception:
        pass
    return None


def reset_hold_duration_to_game_value(hold_duration: float) -> float:
    """Strip the margin back off, for writing into the game's own config."""
    return max(0.01, round(hold_duration - RESET_HOLD_SAFETY_MARGIN, 2))

def update_game_reset_time(game_val: float) -> GameConfigUpdateResult:
    """Write and read back quick_reset_time so the UI never reports a false success."""
    game_config_path = get_game_config_path()
    if not game_config_path or not os.path.exists(game_config_path):
        return GameConfigUpdateResult(
            False,
            "The game config file was not found. Launch the game once so it can create the file.",
        )

    data = load_game_config()
    if data is None:
        return GameConfigUpdateResult(
            False,
            "The game config file could not be read. It may be locked or contain invalid JSON.",
        )

    settings = data.get("cfGameSettings")
    if not isinstance(settings, dict):
        settings = {}
        data["cfGameSettings"] = settings

    expected_value = round(float(game_val), 2)
    settings["quick_reset_time"] = expected_value
    if not save_game_config(data):
        return GameConfigUpdateResult(
            False,
            "Windows did not allow BonkScanner to write to the game config file.",
        )

    verified_data = load_game_config()
    if verified_data is None:
        return GameConfigUpdateResult(
            False,
            "The game config was written but could not be read back for verification.",
        )

    verified_settings = verified_data.get("cfGameSettings")
    actual_value = (
        verified_settings.get("quick_reset_time")
        if isinstance(verified_settings, dict)
        else None
    )
    try:
        actual_value = round(float(actual_value), 2)
    except (TypeError, ValueError, OverflowError):
        return GameConfigUpdateResult(
            False,
            "The saved game config does not contain a valid quick_reset_time value.",
        )

    if actual_value != expected_value:
        return GameConfigUpdateResult(
            False,
            (
                "The game config did not keep the requested quick_reset_time value "
                f"(expected {expected_value:.2f}, found {actual_value:.2f})."
            ),
        )

    return GameConfigUpdateResult(True)

# ==========================================
# LOAD JSON CONFIG
# ==========================================
config_path = os.path.join(application_path, "config.json")
CONFIG_FILE_EXISTED_AT_STARTUP = os.path.isfile(config_path)

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


def get_local_appdata_dir() -> str | None:
    local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_appdata:
        user_profile = os.environ.get("USERPROFILE", "").strip()
        if user_profile:
            local_appdata = os.path.join(user_profile, "AppData", "Local")
    return local_appdata or None


def get_legacy_native_hook_root() -> str | None:
    local_appdata = get_local_appdata_dir()
    if not local_appdata:
        return None
    return os.path.join(local_appdata, "BonkScanner")


def _is_path_within(parent_path: str, child_path: str) -> bool:
    try:
        parent_real = os.path.realpath(parent_path)
        child_real = os.path.realpath(child_path)
        return os.path.commonpath([parent_real, child_real]) == parent_real
    except Exception:
        return False


def _collect_legacy_native_hook_directories(saved_dll_path: str | None = None) -> list[str]:
    root_dir = get_legacy_native_hook_root()
    if not root_dir:
        return []

    candidates: list[str] = [os.path.join(root_dir, "native-hook")]
    if saved_dll_path:
        dll_dir = os.path.dirname(saved_dll_path)
        if dll_dir and _is_path_within(root_dir, dll_dir):
            candidates.append(dll_dir)

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized_candidate = os.path.normcase(os.path.normpath(candidate))
        if normalized_candidate not in seen:
            seen.add(normalized_candidate)
            normalized.append(candidate)
    return normalized


def cleanup_legacy_native_hook_cache(saved_dll_path: str | None = None) -> None:
    root_dir = get_legacy_native_hook_root()
    if not root_dir:
        return

    for directory in _collect_legacy_native_hook_directories(saved_dll_path):
        if not os.path.isdir(directory):
            continue
        if not _is_path_within(root_dir, directory):
            continue
        try:
            shutil.rmtree(directory)
        except Exception:
            continue

    try:
        if os.path.isdir(root_dir) and not os.listdir(root_dir):
            os.rmdir(root_dir)
    except Exception:
        pass

user_config = load_config()
cleanup_legacy_native_hook_cache(user_config.get("NATIVE_HOOK_DLL_PATH"))

def coerce_nonnegative_int(value, default=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(parsed, 0)


def coerce_float(value, default=0.0):
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(parsed):
        return default
    return parsed


def normalize_reset_hold_safety_margin(value) -> float:
    """Return a finite two-decimal safety margin from the advanced config key."""
    parsed = coerce_float(value, DEFAULT_RESET_HOLD_SAFETY_MARGIN)
    if not 0.0 <= parsed <= MAX_RESET_HOLD_SAFETY_MARGIN:
        return DEFAULT_RESET_HOLD_SAFETY_MARGIN
    return round(parsed, 2)


RESET_HOLD_SAFETY_MARGIN = normalize_reset_hold_safety_margin(
    user_config.get("RESET_HOLD_SAFETY_MARGIN")
)
user_config["RESET_HOLD_SAFETY_MARGIN"] = RESET_HOLD_SAFETY_MARGIN


def resolve_auto_reroll_setup_guide_acknowledged(
    saved_value,
    *,
    config_existed: bool,
) -> bool:
    """Distinguish a new install from an existing config predating the guide."""
    if isinstance(saved_value, bool):
        return saved_value
    return bool(config_existed)


def resolve_stop_scanning_on_player_movement(saved_value) -> bool:
    """Keep an explicit choice; leave the new safety guard off otherwise."""
    return saved_value if isinstance(saved_value, bool) else False


# A missing key means two different things. With no config file it is a genuine
# first launch; in an existing install it predates the guide and must not be
# interrupted by an upgrade. Persisting the resolved value also keeps a first-
# launch dismissal via X/Esc pending when some other startup setting is saved.
AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED = (
    resolve_auto_reroll_setup_guide_acknowledged(
        user_config.get("AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED"),
        config_existed=CONFIG_FILE_EXISTED_AT_STARTUP,
    )
)
user_config["AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED"] = (
    AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED
)


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


def _unique_build_name(name, used_names):
    base = str(name or "Build Progression").strip() or "Build Progression"
    candidate = base
    suffix = 2
    while candidate.casefold() in used_names:
        candidate = f"{base} ({suffix})"
        suffix += 1
    used_names.add(candidate.casefold())
    return candidate


def normalize_build_definition_config(value, *, regenerate_ids=False, build_id=None):
    """Normalize one build without knowing which library contains it."""
    source = value if isinstance(value, dict) else {}
    normalized = {
        "id": str(build_id or source.get("id") or uuid4().hex),
        "name": str(source.get("name") or "Build Progression").strip() or "Build Progression",
        "deadlines_enabled": bool(source.get("deadlines_enabled", True)),
        "requirements": [],
    }
    seen: set[tuple[str, str]] = set()
    seen_ids: set[str] = set()
    for order, raw in enumerate(source.get("requirements") or ()):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        target = str(raw.get("target") or "").strip()
        if kind not in {"item", "stat", "progress"} or not target or (kind, target) in seen:
            continue
        if kind == "stat" and target not in ALL_STAT_LABELS:
            continue
        if kind == "progress" and target not in PROGRESS_TARGETS:
            continue
        try:
            required = float(raw.get("required"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(required) or required <= 0:
            continue
        if kind in {"item", "progress"} and not required.is_integer():
            continue
        deadline_raw = raw.get("deadline") if isinstance(raw.get("deadline"), dict) else {}
        deadline_kind = str(deadline_raw.get("kind") or "none").lower()
        if deadline_kind not in {"none", "stage_start", "stage_overtime"}:
            deadline_kind = "none"
        stage = None
        seconds = None
        if deadline_kind in {"stage_start", "stage_overtime"}:
            stage = coerce_nonnegative_int(deadline_raw.get("stage"), 0)
            if deadline_kind == "stage_start" and stage not in {2, 3}:
                deadline_kind = "none"
                stage = None
            elif deadline_kind == "stage_overtime":
                stage = max(1, min(4, stage or 1))
        if deadline_kind == "stage_overtime":
            seconds = max(0.0, coerce_float(deadline_raw.get("seconds"), 0.0))
        requirement_id = str(raw.get("id") or "").strip()
        if regenerate_ids or not requirement_id or requirement_id in seen_ids:
            requirement_id = uuid4().hex
        seen.add((kind, target))
        seen_ids.add(requirement_id)

        # --- Second target: Max for items, Ideal for stats ---
        max_required_value = None
        if kind in {"item", "stat"}:
            raw_max = raw.get("max_required")
            if raw_max is not None:
                try:
                    max_required_value = float(raw_max)
                except (TypeError, ValueError):
                    max_required_value = None
                if max_required_value is not None:
                    if (
                        not math.isfinite(max_required_value)
                        or max_required_value <= 0
                        or max_required_value < required
                        or (kind == "item" and not max_required_value.is_integer())
                    ):
                        max_required_value = None
                    elif kind == "item":
                        max_required_value = int(max_required_value)

        # --- cap_tracking (supported items only) ---
        cap_tracking = False
        if kind == "item":
            from core.build_progression import CAP_SUPPORTED_ITEMS
            if target in CAP_SUPPORTED_ITEMS:
                cap_tracking = bool(raw.get("cap_tracking", False))
            if cap_tracking:
                required = 1  # force min=1 for cap-tracked items

        requirement_entry = {
            "id": requirement_id,
            "kind": kind,
            "target": target,
            "required": int(required) if kind in {"item", "progress"} else required,
            "deadline": {"kind": deadline_kind, "stage": stage, "seconds": seconds},
            "order": order,
        }
        if max_required_value is not None:
            requirement_entry["max_required"] = max_required_value
        if cap_tracking:
            requirement_entry["cap_tracking"] = True
        normalized["requirements"].append(requirement_entry)
    return normalized


def normalize_build_progression_config(value):
    """Return the schema-v3 build library; legacy single-build data is discarded."""
    source = value if isinstance(value, dict) else {}
    if coerce_nonnegative_int(source.get("schema_version"), 0) != 3:
        return {"schema_version": 3, "builds": [], "active_build_id": None}
    raw_builds = source.get("builds")
    if not isinstance(raw_builds, list):
        return {"schema_version": 3, "builds": [], "active_build_id": None}

    builds = []
    used_ids: set[str] = set()
    used_names: set[str] = set()
    for raw in raw_builds:
        if not isinstance(raw, dict):
            continue
        build_id = str(raw.get("id") or "").strip()
        if not build_id or build_id in used_ids:
            build_id = uuid4().hex
        build = normalize_build_definition_config(raw, build_id=build_id)
        build["name"] = _unique_build_name(build["name"], used_names)
        used_ids.add(build_id)
        builds.append(build)

    requested_active = str(source.get("active_build_id") or "").strip()
    active_build_id = requested_active if requested_active in used_ids else None
    if builds and active_build_id is None:
        active_build_id = builds[0]["id"]
    return {
        "schema_version": 3,
        "builds": builds,
        "active_build_id": active_build_id,
    }


def normalize_overlay_config(value):
    overlay = _merge_dict_defaults(value, DEFAULT_OVERLAY)
    saved_schema_version = coerce_nonnegative_int((value or {}).get("schema_version"), 1) if isinstance(value, dict) else 0
    if saved_schema_version < DEFAULT_OVERLAY["schema_version"]:
        overlay["style"] = _merge_dict_defaults(overlay.get("style"), DEFAULT_OVERLAY["style"])
    
    overlay["widgets"] = _normalize_overlay_widgets(overlay.get("widgets"))

    # We forcefully reset max_rows to 40 for stats and banishes in case they were saved as 8/12 in the past
    # so that the grid can expand properly without backend limitation.
    for widget in overlay["widgets"]:
        if widget.get("id") == "build_progression":
            widget["enabled"] = bool(widget.get("enabled", False))
            widget["max_rows"] = max(1, min(coerce_nonnegative_int(widget.get("max_rows"), 6) or 6, 20))
            widget["scale"] = max(0.5, min(coerce_float(widget.get("scale"), 1.0), 3.0))
            widget["show_completed"] = bool(widget.get("show_completed", False))
            legacy_mode = widget.pop("mode", None)
            if legacy_mode in {"full", "compact", "text"}:
                widget["show_header"] = legacy_mode == "full"
                widget["background_opacity"] = 0.0 if legacy_mode == "text" else 0.4
                widget["show_border"] = legacy_mode != "text"
            # A detached widget used to be observed as 0×0 while the editor
            # replaced its markup after changing max rows. The server correctly
            # clamped that invalid write to 60×40, but that size is unusable for
            # Build Progression. Clear the exact legacy artefact once so the
            # widget returns to its natural, content-sized frame.
            if (
                coerce_nonnegative_int(widget.get("width"), -1) == 60
                and coerce_nonnegative_int(widget.get("height"), -1) == 40
            ):
                widget.pop("width", None)
                widget.pop("height", None)
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
    overlay["tracked_items_source"] = normalize_tracked_items_source(
        overlay.get("tracked_items_source"),
        default="custom",
    )
    overlay["tracked_items"] = normalize_tracked_item_rules_config(
        overlay.get("tracked_items"),
        DEFAULT_OVERLAY["tracked_items"],
    )
    if not isinstance(overlay.get("style"), dict):
        overlay["style"] = dict(DEFAULT_OVERLAY["style"])
    return overlay

def normalize_in_game_overlay_config(value):
    overlay = _merge_dict_defaults(value, DEFAULT_IN_GAME_OVERLAY)
    overlay["enabled"] = bool(overlay.get("enabled", False))
    overlay["auto_start"] = bool(overlay.get("auto_start", False))
    
    widgets = overlay.get("widgets", {})
    if not isinstance(widgets, dict):
        widgets = {}
    
    for key, default_widget in DEFAULT_IN_GAME_OVERLAY["widgets"].items():
        if key not in widgets or not isinstance(widgets[key], dict):
            widgets[key] = dict(default_widget)
        else:
            widgets[key] = _merge_dict_defaults(widgets[key], default_widget)
            widgets[key]["enabled"] = bool(widgets[key].get("enabled", True))
            widgets[key]["x"] = coerce_nonnegative_int(widgets[key].get("x"), default_widget["x"])
            widgets[key]["y"] = coerce_nonnegative_int(widgets[key].get("y"), default_widget["y"])
            widgets[key]["scale"] = max(
                0.5,
                min(
                    coerce_float(widgets[key].get("scale"), default_widget["scale"]),
                    3.0,
                ),
            )
            if key == "luck_rarity":
                widgets[key]["show_bar"] = bool(widgets[key].get("show_bar", default_widget.get("show_bar", True)))
                widgets[key]["show_expected"] = bool(
                    widgets[key].get("show_expected", default_widget.get("show_expected", False))
                )
                widgets[key]["expected_layout"] = (
                    widgets[key].get("expected_layout")
                    if widgets[key].get("expected_layout") in ("column", "row")
                    else default_widget.get("expected_layout", "column")
                )
            
            if key == "stats":
                selected_stats_val = widgets[key].get("selected_stats")
                if not isinstance(selected_stats_val, list):
                    selected_stats_val = list(selected_stats_val) if isinstance(selected_stats_val, (tuple, set)) else []
                valid_stats = [s for s in selected_stats_val if s in ALL_STAT_LABELS]
                widgets[key]["selected_stats"] = valid_stats or ["Damage", "Difficulty", "XP Gain", "Luck"]
            
            if key == "event_timer":
                widgets[key]["warning_seconds"] = max(
                    1,
                    min(
                        coerce_nonnegative_int(
                            widgets[key].get("warning_seconds"),
                            default_widget.get("warning_seconds", 15)
                        ),
                        300
                    )
                )

            if key == "build_progression":
                widgets[key]["max_rows"] = max(
                    1,
                    min(coerce_nonnegative_int(widgets[key].get("max_rows"), 5) or 5, 20),
                )
                widgets[key]["show_completed"] = bool(widgets[key].get("show_completed", False))
                # Deadline and ITEMS/STATS columns are part of the compact HUD
                # grammar now, not optional decorations.
                widgets[key].pop("show_target_time", None)
                widgets[key].pop("show_section_headings", None)
            
            if key == "kps":
                metrics_val = widgets[key].get("metrics")
                if not isinstance(metrics_val, list):
                    metrics_val = [metrics_val] if metrics_val else []
                # Support migrating legacy mode to metrics list
                if not metrics_val and "mode" in widgets[key]:
                    legacy_mode = widgets[key]["mode"]
                    if legacy_mode == "instant":
                        metrics_val = ["instant"]
                    elif legacy_mode == "60s":
                        metrics_val = ["60s"]
                    elif legacy_mode == "5m":
                        metrics_val = ["5m"]
                    elif legacy_mode == "run":
                        metrics_val = ["run"]
                
                # Filter valid metrics
                valid_metrics = [m for m in metrics_val if m in {"instant", "60s", "5m", "run"}]
                widgets[key]["metrics"] = valid_metrics or ["instant"]
    
    overlay["widgets"] = widgets
    return overlay


def normalize_tracked_items_source(value, *, default="custom"):
    source = str(value or default).strip().lower()
    if source not in {"custom", "session"}:
        source = default
    return source


def normalize_tracked_item_rules_config(value, default_rules=()):
    raw_rules = value if isinstance(value, list) else list(default_rules)
    normalized_rules = []
    for raw_rule in raw_rules or ():
        if not isinstance(raw_rule, dict):
            continue
        raw_item_names = raw_rule.get("item_names")
        if raw_item_names is None:
            raw_item_names = raw_rule.get("items")
        if raw_item_names is None and raw_rule.get("item_name"):
            raw_item_names = [raw_rule.get("item_name")]
        item_names = []
        for name in raw_item_names or ():
            item_name = str(name).strip()
            if item_name and item_name not in item_names:
                item_names.append(item_name)
        if not item_names:
            continue
        mode = str(raw_rule.get("mode") or "all_run")
        default_label = " + ".join(item_names)
        normalized_rules.append(
            {
                "id": str(raw_rule.get("id") or "_".join(item_names).lower()),
                "label": str(raw_rule.get("label") or default_label),
                "item_names": item_names,
                "mode": mode,
            }
        )
        for optional_key in ("before_stage", "before_seconds", "max_copies"):
            if optional_key in raw_rule:
                normalized_rules[-1][optional_key] = raw_rule[optional_key]
    return normalized_rules


def normalize_session_tracked_items_config(value):
    session_cfg = _merge_dict_defaults(value, DEFAULT_SESSION_TRACKED_ITEMS)
    session_cfg["tracked_items"] = normalize_tracked_item_rules_config(
        session_cfg.get("tracked_items"),
        DEFAULT_SESSION_TRACKED_ITEMS["tracked_items"],
    )
    return session_cfg


def normalize_twitch_bot_config(value):
    raw_commands_cfg = value.get("commands") if isinstance(value, dict) and isinstance(value.get("commands"), dict) else None
    raw_templates_cfg = value.get("templates") if isinstance(value, dict) and isinstance(value.get("templates"), dict) else None
    legacy_bonkhelp_enabled = None
    legacy_bonkhelp_template = None
    if raw_commands_cfg is not None and "bonkhelp" not in raw_commands_cfg and "commands" in raw_commands_cfg:
        legacy_bonkhelp_enabled = bool(raw_commands_cfg.get("commands"))
    if raw_templates_cfg is not None and "bonkhelp" not in raw_templates_cfg and "commands" in raw_templates_cfg:
        legacy_bonkhelp_template = str(raw_templates_cfg.get("commands"))

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
    bot_cfg["one_ring_announcements"] = bool(bot_cfg.get("one_ring_announcements", False))

    recent_lines = bot_cfg.get("announcer_recent_lines")
    if not isinstance(recent_lines, dict):
        recent_lines = {}
    bot_cfg["announcer_recent_lines"] = {
        str(key): [str(line) for line in value if str(line).strip()]
        for key, value in recent_lines.items()
        if isinstance(value, (list, tuple))
    }
    bot_cfg["commands_announcements"] = bool(bot_cfg.get("commands_announcements", False))
    bot_cfg["commands_announcement_interval_minutes"] = min(
        1440,
        max(1, coerce_nonnegative_int(bot_cfg.get("commands_announcement_interval_minutes"), 30)),
    )
    bot_cfg.pop("chests_expected_enabled", None)

    if isinstance(bot_cfg.get("commands"), dict):
        bot_cfg["commands"].pop("commands", None)
        if legacy_bonkhelp_enabled is not None:
            bot_cfg["commands"]["bonkhelp"] = legacy_bonkhelp_enabled
    
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

    bot_cfg["tracked_items_source"] = normalize_tracked_items_source(
        bot_cfg.get("tracked_items_source"),
        default="custom",
    )
    bot_cfg["tracked_items"] = normalize_tracked_item_rules_config(
        bot_cfg.get("tracked_items"),
        DEFAULT_TWITCH_BOT["tracked_items"],
    )

    # Normalize templates
    if not isinstance(bot_cfg.get("templates"), dict):
        bot_cfg["templates"] = dict(DEFAULT_TWITCH_BOT["templates"])
    else:
        if legacy_bonkhelp_template is not None:
            bot_cfg["templates"]["bonkhelp"] = legacy_bonkhelp_template
        bot_cfg["templates"].pop("commands", None)
        bot_cfg["templates"] = _merge_dict_defaults(bot_cfg["templates"], DEFAULT_TWITCH_BOT["templates"])
        for k in DEFAULT_TWITCH_BOT["templates"]:
            bot_cfg["templates"][k] = str(bot_cfg["templates"].get(k, DEFAULT_TWITCH_BOT["templates"][k]))
    if bot_cfg["templates"].get("scanner") in LEGACY_TWITCH_SCANNER_TEMPLATES:
        bot_cfg["templates"]["scanner"] = DEFAULT_TWITCH_BOT["templates"]["scanner"]
    if bot_cfg["templates"].get("chests") in LEGACY_TWITCH_CHESTS_TEMPLATES:
        bot_cfg["templates"]["chests"] = DEFAULT_TWITCH_BOT["templates"]["chests"]
    if bot_cfg["templates"].get("powerups") in LEGACY_TWITCH_POWERUPS_TEMPLATES:
        bot_cfg["templates"]["powerups"] = DEFAULT_TWITCH_BOT["templates"]["powerups"]
    if bot_cfg["templates"].get("one_ring_announcement") in LEGACY_ONE_RING_TEMPLATES:
        bot_cfg["templates"]["one_ring_announcement"] = (
            DEFAULT_TWITCH_BOT["templates"]["one_ring_announcement"]
        )
    if (
        bot_cfg["templates"].get("one_ring_duplicate_announcement")
        in LEGACY_ONE_RING_DUPLICATE_TEMPLATES
    ):
        bot_cfg["templates"]["one_ring_duplicate_announcement"] = (
            DEFAULT_TWITCH_BOT["templates"]["one_ring_duplicate_announcement"]
        )

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

# Min Reroll Delay was removed. Drop both its current and legacy keys from
# existing user configs the next time the normalized config is saved.
user_config.pop("MIN_DELAY", None)
user_config.pop("MAP_LOAD_DELAY", None)

#: Used only when neither user config nor the game config can supply a value.
DEFAULT_RESET_HOLD_DURATION = 0.4


def resolve_reset_hold_duration(
    stored_value,
    game_floor: float | None,
) -> tuple[float, float | None]:
    """Return the hold to use, and the value it was raised from (or None).

    The game's threshold is a **floor, not an equality**. Holding the reset key
    longer than `quick_reset_time` still restarts the run -- only holding it
    shorter never does -- so a hold the user deliberately raised stays raised,
    and only a value that drifted *below* the threshold is pulled back up.
    `game_floor` already carries the 0.05 s safety margin; see
    `get_game_reset_time`.

    That drift was otherwise unrepairable from inside the app. The caller reads
    the game config only when `RESET_HOLD_DURATION` is *absent* from user
    config, and the key is written back on every save, so after the first save
    the game config was never consulted again for the life of the install.
    Before v2.1.7 the settings dialog saved this value even when the matching
    write to the game config had silently failed, leaving those installs holding
    the key for less time than the game requires: the reset never fires, the map
    never changes, and the scanner sits in `wait_for_map_ready` until it times
    out with "Map took too long to load".
    """
    if stored_value is not None:
        duration = coerce_float(stored_value, DEFAULT_RESET_HOLD_DURATION)
    elif game_floor is not None:
        duration = game_floor
    else:
        duration = DEFAULT_RESET_HOLD_DURATION

    duration = max(MIN_RESET_HOLD_DURATION, duration)

    if game_floor is not None and round(duration, 2) < round(game_floor, 2):
        return game_floor, round(duration, 2)
    return duration, None


# Load RESET_HOLD_DURATION from user_config first, fallback to game config,
# fallback to the default -- then hold it to the game's floor either way.
GAME_RESET_HOLD_FLOOR = get_game_reset_time()
RESET_HOLD_DURATION, RESET_HOLD_DURATION_RAISED_FROM = resolve_reset_hold_duration(
    user_config.get("RESET_HOLD_DURATION"),
    GAME_RESET_HOLD_FLOOR,
)


def refresh_reset_hold_duration() -> float | None:
    """Re-read the game's threshold and re-apply the floor. Callable any time.

    Import is too early to be the only check. It can run before the game is
    even launched, and the game rewrites its own config as it exits -- so a
    hold that matched at startup can be too short by the time a run begins.
    A hold shorter than the game's threshold means the reset key never restarts
    the run at all: the map never changes, and the scanner ends every iteration
    in "Map took too long to load".

    Returns the value the hold was raised *from*, or None when nothing moved --
    so a caller that runs on every scan start logs once per real change rather
    than once per scan.
    """
    global GAME_RESET_HOLD_FLOOR, RESET_HOLD_DURATION, RESET_HOLD_DURATION_RAISED_FROM

    GAME_RESET_HOLD_FLOOR = get_game_reset_time()
    # Resolve against the live value, not the stored one: they agree (both the
    # dialog and import write both), and the live one is what the next reroll
    # will actually hold for.
    RESET_HOLD_DURATION, RESET_HOLD_DURATION_RAISED_FROM = resolve_reset_hold_duration(
        RESET_HOLD_DURATION,
        GAME_RESET_HOLD_FLOOR,
    )
    if RESET_HOLD_DURATION_RAISED_FROM is not None:
        user_config["RESET_HOLD_DURATION"] = round(RESET_HOLD_DURATION, 2)
        save_config(user_config)
    return RESET_HOLD_DURATION_RAISED_FROM


def reset_hold_duration_notice(raised_from: float | None) -> str | None:
    """The one wording for "we raised your hold", shared by both callers."""
    if raised_from is None:
        return None
    return (
        f"[*] Reset Hold Duration was {raised_from:.2f}s, below the game's quick reset "
        f"threshold. Raised to {RESET_HOLD_DURATION:.2f}s so restarts register."
    )


HOTKEY = user_config.get("HOTKEY", "f6")
HOTKEY_GAME_KEY_WHITELIST = normalize_hotkey_game_key_whitelist(
    user_config.get("HOTKEY_GAME_KEY_WHITELIST", DEFAULT_HOTKEY_GAME_KEY_WHITELIST)
)
PLAYER_STATS_RECORD_HOTKEY = user_config.get("PLAYER_STATS_RECORD_HOTKEY", "f8")
IN_GAME_OVERLAY_EDIT_HOTKEY = user_config.get("IN_GAME_OVERLAY_EDIT_HOTKEY", "f9")
PLAYER_STATS_RECORD_INTERVAL_SECONDS = coerce_nonnegative_int(
    user_config.get("PLAYER_STATS_RECORD_INTERVAL_SECONDS", 30),
    30,
) or 30
def resolve_fast_tracker_interval_ms(config_data: dict) -> int:
    """Read the renamed fast-refresh interval, accepting the legacy config key."""
    legacy_value = config_data.get("CHAOS_TOME_TRACKER_INTERVAL_MS", 500)
    return max(
        100,
        coerce_nonnegative_int(
            config_data.get("FAST_TRACKER_INTERVAL_MS", legacy_value), 500
        )
        or 500,
    )


FAST_TRACKER_INTERVAL_MS = resolve_fast_tracker_interval_ms(user_config)
AUTO_START_RECORDING = bool(user_config.get("AUTO_START_RECORDING", False))
SHOW_OBS_REMINDER_ON_START_SCANNER = bool(user_config.get("SHOW_OBS_REMINDER_ON_START_SCANNER", False))
STOP_SCANNING_ON_PLAYER_MOVEMENT = resolve_stop_scanning_on_player_movement(
    user_config.get("STOP_SCANNING_ON_PLAYER_MOVEMENT")
)
LEFT_RAIL_COLLAPSED = bool(user_config.get("LEFT_RAIL_COLLAPSED", False))
MENU_HOTKEY = user_config.get("MENU_HOTKEY", "home")
RESET_HOTKEY = user_config.get("RESET_HOTKEY", "r")
PROCESS_NAME = user_config.get("PROCESS_NAME", "Megabonk.exe")
TOTAL_REROLLS = coerce_nonnegative_int(user_config.get("TOTAL_REROLLS", 0))

# Load ignored updates
SKIPPED_UPDATE_VERSION = user_config.get("SKIPPED_UPDATE_VERSION", "")

def normalize_templates_config(value) -> list[dict]:
    """Keep an intentional empty list; default only missing/invalid values."""
    if isinstance(value, list):
        return value
    return [dict(template) for template in DEFAULT_TEMPLATES]


# A missing/invalid value means first run and receives the shipped defaults.
# An empty list is different: users may intentionally remove every template,
# so it must survive a restart rather than silently resurrecting the defaults.
TEMPLATES = normalize_templates_config(user_config.get("TEMPLATES"))


#: Default templates whose colour *tag* changed, as `name -> (old tag, new tag)`.
#: Only tags need to be here. The three defaults that kept their tag and changed
#: meaning through the template palette are picked up by every existing config
#: for free, which is most of why the palette was split rather than repainted.
_RENAMED_TEMPLATE_COLORS = {
    "PERFECT+": ("LIGHTRED_EX", "ORANGE"),
}


def _migrate_template_colors(templates) -> bool:
    """Move a stored default template onto its new colour tag.

    `TEMPLATES` is read from `config.json` and written back on every launch, so
    a change to `DEFAULT_TEMPLATES` alone reaches nobody who has ever run the
    app -- their list was saved with the old tag and is never re-read from the
    defaults.

    Deliberately narrow: it rewrites a template only when **both** its name and
    its current colour still match the shipped default. A PERFECT+ someone has
    already recoloured by hand is left alone, and so is any template of their
    own that happens to be `LIGHTRED_EX`. Same shape as the legacy Twitch
    template migrations above -- and, like those, it runs before the config is
    written back, so it persists on the first launch and costs nothing after.
    """
    changed = False
    for template in templates:
        if not isinstance(template, dict):
            continue
        rename = _RENAMED_TEMPLATE_COLORS.get(str(template.get("name") or "").upper())
        if rename is None:
            continue
        old_tag, new_tag = rename
        if str(template.get("color") or "").upper() != old_tag:
            continue
        template["color"] = new_tag
        changed = True
    return changed


_migrate_template_colors(TEMPLATES)

# Load active templates, default to all if not present
ACTIVE_TEMPLATES = user_config.get("ACTIVE_TEMPLATES")
if ACTIVE_TEMPLATES is None:
    ACTIVE_TEMPLATES = [t["name"] for t in TEMPLATES]


EVALUATION_MODE = user_config.get("EVALUATION_MODE", "templates")
SCORES_SYSTEM = user_config.get("SCORES_SYSTEM", DEFAULT_SCORES_SYSTEM)
if not SCORES_SYSTEM:
    SCORES_SYSTEM = DEFAULT_SCORES_SYSTEM
OVERLAY = normalize_overlay_config(user_config.get("OVERLAY"))
IN_GAME_OVERLAY = normalize_in_game_overlay_config(user_config.get("IN_GAME_OVERLAY"))
SESSION_TRACKED_ITEMS = normalize_session_tracked_items_config(user_config.get("SESSION_TRACKED_ITEMS"))
TWITCH_BOT = normalize_twitch_bot_config(user_config.get("TWITCH_BOT"))
BUILD_PROGRESSION = normalize_build_progression_config(user_config.get("BUILD_PROGRESSION"))

# Populate missing default keys for scores system from older config versions
for key, value in DEFAULT_SCORES_SYSTEM.items():
    if key not in SCORES_SYSTEM:
        SCORES_SYSTEM[key] = value

def calculate_auto_thresholds(current_weights: dict, current_multipliers: dict) -> dict:
    """Scale thresholds from positive shrine points on a reference map.

    Penalties deliberately do not lower automatic targets: otherwise making a
    shrine more undesirable would also make every tier easier to reach and
    partially cancel the configured penalty.
    """
    w_moai = max(float(current_weights.get("moais", 3.0)), 0.0)
    w_shady = max(float(current_weights.get("shady", 2.0)), 0.0)
    w_boss = max(float(current_weights.get("boss", 1.0)), 0.0)
    w_magnet = max(float(current_weights.get("magnet", 0.5)), 0.0)
    w_challenges = max(float(current_weights.get("challenges", 0.0)), 0.0)
    
    m_2 = max(float(current_multipliers.get("microwave", {}).get("2", 1.25)), 0.0)
    
    # Reference map: moai=3, shady=3, boss=2, magnet=2, challenges=2,
    # microwave=2. Challenges default to zero, preserving existing thresholds.
    new_score_ref = (
        3 * w_moai
        + 3 * w_shady
        + 2 * w_boss
        + 2 * w_magnet
        + 2 * w_challenges
    ) * m_2
    
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
user_config["RESET_HOLD_DURATION"] = round(RESET_HOLD_DURATION, 2)
user_config["HOTKEY"] = HOTKEY
user_config["HOTKEY_GAME_KEY_WHITELIST"] = HOTKEY_GAME_KEY_WHITELIST
user_config["PLAYER_STATS_RECORD_HOTKEY"] = PLAYER_STATS_RECORD_HOTKEY
user_config["IN_GAME_OVERLAY_EDIT_HOTKEY"] = IN_GAME_OVERLAY_EDIT_HOTKEY
user_config["PLAYER_STATS_RECORD_INTERVAL_SECONDS"] = PLAYER_STATS_RECORD_INTERVAL_SECONDS
user_config["FAST_TRACKER_INTERVAL_MS"] = FAST_TRACKER_INTERVAL_MS
user_config["AUTO_START_RECORDING"] = AUTO_START_RECORDING
user_config["SHOW_OBS_REMINDER_ON_START_SCANNER"] = SHOW_OBS_REMINDER_ON_START_SCANNER
user_config["STOP_SCANNING_ON_PLAYER_MOVEMENT"] = STOP_SCANNING_ON_PLAYER_MOVEMENT
user_config["LEFT_RAIL_COLLAPSED"] = LEFT_RAIL_COLLAPSED
user_config["MENU_HOTKEY"] = MENU_HOTKEY
user_config["RESET_HOTKEY"] = RESET_HOTKEY
user_config["PROCESS_NAME"] = PROCESS_NAME
user_config["TOTAL_REROLLS"] = TOTAL_REROLLS
user_config["TEMPLATES"] = TEMPLATES
user_config["ACTIVE_TEMPLATES"] = ACTIVE_TEMPLATES
user_config["SKIPPED_UPDATE_VERSION"] = SKIPPED_UPDATE_VERSION
user_config["EVALUATION_MODE"] = EVALUATION_MODE
user_config["SCORES_SYSTEM"] = SCORES_SYSTEM
user_config["OVERLAY"] = OVERLAY
user_config["IN_GAME_OVERLAY"] = IN_GAME_OVERLAY
user_config["SESSION_TRACKED_ITEMS"] = SESSION_TRACKED_ITEMS
user_config["TWITCH_BOT"] = TWITCH_BOT
user_config.pop("NATIVE_HOOK_ENABLED", None)
user_config.pop("NATIVE_HOOK_GAME_SETTING_HOTKEYS_ENABLED", None)
user_config.pop("NATIVE_HOOK_DLL_PATH", None)
user_config.pop("TOGGLE_SKIP_CHEST_ANIMATION_HOTKEY", None)
user_config.pop("TOGGLE_AUTO_SELECT_UPGRADES_HOTKEY", None)
user_config.pop("TOGGLE_PARTICLES_OPACITY_HOTKEY", None)
user_config.pop("CHAOS_TOME_TRACKER_INTERVAL_MS", None)


# If the config.json file did not exist initially (or did not contain TEMPLATES),
# we immediately save the current structure to disk so that the user has something to edit.
save_config(user_config)
