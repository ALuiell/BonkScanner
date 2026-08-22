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
from core.item_metadata import (
    ITEM_RARITY_BY_NAME,
    ITEM_RARITY_COLOR_MAP,
    normalize_item_name_for_rarity,
)
# The rarity roll moved down to core/ when the loot tracker became its second
# consumer -- core/ may not import projections/, and the model was never a
# rendering concern. Both names stay importable from here because every existing
# consumer (the in-game overlay, its window, `tools/replay_loot_expectation.py`)
# reaches for them at this address. The two weight tables did not come with
# them: nothing outside the model itself ever read those.
from core.luck_rarity import (
    LUCK_RARITY_ORDER,
    format_expected_count,
)

TEXT_SHADOW = "-1px -1px 0 #000, 1px -1px 0 #000, -1px 1px 0 #000, 1px 1px 0 #000"
POWERUP_COLORS: dict[str, str] = {
    # Violet, because the powerup is violet in the game -- the hue is not free
    # to change. Brightness was: this row sat at relative luminance 0.215 while
    # Shield, Stonks, Clock and Timestomp run 0.53-0.75, so Rage was the one
    # line in the block at half its neighbours' brightness and read as muddy
    # over grass and water alike. Now 0.60, just above Clock.
    #
    # The other constraint is Bob's Light, whose cooldown row is RARE and so
    # `#e879f9`. Rage was `#e879f9` itself once, then `#a855f7` to escape it at
    # dE2000 14.7; this is 19.7 from it, so the two are further apart than
    # before rather than merely no worse. Full saturation is deliberate: the
    # better-separated colours in this band were all desaturated periwinkles
    # that drift toward the muted grey and stop reading as a colour at all.
    "Rage": "#d0c4ff",
    "Shield": "#4ade80",
    "Stonks": "#fde047",
    "Clock": "#7dd3fc",
    "Timestomp": "#22d3ee",
}
# One red for "this is the dangerous state", wherever it appears -- powerup and
# cooldown rows about to expire, a stat sitting on its cap, an active wave. It
# used to be `#ff4444` here and `#ff4d4d` at the three cap/wave sites: a
# difference of nine units on one channel, which no eye resolves, so the two
# reds carried a distinction that could not be perceived and therefore did not
# exist. `#ff4d4d` won because it is already `--hud-red` in the OBS overlay's
# stylesheet, which makes the same state the same colour on both surfaces.
CRITICAL_COLOR = "#ff4d4d"
HEADER_COLOR = "#ffffff"


