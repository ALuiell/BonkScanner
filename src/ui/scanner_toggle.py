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

Everything above is `SegmentedToggle`'s now; the recording strip wanted the
same control and got it. What is left here is the one thing that is about
scanners: where the state comes from.

How the scanner drives it
=========================

Through ``setText``, unchanged. ``gui_scanner.update_status_ui`` writes
``"Stop Scanner"`` while scanning and ``"Start Scanner"`` otherwise, and that
call is this widget's only state channel -- the port hands it a "toggle_btn"
and knows nothing else about it. ``setText`` therefore reads the caption back
into a state rather than painting it anywhere; ``test_scanner_toggle`` pins
that coupling so it cannot rot into a silent no-op.

``update_status_ui`` also calls ``_set_widget_style_role(toggle_btn, ...)``,
which assigns ``objectName`` -- so this frame's name flips between ``primary``
and ``stopScanner`` at runtime and cannot be used to style it. That is why the
container is selected by a *property* (``[segmentedToggle="true"]``) in the
QSS: the role swap leaves properties alone, so the frame keeps its background
through both states without needing the scanner to know it changed shape.
"""

from __future__ import annotations

from PySide6.QtCore import Signal

from ui.segmented_toggle import ROLE_GO, ROLE_HALT, SegmentedToggle


class ScannerToggle(SegmentedToggle):
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
        super().__init__(
            (
                ("start", "▶  Start", ROLE_GO),
                ("stop", "■  Stop", ROLE_HALT),
            ),
            parent,
        )
        self.activated.connect(lambda _key: self.toggle_requested.emit())
        self._text = self.START_TEXT
        self.set_active("start")

    # -- the scanner's port ---------------------------------------------------

    def setText(self, text) -> None:
        """Adopt the state `text` names. The port's only state channel."""
        self._text = str(text)
        running = self._text.strip() == self.STOP_TEXT
        self.set_active("stop" if running else "start")

    def text(self) -> str:
        return self._text

    def is_running(self) -> bool:
        """Which segment is live. For tests and for callers that need to ask."""
        return self.active_key() == "stop"
