from __future__ import annotations

from game_data import MapStat, StatValue

STAT_LABELS = (
    "Boss Curses",
    "Challenges",
    "Charge Shrines",
    "Chests",
    "Greed Shrines",
    "Magnet Shrines",
    "Microwaves",
    "Moais",
    "Pots",
    "Shady Guy",
)

MAP_STAT_TO_LABEL = {
    MapStat.BOSS_CURSES: "Boss Curses",
    MapStat.CHALLENGES: "Challenges",
    MapStat.CHARGE_SHRINES: "Charge Shrines",
    MapStat.CHESTS: "Chests",
    MapStat.GREED_SHRINES: "Greed Shrines",
    MapStat.MAGNET_SHRINES: "Magnet Shrines",
    MapStat.MICROWAVES: "Microwaves",
    MapStat.MOAIS: "Moais",
    MapStat.POTS: "Pots",
    MapStat.SHADY_GUY: "Shady Guy",
}


def empty_runtime_stats() -> dict[str, int]:
    return {label: 0 for label in STAT_LABELS}


def adapt_map_stats(stats: dict[MapStat, StatValue]) -> dict[str, int]:
    runtime_stats = empty_runtime_stats()

    for stat, value in stats.items():
        label = MAP_STAT_TO_LABEL.get(stat)
        if label is None:
            continue
        runtime_stats[label] = value.max

    return runtime_stats
