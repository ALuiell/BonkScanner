"""Compact Roll Analytics examples with the recording's confirmed counts."""
from PySide6.QtCore import QLocale, QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QBoxLayout, QButtonGroup, QFrame, QGridLayout, QHeaderView, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from core.roll_analysis_view import expected_rolls, recorded_source_from_snapshot
from ui import i18n as l10n
from ui.shared import resource_path

from .guide_locale import bind, localization, message
from .run_sample import game_clock, load_run_example


_STYLE = """
QFrame#rollAnalyticsGuidePreview {background:#172333; border:1px solid #2d4258; border-radius:11px;}
QLabel#GuideRollContext, QLabel#GuideRollSummaryName {background:transparent; color:#a7bcd1; font-size:12px;}
QLabel#GuideRollSummaryValue {background:transparent; color:#f0f7ff; font-size:20px; font-weight:700;}
QPushButton#RollAnalyticsSource {
    background:#1c3046; border:1px solid #38516b; border-radius:6px;
    color:#d7eaff; font-size:12px; font-weight:600; padding:5px 9px;
}
QPushButton#RollAnalyticsSource:hover {background:#28445e;}
QPushButton#RollAnalyticsSource:checked {background:#31577a; border-color:#5d93c1; color:#fff;}
QPushButton#RollAnalyticsSource:focus {border-color:#7ebcff;}
QTableWidget#GuideRollTable {
    background:#142131; alternate-background-color:#19293a; color:#e4edf5;
    border:1px solid #30445a; border-radius:6px; font-size:13px;
}
QTableWidget#GuideRollTable::item {border:0; padding:0 6px;}
QTableWidget#GuideRollTable QHeaderView::section {
    background:#1d3044; color:#c7daee; border:0; border-bottom:1px solid #30445a;
    font-size:12px; font-weight:700; padding:3px 6px;
}
"""

_ROW_HEIGHT = 21


def _recording_example():
    example = load_run_example()
    for snapshot in reversed(example.snapshots):
        dice = recorded_source_from_snapshot(snapshot, "dice")
        chaos = recorded_source_from_snapshot(snapshot, "chaos")
        if dice.analytics is not None and chaos.analytics is not None:
            seconds = dice.game_time_seconds if dice.game_time_seconds is not None else dice.elapsed_seconds
            return example.character, game_clock(seconds or 0), {"dice": dice.analytics, "chaos": chaos.analytics}
    raise ValueError("The guide recording needs confirmed Dice and Chaos Tome counters")


def _wrapped_label(role):
    label = QLabel()
    label.setObjectName(role)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return label


class _RollTable(QTableWidget):
    def __init__(self):
        super().__init__(0, 4)
        self.setObjectName("GuideRollTable")
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionMode(QTableWidget.NoSelection)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFocusPolicy(Qt.NoFocus)
        self.verticalHeader().hide()
        self.verticalHeader().setMinimumSectionSize(_ROW_HEIGHT)
        self.verticalHeader().setDefaultSectionSize(_ROW_HEIGHT)
        self.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in range(1, self.columnCount()):
            self.horizontalHeader().setSectionResizeMode(column, QHeaderView.Fixed)

    def wheelEvent(self, event):
        # Scrolling belongs to the guide page, including over table rows.
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            parent.wheelEvent(event)
        else:
            super().wheelEvent(event)

    def set_rows(self, rows, expected, locale):
        self.setUpdatesEnabled(False)
        try:
            self.setHorizontalHeaderLabels((str(l10n.tr("Stat")), message("roll.guide.rolls"), str(l10n.tr("Share")), "Δ"))
            self.horizontalHeaderItem(2).setToolTip(str(l10n.tr("Share of all confirmed rolls for this source.")))
            self.horizontalHeaderItem(3).setToolTip(message("roll.guide.delta_note"))
            self.setRowCount(len(rows))
            for index, row in enumerate(rows):
                name = str(l10n.stat(row.label))
                count = locale.toString(row.count)
                share = f"{locale.toString(row.percent, 'f', 1)}%" if row.percent is not None else "—"
                delta = "—"
                if expected is not None:
                    difference = row.count - expected
                    sign = "+" if difference >= 0.05 else "−" if difference <= -0.05 else ""
                    delta = sign + locale.toString(abs(difference), "f", 1)
                for column, text in enumerate((name, count, share, delta)):
                    item = QTableWidgetItem(text)
                    item.setTextAlignment((Qt.AlignLeft if column == 0 else Qt.AlignRight) | Qt.AlignVCenter)
                    item.setToolTip(name if column == 0 else text)
                    self.setItem(index, column, item)
            self.ensurePolished()
            for column in range(1, self.columnCount()):
                heading = self.horizontalHeader().sectionSizeHint(column)
                self.setColumnWidth(column, max(37, heading, self.sizeHintForColumn(column) + 4))
            self.setFixedHeight(self.horizontalHeader().sizeHint().height() + len(rows) * _ROW_HEIGHT + 2)
        finally:
            self.setUpdatesEnabled(True)


