"""The scanner's Start/Stop control, as a two-segment toggle.

Replaces the single header button that swapped its own caption between
``Start Scanner`` and ``Stop Scanner``. Two things pushed it out:

* The two captions came with two QSS roles of different weight and padding
  (``primary`` at 12.5px/700, ``stopScanner`` at 13px/800), so the button
  measured 199x34 in one state and 194x37 in the other. ``_build_header_controls``
  pinned ``setMinimumWidth(210)`` / ``setMinimumHeight(38)`` over both to stop
  the header twitching -- a floor propped over a size disagreement. Here the
  segments never change their own text, so the control's width is a property
  of its construction and the floors are gone.
* A caption-swapping button shows the *action* and hides the *state*. Two
  segments show both: the live one is the action available now, the dim one is
  the state's other half.

The lit segment is always the enabled one, so "press the lit one" is the whole
interaction; the dim segment is disabled and cannot fire a start on an already
running scanner.

How the scanner drives it
=========================

Through ``setText``, unchanged. ``gui_scanner.update_status_ui`` writes
``"Stop Scanner"`` while scanning and ``"Start Scanner"`` otherwise, and that
call is this widget's only state channel -- the port hands it a "toggle_btn"
and knows nothing else about it. ``setText`` therefore reads the caption back
into a boolean rather than painting it anywhere; ``test_scanner_toggle`` pins
that coupling so it cannot rot into a silent no-op.

``update_status_ui`` also calls ``_set_widget_style_role(toggle_btn, ...)``,
which assigns ``objectName`` -- so this frame's name flips between ``primary``
and ``stopScanner`` at runtime and cannot be used to style it. That is why the
container is selected by a *property* (``[scannerToggle="true"]``) in the QSS:
the role swap leaves properties alone, so the frame keeps its background
through both states without needing the scanner to know it changed shape.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton


class ScannerToggle(QFrame):
    """Two segments -- Start and Stop -- of which exactly one is live."""

    #: Emitted when the user presses the live segment. The header connects it
    #: to `Scanner.toggle_main_loop`, which is what the old `clicked` drove.
    toggle_requested = Signal()

    #: The two captions `gui_scanner.update_status_ui` writes. Named because
    #: `setText` compares against them; a typo on either side would otherwise
    #: leave the control stuck on Start with nothing raising.
    START_TEXT = "Start Scanner"
    STOP_TEXT = "Stop Scanner"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("scannerToggle")
        # Selected by the QSS instead of the objectName -- see the module
        # docstring for why the name cannot be relied on here.
        self.setProperty("scannerToggle", "true")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)

        self._start_btn = QPushButton("▶  Start")
        self._start_btn.setProperty("segment", "start")
        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setProperty("segment", "stop")
        for button in (self._start_btn, self._stop_btn):
            button.setObjectName("scannerSegment")
            button.setMinimumWidth(96)
            button.setMinimumHeight(30)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(self.toggle_requested)
            layout.addWidget(button)

        self._text = self.START_TEXT
        self._apply(running=False)

    # -- the scanner's port ---------------------------------------------------

    def setText(self, text) -> None:
        """Adopt the state `text` names. The port's only state channel."""
        self._text = str(text)
        self._apply(running=self._text.strip() == self.STOP_TEXT)

    def text(self) -> str:
        return self._text

    # -- state ----------------------------------------------------------------

    def is_running(self) -> bool:
        """Which segment is live. For tests and for callers that need to ask."""
        return self._stop_btn.isEnabled()

    def _apply(self, *, running: bool) -> None:
        for button, live in ((self._start_btn, not running), (self._stop_btn, running)):
            button.setEnabled(live)
            button.setProperty("active", "true" if live else "false")
            _repolish(button)


def _repolish(widget) -> None:
    """Make Qt re-evaluate a widget's QSS after a property changed.

    Property-driven selectors are not re-matched on assignment; without this
    the segments would keep whichever colours they were built with.
    """
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