def build_build_progression_overlay_html(payload: dict[str, Any], *, edit_mode: bool = False) -> str:
    """Minimal frameless HUD markup for Qt's limited rich-text renderer.

    This is painted by ``QLabel``, not a browser. Qt rich text supports tables
    and basic inline styles, but not CSS Grid/Flex or ``gap``. Using browser
    layout here concatenates adjacent cells into strings such as
    ``Sucky Magnet--/1T2 +00:00``. Keep this renderer table-only; the OBS
    version can continue using modern CSS in ``overlay.js``.
    """
    if not payload.get("configured"):
        return "<div style='color:#8c96a8'>Build not configured</div>" if edit_mode else ""
    if not payload.get("available"):
        return "<div style='color:#8c96a8'>Waiting for live run</div>" if edit_mode else ""
    shadow = TEXT_SHADOW
    if payload.get("complete"):
        if payload.get("late_complete"):
            return (
                f"<div style='color:#F97316;font-weight:800;text-shadow:{shadow}'>"
                f"! BUILD COMPLETE · {escape(str(payload.get('completion_time') or '--:--'))}</div>"
            )
        return (
            f"<div style='color:#59d890;font-weight:800;text-shadow:{shadow}'>"
            f"✓ BUILD COMPLETE · {escape(str(payload.get('completion_time') or '--:--'))}</div>"
        )
    colors = {
        "unknown": "#8c96a8", "neutral": "#d7dde5", "warning": "#f1c861",
        "overdue": "#ff6f76", "satisfied": "#59d890", "banished": "#A78BFA",
    }
    rows = []
    section_labels = {"item": "ITEMS", "stat": "STATS", "progress": "PROGRESS"}
    last_kind = ""
    for row in payload.get("rows") or ():
        kind = str(row.get("kind") or "")
        if payload.get("show_section_headings") and kind != last_kind:
            rows.append(
                "<tr><td colspan='4' style='padding-top:4px;padding-bottom:2px;'>"
                f"<span style='color:#708096;font-size:9px;text-shadow:{shadow};font-weight:800'>"
                f"{section_labels.get(kind, 'PROGRESS')}</span></td></tr>"
            )
        last_kind = kind
        status = str(row.get("status") or "unknown")
        color = colors.get(status, "#d7dde5")
        is_late = bool(row.get("late"))
        min_in_progress = bool(row.get("min_met")) and not bool(row.get("complete"))
        if is_late:
            symbol_color = "#F97316"
            timing_color = "#F97316"
        elif min_in_progress:
            symbol_color = "#59D890"
            timing_color = "#16E7FF"
        else:
            symbol_color = color
            timing_color = color
        # Unknown already reads as ``--`` in the value column. A leading '?'
        # repeats that fact and looks like corrupt text when every row is still
        # waiting for the first inventory read.
        symbol = (
            ""
            if status in {"unknown", "neutral"} and not is_late and not min_in_progress
            else str(row.get("symbol") or "")
        )
        timing = escape(str(row.get("time") or ""))
        label_color = str(row.get("label_color") or "#d7dde5")
        if not (
            len(label_color) == 7
            and label_color.startswith("#")
            and all(char in "0123456789abcdefABCDEF" for char in label_color[1:])
        ):
            label_color = "#d7dde5"
        label = escape(str(row.get("label") or "--"))
        if row.get("banished"):
            label = f"<s>{label}</s>"
        rows.append(
            "<tr>"
            f"<td width='16' style='color:{symbol_color};text-shadow:{shadow};white-space:nowrap;'>"
            f"<b>{escape(symbol)}</b>&nbsp;</td>"
            f"<td style='color:{label_color};text-shadow:{shadow};white-space:nowrap;'>"
            f"{label}&nbsp;&nbsp;</td>"
            f"<td align='left' style='color:#d7dde5;text-shadow:{shadow};white-space:nowrap;'>"
            f"<b>{escape(str(row.get('value') or '--'))}</b>&nbsp;&nbsp;</td>"
            f"<td align='right' style='color:{timing_color};text-shadow:{shadow};white-space:nowrap;'>"
            f"{timing}</td>"
            "</tr>"
        )
    title = escape(str(payload.get("name") or "Build Progression"))
    progress = escape(str(payload.get("progress") or "0/0"))
    return (
        f"<div style='color:#fff;text-shadow:{shadow};font-weight:700'>"
        f"{title}&nbsp;&middot;&nbsp;{progress}</div>"
        "<table cellspacing='0' cellpadding='0' "
        "style='border-collapse:collapse;border-spacing:0;'>"
        f"{''.join(rows)}</table>"
    )
#: The colour of "this overlay does not recognise this thing" -- an unrecognised
#: powerup, or an item whose rarity the catalog has never heard of.
#:
#: Was `#d8b4fe`, a light lavender, which is dE2000 5.9 from the violet Rage now
#: needs to be legible: an unknown powerup row renders *inside the Powerups
#: block*, directly beside Rage, so those two are the one pair here that is
#: guaranteed to be adjacent. A neutral is also the more honest answer -- not
#: knowing what something is has no hue, and every colour in this palette
#: otherwise means something specific.
FALLBACK_COLOR = "#cbd5e1"

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


#: Below this many seconds remaining, a row switches to `CRITICAL_COLOR`.
#: Matches the powerup rows' threshold so the two blocks mean the same thing by
#: the same colour.
ITEM_COOLDOWN_CRITICAL_SECONDS = 5.0

