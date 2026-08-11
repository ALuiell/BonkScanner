"""Normalization of the persisted overlay widget configuration.

Step 17b's decision, and why it went this way. `infra/overlay_server.py` used to
reach up into `projections.obs` for the private `_widget_config_by_id`, from
inside the body of `_serve_state` -- a runtime `infra -> projections` edge
against the §2 table, invisible to a header scan, found by step 16's checker.

17b offered two designs and asked for the owner to be decided before any code
moved:

1. widget configuration is a normalized *configuration* value -> expose a
   Qt-free public function below `infra/`;
2. it is part of the HTTP *payload* shape -> let the projection own the whole
   payload and inject the result into the server.

This is (1), and the deciding evidence is behavioural rather than aesthetic.
`_serve_state` does not merely assemble a response: it deliberately *overrides*
`widgets`, `canvas_width` and `canvas_height` on the cached state with settings
re-read at request time. It has to. The overlay editor POSTs new widget geometry
to this same server (`/api/save-widget-positions`), and the browser must see the
result on its next poll rather than waiting for the next tracker update to
refresh the cached payload. Design (2) would either reintroduce that staleness
or force the projection to re-read settings on every HTTP request, pushing I/O
into a layer that is supposed to be pure.

So the normalization is configuration handling, both consumers need exactly the
same rules, and `core/` is the one layer both `projections/` and `infra/` may
import. `projections/obs.py` keeps building the payload; it now imports these
rules downward instead of owning them.

The coercion helpers came along because they are what the normalization is made
of, and moving the function without them would have left projections/obs.py
holding half the definition. They are still used elsewhere in that module, which
now imports them back from here -- a legal projections -> core edge.
"""

from __future__ import annotations

from typing import Any

DEFAULT_STATS_WIDGET_LABELS = ("Damage", "Attack Speed", "Luck", "XP Gain")
DEFAULT_KPS_WIDGET_METRIC_IDS = ("current", "minute_avg", "five_minute_avg", "run_avg")

LUCK_EXPECTED_LAYOUT_IDS = ("column", "row")
DEFAULT_LUCK_EXPECTED_LAYOUT = "column"


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


def _selected_kps_metric_ids(value: Any) -> tuple[str, ...]:
    allowed = set(DEFAULT_KPS_WIDGET_METRIC_IDS)
    if isinstance(value, (list, tuple)):
        metric_ids = tuple(
            str(metric_id).strip()
            for metric_id in value
            if str(metric_id).strip() in allowed
        )
        if metric_ids:
            return metric_ids
    return DEFAULT_KPS_WIDGET_METRIC_IDS


def _luck_expected_layout(value: Any) -> str:
    if isinstance(value, str) and value in LUCK_EXPECTED_LAYOUT_IDS:
        return value
    return DEFAULT_LUCK_EXPECTED_LAYOUT


def widget_config_by_id(overlay_config: dict[str, Any]) -> dict[str, Any]:
    """Normalize the persisted overlay config into per-widget settings by id.

    Public, unlike the `_widget_config_by_id` it replaces: two layers consume it,
    so a leading underscore was never telling the truth.
    """
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
            "selected_kps_metrics": _selected_kps_metric_ids(raw_widget.get("selected_kps_metrics")),
            "background_opacity": _coerce_bounded_float(raw_widget.get("background_opacity"), default=0.0),
            "show_border": bool(raw_widget.get("show_border", False)),
            "show_header": bool(raw_widget.get("show_header", True)),
            # Build Progression only. Keep it in the shared normalization because
            # both the OBS projection and the HTTP server consume this boundary;
            # dropping it here made a persisted checked box arrive as False.
            "show_completed": bool(raw_widget.get("show_completed", False)),
            # Stats-widget only. Defaults to the abbreviated form, which is what
            # the In-Game overlay and the Twitch bot already show; a streamer
            # with room in the scene can switch back to the full stat names.
            "short_stat_labels": bool(raw_widget.get("short_stat_labels", True)),
            # `luck_rarity` only, and its own settings rather than the in-game
            # widget's: the two surfaces are configured apart on purpose.
            "show_bar": bool(raw_widget.get("show_bar", True)),
            "show_expected": bool(raw_widget.get("show_expected", True)),
            "expected_layout": _luck_expected_layout(raw_widget.get("expected_layout")),
            "x": _coerce_optional_int(raw_widget.get("x")),
            "y": _coerce_optional_int(raw_widget.get("y")),
            "width": _coerce_optional_int(raw_widget.get("width")),
            "height": _coerce_optional_int(raw_widget.get("height")),
            "scale": max(0.4, min(_coerce_optional_float(raw_widget.get("scale")) or 1.0, 4.0)),
        }
    return widgets
