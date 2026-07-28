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

#: Which states are alive: the scanner running, and a recording in progress.
#: Both are things that keep happening while the user looks elsewhere, which
#: is what the ring is for. The off states -- `idle`, `off` -- sit still.
PULSING_STATES = ("running", "on")

DOT_DIAMETER = 8
#: The widget is wider than the dot because the ring needs somewhere to go, so
#: ~5px of it is transparent on each side. Anything placing a caption next to
#: one of these has to take that off its own spacing or the pair reads as two
#: unrelated things -- see `LABEL_SPACING`.
WIDGET_SIZE = 18
#: Gap between a dot and its caption, chosen against the padding above: 3 here
#: is about 8px of visible space.
LABEL_SPACING = 3
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
        # `isVisible` is half the condition, not a nicety: a dot whose state is
        # set before anything shows it -- during `_build_header`, or on a panel
        # the user has not opened -- would otherwise start a repaint loop with
        # nothing on screen to give it away. `hideEvent` cannot catch that one,
        # because nothing hides a widget that was never shown.
        should_pulse = (
            str(self.property("state") or "") in PULSING_STATES and self.isVisible()
        )
        if should_pulse and not self.is_pulsing():
            self._animation.start()
        elif not should_pulse and self.is_pulsing():
            self._animation.stop()
            self._set_pulse(0.0)

    def hideEvent(self, event) -> None:
        # Nothing off screen should be asking for repaints -- a collapsed panel
        # or a minimised window is as good a reason to stop as a state change.
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
    """`● REC` -- always on the line, lit only while a recording is running.

    Deliberately not hidden when idle. The question it answers is "is a
    recording running", and a widget that is absent when the answer is no
    cannot be told apart from one that is broken, missing or on a tab the user
    is not looking at -- which is how it read the first time.

    Green while recording -- `gui_overlay`'s convention for the OBS server's
    `Live` line, rather than a camera's REC lamp where red means recording. The
    app already had one of these, so the flag matches it. It pulses for the
    same reason the scanner's dot does: a recording keeps running while the
    user is looking at something else.

    Grey when it is not. Red was tried and read as a fault rather than as "no
    recording" -- an idle state should be quiet, and the header already spells
    "nothing is happening" in `#5C6675` next to the scanner's own dot.

    The dot carries the state and the caption does not, for the same reason:
    a coloured word "REC" is an alarm, a coloured circle is a lamp.

    Its own widget rather than two loose header children so the pair moves and
    switches together, and so the caption sits against the dot rather than a
    dot's width away from it.
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("recFlag")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(LABEL_SPACING)

        # `recDot`, not `statusDot`: the two answer different questions and
        # their states do not line up -- this one is on/off, the scanner's is
        # idle/running -- so they get their own colour rules.
        self._dot = PulsingDot()
        self._dot.setObjectName("recDot")
        layout.addWidget(self._dot, 0, Qt.AlignVCenter)

        self._text = QLabel("REC")
        self._text.setObjectName("recText")
        layout.addWidget(self._text, 0, Qt.AlignVCenter)

        self.set_recording(False)

    def set_recording(self, recording: bool) -> None:
        """Light or dim the flag. Called once a second by `update_timer`."""
        self._recording = bool(recording)
        _set_state(self._dot, "on" if self._recording else "off")

    def is_recording(self) -> bool:
        return self._recording


def _set_state(widget, state: str) -> None:
    """Assign `state` and make Qt re-match the stylesheet against it.

    The same two steps `_set_widget_style_role` takes, minus the objectName --
    these two widgets keep theirs, and importing `ui.styles` from here would
    put a cycle between the widget module and the stylesheet module.
    """
    if widget.property("state") == state:
        return
    widget.setProperty("state", state)
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
