"""Pure formatting helpers for the player stats and compare runs views.

Moved from ``PlayerStatsMixin`` without behaviour change: every function here is
a pure ``str``/value formatter that never touches widget or client state.
"""

from __future__ import annotations

import html
from math import isfinite

from core import run_summary
from projections.item_sort import (
    ITEM_RARITY_SORT_ORDER,
    ITEM_SORT_DEFAULT,
    ITEM_SORT_RARITY_ASC,
    ITEM_SORT_RARITY_DESC,
)
from core.item_metadata import (
    COLOR_MAP,
    ITEM_RARITY_BY_NAME,
    ITEM_RARITY_COLOR_MAP,
    item_display_color,
    normalize_item_name_for_display,
    normalize_item_name_for_rarity,
)
from core.tracker.chaos import CHAOS_TOME_GAME_STAT_ORDER
from core.tracker.chests import key_proc_chance
from core.stats.types import calculate_chests_per_minute
from projections.metric_table import (
    EMPTY_METRIC_TABLE,
    MetricRow,
    MetricSection,
    MetricTable,
)

COMPARE_RUN_STAT_LABELS = (
    "Damage",
    "Attack Speed",
    "Luck",
    "XP Gain",
    "Difficulty",
    "Powerup Multiplier",
    "Powerup Drop Chance",
)


def _snapshot_compare_time(snapshot) -> float | None:
    game_time = getattr(snapshot, "game_time_seconds", None)
    if game_time is not None:
        return float(game_time)
    elapsed = getattr(snapshot, "elapsed_seconds", None)
    if elapsed is not None:
        return float(elapsed)
    return None


def _item_rarity_totals(items) -> dict[str, int]:
    rarity_totals = {
        "LEGENDARY": 0,
        "RARE": 0,
        "UNCOMMON": 0,
        "COMMON": 0,
    }
    for item_name, count in _item_counts(items).items():
        display_name = _normalize_item_name_for_display(item_name)
        rarity_name = _normalize_item_name_for_rarity(display_name)
        rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
        if rarity in rarity_totals:
            rarity_totals[rarity] += count
    return rarity_totals


def _empty_item_rarity_totals() -> dict[str, int]:
    return {
        "LEGENDARY": 0,
        "RARE": 0,
        "UNCOMMON": 0,
        "COMMON": 0,
    }


def format_items_rarity_summary_rich_text(items) -> str:
    rarity_totals = _item_rarity_totals(items)
    parts: list[str] = []
    for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
        total = rarity_totals.get(rarity, 0)
        if total <= 0:
            continue
        color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
        parts.append(
            f'<span style="color:{color}; font-weight:700;">&#9679;</span> '
            f'<span style="color:#E5E7EB;">{html.escape(str(total))}</span>'
        )
    return "  ".join(parts)


def _item_rarity_rank(item_text: str) -> int:
    item_name, _suffix = _split_item_stack_suffix(item_text)
    display_name = _normalize_item_name_for_display(item_name)
    rarity_name = _normalize_item_name_for_rarity(display_name)
    rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
    return ITEM_RARITY_SORT_ORDER.get(rarity, -1)


def format_duration(seconds: int) -> str:
    return format_elapsed_time(seconds)


