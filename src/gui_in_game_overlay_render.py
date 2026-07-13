from __future__ import annotations

from html import escape
from math import isfinite, log
from typing import Any

from gui_styles import ITEM_RARITY_COLOR_MAP
from stat_label_abbreviations import abbreviate_stat_label

TEXT_SHADOW = "-1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000"
POWERUP_COLORS: dict[str, str] = {
    "Rage": "#e879f9",
    "Shield": "#4ade80",
    "Stonks": "#fde047",
    "Clock": "#7dd3fc",
    "Timestomp": "#22d3ee",
}
CRITICAL_COLOR = "#ff4444"
HEADER_COLOR = "#ffffff"
FALLBACK_COLOR = "#d8b4fe"
LUCK_RARITY_BASE_WEIGHTS: dict[str, float] = {
    "COMMON": 70.0,
    "UNCOMMON": 15.0,
    "RARE": 6.0,
    "LEGENDARY": 1.5,
}
LUCK_RARITY_ORDER: tuple[str, ...] = ("LEGENDARY", "RARE", "UNCOMMON", "COMMON")
_LUCK_RARITY_EXPONENTS: dict[str, int] = {
    "COMMON": 3,
    "UNCOMMON": 2,
    "RARE": 1,
    "LEGENDARY": 0,
}

_KPS_METRICS: dict[str, tuple[str, str]] = {
    "instant": ("current_ui_kps", "KPS"),
    "60s": ("current_minute_avg_kps", "60s"),
    "5m": ("current_five_minute_avg_kps", "5m"),
    "run": ("current_run_avg_kps", "Run"),
}
_STATS_LABEL_MIN_WIDTH_PX = 40
_STATS_LABEL_WIDTH_PER_CHAR_PX = 9
_XP_GAIN_CAP = 10.0


def build_kps_overlay_html(run_tracker: Any, metrics_cfg: list[str] | tuple[str, ...]) -> str:
    values = {
        "current": _read_tracker_kps(run_tracker, "current_ui_kps"),
        "minute_avg": _read_tracker_kps(run_tracker, "current_minute_avg_kps"),
        "five_minute_avg": _read_tracker_kps(run_tracker, "current_five_minute_avg_kps"),
        "run_avg": _read_tracker_kps(run_tracker, "current_run_avg_kps"),
    }
    return build_kps_overlay_html_from_values(values, metrics_cfg)


def build_kps_overlay_html_from_values(
    values: dict[str, int | None],
    metrics_cfg: list[str] | tuple[str, ...],
) -> str:
    """Render KPS values supplied by an immutable runtime projection."""
    sep = f"<span style='color: #94a3b8; text-shadow: {TEXT_SHADOW};'> | </span>"
    spans: list[str] = []

    for metric_id in metrics_cfg:
        metric_info = _KPS_METRICS.get(metric_id)
        if metric_info is None:
            continue
        method_name, label = metric_info
        value = values.get(_KPS_VALUE_KEYS[method_name])
        value_text = f"{value}" if value is not None else "--"
        spans.append(
            f"<span style='color: white; text-shadow: {TEXT_SHADOW};'>{label} {value_text}</span>"
        )

    return sep.join(spans)


_KPS_VALUE_KEYS = {
    "current_ui_kps": "current",
    "current_minute_avg_kps": "minute_avg",
    "current_five_minute_avg_kps": "five_minute_avg",
    "current_run_avg_kps": "run_avg",
}


def _read_tracker_kps(run_tracker: Any, method_name: str) -> int | None:
    reader = getattr(run_tracker, method_name, None)
    return reader() if callable(reader) else None


def build_status_indicator_html(label: str, is_active: bool) -> str:
    color = "#22c55e" if is_active else "#ef4444"
    return (
        f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>"
        f"{label} &#9679;</span>"
    )


def build_luck_rarity_overlay_html(snapshot: Any) -> str:
    stats = getattr(snapshot, "stats", None)
    luck_stat = stats.get("Luck") if isinstance(stats, dict) else None
    luck_value = getattr(luck_stat, "value", None)
    probabilities = calculate_luck_rarity_probabilities(luck_value)
    return build_luck_rarity_overlay_html_for_probabilities(probabilities)


