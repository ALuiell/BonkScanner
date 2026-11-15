"""Interactive examples for the Recordings page of the Quick Guide."""
from PySide6.QtCore import QLocale, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from projections import formatting
from ui import i18n as l10n
from ui.tabs.player_stats.stat_cards import damage_source_share_text
from ui.timeline_visuals import RUN_A_COLOR, RUN_B_COLOR

from .guide_locale import bind, localization, message, ui
from .recording_guide_timeline import RecordingGuideTimeline
from .run_sample import game_clock, load_run_example


_STYLE = """
QWidget#GuideRecordings { background:#141d29; }
QFrame#GuideRecordingCard { background:#172333; border:1px solid #2d4258; border-radius:11px; }
QLabel#GuideRecordingTitle { background:transparent; color:#d7eaff; font-size:16px; font-weight:700; }
QLabel#GuideRecordingMeta { background:transparent; color:#a7bcd1; font-size:12px; }
QLabel#GuideRecordingMetricName { background:transparent; color:#c6dbef; font-size:12px; }
QLabel#GuideRecordingMetricValue { background:transparent; color:#f0f7ff; font-size:18px; font-weight:700; }
QWidget#GuideRecordingSourceRow { background:transparent; }
QLabel#GuideRecordingSourceName { background:transparent; color:#d7eaff; font-size:13px; font-weight:600; }
QLabel#GuideRecordingSourceValue { background:transparent; color:#f0f7ff; font-size:13px; font-weight:700; }
QPushButton#GuideRecordingAction, QPushButton#GuideRecordingMode {
    background:#1c3046; border:1px solid #38516b; border-radius:6px;
    color:#d7eaff; font-size:12px; padding:4px 8px;
}
QPushButton#GuideRecordingAction:hover, QPushButton#GuideRecordingMode:hover { background:#28445e; }
QPushButton#GuideRecordingMode:checked { background:#31577a; border-color:#5d93c1; color:#fff; }
QPushButton#GuideRecordingAction:focus, QPushButton#GuideRecordingMode:focus { border-color:#7ebcff; }
QProgressBar#GuideRecordingShare { background:#233449; border:0; border-radius:3px; }
QProgressBar#GuideRecordingShare::chunk { background:#69adf2; border-radius:3px; }
"""

_COMPARE_EXAMPLE = (125, 357)


def _label(role):
    label = QLabel()
    label.setObjectName(role)
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    return label


