"""Interactive recording timeline used by the Quick Guide."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QLocale, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QSizePolicy, QToolTip, QVBoxLayout, QWidget

from app.guide_examples import RunExample
from core.localization_context import using_translator
from core.powerup_history import POWERUPS
from projections import scrubber as scrubber_model
from projections.powerup_history import PowerupProjection
from projections.timeline_axis import build_axis_projection
from ui import i18n as l10n
from ui.shared import resource_path
from ui.tabs.player_stats.recording_scrubber import RecordingScrubber
from ui.timeline_controls import TIMELINE_CAP_LABELS

from .guide_locale import localization, message, ui
from .run_sample import game_clock


_STYLE = """
QFrame#GuideRecordingTimeline { background:#172333; border:1px solid #2d4258; border-radius:11px; }
QLabel#GuideTimelineTitle { background:transparent; color:#d7eaff; font-size:16px; font-weight:700; }
QLabel#GuideTimelineSource, QLabel#GuideTimelineMetricName { background:transparent; color:#a7bcd1; font-size:12px; }
QLabel#GuideTimelineMetricValue { background:transparent; color:#f0f7ff; font-size:20px; font-weight:700; }
QCheckBox#GuideTimelinePowerups, QCheckBox#GuideTimelineDiffCap { background:transparent; color:#d7eaff; font-size:12px; spacing:4px; }
QWidget#GuidePowerupReadout, QWidget#GuidePowerupItem, QWidget#GuidePowerupItem QLabel { background:transparent; }
QLabel#GuidePowerupCount { color:#c6dbef; font-size:12px; }
"""

_CLOCK_EFFECT = next(effect[0] for effect in POWERUPS if effect[1] == "Clock")
_MIN_TIME_STOP_SECONDS = 15


class _PowerupItem(QWidget):
    def __init__(self, projection, effect_id, asset):
        super().__init__()
        self.setObjectName("GuidePowerupItem")
        self._projection = projection
        self._effect_id = effect_id
        self._captures = None
        self._estimated = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        icon = QLabel()
        icon.setPixmap(QIcon(resource_path(f"media/powerups/{asset}.svg")).pixmap(13, 13))
        self.count = QLabel()
        self.count.setObjectName("GuidePowerupCount")
        for label in (icon, self.count):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(label)

    def set_value(self, text, captures, *, estimated=False):
        self._captures = captures
        self._estimated = estimated
        self.count.setText(text)

    def event(self, event):
        if event.type() == QEvent.ToolTip and self._captures is not None:
            if self._estimated:
                tooltip = message("run.timeline.time_stop_estimate", seconds=_MIN_TIME_STOP_SECONDS)
            else:
                with using_translator(l10n.active_translator()):
                    tooltip = self._projection.tooltip(self._effect_id, *self._captures)
            QToolTip.showText(event.globalPos(), tooltip, self)
            return True
        return super().event(event)


class _PowerupReadout(QWidget):
    def __init__(self, projection):
        super().__init__()
        self.setObjectName("GuidePowerupReadout")
        self._projection = projection
        self._estimate_clock = not any(
            obs.valid and obs.za_warudo_count is not None and obs.powerups_used is not None
            for obs in projection.observations
        )
        self._long_time_stops = tuple(
            span for span in projection.intervals
            if span.effect_id == _CLOCK_EFFECT and span.seconds > _MIN_TIME_STOP_SECONDS
        )
        self._columns = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(2)
        self._items = {
            effect_id: _PowerupItem(projection, effect_id, asset)
            for effect_id, _, asset, _, _ in POWERUPS
        }
        self.set_columns(2)

    def set_columns(self, columns):
        if columns == self._columns:
            return
        self._columns = columns
        for index, item in enumerate(self._items.values()):
            self._grid.removeWidget(item)
            self._grid.addWidget(item, index // columns, index % columns)

    def set_range(self, capture_a, capture_b):
        if not self._projection.observations:
            for item in self._items.values():
                item.set_value("—", None)
            return
        captures = (capture_a, capture_b)
        counts = self._projection.counts(*captures)
        totals = self._projection.totals(*captures)
        for effect_id, item in self._items.items():
            estimate = effect_id == _CLOCK_EFFECT and self._estimate_clock
            if estimate:
                count, duration = self._time_stop_estimate(*captures)
                quantity = f"≈{count}"
            else:
                unresolved = effect_id == _CLOCK_EFFECT and self._projection.unattributed_clock_events(*captures)
                quantity = f"×{counts.get(effect_id, 0)}{'+' if unresolved else ''}"
                duration = totals[effect_id]
            minutes, seconds = divmod(int(duration), 60)
            item.set_value(f"{quantity} · {minutes}:{seconds:02d}", captures, estimated=estimate)

    def _time_stop_estimate(self, capture_a, capture_b):
        low, high = (float("-inf"), capture_a) if capture_b is None else sorted((capture_a, capture_b))
        count = 0
        duration = 0.0
        for span in self._long_time_stops:
            start, end = max(low, span.start_capture), min(high, span.end_capture)
            if start >= end:
                continue
            seconds = span.seconds
            if start != span.start_capture or end != span.end_capture:
                seconds = self._projection.totals(start, end)[_CLOCK_EFFECT]
            if seconds > _MIN_TIME_STOP_SECONDS:
                count += 1
                duration += seconds
        return count, duration


class RecordingGuideTimeline(QFrame):
    """A local, interactive example using the same plot as Recordings."""

    positions_changed = Signal(int, object)

    def __init__(self, example: RunExample):
        super().__init__()
        self.setObjectName("GuideRecordingTimeline")
        self.setMinimumHeight(255)
        self.setStyleSheet(_STYLE)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._snapshots = example.snapshots
        self._powerups = PowerupProjection(example.vod.powerup_history)
        self._example = example

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 11, 14, 11)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self._title = QLabel()
        self._title.setObjectName("GuideTimelineTitle")
        self._title.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        toolbar.addWidget(self._title, 1)
        self._powerup_control = QCheckBox()
        self._powerup_control.setObjectName("GuideTimelinePowerups")
        self._cap_control = QCheckBox()
        self._cap_control.setObjectName("GuideTimelineDiffCap")
        # These controls are guide-local and never write timeline preferences.
        for control in (self._powerup_control, self._cap_control):
            control.setChecked(True)
            toolbar.addWidget(control)
        layout.addLayout(toolbar)

        header = QHBoxLayout()
        header.setSpacing(8)
        self._source = QLabel()
        self._source.setObjectName("GuideTimelineSource")
        self._source.setWordWrap(True)
        self._source.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        header.addWidget(self._source, 1)
        self._powerup_readout = _PowerupReadout(self._powerups)
        header.addWidget(self._powerup_readout)
        layout.addLayout(header)

        self._scrubber = RecordingScrubber()
        self._scrubber.setObjectName("GuideTimelinePlot")
        self._scrubber.setFixedHeight(150)
        self._keys = ("Difficulty", scrubber_model.KILLS_SERIES, "XP Gain")
        self._scrubber.set_model(
            scrubber_model.build_model(self._snapshots, series_keys=self._keys),
            projection=build_axis_projection(self._snapshots),
        )
        self._scrubber.set_powerups(self._powerups)
        self._scrubber.set_index(min(300, max(0, len(self._snapshots) - 1)))
        layout.addWidget(self._scrubber)

        self._metrics = []
        metrics = QGridLayout()
        metrics.setContentsMargins(0, 0, 0, 0)
        metrics.setHorizontalSpacing(8)
        metrics.setVerticalSpacing(2)
        for column in range(4):
            name = QLabel()
            name.setObjectName("GuideTimelineMetricName")
            name.setWordWrap(True)
            name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            metrics.addWidget(name, 0, column)
            value = QLabel()
            value.setObjectName("GuideTimelineMetricValue")
            value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            metrics.addWidget(value, 1, column)
            metrics.setColumnStretch(column, 1)
            self._metrics.append((name, value))
        layout.addLayout(metrics)

        self._powerup_control.toggled.connect(self._update_controls)
        self._cap_control.toggled.connect(self._update_controls)
        self._scrubber.indexChanged.connect(self._position_changed)
        self._scrubber.pinChanged.connect(self._position_changed)
        self._update_controls()
        l10n.RefreshBinding(self, self._refresh_language)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._powerup_readout.set_columns(2 if event.size().width() < 540 else 4)

    def _refresh_language(self):
        self._title.setText(ui("Timeline"))
        self._scrubber.setAccessibleName(self._title.text())
        self._source.setText(message(
            "run.real_recording", character=str(l10n.game("characters", self._example.character)),
            kills=QLocale(localization().translator.language).toString(self._example.kill_count),
        ))
        self._powerup_control.setText(str(l10n.tr("Powerups")))
        self._cap_control.setText(ui(TIMELINE_CAP_LABELS["Difficulty"]))
        self._update_metrics()

    def _update_controls(self, *_args):
        slots = tuple((key,) for key in self._keys)
        show_powerups = self._powerup_control.isChecked()
        if show_powerups:
            slots += ((scrubber_model.POWERUPS_SERIES,),)
        self._powerup_readout.setVisible(show_powerups)
        self._scrubber.set_slots(slots)
        self._scrubber.set_cap_keys(("Difficulty",) if self._cap_control.isChecked() else ())
        self._update_powerup_readout()

    def _position_changed(self, *_args):
        self._update_metrics()
        self._update_powerup_readout()
        self.positions_changed.emit(self._scrubber.index(), self._scrubber.pin())

    def _update_powerup_readout(self):
        if not self._powerup_control.isChecked() or not self._snapshots:
            return
        a = self._snapshots[self._scrubber.index()]
        pin = self._scrubber.pin()
        b = self._snapshots[pin] if pin is not None else None
        self._powerup_readout.set_range(a.captured_at, b.captured_at if b is not None else None)

    def _update_metrics(self):
        if not self._snapshots:
            return
        snapshot = self._snapshots[self._scrubber.index()]
        game_time = snapshot.game_time_seconds
        game = "—" if game_time is None else game_clock(game_time)
        time_stop = any(effect.effect_id == _CLOCK_EFFECT for effect in self._powerups.active(snapshot.captured_at))
        cursor = f"A · {message('run.timeline.time_stop')}" if time_stop else "A"
        labels = [(cursor, game, "#38bdf8")]
        for key in self._keys:
            series = self._scrubber.model.series(key)
            if key == scrubber_model.KILLS_SERIES:
                value = snapshot.mob_kills
                value = "—" if value is None else QLocale(localization().translator.language).toString(value)
                name = str(l10n.tr("Kills"))
            else:
                stat = snapshot.stats.get(key)
                value = str(stat.display_value or "—") if stat else "—"
                name = str(l10n.stat(key))
            labels.append((name, value, series.color if series else "#c6dbef"))
        for (caption, reading), (name, value, color) in zip(self._metrics, labels, strict=True):
            caption.setText(name)
            style = f"color:{color};"
            if caption.styleSheet() != style:
                caption.setStyleSheet(style)
            reading.setText(value)

    def show_segment(self, a: int, b: int):
        """Select both cursors and publish the completed selection once."""
        self._scrubber.set_index(a)
        self._scrubber.set_pin(b)
        self._position_changed()
