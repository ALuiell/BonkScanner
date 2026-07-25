from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core import run_summary
from core.tracker.snapshots import RuntimeStateSnapshot
from core.item_metadata import COLOR_MAP, ITEM_RARITY_COLOR_MAP
from core.stat_labels import abbreviate_stat_label
# Overlay-config normalization moved down to core/ in step 17b, so that
# infra/overlay_server.py can consume it without an infra -> projections import.
# The coercion helpers are still used throughout this module.
from core.overlay_config import (
    _coerce_int,
    _coerce_optional_float,
    _coerce_optional_int,
    _luck_expected_layout,
    _selected_stat_labels,
    widget_config_by_id,
)
from core.luck_rarity import (
    LUCK_RARITY_ORDER,
    calculate_luck_rarity_probabilities,
    format_expected_count,
    format_luck_rarity_percent,
)

if TYPE_CHECKING:
    from core.tracker.live_run import LiveRunTracker


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
    kps: dict[str, int | None]

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
            "kps": self.kps,
        }


def build_overlay_state(tracker: LiveRunTracker, overlay_config: dict[str, Any] | None = None) -> dict[str, Any]:
    return build_overlay_state_from_snapshot(tracker.runtime_snapshot(), overlay_config)


def build_overlay_state_from_snapshot(
    runtime: RuntimeStateSnapshot,
    overlay_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Project a runtime snapshot into the stable OBS HTTP payload."""
    overlay_config = overlay_config or {}
    snapshot = runtime.latest_snapshot
    widgets = widget_config_by_id(overlay_config)
    state = OverlayState(
        status=runtime.status,
        updated_at=runtime.updated_at,
        run_id=runtime.run_id,
        current_stage=runtime.current_stage_index,
        run_timer_label=_format_timer(getattr(snapshot, "game_time_seconds", None)),
        mob_kills=_coerce_optional_int(getattr(snapshot, "mob_kills", None)),
        player_level=_coerce_optional_int(getattr(snapshot, "player_level", None)),
        chests_per_minute=_coerce_optional_float(getattr(snapshot, "chests_per_minute", None)),
        widgets=widgets,
        tracked_items=_overlay_tracked_item_rows(list(runtime.tracked_items), overlay_config),
        stage_summary=_overlay_stage_summary_rows(list(runtime.stage_summary)),
        kps=dict(runtime.kps),
    )
    data = state.to_dict()
    data["template"] = str(overlay_config.get("template") or "compact")
    data["poll_ms"] = _coerce_poll_ms(overlay_config.get("poll_ms"))
    data["canvas_width"] = _coerce_int(overlay_config.get("canvas_width"), default=1920) or 1920
    data["canvas_height"] = _coerce_int(overlay_config.get("canvas_height"), default=1080) or 1080
    data["style"] = dict(overlay_config.get("style") or {})
    data["stats"] = _snapshot_stats(snapshot, widgets)
    data["banishes"] = _snapshot_banishes(snapshot, widgets)
    data["luck_rarity"] = _snapshot_luck_rarity(runtime, widgets)
    return data


def _snapshot_luck_rarity(
    runtime: RuntimeStateSnapshot,
    widgets: dict[str, Any],
) -> dict[str, Any]:
    """The Luck widget's payload: chances, counts and both toggles.

    Everything is resolved here rather than in the browser. `projections/` may
    import `core/` only, so this module can reach the rarity model and the
    already-computed summary on the snapshot, and `overlay.js` can reach
    neither -- the renderer gets finished strings and colours and does layout.
    That split is also what keeps the two overlays from drifting: one model, one
    formatter, two renderers.
    """
    widget = widgets.get("luck_rarity") or {}
    loot = getattr(runtime, "loot_stats", None)
    probabilities = calculate_luck_rarity_probabilities(getattr(runtime, "luck", None))
    actual = getattr(loot, "actual", None) or {}
    expected = getattr(loot, "expected", None) or {}
    available = bool(getattr(loot, "available", False))
    return {
        # An unmeasurable run reports itself so, and the renderer drops the
        # block rather than drawing zeros. The chance row stays either way: it
        # depends on the current Luck alone and a late attach cannot spoil it.
        "available": available,
        "show_bar": bool(widget.get("show_bar", True)),
        "show_expected": bool(widget.get("show_expected", True)) and available,
        "expected_layout": _luck_expected_layout(widget.get("expected_layout")),
        "tiers": [
            {
                "rarity": rarity,
                "color": ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"]),
                "chance": probabilities.get(rarity),
                "chance_text": format_luck_rarity_percent(probabilities.get(rarity)),
                "actual": _coerce_int(actual.get(rarity), default=0),
                "expected_text": format_expected_count(expected.get(rarity)),
            }
            for rarity in LUCK_RARITY_ORDER
        ],
    }


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
    use_short_labels = bool(widget.get("short_stat_labels", True))
    rows: list[dict[str, str]] = []
    for label in selected_labels:
        stat = stats.get(label)
        rows.append(
            {
                "label": str(label),
                "display_label": (
                    abbreviate_stat_label(str(label)) if use_short_labels else str(label)
                ),
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


def _overlay_kps_metrics(tracker: LiveRunTracker) -> dict[str, int | None]:
    return {
        "current": _coerce_optional_int(tracker.current_ui_kps()),
        "minute_avg": _coerce_optional_int(tracker.current_minute_avg_kps()),
        "five_minute_avg": _coerce_optional_int(tracker.current_five_minute_avg_kps()),
        "run_avg": _coerce_optional_int(tracker.current_run_avg_kps()),
    }


def _format_timer(seconds: float | None) -> str:
    if seconds is None:
        return "--"
    return run_summary.format_elapsed_time(seconds)


def _coerce_poll_ms(value: Any) -> int:
    return max(250, min(_coerce_int(value, default=500), 5000))