def format_elapsed_time(seconds: float | int) -> str:
    minutes, seconds = divmod(max(int(seconds), 0), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_in_game_time(seconds: float | None) -> str:
    if seconds is None:
        return "In-Game Time: --"
    return f"In-Game Time: {format_elapsed_time(seconds)}"


def format_mob_kills(value: int | None, kps: int | None = None) -> str:
    if value is None:
        return "Mob Kills: --"
    formatted_value = format_count(value)
    if kps is not None:
        return f"Mob Kills: {formatted_value} ({format_count(kps)}/s)"
    return f"Mob Kills: {formatted_value}"


def format_kps_averages(
    minute_avg_kps: int | None,
    five_minute_avg_kps: int | None,
) -> str:
    values = []
    for label, value in (
        ("60s", minute_avg_kps),
        ("5m", five_minute_avg_kps),
    ):
        if value is None:
            values.append(f"{label} --")
        else:
            values.append(f"{label} {format_count(value)}/s")
    return f"KPS: {' | '.join(values)}"


def format_count(value: int | float) -> str:
    return f"{max(0, int(value)):,}"


def format_damage_source_value(value: int | float) -> str:
    value = max(0.0, float(value))
    suffixes = (
        "",
        "K",
        "M",
        "B",
        "T",
        "Q",
        "QI",
        "SX",
        "SP",
        "OC",
        "NO",
        "DC",
    )
    if value < 1000:
        return f"{int(round(value)):,}"

    suffix_index = 0
    while value >= 1000.0 and suffix_index < len(suffixes) - 1:
        value /= 1000.0
        suffix_index += 1

    if value >= 100:
        formatted = f"{value:.0f}"
    elif value >= 10:
        formatted = f"{value:.1f}"
    else:
        formatted = f"{value:.2f}"
    return f"{formatted}{suffixes[suffix_index]}"


def format_player_level(value: int | None) -> str:
    if value is None:
        return "Level: --"
    return f"Level: {max(0, int(value))}"


def format_items(items) -> str:
    if not items:
        return "--"
    return ", ".join(items)


def format_compare_run_snapshot_summary(vod, snapshot, index: int) -> str:
    item_total = _snapshot_item_total(snapshot)
    rows = [
        f'<span style="color:#98A7BA;">Snapshot:</span> {index + 1}/{len(vod.snapshots)}',
        f'<span style="color:#98A7BA;">Record Time:</span> {html.escape(snapshot.time_label)}',
        f'<span style="color:#98A7BA;">In-Game:</span> {html.escape(format_in_game_time(getattr(snapshot, "game_time_seconds", None)).replace("In-Game Time: ", ""))}',
        f'<span style="color:#98A7BA;">Kills:</span> {html.escape(format_mob_kills(getattr(snapshot, "mob_kills", None)).replace("Mob Kills: ", ""))}',
        f'<span style="color:#98A7BA;">Level:</span> {html.escape(format_player_level(getattr(snapshot, "player_level", None)).replace("Level: ", ""))}',
        f'<span style="color:#98A7BA;">Items:</span> {format_count(item_total)}',
    ]
    return "<br>".join(rows)


def format_compare_run_selected_stats(snapshot, stat_labels: tuple[str, ...] | None = None) -> str:
    rows: list[str] = []
    for label in stat_labels or COMPARE_RUN_STAT_LABELS:
        stat = getattr(snapshot, "stats", {}).get(label)
        display = stat.display_value if stat is not None else "--"
        rows.append(f'<span style="color:#98A7BA;">{html.escape(label)}:</span> {html.escape(display)}')
    return "<br>".join(rows) if rows else "--"


def format_compare_runs_diff(
    vod_a,
    snapshot_a,
    vod_b,
    snapshot_b,
    *,
    stat_labels: tuple[str, ...] | None = None,
    include_items: bool = False,
    item_details_expanded: bool = False,
    include_weapons: bool = False,
    include_tomes: bool = False,
    include_chaos: bool = False,
) -> str:
    rows = [format_compare_runs_overview_diff(vod_a, snapshot_a, vod_b, snapshot_b)]
    stat_text = format_compare_runs_stats_diff(snapshot_a, snapshot_b, stat_labels=stat_labels)
    if stat_text and stat_text != "--":
        rows.append('<br><span style="color:#E5E7EB; font-weight:700;">Selected Stats</span>')
        rows.append(stat_text)
    if include_items:
        rows.append('<br><span style="color:#E5E7EB; font-weight:700;">Items</span>')
        rows.append(format_compare_runs_items_diff(snapshot_a, snapshot_b, details_expanded=item_details_expanded))
    if include_weapons:
        rows.append('<br><span style="color:#E5E7EB; font-weight:700;">Weapons</span>')
        rows.append(format_compare_runs_weapons_diff(snapshot_a, snapshot_b))
    if include_tomes:
        rows.append('<br><span style="color:#E5E7EB; font-weight:700;">Tomes</span>')
        rows.append(format_compare_runs_tomes_diff(snapshot_a, snapshot_b))
    if include_chaos:
        rows.append('<br><span style="color:#E5E7EB; font-weight:700;">Chaos</span>')
        rows.append(format_compare_runs_chaos_diff(snapshot_a, snapshot_b))
    return "<br>".join(rows)


def format_compare_runs_overview_diff(vod_a, snapshot_a, vod_b, snapshot_b) -> str:
    time_a = _snapshot_compare_time(snapshot_a)
    time_b = _snapshot_compare_time(snapshot_b)
    rows = [
        f'<span style="color:#98A7BA;">A:</span> {html.escape(vod_a.metadata.name)}',
        f'<span style="color:#98A7BA;">B:</span> {html.escape(vod_b.metadata.name)}',
        '<span style="color:#98A7BA;">Mode:</span> Run B compared to Run A',
    ]
    if time_a is not None and time_b is not None:
        rows.append(
            f'<span style="color:#98A7BA;">Time offset:</span> {_format_signed_seconds(time_b - time_a)}'
        )

    kill_delta = _raw_snapshot_int_delta(snapshot_a, snapshot_b, "mob_kills")
    if kill_delta is not None:
        rows.append(f'<span style="color:#98A7BA;">Kill Difference:</span> {_format_signed_count(kill_delta)}')

    level_delta = _raw_snapshot_int_delta(snapshot_a, snapshot_b, "player_level")
    if level_delta is not None:
        rows.append(f'<span style="color:#98A7BA;">Level Difference:</span> {_format_signed_count(level_delta)}')

    item_delta = _snapshot_item_total(snapshot_b) - _snapshot_item_total(snapshot_a)
    rows.append(f'<span style="color:#98A7BA;">Item Difference:</span> {_format_signed_count(item_delta)}')
    return "<br>".join(rows)


def format_compare_runs_stats_diff(snapshot_a, snapshot_b, *, stat_labels: tuple[str, ...] | None = None) -> str:
    stat_rows = _format_compare_run_stat_deltas(snapshot_a, snapshot_b, stat_labels=stat_labels)
    return "<br>".join(stat_rows) if stat_rows else "--"


def format_compare_runs_items_diff(snapshot_a, snapshot_b, *, details_expanded: bool = False) -> str:
    item_rows = _format_compare_run_item_deltas(
        snapshot_a,
        snapshot_b,
        details_expanded=details_expanded,
    )
    return "<br>".join(item_rows) if item_rows else "--"


def format_compare_runs_stage_summary_diff(vod_a, index_a, vod_b, index_b) -> str:
    rows_a = _build_compare_run_stage_summary_rows(vod_a, index_a)
    rows_b = _build_compare_run_stage_summary_rows(vod_b, index_b)
    blocks: list[str] = []
    for row_a, row_b in zip(rows_a, rows_b):
        label = html.escape(str(row_a.get("label", row_b.get("label", "--"))))
        blocks.append(
            "<div style='margin-bottom:10px;'>"
            f"<span style='color:#E5E7EB; font-weight:700;'>{label}</span><br>"
            f"<span style='color:#98A7BA;'>Time:</span> {_format_compare_stage_summary_metric(row_a.get('time', '--'), row_b.get('time', '--'), metric='time')}<br>"
            f"<span style='color:#98A7BA;'>Kills:</span> {_format_compare_stage_summary_metric(row_a.get('kills', '--'), row_b.get('kills', '--'), metric='count')}<br>"
            f"<span style='color:#98A7BA;'>Items:</span> {_format_compare_stage_summary_items(row_a.get('items', '--'), row_b.get('items', '--'))}"
            "</div>"
        )
    return "".join(blocks) if blocks else "--"


#: Shown in place of the sections when a card has nothing to compare. One
#: constant per card so the HTML renderer and the widget renderer cannot drift.
WEAPONS_COMPARE_EMPTY_TEXT = "No weapon data"
TOMES_COMPARE_EMPTY_TEXT = "No tome data"
CHAOS_COMPARE_EMPTY_TEXT = "No Chaos Tome data"


def format_compare_runs_weapons_diff(snapshot_a, snapshot_b) -> str:
    weapon_rows = _format_compare_run_weapon_deltas(snapshot_a, snapshot_b)
    return "<br>".join(weapon_rows) if weapon_rows else "--"


def format_compare_runs_tomes_diff(snapshot_a, snapshot_b) -> str:
    tome_rows = _format_compare_run_tome_deltas(snapshot_a, snapshot_b)
    return "<br>".join(tome_rows) if tome_rows else "--"


def build_compare_runs_weapons_table(snapshot_a, snapshot_b) -> MetricTable:
    """The Weapons card as data: one section per weapon, one row per upgrade.

    Same content as `format_compare_runs_weapons_diff`, and deliberately built
    from the same row helper -- this exists so the card can be rendered by
    widgets rather than by a `QLabel` re-laying-out a 12 KB HTML document per
    scrub frame.
    """
    weapons_a = _index_named_snapshots(getattr(snapshot_a, "weapons", ()))
    weapons_b = _index_named_snapshots(getattr(snapshot_b, "weapons", ()))
    sections = tuple(
        _entity_metric_section(
            name,
            weapons_a.get(name),
            weapons_b.get(name),
            _weapon_compare_metric_rows(weapons_a.get(name), weapons_b.get(name)),
        )
        for name in sorted(set(weapons_a) | set(weapons_b), key=str.casefold)
    )
    return MetricTable(sections=sections, empty_text=WEAPONS_COMPARE_EMPTY_TEXT)


def build_compare_runs_tomes_table(snapshot_a, snapshot_b) -> MetricTable:
    """The Tomes card as data. See `build_compare_runs_weapons_table`."""
    tomes_a = _index_named_snapshots(getattr(snapshot_a, "tomes", ()))
    tomes_b = _index_named_snapshots(getattr(snapshot_b, "tomes", ()))
    sections = tuple(
        _entity_metric_section(
            name,
            tomes_a.get(name),
            tomes_b.get(name),
            _tome_compare_metric_rows(name, tomes_a.get(name), tomes_b.get(name)),
        )
        for name in sorted(set(tomes_a) | set(tomes_b), key=str.casefold)
    )
    return MetricTable(sections=sections, empty_text=TOMES_COMPARE_EMPTY_TEXT)


def build_compare_runs_chaos_table(snapshot_a, snapshot_b) -> MetricTable:
    """The Chaos card as data: an overview section and, if tracked, the stats.

    Chaos's sections are plain tables rather than named entities, so they carry
    a column name in `headers[0]` and no title.
    """
    chaos_a = getattr(snapshot_a, "chaos_tome", None)
    chaos_b = getattr(snapshot_b, "chaos_tome", None)
    if chaos_a is None and chaos_b is None:
        return MetricTable(empty_text=CHAOS_COMPARE_EMPTY_TEXT)

    sections = [
        MetricSection(
            headers=("Metric", "A", "B", "Diff"),
            rows=tuple(MetricRow(*row) for row in _chaos_compare_overview_rows(chaos_a, chaos_b)),
        )
    ]
    stat_rows = _format_compare_run_chaos_stat_rows(chaos_a, chaos_b)
    if stat_rows:
        sections.append(
            MetricSection(
                headers=("Stat", "A", "B", "Diff"),
                rows=tuple(MetricRow(*row) for row in stat_rows),
            )
        )
    return MetricTable(sections=tuple(sections), empty_text=CHAOS_COMPARE_EMPTY_TEXT)


def _entity_metric_section(name: str, value_a, value_b, rows) -> MetricSection:
    return MetricSection(
        headers=("", "A", "B", "Diff"),
        rows=tuple(MetricRow(*row) for row in rows),
        title=str(name),
        subtitle=_entity_level_text(value_a, value_b),
    )


def _chaos_compare_overview_rows(chaos_a, chaos_b) -> list[tuple[str, str, str, str]]:
    """Chaos's level/rolls/stats rows, without markup."""
    return [
        _format_compare_metric_row(
            "Level",
            _metric_value(getattr(chaos_a, "level", None), getattr(chaos_a, "level", None)),
            _metric_value(getattr(chaos_b, "level", None), getattr(chaos_b, "level", None)),
        ),
        (
            "Tracked Rolls",
            _format_chaos_roll_count(chaos_a),
            _format_chaos_roll_count(chaos_b),
            _format_signed_count(_chaos_roll_count(chaos_b) - _chaos_roll_count(chaos_a)),
        ),
        (
            "Stats",
            str(_chaos_stat_count(chaos_a)),
            str(_chaos_stat_count(chaos_b)),
            _format_signed_count(_chaos_stat_count(chaos_b) - _chaos_stat_count(chaos_a)),
        ),
    ]


def format_compare_runs_chaos_diff(snapshot_a, snapshot_b) -> str:
    chaos_a = getattr(snapshot_a, "chaos_tome", None)
    chaos_b = getattr(snapshot_b, "chaos_tome", None)
    if chaos_a is None and chaos_b is None:
        return f'<span style="color:#98A7BA;">{CHAOS_COMPARE_EMPTY_TEXT}</span>'

    blocks = [
        _format_compare_metric_table(
            ("Metric", "A", "B", "Diff"),
            _chaos_compare_overview_rows(chaos_a, chaos_b),
        )
    ]

    stat_rows = _format_compare_run_chaos_stat_rows(chaos_a, chaos_b)
    if stat_rows:
        blocks.append(_format_compare_metric_table(("Stat", "A", "B", "Diff"), stat_rows))
    return "<br>".join(blocks)


def _format_compare_run_stat_deltas(snapshot_a, snapshot_b, *, stat_labels: tuple[str, ...] | None = None) -> list[str]:
    rows: list[str] = []
    for label in stat_labels or COMPARE_RUN_STAT_LABELS:
        stat_a = getattr(snapshot_a, "stats", {}).get(label)
        stat_b = getattr(snapshot_b, "stats", {}).get(label)
        if stat_a is None and stat_b is None:
            continue
        display_a = stat_a.display_value if stat_a is not None else "--"
        display_b = stat_b.display_value if stat_b is not None else "--"
        delta_text = ""
        if stat_a is not None and stat_b is not None and stat_a.value is not None and stat_b.value is not None:
            delta_text = f" ({_format_compare_run_stat_delta(stat_a, stat_b)})"
        rows.append(
            f'<span style="color:#98A7BA;">{html.escape(label)}:</span> '
            f'{html.escape(display_a)} -> {html.escape(display_b)}{html.escape(delta_text)}'
        )
    return rows


def _snapshot_item_total(snapshot) -> int:
    return sum(_item_counts(getattr(snapshot, "items", ())).values())


def _build_compare_run_stage_summary_rows(vod, index) -> list[dict[str, str]]:
    if vod is None or index is None:
        return build_stage_summary(())
    snapshots = getattr(vod, "snapshots", ()) or ()
    if not snapshots:
        return build_stage_summary(())
    bounded_index = min(max(int(index), 0), len(snapshots) - 1)
    return build_stage_summary(snapshots[: bounded_index + 1])


def _format_compare_stage_summary_metric(value_a: str, value_b: str, *, metric: str) -> str:
    escaped_a = html.escape(str(value_a))
    escaped_b = html.escape(str(value_b))
    delta_text = ""
    if metric == "time":
        seconds_a = _parse_stage_summary_time(value_a)
        seconds_b = _parse_stage_summary_time(value_b)
        if seconds_a is not None and seconds_b is not None:
            delta_text = f" ({_format_signed_seconds(seconds_b - seconds_a)})"
    else:
        count_a = _parse_stage_summary_count(value_a)
        count_b = _parse_stage_summary_count(value_b)
        if count_a is not None and count_b is not None:
            delta_text = f" ({_format_signed_count(count_b - count_a)})"
    return f"{escaped_a} <span style='color:#98A7BA;'>&rarr;</span> {escaped_b}{html.escape(delta_text)}"


def _format_compare_stage_summary_items(value_a: str, value_b: str) -> str:
    return (
        f"{value_a} <span style='color:#98A7BA;'>&rarr;</span> {value_b}"
        if value_a != "--" or value_b != "--"
        else "--"
    )


def _parse_stage_summary_time(value: str | None) -> int | None:
    if value in (None, "--"):
        return None
    parts = str(value).split(":")
    if len(parts) not in (2, 3) or any(not part.isdigit() for part in parts):
        return None
    total = 0
    for part in parts:
        total = total * 60 + int(part)
    return total


def _parse_stage_summary_count(value: str | None) -> int | None:
    if value in (None, "--"):
        return None
    try:
        return int(str(value).replace(",", ""))
    except ValueError:
        return None


def _compare_run_item_counts(snapshot_a, snapshot_b):
    """Both inventories as counts, plus what each side has more of."""
    counts_a = _item_counts(getattr(snapshot_a, "items", ()))
    counts_b = _item_counts(getattr(snapshot_b, "items", ()))
    more_in_b: dict[str, int] = {}
    more_in_a: dict[str, int] = {}
    for name in set(counts_a) | set(counts_b):
        delta = counts_b.get(name, 0) - counts_a.get(name, 0)
        if delta > 0:
            more_in_b[name] = delta
        elif delta < 0:
            more_in_a[name] = abs(delta)
    return counts_a, counts_b, more_in_b, more_in_a


def _item_delta_text_rows(more_in_b, more_in_a, *, include_inline: bool) -> list[str]:
    """The Items card's text half: the rarity line, and the inline lists.

    Everything here is a short flowing line, which is cheap to lay out; the
    per-item table that used to follow it is what cost 70 ms a frame and is now
    built by `build_compare_runs_items_table` instead.
    """
    rarity_rows = _format_item_delta_rarity_totals(more_in_b, more_in_a)
    if not more_in_b and not more_in_a:
        return [
            f'<span style="color:#98A7BA;">Rarity:</span> {rarity_rows}',
            '<span style="color:#98A7BA;">No item count differences</span>',
        ]
    rows = [f'<span style="font-size:14px;"><span style="color:#98A7BA; font-weight:700;">Rarity Delta:</span> {rarity_rows}</span>']
    if include_inline:
        if more_in_b:
            rows.append(f'<span style="color:#98A7BA;">B has more:</span> {_format_item_delta_inline(more_in_b, "+", max_items=3)}')
        if more_in_a:
            rows.append(f'<span style="color:#98A7BA;">A has more:</span> {_format_item_delta_inline(more_in_a, "-", max_items=3)}')
    return rows


def _format_compare_run_item_deltas(snapshot_a, snapshot_b, *, details_expanded: bool = False) -> list[str]:
    counts_a, counts_b, more_in_b, more_in_a = _compare_run_item_counts(snapshot_a, snapshot_b)
    rows = _item_delta_text_rows(more_in_b, more_in_a, include_inline=not details_expanded)
    if details_expanded and (more_in_b or more_in_a):
        rows.append(_format_item_delta_table(counts_a, counts_b))
    return rows


def build_compare_runs_items_summary(snapshot_a, snapshot_b, *, details_expanded: bool = False) -> str:
    """The Items card's text half, with the per-item table left to the widget."""
    _counts_a, _counts_b, more_in_b, more_in_a = _compare_run_item_counts(snapshot_a, snapshot_b)
    rows = _item_delta_text_rows(more_in_b, more_in_a, include_inline=not details_expanded)
    return "<br>".join(rows) if rows else "--"


def build_compare_runs_items_table(snapshot_a, snapshot_b, *, details_expanded: bool = False) -> MetricTable:
    """The per-item table, and only when the user has expanded the details.

    Folded away it is an empty table, which the view renders as nothing at all
    -- the summary line above it already says there is nothing to show.
    """
    if not details_expanded:
        return EMPTY_METRIC_TABLE
    counts_a, counts_b, _more_in_b, _more_in_a = _compare_run_item_counts(snapshot_a, snapshot_b)
    rows = tuple(
        MetricRow(
            label=_normalize_item_name_for_display(name),
            value_a=format_count(count_a),
            value_b=format_count(count_b),
            delta=_format_signed_count(delta),
            label_color=_item_delta_color(name),
        )
        for name, count_a, count_b, delta in _item_delta_table_rows(counts_a, counts_b)
    )
    if not rows:
        return EMPTY_METRIC_TABLE
    return MetricTable(
        sections=(MetricSection(headers=("Name", "A", "B", "Diff"), rows=rows),)
    )


def _format_item_delta_rarity_totals(more_in_b: dict[str, int], more_in_a: dict[str, int]) -> str:
    parts: list[str] = []
    for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
        total = 0
        for name, count in more_in_b.items():
            if _item_rarity_name(name) == rarity:
                total += int(count)
        for name, count in more_in_a.items():
            if _item_rarity_name(name) == rarity:
                total -= int(count)
        if total == 0:
            continue
        color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
        parts.append(
            f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
            f'<span style="color:#E5E7EB;">{_format_signed_count(total)}</span>'
        )
    return " ".join(parts) if parts else '<span style="color:#98A7BA;">--</span>'


def _format_item_delta_inline(deltas: dict[str, int], sign: str, *, max_items: int = 6) -> str:
    sorted_items = _sort_item_delta_pairs(deltas.items())
    visible_items = sorted_items[:max_items]
    parts = [
        f'{_format_item_delta_name(name)} {sign}{format_count(count)}'
        for name, count in visible_items
    ]
    hidden_count = len(sorted_items) - len(visible_items)
    if hidden_count > 0:
        parts.append(f'<span style="color:#98A7BA;">+{hidden_count} more</span>')
    return " | ".join(parts) if parts else "--"


def _format_item_delta_table(counts_a: dict[str, int], counts_b: dict[str, int]) -> str:
    header_style = "color:#98A7BA; font-weight:700; padding:4px 8px; border-bottom:1px solid #26364A;"
    cell_style = "padding:4px 8px; border-bottom:1px solid #1E2A3A;"
    rows: list[str] = [
        (
            '<table cellspacing="0" cellpadding="0" style="width:100%; border-collapse:collapse; font-size:14px;">'
            "<tr>"
            f'<td style="{header_style}">Name</td>'
            f'<td align="right" style="{header_style}">A</td>'
            f'<td align="right" style="{header_style}">B</td>'
            f'<td align="right" style="{header_style}">Diff</td>'
            "</tr>"
        )
    ]
    for row_index, (name, count_a, count_b, delta) in enumerate(_item_delta_table_rows(counts_a, counts_b)):
        background = "#0F1722" if row_index % 2 == 0 else "#121C28"
        rows.append(
            f'<tr style="background-color:{background};">'
            f'<td style="{cell_style}">{_format_item_delta_name(name)}</td>'
            f'<td align="right" style="{cell_style}; color:#E5E7EB;">{format_count(count_a)}</td>'
            f'<td align="right" style="{cell_style}; color:#E5E7EB;">{format_count(count_b)}</td>'
            f'<td align="right" style="{cell_style}">{_format_signed_delta_rich_text(delta)}</td>'
            "</tr>"
        )
    rows.append("</table>")
    return "".join(rows)


def _item_delta_table_rows(counts_a: dict[str, int], counts_b: dict[str, int]) -> tuple[tuple[str, int, int, int], ...]:
    rows: list[tuple[str, int, int, int]] = []
    for name in set(counts_a) | set(counts_b):
        count_a = counts_a.get(name, 0)
        count_b = counts_b.get(name, 0)
        delta = count_b - count_a
        if delta == 0:
            continue
        rows.append((name, count_a, count_b, delta))
    return tuple(
        sorted(
            rows,
            key=lambda row: (
                -_item_rarity_rank(row[0]),
                -abs(row[3]),
                _normalize_item_name_for_display(row[0]).casefold(),
            ),
        )
    )


def _format_signed_delta_rich_text(value: int) -> str:
    color = "#22C55E" if value > 0 else "#FB7185" if value < 0 else "#98A7BA"
    return f'<span style="color:{color}; font-weight:700;">{_format_signed_count(value)}</span>'


def _format_item_delta_by_rarity(deltas: dict[str, int], sign: str) -> str:
    grouped: dict[str, list[tuple[str, int]]] = {
        "LEGENDARY": [],
        "RARE": [],
        "UNCOMMON": [],
        "COMMON": [],
        "UNKNOWN": [],
    }
    for name, count in _sort_item_delta_pairs(deltas.items()):
        rarity = _item_rarity_name(name) or "UNKNOWN"
        if rarity not in grouped:
            rarity = "UNKNOWN"
        grouped[rarity].append((name, count))

    rows: list[str] = []
    for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON", "UNKNOWN"):
        items = grouped[rarity]
        if not items:
            continue
        color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
        item_text = " | ".join(
            f'{_format_item_delta_name(name)} {sign}{format_count(count)}'
            for name, count in items
        )
        rows.append(
            f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
            f'<span style="color:#E5E7EB;">{item_text}</span>'
        )
    return "<br>".join(rows) if rows else "--"


def _item_delta_color(item_name: str) -> str:
    """An item's display colour: its rarity, overridden by its own palette entry."""
    display_name = _normalize_item_name_for_display(item_name)
    rarity = _item_rarity_name(display_name)
    color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
    return item_display_color(display_name, color)


def _format_item_delta_name(item_name: str) -> str:
    display_name = _normalize_item_name_for_display(item_name)
    return (
        f'<span style="color:{_item_delta_color(item_name)}; font-weight:700;">'
        f"{html.escape(display_name)}</span>"
    )


def _item_rarity_name(item_name: str) -> str | None:
    display_name = _normalize_item_name_for_display(item_name)
    rarity_name = _normalize_item_name_for_rarity(display_name)
    return ITEM_RARITY_BY_NAME.get(rarity_name)


def _format_compare_run_weapon_deltas(snapshot_a, snapshot_b) -> list[str]:
    weapons_a = _index_named_snapshots(getattr(snapshot_a, "weapons", ()))
    weapons_b = _index_named_snapshots(getattr(snapshot_b, "weapons", ()))
    rows: list[str] = []
    for name in sorted(set(weapons_a) | set(weapons_b), key=str.casefold):
        rows.append(_format_weapon_compare_card(name, weapons_a.get(name), weapons_b.get(name)))
    return rows or [f'<span style="color:#98A7BA;">{WEAPONS_COMPARE_EMPTY_TEXT}</span>']


def _format_compare_run_tome_deltas(snapshot_a, snapshot_b) -> list[str]:
    tomes_a = _index_named_snapshots(getattr(snapshot_a, "tomes", ()))
    tomes_b = _index_named_snapshots(getattr(snapshot_b, "tomes", ()))
    rows: list[str] = []
    for name in sorted(set(tomes_a) | set(tomes_b), key=str.casefold):
        card = _format_tome_compare_card(name, tomes_a.get(name), tomes_b.get(name))
        if card:
            rows.append(card)
    return rows or [f'<span style="color:#98A7BA;">{TOMES_COMPARE_EMPTY_TEXT}</span>']


def _format_compare_run_chaos_stat_rows(chaos_a, chaos_b) -> list[tuple[str, str, str, str]]:
    stats_a = _index_chaos_stats(chaos_a)
    stats_b = _index_chaos_stats(chaos_b)
    rows: list[tuple[str, str, str, str]] = []
    for stat_id in sorted(
        set(stats_a) | set(stats_b),
        key=lambda value: (
            CHAOS_TOME_GAME_STAT_ORDER.get(int(value), 999),
            _chaos_compare_stat_label(stats_a.get(value), stats_b.get(value)).casefold(),
        ),
    ):
        stat_a = stats_a.get(stat_id)
        stat_b = stats_b.get(stat_id)
        label = _chaos_compare_stat_label(stat_a, stat_b)
        rows.append(
            _format_compare_metric_row(
                label,
                _chaos_compare_metric_value(stat_a),
                _chaos_compare_metric_value(stat_b),
            )
        )
    return rows


def _chaos_compare_metric_value(stat):
    if stat is None:
        return None
    return _metric_value(
        getattr(stat, "value", None),
        getattr(stat, "display_delta", None),
    )


def _index_chaos_stats(chaos_tome) -> dict[int, object]:
    if chaos_tome is None:
        return {}
    stats: dict[int, object] = {}
    for stat in getattr(chaos_tome, "stats", ()) or ():
        try:
            stat_id = int(getattr(stat, "stat_id"))
        except (TypeError, ValueError):
            continue
        stats[stat_id] = stat
    return stats


def _chaos_compare_stat_label(stat_a, stat_b) -> str:
    stat = stat_a if stat_a is not None else stat_b
    if stat is None:
        return "Unknown"
    return str(getattr(stat, "label", f"Stat {getattr(stat, 'stat_id', '?')}"))


def _chaos_roll_count(chaos_tome) -> int:
    if chaos_tome is None:
        return 0
    return sum(int(getattr(stat, "rolls", 0) or 0) for stat in getattr(chaos_tome, "stats", ()) or ())


def _format_chaos_roll_count(chaos_tome) -> str:
    if chaos_tome is None:
        return "--"
    return format_count(_chaos_roll_count(chaos_tome))


def _chaos_stat_count(chaos_tome) -> int:
    if chaos_tome is None:
        return 0
    return len(tuple(getattr(chaos_tome, "stats", ()) or ()))


def _index_named_snapshots(snapshots) -> dict[str, object]:
    indexed: dict[str, object] = {}
    for snapshot in snapshots or ():
        name = getattr(snapshot, "name", "")
        if name:
            indexed[str(name)] = snapshot
    return indexed


def _format_named_level_deltas(values_a: dict[str, object], values_b: dict[str, object], *, level_attr: str, value_formatter) -> list[str]:
    rows: list[str] = []
    for name in sorted(set(values_a) | set(values_b), key=str.casefold):
        value_a = values_a.get(name)
        value_b = values_b.get(name)
        if value_a is None:
            rows.append(f'<span style="color:#98A7BA;">{html.escape(name)}:</span> -- -> {value_formatter(value_b)}')
            continue
        if value_b is None:
            rows.append(f'<span style="color:#98A7BA;">{html.escape(name)}:</span> {value_formatter(value_a)} -> --')
            continue
        level_delta = int(getattr(value_b, level_attr, 0)) - int(getattr(value_a, level_attr, 0))
        rows.append(
            f'<span style="color:#98A7BA;">{html.escape(name)}:</span> '
            f'{value_formatter(value_a)} -> {value_formatter(value_b)} ({_format_signed_count(level_delta)} lv)'
        )
    return rows or ['<span style="color:#98A7BA;">No data</span>']


def _format_weapon_compare_block(name: str, weapon_a, weapon_b) -> str:
    title = _format_compare_entity_title(name, weapon_a, weapon_b)
    stat_ids = set()
    for weapon in (weapon_a, weapon_b):
        if weapon is None:
            continue
        stat_ids.update(getattr(weapon, "upgrade_stat_ids", ()))
        stat_ids.update(getattr(weapon, "upgraded_stats", {}).keys())
    stat_rows = []
    for stat_id in sorted(stat_ids, key=lambda value: _weapon_stat_label(weapon_a, weapon_b, value).casefold()):
        stat_a = getattr(weapon_a, "upgraded_stats", {}).get(stat_id) if weapon_a is not None else None
        stat_b = getattr(weapon_b, "upgraded_stats", {}).get(stat_id) if weapon_b is not None else None
        label = _weapon_stat_label(weapon_a, weapon_b, stat_id)
        stat_rows.append(_format_compare_metric_row(label, stat_a, stat_b))
    table = _format_compare_metric_table(("Upgrade", "A", "B", "Diff"), stat_rows)
    return f'{title}<br>{table}'


def _weapon_compare_metric_rows(weapon_a, weapon_b) -> list[tuple[str, str, str, str]]:
    """The rows of one weapon's compare card, without markup.

    Extracted so the HTML card and the widget-rendered card cannot disagree
    about content: both fold over this list.
    """
    metric_rows: list[tuple[str, str, str, str]] = [
        ("Level", _level_display(weapon_a), _level_display(weapon_b), _level_delta(weapon_a, weapon_b))
    ]
    stat_ids = set()
    for weapon in (weapon_a, weapon_b):
        if weapon is None:
            continue
        stat_ids.update(getattr(weapon, "upgrade_stat_ids", ()))
        stat_ids.update(getattr(weapon, "upgraded_stats", {}).keys())
    for stat_id in sorted(stat_ids, key=lambda value: _weapon_stat_label(weapon_a, weapon_b, value).casefold()):
        stat_a = getattr(weapon_a, "upgraded_stats", {}).get(stat_id) if weapon_a is not None else None
        stat_b = getattr(weapon_b, "upgraded_stats", {}).get(stat_id) if weapon_b is not None else None
        label, display_a, display_b, delta = _format_compare_metric_row(
            _weapon_stat_label(weapon_a, weapon_b, stat_id),
            stat_a,
            stat_b,
        )
        metric_rows.append((label, display_a, display_b, delta))
    return metric_rows


def _format_weapon_compare_card(name: str, weapon_a, weapon_b) -> str:
    return _format_compare_mini_card(
        name,
        weapon_a,
        weapon_b,
        _weapon_compare_metric_rows(weapon_a, weapon_b),
    )


def _format_tome_compare_block(name: str, tome_a, tome_b) -> str:
    title = _format_compare_entity_title(name, tome_a, tome_b)
    rows = [
        _format_compare_metric_row(
            "Level",
            _metric_value(getattr(tome_a, "level", None), getattr(tome_a, "level", None)),
            _metric_value(getattr(tome_b, "level", None), getattr(tome_b, "level", None)),
        )
    ]
    if name.casefold() != "chaos":
        label = _tome_value_label(tome_a, tome_b)
        rows.append(
            _format_compare_metric_row(
                label,
                _metric_value(getattr(tome_a, "value", None), getattr(tome_a, "display_value", None)),
                _metric_value(getattr(tome_b, "value", None), getattr(tome_b, "display_value", None)),
            )
        )
    table = _format_compare_metric_table(("Metric", "A", "B", "Diff"), rows)
    return f'{title}<br>{table}'


def _tome_compare_metric_rows(name: str, tome_a, tome_b) -> list[tuple[str, str, str, str]]:
    """One tome's compare rows, without markup. See `_weapon_compare_metric_rows`."""
    if name.casefold() == "chaos":
        return [("Level", _level_display(tome_a), _level_display(tome_b), _level_delta(tome_a, tome_b))]
    return [
        (
            _tome_value_label(tome_a, tome_b),
            *_format_compare_metric_values(
                _metric_value(getattr(tome_a, "value", None), getattr(tome_a, "display_value", None)),
                _metric_value(getattr(tome_b, "value", None), getattr(tome_b, "display_value", None)),
            ),
        )
    ]


def _format_tome_compare_card(name: str, tome_a, tome_b) -> str:
    return _format_compare_mini_card(
        name,
        tome_a,
        tome_b,
        _tome_compare_metric_rows(name, tome_a, tome_b),
    )


def _format_compare_metric_transition(value_a, value_b) -> tuple[str, str]:
    _label, display_a, display_b, delta = _format_compare_metric_row("", value_a, value_b)
    return f"{display_a} -> {display_b}", delta


def _format_compare_metric_values(value_a, value_b) -> tuple[str, str, str]:
    _label, display_a, display_b, delta = _format_compare_metric_row("", value_a, value_b)
    return display_a, display_b, delta


def _format_compare_mini_card(name: str, value_a, value_b, metric_rows: list[tuple[str, str, str, str]]) -> str:
    header = _format_compare_entity_title(name, value_a, value_b)
    if not metric_rows:
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" '
            'style="background-color:#0F1722; border:1px solid #1E2A3A; border-collapse:collapse; margin-bottom:8px; font-size:14px;">'
            '<tr>'
            f'<td colspan="4" style="padding:8px 10px;">{header}</td>'
            '</tr>'
            '</table>'
        )
    rows = [
        '<table width="100%" cellspacing="0" cellpadding="0" '
        'style="background-color:#0F1722; border:1px solid #1E2A3A; border-collapse:collapse; margin-bottom:8px; font-size:14px;">',
        "<tr>",
        f'<td width="52%" style="color:#E5E7EB; font-weight:700; padding:7px 10px; border-bottom:1px solid #26364A;">{header}</td>',
        '<td width="16%" align="right" style="color:#98A7BA; font-weight:700; padding:7px 10px; border-left:1px solid #26364A; border-bottom:1px solid #26364A;">A</td>',
        '<td width="16%" align="right" style="color:#98A7BA; font-weight:700; padding:7px 10px; border-left:1px solid #26364A; border-bottom:1px solid #26364A;">B</td>',
        '<td width="16%" align="right" style="color:#98A7BA; font-weight:700; padding:7px 10px; border-left:1px solid #26364A; border-bottom:1px solid #26364A;">Diff</td>',
        "</tr>",
    ]
    metric_cell_style = "padding:5px 10px; border-bottom:1px solid #1E2A3A;"
    value_cell_style = "padding:5px 10px; border-left:1px solid #1E2A3A; border-bottom:1px solid #1E2A3A;"
    diff_cell_style = "padding:5px 10px; border-left:1px solid #1E2A3A; border-bottom:1px solid #1E2A3A;"
    for label, display_a, display_b, delta in metric_rows:
        rows.append(
            "<tr>"
            f'<td style="{metric_cell_style}; color:#98A7BA;">{html.escape(label)}</td>'
            f'<td align="right" style="{value_cell_style}; color:#E5E7EB;">{html.escape(display_a)}</td>'
            f'<td align="right" style="{value_cell_style}; color:#E5E7EB;">{html.escape(display_b)}</td>'
            f'<td align="right" style="{diff_cell_style}">{_format_metric_delta_rich_text(delta)}</td>'
            "</tr>"
        )
    rows.append("</table>")
    return "".join(rows)


