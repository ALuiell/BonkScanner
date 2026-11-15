"""Readable, interactive Roll Analytics example built from the Scanner's view."""
from types import SimpleNamespace

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QBoxLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QScrollArea, QSizePolicy, QTableView, QVBoxLayout, QWidget,
)

from core.roll_analytics import ROLL_STATS, aggregate_roll_counts, confirmed_roll_counts
from .guide_locale import bind, message
from .run_sample import game_clock, load_run_example
from ui import i18n as l10n
from ui.dialogs.roll_analytics import RollAnalyticsWindow


_STAT_NAMES = dict(ROLL_STATS)
_COLUMN_GROUPS = (tuple(range(5)), tuple(range(6, 11)))
_STYLE = """
QFrame#rollAnalyticsGuidePreview {background:#101925; border:1px solid #2b3c50; border-radius:10px;}
QLabel#GuideRollContext, QLabel#GuideRollSort {background:transparent; color:#b7cadc; font-size:12px;}
QWidget#GuideRollTables {background:transparent;}
QTableView#GuideRollTable {
    background:#101923; alternate-background-color:#162130; color:#e4edf5;
    border:1px solid #32445a; border-radius:6px; font-size:14px;
}
QTableView#GuideRollTable QHeaderView::section {
    background:#1a2a3b; color:#c7daee; font-size:12px; font-weight:700;
    border:0; border-bottom:1px solid #32445a; padding:5px 7px;
}
"""


class _ExampleService:
    def __init__(self):
        example = load_run_example()
        self.character = example.character
        for snapshot in reversed(example.snapshots):
            counts = confirmed_roll_counts(snapshot.chaos_tome, snapshot.character_passive)
            if "dice" in counts and "chaos" in counts:
                self.clock = game_clock(snapshot.game_time_seconds or snapshot.elapsed_seconds)
                self._snapshots = {
                    source: aggregate_roll_counts(source, rows) for source, rows in counts.items()
                }
                break
        else:
            raise ValueError("The guide recording needs confirmed Dice and Chaos Tome counters")

    def status(self):
        return SimpleNamespace(error=None, revision=1)

    def set_collection_active(self, _active):
        pass

    def snapshot(self, source):
        return self._snapshots[source]


class _ExampleAnalytics(RollAnalyticsWindow):
    """Keep production formatting, sorting and calculations on the sample."""

    def _save_preferences(self, selected, expected):
        self._selected = frozenset(selected)
        self._show_expected = bool(expected)
        self._last_key = None
        self.refresh()

    def translate_stats(self):
        for column in (0, 6):
            for row in range(self._table.rowCount()):
                item = self._table.item(row, column)
                name = _STAT_NAMES.get(item.data(Qt.UserRole))
                if name:
                    l10n.display(item, "setText", l10n.stat(name))


class _RollStatTable(QTableView):
    def wheelEvent(self, event):
        # This table shows every row. Wheel movement belongs to the guide page.
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent is None:
            super().wheelEvent(event)
        else:
            parent.wheelEvent(event)


