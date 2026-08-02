from __future__ import annotations

from html import escape
from typing import Any

from core.stage_rules import (
    GRAVEYARD_STAGE_DURATION_SECONDS,
    XP_GAIN_CAP,
    difficulty_cap,
    stage_duration_seconds,
)
from core.stat_labels import abbreviate_stat_label
from core.item_metadata import ITEM_RARITY_COLOR_MAP
# The rarity roll moved down to core/ when the loot tracker became its second
# consumer -- core/ may not import projections/, and the model was never a
# rendering concern. Both names stay importable from here because every existing
# consumer (the in-game overlay, its window, `tools/replay_loot_expectation.py`)
# reaches for them at this address. The two weight tables did not come with
# them: nothing outside the model itself ever read those.
from core.luck_rarity import (
    LUCK_RARITY_ORDER,
    calculate_luck_rarity_probabilities,
    format_expected_count,
)

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

_KPS_METRICS: dict[str, tuple[str, str]] = {
    "instant": ("current_ui_kps", "KPS"),
    "60s": ("current_minute_avg_kps", "60s"),
    "5m": ("current_five_minute_avg_kps", "5m"),
    "run": ("current_run_avg_kps", "Run"),
}
_STATS_LABEL_MIN_WIDTH_PX = 40
_STATS_LABEL_WIDTH_PER_CHAR_PX = 9
# The Graveyard main map runs a fixed 960 s stage.  `stage_duration_seconds` read
# from CurrentStage -> Timeline -> stageTime is a live timeline marker there, so
# every Graveyard schedule -- the Event Timer and the Difficulty cap alike --
# uses this constant instead of the value carried by the snapshot.
#
# These four names are re-exported rather than defined: `core/stage_rules.py`
# owns them now, because the Recordings scrubber draws the same cap staircase
# over a recorded run and a game constant with two homes drifts silently.
_XP_GAIN_CAP = XP_GAIN_CAP
_GRAVEYARD_STAGE_DURATION_SECONDS = GRAVEYARD_STAGE_DURATION_SECONDS


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


def build_status_indicator_html(label: str, is_active: bool) -> str:
    color = "#22c55e" if is_active else "#ef4444"
    return (
        f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>"
        f"{label} &#9679;</span>"
    )


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


# The grey the `|` separators already use. Expected takes it rather than a
# darker tint of the tier hue, which is unreadable over grass and wood, and
# rather than white, which would outrank the actual figure when the hierarchy
# runs the other way. One grey for all four beats four hand-picked shades.
LUCK_EXPECTED_MUTED_COLOR = "#94a3b8"

LUCK_EXPECTED_LAYOUTS = ("column", "row")
LUCK_EXPECTED_DEFAULT_LAYOUT = "column"

# The minimum centre gap, so cells can never touch at counts the stress test did
# not reach. `column` holds 147 px at `999 (999)` and `row` 8 px, which is where
# this number comes from -- it is the floor `row` is already at, not a guess.
_LUCK_EXPECTED_CELL_PAD_PX = 4
_LUCK_EXPECTED_COLUMN_PAD_PX = 12


def normalize_luck_expected_layout(value: Any) -> str:
    return str(value) if value in LUCK_EXPECTED_LAYOUTS else LUCK_EXPECTED_DEFAULT_LAYOUT


def _luck_expected_cell_html(
    rarity: str,
    actual: Any,
    expected: Any,
    *,
    with_dot: bool,
) -> str:
    """One tier's figures: actual in the tier colour, expected in the grey.

    No rarity words anywhere -- colour carries the tier on both overlays, which
    is what keeps the naming question that governs chat from ever reaching them
    and the two surfaces from being able to disagree.
    """
    color = ITEM_RARITY_COLOR_MAP.get(rarity, FALLBACK_COLOR)
    actual_text = escape(str(max(0, int(actual or 0))))
    expected_text = escape(format_expected_count(expected))
    dot = (
        f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>&#9679;</span> "
        if with_dot
        else ""
    )
    joined = (
        f"({expected_text})" if with_dot else f"/{expected_text}"
    )
    separator = " " if with_dot else ""
    return (
        f"{dot}"
        f"<span style='color: {color}; text-shadow: {TEXT_SHADOW};'>{actual_text}</span>"
        f"{separator}"
        f"<span style='color: {LUCK_EXPECTED_MUTED_COLOR}; text-shadow: {TEXT_SHADOW};'>"
        f"{joined}</span>"
    )