def build_luck_rarity_overlay_html_for_probabilities(
    probabilities: dict[str, float | None],
) -> str:

    sep = f"<span style='color: #94a3b8; text-shadow: {TEXT_SHADOW};'> | </span>"
    spans: list[str] = []
    for rarity in LUCK_RARITY_ORDER:
        color = ITEM_RARITY_COLOR_MAP.get(rarity, FALLBACK_COLOR)
        probability = probabilities.get(rarity)
        value_text = "--" if probability is None else f"{probability:.2f}%"
        spans.append(f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>{value_text}</span>")
    return sep.join(spans)


def build_powerups_overlay_html(
    snapshot: Any,
    *,
    edit_mode: bool = False,
    current_run_time_seconds: float | None = None,
) -> str:
    """Build overlay HTML for active powerups.

    Returns an empty string if none are active. In edit mode returns a placeholder
    so the widget stays visible and draggable.
    """
    active = list(getattr(snapshot, "active", None) or [])
    if not active:
        if edit_mode:
            return (
                f"<span style='color: {HEADER_COLOR}; opacity: 0.5; "
                f"text-shadow: {TEXT_SHADOW};'>Powerups (preview)</span>"
            )
        return ""

    pm_display = str(getattr(snapshot, "powerup_multiplier_display", "--") or "--")
    header = f"Powerups (PM {pm_display})" if pm_display != "--" else "Powerups"
    lines = [f"<span style='color: {HEADER_COLOR}; text-shadow: {TEXT_SHADOW};'>{header}</span>"]

    for effect in active:
        name = str(getattr(effect, "name", "?"))
        remaining = max(0.0, float(getattr(effect, "remaining_seconds", 0)))
        pickup_ui = getattr(effect, "pickup_ui", None)
        expires_ui = getattr(effect, "expires_ui", None)
        secs = int(round(remaining))
        time_str = f"{secs}s"

        if pickup_ui is not None and expires_ui is not None:
            detail = f"{pickup_ui} → {expires_ui} ({time_str})"
        else:
            detail = f"({time_str})"

        color = CRITICAL_COLOR if remaining < 5 else POWERUP_COLORS.get(name, FALLBACK_COLOR)
        lines.append(
            f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>"
            f"{name}: {detail}</span>"
        )

    return "<br>".join(lines)


def calculate_luck_rarity_probabilities(luck_value: float | None) -> dict[str, float | None]:
    if luck_value is None:
        return {rarity: None for rarity in LUCK_RARITY_ORDER}
    try:
        luck_value = float(luck_value)
    except (TypeError, ValueError):
        return {rarity: None for rarity in LUCK_RARITY_ORDER}
    if not isfinite(luck_value):
        return {rarity: None for rarity in LUCK_RARITY_ORDER}

    adjusted_luck = max(luck_value, -0.999999999)
    strength = log(adjusted_luck + 1.0) * 1.5

    weights: dict[str, float] = {}
    for rarity, base_weight in LUCK_RARITY_BASE_WEIGHTS.items():
        exponent = _LUCK_RARITY_EXPONENTS[rarity] * strength
        weights[rarity] = base_weight * (1.5 ** (-exponent))

    total_weight = sum(weights.values())
    if total_weight <= 0 or not isfinite(total_weight):
        return {rarity: None for rarity in LUCK_RARITY_ORDER}

    return {
        rarity: (weights[rarity] / total_weight) * 100.0
        for rarity in LUCK_RARITY_ORDER
    }


def _format_stats_display_value(label: str, display_value: Any, raw_value: float | None) -> str:
    if label == "XP Gain" and raw_value is not None and raw_value >= _XP_GAIN_CAP:
        return "10x"
    return str(display_value if display_value not in (None, "") else "--")


def _format_event_clock(remaining_seconds: float) -> str:
    total_seconds = max(0, int(round(float(remaining_seconds))))
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _build_in_game_stats_rows(
    stats: dict[str, Any],
    selected_stats: list[str],
    *,
    stage_index: int,
    stage_timer_seconds: float,
    stage_time_seconds: float,
    is_graveyard: bool,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for label in selected_stats:
        stat = stats.get(label)
        if stat is None:
            continue

        display_val = getattr(stat, "display_value", "--")
        raw_val = getattr(stat, "value", None)
        try:
            raw_val = float(raw_val) if raw_val is not None else None
        except (TypeError, ValueError):
            raw_val = None

        color = "#16e7ff"  # Cyan by default
        cap_suffix = ""

        if not is_graveyard and raw_val is not None:
            if label == "Difficulty":
                is_after_2m_ghosts = stage_timer_seconds >= (stage_time_seconds + 120.0)

                cap = None
                if stage_index == 0:
                    cap = 4.95 if is_after_2m_ghosts else 5.71
                elif stage_index == 1:
                    cap = 4.38 if is_after_2m_ghosts else 5.14
                elif stage_index == 2:
                    cap = 3.81 if is_after_2m_ghosts else 4.57

                if cap is not None:
                    cap_pct = int(round(cap * 100))
                    cap_suffix = f" / {cap_pct}%"
                    if raw_val >= cap:
                        color = "#ff4d4d"  # Red
            elif label == "XP Gain":
                cap_suffix = " / 10x"
                if raw_val >= _XP_GAIN_CAP:
                    color = "#ff4d4d"  # Red

        rows.append(
            {
                "label": label,
                "display_label": abbreviate_stat_label(label),
                "display_value": _format_stats_display_value(label, display_val, raw_val),
                "color": color,
                "cap_suffix": cap_suffix,
            }
        )
    return rows


def _calculate_stats_label_width_px(rows: list[dict[str, str]]) -> int:
    if not rows:
        return _STATS_LABEL_MIN_WIDTH_PX
    max_len = max(len(str(row.get("display_label") or "")) for row in rows)
    return max(_STATS_LABEL_MIN_WIDTH_PX, (max_len + 1) * _STATS_LABEL_WIDTH_PER_CHAR_PX)


def build_stats_overlay_html(
    snapshot: Any,
    selected_stats: list[str],
    stage_index: int,
    stage_timer_seconds: float,
    stage_time_seconds: float,
    is_graveyard: bool,
) -> str:
    if snapshot is None:
        return ""
    stats = getattr(snapshot, "stats", {}) or {}
    if not isinstance(stats, dict):
        return ""
    rows = _build_in_game_stats_rows(
        stats,
        selected_stats,
        stage_index=stage_index,
        stage_timer_seconds=stage_timer_seconds,
        stage_time_seconds=stage_time_seconds,
        is_graveyard=is_graveyard,
    )
    if not rows:
        return ""

    label_width_px = _calculate_stats_label_width_px(rows)
    html_rows = []
    for row in rows:
        display_label = escape(str(row["display_label"]))
        display_value = escape(str(row["display_value"]))
        cap_suffix = escape(str(row["cap_suffix"]))
        color = escape(str(row["color"]))
        html_rows.append(
            "<tr>"
            f"<td width='{label_width_px}' style='width: {label_width_px}px; padding: 0 10px 1px 0; "
            f"color: #ffffff; text-shadow: {TEXT_SHADOW}; white-space: nowrap;'>{display_label}:</td>"
            f"<td style='padding: 0 0 1px 0; color: {color}; text-shadow: {TEXT_SHADOW}; "
            f"white-space: nowrap;'>{display_value}{cap_suffix}</td>"
            "</tr>"
        )

    return (
        "<table cellspacing='0' cellpadding='0' "
        "style='border-collapse: collapse; border-spacing: 0;'>"
        f"{''.join(html_rows)}"
        "</table>"
    )


def build_event_timer_overlay_html(
    stage_index: int,
    stage_timer_seconds: float,
    stage_time_seconds: float,
    is_graveyard: bool,
    warning_seconds: int = 15,
    graveyard_main_map_events_active: bool = False,
    edit_mode: bool = False,
) -> str:
    preview_html = (
        f"<span style='color: {HEADER_COLOR}; opacity: 0.5; "
        f"text-shadow: {TEXT_SHADOW};'>Event Timer (preview)</span>"
    )
    if is_graveyard:
        if not graveyard_main_map_events_active:
            return preview_html if edit_mode else ""
        events = [
            ("boss", 780.0, 0.0),
            ("wave", 720.0, 30.0),
            ("boss", 540.0, 0.0),
            ("wave", 480.0, 30.0),
            ("boss", 360.0, 0.0),
            ("wave", 300.0, 30.0),
            ("boss", 180.0, 0.0),
            ("wave", 120.0, 30.0),
        ]
    else:
        if stage_index not in (0, 1, 2):
            return preview_html if edit_mode else ""
        if stage_index in (0, 1):
            events = [
                ("boss", 420.0, 0.0),
                ("wave", 360.0, 30.0),
                ("wave", 180.0, 30.0),
                ("boss", 120.0, 0.0),
            ]
        else:  # stage_index == 2
            events = [
                ("boss", 390.0, 0.0),
                ("wave", 330.0, 30.0),
                ("wave", 240.0, 30.0),
                ("boss", 180.0, 0.0),
            ]

    # `stage_timer_seconds` is the elapsed MyTime stage timer.  The value read
    # from CurrentStage -> Timeline -> stageTime is a live timeline marker, not
    # the map's total duration, so it must not be used as the countdown base.
    # Event schedules use the fixed duration of the active map stage.
    if is_graveyard:
        event_stage_duration = 960.0
    elif stage_index in (0, 1):
        event_stage_duration = 600.0 if stage_index == 0 else 540.0
    elif stage_index == 2:
        event_stage_duration = 480.0
    else:
        event_stage_duration = 0.0

    remaining_time = event_stage_duration - stage_timer_seconds
    if remaining_time <= 0:
        return preview_html if edit_mode else ""

    # Check active waves first
    for ev_type, start_rem, duration in events:
        if duration > 0.0:
            end_rem = start_rem - duration
            if end_rem <= remaining_time <= start_rem:
                return (
                    f"<span style='color: #ff4d4d; text-shadow: {TEXT_SHADOW}; font-weight: bold;'>"
                    "Wave Active</span>"
                )

    # Check upcoming warnings next
    upcoming_events = []
    for ev_type, start_rem, duration in events:
        if remaining_time > start_rem:
            diff = remaining_time - start_rem
            threshold_seconds = int(warning_seconds)
            if diff <= threshold_seconds:
                upcoming_events.append((diff, ev_type, start_rem))

    if upcoming_events:
        upcoming_events.sort()
        _diff, ev_type, start_rem = upcoming_events[0]
        label = "Boss" if ev_type == "boss" else "Wave"
        event_time = _format_event_clock(start_rem)
        return (
            f"<span style='color: #ff9f1c; text-shadow: {TEXT_SHADOW}; font-weight: bold;'>"
            f"{label} at {event_time}</span>"
        )

    return preview_html if edit_mode else ""
