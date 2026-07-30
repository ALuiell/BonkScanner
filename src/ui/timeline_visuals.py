"""Shared painter palette and marker geometry for recording timelines."""
from __future__ import annotations

import bisect
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtCore import Qt


RUN_A_COLOR = QColor("#38BDF8")
RUN_B_COLOR = QColor("#C084FC")
TRACK_SURFACE = QColor("#141A22")
TRACK_BORDER = QColor("#2A3542")
STAGE_TEXT = QColor("#DCE6F2")
STAGE_MUTED_TEXT = QColor("#8A94A3")
STAGE_A_FILL = QColor(56, 189, 248, 20)
STAGE_B_FILL = QColor(192, 132, 252, 20)
ENDED_FILL = QColor(5, 8, 12, 172)
PLAYHEAD_SHADOW = QColor(0, 0, 0, 140)

MARKER_BIN_WIDTH = 8.0
MARKER_STRIP_HEIGHT = 11.0
MARKER_HOVER_SLACK = 5.0
MARKER_TOOLTIP_MAX_LINES = 8
_MARKER_RANK = {"rare": 1, "legendary": 2, "banish": 3}


@dataclass(frozen=True)
class MarkerGlyph:
    x: float
    kind: str
    color: QColor
    hit_rect: QRectF
    tooltip: str


@dataclass(frozen=True)
class CapGeometry:
    x0: float
    x1: float
    y: float


def nearest_position_index(positions, position: float) -> int | None:
    if not positions:
        return None
    target = max(0.0, min(1.0, float(position)))
    at = bisect.bisect_left(positions, target)
    candidates = {
        bisect.bisect_left(positions, positions[index])
        for index in (max(0, at - 1), min(len(positions) - 1, at))
    }
    return min(candidates, key=lambda index: (abs(positions[index] - target), index))


def build_series_path(values, positions, plot: QRectF, scale: float) -> QPainterPath:
    """Pixel-sampled curve path over an arbitrary prepared timeline axis."""
    path = QPainterPath()
    if not positions or scale <= 0.0 or plot.width() <= 0.0 or plot.height() <= 0.0:
        return path
    samples = max(int(plot.width()), 2)
    active = False
    for sample in range(samples + 1):
        position = sample / samples
        index = nearest_position_index(positions, position)
        if index is None or index >= len(values) or values[index] is None:
            active = False
            continue
        normalized = max(0.0, min(1.0, float(values[index]) / scale))
        point = QPointF(
            plot.left() + position * plot.width(),
            plot.bottom() - normalized * plot.height(),
        )
        if active:
            path.lineTo(point)
        else:
            path.moveTo(point)
            active = True
    return path


def build_cap_geometry(steps, positions, plot: QRectF, scale: float):
    if not positions or scale <= 0.0:
        return ()
    result = []
    for step in steps:
        start = min(max(step.start, 0), len(positions) - 1)
        end = min(max(step.end, start), len(positions) - 1)
        ratio = min(max(float(step.value) / scale, 0.0), 1.0)
        result.append(
            CapGeometry(
                plot.left() + positions[start] * plot.width(),
                plot.left() + positions[end] * plot.width(),
                plot.bottom() - ratio * plot.height(),
            )
        )
    return tuple(result)


def paint_stage_band(
    painter: QPainter,
    area: QRectF,
    *,
    fill: QColor,
    text: str,
    font: QFont,
) -> None:
    painter.fillRect(area, fill)
    painter.setPen(QPen(TRACK_BORDER, 1.0))
    painter.drawLine(area.right(), area.top(), area.right(), area.bottom())
    painter.setFont(font)
    painter.setPen(STAGE_TEXT if area.width() >= 55.0 else STAGE_MUTED_TEXT)
    painter.drawText(
        QRectF(
            area.left() + 5.0,
            area.top() + 1.0,
            max(area.width() - 7.0, 8.0),
            17.0,
        ),
        Qt.AlignLeft | Qt.AlignVCenter,
        text,
    )


def paint_playhead(
    painter: QPainter,
    rect: QRectF,
    position: float,
    *,
    color: QColor,
    label: str,
    font: QFont,
) -> None:
    x = rect.left() + max(0.0, min(1.0, position)) * rect.width()
    painter.setPen(QPen(PLAYHEAD_SHADOW, 3.0))
    painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
    painter.setPen(QPen(color, 2.0))
    painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
    badge = QRectF(x - 9.0, rect.top(), 18.0, 15.0)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawRoundedRect(badge, 4.0, 4.0)
    painter.setPen(QColor("#06202B"))
    painter.setFont(font)
    painter.drawText(badge, Qt.AlignCenter, label)


def build_marker_glyphs(markers, positions, rect: QRectF) -> tuple[MarkerGlyph, ...]:
    """Bin events by painted x while retaining every event in the tooltip."""
    bins: dict[int, tuple[float, list]] = {}
    for marker in markers:
        if not 0 <= marker.index < len(positions):
            continue
        x = rect.left() + positions[marker.index] * rect.width()
        key = int(x // MARKER_BIN_WIDTH)
        if key not in bins:
            bins[key] = (x, [])
        bins[key][1].append(marker)

    top = rect.bottom() - MARKER_STRIP_HEIGHT
    glyphs = []
    for _key, (x, events) in sorted(bins.items()):
        winner = max(events, key=lambda marker: _MARKER_RANK.get(marker.kind, 0))
        texts = [marker.text for marker in events]
        if len(texts) > MARKER_TOOLTIP_MAX_LINES:
            hidden = len(texts) - MARKER_TOOLTIP_MAX_LINES
            texts = texts[:MARKER_TOOLTIP_MAX_LINES] + [f"+{hidden} more"]
        glyphs.append(
            MarkerGlyph(
                x=x,
                kind=winner.kind,
                color=QColor(winner.color),
                hit_rect=QRectF(
                    x - 5.0,
                    top - MARKER_HOVER_SLACK,
                    10.0,
                    MARKER_STRIP_HEIGHT + MARKER_HOVER_SLACK * 2.0,
                ),
                tooltip="\n".join(texts),
            )
        )
    return tuple(glyphs)


def paint_marker_glyphs(painter: QPainter, glyphs) -> None:
    painter.setPen(Qt.NoPen)
    for glyph in glyphs:
        center_y = glyph.hit_rect.center().y()
        painter.setBrush(glyph.color)
        if glyph.kind == "banish":
            painter.drawEllipse(QRectF(glyph.x - 2.5, center_y - 2.5, 5.0, 5.0))
        else:
            painter.save()
            painter.translate(glyph.x, center_y)
            painter.rotate(45.0)
            painter.drawRect(QRectF(-2.6, -2.6, 5.2, 5.2))
            painter.restore()
