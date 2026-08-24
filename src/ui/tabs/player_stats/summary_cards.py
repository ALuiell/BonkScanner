"""Stage-summary and chests-card writers, shared by both Player Stats tabs.

The last of `PlayerStatsCardsMixin`, and the reason it does not need to be a
mixin: both functions take the labels they write as an **argument**. They never
had the string-keyed-lookup problem the rest of that class had, because they
never looked anything up on a shared `self` -- the caller, which owns the
widgets, hands them over.

That makes them ordinary module-level functions, which is what they should
always have been. Two tabs call them with their own labels; nothing else can
reach a widget through them.
"""

from __future__ import annotations

from core.luck_rarity import (
    LUCK_RARITY_ORDER,
    calculate_luck_rarity_probabilities,
    format_expected_count,
    format_luck_rarity_percent,
)
from projections import formatting
from ui.shared import _set_text


def set_stage_summary_labels(labels, rows) -> None:
    """Write four stage rows into `labels`, or dashes when there are none.

    `labels` is either a list of dicts (the gridded layout both tabs build) or
    a list of single labels (the older one-line-per-stage form). Both shapes
    are still handled; the branch predates this move and is not this change's
    to remove.
    """
    default_rows = [
        {
            "label": f"Stage {index}",
            "kills": "--",
            "time": "--",
            "items": "--",
        }
        for index in range(1, 5)
    ]
    rows = rows or default_rows
    for labels_by_column, row in zip(labels, rows):
        if isinstance(labels_by_column, dict):
            labels_by_column["stage"].setText(str(row["label"]).replace("Stage ", ""))
            labels_by_column["time"].setText(row["time"])
            labels_by_column["kills"].setText(row["kills"])
            labels_by_column["items"].setText(row["items"])
        else:
            labels_by_column.setText(
                f"{row['label']}: Kills {row['kills']} | Time {row['time']} | Items {row['items']}"
            )


#: The Item Rarity explanation and the legacy/fallback Chests explanation.
#: Live Chests now supplies a precise status because its strict completeness
#: gate can also be waiting on factual counters or a fast/slow coverage match.
EXPECTED_COUNTS_UNAVAILABLE_TEXT = (
    "Needs the app running from the start of the run for an accurate count."
)

CHEST_EXPECTED_STATUS_TEXT = {
    "pending": "Waiting for the initial Expected chest baseline.",
    "baseline_missed": (
        "Expected tracking began after a normal chest was already opened."
    ),
    "counters_unavailable": "Waiting for complete chest counters.",
    "coverage_mismatch": (
        "Chest counters are syncing; Expected is temporarily unavailable."
    ),
}


def set_loot_rarity_card_values(labels, luck_value, loot_stats) -> None:
    """Write the rarity card: chance always, counts only when measurable.

    The two halves fail apart, exactly as they do in `!luck`. The chance
    depends on nothing but the Luck held right now, so it survives a late
    attach; the counts do not, and rather than showing partial numbers the card
    says why -- this is the surface the streamer reads, and the only one that
    can carry the reason.
    """
    if not labels:
        return
    probabilities = calculate_luck_rarity_probabilities(luck_value)
    available = bool(getattr(loot_stats, "available", False))
    actual = getattr(loot_stats, "actual", None) or {}
    expected = getattr(loot_stats, "expected", None) or {}
    for rarity in LUCK_RARITY_ORDER:
        row = labels.get(rarity)
        if not row:
            continue
        _set_text(row["chance"], format_luck_rarity_percent(probabilities.get(rarity)))
        if available:
            counts = (
                f"{int(actual.get(rarity, 0))} "
                f"(exp {format_expected_count(expected.get(rarity))})"
            )
        else:
            counts = "--"
        _set_text(row["counts"], counts)
    status = labels.get("status")
    if status is not None:
        _set_text(status, "" if available else EXPECTED_COUNTS_UNAVAILABLE_TEXT)
        status.setVisible(not available)


def set_chests_card_values(
    labels,
    values: dict[str, str] | None,
    *,
    expected_status: str | None = None,
) -> None:
    """Write the chests card, falling back to the all-empty projection.

    The cell still decides whether the status line is visible.  Live data also
    supplies ``expected_status`` so the line distinguishes a missed baseline
    from pending factual counters and a temporary coverage mismatch; legacy
    recordings retain the old fallback text.
    """
    if not labels:
        return
    values = values or formatting.chests_card_values(
        None, None, None, None, None, None, None, None, None
    )
    for key, label in labels.items():
        if key == "status":
            continue
        _set_text(label, values.get(key, "--"))
    status = labels.get("status")
    if status is not None:
        expected_available = values.get("expected", "--") != "--"
        unavailable_text = CHEST_EXPECTED_STATUS_TEXT.get(
            str(expected_status),
            EXPECTED_COUNTS_UNAVAILABLE_TEXT,
        )
        _set_text(status, "" if expected_available else unavailable_text)
        status.setVisible(not expected_available)
