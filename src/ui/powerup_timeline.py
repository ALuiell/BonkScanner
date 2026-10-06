"""Shared power-up painter and wrapping footer for both recording viewers."""
from html import escape

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPen
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QLabel, QWidget

from core.powerup_history import POWERUPS
from projections.powerup_history import PowerupProjection, duration_label, time_label
from ui.shared import resource_path


def paint_powerups(painter, projection, plot, duration, *, axis_projection=None):
    """Return tooltip hits; no reservation or rescaling of the numeric plot."""
    if projection is None:
        return ()
    hits = []
    names = {p[0]: p[1] for p in POWERUPS}
    styles = {p[0]: (p[3], p[4]) for p in POWERUPS}

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
    for span in projection.intervals:
        color, level = styles[span.effect_id]
        x1 = plot.left() + position(span.start_axis) * plot.width()
        x2 = plot.left() + position(span.end_axis) * plot.width()
        x1 = min(x1, plot.right() - 2.0)
        x2 = min(plot.right(), max(x1 + 2.0, x2))
        y = plot.bottom() - level * plot.height()
        painter.setPen(QPen(QColor(color), 2.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(x1, y), QPointF(x2, y))
        elapsed = duration_label(span.seconds) if span.seconds >= 1 else f"{span.seconds:.3f} s"
        hits.append((QRectF(x1 - 2, y - 4, x2 - x1 + 4, 8),
                     f"{names[span.effect_id]}  {time_label(span.start_axis)} → "
                     f"{time_label(span.end_axis)} · {elapsed}"))
    painter.restore()
    return tuple(hits)


class PowerupTimelineRow(QWidget):
    def __init__(self, parent=None, *, side=""):
        super().__init__(parent)
        self.setObjectName("PowerupTimelineRow")
        self.side = side
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.text = QLabel()
        self.text.setTextFormat(Qt.RichText)
        self.text.setWordWrap(True)
        layout.addWidget(self.text, 1)
        self.icons = {}
        for effect_id, name, asset, color, level in POWERUPS:
            icon = QLabel()
            icon.setFixedSize(24, 24)
            icon.setPixmap(QIcon(resource_path(f"media/powerups/{asset}.svg")).pixmap(24, 24))
            opacity = QGraphicsOpacityEffect(icon)
            icon.setGraphicsEffect(opacity)
            layout.addWidget(icon)
            self.icons[effect_id] = (icon, opacity)
        self.hide()

    def set_state(self, projection: PowerupProjection, capture_a, capture_b=None,
                  *, axis_a=0.0, axis_b=None):
        prefix = f"<b>{escape(self.side)}</b>  " if self.side else ""
        if projection.history is None or not projection.observations:
            self.text.setText(prefix + "Power-up data unavailable")
            for icon, opacity in self.icons.values():
                opacity.setOpacity(.3)
                icon.setToolTip("Power-up data unavailable")
            return
        totals = projection.totals(capture_a, capture_b)
        active = {effect.effect_id: effect for effect in projection.active(capture_a)}
        selected = set(active) if capture_b is None else {key for key, value in totals.items() if value > 0}
        parts = []
        if capture_b is not None:
            low, high = sorted((axis_a, axis_b if axis_b is not None else axis_a))
            prefix += f"A–B {time_label(low)} → {time_label(high)}  ·  "
        for effect_id, name, asset, color, level in POWERUPS:
            icon, opacity = self.icons[effect_id]
            opacity.setOpacity(1.0 if effect_id in selected else .3)
            icon.setToolTip(projection.tooltip(effect_id, capture_a, capture_b))
            if effect_id not in selected:
                continue
            interval = ""
            if capture_b is None:
                effect = active[effect_id]
                interval = f" {time_label(effect.start_axis)} → {time_label(effect.end_axis)}"
            parts.append(f'<span style="color:{color}">{name}{interval} · {duration_label(totals[effect_id])}</span>')
        empty = ("No active power-ups" if projection.observed_at(capture_a)
                 else "Power-up state unknown") if capture_b is None else "No observed power-up activity"
        text = prefix + " &nbsp;|&nbsp; ".join(parts or [empty])
        if not projection.complete(capture_a, capture_b):
            text += ' <span style="color:#94A3B8">· Partial data</span>'
        self.text.setText(text)
        self.text.setToolTip("Totals include only observed game time; pauses and unobserved gaps are excluded.")
