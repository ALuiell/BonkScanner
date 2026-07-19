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


def set_chests_card_values(labels, values: dict[str, str] | None) -> None:
    """Write the chests card, falling back to the all-empty projection."""
    if not labels:
        return
    values = values or formatting.chests_card_values(
        None, None, None, None, None, None, None, None, None
    )
    for key, label in labels.items():
        _set_text(label, values.get(key, "--"))
