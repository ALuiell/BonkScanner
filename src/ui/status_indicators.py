"""The header's live indicators: a status dot that pulses, and a REC flag.

Why the dot is painted rather than styled
=========================================

The dot used to be a `QLabel` that Qt filled from the stylesheet -- 8x8, a 4px
radius, `background-color` picked by a `state` property. That draws a circle
and nothing else: QSS has no animation, and the widget was clamped to the
circle's own size, so there was no room around it to draw into either.

`PulsingDot` keeps the label and the `state` property -- `gui_scanner` still
drives it through `_set_widget_style_role(dot, "statusDot", state=...)` and
knows nothing new -- but takes over the painting. The widget is 18x18 with a
transparent background, the 8px dot is drawn in its centre, and a ring expands
out of it and fades while the scanner is live. That is the animation the flat
`background-color` could not express.

The colours stay in the stylesheet. `dotColor` is a real Qt property, so the
QSS sets it with `qproperty-dotColor` per state, exactly where the old
`background-color` per state was. Nothing about which colour means what moved
into Python.

Why the animation is driven by the property, not by a caller
============================================================

Nobody tells this widget to start pulsing. `_set_widget_style_role` assigns
`state` and re-polishes, and that is the only signal there is -- adding a
`start_pulse()` for the scanner to call would mean a second channel that can
disagree with the first. `event()` watches for `DynamicPropertyChange` instead,
which fires however the property was set, so the animation cannot drift out of
step with the colour.
"""

from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QEvent, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

#: Which states are alive. `rec` pulses for the same reason `running` does --
#: something is happening that the user cannot see from the numbers alone.
PULSING_STATES = ("running", "rec")

DOT_DIAMETER = 8
WIDGET_SIZE = 18
#: How far the ring travels past the dot's edge, and how solid it starts.
RING_TRAVEL = 5.0
RING_ALPHA = 170


class PulsingDot(QLabel):
    """The status dot. Solid when idle, pulsing while the state is live."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(WIDGET_SIZE, WIDGET_SIZE)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._dot_color = QColor("#5C6675")
        self._pulse = 0.0

        self._animation = QPropertyAnimation(self, b"pulse", self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(1800)
        self._animation.setLoopCount(-1)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)

    # -- properties the stylesheet and the animation write --------------------

    def _get_dot_color(self) -> QColor:
        return self._dot_color

    def _set_dot_color(self, color: QColor) -> None:
        self._dot_color = QColor(color)
        self.update()

    #: Set from the QSS as `qproperty-dotColor`, per `state`.
    dotColor = Property(QColor, _get_dot_color, _set_dot_color)

    def _get_pulse(self) -> float:
        return self._pulse

    def _set_pulse(self, value: float) -> None:
        self._pulse = float(value)
        self.update()

    pulse = Property(float, _get_pulse, _set_pulse)

    # -- state ----------------------------------------------------------------

    def is_pulsing(self) -> bool:
        return self._animation.state() == QPropertyAnimation.Running

    def event(self, event) -> bool:
        # The only notification there is that `state` changed: whoever set it,
        # including `_set_widget_style_role`, gets here.
        if event.type() == QEvent.DynamicPropertyChange:
            if bytes(event.propertyName()).decode() == "state":
                self._sync_animation()
        return super().event(event)

    def _sync_animation(self) -> None:
        # `isVisible` is half the condition, not a nicety. `RecordingFlag`
        # builds its dot with `state="rec"` and *then* hides itself, so a
        # state-only check leaves a repaint loop running behind a flag the user
        # never sees -- for the whole session, since nothing hides a widget
        # that was never shown and `hideEvent` therefore never fires.
        should_pulse = (
            str(self.property("state") or "") in PULSING_STATES and self.isVisible()
        )
        if should_pulse and not self.is_pulsing():
            self._animation.start()
        elif not should_pulse and self.is_pulsing():
            self._animation.stop()
            self._set_pulse(0.0)

    def hideEvent(self, event) -> None:
        # A hidden REC flag must not keep a repaint loop alive behind it.
        self._animation.stop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_animation()

    # -- painting -------------------------------------------------------------

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        centre = self.rect().center()
        # `+1` because an even-sided rect's centre rounds down, which would put
        # the dot half a pixel off and make the ring visibly lopsided.
        x = centre.x() + 1
        y = centre.y() + 1
        radius = DOT_DIAMETER / 2.0

        if self.is_pulsing():
            ring = QColor(self._dot_color)
            ring.setAlpha(int(RING_ALPHA * (1.0 - self._pulse)))
            painter.setBrush(ring)
            spread = radius + RING_TRAVEL * self._pulse
            painter.drawEllipse(
                float(x) - spread, float(y) - spread, spread * 2, spread * 2
            )

        painter.setBrush(self._dot_color)
        painter.drawEllipse(
            float(x) - radius, float(y) - radius, radius * 2, radius * 2
        )


class RecordingFlag(QWidget):
    """`● REC`, shown only while a recording is running.

    Its own widget rather than two loose header children, so the scanner can
    show and hide the pair with one call and the dot's animation follows the
    visibility -- `PulsingDot.hideEvent` is what stops the loop when the flag
    goes away.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("recFlag")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._dot = PulsingDot()
        self._dot.setObjectName("statusDot")
        self._dot.setProperty("state", "rec")
        layout.addWidget(self._dot, 0, Qt.AlignVCenter)

        self._text = QLabel("REC")
        self._text.setObjectName("recText")
        layout.addWidget(self._text, 0, Qt.AlignVCenter)

        self.setVisible(False)

    def set_recording(self, recording: bool) -> None:
        """Show or hide the flag. Called once a second by `update_timer`."""
        self.setVisible(bool(recording))

    def is_pulsing(self) -> bool:
        return self._dot.is_pulsing()
