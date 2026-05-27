from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import run_summary
from gui_styles import COLOR_MAP, ITEM_RARITY_COLOR_MAP
from live_run_tracker import LiveRunTracker


@dataclass(frozen=True)
class OverlayState:
    status: str
    updated_at: float
    run_id: str | None
    current_stage: int
    run_timer_label: str
    mob_kills: int | None
    player_level: int | None
    chests_per_minute: float | None
    widgets: dict[str, Any]
    tracked_items: list[dict[str, Any]]
    stage_summary: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "updated_at": self.updated_at,
            "run_id": self.run_id,
            "current_stage": self.current_stage,
            "run_timer_label": self.run_timer_label,
            "mob_kills": self.mob_kills,
            "player_level": self.player_level,
            "chests_per_minute": self.chests_per_minute,
            "widgets": self.widgets,
            "tracked_items": self.tracked_items,
            "stage_summary": self.stage_summary,
        }


def build_overlay_state(tracker: LiveRunTracker, overlay_config: dict[str, Any] | None = None) -> dict[str, Any]:
    overlay_config = overlay_config or {}
    snapshot = tracker.latest_snapshot()
    status = tracker.status()
    widgets = _widget_config_by_id(overlay_config)
    state = OverlayState(
        status=status,
        updated_at=tracker.clock(),
        run_id=tracker.run_id,
        current_stage=tracker.current_stage_index,
        run_timer_label=_format_timer(getattr(snapshot, "game_time_seconds", None)),
        mob_kills=_coerce_optional_int(getattr(snapshot, "mob_kills", None)),
        player_level=_coerce_optional_int(getattr(snapshot, "player_level", None)),
        chests_per_minute=_coerce_optional_float(getattr(snapshot, "chests_per_minute", None)),
        widgets=widgets,
        tracked_items=tracker.tracked_item_rows(),
        stage_summary=_overlay_stage_summary_rows(tracker.stage_summary_rows()),
    )
    data = state.to_dict()
    data["template"] = str(overlay_config.get("template") or "compact")
    data["poll_ms"] = _coerce_poll_ms(overlay_config.get("poll_ms"))
    data["style"] = dict(overlay_config.get("style") or {})
    data["items"] = _snapshot_items(snapshot, overlay_config)
    data["weapons"] = _snapshot_weapons(snapshot)
    data["items_available"] = bool(getattr(snapshot, "items_available", False))
    data["weapons_available"] = bool(getattr(snapshot, "weapons_available", False))
    return data


def _widget_config_by_id(overlay_config: dict[str, Any]) -> dict[str, Any]:
    widgets: dict[str, Any] = {}
    for index, raw_widget in enumerate(overlay_config.get("widgets") or ()):
        if not isinstance(raw_widget, dict):
            continue
        widget_id = str(raw_widget.get("id") or "").strip()
        if not widget_id:
            continue
        widgets[widget_id] = {
            "id": widget_id,
            "enabled": bool(raw_widget.get("enabled", True)),
            "mode": str(raw_widget.get("mode") or "compact"),
            "order": _coerce_int(raw_widget.get("order"), default=(index + 1) * 10),
            "max_rows": _coerce_int(raw_widget.get("max_rows"), default=4),
        }
    return widgets


def _overlay_stage_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    overlay_rows: list[dict[str, Any]] = []
    for row in rows:
        label = str(row.get("label") or "--").replace("Stage ", "")
        item_rarities = row.get("item_rarities")
        if not isinstance(item_rarities, dict):
            item_rarities = run_summary.empty_item_rarity_totals()
        overlay_rows.append(
            {
                "stage": label,
                "time": str(row.get("time") or "--"),
                "kills": str(row.get("kills") or "--"),
                "items": _overlay_item_rarity_counts(item_rarities),
            }
        )
    return overlay_rows


def _overlay_item_rarity_counts(item_rarities: dict[str, Any]) -> list[dict[str, Any]]:
    counts: list[dict[str, Any]] = []
    for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
        count = _coerce_int(item_rarities.get(rarity), default=0)
        if count <= 0:
            continue
        counts.append(
            {
                "rarity": rarity,
                "count": count,
                "color": ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"]),
            }
        )
    return counts


def _snapshot_items(snapshot: Any, overlay_config: dict[str, Any]) -> list[str]:
    if snapshot is None:
        return []
    max_items = 12
    for raw_widget in overlay_config.get("widgets") or ():
        if isinstance(raw_widget, dict) and raw_widget.get("id") == "items":
            max_items = _coerce_int(raw_widget.get("max_rows"), default=max_items)
    return [str(item) for item in tuple(getattr(snapshot, "items", ()) or ())[:max_items]]


def _snapshot_weapons(snapshot: Any) -> list[dict[str, Any]]:
    if snapshot is None:
        return []
    weapons = []
    for weapon in tuple(getattr(snapshot, "weapons", ()) or ()):
        upgraded_stats = []
        for stat_id in getattr(weapon, "upgrade_stat_ids", ()) or ():
            stat = getattr(weapon, "upgraded_stats", {}).get(stat_id)
            if stat is None:
                continue
            upgraded_stats.append(
                {
                    "label": str(getattr(stat, "label", "")),
                    "value": str(getattr(stat, "display_value", "--")),
                }
            )
        weapons.append(
            {
                "name": str(getattr(weapon, "name", "Unknown Weapon")),
                "level": _coerce_int(getattr(weapon, "level", 0)),
                "stats": upgraded_stats[:3],
            }
        )
    return weapons


def _format_timer(seconds: float | None) -> str:
    if seconds is None:
        return "--"
    return run_summary.format_elapsed_time(seconds)


def _coerce_poll_ms(value: Any) -> int:
    return max(250, min(_coerce_int(value, default=500), 5000))


def _coerce_optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default