def _entity_level_text(value_a, value_b) -> str:
    """`Lv. 3 -> 5`, or the `--` forms when one side has no entity.

    One implementation for the two HTML titles below and for the widget
    renderer's subtitle; it was duplicated verbatim in both titles before.
    """
    level_a = getattr(value_a, "level", None)
    level_b = getattr(value_b, "level", None)
    if level_a is None and level_b is None:
        return "Lv. --"
    if level_a is None:
        return f"Lv. -- -> {int(level_b)}"
    if level_b is None:
        return f"Lv. {int(level_a)} -> --"
    return f"Lv. {int(level_a)} -> {int(level_b)}"


def _format_compare_entity_title(name: str, value_a, value_b) -> str:
    level_text = _entity_level_text(value_a, value_b)
    return f'<span style="color:#E5E7EB; font-weight:700;">{html.escape(name)}</span> <span style="color:#98A7BA;">({level_text})</span>'


def _format_compare_entity_label(name: str, value_a, value_b) -> str:
    level_text = _entity_level_text(value_a, value_b)
    return f'<span style="font-weight:700;">{html.escape(name)}</span><br><span style="color:#98A7BA;">{level_text}</span>'


def _weapon_stat_label(weapon_a, weapon_b, stat_id: int) -> str:
    for weapon in (weapon_a, weapon_b):
        if weapon is None:
            continue
        stat = getattr(weapon, "upgraded_stats", {}).get(stat_id)
        if stat is not None:
            return str(stat.label)
    return str(stat_id)