class _RollTables(QWidget):
    """The two groups in the production table, stacked when width is limited."""

    def __init__(self, analytics, parent):
        super().__init__(parent)
        self.setObjectName("GuideRollTables")
        self._analytics = analytics
        self._layout = QBoxLayout(QBoxLayout.TopToBottom, self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self._views = []
        model = analytics._table.model()
        for columns in _COLUMN_GROUPS:
            view = _RollStatTable(self)
            view.setObjectName("GuideRollTable")
            view.setModel(model)
            view.setAlternatingRowColors(True)
            view.setShowGrid(False)
            view.setEditTriggers(QTableView.NoEditTriggers)
            view.setSelectionMode(QTableView.NoSelection)
            view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            view.setFocusPolicy(Qt.NoFocus)
            view.verticalHeader().hide()
            view.verticalHeader().setMinimumSectionSize(28)
            view.verticalHeader().setDefaultSectionSize(28)
            view.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
            header = view.horizontalHeader()
            header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            header.setSectionResizeMode(columns[0], QHeaderView.Stretch)
            for column in columns[1:]:
                header.setSectionResizeMode(column, QHeaderView.Fixed)
            self._views.append(view)
            self._layout.addWidget(view, 1, Qt.AlignTop)

        l10n.RefreshBinding(self, self.refresh)

    def refresh(self):
        self._analytics.translate_stats()
        for view, columns in zip(self._views, _COLUMN_GROUPS, strict=True):
            # The right-hand group has 13 stats. The shared model also has the
            # left group's 14th row, which should only appear in the left view.
            last_row = view.model().rowCount() - 1
            item = self._analytics._table.item(last_row, columns[0])
            view.setRowHidden(last_row, item.data(Qt.UserRole) is None)
        self._fit_tables()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_tables()

    def _fit_tables(self):
        table = self._analytics._table
        model = table.model()
        expected = self._analytics._show_expected
        compact = expected and self.width() < 500
        rolls = message("roll.guide.count_short") if compact else l10n.tr("Rolls")
        reference = message("roll.guide.expected_short") if compact else l10n.tr("Exp.")
        for columns in _COLUMN_GROUPS:
            l10n.display(table.horizontalHeaderItem(columns[1]), "setText", rolls)
            l10n.display(table.horizontalHeaderItem(columns[3]), "setText", reference)

        widths = []
        for view, columns in zip(self._views, _COLUMN_GROUPS, strict=True):
            for column in range(model.columnCount()):
                view.setColumnHidden(column, column not in columns)
            view.setColumnHidden(columns[3], not expected)
            names = (model.index(i, columns[0]).data() or "" for i in range(model.rowCount()))
            name_width = max(
                max(map(view.fontMetrics().horizontalAdvance, names), default=0) + 22,
                view.sizeHintForColumn(columns[0]),
            )
            numeric = {}
            for column in columns[1:]:
                if view.isColumnHidden(column):
                    continue
                width = max(
                    view.sizeHintForColumn(column), view.horizontalHeader().sectionSizeHint(column), 36,
                ) + 3
                view.setColumnWidth(column, width)
                numeric[column] = view.columnWidth(column)
            delta_width = numeric.pop(columns[4])
            values_width = sum(numeric.values())
            show_delta = expected and name_width + values_width + delta_width <= self.width()
            view.setColumnHidden(columns[4], not show_delta)
            widths.append(name_width + values_width + (delta_width if show_delta else 0))
        fits_side_by_side = 2 * max(widths) + self._layout.spacing() <= self.width()
        direction = QBoxLayout.LeftToRight if fits_side_by_side else QBoxLayout.TopToBottom
        if direction != self._layout.direction():
            self._layout.setDirection(direction)

        for view in self._views:
            visible_height = sum(view.rowHeight(row) for row in range(model.rowCount()) if not view.isRowHidden(row))
            view.setFixedHeight(view.horizontalHeader().sizeHint().height() + visible_height + 2)


class _RollPreview(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("rollAnalyticsGuidePreview")
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(11, 9, 11, 11)
        layout.setSpacing(8)

        service = _ExampleService()
        proxy = SimpleNamespace(coordinator=SimpleNamespace(roll_analytics=service), has_premium_access=lambda: True)
        analytics = _ExampleAnalytics(proxy, self)
        context = bind(QLabel(), lambda: message(
            "run.live_snapshot", character=str(l10n.game("characters", service.character)), time=service.clock,
        ))
        context.setObjectName("GuideRollContext")
        layout.addWidget(context)
        self._source_buttons = tuple(analytics._source_buttons.values())
        self._source_frame = self._source_buttons[0].parentWidget()
        self._source_frame.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self._source_frame)

        options = QHBoxLayout()
        options.setSpacing(7)
        sort_label = l10n.localized(QLabel, l10n.tr("Sort by"))
        sort_label.setObjectName("GuideRollSort")
        sort_label.setBuddy(analytics._sort_by)
        options.addWidget(sort_label)
        options.addWidget(analytics._sort_by)
        options.addStretch(1)
        l10n.display(analytics._expected_switch, "setText", l10n.tr("Expected"))
        options.addWidget(analytics._expected_switch)
        layout.addLayout(options)

        summary = analytics._total.parentWidget()
        caption = summary.findChild(QLabel, "kpiLabel")
        l10n.display(caption, "setText", l10n.tr("Rolls"))
        analytics._stat_count.hide()
        stat_count = bind(QLabel(), lambda: message("roll.guide.stat_count", count=len(ROLL_STATS)))
        stat_count.setObjectName("dialogSubtitle")
        summary.layout().addWidget(stat_count)
        layout.addWidget(summary)

        tables = _RollTables(analytics, self)
        for button in self._source_buttons:
            button.clicked.connect(tables.refresh)
        analytics._sort_by.currentIndexChanged.connect(tables.refresh)
        analytics._expected_switch.toggled.connect(tables.refresh)
        layout.addWidget(tables)
        l10n.RefreshBinding(self, self._fit_source_buttons)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_source_buttons()

    def _fit_source_buttons(self):
        tabs = self._source_frame.layout()
        left, _, right, _ = self.layout().getContentsMargins()
        inset = tabs.contentsMargins()
        needed = sum(button.minimumSizeHint().width() for button in self._source_buttons)
        needed += inset.left() + inset.right() + tabs.spacing()
        horizontal = self.width() - left - right - 2 >= needed
        tabs.setDirection(QBoxLayout.LeftToRight if horizontal else QBoxLayout.TopToBottom)


def build_roll_analytics_preview() -> QWidget:
    return _RollPreview()
