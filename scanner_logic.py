from __future__ import annotations

from game_data import EItem, MapStat
import logic


REQUIRED_SHADY_GUY_ITEMS = frozenset(
    {
        EItem.SoulHarvester.name,
    }
)


def item_name(item: object) -> str:
    return str(getattr(item, "name", item))


def has_required_shady_guy_item(
    items: list[object],
    required_items: frozenset[str] = REQUIRED_SHADY_GUY_ITEMS,
) -> bool:
    return any(item_name(item) in required_items for item in items)


def shady_guy_count(raw_stats: dict[object, object], stats: dict[str, int]) -> int:
    shady_stat = raw_stats.get(MapStat.SHADY_GUY)
    shady_count = getattr(shady_stat, "max", shady_stat) if shady_stat is not None else stats.get("Shady Guy", 0)
    try:
        return max(int(shady_count), 0)
    except (TypeError, ValueError):
        return 0


def format_stats(stats: dict, scores_config: dict) -> str:
    shady = stats.get("Shady Guy", 0)
    moai = stats.get("Moais", 0)
    microwaves = logic.normalize_microwaves(stats.get("Microwaves"))
    boss = stats.get("Boss Curses", 0)
    magnet = stats.get("Magnet Shrines", 0)
    score = logic.calculate_score(stats, scores_config)
    return (
        f"Shady: {shady}, Moai: {moai}, Microwaves: {microwaves}, Boss: {boss}, "
        f"Magnet: {magnet}, Score: {score:.1f}"
    )


def calculate_map_score(stats: dict, scores_config: dict) -> float:
    return logic.calculate_score(stats, scores_config)


def evaluate_candidate(
    stats: dict,
    evaluation_mode: str,
    active_templates: list[str],
    templates: list[dict],
    scores_config: dict,
) -> dict | None:
    if evaluation_mode == "templates":
        return logic.find_matching_template(stats, active_templates, templates)
    return logic.evaluate_map_by_scores(stats, scores_config)