def _tome_value_label(tome_a, tome_b) -> str:
    for tome in (tome_a, tome_b):
        label = getattr(tome, "stat_label", None)
        if label:
            return str(label)
    return "Value"


def _metric_value(value, display_value):
    if value is None and display_value is None:
        return None
    return type("CompareMetricValue", (), {"value": value, "display_value": str(display_value)})()


def _format_compare_metric_row(label: str, value_a, value_b) -> tuple[str, str, str, str]:
    display_a = getattr(value_a, "display_value", "--") if value_a is not None else "--"
    display_b = getattr(value_b, "display_value", "--") if value_b is not None else "--"
    delta = "--"
    if value_a is not None and value_b is not None:
        raw_a = getattr(value_a, "value", None)
        raw_b = getattr(value_b, "value", None)
        if raw_a is not None and raw_b is not None:
            delta = _format_compare_run_stat_delta(value_a, value_b)
        else:
            delta = _format_display_value_delta(display_a, display_b) or "--"
    return (label, str(display_a), str(display_b), delta)


def _format_compare_metric_table(headers: tuple[str, str, str, str], rows: list[tuple[str, str, str, str]]) -> str:
    header_style = "color:#98A7BA; font-weight:700; padding:3px 7px; border-bottom:1px solid #26364A;"
    cell_style = "padding:3px 7px; border-bottom:1px solid #1E2A3A;"
    html_rows = [
        (
            '<table cellspacing="0" cellpadding="0" style="width:100%; border-collapse:collapse; margin-bottom:6px;">'
            "<tr>"
            f'<td style="{header_style}">{html.escape(headers[0])}</td>'
            f'<td align="right" style="{header_style}">{html.escape(headers[1])}</td>'
            f'<td align="right" style="{header_style}">{html.escape(headers[2])}</td>'
            f'<td align="right" style="{header_style}">{html.escape(headers[3])}</td>'
            "</tr>"
        )
    ]
    for row_index, (label, display_a, display_b, delta) in enumerate(rows):
        background = "#0F1722" if row_index % 2 == 0 else "#121C28"
        html_rows.append(
            f'<tr style="background-color:{background};">'
            f'<td style="{cell_style}; color:#E5E7EB;">{html.escape(label)}</td>'
            f'<td align="right" style="{cell_style}; color:#E5E7EB;">{html.escape(display_a)}</td>'
            f'<td align="right" style="{cell_style}; color:#E5E7EB;">{html.escape(display_b)}</td>'
            f'<td align="right" style="{cell_style}">{_format_metric_delta_rich_text(delta)}</td>'
            "</tr>"
        )
    html_rows.append("</table>")
    return "".join(html_rows)


