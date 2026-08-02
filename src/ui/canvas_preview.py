"""A scaled, read-only picture of where the overlay widgets sit.

Deliberately not draggable. Two editors already write this geometry -- the
browser's `?edit=true` mode, which POSTs to `/api/save-widget-positions`, and
the in-game overlay's own edit mode -- and a third writer over the same numbers
with its own clamping rules is how they drift apart quietly. At the size this
sits in a side column the scale is roughly 1:6, so a drag here would carry six
real pixels per screen pixel anyway, and the true size of a widget is not known
in advance: it depends on the text in it.

What it is for is the one question the tab could not answer before -- "is my
layout still what I think it is?" -- which needs the real coordinates and
nothing else.

The frame follows the *real* canvas aspect ratio rather than the mock's
hardcoded 16:9. The canvas is user-set, and drawing a 16:9 box around a
2560x1080 canvas would mislead exactly the people who changed it.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QEvent, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

LEGEND_COLUMNS = 2
GRID_STEP = 28
MIN_BLOCK_WIDTH = 14
MIN_BLOCK_HEIGHT = 8

#: What to draw for a widget whose real size is unknown, **in canvas units**, so
#: it scales down with everything else. Sizing an unknown block from its label's
#: pixel width instead was the first version's mistake: at roughly 1:6 the text
#: "Scanner status" measures three to four times the real widget, and the block
#: then had to be pushed inward to fit the frame -- so a widget sitting against
#: the right edge was drawn near the middle, which is the opposite of what a
#: position preview is for.
DEFAULT_BLOCK_WIDTH = 220
DEFAULT_BLOCK_HEIGHT = 48


@dataclass(frozen=True)
class PreviewWidget:
    """One block to draw: a label and where it sits on the canvas.

    `width` and `height` are in canvas units, like `x` and `y`. Zero means "not
    known" and takes the default above -- never a size derived from the label,
    which does not scale with the canvas.

    `marker` is what actually gets painted in the block. A true-size block on a
    2560-wide canvas in a 360px column is around twenty pixels across, so a name
    in it is either elided to "St..." or not drawn at all -- which is what the
    first version looked like. The name goes to the legend and the tooltip
    instead, and the block carries a number.
    """

    label: str
    x: int
    y: int
    width: int = 0
    height: int = 0
    marker: str = ""


class CanvasPreview(QWidget):
    """Draws `PreviewWidget`s scaled into a canvas-shaped frame."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("canvasPreview")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._canvas_width = 1920
        self._canvas_height = 1080
        self._widgets: tuple[PreviewWidget, ...] = ()
        self._placeholder = ""

    # -- content --------------------------------------------------------------

    def set_canvas(self, width: int, height: int) -> None:
        self._canvas_width = max(1, int(width))
        self._canvas_height = max(1, int(height))
        self.updateGeometry()
        self.update()

    def set_widgets(self, widgets) -> None:
        self._widgets = tuple(widgets)
        self.update()

    def set_placeholder(self, text: str) -> None:
        """Say why there is nothing to draw, instead of drawing an empty grid.

        The OBS overlay lays widgets out by flow when none of them has explicit
        coordinates -- that layout lives in the page's CSS and cannot be
        reproduced here, so an empty frame would be a lie rather than a blank.
        """
        self._placeholder = str(text)
        self.update()

    # -- geometry -------------------------------------------------------------

    def heightForWidth(self, width: int) -> int:
        return max(1, round(width * self._canvas_height / self._canvas_width))

    def hasHeightForWidth(self) -> bool:
        return True

    def sizeHint(self):
        from PySide6.QtCore import QSize

        width = max(200, self.width() or 320)
        return QSize(width, self.heightForWidth(width))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.setFixedHeight(self.heightForWidth(self.width()))

    # -- identifying a block --------------------------------------------------

    def legend_html(self) -> str:
        """The numbered names, as a two-column table for a `QLabel`.

        The numbers are all the blocks can carry, so the mapping has to live
        somewhere; putting it right under the canvas keeps it in one glance
        rather than behind a hover.
        """
        if self._placeholder or not self._widgets:
            return ""
        cells = [
            "<td style='color:#38BDF8; padding-right:4px'>{marker}</td>"
            "<td style='color:#8A94A3; padding-right:12px'>{label}</td>".format(
                marker=widget.marker or "•", label=widget.label
            )
            for widget in self._widgets
        ]
        rows = [
            "<tr>" + "".join(cells[index:index + LEGEND_COLUMNS]) + "</tr>"
            for index in range(0, len(cells), LEGEND_COLUMNS)
        ]
        return "<table cellspacing='0' cellpadding='0'>" + "".join(rows) + "</table>"

    def widget_at(self, point) -> PreviewWidget | None:
        """The block under `point`, latest first so the top one wins."""
        for widget, block in reversed(list(zip(self._widgets, self.block_rects()))):
            if block.contains(point):
                return widget
        return None

    def event(self, event):
        """Name the block under the cursor.

        The blocks are far too small to hold a name at this scale, so hovering
        is how you check one without counting down the legend.
        """
        if event.type() == QEvent.ToolTip:
            widget = self.widget_at(event.pos())
            if widget is None:
                QToolTip.hideText()
            else:
                QToolTip.showText(
                    event.globalPos(),
                    f"{widget.label} — {widget.x}, {widget.y}",
                    self,
                )
            return True
        return super().event(event)

    # -- placement ------------------------------------------------------------

    def frame_rect(self) -> QRect:
        return self.rect().adjusted(0, 0, -1, -1)

    def block_rects(self) -> list[QRect]:
        """Where each widget's block lands, in this widget's coordinates.

        Split out of `paintEvent` so placement can be asserted directly. Testing
        it through rendered pixels was tried and is a poor bargain: the grid
        lines behind the blocks make "differs from the background" true almost
        everywhere, so the probe measures the grid rather than the block.
        """
        frame = self.frame_rect()
        if self._placeholder or not self._widgets:
            return []
        scale_x = frame.width() / self._canvas_width
        scale_y = frame.height() / self._canvas_height
        rects = []
        for widget in self._widgets:
            rects.append(
                QRect(
                    frame.left() + round(widget.x * scale_x),
                    frame.top() + round(widget.y * scale_y),
                    max(MIN_BLOCK_WIDTH, round((widget.width or DEFAULT_BLOCK_WIDTH) * scale_x)),
                    max(MIN_BLOCK_HEIGHT, round((widget.height or DEFAULT_BLOCK_HEIGHT) * scale_y)),
                )
            )
        return rects

    # -- painting -------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, False)
        frame = self.rect().adjusted(0, 0, -1, -1)

        painter.fillRect(frame, QColor("#0B0F14"))
        painter.setPen(QPen(QColor("#1B222B"), 1))
        for x in range(frame.left() + GRID_STEP, frame.right(), GRID_STEP):
            painter.drawLine(x, frame.top(), x, frame.bottom())
        for y in range(frame.top() + GRID_STEP, frame.bottom(), GRID_STEP):
            painter.drawLine(frame.left(), y, frame.right(), y)

        painter.setPen(QPen(QColor("#2A3542"), 1))
        painter.drawRect(frame)

        if self._placeholder:
            painter.setPen(QColor("#5C6675"))
            painter.drawText(
                frame.adjusted(12, 12, -12, -12),
                Qt.AlignCenter | Qt.TextWordWrap,
                self._placeholder,
            )
            return

        label_font = QFont(painter.font())
        label_font.setPointSizeF(max(6.0, label_font.pointSizeF() - 2.0))
        painter.setFont(label_font)
        metrics = QFontMetrics(label_font)

        # Everything below is clipped to the frame rather than moved into it.
        # The block's top-left is the whole answer this widget exists to give,
        # so it is drawn where the coordinates say and cut off at the edge if it
        # does not fit -- a widget hanging off the right edge should look like
        # one, not be quietly slid inward until it fits.
        painter.setClipRect(frame)

        for widget, block in zip(self._widgets, self.block_rects()):
            painter.fillRect(block, QColor(47, 111, 176, 150))
            painter.setPen(QPen(QColor("#3E82C6"), 1))
            painter.drawRect(block)

            marker = widget.marker or widget.label[:1]
            painter.setPen(QColor("#EDF1F5"))
            if metrics.horizontalAdvance(marker) + 4 <= block.width():
                painter.drawText(block, Qt.AlignCenter, marker)
            else:
                # Too small even for a digit. The block still says *where*, and
                # the legend and the tooltip still say what -- better than an
                # elided glyph that reads as a rendering fault.
                pass

        painter.setClipping(False)
        painter.setPen(QColor("#5C6675"))
        painter.drawText(
            frame.adjusted(0, 0, -6, -4),
            Qt.AlignRight | Qt.AlignBottom,
            f"{self._canvas_width} × {self._canvas_height}",
        )
