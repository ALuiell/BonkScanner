"""The Recordings scrubber: stage bands, series curves, caps, playhead, pin.

Replaces four widgets at once -- the bare ``QSlider``, the "Timeline: … |
Selected: …" caption, and the *Set Compare Start* / *Clear Compare* buttons --
because all four were describing one thing: where in the run you are looking,
and from where you are comparing. The pin *is* the compare start, so setting it
is a drag rather than a button, and the caption is the position readout the
widget already has to paint.

Draws only. Everything it draws is decided by ``projections/scrubber.py``,
which is rebuilt once per loaded recording; ``paintEvent`` walks the prepared
model and never touches a snapshot. That split matters: a drag repaints at
pointer rate, and the alternative shape -- deriving series inside the paint --
would put a walk over ~900 snapshots and 30 stats on the drag path, which is
the fault ``ui/metric_table.py`` was written to fix elsewhere in this tab.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from projections import scrubber as model_module


# Palette, matched to `redisign_ui/bonkscanner_redesign.qss`. Local constants
# rather than a stylesheet: `paintEvent` needs real colour values, and a QSS
# rule cannot reach inside a custom-painted widget.
_BG = QColor("#141A22")
_BORDER = QColor("#2A3542")
_BAND_TOP = QColor(47, 111, 176, 26)
_BAND_BOTTOM = QColor(47, 111, 176, 5)
_BAND_EDGE = QColor("#2A3542")
_BAND_TEXT = QColor("#5C6675")
_MUTED_TEXT = QColor("#3D4756")
_SEGMENT_FILL = QColor(56, 189, 248, 23)
_SEGMENT_EDGE = QColor(56, 189, 248, 140)
_PIN = QColor("#38BDF8")
_PIN_TEXT = QColor("#06202B")
_PLAYHEAD = QColor("#EDF1F5")
_PLAYHEAD_SHADOW = QColor(0, 0, 0, 140)
_OVER_CAP = QColor(240, 120, 126, 16)

#: Height of the strip along the top that carries stage captions.
_BAND_LABEL_HEIGHT = 15
#: Height of the strip along the bottom that carries event markers.
_MARKER_STRIP_HEIGHT = 11
#: Breathing room so a curve at full scale does not merge into the border.
_PLOT_PADDING = 7
#: Marker glyphs are ~5 px wide; binning at that width is the densest the strip
#: can be while individual events still read as separate.
_MARKER_BIN_WIDTH = 8.0
#: Which event wins its bin. A banish outranks a pickup because it is the rarer
#: decision, and a legendary outranks a rare for the obvious reason.
_MARKER_RANK = {"rare": 1, "legendary": 2, "banish": 3}
#: Vertical slack around the marker strip for hover. The strip is 11 px tall,
#: which is a hard target for a pointer; the band above it is empty anyway.
_MARKER_HOVER_SLACK = 5.0
#: Lines before the tooltip stops listing and starts counting. A bin can hold a
#: whole level-up's worth of pickups, and a tooltip taller than the widget it
#: describes is worse than a summary.
_MARKER_TOOLTIP_MAX_LINES = 8


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
        self._slots: tuple[tuple[str, ...], ...] = model_module.DEFAULT_SLOTS
        self._index = 0
        self._pin: int | None = None
        self._dragging = False
        # Geometry that depends on the model, the slots and the widget size --
        # but *not* on the playhead or the pin, which are the only two things a
        # drag changes. Rebuilding the curves on every pointer move cost ~17 ms
        # of the 18.6 ms frame, measured over a 713-snapshot recording with
        # five series; caching it is what keeps a drag ahead of the pointer.
        self._cache_key: tuple | None = None
        self._cached_paths: list[tuple[QPainterPath, QColor]] = []
        self._cached_markers: list[tuple[float, str, QColor]] = []
        self._cached_caps: list[tuple[float, float, float, QColor, float | None]] = []
        self._model_token = 0
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(False)
        self.setCursor(Qt.PointingHandCursor)

    # -- state ------------------------------------------------------------

    @property
    def model(self) -> model_module.ScrubberModel:
        return self._model

    def set_model(self, model: model_module.ScrubberModel) -> None:
        self._model = model
        self._model_token += 1
        self._index = min(self._index, max(model.count - 1, 0))
        if self._pin is not None and self._pin > max(model.count - 1, 0):
            self._pin = None
        self.update()

    def set_slots(self, slots) -> None:
        self._slots = tuple(tuple(slot) for slot in slots)
        self.update()

    @property
    def series_keys(self) -> tuple[str, ...]:
        return tuple(key for slot in self._slots for key in slot)

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
        return self._model.index_at((x - rect.left()) / rect.width())

    def mousePressEvent(self, event) -> None:
        if self._model.count <= 0 or event.button() != Qt.LeftButton:
            super().mousePressEvent(event)
            return
        index = self._index_at_x(event.position().x())
        if event.modifiers() & Qt.ShiftModifier:
            # Shift-click drops the compare anchor. The button it replaces was
            # "Set Compare Start", which could only ever anchor at the *current*
            # playhead; here the anchor is a place you point at.
            self.set_pin(index, emit=True)
            return
        self._dragging = True
        self.set_index(index, emit=True)

    def mouseMoveEvent(self, event) -> None:
        if not self._dragging:
            super().mouseMoveEvent(event)
            return
        self.set_index(self._index_at_x(event.position().x()), emit=True)

    def mouseReleaseEvent(self, event) -> None:
        self._dragging = False
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
        if self._model.count <= 0 or not self._model.markers:
            return ""
        track = self._track_rect()
        strip_top = track.bottom() - _MARKER_STRIP_HEIGHT - _MARKER_HOVER_SLACK
        y = float(point.y())
        if not (strip_top <= y <= track.bottom()):
            return ""
        key = int(float(point.x()) // _MARKER_BIN_WIDTH)
        texts = [
            marker.text
            for marker in self._model.markers
            if int(self._x_of(marker.index) // _MARKER_BIN_WIDTH) == key
        ]
        if not texts:
            return ""
        if len(texts) > _MARKER_TOOLTIP_MAX_LINES:
            hidden = len(texts) - _MARKER_TOOLTIP_MAX_LINES
            texts = texts[:_MARKER_TOOLTIP_MAX_LINES] + [f"+{hidden} more"]
        return "\n".join(texts)

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
        elif key == Qt.Key_A:
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
        return rect.left() + self._model.position(index) * rect.width()

    # -- painting ---------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        track = self._track_rect()

        painter.setPen(QPen(_BORDER, 1.0))
        painter.setBrush(_BG)
        painter.drawRoundedRect(track, 9.0, 9.0)

        if self._model.count <= 0:
            self._paint_placeholder(painter, track)
            painter.end()
            return

        self._ensure_render_cache()

        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(track, 9.0, 9.0)
        painter.setClipPath(clip)

        self._paint_stage_bands(painter, track)
        self._paint_caps(painter)
        self._paint_series(painter)
        self._paint_no_series_hint(painter)
        self._paint_segment(painter, track)
        self._paint_markers(painter, track)
        painter.restore()

        self._paint_pin(painter, track)
        self._paint_playhead(painter, track)
        painter.end()

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
            gradient_top = QRectF(area)
            painter.fillRect(gradient_top, _BAND_TOP if band.stage_index is not None else _BAND_BOTTOM)
            painter.setPen(QPen(_BAND_EDGE, 1.0))
            painter.drawLine(area.right(), area.top(), area.right(), area.bottom())
            painter.setPen(_BAND_TEXT)
            painter.drawText(
                QRectF(area.left() + 7.0, area.top() + 2.0, max(area.width() - 10.0, 10.0), _BAND_LABEL_HEIGHT),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"{band.label} · {_format_span(band.elapsed_seconds)}",
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
        self._cached_markers = self._build_marker_bins()

    def _build_series_paths(self, plot: QRectF) -> list[tuple[QPainterPath, QColor]]:
        if plot.height() <= 0 or plot.width() <= 0 or self._model.count <= 0:
            return []
        # Sampled to the widget's pixel width rather than drawn per snapshot: a
        # 900-point path across an 800 px track spends most of its segments
        # inside one pixel column.
        samples = max(int(plot.width()), 2)
        built: list[tuple[QPainterPath, QColor]] = []
        for key in self.series_keys:
            series = self._model.series(key)
            if series is None or not series.available:
                continue
            path = QPainterPath()
            started = False
            for sample in range(samples + 1):
                index = self._model.index_at(sample / samples)
                ratio = series.normalised(index)
                if ratio is None:
                    continue
                x = plot.left() + (sample / samples) * plot.width()
                y = plot.bottom() - ratio * plot.height()
                if started:
                    path.lineTo(x, y)
                else:
                    path.moveTo(x, y)
                    started = True
            if started:
                built.append((path, QColor(series.color)))
        return built

    def _build_cap_geometry(
        self, plot: QRectF
    ) -> list[tuple[float, float, float, QColor, float | None]]:
        """``(x0, x1, y, colour, over_cap_from_x)`` per cap step."""
        geometry: list[tuple[float, float, float, QColor, float | None]] = []
        for key in self.series_keys:
            steps = self._model.caps(key)
            series = self._model.series(key)
            if not steps or series is None or not series.available:
                continue
            colour = QColor(series.color)
            over_cap_from: float | None = None
            for step in steps:
                ratio = min(max(step.value / series.scale, 0.0), 1.0)
                y = plot.bottom() - ratio * plot.height()
                crossed = None
                if over_cap_from is None:
                    crossed = self._first_index_over(series, step)
                    if crossed is not None:
                        over_cap_from = self._x_of(crossed)
                geometry.append(
                    (
                        self._x_of(step.start),
                        self._x_of(step.end),
                        y,
                        colour,
                        over_cap_from if crossed is not None else None,
                    )
                )
        return geometry

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
        plot = self._plot_rect()
        for x0, x1, y, colour, over_cap_from in self._cached_caps:
            painter.setPen(QPen(colour, 1.0, Qt.DashLine))
            painter.drawLine(x0, y, x1, y)
            if over_cap_from is not None:
                painter.fillRect(
                    QRectF(over_cap_from, plot.top(), plot.right() - over_cap_from, plot.height()),
                    _OVER_CAP,
                )

    @staticmethod
    def _first_index_over(series: model_module.Series, step: model_module.CapStep) -> int | None:
        for index in range(step.start, step.end + 1):
            value = series.values[index]
            if value is not None and value >= step.value:
                return index
        return None

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
        top = track.bottom() - _MARKER_STRIP_HEIGHT
        painter.setPen(Qt.NoPen)
        for x, kind, colour in self._cached_markers:
            painter.setBrush(colour)
            if kind == "banish":
                painter.drawEllipse(QRectF(x - 2.5, top + 3.0, 5.0, 5.0))
            else:
                painter.save()
                painter.translate(x, top + 5.0)
                painter.rotate(45.0)
                painter.drawRect(QRectF(-2.6, -2.6, 5.2, 5.2))
                painter.restore()

    def _build_marker_bins(self) -> list[tuple[float, str, QColor]]:
        """One glyph per bin, so a dense run reads as events and not as a bar.

        A long recording produces ~190 markers; drawn one-per-event across an
        800 px track they merge into a solid strip that says only "items
        happened". Binning to a glyph's own width keeps the *distribution*
        legible, which is the only thing the strip is for -- the exact item is
        the tooltip's job.

        Binned in the widget rather than in the model because the right bin
        size is the glyph's, and the model has no pixels. The same recording
        binned differently in a narrow and a wide window is correct.
        """
        if not self._model.markers:
            return []
        bins: dict[int, tuple[int, str, QColor]] = {}
        for marker in self._model.markers:
            x = self._x_of(marker.index)
            key = int(x // _MARKER_BIN_WIDTH)
            rank = _MARKER_RANK.get(marker.kind, 0)
            existing = bins.get(key)
            if existing is None or rank > existing[0]:
                bins[key] = (rank, marker.kind, QColor(marker.color))
        return [
            ((key + 0.5) * _MARKER_BIN_WIDTH, kind, colour)
            for key, (_rank, kind, colour) in sorted(bins.items())
        ]

    def _paint_pin(self, painter: QPainter, track: QRectF) -> None:
        if self._pin is None:
            return
        x = self._x_of(self._pin)
        painter.setPen(QPen(_PIN, 2.0))
        painter.drawLine(x, track.top(), x, track.bottom())
        badge = QRectF(x - 9.0, track.top(), 18.0, 15.0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_PIN)
        painter.drawRoundedRect(badge, 4.0, 4.0)
        painter.setPen(_PIN_TEXT)
        painter.setFont(self._small_font())
        painter.drawText(badge, Qt.AlignCenter, "A")

    def _paint_playhead(self, painter: QPainter, track: QRectF) -> None:
        x = self._x_of(self._index)
        painter.setPen(QPen(_PLAYHEAD_SHADOW, 3.0))
        painter.drawLine(x, track.top(), x, track.bottom())
        painter.setPen(QPen(_PLAYHEAD, 2.0))
        painter.drawLine(x, track.top(), x, track.bottom())
        painter.setPen(QPen(_PLAYHEAD_SHADOW, 1.5))
        painter.setBrush(_PLAYHEAD)
        painter.drawEllipse(QRectF(x - 5.0, track.top() + 1.0, 10.0, 10.0))


def _format_span(seconds: int) -> str:
    seconds = max(0, int(seconds))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
