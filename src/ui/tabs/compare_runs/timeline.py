"""High-frequency, two-lane timeline used by Compare Runs.

The expensive layer (stage geometry, markers and series paths) is rendered to
one pixmap.  Scrubbing only changes ``_position`` and paints the playhead over
that pixmap, so 120 Hz pointer input never rebuilds a model or a curve.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from projections import formatting
from projections import scrubber as scrubber_model


AXIS_TIME = "time"
AXIS_PROGRESS = "progress"
AXIS_MODES = (AXIS_TIME, AXIS_PROGRESS)

RUN_A_COLOR = QColor("#38BDF8")
RUN_B_COLOR = QColor("#C084FC")
BACKGROUND = QColor("#0B0F14")
SURFACE = QColor("#0E1217")
BORDER = QColor("#2A3542")
MUTED = QColor("#718096")
TEXT = QColor("#DCE6F2")
ENDED = QColor(5, 8, 12, 172)
STAGE_A = QColor(56, 189, 248, 20)
STAGE_B = QColor(192, 132, 252, 20)

_OUTER_MARGIN = 1.0
_LABEL_WIDTH = 32.0
_TOP_GUTTER = 20.0
_BOTTOM_GUTTER = 13.0
_LANE_GAP = 8.0
_STAGE_LABEL_HEIGHT = 17.0
_MARKER_HEIGHT = 8.0
_MARKER_BIN_WIDTH = 6.0


def _safe_time(snapshot, fallback: float) -> float:
    value = formatting._snapshot_compare_time(snapshot)
    try:
        value = float(value)
    except (TypeError, ValueError):
        return fallback
    return value if isfinite(value) else fallback


def snapshot_times(snapshots) -> tuple[float, ...]:
    """Monotonic compare-times, with index progress as a stable fallback."""
    values: list[float] = []
    previous = 0.0
    for index, snapshot in enumerate(snapshots or ()):
        value = _safe_time(snapshot, float(index))
        value = max(previous, value)
        values.append(value)
        previous = value
    return tuple(values)


def axis_positions(
    snapshots,
    *,
    mode: str,
    common_duration: float | None = None,
) -> tuple[float, ...]:
    """Project one recording onto the shared axis without per-frame work."""
    snapshots = tuple(snapshots or ())
    if not snapshots:
        return ()
    if mode == AXIS_PROGRESS:
        denominator = max(len(snapshots) - 1, 1)
        return tuple(index / denominator for index in range(len(snapshots)))
    times = snapshot_times(snapshots)
    duration = max(float(common_duration or 0.0), times[-1], 1.0)
    return tuple(max(0.0, min(1.0, value / duration)) for value in times)


def shared_series_scales(
    model_a: scrubber_model.ScrubberModel,
    model_b: scrubber_model.ScrubberModel,
    series_keys,
) -> dict[str, float]:
    """One raw maximum per metric across both recordings."""
    scales: dict[str, float] = {}
    for key in dict.fromkeys(series_keys):
        values = []
        for model in (model_a, model_b):
            series = model.series(key)
            if series is not None:
                values.extend(
                    float(value)
                    for value in series.values
                    if value is not None and isfinite(float(value))
                )
        scales[key] = max((value for value in values if value >= 0.0), default=1.0) or 1.0
    return scales


def stage_start_deltas(
    model_a: scrubber_model.ScrubberModel,
    model_b: scrubber_model.ScrubberModel,
    times_a: tuple[float, ...],
    times_b: tuple[float, ...],
) -> dict[int, float | None]:
    """B stage start minus the matching A stage start, by stage number."""
    starts_a = {
        band.stage_index: times_a[band.start]
        for band in model_a.stages
        if band.stage_index is not None and 0 <= band.start < len(times_a)
    }
    result: dict[int, float | None] = {}
    for band in model_b.stages:
        stage = band.stage_index
        if stage is None or not 0 <= band.start < len(times_b):
            continue
        start_a = starts_a.get(stage)
        result[stage] = None if start_a is None else times_b[band.start] - start_a
    return result


@dataclass(frozen=True)
class _Lane:
    snapshots: tuple
    model: scrubber_model.ScrubberModel
    times: tuple[float, ...]
    positions: tuple[float, ...]


class CompareRunsTimeline(QWidget):
    """Two cached recording tracks with one normalized playhead."""

    positionChanged = Signal(float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("CompareRunsTimeline")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(214)
        self.setMouseTracking(False)
        self.setToolTip("Drag to compare both recordings at the same position")

        empty = scrubber_model.ScrubberModel(count=0)
        self._lane_a = _Lane((), empty, (), ())
        self._lane_b = _Lane((), empty, (), ())
        self._axis_mode = AXIS_TIME
        self._series_keys: tuple[str, ...] = ()
        self._shared_scales: dict[str, float] = {}
        self._stage_deltas: dict[int, float | None] = {}
        self._position = 0.0
        self._common_duration = 1.0
        self._dragging = False
        self._data_token = 0
        self._cache_key = None
        self._static_layer: QPixmap | None = None
        self._marker_hits: tuple[tuple[QRectF, str], ...] = ()
        self._static_rebuilds = 0

    @property
    def axis_mode(self) -> str:
        return self._axis_mode

    @property
    def position(self) -> float:
        return self._position

    @property
    def common_duration(self) -> float:
        return self._common_duration

    @property
    def static_rebuilds(self) -> int:
        """Instrumentation used by performance tests."""
        return self._static_rebuilds

    def set_axis_mode(self, mode: str) -> None:
        mode = mode if mode in AXIS_MODES else AXIS_TIME
        if mode == self._axis_mode:
            return
        self._axis_mode = mode
        self._reproject()

    def set_runs(self, vod_a, vod_b, *, series_keys=()) -> None:
        keys = tuple(dict.fromkeys(series_keys))
        snapshots_a = tuple(getattr(vod_a, "snapshots", ()) or ())
        snapshots_b = tuple(getattr(vod_b, "snapshots", ()) or ())
        model_a = scrubber_model.build_model(snapshots_a, series_keys=keys)
        model_b = scrubber_model.build_model(snapshots_b, series_keys=keys)
        self._series_keys = keys
        self._lane_a = _Lane(snapshots_a, model_a, snapshot_times(snapshots_a), ())
        self._lane_b = _Lane(snapshots_b, model_b, snapshot_times(snapshots_b), ())
        self._shared_scales = shared_series_scales(model_a, model_b, keys)
        self._stage_deltas = stage_start_deltas(
            model_a,
            model_b,
            self._lane_a.times,
            self._lane_b.times,
        )
        self._reproject()

    def set_series_keys(self, series_keys) -> None:
        keys = tuple(dict.fromkeys(series_keys))
        if keys == self._series_keys:
            return
        # Models own the projections, so a slot change is the only non-recording
        # action that intentionally rebuilds them.
        class _Vod:
            def __init__(self, snapshots):
                self.snapshots = snapshots

        self.set_runs(
            _Vod(self._lane_a.snapshots),
            _Vod(self._lane_b.snapshots),
            series_keys=keys,
        )

    def set_position(self, position: float, *, emit: bool = False) -> None:
        value = max(0.0, min(1.0, float(position)))
        if value == self._position:
            return
        self._position = value
        self.update()
        if emit:
            self.positionChanged.emit(value)

    def nearest_indices(self, position: float | None = None) -> tuple[int | None, int | None]:
        position = self._position if position is None else max(0.0, min(1.0, float(position)))
        return self._nearest_index(self._lane_a, position), self._nearest_index(self._lane_b, position)

    def _nearest_index(self, lane: _Lane, position: float) -> int | None:
        if not lane.positions:
            return None
        import bisect

        at = bisect.bisect_left(lane.positions, position)
        candidates = (max(0, at - 1), min(len(lane.positions) - 1, at))
        return min(candidates, key=lambda index: (abs(lane.positions[index] - position), index))

    def _reproject(self) -> None:
        common_duration = max(
            self._lane_a.times[-1] if self._lane_a.times else 0.0,
            self._lane_b.times[-1] if self._lane_b.times else 0.0,
            1.0,
        )
        self._common_duration = common_duration
        self._lane_a = _Lane(
            self._lane_a.snapshots,
            self._lane_a.model,
            self._lane_a.times,
            axis_positions(
                self._lane_a.snapshots,
                mode=self._axis_mode,
                common_duration=common_duration,
            ),
        )
        self._lane_b = _Lane(
            self._lane_b.snapshots,
            self._lane_b.model,
            self._lane_b.times,
            axis_positions(
                self._lane_b.snapshots,
                mode=self._axis_mode,
                common_duration=common_duration,
            ),
        )
        self._data_token += 1
        self._cache_key = None
        self.update()

    def _track_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(
            _LABEL_WIDTH,
            _TOP_GUTTER,
            -_OUTER_MARGIN,
            -_BOTTOM_GUTTER,
        )

    def _lane_rects(self) -> tuple[QRectF, QRectF]:
        track = self._track_rect()
        height = max(1.0, (track.height() - _LANE_GAP) / 2.0)
        return (
            QRectF(track.left(), track.top(), track.width(), height),
            QRectF(track.left(), track.top() + height + _LANE_GAP, track.width(), height),
        )

    def _x(self, rect: QRectF, position: float) -> float:
        return rect.left() + position * rect.width()

    def mousePressEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        self._dragging = True
        self._set_position_from_x(event.position().x())

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        self._set_position_from_x(event.position().x())

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        super().mouseReleaseEvent(event)

    def _set_position_from_x(self, x: float) -> None:
        track = self._track_rect()
        if track.width() <= 0.0:
            return
        self.set_position((x - track.left()) / track.width(), emit=True)

    def event(self, event) -> bool:
        if event.type() == QEvent.ToolTip:
            for rect, text in self._marker_hits:
                if rect.contains(QPointF(event.pos())):
                    QToolTip.showText(event.globalPos(), text, self)
                    return True
        return super().event(event)

    def resizeEvent(self, event) -> None:
        self._cache_key = None
        super().resizeEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._ensure_static_layer()
        if self._static_layer is not None:
            painter.drawPixmap(0, 0, self._static_layer)
        self._paint_playhead(painter)
        painter.end()

    def _ensure_static_layer(self) -> None:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        key = (self._data_token, self.width(), self.height(), round(dpr, 2))
        if key == self._cache_key and self._static_layer is not None:
            return
        self._cache_key = key
        pixmap = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._paint_static(painter)
        painter.end()
        self._static_layer = pixmap
        self._static_rebuilds += 1

    def _paint_static(self, painter: QPainter) -> None:
        outer = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        painter.setPen(QPen(BORDER, 1.0))
        painter.setBrush(BACKGROUND)
        painter.drawRoundedRect(outer, 10.0, 10.0)

        lane_rects = self._lane_rects()
        hits: list[tuple[QRectF, str]] = []
        for side, lane, rect, side_color, stage_color in (
            ("A", self._lane_a, lane_rects[0], RUN_A_COLOR, STAGE_A),
            ("B", self._lane_b, lane_rects[1], RUN_B_COLOR, STAGE_B),
        ):
            painter.setPen(QPen(BORDER, 1.0))
            painter.setBrush(SURFACE)
            painter.drawRoundedRect(rect, 6.0, 6.0)
            painter.setFont(self._small_font(bold=True))
            painter.setPen(side_color)
            painter.drawText(
                QRectF(5.0, rect.top(), _LABEL_WIDTH - 8.0, rect.height()),
                Qt.AlignCenter,
                side,
            )
            if not lane.snapshots:
                painter.setPen(MUTED)
                painter.drawText(rect, Qt.AlignCenter, "Select a recording")
                continue
            self._paint_stages(painter, lane, rect, stage_color, side)
            self._paint_series(painter, lane, rect)
            hits.extend(self._paint_markers(painter, lane, rect))
            if self._axis_mode == AXIS_TIME and lane.positions and lane.positions[-1] < 0.999:
                start = self._x(rect, lane.positions[-1])
                painter.fillRect(
                    QRectF(start, rect.top(), rect.right() - start, rect.height()),
                    ENDED,
                )
                painter.setPen(MUTED)
                painter.drawText(
                    QRectF(start, rect.top(), rect.right() - start, rect.height()),
                    Qt.AlignCenter,
                    "RUN ENDED",
                )
        self._marker_hits = tuple(hits)

    def _paint_stages(
        self,
        painter: QPainter,
        lane: _Lane,
        rect: QRectF,
        fill: QColor,
        side: str,
    ) -> None:
        if not lane.model.stages:
            painter.setPen(MUTED)
            painter.setFont(self._small_font())
            painter.drawText(
                QRectF(rect.left() + 7.0, rect.top(), rect.width(), _STAGE_LABEL_HEIGHT),
                Qt.AlignLeft | Qt.AlignVCenter,
                "STAGES NOT RECORDED",
            )
            return
        painter.setFont(self._small_font(bold=True))
        for band in lane.model.stages:
            if not lane.positions:
                continue
            start = min(max(band.start, 0), len(lane.positions) - 1)
            end = min(max(band.end, start), len(lane.positions) - 1)
            left = self._x(rect, lane.positions[start])
            right = self._x(rect, lane.positions[end])
            area = QRectF(left, rect.top(), max(right - left, 1.0), rect.height())
            painter.fillRect(area, fill)
            painter.setPen(QPen(BORDER, 1.0))
            painter.drawLine(area.right(), area.top(), area.right(), area.bottom())
            text = band.label
            if side == "B" and band.stage_index is not None:
                delta = self._stage_deltas.get(band.stage_index)
                if delta is not None:
                    sign = "+" if delta >= 0 else "−"
                    text += f" · {sign}{abs(delta):.0f}s"
            painter.setPen(TEXT if area.width() >= 55.0 else MUTED)
            painter.drawText(
                QRectF(area.left() + 5.0, area.top(), max(area.width() - 7.0, 8.0), _STAGE_LABEL_HEIGHT),
                Qt.AlignLeft | Qt.AlignVCenter,
                text,
            )
        if side == "B":
            stages_a = {
                band.stage_index
                for band in self._lane_a.model.stages
                if band.stage_index is not None
            }
            stages_b = {
                band.stage_index
                for band in lane.model.stages
                if band.stage_index is not None
            }
            missing = sorted(stages_a - stages_b)
            if missing:
                labels = ", ".join(f"Stage {stage + 1}" for stage in missing)
                painter.setPen(MUTED)
                painter.drawText(
                    QRectF(rect.left() + 6.0, rect.top(), rect.width() - 12.0, _STAGE_LABEL_HEIGHT),
                    Qt.AlignRight | Qt.AlignVCenter,
                    f"{labels} not reached",
                )

    def _paint_series(self, painter: QPainter, lane: _Lane, rect: QRectF) -> None:
        plot = rect.adjusted(2.0, _STAGE_LABEL_HEIGHT + 3.0, -2.0, -(_MARKER_HEIGHT + 4.0))
        if plot.width() <= 0.0 or plot.height() <= 0.0:
            return
        for key in self._series_keys:
            series = lane.model.series(key)
            scale = self._shared_scales.get(key, 1.0)
            if series is None or not series.available or scale <= 0.0:
                continue
            path = QPainterPath()
            active = False
            for index, value in enumerate(series.values):
                if value is None or index >= len(lane.positions):
                    active = False
                    continue
                normalized = max(0.0, min(1.0, float(value) / scale))
                point = QPointF(
                    self._x(plot, lane.positions[index]),
                    plot.bottom() - normalized * plot.height(),
                )
                if active:
                    path.lineTo(point)
                else:
                    path.moveTo(point)
                    active = True
            painter.setPen(QPen(QColor(series.color), 1.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

    def _paint_markers(self, painter: QPainter, lane: _Lane, rect: QRectF):
        bins: dict[int, tuple[float, list]] = {}
        for marker in lane.model.markers:
            if not 0 <= marker.index < len(lane.positions):
                continue
            x = self._x(rect, lane.positions[marker.index])
            key = int(x // _MARKER_BIN_WIDTH)
            if key not in bins:
                bins[key] = (x, [])
            bins[key][1].append(marker)
        hits = []
        for x, markers in bins.values():
            top = rect.bottom() - _MARKER_HEIGHT - 2.0
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(markers[0].color))
            painter.drawRoundedRect(QRectF(x - 2.5, top, 5.0, _MARKER_HEIGHT), 2.0, 2.0)
            text = "\n".join(marker.text for marker in markers[:10])
            if len(markers) > 10:
                text += f"\n+{len(markers) - 10} more"
            hits.append((QRectF(x - 5.0, top - 3.0, 10.0, _MARKER_HEIGHT + 6.0), text))
        return hits

    def _paint_playhead(self, painter: QPainter) -> None:
        track = self._track_rect()
        x = self._x(track, self._position)
        painter.setPen(QPen(QColor("#EAF2FB"), 1.4))
        painter.drawLine(QPointF(x, track.top() - 6.0), QPointF(x, track.bottom() + 3.0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#EAF2FB"))
        painter.drawEllipse(QPointF(x, track.top() - 8.0), 3.5, 3.5)

    def _small_font(self, *, bold: bool = False) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
        font.setBold(bold)
        return font
