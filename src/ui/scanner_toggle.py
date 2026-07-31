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
same control and got it. The caption channel below it is `RunToggle`'s, because
the three streaming tabs drive their toggles exactly this way -- see that
module for why a caption is the state, and what that costs.

What is left here is the one thing that is about scanners: which two literals
``gui_scanner.update_status_ui`` writes. ``test_scanner_toggle`` pins that
coupling so it cannot rot into a silent no-op.
"""

from __future__ import annotations

from ui.run_toggle import RunToggle


class ScannerToggle(RunToggle):
    """`RunToggle` carrying the scanner's caption pair."""

    #: The two captions `gui_scanner.update_status_ui` writes. Named because
    #: `setText` compares against them; a typo on either side would otherwise
    #: leave the control stuck on Start with nothing raising.
    START_TEXT = "Start Scanner"
    STOP_TEXT = "Stop Scanner"

    def __init__(self, parent=None) -> None:
        super().__init__(self.START_TEXT, self.STOP_TEXT, parent)