def item_cooldown_row_color(item_name: str) -> str:
    """A cooldown row's colour: the item's own rarity.

    Not a hand-kept table. `ITEM_RARITY_BY_NAME` already covers 163 items --
    including all three of the timed classes still queued for this widget -- so
    a newly supported item is coloured correctly without a renderer change, and
    there is no second table to drift out of step.

    `item_display_color` looks like the obvious source and is not: its map holds
    exactly **one** entry, Golden Ring, as a special case for the ring
    announcer. Every item routed through it would have come back
    `FALLBACK_COLOR` -- one colour for all of them.

    Rarity colours are the overlay's shared vocabulary rather than this
    widget's: the Luck row, the bar and the expected block already speak them,
    so `#E879F9` means "rare" everywhere it appears. That it also happens to be
    the Rage powerup's colour is a coincidence in the existing palette, not a
    meaning invented here.
    """
    rarity = ITEM_RARITY_BY_NAME.get(normalize_item_name_for_rarity(item_name))
    return ITEM_RARITY_COLOR_MAP.get(rarity, FALLBACK_COLOR)


def build_item_cooldowns_overlay_html(
    projection: Any,
    *,
    edit_mode: bool = False,
) -> str:
    """The countdown to each timed item's next trigger.

    Returns an empty string when there is nothing to show, which the widget
    renders as hidden -- no timed item held is not a state worth a caption. In
    edit mode it returns a placeholder instead, or the widget cannot be grabbed
    with the mouse before the player owns one.

    **The countdown is computed here, from the mark and the clock carried
    together on the projection.** ``next_trigger_time`` is an absolute mark on
    the game's own clock, not a countdown, and the subtraction belongs at paint
    time: the overlay repaints every 500 ms against a 1 s read lane, so a
    remaining time frozen at read time would always be shown stale. Both values
    come from one pass, so the difference is coherent by construction.

    **Nothing is drawn once the run is over.** On the death screen the game
    clock freezes and every read keeps succeeding, so the reading stays fresh
    and the countdown would sit frozen on screen indefinitely -- measured, 256
    consecutive successful reads across 26 s. Freshness cannot detect that;
    only the lifecycle can. The same freeze happens under pause, where holding
    the value *is* correct, which is exactly why the two need separating by
    something other than the reading itself.
    """
    if edit_mode:
        snapshot = getattr(projection, "item_cooldowns", None)
        if snapshot is None or not getattr(snapshot, "readings", ()):
            return (
                f"<span style='color: {HEADER_COLOR}; opacity: 0.5; "
                f"text-shadow: {TEXT_SHADOW};'>Item Cooldowns (preview)</span>"
            )
    elif getattr(projection, "run_completed", False):
        return ""

    snapshot = getattr(projection, "item_cooldowns", None)
    readings = tuple(getattr(snapshot, "readings", ()) or ())
    if not readings:
        return ""

    my_time = getattr(snapshot, "my_time_seconds", None)
    if my_time is None:
        return ""

    lines = [
        f"<span style='color: {HEADER_COLOR}; text-shadow: {TEXT_SHADOW};'>Cooldowns</span>"
    ]
    for reading in readings:
        name = str(getattr(reading, "name", "?"))
        # Clamped at zero: the mark goes briefly negative between a trigger and
        # the pass that observes the re-arm (measured at -0.01 s), and "0s"
        # reads as "about to fire", which is what is happening.
        remaining = max(0.0, float(getattr(reading, "next_trigger_time", 0.0)) - float(my_time))

        colour = (
            CRITICAL_COLOR
            if remaining < ITEM_COOLDOWN_CRITICAL_SECONDS
            else item_cooldown_row_color(name)
        )
        # Truncated, not rounded. `{:.0f}` rounds half to even, which both
        # displays *more* time than remains (26.5 -> 27 under half-up, and
        # inconsistently under half-even: 26.5 -> 26 but 27.5 -> 28) and never
        # shows `0s`. A countdown that overstates its own deadline is the one
        # error mode worth ruling out here, and truncating also makes the final
        # second read `0s`, which is what "about to fire" should look like.
        lines.append(
            f"<span style='color: {colour}; text-shadow: {TEXT_SHADOW};'>"
            f"{escape(name)}: {int(remaining)}s</span>"
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
                        color = CRITICAL_COLOR
            elif label == "XP Gain":
                cap_suffix = " / 10x"
                if raw_val >= _XP_GAIN_CAP:
                    color = CRITICAL_COLOR

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
                    f"<span style='color: {CRITICAL_COLOR}; text-shadow: {TEXT_SHADOW}; "
                    f"font-weight: bold;'>Wave Active</span>"
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
