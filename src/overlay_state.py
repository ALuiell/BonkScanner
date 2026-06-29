from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import run_summary
from gui_styles import COLOR_MAP, ITEM_RARITY_COLOR_MAP
from live_run_tracker import LiveRunTracker


DEFAULT_STATS_WIDGET_LABELS = ("Damage", "Attack Speed", "Luck", "XP Gain")


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
    tracker_state = tracker.state_snapshot()
    snapshot = tracker_state.latest_snapshot
    widgets = _widget_config_by_id(overlay_config)
    state = OverlayState(
        status=tracker_state.status,
        updated_at=tracker_state.updated_at,
        run_id=tracker_state.run_id,
        current_stage=tracker_state.current_stage_index,
        run_timer_label=_format_timer(getattr(snapshot, "game_time_seconds", None)),
        mob_kills=_coerce_optional_int(getattr(snapshot, "mob_kills", None)),
        player_level=_coerce_optional_int(getattr(snapshot, "player_level", None)),
        chests_per_minute=_coerce_optional_float(getattr(snapshot, "chests_per_minute", None)),
        widgets=widgets,
        tracked_items=_overlay_tracked_item_rows(tracker_state.tracked_items, overlay_config),
        stage_summary=_overlay_stage_summary_rows(tracker_state.stage_summary),
    )
    data = state.to_dict()
    data["template"] = str(overlay_config.get("template") or "compact")
    data["poll_ms"] = _coerce_poll_ms(overlay_config.get("poll_ms"))
    data["canvas_width"] = _coerce_int(overlay_config.get("canvas_width"), default=1920) or 1920
    data["canvas_height"] = _coerce_int(overlay_config.get("canvas_height"), default=1080) or 1080
    data["style"] = dict(overlay_config.get("style") or {})
    data["stats"] = _snapshot_stats(snapshot, widgets)
    data["banishes"] = _snapshot_banishes(snapshot, widgets)
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
            "max_rows": _coerce_int(raw_widget.get("max_rows"), default=40),
            "selected_stats": _selected_stat_labels(raw_widget.get("selected_stats")),
            "background_opacity": _coerce_bounded_float(raw_widget.get("background_opacity"), default=0.0),
            "show_header": bool(raw_widget.get("show_header", True)),
            "x": _coerce_optional_int(raw_widget.get("x")),
            "y": _coerce_optional_int(raw_widget.get("y")),
            "width": _coerce_optional_int(raw_widget.get("width")),
            "height": _coerce_optional_int(raw_widget.get("height")),
            "scale": max(0.4, min(_coerce_optional_float(raw_widget.get("scale")) or 1.0, 4.0)),
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


def _overlay_tracked_item_rows(rows: list[dict[str, Any]], overlay_config: dict[str, Any]) -> list[dict[str, Any]]:
    if "tracked_items" not in overlay_config:
        return rows
    configured_ids = {
        str(rule.get("id") or "")
        for rule in overlay_config.get("tracked_items") or ()
        if isinstance(rule, dict)
    }
    if not configured_ids:
        return []
    return [row for row in rows if str(row.get("id") or "") in configured_ids]


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


def _snapshot_stats(snapshot: Any, widgets: dict[str, Any]) -> list[dict[str, str]]:
    if snapshot is None:
        return []
    stats = getattr(snapshot, "stats", {}) or {}
    if not isinstance(stats, dict):
        return []
    widget = widgets.get("stats") or {}
    selected_labels = _selected_stat_labels(widget.get("selected_stats"))
    max_rows = _coerce_int(widget.get("max_rows"), default=40)
    rows: list[dict[str, str]] = []
    for label in selected_labels:
        stat = stats.get(label)
        rows.append(
            {
                "label": str(label),
                "value": str(getattr(stat, "display_value", "--") if stat is not None else "--"),
            }
        )
        if len(rows) >= max_rows:
            break
    return rows


def _snapshot_banishes(snapshot: Any, widgets: dict[str, Any]) -> list[str]:
    if snapshot is None:
        return []
    widget = widgets.get("banishes") or {}
    max_rows = _coerce_int(widget.get("max_rows"), default=40)
    return [str(item) for item in tuple(getattr(snapshot, "banishes", ()) or ())[:max_rows]]


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


def _coerce_bounded_float(value: Any, *, default: float = 0.0) -> float:
    try:
        return max(0.0, min(float(value), 1.0))
    except (TypeError, ValueError):
        return default


def _coerce_int(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _selected_stat_labels(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        labels = tuple(str(label).strip() for label in value if str(label).strip())
        if labels:
            return labels
    return DEFAULT_STATS_WIDGET_LABELS