def _format_grouped_compare_table(headers: tuple[str, str, str, str, str], rows: list[tuple[str, str, str, str, str]]) -> str:
    header_style = "color:#98A7BA; font-weight:700; padding:3px 7px; border-bottom:1px solid #26364A;"
    cell_style = "padding:3px 7px; border-bottom:1px solid #1E2A3A;"
    html_rows = [
        (
            '<table cellspacing="0" cellpadding="0" style="width:100%; border-collapse:collapse; margin-bottom:6px;">'
            "<tr>"
            f'<td style="{header_style}">{html.escape(headers[0])}</td>'
            f'<td style="{header_style}">{html.escape(headers[1])}</td>'
            f'<td align="right" style="{header_style}">{html.escape(headers[2])}</td>'
            f'<td align="right" style="{header_style}">{html.escape(headers[3])}</td>'
            f'<td align="right" style="{header_style}">{html.escape(headers[4])}</td>'
            "</tr>"
        )
    ]
    last_group = None
    visible_group = ""
    for row_index, (group, metric, display_a, display_b, delta) in enumerate(rows):
        background = "#0F1722" if row_index % 2 == 0 else "#121C28"
        if group != last_group:
            visible_group = group
            last_group = group
        else:
            visible_group = ""
        html_rows.append(
            f'<tr style="background-color:{background};">'
            f'<td style="{cell_style}; color:#E5E7EB;">{visible_group}</td>'
            f'<td style="{cell_style}; color:#E5E7EB;">{html.escape(metric)}</td>'
            f'<td align="right" style="{cell_style}; color:#E5E7EB;">{html.escape(display_a)}</td>'
            f'<td align="right" style="{cell_style}; color:#E5E7EB;">{html.escape(display_b)}</td>'
            f'<td align="right" style="{cell_style}">{_format_metric_delta_rich_text(delta)}</td>'
            "</tr>"
        )
    html_rows.append("</table>")
    return "".join(html_rows)


