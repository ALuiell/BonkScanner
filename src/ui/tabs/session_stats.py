"""The Session Stats tab, as an owned view.

What was here before was four ``QGroupBox``es of ``QLabel``s, each holding a
whole sentence: ``"Session Rerolls: 3412"``, ``"Best Map Found: Shady: 2, Moai:
4, Microwaves: 6, Boss: 1, Magnet: 3, Score: 87.5"``. Three things came out of
reading it against the data behind it.

**Two numbers the app already computes were shown nowhere.**
``SessionStats.found_seed_count()`` exists because the tracked-item percentages
need it, and ``config.TOTAL_REROLLS`` is incremented and persisted on every
reroll -- neither reached any tab. Between them they answer the question the
tool is run for, which is rerolls per seed, and that was not on screen either.

**Best and Worst could not be compared.** They were two sentences of six values
each, so telling them apart meant parsing the same string twice. They are two
cards of the same rows now, and `map_scoring.map_highlight_rows` is what hands
over the parts rather than the prose.

**Tracked items lost the half of the rule that matters.** A rule is a set of
items *and* a condition -- ``map_1_only`` or ``all_run``, the only two the
settings dialog can produce. The tab showed ``format_tracked_item_rows_for_stats_tab``'s
join, in which the condition survived only as a ``T1`` suffix on one of the two
modes. Here the items are rarity chips and the condition is a badge, and the
rule's *label* is gone from the display entirely: it is always built from those
same item names and that same mode, so printing it above the chips repeated it.

Why the tab is a view object and not more scanner methods
========================================================

`Scanner` owns the scan lifecycle. It built these widgets and wrote to them by
name because that is where the session counters live, not because rendering a
table of averages is its job -- and the renderer this needs (bars, chips,
badges, an empty state) is several times the size of the one it replaces. The
scanner keeps the numbers and calls the five setters below; nothing in here
knows what a scan is.
"""

from __future__ import annotations

from typing import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.map_scoring import map_highlight_rows
from projections import formatting
from ui.shared import _apply_button_icon, _clear_layout, _make_scroll_section, _set_text

#: The two conditions the settings dialog can produce. Everything else in
#: `TrackedItemRule.mode` is unreachable from the UI, so the badge only ever
#: shows one of these two.
CONDITION_LABELS = {
    "map_1_only": "Map 1",
    "all_run": "All run",
}


def condition_label(mode: str) -> str:
    """The badge text for a rule's mode."""
    return CONDITION_LABELS.get(str(mode or ""), "All run")


def rerolls_per_seed(rerolls: int, seeds_found: int) -> str:
    """`rerolls / seeds`, or a dash when no seed has been found yet.

    Pure and named because it is the number the tab exists to show and the one
    thing on it that is not read straight off a counter.
    """
    if seeds_found <= 0:
        return "--"
    return f"{int(round(rerolls / seeds_found)):,}"


def average_bar_fractions(averages: Sequence[float]) -> list[float]:
    """Each average as a fraction of the largest, for the bars.

    Against the largest rather than a fixed ceiling: the question a reader has
    is which target is eating the rerolls, which is a comparison between rows
    and not against any absolute number.
    """
    values = [max(0.0, float(value)) for value in averages]
    ceiling = max(values, default=0.0)
    if ceiling <= 0.0:
        return [0.0 for _ in values]
    return [value / ceiling for value in values]


