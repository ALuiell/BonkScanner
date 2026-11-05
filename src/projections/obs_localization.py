"""Browser presentation catalog; runtime values and editor IDs stay canonical."""
from core.localization import Translator
from core.localization_context import message_key
from core.overlay_localization import OVERLAY_MESSAGE_KEYS
from core.stat_labels import STAT_LABEL_ABBREVIATIONS
from core.stats.weapon_tracker import WEAPON_TRACKER_METRICS


OBS_MESSAGES = (
    "Tracked Items", "Stats", "KPS", "Stage Summary", "Banishes", "Luck",
    "Build Progression", "Weapon Tracker", "No Weapon Stats Selected",
    "Waiting for Weapon Data", "No Matching Weapon Stats", "Build not configured",
    "Waiting for live run", "BUILD COMPLETE", "ITEMS", "STATS", "PROGRESS",
    "60s", "5m", "Run", "Stage", "Time", "Kills", "Items", "No banishes yet",
    "+{count} more", "Overlay Layout Editor",
    "Drag widgets to place them anywhere. Close this browser tab when done.",
    "Canvas Resolution:", "Apply", "Decrease Scale", "Increase Scale", "Status",
    "Waiting for live stats...", "widget unavailable", "overlay unavailable",
    "waiting", "reconnecting", "live", "stopped", "game_not_found", "error",
    "Available from the next run", "Waiting for loot data…", "BANISHED",
    "NO DEADLINE", "CAP ACTIVE", "TO IDEAL", "Lv.{level}", "HC", "SC",
    "Player Level", "Mob Kills", "Chests Opened", "Stage Reached",
)


def browser_localization(translator: Translator) -> dict:
    def text(source):
        key = OVERLAY_MESSAGE_KEYS.get(source, message_key(source))
        return translator.message_template(key) if translator.has_text(key) else source

    # Raw format templates are expanded by the browser after escaping at the
    # insertion boundary; no executable HTML or user input is part of this map.
    messages = {source: text(source) for source in OBS_MESSAGES}
    games = {category: translator.game_names(category)
             for category in ("items", "weapons", "tomes", "stats", "rarities")}
    stats = games["stats"]
    if translator.game_language == "en":
        stats = dict(stats)
        stats.update({short: short for short in STAT_LABEL_ABBREVIATIONS.values()})
    else:
        stats.update({short: stats.get(full, full)
                      for full, short in STAT_LABEL_ABBREVIATIONS.items()})
    games["stats"] = stats
    for spec in WEAPON_TRACKER_METRICS.values():
        stats[spec.short_label] = (spec.short_label if translator.game_language == "en"
                                   else stats.get(spec.player_stat_label, spec.player_stat_label))
    return {"language": translator.language, "game_language": translator.game_language,
            "messages": messages, "game": games}