def _format_metric_delta_rich_text(delta: str) -> str:
    if delta == "--":
        return '<span style="color:#98A7BA;">--</span>'
    color = "#22C55E" if delta.startswith("+") else "#FB7185" if delta.startswith("-") else "#98A7BA"
    return f'<span style="color:{color}; font-weight:700;">{html.escape(delta)}</span>'


def _format_display_value_delta(display_a: str, display_b: str) -> str | None:
    text_a = str(display_a).strip()
    text_b = str(display_b).strip()
    suffix = ""
    if text_a.endswith("%") and text_b.endswith("%"):
        suffix = "%"
        text_a = text_a[:-1]
        text_b = text_b[:-1]
    elif text_a.endswith("x") and text_b.endswith("x"):
        suffix = "x"
        text_a = text_a[:-1]
        text_b = text_b[:-1]
    try:
        value_a = float(text_a.replace(",", ""))
        value_b = float(text_b.replace(",", ""))
    except ValueError:
        return None
    delta = value_b - value_a
    if abs(delta) < 0.00001:
        formatted = "0"
    elif delta.is_integer():
        formatted = f"{int(delta):+d}"
    else:
        formatted = f"{delta:+.2f}"
    return f"{formatted}{suffix}"


def _level_display(value) -> str:
    level = getattr(value, "level", None)
    return "--" if level is None else str(int(level))


def _level_delta(value_a, value_b) -> str:
    level_a = getattr(value_a, "level", None)
    level_b = getattr(value_b, "level", None)
    if level_a is None or level_b is None:
        return "--"
    return _format_signed_count(int(level_b) - int(level_a))


def _format_weapon_summary(weapon) -> str:
    level = getattr(weapon, "level", None)
    if level is None:
        return "--"
    stats = []
    for stat_id in getattr(weapon, "upgrade_stat_ids", ())[:2]:
        stat = getattr(weapon, "upgraded_stats", {}).get(stat_id)
        if stat is not None:
            stats.append(f"{stat.label} {stat.display_value}")
    suffix = f" [{', '.join(stats)}]" if stats else ""
    return f"Lv. {int(level)}{suffix}"


def _format_tome_summary(tome) -> str:
    level = getattr(tome, "level", None)
    if level is None:
        return "--"
    stat_label = getattr(tome, "stat_label", "")
    display_value = getattr(tome, "display_value", "")
    suffix = f" [{stat_label} {display_value}]" if stat_label and display_value else ""
    return f"Lv. {int(level)}{suffix}"


def _raw_snapshot_int_delta(base_snapshot, snapshot, attr_name: str) -> int | None:
    base_value = getattr(base_snapshot, attr_name, None)
    current_value = getattr(snapshot, attr_name, None)
    if base_value is None or current_value is None:
        return None
    return int(current_value) - int(base_value)


def _format_signed_count(value: int | float) -> str:
    value = int(value)
    if value > 0:
        return f"+{format_count(value)}"
    if value < 0:
        return f"-{format_count(abs(value))}"
    return "0"


def _format_signed_seconds(value: float) -> str:
    sign = "+" if value > 0 else "-" if value < 0 else ""
    return f"{sign}{format_elapsed_time(abs(float(value)))}"


def _format_signed_stat_delta(value: float) -> str:
    if abs(value) < 0.00001:
        return "0"
    if float(value).is_integer():
        return f"{int(value):+d}"
    return f"{value:+.2f}"


def _format_compare_run_stat_delta(stat_a, stat_b) -> str:
    percent_delta = _display_percent_delta(
        getattr(stat_a, "display_value", ""),
        getattr(stat_b, "display_value", ""),
    )
    if percent_delta is not None:
        return _format_signed_percent_delta(percent_delta)
    return _format_signed_stat_delta(float(stat_b.value) - float(stat_a.value))


def _display_percent_delta(display_a: str, display_b: str) -> float | None:
    text_a = str(display_a).strip()
    text_b = str(display_b).strip()
    if not text_a.endswith("%") or not text_b.endswith("%"):
        return None
    try:
        value_a = float(text_a[:-1].replace(",", ""))
        value_b = float(text_b[:-1].replace(",", ""))
    except ValueError:
        return None
    return value_b - value_a


def _format_signed_percent_delta(value: float) -> str:
    if abs(value) < 0.00001:
        return "0%"
    sign = "+" if value > 0 else "-"
    magnitude = abs(value)
    if magnitude.is_integer():
        return f"{sign}{int(magnitude)}%"
    return f"{sign}{magnitude:.2f}%"


def format_snapshot_new_items(previous_snapshot, snapshot) -> str:
    if previous_snapshot is None:
        return "No previous snapshot"
    new_items = diff_new_items(getattr(previous_snapshot, "items", ()), getattr(snapshot, "items", ()))
    if not new_items:
        return "No new items since previous snapshot"
    return format_new_items_rich_text(new_items)


def format_snapshot_item_gains_preview(previous_snapshot, snapshot, *, segment_snapshots=()) -> str:
    if previous_snapshot is None:
        return "No previous snapshot"
    changes = summarize_item_segment_changes(segment_snapshots or (previous_snapshot, snapshot))
    gains = changes["gained"]
    total = sum(gain for _name, gain in gains)
    items_summary = format_item_gain_rarity_totals(gains)
    if total > 0:
        items_summary = f'{items_summary} <span style="color:#98A7BA;">+{format_count(total)}</span>'
    rows = [f'<span style="color:#98A7BA;">Items:</span> {items_summary}']
    time_delta = _snapshot_time_delta(previous_snapshot, snapshot)
    if time_delta is not None:
        rows.append(f'<span style="color:#98A7BA;">Time:</span> {format_elapsed_time(time_delta)}')

    kill_delta = _snapshot_int_delta(previous_snapshot, snapshot, "mob_kills")
    if kill_delta is not None and kill_delta > 0:
        rows.append(f'<span style="color:#98A7BA;">Kills:</span> +{format_count(kill_delta)}')

    level_delta = _snapshot_int_delta(previous_snapshot, snapshot, "player_level")
    if level_delta is not None and level_delta > 0:
        rows.append(f'<span style="color:#98A7BA;">Levels:</span> +{format_count(level_delta)}')

    return "<br>".join(rows)


def diff_new_items(previous_items, current_items) -> tuple[str, ...]:
    return tuple(f"{name} x{gain}" for name, gain in diff_item_gains(previous_items, current_items))


def diff_item_gains(previous_items, current_items) -> tuple[tuple[str, int], ...]:
    changes = summarize_item_count_changes(previous_items, current_items)
    return changes["gained"]


def summarize_item_count_changes(previous_items, current_items) -> dict[str, tuple[tuple[str, int], ...]]:
    previous_counts = _item_counts(previous_items)
    current_counts = _item_counts(current_items)
    gained: dict[str, int] = {}
    lost: dict[str, int] = {}
    broken: dict[str, int] = {}
    for name in set(previous_counts) | set(current_counts):
        current_count = current_counts.get(name, 0)
        delta = current_count - previous_counts.get(name, 0)
        if delta > 0:
            gained[name] = gained.get(name, 0) + delta
        elif delta < 0:
            target = broken if _is_breakable_consumed_item(name) else lost
            target[name] = target.get(name, 0) + abs(delta)
    return {
        "gained": _sort_item_delta_pairs(gained.items()),
        "lost": _sort_item_delta_pairs(lost.items()),
        "broken": _sort_item_delta_pairs(broken.items()),
    }


def summarize_item_segment_changes(snapshots) -> dict[str, tuple[tuple[str, int], ...]]:
    snapshots = tuple(snapshots or ())
    gained: dict[str, int] = {}
    lost: dict[str, int] = {}
    broken: dict[str, int] = {}
    if len(snapshots) < 2:
        return {"gained": (), "lost": (), "broken": ()}

    previous_items = getattr(snapshots[0], "items", ())
    for snapshot in snapshots[1:]:
        changes = summarize_item_count_changes(previous_items, getattr(snapshot, "items", ()))
        for bucket_name, target in (("gained", gained), ("lost", lost), ("broken", broken)):
            for name, count in changes[bucket_name]:
                target[name] = target.get(name, 0) + count
        previous_items = getattr(snapshot, "items", ())

    return {
        "gained": _sort_item_delta_pairs(gained.items()),
        "lost": _sort_item_delta_pairs(lost.items()),
        "broken": _sort_item_delta_pairs(broken.items()),
    }


