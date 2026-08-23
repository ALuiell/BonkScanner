"""The Recordings scrubber: stage bands, series curves, caps, playhead, pin.

Replaces four widgets at once -- the bare ``QSlider``, the "Timeline: … |
Selected: …" caption, and the *Set Compare Start* / *Clear Compare* buttons --
because all four were describing one thing: where in the run you are looking,
and which second point you are comparing against. The playhead is A; the pin is
the Shift-clicked compare point B, so setting B is a gesture rather than a
button, and the caption is the position readout the widget already has to paint.

Draws only. Everything it draws is decided by ``projections/scrubber.py``,
which is rebuilt once per loaded recording; ``paintEvent`` walks the prepared
model and never touches a snapshot. That split matters: a drag repaints at
pointer rate, and the alternative shape -- deriving series inside the paint --
would put a walk over ~900 snapshots and 30 stats on the drag path, which is
the fault ``ui/metric_table.py`` was written to fix elsewhere in this tab.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from core.stats.formats import PlayerStatFormat
from core.stats.formatters import format_player_stat_value
from projections import scrubber as model_module
from projections.timeline_axis import AXIS_PROGRESS, TimelineAxisProjection
from ui.timeline_visuals import (
    MARKER_STRIP_HEIGHT,
    MARKER_TOOLTIP_MAX_LINES,
    RUN_A_COLOR,
    RUN_B_COLOR,
    STAGE_A_FILL,
    TRACK_BORDER,
    TRACK_SURFACE,
    build_cap_geometry,
    build_marker_glyphs,
    build_series_path,
    paint_marker_glyphs,
    paint_playhead,
    paint_stage_band,
)


# Shared painter tokens are defined in `ui/timeline_visuals.py` and mirrored by
# `ui_assets/bonkscanner_theme.qss`; QSS cannot style custom-painted pixels.
_BG = TRACK_SURFACE
_BORDER = TRACK_BORDER
_BAND_TOP = STAGE_A_FILL
_BAND_BOTTOM = QColor(56, 189, 248, 7)
_MUTED_TEXT = QColor("#3D4756")
_SEGMENT_FILL = QColor(56, 189, 248, 23)
_SEGMENT_EDGE = QColor(56, 189, 248, 140)
_PIN = RUN_B_COLOR
_PLAYHEAD = RUN_A_COLOR

#: Height of the strip along the top that carries stage captions.
_BAND_LABEL_HEIGHT = 15
#: Height of the strip along the bottom that carries event markers.
_MARKER_STRIP_HEIGHT = int(MARKER_STRIP_HEIGHT)
_MARKER_TOOLTIP_MAX_LINES = MARKER_TOOLTIP_MAX_LINES
#: Breathing room so a curve at full scale does not merge into the border.
_PLOT_PADDING = 7
#: Marker glyphs are ~5 px wide; binning at that width is the densest the strip
#: can be while individual events still read as separate.
class RecordingScrubber(QWidget):
    """Scrub position and compare anchor over one loaded recording."""

    #: The playhead moved. Emitted on every change, including programmatic
    #: ones from `set_index(..., emit=True)`; the *tab* coalesces these into
    #: repaints, the same division `on_vods_slider_changed` already used.
    indexChanged = Signal(int)
    #: The compare anchor moved, or was cleared (``None``).
    pinChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model = model_module.ScrubberModel(count=0)
        self._projection = TimelineAxisProjection((), (), 1.0, AXIS_PROGRESS)
        self._slots: tuple[tuple[str, ...], ...] = model_module.DEFAULT_SLOTS
        self._index = 0
        self._pin: int | None = None
        self._dragging = False
        self._pin_dragging = False
        # Geometry that depends on the model, the slots and the widget size --
        # but *not* on the playhead or the pin, which are the only two things a
        # drag changes. Rebuilding the curves on every pointer move cost ~17 ms
        # of the 18.6 ms frame, measured over a 713-snapshot recording with
        # five series; caching it is what keeps a drag ahead of the pointer.
        self._cache_key: tuple | None = None
        self._cached_paths: list[tuple[QPainterPath, QColor]] = []
        self._cached_markers = ()
        self._cached_caps: list[tuple[float, float, float, QColor, str | None]] = []
        self._cap_keys: tuple[str, ...] = ()
        self._model_token = 0
        self._static_layer: QPixmap | None = None
        self._static_cache_key = None
        self._static_rebuilds = 0
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(False)
        self.setCursor(Qt.PointingHandCursor)

    # -- state ------------------------------------------------------------

    @property
    def model(self) -> model_module.ScrubberModel:
        return self._model

    def set_model(
        self,
        model: model_module.ScrubberModel,
        *,
        projection: TimelineAxisProjection | None = None,
    ) -> None:
        self._model = model
        if projection is None or len(projection.positions) != model.count:
            denominator = max(model.count - 1, 1)
            positions = tuple(index / denominator for index in range(model.count))
            projection = TimelineAxisProjection(
                tuple(float(index) for index in range(model.count)),
                positions,
                float(denominator),
                AXIS_PROGRESS,
            )
        self._projection = projection
        self._model_token += 1
        self._invalidate_static_layer()
        self._index = min(self._index, max(model.count - 1, 0))
        if self._pin is not None and self._pin > max(model.count - 1, 0):
            self._pin = None
        self.update()

    def set_slots(self, slots) -> None:
        slots = tuple(tuple(slot) for slot in slots)
        if slots == self._slots:
            return
        self._slots = slots
        self._invalidate_static_layer()
        self.update()

    def set_projection(self, projection: TimelineAxisProjection) -> None:
        if len(projection.positions) != self._model.count:
            raise ValueError("timeline projection must match the scrubber model")
        if projection == self._projection:
            return
        self._projection = projection
        self._model_token += 1
        self._invalidate_static_layer()
        self.update()

    @property
    def static_rebuilds(self) -> int:
        return self._static_rebuilds

    @property
    def series_keys(self) -> tuple[str, ...]:
        """What gets a curve: exactly what the four slots asked for."""
        return tuple(key for slot in self._slots for key in slot)

    @property
    def model_keys(self) -> tuple[str, ...]:
        """What the model must carry: the plotted series *and* the caps.

        A cap line needs its stat's scale to know what height to sit at, and
        that scale comes from the built series -- so a ceiling shown without
        its curve still needs the series in the model. This is the seam that
        lets the two be asked for independently.
        """
        return tuple(dict.fromkeys(self.series_keys + self._cap_keys))

    @property
    def cap_keys(self) -> tuple[str, ...]:
        return self._cap_keys

    def set_cap_keys(self, cap_keys) -> None:
        """Which ceilings to draw, independent of which curves are plotted."""
        keys = tuple(dict.fromkeys(cap_keys))
        if keys == self._cap_keys:
            return
        self._cap_keys = keys
        self._invalidate_static_layer()
        self.update()

    def drawable_cap_keys(self) -> tuple[str, ...]:
        """The ceilings this scrubber will actually paint.

        A method rather than an inline loop condition so the rule -- caps come
        from `_cap_keys`, *not* from the plotted series -- is something a test
        can read.
        """
        keys = []
        for key in self._cap_keys:
            series = self._model.series(key)
            if not self._model.caps(key) or series is None or not series.available:
                continue
            keys.append(key)
        return tuple(keys)

    def index(self) -> int:
        return self._index

    def set_index(self, index: int, *, emit: bool = False) -> None:
        if self._model.count <= 0:
            return
        index = min(max(int(index), 0), self._model.count - 1)
        if index == self._index:
            return
        self._index = index
        self.update()
        if emit:
            self.indexChanged.emit(index)

    def pin(self) -> int | None:
        return self._pin

    def set_pin(self, index: int | None, *, emit: bool = False) -> None:
        if index is not None:
            if self._model.count <= 0:
                return
            index = min(max(int(index), 0), self._model.count - 1)
        if index == self._pin:
            return
        self._pin = index
        self.update()
        if emit:
            self.pinChanged.emit(index)

    # -- input ------------------------------------------------------------

    def _index_at_x(self, x: float) -> int:
        rect = self._track_rect()
        if rect.width() <= 0:
            return 0
        index = self._projection.nearest_index((x - rect.left()) / rect.width())
        return 0 if index is None else index

    def mousePressEvent(self, event) -> None:
        if self._model.count <= 0 or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        index = self._index_at_x(event.position().x())
        if event.modifiers() & Qt.ShiftModifier:
            # Shift-drag owns compare point B until the button is released.
            # A short press is still the old Shift-click gesture; keeping the
            # drag active makes fine positioning continuous instead of a row
            # of repeated clicks.
            self._pin_dragging = True
            self._dragging = False
            self.set_pin(index, emit=True)
            return
        self._pin_dragging = False
        self._dragging = True
        self.set_index(index, emit=True)

    def mouseMoveEvent(self, event) -> None:
        if self._pin_dragging:
            self.set_pin(self._index_at_x(event.position().x()), emit=True)
            return
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        self.set_index(self._index_at_x(event.position().x()), emit=True)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
        self._pin_dragging = False
        super().mouseReleaseEvent(event)

    def event(self, event) -> bool:
        """Answer a tooltip request over the marker strip with its events.

        `QEvent.ToolTip` rather than mouse tracking: Qt asks only when the
        pointer has settled, so hovering costs nothing while the pointer is
        moving -- and nothing at all during a drag, which is the path this
        widget is built to keep short.

        Falling through to `super()` when the pointer is not over a marker is
        what lets the widget's own tooltip -- the keyboard and shift-click
        help -- still appear everywhere else.
        """
        if event.type() == QEvent.ToolTip:
            text = self._marker_tooltip_at(event.pos())
            if text:
                QToolTip.showText(event.globalPos(), text, self)
                return True
        return super().event(event)

    def _marker_tooltip_at(self, point) -> str:
        """Every event binned to the glyph under `point`, or ``""``."""
        self._ensure_static_layer()
        for glyph in self._cached_markers:
            if glyph.hit_rect.contains(point):
                return glyph.tooltip
        return ""

    def keyPressEvent(self, event) -> None:
        if self._model.count <= 0:
            super().keyPressEvent(event)
            return
        step = 10 if event.modifiers() & Qt.ShiftModifier else 1
        key = event.key()
        if key == Qt.Key_Left:
            self.set_index(self._index - step, emit=True)
        elif key == Qt.Key_Right:
            self.set_index(self._index + step, emit=True)
        elif key == Qt.Key_Home:
            self.set_index(0, emit=True)
        elif key == Qt.Key_End:
            self.set_index(self._model.count - 1, emit=True)
        elif key == Qt.Key_B:
            self.set_pin(self._index, emit=True)
        elif key == Qt.Key_Escape:
            self.set_pin(None, emit=True)
        else:
            super().keyPressEvent(event)

    # -- geometry ---------------------------------------------------------

    def _track_rect(self) -> QRectF:
        rect = QRectF(self.rect())
        return rect.adjusted(1.0, 1.0, -1.0, -1.0)

    def _plot_rect(self) -> QRectF:
        return self._track_rect().adjusted(
            0.0,
            _BAND_LABEL_HEIGHT + _PLOT_PADDING,
            0.0,
            -(_MARKER_STRIP_HEIGHT + _PLOT_PADDING),
        )

    def _x_of(self, index: int) -> float:
        rect = self._track_rect()
        if not self._projection.positions:
            return rect.left()
        index = min(max(int(index), 0), len(self._projection.positions) - 1)
        return rect.left() + self._projection.positions[index] * rect.width()

    # -- painting ---------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._ensure_static_layer()
        if self._static_layer is not None:
            painter.drawPixmap(0, 0, self._static_layer)

        if self._model.count <= 0:
            painter.end()
            return

        track = self._track_rect()
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(track, 9.0, 9.0)
        painter.setClipPath(clip)
        self._paint_segment(painter, track)
        painter.restore()
        self._paint_pin(painter, track)
        self._paint_playhead(painter, track)
        painter.end()

    def _paint_static(self, painter: QPainter) -> None:
        track = self._track_rect()
        painter.setPen(QPen(_BORDER, 1.0))
        painter.setBrush(_BG)
        painter.drawRoundedRect(track, 9.0, 9.0)

        if self._model.count <= 0:
            self._paint_placeholder(painter, track)
            return

        self._ensure_render_cache()

        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(track, 9.0, 9.0)
        painter.setClipPath(clip)

        self._paint_stage_bands(painter, track)
        self._paint_caps(painter)
        self._paint_series(painter)
        self._paint_cap_labels(painter)
        self._paint_no_series_hint(painter)
        self._paint_markers(painter, track)
        painter.restore()

    def _ensure_static_layer(self) -> None:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        key = (self._model_token, self._slots, self.width(), self.height(), round(dpr, 2))
        if key == self._static_cache_key and self._static_layer is not None:
            return
        self._static_cache_key = key
        pixmap = QPixmap(
            max(1, int(self.width() * dpr)),
            max(1, int(self.height() * dpr)),
        )
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        self._paint_static(painter)
        painter.end()
        self._static_layer = pixmap
        self._static_rebuilds += 1

    def _invalidate_static_layer(self) -> None:
        self._cache_key = None
        self._static_cache_key = None
        self._static_layer = None

    def resizeEvent(self, event) -> None:
        self._invalidate_static_layer()
        super().resizeEvent(event)

    def _paint_placeholder(self, painter: QPainter, track: QRectF) -> None:
        painter.setPen(_MUTED_TEXT)
        painter.setFont(self._small_font())
        painter.drawText(track, Qt.AlignCenter, "No recording loaded")

    def _small_font(self) -> QFont:
        font = QFont(self.font())
        font.setPointSizeF(max(7.0, font.pointSizeF() - 1.5))
        font.setBold(True)
        return font

    def _paint_stage_bands(self, painter: QPainter, track: QRectF) -> None:
        bands = self._model.stages
        if not bands:
            # Older recordings carry no `stage_index`. Saying so is the point:
            # an empty track would read as "one stage", which is a different
            # and false claim.
            painter.setPen(_MUTED_TEXT)
            painter.setFont(self._small_font())
            painter.drawText(
                QRectF(track.left() + 7.0, track.top() + 2.0, track.width(), _BAND_LABEL_HEIGHT),
                Qt.AlignLeft | Qt.AlignVCenter,
                "STAGES NOT RECORDED",
            )
            return
        painter.setFont(self._small_font())
        for band in bands:
            left = self._x_of(band.start)
            right = self._x_of(band.end)
            area = QRectF(left, track.top(), max(right - left, 1.0), track.height())
            paint_stage_band(
                painter,
                area,
                fill=_BAND_TOP if band.stage_index is not None else _BAND_BOTTOM,
                text=f"{band.label} · {_format_span(band.elapsed_seconds)}",
                font=self._small_font(),
            )

    # -- render cache -----------------------------------------------------

    def _ensure_render_cache(self) -> None:
        """Rebuild curve paths, cap lines and marker bins if anything moved.

        Keyed on what they actually depend on: the model, the slot selection
        and the widget's size. The playhead and the pin are deliberately absent
        from the key -- they are what a drag changes, and they are drawn
        straight over the cached geometry.
        """
        plot = self._plot_rect()
        key = (
            self._model_token,
            self._slots,
            round(plot.width(), 1),
            round(plot.height(), 1),
        )
        if key == self._cache_key:
            return
        self._cache_key = key
        self._cached_paths = self._build_series_paths(plot)
        self._cached_caps = self._build_cap_geometry(plot)
        self._cached_markers = build_marker_glyphs(
            self._model.markers,
            self._projection.positions,
            self._track_rect(),
        )

    def _build_series_paths(self, plot: QRectF) -> list[tuple[QPainterPath, QColor]]:
        if plot.height() <= 0 or plot.width() <= 0 or self._model.count <= 0:
            return []
        built: list[tuple[QPainterPath, QColor]] = []
        for key in self.series_keys:
            series = self._model.series(key)
            if series is None or not series.available:
                continue
            path = build_series_path(
                series.values,
                self._projection.positions,
                plot,
                self._model.series_scale(key, include_cap=key in self._cap_keys),
            )
            if path.elementCount():
                built.append((path, QColor(series.color)))
        return built

    def _build_cap_geometry(
        self, plot: QRectF
    ) -> list[tuple[float, float, float, QColor, str | None]]:
        """``(x0, x1, y, colour, label)`` per cap step."""
        result: list[tuple[float, float, float, QColor, str | None]] = []
        for key in self.drawable_cap_keys():
            steps = self._model.caps(key)
            series = self._model.series(key)
            colour = QColor(series.color)
            geometries = build_cap_geometry(
                steps,
                self._projection.positions,
                plot,
                self._model.series_scale(key, include_cap=True),
            )
            for step, cap in zip(steps, geometries):
                result.append(
                    (
                        cap.x0,
                        cap.x1,
                        cap.y,
                        colour,
                        (
                            format_player_stat_value(
                                step.value, PlayerStatFormat.PERCENT
                            )
                            if key == "Difficulty"
                            else None
                        ),
                    )
                )
        return result

    def _paint_no_series_hint(self, painter: QPainter) -> None:
        """Say why the track is blank when every slot is set to None.

        Scrubbing still works with no series -- the stage bands, markers and
        pin are all still there -- so an empty plot is a legitimate state and
        not an error. It is also indistinguishable from a broken one unless it
        says so, which is the same reason `_paint_stage_bands` announces a
        recording with no stages instead of drawing nothing.
        """
        if self._cached_paths:
            return
        painter.setPen(_MUTED_TEXT)
        painter.setFont(self._small_font())
        painter.drawText(self._plot_rect(), Qt.AlignCenter, "NO SERIES SELECTED")

    def _paint_caps(self, painter: QPainter) -> None:
        for x0, x1, y, colour, _label in self._cached_caps:
            painter.setPen(QPen(colour, 1.0, Qt.DashLine))
            painter.drawLine(x0, y, x1, y)

    def _paint_cap_labels(self, painter: QPainter) -> None:
        """Put Difficulty's percent on top of both its cap and its curve."""
        plot = self._plot_rect()
        for x0, x1, y, colour, label in self._cached_caps:
            if not label:
                continue

            painter.save()
            painter.setFont(self._small_font())
            metrics = painter.fontMetrics()
            label_width = metrics.horizontalAdvance(label) + 8.0
            label_height = metrics.height() + 2.0
            # A cap that lasts only a few snapshots has no honest place for a
            # caption. Drawing it over the neighbouring step makes both values
            # ambiguous, so keep the line and wait for the next readable run.
            if x1 - x0 < label_width + 8.0:
                painter.restore()
                continue

            right = x1 - 4.0
            left = max(x0 + 4.0, right - label_width)
            top = y - label_height - 2.0
            if top < plot.top() + _BAND_LABEL_HEIGHT:
                top = y + 2.0
            label_rect = QRectF(left, top, label_width, label_height)

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(11, 15, 20, 215))
            painter.drawRoundedRect(label_rect, 3.0, 3.0)
            painter.setPen(colour.lighter(115))
            painter.drawText(label_rect, Qt.AlignCenter, label)
            painter.restore()

    def _paint_series(self, painter: QPainter) -> None:
        painter.setBrush(Qt.NoBrush)
        for path, colour in self._cached_paths:
            painter.setPen(QPen(colour, 1.6))
            painter.drawPath(path)

    def _paint_segment(self, painter: QPainter, track: QRectF) -> None:
        if self._pin is None:
            return
        left = min(self._x_of(self._pin), self._x_of(self._index))
        right = max(self._x_of(self._pin), self._x_of(self._index))
        painter.fillRect(QRectF(left, track.top(), max(right - left, 1.0), track.height()), _SEGMENT_FILL)
        painter.setPen(QPen(_SEGMENT_EDGE, 1.0))
        painter.drawLine(left, track.top(), left, track.bottom())
        painter.drawLine(right, track.top(), right, track.bottom())

    def _paint_markers(self, painter: QPainter, track: QRectF) -> None:
        del track
        paint_marker_glyphs(painter, self._cached_markers)

    def _paint_pin(self, painter: QPainter, track: QRectF) -> None:
        if self._pin is None:
            return
        paint_playhead(
            painter,
            track,
            self._projection.positions[self._pin],
            color=_PIN,
            label="B",
            font=self._small_font(),
        )

    def _paint_playhead(self, painter: QPainter, track: QRectF) -> None:
        paint_playhead(
            painter,
            track,
            self._projection.positions[self._index],
            color=_PLAYHEAD,
            label="A",
            font=self._small_font(),
        )


def _format_span(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