def build_luck_expected_overlay_html(
    actual: dict[str, Any],
    expected: dict[str, Any],
    *,
    layout: str = LUCK_EXPECTED_DEFAULT_LAYOUT,
) -> str:
    """The actual-versus-expected block, in one of the two settled layouts.

    ``column`` is a two-by-two block of ``● 116 (118)``, the dot carrying the
    tier colour; ``row`` is a single line of ``116/118`` per tier with no dots.
    They trade roughly 45 px of screen against legibility -- a real user
    preference rather than an unmade decision -- and share every other rule, so
    the branch is one arm here rather than two builders.

    Either layout **stretches across the widget's width**, first cell flush
    left, last flush right, so growing numbers eat the centre gap instead of
    changing the footprint. ``row`` works without dots precisely because of that
    stretch: at ~38 px the whitespace separates the groups the way the dot does
    in ``column``.

    Nothing here is tied to the bar's segment geometry, and it must not be: the
    bar is proportional, so a tier at 1% is a segment one pixel wide with no
    room under it. Only `LUCK_RARITY_ORDER` and the colours are shared.
    """
    layout = normalize_luck_expected_layout(layout)
    cell_style = (
        f"padding: 0 {_LUCK_EXPECTED_CELL_PAD_PX}px; white-space: nowrap;"
    )

    if layout == "row":
        alignments = ("left", "center", "center", "right")
        cells = "".join(
            f"<td width='25%' align='{alignment}' style='{cell_style}'>"
            f"{_luck_expected_cell_html(rarity, actual.get(rarity), expected.get(rarity), with_dot=False)}"
            "</td>"
            for rarity, alignment in zip(LUCK_RARITY_ORDER, alignments)
        )
        rows = f"<tr>{cells}</tr>"
    else:
        rows = ""
        for index in (0, 2):
            left, right = LUCK_RARITY_ORDER[index], LUCK_RARITY_ORDER[index + 1]
            rows += (
                "<tr>"
                f"<td width='50%' align='left' style='{cell_style} "
                f"padding-right: {_LUCK_EXPECTED_COLUMN_PAD_PX}px;'>"
                f"{_luck_expected_cell_html(left, actual.get(left), expected.get(left), with_dot=True)}"
                "</td>"
                f"<td width='50%' align='right' style='{cell_style} "
                f"padding-left: {_LUCK_EXPECTED_COLUMN_PAD_PX}px;'>"
                f"{_luck_expected_cell_html(right, actual.get(right), expected.get(right), with_dot=True)}"
                "</td>"
                "</tr>"
            )

    return (
        "<table width='100%' cellspacing='0' cellpadding='0' "
        "style='border-collapse: collapse; border-spacing: 0;'>"
        f"{rows}"
        "</table>"
    )


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

        if raw_val is not None:
            if label == "Difficulty":
                # Graveyard carries no stage tier: its raw `stage_index` stays at
                # the value of whatever stage pointer the map reuses (2 in
                # practice), so the tier table below must not be consulted there.
                # One rule covers the whole map -- crypts, main map and boss room
                # alike -- because no phase marker is available to the projection
                # yet.
                cap_stage_duration = (
                    _GRAVEYARD_STAGE_DURATION_SECONDS if is_graveyard else stage_time_seconds
                )
                cap = difficulty_cap(
                    stage_index,
                    stage_timer_seconds,
                    is_graveyard=is_graveyard,
                    cap_stage_duration=cap_stage_duration,
                )

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
    event_stage_duration = stage_duration_seconds(stage_index, is_graveyard=is_graveyard)

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