def _sort_item_delta_pairs(items) -> tuple[tuple[str, int], ...]:
    return tuple(
        sorted(
            ((str(name), int(count)) for name, count in items if int(count) > 0),
            key=lambda item: (-_item_rarity_rank(item[0]), -item[1], item[0].casefold()),
        )
    )


def _is_breakable_consumed_item(item_name: str) -> bool:
    rarity_name = _normalize_item_name_for_rarity(item_name)
    return rarity_name in {"Za Warudo", "Ze Warudo"}


def format_snapshot_item_changes_details(previous_snapshot, snapshot, *, segment_snapshots=()) -> str:
    changes = summarize_item_segment_changes(segment_snapshots or (previous_snapshot, snapshot))
    sections: list[str] = []
    if changes["gained"]:
        sections.append(
            '<span style="color:#98A7BA; font-weight:700;">Gained</span><br>'
            f'{format_item_gains_by_rarity(changes["gained"])}'
        )
    if changes["broken"]:
        sections.append(
            '<span style="color:#98A7BA; font-weight:700;">Broken</span><br>'
            f'{format_item_losses_by_rarity(changes["broken"], suffix="broken")}'
        )
    if changes["lost"]:
        sections.append(
            '<span style="color:#98A7BA; font-weight:700;">Lost</span><br>'
            f'{format_item_losses_by_rarity(changes["lost"])}'
        )
    if not sections:
        return '<span style="color:#98A7BA;">No item changes in this segment</span>'
    return "<br>".join(sections)


#: Section order for the compare card, and the sign each one carries.
_COMPARE_SECTIONS = (("gained", "Gained", "+"), ("broken", "Broken", "-"), ("lost", "Lost", "-"))


def compare_detail_chips(
    previous_snapshot, snapshot, *, segment_snapshots=()
) -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """The segment's item changes as chips: `(section, ((text, tag), ...))`.

    The widget counterpart to `format_snapshot_item_changes_details`, which
    renders the same data as one rich-text block with the items inside a
    section joined by `" | "`. That block is unreadable past about six items:
    the rarity is a coloured bullet at the *start of the row*, so every item
    after the first is an unmarked name in a pipe-separated run.

    A chip carries its own rarity, so it stays legible however many there are
    -- and it is the shape the Items panel beside it already uses.

    Pure and here rather than in the tab: the grouping is a projection
    decision, and this way it is testable without a widget.
    """
    changes = summarize_item_segment_changes(
        segment_snapshots or (previous_snapshot, snapshot)
    )
    sections: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    for key, title, sign in _COMPARE_SECTIONS:
        entries = changes.get(key) or ()
        if not entries:
            continue
        chips: list[tuple[str, str]] = []
        for name, count in entries:
            display_name = _normalize_item_name_for_display(name)
            rarity = _item_rarity_name(display_name)
            tag = _ITEM_CHIP_OBJECT_NAME_BY_RARITY.get(rarity, "tagNeutral")
            chips.append((f"{display_name} {sign}{format_count(count)}", tag))
        sections.append((title, tuple(chips)))
    return tuple(sections)


def format_item_gains_by_rarity(
    gains: tuple[tuple[str, int], ...],
    *,
    max_items: int | None = None,
) -> str:
    if not gains:
        return '<span style="color:#98A7BA;">No item gains</span>'

    grouped: dict[str, list[tuple[str, int]]] = {
        "LEGENDARY": [],
        "RARE": [],
        "UNCOMMON": [],
        "COMMON": [],
        "UNKNOWN": [],
    }
    for name, gain in gains:
        rarity_name = _normalize_item_name_for_rarity(name)
        rarity = ITEM_RARITY_BY_NAME.get(rarity_name, "UNKNOWN")
        if rarity not in grouped:
            rarity = "UNKNOWN"
        grouped[rarity].append((_normalize_item_name_for_display(name), int(gain)))

    remaining = max_items
    hidden_count = 0
    rows: list[str] = []
    for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON", "UNKNOWN"):
        items = grouped[rarity]
        if not items:
            continue
        if remaining is not None:
            visible_items = items[:remaining]
            hidden_count += max(0, len(items) - len(visible_items))
            remaining -= len(visible_items)
            if not visible_items:
                continue
        else:
            visible_items = items
        color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
        item_text = " | ".join(
            _format_item_change_text(name, f"+{format_count(gain)}")
            for name, gain in visible_items
        )
        rows.append(
            f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
            f'<span style="color:#E5E7EB;">{item_text}</span>'
        )
        if remaining is not None and remaining <= 0:
            break

    if hidden_count > 0:
        rows.append(f'<span style="color:#98A7BA;">+{hidden_count} more gains...</span>')
    return "<br>".join(rows)


def format_item_losses_by_rarity(
    losses: tuple[tuple[str, int], ...],
    *,
    suffix: str | None = None,
) -> str:
    if not losses:
        return '<span style="color:#98A7BA;">No item losses</span>'

    grouped: dict[str, list[tuple[str, int]]] = {
        "LEGENDARY": [],
        "RARE": [],
        "UNCOMMON": [],
        "COMMON": [],
        "UNKNOWN": [],
    }
    for name, loss in losses:
        rarity_name = _normalize_item_name_for_rarity(name)
        rarity = ITEM_RARITY_BY_NAME.get(rarity_name, "UNKNOWN")
        if rarity not in grouped:
            rarity = "UNKNOWN"
        grouped[rarity].append((_normalize_item_name_for_display(name), int(loss)))

    rows: list[str] = []
    for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON", "UNKNOWN"):
        items = grouped[rarity]
        if not items:
            continue
        color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
        item_text = " | ".join(
            _format_item_change_text(
                name,
                f"-{format_count(loss)}{f' {suffix}' if suffix else ''}",
            )
            for name, loss in items
        )
        rows.append(
            f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
            f'<span style="color:#E5E7EB;">{item_text}</span>'
        )
    return "<br>".join(rows)


def format_item_loss_inline(losses: tuple[tuple[str, int], ...]) -> str:
    if not losses:
        return '<span style="color:#98A7BA;">--</span>'
    return " | ".join(
        _format_item_change_text(
            _normalize_item_name_for_display(name),
            f"-{format_count(count)}",
        )
        for name, count in losses
    )


def _format_item_change_text(display_name: str, suffix: str) -> str:
    color = item_display_color(display_name, "#E5E7EB")
    return (
        f'<span style="color:{color};">'
        f'{html.escape(display_name)} {html.escape(suffix)}</span>'
    )


def format_item_gain_rarity_totals(gains: tuple[tuple[str, int], ...]) -> str:
    rarity_totals = _empty_item_rarity_totals()
    for name, gain in gains:
        rarity_name = _normalize_item_name_for_rarity(name)
        rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
        if rarity in rarity_totals:
            rarity_totals[rarity] += int(gain)

    parts: list[str] = []
    for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
        total = rarity_totals.get(rarity, 0)
        if total <= 0:
            continue
        color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
        parts.append(
            f'<span style="color:{color}; font-weight:800;">&#9679;</span> '
            f'<span style="color:#E5E7EB;">{format_count(total)}</span>'
        )
    return " ".join(parts) if parts else '<span style="color:#98A7BA;">--</span>'


def format_snapshot_compare_summary(
    base_snapshot,
    snapshot,
    *,
    base_index: int | None,
    current_index: int | None,
    segment_snapshots=(),
) -> str:
    pieces: list[str] = []
    if base_index is not None and current_index is not None:
        pieces.append(f"Snapshot {int(base_index) + 1} -> {int(current_index) + 1}")
    base_time = getattr(base_snapshot, "game_time_seconds", None)
    current_time = getattr(snapshot, "game_time_seconds", None)
    if base_time is not None and current_time is not None:
        pieces.append(f"{format_elapsed_time(base_time)} -> {format_elapsed_time(current_time)}")
    kill_delta = _snapshot_int_delta(base_snapshot, snapshot, "mob_kills")
    if kill_delta is not None and kill_delta > 0:
        pieces.append(f"+{format_count(kill_delta)} kills")
    level_delta = _snapshot_int_delta(base_snapshot, snapshot, "player_level")
    if level_delta is not None and level_delta > 0:
        pieces.append(f"+{format_count(level_delta)} levels")
    changes = summarize_item_segment_changes(segment_snapshots or (base_snapshot, snapshot))
    item_total = sum(gain for _name, gain in changes["gained"])
    pieces.append(f"+{format_count(item_total)} items")
    broken_total = sum(count for _name, count in changes["broken"])
    if broken_total:
        pieces.append(f"{format_count(broken_total)} broken")
    lost_total = sum(count for _name, count in changes["lost"])
    if lost_total:
        pieces.append(f"-{format_count(lost_total)} lost")
    return " | ".join(pieces)


def _snapshot_int_delta(base_snapshot, snapshot, attr_name: str) -> int | None:
    base_value = getattr(base_snapshot, attr_name, None)
    current_value = getattr(snapshot, attr_name, None)
    if base_value is None or current_value is None:
        return None
    return max(0, int(current_value) - int(base_value))


def _snapshot_time_delta(base_snapshot, snapshot) -> float | None:
    base_time = getattr(base_snapshot, "game_time_seconds", None)
    current_time = getattr(snapshot, "game_time_seconds", None)
    if base_time is None or current_time is None:
        return None
    return max(0.0, float(current_time) - float(base_time))