class SessionStatsTab:
    """Session Stats: the KPI strip, both map cards and the two tables."""

    def __init__(self, *, on_open_tracked_item_settings: Callable[[], None]) -> None:
        self._on_open_tracked_item_settings = on_open_tracked_item_settings

        self._root = None
        self._kpi_values: dict[str, QLabel] = {}
        self._chip_values: dict[str, QLabel] = {}
        self._best_score = None
        self._worst_score = None
        self._best_rows_layout = None
        self._worst_rows_layout = None
        self._tracked_layout = None
        self._tracked_empty = None
        self._averages_layout = None
        self._averages_empty = None

        # What the scanner has handed over so far, so a setter that only knows
        # part of the state can re-render the whole strip.
        self._rerolls = 0
        self._seeds_found = 0

    @property
    def root_widget(self):
        return self._root

    # -- construction ---------------------------------------------------------

    def build(self) -> QWidget:
        self._root = QWidget()
        outer = QVBoxLayout(self._root)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll, _content, layout = _make_scroll_section()
        outer.addWidget(scroll)
        layout.setSpacing(10)

        layout.addWidget(self._build_kpi_card())
        layout.addLayout(self._build_map_cards())
        layout.addLayout(self._build_tables())
        layout.addStretch(1)
        return self._root

    def _build_kpi_card(self) -> QFrame:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(0)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(14)
        for column, (key, caption) in enumerate(
            (
                ("time", "Session Time"),
                ("rerolls", "Rerolls"),
                ("seeds", "Seeds Found"),
                ("rpm", "Rerolls / min"),
            )
        ):
            grid.addWidget(_eyebrow(caption), 0, column)
            value = QLabel("--")
            value.setObjectName("kpiValueHero")
            self._kpi_values[key] = value
            grid.addWidget(value, 1, column)
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)

        layout.addSpacing(12)
        layout.addWidget(_divider())
        layout.addSpacing(10)

        chips = QHBoxLayout()
        chips.setContentsMargins(0, 0, 0, 0)
        chips.setSpacing(26)
        for key, caption in (
            ("per_seed", "Rerolls / seed"),
            ("all_time", "All-time rerolls"),
        ):
            chip = QHBoxLayout()
            chip.setContentsMargins(0, 0, 0, 0)
            chip.setSpacing(7)
            chip.addWidget(_eyebrow(caption))
            value = QLabel("--")
            value.setObjectName("chipValue")
            self._chip_values[key] = value
            chip.addWidget(value)
            chips.addLayout(chip)
        chips.addStretch(1)
        layout.addLayout(chips)
        return card

    def _build_map_cards(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        for kind, caption in (("best", "Best map"), ("worst", "Worst map")):
            card = _card()
            layout = QVBoxLayout(card)
            layout.setContentsMargins(14, 12, 14, 12)
            layout.setSpacing(8)

            header = QHBoxLayout()
            header.setContentsMargins(0, 0, 0, 0)
            title = QLabel(caption.upper())
            title.setObjectName(f"mapTitle{kind.capitalize()}")
            score = QLabel("--")
            score.setObjectName(f"mapScore{kind.capitalize()}")
            score.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            header.addWidget(title)
            header.addStretch(1)
            header.addWidget(score)
            layout.addLayout(header)

            rows = QVBoxLayout()
            rows.setContentsMargins(0, 0, 0, 0)
            rows.setSpacing(2)
            layout.addLayout(rows)
            layout.addStretch(1)

            if kind == "best":
                self._best_score, self._best_rows_layout = score, rows
            else:
                self._worst_score, self._worst_rows_layout = score, rows
            row.addWidget(card, 1)
        return row

    def _build_tables(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)

        tracked = _card()
        tracked_layout = QVBoxLayout(tracked)
        tracked_layout.setContentsMargins(14, 12, 14, 12)
        tracked_layout.setSpacing(0)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(_eyebrow("Tracked items"))
        head.addStretch(1)
        gear = QPushButton("")
        gear.setObjectName("iconBtn")
        gear.setToolTip("Tracked item settings")
        gear.setFixedSize(28, 26)
        _apply_button_icon(gear, "media/settings_icon.png", 16)
        gear.clicked.connect(lambda _checked=False: self._on_open_tracked_item_settings())
        head.addWidget(gear)
        tracked_layout.addLayout(head)
        tracked_layout.addSpacing(6)
        self._tracked_layout = QVBoxLayout()
        self._tracked_layout.setContentsMargins(0, 0, 0, 0)
        self._tracked_layout.setSpacing(0)
        tracked_layout.addLayout(self._tracked_layout)
        self._tracked_empty = QLabel("No tracked items configured")
        self._tracked_empty.setObjectName("tableEmpty")
        tracked_layout.addWidget(self._tracked_empty)
        tracked_layout.addStretch(1)
        row.addWidget(tracked, 1)

        averages = _card()
        averages_layout = QVBoxLayout(averages)
        averages_layout.setContentsMargins(14, 12, 14, 12)
        averages_layout.setSpacing(0)
        averages_layout.addWidget(_eyebrow("Average rerolls per target"))
        averages_layout.addSpacing(6)
        self._averages_layout = QVBoxLayout()
        self._averages_layout.setContentsMargins(0, 0, 0, 0)
        self._averages_layout.setSpacing(4)
        averages_layout.addLayout(self._averages_layout)
        self._averages_empty = QLabel("No active targets")
        self._averages_empty.setObjectName("tableEmpty")
        averages_layout.addWidget(self._averages_empty)
        averages_layout.addStretch(1)
        row.addWidget(averages, 1)
        return row

    # -- the scanner's writers -----------------------------------------------

    def set_session_clock(self, *, elapsed_text: str, rpm: float) -> None:
        _set_text(self._kpi_values.get("time"), elapsed_text)
        _set_text(self._kpi_values.get("rpm"), f"{rpm:.1f}")

    def set_counters(self, *, rerolls: int, seeds_found: int, all_time_rerolls: int) -> None:
        self._rerolls = max(0, int(rerolls))
        self._seeds_found = max(0, int(seeds_found))
        _set_text(self._kpi_values.get("rerolls"), f"{self._rerolls:,}")
        _set_text(self._kpi_values.get("seeds"), f"{self._seeds_found:,}")
        _set_text(
            self._chip_values.get("per_seed"),
            rerolls_per_seed(self._rerolls, self._seeds_found),
        )
        _set_text(self._chip_values.get("all_time"), f"{max(0, int(all_time_rerolls)):,}")

    def set_map_highlights(self, *, best_stats, worst_stats, active_templates) -> None:
        for stats, score_label, rows_layout, kind in (
            (best_stats, self._best_score, self._best_rows_layout, "best"),
            (worst_stats, self._worst_score, self._worst_rows_layout, "worst"),
        ):
            if rows_layout is None:
                continue
            _clear_layout(rows_layout)
            if not stats:
                _set_text(score_label, "--")
                placeholder = QLabel("No map yet")
                placeholder.setObjectName("tableEmpty")
                rows_layout.addWidget(placeholder)
                continue
            rows, score = map_highlight_rows(stats, active_templates)
            _set_text(score_label, f"{score:.1f}")
            for name, value in rows:
                rows_layout.addWidget(_stat_row(name, str(value), kind))

    def set_average_rows(self, rows) -> None:
        """`rows` is `(name, colour, average, found_count)`, already ordered."""
        if self._averages_layout is None:
            return
        _clear_layout(self._averages_layout)
        rows = list(rows or ())
        if self._averages_empty is not None:
            self._averages_empty.setVisible(not rows)
        fractions = average_bar_fractions([average for _n, _c, average, _f in rows])
        for (name, colour, average, found), fraction in zip(rows, fractions):
            self._averages_layout.addWidget(
                _average_row(name, colour, average, found, fraction)
            )

    def set_tracked_rows(self, rows) -> None:
        """`rows` is the tracker's, with `item_names`, `mode`, `count`, `percent`."""
        if self._tracked_layout is None:
            return
        _clear_layout(self._tracked_layout)
        rows = list(rows or ())
        if self._tracked_empty is not None:
            self._tracked_empty.setVisible(not rows)
        for index, row in enumerate(rows):
            self._tracked_layout.addWidget(
                _tracked_row(row, last=index == len(rows) - 1)
            )


# -- row builders -------------------------------------------------------------


def _card() -> QFrame:
    card = QFrame()
    card.setObjectName("card")
    return card


def _divider() -> QFrame:
    line = QFrame()
    line.setObjectName("LiveStatsItemsDivider")
    line.setFrameShape(QFrame.HLine)
    return line


def _eyebrow(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("kpiLabel")
    return label


def _stat_row(name: str, value: str, kind: str) -> QWidget:
    row = QWidget()
    row.setObjectName("cardContent")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 1, 0, 1)
    layout.setSpacing(8)
    label = QLabel(name)
    label.setObjectName("rowLabel")
    value_label = QLabel(value)
    value_label.setObjectName("mapValueBest" if kind == "best" else "mapValueWorst")
    value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    layout.addWidget(label)
    layout.addStretch(1)
    layout.addWidget(value_label)
    return row


def _average_row(name: str, colour: str, average: float, found: int, fraction: float) -> QWidget:
    row = QWidget()
    row.setObjectName("cardContent")
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 2, 0, 2)
    layout.setSpacing(10)

    name_label = QLabel(name)
    name_label.setObjectName("averageName")
    name_label.setStyleSheet(f"color: {colour};")
    name_label.setMinimumWidth(96)
    layout.addWidget(name_label, 1)

    value_label = QLabel(f"{average:.1f}" if found else "N/A")
    value_label.setObjectName("rowValue")
    value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    value_label.setMinimumWidth(38)
    layout.addWidget(value_label)

    layout.addWidget(_bar(fraction, colour), 1)

    found_label = QLabel(f"{found}")
    found_label.setObjectName("averageFound")
    found_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    found_label.setMinimumWidth(28)
    layout.addWidget(found_label)
    return row


