"""Quiet activity lanes and an aligned in-chart uptime legend for both viewers."""

POWERUP_LANE_HEIGHT = 23.0
from functools import lru_cache
from math import ceil

from PySide6.QtCore import QPointF, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetricsF, QIcon, QImage, QPainter, QPen
from PySide6.QtWidgets import QWidget

from core.powerup_history import POWERUPS
from projections.powerup_history import PowerupProjection, duration_label, time_label
from ui.shared import resource_path


def paint_powerups(painter, projection, plot, duration, *, axis_projection=None):
    """Paint four subdued lanes immediately above the existing event strip."""
    if projection is None:
        return ()
    hits = []
    names = {p[0]: p[1] for p in POWERUPS}
    styles = {p[0]: (p[3], i) for i, p in enumerate(POWERUPS)}

    def position(value):
        if axis_projection is not None and axis_projection.mode == "progress":
            from bisect import bisect_right
            times, positions = axis_projection.times, axis_projection.positions
            at = bisect_right(times, value) - 1
            if at < 0:
                return 0.0
            if at + 1 >= len(times):
                return positions[-1]
            part = (value - times[at]) / max(times[at + 1] - times[at], 1e-12)
            return positions[at] + part * (positions[at + 1] - positions[at])
        return max(0.0, min(1.0, value / max(duration, 1.0)))

    painter.save()
    painter.setClipRect(plot)
    strip = QRectF(plot.left(), plot.bottom() - POWERUP_LANE_HEIGHT, plot.width(), POWERUP_LANE_HEIGHT)
    painter.fillRect(strip, QColor(11, 20, 28, 80))
    painter.setPen(QPen(QColor(70, 89, 103, 90), .5))
    painter.drawLine(strip.topLeft(), strip.topRight())
    for span in projection.intervals:
        color, lane = styles[span.effect_id]
        x1 = plot.left() + position(span.start_axis) * plot.width()
        x2 = plot.left() + position(span.end_axis) * plot.width()
        x1 = min(x1, plot.right() - 2.0)
        x2 = min(plot.right(), max(x1 + 2.0, x2))
        y = plot.bottom() - 19.0 + lane * 5.0
        ink = QColor(color)
        ink.setAlphaF(.65)
        painter.setPen(QPen(ink, 2.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(x1, y), QPointF(x2, y))
        elapsed = duration_label(span.seconds) if span.seconds >= 1 else f"{span.seconds:.3f} s"
        hits.append((QRectF(x1 - 2, y - 4, x2 - x1 + 4, 8),
                     f"{names[span.effect_id]}  {time_label(span.start_axis)} → "
                     f"{time_label(span.end_axis)} · {elapsed}"))
    painter.restore()
    return tuple(hits)


def _ink_bounds(image):
    points = [(x, y) for y in range(image.height()) for x in range(image.width())
              if image.pixelColor(x, y).alpha() > 16]
    if not points:
        return image.rect()
    left, top = min(x for x, y in points), min(y for x, y in points)
    return QRect(left, top, max(x for x, y in points) - left + 1,
                 max(y for x, y in points) - top + 1)


@lru_cache(maxsize=4)
def _icon_ink(asset):
    pixmap = QIcon(resource_path(f"media/powerups/{asset}.svg")).pixmap(64, 64)
    return pixmap, _ink_bounds(pixmap.toImage())


class PowerupTimelineRow(QWidget):
    """A transparent chart child: fixed order, all four observed totals visible.

    Pointer input stays with the timeline. It forwards tooltip requests to
    tooltip_at(), so hovering the legend does not change scrubbing semantics.
    """
    def __init__(self, parent=None, *, side=""):
        super().__init__(parent)
        self.side = side
        self.setObjectName("PowerupTimelineRow")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: transparent;")
        self.entries = ()
        self.note = ""
        self._hits = ()
        self._header_font = None
        self._ink_center = 8.5
        self.hide()

    def set_header_font(self, font):
        if font == self._header_font:
            return
        self._header_font = font
        self.setFont(font)
        probe = QImage(80, 17, QImage.Format_ARGB32_Premultiplied)
        probe.fill(Qt.transparent)
        painter = QPainter(probe)
        painter.setFont(font)
        painter.setPen(Qt.white)
        painter.drawText(QRectF(0, 0, 80, 17), Qt.AlignLeft | Qt.AlignVCenter, "16:30")
        painter.end()
        ink = _ink_bounds(probe)
        self._ink_center = ink.y() + ink.height() / 2
        self._resize_to_content()

    def set_state(self, projection: PowerupProjection, capture_a, capture_b=None,
                  *, axis_a=0.0, axis_b=None):
        available = projection.history is not None and bool(projection.observations)
        totals = projection.totals(capture_a, capture_b) if available else {}
        active = {effect.effect_id: effect for effect in projection.active(capture_a)} if available else {}
        selected = set(active) if capture_b is None else {key for key, value in totals.items() if value > 0}
        entries = []
        for effect_id, name, asset, color, level in POWERUPS:
            seconds = totals.get(effect_id)
            label = "—" if seconds is None else f"{int(seconds) // 60}:{int(seconds) % 60:02d}"
            tooltip = projection.tooltip(effect_id, capture_a, capture_b) if available else "Power-up data unavailable"
            if available:
                if capture_b is None:
                    tooltip += f"\nObserved uptime through A ({time_label(axis_a)})."
                    effect = active.get(effect_id)
                    if effect is not None:
                        tooltip += f"\nActive interval known at A: {time_label(effect.start_axis)} → {time_label(effect.end_axis)}"
                    elif projection.observed_at(capture_a):
                        tooltip += "\nInactive at A."
                else:
                    low, high = sorted((axis_a, axis_b if axis_b is not None else axis_a))
                    tooltip += f"\nA–B {time_label(low)} → {time_label(high)}"
            entries.append((effect_id, asset, label, effect_id in selected, tooltip))
        self.entries = tuple(entries)
        self.note = ("No data" if not available else
                     "Unknown · Partial" if capture_b is None and not projection.observed_at(capture_a) else
                     "Partial" if not projection.complete(capture_a, capture_b) else "")
        self._resize_to_content()
        self.update()

    def _resize_to_content(self):
        metrics = QFontMetricsF(self.font())
        width = sum(19 + metrics.horizontalAdvance(entry[2]) + 13 for entry in self.entries)
        if self.note:
            width += metrics.horizontalAdvance(self.note) + 4
        self.setFixedSize(ceil(width), 17)

    def tooltip_at(self, point):
        for rect, tooltip in self._hits:
            if rect.contains(point):
                return tooltip
        return ""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setFont(self.font())
        metrics = QFontMetricsF(self.font())
        hits = []
        x = 0.0
        for effect_id, asset, label, active, tooltip in self.entries:
            pixmap, ink = _icon_ink(asset)
            ratio = min(12 / max(ink.width(), 1), 12 / max(ink.height(), 1))
            width, height = ink.width() * ratio, ink.height() * ratio
            painter.setOpacity(1.0 if active else .38)
            painter.drawPixmap(QRectF(x + (14 - width) / 2, self._ink_center - height / 2, width, height),
                               pixmap, QRectF(ink))
            painter.setPen(QColor("#C5CFDA"))
            text_width = metrics.horizontalAdvance(label)
            painter.drawText(QRectF(x + 19, 0, text_width + 2, 17), Qt.AlignLeft | Qt.AlignVCenter, label)
            item_width = 19 + text_width + 13
            hits.append((QRectF(x, 0, item_width - 5, 17), tooltip))
            x += item_width
        painter.setOpacity(1.0)
        if self.note:
            painter.setPen(QColor("#94A3B8"))
            painter.drawText(QRectF(x, 0, self.width() - x, 17), Qt.AlignLeft | Qt.AlignVCenter, self.note)
            hits.append((QRectF(x, 0, self.width() - x, 17),
                         "Power-up data unavailable" if self.note == "No data" else
                         "Partial observations; pauses and unobserved time are excluded. Hover an effect for coverage details."))
        self._hits = tuple(hits)
        painter.end()


def place_powerup_readout(row, track, caption, font, *, caption_width=None):
    """Share the exact stage-label rectangle and baseline, allowing narrow headers."""
    if row is None or row.isHidden():
        return None
    row.set_header_font(font)
    metrics = QFontMetricsF(font)
    available = max(0, track.width() - row.width() - 25)
    if caption_width is not None:
        available = min(available, max(0, caption_width - 7))
    text_width = min(metrics.horizontalAdvance(caption), available)
    old = row.geometry()
    row.move(round(track.left() + 5 + text_width + 14), round(track.top() + 1))
    row.raise_()
    if row.geometry() != old:
        row.parentWidget().update()
    return QRectF(row.geometry())
