"""Fixed widths and card shapes the two Player Stats tabs size themselves to.

Split out of ``gui_layout.py`` by step 27b, which is what made ``ui/layout.py``
possible. The two ``TOPLEVEL_DEBT`` entries pointing at ``gui_layout`` were
both from this package, and **neither named anything the layout does** -- not
``build_layout``, not ``TabRouter``, not one of the five view composition
roots. Moving the layout wholesale would have closed both entries while
leaving the actual problem standing: ``ui/layout.py`` builds this package
inside its builders and ``recordings.py`` imports it at module level, which is
a genuine cycle. It survived only because the ``live_stats`` side was deferred
into a method body, and the comment at ``live_stats.py`` recorded that step 19
had already shipped that cycle once -- invisible to the suite *and* to
``test_import_direction``, because both parse ASTs rather than importing.

Here, in the package that is their only consumer, they are a leaf: this module
imports Qt and one ``core`` enum and nothing else in ``ui``. Both tabs import
it as an ordinary module-level sibling, and the deferral is gone.

Not ``ui/shared.py``, which was the other candidate and holds one relocated
sibling of these already (``_apply_summary_label_padding``, moved there at
step 21 so ``compare_runs`` would not open a ``ui -> <top-level>`` edge).
``ui/shared.py`` is general-purpose UI utility; these are Player Stats layout
metrics, and the measurement says so -- ``live_stats.py`` and ``recordings.py``
are their only two importers in the tree, and both live here.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QFormLayout, QFrame, QLabel

from core.stats.formats import PlayerStatFormat


LIVE_STATS_CARD_COLUMNS = 3
LIVE_STATS_VALUE_WIDTH = 64
RECORDINGS_STATS_CARD_COLUMNS = 3
RECORDINGS_LIST_MIN_WIDTH = 190
RECORDINGS_LIST_MAX_WIDTH = 280
STAGE_SUMMARY_COLUMN_BASELINES = {
    "stage": "Stage",
    "time": "59:59",
    "kills": "999,999",
    "items": "\u25cf 99 \u25cf 99 \u25cf 99 \u25cf 99",
}
STAGE_SUMMARY_COLUMN_PADDING = 8
SUMMARY_LABEL_BASELINE_PADDING = 8
RUN_SUMMARY_LABEL_BASELINES = {
    "chests_per_minute": "Average chests/min: 999.99",
    "powerups_duration": "Powerups: 999.9s | Clock: 999.9s",
    "in_game_time": "In-Game Time: 99:59:59",
    "mob_kills": "Mob Kills: 999,999",
    "kps_averages": "KPS: 60s 999/s | 5m 999/s",
    "level": "Level: 999",
}
POWERUPS_CARD_LINE_BASELINE = "Stonks: 99:59 -> +99:59 (999.99s)"
PLAYER_STAT_VALUE_BASELINES = {
    PlayerStatFormat.FLAT: "999,999",
    PlayerStatFormat.PERCENT: "999.9%",
    PlayerStatFormat.MULTIPLIER: "999.9x",
}


def _reserve_label_baseline_width(label, baseline: str, padding: int = SUMMARY_LABEL_BASELINE_PADDING) -> None:
    metrics = QFontMetrics(label.font())
    width = max(metrics.horizontalAdvance(baseline), metrics.horizontalAdvance(label.text()))
    label.setMinimumWidth(max(label.minimumWidth(), width + padding))


def _retain_hidden_widget_size(widget) -> None:
    policy = widget.sizePolicy()
    policy.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(policy)


def _build_chests_stats_card():
    card = QFrame()
    card.setObjectName("StatCard")
    layout = QFormLayout(card)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setHorizontalSpacing(6)
    layout.setVerticalSpacing(4)
    values = {}
    for key, title in (
        ("maps", "Maps"),
        ("total", "Total"),
        ("paid_free", "Paid / Free"),
        ("key_procs", "Key Procs"),
        ("expected", "Expected"),
        ("keys", "Keys"),
    ):
        value_label = QLabel("--")
        value_label.setMinimumWidth(LIVE_STATS_VALUE_WIDTH)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if key == "maps":
            value_label.setWordWrap(True)
        layout.addRow(title, value_label)
        values[key] = value_label
    return card, values


def _apply_run_summary_baselines(chests_per_minute_label, *labels) -> None:
    if len(labels) == 3:
        powerups_duration_label = None
        in_game_time_label, mob_kills_label, level_label = labels
        kps_averages_label = None
    elif len(labels) == 4:
        powerups_duration_label = None
        in_game_time_label, mob_kills_label, kps_averages_label, level_label = labels
    elif len(labels) == 5:
        powerups_duration_label, in_game_time_label, mob_kills_label, kps_averages_label, level_label = labels
    else:
        raise TypeError("_apply_run_summary_baselines() expects 4, 5, or 6 labels")
    _reserve_label_baseline_width(
        chests_per_minute_label,
        RUN_SUMMARY_LABEL_BASELINES["chests_per_minute"],
    )
    if powerups_duration_label is not None:
        _reserve_label_baseline_width(
            powerups_duration_label,
            RUN_SUMMARY_LABEL_BASELINES["powerups_duration"],
        )
    _reserve_label_baseline_width(
        in_game_time_label,
        RUN_SUMMARY_LABEL_BASELINES["in_game_time"],
    )
    _reserve_label_baseline_width(
        mob_kills_label,
        RUN_SUMMARY_LABEL_BASELINES["mob_kills"],
    )
    if kps_averages_label is not None:
        _reserve_label_baseline_width(
            kps_averages_label,
            RUN_SUMMARY_LABEL_BASELINES["kps_averages"],
        )
    _reserve_label_baseline_width(
        level_label,
        RUN_SUMMARY_LABEL_BASELINES["level"],
    )


def _apply_player_stat_value_baseline(label, value_format) -> None:
    baseline = PLAYER_STAT_VALUE_BASELINES.get(value_format, PLAYER_STAT_VALUE_BASELINES[PlayerStatFormat.FLAT])
    _reserve_label_baseline_width(label, baseline)


def _apply_stage_summary_column_baseline(layout, rows) -> None:
    for column, key in enumerate(("stage", "time", "kills", "items")):
        baseline = STAGE_SUMMARY_COLUMN_BASELINES[key]
        width = 0
        for row in rows:
            label = row[key]
            metrics = QFontMetrics(label.font())
            width = max(width, metrics.horizontalAdvance(baseline), metrics.horizontalAdvance(label.text()))
        layout.setColumnMinimumWidth(column, width + STAGE_SUMMARY_COLUMN_PADDING)


def _apply_powerups_card_baselines(labels_by_name) -> None:
    for label in labels_by_name.values():
        _reserve_label_baseline_width(label, POWERUPS_CARD_LINE_BASELINE)
