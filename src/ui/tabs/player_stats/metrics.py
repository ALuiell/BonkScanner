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
from PySide6.QtWidgets import QFormLayout, QFrame, QGridLayout, QLabel, QVBoxLayout

from core.item_metadata import ITEM_RARITY_COLOR_MAP
from core.luck_rarity import (
    GAME_RARITY_NAMES,
    LUCK_RARITY_MODEL_ATTRIBUTION,
    LUCK_RARITY_ORDER,
)
from core.stats.formats import PlayerStatFormat


LIVE_STATS_CARD_COLUMNS = 3
LIVE_STATS_VALUE_WIDTH = 64
RECORDINGS_STATS_CARD_COLUMNS = 3
RECORDINGS_LIST_MIN_WIDTH = 198
RECORDINGS_LIST_MAX_WIDTH = 288
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


def _build_chests_stats_card(*, include_chests_per_minute: bool = False):
    """Six core rows, plus an optional rate and the shared unavailable line.

    Recordings puts the derived average rate beside the counters in Loot.
    Live Stats already shows that rate in Run Summary, so its shared card keeps
    the original six-row shape.

    The same reason-when-it-can't-fill line the rarity card
    uses below it: `Expected` here fails apart for the same underlying
    reason -- a late attach -- so it gets the same explanation, not a
    second one invented for this card.
    """
    card = QFrame()
    card.setObjectName("StatCard")
    outer = QVBoxLayout(card)
    outer.setContentsMargins(8, 8, 8, 8)
    outer.setSpacing(4)

    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setHorizontalSpacing(6)
    form.setVerticalSpacing(4)
    values = {}
    rows = [
        ("maps", "Maps"),
        ("total", "Total"),
    ]
    if include_chests_per_minute:
        rows.append(("chests_per_minute", "Average chests/min"))
    rows.extend((
        ("paid_free", "Paid / Free"),
        ("key_procs", "Key Procs"),
        ("expected", "Expected"),
        ("keys", "Keys"),
    ))
    for key, title in rows:
        name_label = QLabel(title)
        name_label.setObjectName("LiveStatsLootStatName")
        value_label = QLabel("--")
        value_label.setObjectName("LiveStatsLootStatValue")
        value_label.setMinimumWidth(LIVE_STATS_VALUE_WIDTH)
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if key == "maps":
            value_label.setWordWrap(True)
        form.addRow(name_label, value_label)
        values[key] = value_label
    outer.addLayout(form)

    status_label = QLabel("")
    status_label.setObjectName("LiveStatsMetaText")
    status_label.setWordWrap(True)
    status_label.setVisible(False)
    outer.addWidget(status_label)
    values["status"] = status_label
    return card, values


def _build_loot_rarity_card():
    """Four lines, one per tier: drop chance, actual, expectation.

    Same grouping the `!luck` line uses, so the two read alike -- and the same
    vocabulary, because this is the other surface with words on it. Our internal
    keys are offset by one tier in the middle (`GAME_RARITY_NAMES`), which is
    invisible where colour carries the meaning and wrong here.

    This is also where the *streamer* learns why the numbers are missing.
    Viewers never see the reason; the one person who can act on it does.
    """
    card = QFrame()
    card.setObjectName("StatCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(4)

    grid = QGridLayout()
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(10)
    grid.setVerticalSpacing(4)
    values = {}
    for row, rarity in enumerate(LUCK_RARITY_ORDER):
        name_label = QLabel(GAME_RARITY_NAMES[rarity])
        name_label.setObjectName("LiveStatsLootStatName")
        name_label.setStyleSheet(
            f"color: {ITEM_RARITY_COLOR_MAP.get(rarity, '#E5E7EB')}; font-weight: 700; background: transparent;"
        )
        chance_label = QLabel("--")
        chance_label.setObjectName("LiveStatsLootStatValue")
        chance_label.setMinimumWidth(LIVE_STATS_VALUE_WIDTH)
        chance_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        counts_label = QLabel("--")
        counts_label.setObjectName("LiveStatsLootStatValue")
        counts_label.setMinimumWidth(LIVE_STATS_VALUE_WIDTH)
        counts_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        grid.addWidget(name_label, row, 0)
        grid.addWidget(chance_label, row, 1)
        grid.addWidget(counts_label, row, 2)
        values[rarity] = {"chance": chance_label, "counts": counts_label}
    grid.setColumnStretch(0, 1)
    layout.addLayout(grid)

    status_label = QLabel("")
    status_label.setObjectName("LiveStatsMetaText")
    status_label.setWordWrap(True)
    status_label.setVisible(False)
    layout.addWidget(status_label)
    values["status"] = status_label
    card.setToolTip(LUCK_RARITY_MODEL_ATTRIBUTION)
    return card, values


def _build_empty_placeholder_card():
    """The hole the chests card leaves behind in `Stats`, to be filled later.

    A visible empty card rather than a closed gap: the grid's other cards keep
    their positions, so nothing the user has learned to find by place moves.
    """
    card = QFrame()
    card.setObjectName("StatCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.addStretch(1)
    return card


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
