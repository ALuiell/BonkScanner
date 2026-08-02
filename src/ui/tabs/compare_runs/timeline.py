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
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from projections import scrubber as scrubber_model
from core.stats.formats import PlayerStatFormat
from core.stats.formatters import format_player_stat_value
from projections.timeline_axis import (
    AXIS_MODES,
    AXIS_PROGRESS,
    AXIS_TIME,
    axis_positions,
    build_axis_projection,
    snapshot_times,
)
from ui.timeline_visuals import (
    ENDED_FILL,
    RUN_A_COLOR,
    RUN_B_COLOR,
    STAGE_A_FILL,
    STAGE_B_FILL,
    STAGE_MUTED_TEXT,
    TRACK_BORDER,
    TRACK_SURFACE,
    build_cap_geometry,
    build_marker_glyphs,
    build_series_path,
    paint_marker_glyphs,
    paint_playhead,
    paint_stage_band,
)


BORDER = TRACK_BORDER
MUTED = STAGE_MUTED_TEXT
ENDED = ENDED_FILL
STAGE_A = STAGE_A_FILL
STAGE_B = STAGE_B_FILL

_OUTER_MARGIN = 1.0
_LABEL_WIDTH = 32.0
_TOP_GUTTER = 6.0
_BOTTOM_GUTTER = 13.0
_LANE_GAP = 8.0
_STAGE_LABEL_HEIGHT = 17.0
_MARKER_HEIGHT = 11.0
_NORMAL_HEIGHT = 214
_COMPACT_HEIGHT = 112


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
        self.setFixedHeight(_NORMAL_HEIGHT)
        self.setMouseTracking(False)
        self.setToolTip("Drag to compare both recordings at the same position")

        empty = scrubber_model.ScrubberModel(count=0)
        self._lane_a = _Lane((), empty, (), ())
        self._lane_b = _Lane((), empty, (), ())
        self._axis_mode = AXIS_TIME
        self._compact = False
        self._series_keys: tuple[str, ...] = ()
        self._cap_keys: tuple[str, ...] = ()
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
    def compact(self) -> bool:
        return self._compact

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

    def set_compact(self, compact: bool) -> None:
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        self.setFixedHeight(_COMPACT_HEIGHT if compact else _NORMAL_HEIGHT)
        self._cache_key = None
        self.updateGeometry()
        self.update()

    def set_runs(self, vod_a, vod_b, *, series_keys=(), cap_keys=()) -> None:
        keys = tuple(dict.fromkeys(series_keys))
        caps = tuple(dict.fromkeys(cap_keys))
        # A cap line still needs its stat's *scale* to know what height to sit
        # at, and that scale comes from the built series. So the models and the
        # shared scales cover the caps too, while `_series_keys` -- what gets
        # a curve drawn -- stays exactly what the slots asked for. Without this
        # a cap could only be shown by also plotting its curve, which is the
        # coupling this parameter exists to break.
        model_keys = tuple(dict.fromkeys(keys + caps))
        snapshots_a = tuple(getattr(vod_a, "snapshots", ()) or ())
        snapshots_b = tuple(getattr(vod_b, "snapshots", ()) or ())
        model_a = scrubber_model.build_model(snapshots_a, series_keys=model_keys)
        model_b = scrubber_model.build_model(snapshots_b, series_keys=model_keys)
        self._series_keys = keys
        self._cap_keys = caps
        self._lane_a = _Lane(snapshots_a, model_a, snapshot_times(snapshots_a), ())
        self._lane_b = _Lane(snapshots_b, model_b, snapshot_times(snapshots_b), ())
        self._shared_scales = shared_series_scales(model_a, model_b, model_keys)
        self._stage_deltas = stage_start_deltas(
            model_a,
            model_b,
            self._lane_a.times,
            self._lane_b.times,
        )
        self._reproject()

    def set_cap_keys(self, cap_keys) -> None:
        """Which caps to draw, independent of which curves are plotted."""
        caps = tuple(dict.fromkeys(cap_keys))
        if caps == self._cap_keys:
            return
        self._rebuild(self._series_keys, caps)

    def set_series_keys(self, series_keys) -> None:
        keys = tuple(dict.fromkeys(series_keys))
        if keys == self._series_keys:
            return
        self._rebuild(keys, self._cap_keys)

    def _rebuild(self, series_keys, cap_keys) -> None:
        # Models own the projections, so a slot or cap change is the only
        # non-recording action that intentionally rebuilds them.
        class _Vod:
            def __init__(self, snapshots):
                self.snapshots = snapshots

        self.set_runs(
            _Vod(self._lane_a.snapshots),
            _Vod(self._lane_b.snapshots),
            series_keys=series_keys,
            cap_keys=cap_keys,
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
        candidates = {
            bisect.bisect_left(lane.positions, lane.positions[index])
            for index in (max(0, at - 1), min(len(lane.positions) - 1, at))
        }
        return min(candidates, key=lambda index: (abs(lane.positions[index] - position), index))

    def _reproject(self) -> None:
        common_duration = max(
            self._lane_a.times[-1] if self._lane_a.times else 0.0,
            self._lane_b.times[-1] if self._lane_b.times else 0.0,
            1.0,
        )
        self._common_duration = common_duration
        projection_a = build_axis_projection(
            self._lane_a.snapshots,
            mode=self._axis_mode,
            common_duration=common_duration,
        )
        projection_b = build_axis_projection(
            self._lane_b.snapshots,
            mode=self._axis_mode,
            common_duration=common_duration,
        )
        self._lane_a = _Lane(
            self._lane_a.snapshots,
            self._lane_a.model,
            projection_a.times,
            projection_a.positions,
        )
        self._lane_b = _Lane(
            self._lane_b.snapshots,
            self._lane_b.model,
            projection_b.times,
            projection_b.positions,
        )
        self._data_token += 1
        self._cache_key = None
        self.update()

    def _track_rect(self) -> QRectF:
        top_gutter = 3.0 if self._compact else _TOP_GUTTER
        bottom_gutter = 6.0 if self._compact else _BOTTOM_GUTTER
        return QRectF(self.rect()).adjusted(
            _LABEL_WIDTH,
            top_gutter,
            -_OUTER_MARGIN,
            -bottom_gutter,
        )

    def _lane_rects(self) -> tuple[QRectF, QRectF]:
        track = self._track_rect()
        lane_gap = 4.0 if self._compact else _LANE_GAP
        height = max(1.0, (track.height() - lane_gap) / 2.0)
        return (
            QRectF(track.left(), track.top(), track.width(), height),
            QRectF(track.left(), track.top() + height + lane_gap, track.width(), height),
        )

    def _stage_label_height(self) -> float:
        return 12.0 if self._compact else _STAGE_LABEL_HEIGHT

    def _marker_height(self) -> float:
        return 8.0 if self._compact else _MARKER_HEIGHT

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
        lane_rects = self._lane_rects()
        hits: list[tuple[QRectF, str]] = []
        for side, lane, rect, side_color, stage_color in (
            ("A", self._lane_a, lane_rects[0], RUN_A_COLOR, STAGE_A),
            ("B", self._lane_b, lane_rects[1], RUN_B_COLOR, STAGE_B),
        ):
            painter.setPen(QPen(BORDER, 1.0))
            painter.setBrush(TRACK_SURFACE)
            painter.drawRoundedRect(rect, 9.0, 9.0)
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
            self._paint_caps(painter, lane, rect)
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
                QRectF(
                    rect.left() + 7.0,
                    rect.top(),
                    rect.width(),
                    self._stage_label_height(),
                ),
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
            text = band.label
            if not self._compact and side == "B" and band.stage_index is not None:
                delta = self._stage_deltas.get(band.stage_index)
                if delta is not None:
                    sign = "+" if delta >= 0 else "−"
                    text += f" · Δ{sign}{abs(delta):.0f}s"
            paint_stage_band(
                painter,
                area,
                fill=fill,
                text=text,
                font=self._small_font(bold=True),
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
                    QRectF(
                        rect.left() + 6.0,
                        rect.top(),
                        rect.width() - 12.0,
                        self._stage_label_height(),
                    ),
                    Qt.AlignRight | Qt.AlignVCenter,
                    f"{labels} not reached",
                )

    def _paint_series(self, painter: QPainter, lane: _Lane, rect: QRectF) -> None:
        plot = rect.adjusted(
            2.0,
            self._stage_label_height() + 3.0,
            -2.0,
            -(self._marker_height() + 4.0),
        )
        if plot.width() <= 0.0 or plot.height() <= 0.0:
            return
        for key in self._series_keys:
            series = lane.model.series(key)
            scale = self._shared_scales.get(key, 1.0)
            if series is None or not series.available or scale <= 0.0:
                continue
            path = build_series_path(
                series.values,
                lane.positions,
                plot,
                scale,
            )
            painter.setPen(QPen(QColor(series.color), 1.6))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)

    def drawable_cap_keys(self, lane: _Lane) -> tuple[str, ...]:
        """The caps this lane will actually draw.

        A method rather than an inline loop condition so the rule -- caps come
        from `_cap_keys`, *not* from the plotted series -- is something a test
        can read. Asserting on `_cap_keys` alone did not catch a `_paint_caps`
        that had gone back to iterating `_series_keys`.
        """
        keys = []
        for key in self._cap_keys:
            series = lane.model.series(key)
            scale = self._shared_scales.get(key, 1.0)
            if series is None or not series.available or scale <= 0.0:
                continue
            keys.append(key)
        return tuple(keys)

    def _paint_caps(self, painter: QPainter, lane: _Lane, rect: QRectF) -> None:
        plot = rect.adjusted(
            2.0,
            self._stage_label_height() + 3.0,
            -2.0,
            -(self._marker_height() + 4.0),
        )
        for key in self.drawable_cap_keys(lane):
            series = lane.model.series(key)
            scale = self._shared_scales.get(key, 1.0)
            color = QColor(series.color)
            steps = lane.model.caps(key)
            geometries = build_cap_geometry(
                steps,
                lane.positions,
                plot,
                scale,
            )
            for step, cap in zip(steps, geometries):
                painter.setPen(QPen(color, 1.0, Qt.DashLine))
                painter.drawLine(
                    QPointF(cap.x0, cap.y),
                    QPointF(cap.x1, cap.y),
                )
                if key == "Difficulty" and not self._compact:
                    self._paint_cap_label(
                        painter,
                        plot,
                        cap.x0,
                        cap.x1,
                        cap.y,
                        color,
                        format_player_stat_value(
                            step.value,
                            PlayerStatFormat.PERCENT,
                        ),
                    )

    def _paint_cap_label(
        self,
        painter: QPainter,
        plot: QRectF,
        x0: float,
        x1: float,
        y: float,
        color: QColor,
        label: str,
    ) -> None:
        painter.save()
        painter.setFont(self._small_font(bold=True))
        metrics = painter.fontMetrics()
        width = metrics.horizontalAdvance(label) + 8.0
        height = metrics.height() + 2.0
        if x1 - x0 < width + 8.0:
            painter.restore()
            return
        right = x1 - 4.0
        left = max(x0 + 4.0, right - width)
        top = y - height - 2.0
        if top < plot.top():
            top = y + 2.0
        label_rect = QRectF(left, top, width, height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(11, 15, 20, 215))
        painter.drawRoundedRect(label_rect, 3.0, 3.0)
        painter.setPen(color.lighter(115))
        painter.drawText(label_rect, Qt.AlignCenter, label)
        painter.restore()

    def _paint_markers(self, painter: QPainter, lane: _Lane, rect: QRectF):
        glyphs = build_marker_glyphs(lane.model.markers, lane.positions, rect)
        paint_marker_glyphs(painter, glyphs)
        return [(glyph.hit_rect, glyph.tooltip) for glyph in glyphs]

    def _paint_playhead(self, painter: QPainter) -> None:
        for side, rect, color in zip(
            ("A", "B"),
            self._lane_rects(),
            (RUN_A_COLOR, RUN_B_COLOR),
        ):
            paint_playhead(
                painter,
                rect,
                self._position,
                color=color,
                label=side,
                font=self._small_font(bold=True),
            )

    def _small_font(self, *, bold: bool = False) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
        font.setBold(bold)
        return font