def _bar(fraction: float, colour: str) -> QWidget:
    """A 6px track with a proportional fill, laid out rather than painted.

    Two stretches in a box: no custom `paintEvent`, and the fill follows the
    row's width for free. The same shape the Damage Sources bars use.
    """
    track = QWidget()
    track.setObjectName("barTrack")
    track.setFixedHeight(6)
    layout = QHBoxLayout(track)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(0)
    fill = QWidget()
    fill.setObjectName("barFill")
    fill.setStyleSheet(f"background-color: {colour}; border-radius: 3px;")
    filled = max(0, min(1000, int(round(fraction * 1000))))
    layout.addWidget(fill, filled)
    if filled < 1000:
        layout.addStretch(1000 - filled)
    return track


def _tracked_row(row, *, last: bool) -> QWidget:
    widget = QWidget()
    widget.setObjectName("trackedRow" if not last else "trackedRowLast")
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 7, 0, 7)
    layout.setSpacing(8)

    chips = QWidget()
    chips.setObjectName("cardContent")
    chips_layout = QHBoxLayout(chips)
    chips_layout.setContentsMargins(0, 0, 0, 0)
    chips_layout.setSpacing(5)
    item_names = tuple(row.get("item_names") or ())
    if not item_names:
        # A rule with no items cannot exist through the dialog, but the row
        # comes from persisted config -- so it degrades to the label rather
        # than rendering an empty strip.
        fallback = QLabel(str(row.get("label") or "Item"))
        fallback.setObjectName("rowLabel")
        chips_layout.addWidget(fallback)
    for index, item_name in enumerate(item_names):
        if index:
            plus = QLabel("+")
            plus.setObjectName("chipPlus")
            chips_layout.addWidget(plus)
        display_text, object_name = formatting.item_chip_display(str(item_name))
        chip = QLabel(display_text)
        chip.setObjectName(object_name)
        chips_layout.addWidget(chip)
    chips_layout.addStretch(1)
    layout.addWidget(chips, 1)

    badge = QLabel(condition_label(row.get("mode")))
    badge.setObjectName(
        "condBadge" if str(row.get("mode")) == "map_1_only" else "condBadgeMuted"
    )
    layout.addWidget(badge)

    count = QLabel(f"{int(row.get('count') or 0)}")
    count.setObjectName("trackedCount")
    count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    count.setMinimumWidth(28)
    layout.addWidget(count)

    percent = row.get("percent")
    rate = QLabel("--" if percent is None else f"{float(percent):.0f}%")
    rate.setObjectName("trackedRate" if percent is not None else "trackedRateMuted")
    rate.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
    rate.setMinimumWidth(40)
    layout.addWidget(rate)
    return widget