def format_new_items_rich_text(items) -> str:
    if not items:
        return "No new items since previous snapshot"
    return ", ".join(_format_single_item_rich_text(item) for item in items)


def format_banishes_rich_text(banishes) -> str:
    banishes = tuple(str(item) for item in (banishes or ()))
    if not banishes:
        return "No banishes yet"
    return ", ".join(_format_single_banish_rich_text(item) for item in banishes)


def _format_single_banish_rich_text(banish_text: str) -> str:
    if banish_text.endswith(" Tome"):
        tome_name = html.escape(banish_text)
        return f'<span style="font-weight: 700;">{tome_name}</span>'
    return _format_single_item_rich_text(banish_text)


def _item_counts(items) -> dict[str, int]:
    return run_summary.item_counts(items)


def build_stage_summary(snapshots) -> list[dict[str, str]]:
    return run_summary.build_stage_summary(snapshots)


def _format_stage_item_rarity_summary(rarity_totals: dict[str, int]) -> str:
    parts: list[str] = []
    for rarity in ("LEGENDARY", "RARE", "UNCOMMON", "COMMON"):
        total = int(rarity_totals.get(rarity, 0))
        if total <= 0:
            continue
        color = ITEM_RARITY_COLOR_MAP.get(rarity, COLOR_MAP["DEFAULT"])
        parts.append(
            f'<span style="color:{color}; font-weight:700;">&#9679;</span> '
            f'<span style="color:#E5E7EB;">{html.escape(str(total))}</span>'
        )
    return " ".join(parts) if parts else '<span style="color:#98A7BA;">--</span>'


def format_items_rich_text(items) -> str:
    if not items:
        return "--"
    return ", ".join(_format_single_item_rich_text(item) for item in items)


def _format_single_item_rich_text(item_text: str) -> str:
    item_name, suffix = _split_item_stack_suffix(item_text)
    display_name = _normalize_item_name_for_display(item_name)
    rarity_name = _normalize_item_name_for_rarity(display_name)
    rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
    color = ITEM_RARITY_COLOR_MAP.get(rarity)
    color = item_display_color(display_name, color)
    escaped_name = html.escape(display_name)
    if color:
        escaped_name = f'<span style="color: {color}; font-weight: 700;">{escaped_name}</span>'
    escaped_suffix = html.escape(suffix)
    return f"{escaped_name}{escaped_suffix}"


_ITEM_CHIP_OBJECT_NAME_BY_RARITY = {
    "COMMON": "tagCommon",
    "UNCOMMON": "tagUncommon",
    "RARE": "tagRare",
    "LEGENDARY": "tagLegendary",
}


#: The four rarities the item panel groups by, strongest first. Anything whose
#: rarity is unknown is deliberately absent: it is shown, never filtered on.
ITEM_RARITY_ORDER = ("LEGENDARY", "RARE", "UNCOMMON", "COMMON")


def item_rarity(item_text: str) -> str | None:
    """The rarity of one item as it appears in a snapshot's item list.

    Takes the display text -- stack suffix and all -- because that is the form
    the item panel holds. ``None`` for anything the rarity table does not know.
    """
    item_name, _suffix = _split_item_stack_suffix(item_text)
    return _item_rarity_name(item_name)


def item_rarity_totals(items) -> dict[str, int]:
    """Per-rarity counts, the same ones the rarity summary prints."""
    return _item_rarity_totals(items)


def item_chip_display(item_text: str) -> tuple[str, str]:
    """`(label text incl. stack suffix, chip objectName)` for one item.

    The counterpart to `_format_single_item_rich_text` for chip-widget
    rendering rather than a single rich-text line: same name/suffix/rarity
    lookup, but it hands back a QSS objectName (`tagCommon` and friends,
    already styled in the redesign sheet) instead of a colour baked into an
    HTML span, since a chip is a real widget rather than markup.
    """
    item_name, suffix = _split_item_stack_suffix(item_text)
    display_name = _normalize_item_name_for_display(item_name)
    rarity_name = _normalize_item_name_for_rarity(display_name)
    rarity = ITEM_RARITY_BY_NAME.get(rarity_name)
    object_name = _ITEM_CHIP_OBJECT_NAME_BY_RARITY.get(rarity, "tagNeutral")
    return f"{display_name}{suffix}", object_name


def _split_item_stack_suffix(item_text: str) -> tuple[str, str]:
    if not item_text:
        return "", ""
    name, separator, suffix = item_text.rpartition(" x")
    if separator and suffix.isdigit():
        return name, f"{separator}{suffix}"
    return item_text, ""


def _normalize_item_name_for_rarity(item_name: str) -> str:
    return normalize_item_name_for_rarity(item_name)


def _normalize_item_name_for_display(item_name: str) -> str:
    return normalize_item_name_for_display(item_name)


def format_chests_per_minute(value: float | None) -> str:
    if value is None:
        return "Average chests/min: --"
    return f"Average chests/min: {value:.2f}"


def format_powerups_duration(stats) -> str:
    stat = (stats or {}).get("Powerup Multiplier")
    try:
        powerup_multiplier = float(getattr(stat, "value", None))
    except (TypeError, ValueError):
        return "Powerups: --"
    if not isfinite(powerup_multiplier):
        return "Powerups: --"

    standard_duration = 15.0 * powerup_multiplier
    clock_duration = 12.0 * powerup_multiplier
    return (
        f"Powerups: {format_seconds_compact(standard_duration)}s"
        f" | Clock: {format_seconds_compact(clock_duration)}s"
    )


def format_seconds_compact(value: float) -> str:
    return str(int(round(value)))


def merge_banish_appearance_order(previous_banishes, current_banishes) -> tuple[str, ...]:
    current = tuple(str(item) for item in (current_banishes or ()))
    if not current:
        return ()
    previous = tuple(str(item) for item in (previous_banishes or ()))
    merged = [item for item in previous if item in current]
    for item in current:
        if item not in merged:
            merged.append(item)
    return tuple(merged)


def calculate_player_chests_per_minute(stats) -> float | None:
    elite_stat = stats.get("Elite Spawn Increase")
    powerup_stat = stats.get("Powerup Drop Chance")
    elite_spawn_increase = getattr(elite_stat, "value", None)
    powerup_drop_chance = getattr(powerup_stat, "value", None)
    if elite_spawn_increase is None or powerup_drop_chance is None:
        return None
    return calculate_chests_per_minute(elite_spawn_increase, powerup_drop_chance)


def resolve_snapshot_chests_per_minute(snapshot) -> float | None:
    stored_value = getattr(snapshot, "chests_per_minute", None)
    if stored_value is not None:
        return stored_value
    return calculate_player_chests_per_minute(snapshot.stats)


def chests_card_values(
    opened_by_stage: dict[int, int] | None,
    total_by_stage: dict[int, int] | None,
    opened: int | None,
    total: int | None,
    paid: int | None,
    key_procs: int | None,
    free: int | None,
    keys: int | None,
    expected: float | None,
    total_is_minimum: bool = False,
) -> dict[str, str]:
    if total is None:
        return {
            "maps": "--",
            "total": "--",
            "paid_free": "-- / --",
            "key_procs": "-- (--)",
            "expected": "--",
            "keys": "-- (--)",
        }

    stage_parts = []
    for stage, count in sorted((opened_by_stage or {}).items()):
        stage_total = (total_by_stage or {}).get(stage, 0)
        if int(count) < 0:
            stage_parts.append(f"T{stage}:--/{stage_total}")
        else:
            stage_parts.append(f"T{stage}:{count}/{stage_total}")
    opened_text = "--" if opened is None else str(opened)
    if opened is not None and total_is_minimum:
        opened_text += "+"
    total_text = str(total)
    stages = " ".join(stage_parts) if stage_parts else f"T1:{opened_text}/{total_text}"

    paid_text = "--" if paid is None else str(paid)
    free_text = "--" if free is None else str(free)
    normal = None if paid is None or key_procs is None else paid + key_procs
    procs_text = "--" if key_procs is None or normal is None else f"{key_procs}/{normal}"
    proc_rate = (
        "--"
        if key_procs is None or not normal
        else f"{key_procs / normal * 100.0:.1f}%"
    )
    expected_text = "--" if expected is None else f"{expected:.1f}"
    keys_text = "--" if keys is None else str(keys)
    chance = "--" if keys is None else f"{key_proc_chance(keys) * 100.0:.1f}%"
    return {
        "maps": stages,
        "total": f"{opened_text}/{total_text}",
        "paid_free": f"{paid_text} / {free_text}",
        "key_procs": f"{procs_text} ({proc_rate})",
        "expected": expected_text,
        "keys": f"{keys_text} ({chance})",
    }


def sort_items_for_display(items, mode: str | None) -> tuple[str, ...]:
    items = tuple(items or ())
    if mode == ITEM_SORT_DEFAULT or not items:
        return items
    reverse = mode == ITEM_SORT_RARITY_DESC
    if mode not in (ITEM_SORT_RARITY_ASC, ITEM_SORT_RARITY_DESC):
        return items

    def sort_key(entry) -> tuple[int, int]:
        index, item = entry
        rarity_rank = _item_rarity_rank(str(item))
        return (-rarity_rank if reverse else rarity_rank, index)

    return tuple(item for _index, item in sorted(enumerate(items), key=sort_key))


def _item_total_count(items) -> int:
    return sum(_item_counts(items).values())