def _card_layout(card):
    card.setObjectName("GuideRecordingCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(6)
    return layout


def _count(value):
    return QLocale(localization().translator.language).toString(value)


def _clock(snapshot):
    seconds = snapshot.game_time_seconds
    return game_clock(seconds if seconds is not None else snapshot.elapsed_seconds)


class _SegmentComparison(QFrame):
    show_example = Signal()

    def __init__(self, snapshots):
        super().__init__()
        self._snapshots = snapshots
        self._positions = None
        self._example_totals = self._totals(*_COMPARE_EXAMPLE)
        self._update = QTimer(self)
        self._update.setSingleShot(True)
        self._update.timeout.connect(self._refresh)

        layout = _card_layout(self)
        heading = QHBoxLayout()
        heading.addWidget(bind(_label("GuideRecordingTitle"), lambda: message("run.compare.title")), 1)
        jump = QPushButton()
        jump.setObjectName("GuideRecordingAction")
        jump.setCursor(Qt.PointingHandCursor)
        jump.setAutoDefault(False)
        bind(jump, lambda: message("run.compare.show"))
        jump.clicked.connect(self.show_example)
        heading.addWidget(jump)
        layout.addLayout(heading)
        self._range = _label("GuideRecordingMeta")
        self._range.setTextFormat(Qt.RichText)
        layout.addWidget(self._range)

        self._values = []
        grid = QGridLayout()
        grid.setContentsMargins(0, 2, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        for column, key in enumerate(("levels", "kills", "items")):
            value = _label("GuideRecordingMetricValue")
            value.setWordWrap(False)
            self._values.append(value)
            grid.addWidget(value, 0, column)
            grid.addWidget(bind(_label("GuideRecordingMetricName"), lambda name=key: message(f"run.compare.{name}")), 1, column)
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        layout.addWidget(bind(_label("GuideRecordingMeta"), lambda: message("run.compare.keys")))
        layout.addStretch(1)
        l10n.RefreshBinding(self, self._refresh)

    def set_positions(self, a, b):
        positions = (a, b) if b is not None else None
        if positions == self._positions:
            return
        self._positions = positions
        if positions is None or positions == _COMPARE_EXAMPLE:
            self._update.stop()
            self._refresh()
        else:
            # Item history can cover hundreds of snapshots. Update it once
            # the cursors settle while the chart continues to scrub normally.
            self._update.start(85)

    def _totals(self, a, b):
        low, high = sorted((a, b))
        segment = self._snapshots[low:high + 1]
        changes = formatting.summarize_item_segment_changes(segment)
        return (
            formatting.segment_counter_delta(segment, "player_level"),
            formatting.segment_counter_delta(segment, "mob_kills"),
            sum(count for _, count in changes["gained"]),
            sum(count for _, count in changes["lost"]),
        )

    def _refresh(self):
        a, b = self._positions or _COMPARE_EXAMPLE
        marker_a = f'<b style="color:{RUN_A_COLOR.name()}">A</b> {_clock(self._snapshots[a])}'
        marker_b = f'<b style="color:{RUN_B_COLOR.name()}">B</b> {_clock(self._snapshots[b])}'
        span = f"{marker_a} → {marker_b}"
        self._range.setText(message("run.compare.example", span=span) if self._positions is None else span)
        levels, kills, gains, lost = self._example_totals if (a, b) == _COMPARE_EXAMPLE else self._totals(a, b)
        totals = (
            f"+{_count(levels)}" if levels is not None else "—",
            f"+{_count(kills)}" if kills is not None else "—",
            f"+{_count(gains)} / −{_count(lost)}",
        )
        for label, value in zip(self._values, totals, strict=True):
            label.setText(value)


class _DamageSources(QFrame):
    def __init__(self, example):
        super().__init__()
        self._separate_run = example.damage_example is not None
        self._snapshot = example.damage_example or example.snapshots[-1]
        self._metric = "damage"
        layout = _card_layout(self)
        heading = QHBoxLayout()
        heading.setSpacing(5)
        heading.addWidget(bind(_label("GuideRecordingTitle"), lambda: ui("Damage Sources")), 1)
        self._modes = QButtonGroup(self)
        for key, caption in (("damage", "Damage"), ("kills", "Kills")):
            button = QPushButton()
            button.setObjectName("GuideRecordingMode")
            button.setProperty("metric", key)
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
            button.setCheckable(True)
            button.setChecked(key == self._metric)
            bind(button, lambda text=caption: ui(text))
            button.clicked.connect(lambda _checked, mode=key: self._set_metric(mode))
            self._modes.addButton(button)
            heading.addWidget(button)
        layout.addLayout(heading)

        self._source = _label("GuideRecordingMeta")
        layout.addWidget(self._source)
        self._rows = []
        for _ in range(2):
            row = QWidget()
            row.setObjectName("GuideRecordingSourceRow")
            section = QVBoxLayout(row)
            section.setContentsMargins(0, 0, 0, 0)
            section.setSpacing(4)
            values = QHBoxLayout()
            name = _label("GuideRecordingSourceName")
            value = QLabel()
            value.setObjectName("GuideRecordingSourceValue")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            values.addWidget(name, 1)
            values.addWidget(value)
            section.addLayout(values)
            bar = QProgressBar()
            bar.setObjectName("GuideRecordingShare")
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            section.addWidget(bar)
            layout.addWidget(row)
            self._rows.append((row, name, value, bar))
        layout.addStretch(1)
        l10n.RefreshBinding(self, self._refresh)

    def _set_metric(self, metric):
        self._metric = metric
        self._refresh()

    def _refresh(self):
        sources = self._snapshot.damage_sources
        values = tuple((source, getattr(source, self._metric)) for source in sources)
        ranked = sorted(
            ((source, value) for source, value in values if value is not None),
            key=lambda row: (-row[1], row[0].source_name.casefold()),
        )
        total = sum(value for _, value in ranked) if len(ranked) == len(values) else None
        if not ranked and self._metric == "kills":
            self._source.setText(str(l10n.tr("Kill data unavailable")))
        else:
            time = _clock(self._snapshot)
            self._source.setText(message("run.damage.source", time=time) if self._separate_run else time)
        for index, (row, name, value_label, bar) in enumerate(self._rows):
            row.setVisible(index < len(ranked))
            if index >= len(ranked):
                continue
            source, value = ranked[index]
            name.setText(str(l10n.game_term(source.source_name, ("damage_sources", "weapons", "items", "passives"))))
            share = damage_source_share_text(value, total)
            display = _count(value) if self._metric == "kills" else formatting.format_damage_source_value(value)
            value_label.setText(f"{display} · {share}" if total is not None else display)
            bar.setVisible(total is not None)
            bar.setValue(round(1000 * value / total) if total else 0)


class RecordingsGuidePreview(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("GuideRecordings")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet(_STYLE)
        self._columns = 0
        example = load_run_example()
        self._timeline = RecordingGuideTimeline(example)
        self._comparison = _SegmentComparison(example.snapshots)
        self._damage = _DamageSources(example)
        self._timeline.positions_changed.connect(self._comparison.set_positions)
        self._comparison.show_example.connect(lambda: self._timeline.show_segment(*_COMPARE_EXAMPLE))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(self._timeline)
        self._details = QGridLayout()
        self._details.setSpacing(12)
        self._reflow()
        layout.addLayout(self._details)
        layout.addStretch(1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow()

    def _reflow(self):
        columns = 1 if self.width() < 620 else 2
        if columns == self._columns:
            return
        self._columns = columns
        self._details.removeWidget(self._comparison)
        self._details.removeWidget(self._damage)
        self._details.addWidget(self._comparison, 0, 0)
        self._details.addWidget(self._damage, 1 if columns == 1 else 0, columns - 1)
        self._details.setColumnStretch(0, 1)
        self._details.setColumnStretch(1, int(columns == 2))