class _RollPreview(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("rollAnalyticsGuidePreview")
        self.setStyleSheet(_STYLE)
        self._character, self._clock, self._snapshots = _recording_example()
        self._source = "dice"
        self._two_columns = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        self._header = QBoxLayout(QBoxLayout.LeftToRight)
        self._header.setSpacing(7)
        self._source_layout = QBoxLayout(QBoxLayout.LeftToRight)
        self._source_layout.setSpacing(7)
        self._header.addLayout(self._source_layout)
        self._buttons = QButtonGroup(self)
        for source, caption, icon in (
            ("dice", "Dice passive", "roll_dice.svg"), ("chaos", "Chaos Tome", "roll_chaos.svg"),
        ):
            button = QPushButton(QIcon(resource_path(f"media/{icon}")), "")
            title = l10n.tr(caption)
            if source == "dice":
                bind(button, lambda: message("roll.guide.dice_source"))
            else:
                l10n.display(button, "setText", title)
            l10n.display(button, "setToolTip", title)
            l10n.display(button, "setAccessibleName", title)
            button.setObjectName("RollAnalyticsSource")
            button.setProperty("source", source)
            button.setIconSize(QSize(15, 15))
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            button.setCheckable(True)
            button.setChecked(source == self._source)
            button.clicked.connect(lambda _checked, name=source: self._select_source(name))
            self._buttons.addButton(button)
            self._source_layout.addWidget(button)
        self._context = _wrapped_label("GuideRollContext")
        self._context.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._header.addWidget(self._context, 1)
        layout.addLayout(self._header)

        summary = QGridLayout()
        summary.setHorizontalSpacing(10)
        summary.setVerticalSpacing(1)
        self._summary_values = []
        for column, key in enumerate(("confirmed", "chance", "expected")):
            name = bind(_wrapped_label("GuideRollSummaryName"), lambda item=key: message(f"roll.guide.{item}"))
            value = _wrapped_label("GuideRollSummaryValue")
            summary.addWidget(name, 0, column)
            summary.addWidget(value, 1, column)
            summary.setColumnStretch(column, 1)
            self._summary_values.append(value)
        layout.addLayout(summary)

        tables = QBoxLayout(QBoxLayout.LeftToRight)
        tables.setSpacing(8)
        self._tables = (_RollTable(), _RollTable())
        for table in self._tables:
            tables.addWidget(table, 1, Qt.AlignTop)
        layout.addLayout(tables)
        layout.addStretch(1)

        l10n.RefreshBinding(self, self._refresh)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        old_columns = self._two_columns
        self._two_columns = self.width() >= 610
        self._fit_header()
        if old_columns != self._two_columns:
            self._refresh_tables()

    def _fit_header(self):
        buttons_width = sum(button.sizeHint().width() for button in self._buttons.buttons())
        horizontal = self.width() >= buttons_width + 220
        self._header.setDirection(QBoxLayout.LeftToRight if horizontal else QBoxLayout.TopToBottom)
        self._source_layout.setDirection(
            QBoxLayout.LeftToRight if self.width() >= buttons_width + 33 else QBoxLayout.TopToBottom,
        )
        self._context.setAlignment(Qt.AlignRight | Qt.AlignVCenter if horizontal else Qt.AlignLeft)

    def _select_source(self, source):
        self._source = source
        self._refresh()

    def _refresh(self):
        snapshot = self._snapshots[self._source]
        character = str(l10n.game("characters", self._character))
        stamp = message("run.live_snapshot", character=character, time=self._clock)
        self._context.setText(f"{stamp} · {message('roll.guide.stat_count', count=len(snapshot.rows))}")
        locale = QLocale(localization().translator.language)
        expected = expected_rolls(snapshot.source, snapshot.total, (snapshot.rows[0].stat_id,))
        metrics = (locale.toString(snapshot.total), "—", "—")
        if expected is not None:
            chance = locale.toString(expected / snapshot.total * 100, 'f', 1)
            metrics = (metrics[0], f"{chance}%", locale.toString(expected, 'f', 1))
        for label, value in zip(self._summary_values, metrics, strict=True):
            label.setText(value)
        self._summary_values[1].setToolTip(message("roll.guide.model_note"))
        self._summary_values[2].setToolTip(message("roll.guide.model_note"))
        self._fit_header()
        self._refresh_tables()

    def _refresh_tables(self):
        snapshot = self._snapshots[self._source]
        rows = snapshot.rows
        locale = QLocale(localization().translator.language)
        expected = expected_rolls(snapshot.source, snapshot.total, (rows[0].stat_id,))
        left, right = self._tables
        split = (len(rows) + 1) // 2 if self._two_columns else len(rows)
        left.set_rows(rows[:split], expected, locale)
        right.setVisible(self._two_columns)
        if self._two_columns:
            right.set_rows(rows[split:], expected, locale)


def build_roll_analytics_preview() -> QFrame:
    return _RollPreview()
