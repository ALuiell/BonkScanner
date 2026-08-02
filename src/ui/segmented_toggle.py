"""A row of segments of which exactly one is live.

Generalised out of `ScannerToggle` when the recording strip needed the same
control. What both wanted is the same three properties:

* the captions never change, so the control is one width in every state and
  needs no hand-measured size floor propped over a caption swap;
* the lit segment is the enabled one, so "press the lit one" is the whole
  interaction and a click cannot ask for a transition that is not available;
* the state is visible without reading, because the *other* segment is still
  there to be compared against.

What the two callers do not share is how state arrives. The scanner's toggle
reads it out of a caption `gui_scanner` writes, because that port has no other
channel; the recording strip calls `set_active` directly, because it owns its
own refresh. That difference is the subclass, and it is the only thing in
`ScannerToggle` that is about scanners.

Colours live in the stylesheet, keyed on three properties this widget sets:
`role` (which segment is the affirmative one), `active` (is it the live one),
and `variant` (a qualifier on the live segment, such as `armed`). Adding a
state means adding a QSS rule, not a branch here.
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton

#: The affirmative segment (Start, Rec) and the negative one (Stop). Only the
#: stylesheet reads these; the key is what code uses to name a segment.
ROLE_GO = "go"
ROLE_HALT = "halt"

#: A floor, so `Rec` and `Stop` do not come out as two tiny pills. **Not** a
#: width: see `_Segment` for why the difference is load-bearing.
SEGMENT_MIN_WIDTH = 96
SEGMENT_MIN_HEIGHT = 30


class _Segment(QPushButton):
    """A segment that is never narrower than the floor *or* than its own text.

    These used to carry `setMinimumWidth(SEGMENT_MIN_WIDTH)`, and that is a
    stronger statement than it reads as: Qt ignores `minimumSizeHint` once an
    explicit `minimumSize` is set, so 96px stopped being a floor and became the
    entire minimum. Any layout under pressure was then free to squeeze a
    segment to 96px no matter how long its caption was -- and with the
    stylesheet's `padding: 7px 18px` eating 36 of those, only 60px were left
    for the text.

    `Start` (30px) and `Stop` (28px) fit in 60 and never showed it. The OBS
    tab's `Full overlay` (70px) and `Single widget` (83px) did not, and shipped
    as `ull overla` / `ngle widg` in any window narrow enough to make the
    layout ask.

    Overriding the hint instead keeps the floor and lets Qt's own measurement
    win when it is larger. It is also evaluated *late*, which matters: the
    padding that decides the answer arrives with the stylesheet, long after
    these buttons are constructed.
    """

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(
            max(SEGMENT_MIN_WIDTH, hint.width()),
            max(SEGMENT_MIN_HEIGHT, hint.height()),
        )


class SegmentedToggle(QFrame):
    """Segments in a frame, one live at a time.

    `segments` is `((key, caption, role), ...)`. The key names the segment for
    `set_active` and for tests; the caption is fixed for the widget's life --
    that is what keeps the width constant -- and the role picks its colours.
    """

    #: The key of the segment the user pressed. Only the live segment can emit
    #: it: the others are disabled, so the click never lands.
    activated = Signal(str)

    def __init__(
        self,
        segments: Sequence[tuple[str, str, str]],
        parent=None,
        *,
        disable_inactive: bool = True,
    ) -> None:
        """`disable_inactive` is what the segments *mean*.

        Default: the lit segment is the action available now and the others are
        disabled, so a click cannot ask for a transition that is not on offer --
        the scanner's Start/Stop and the recording strip's Rec/Stop.

        `False`: the segments are choices and the lit one is the current one, so
        every segment stays clickable. The tracked-item picker's Map 1 / Whole
        run is that, and shipping it on the default made "Whole run"
        unselectable -- the segment was disabled, so the rule could not be made
        at all.
        """
        super().__init__(parent)
        self._disable_inactive = bool(disable_inactive)
        self.setObjectName("segmentedToggle")
        # Selected by property rather than objectName in the QSS, because
        # `_set_widget_style_role` renames whatever it is handed and the
        # scanner hands it this frame. See `ScannerToggle`.
        self.setProperty("segmentedToggle", "true")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)

        self._buttons: dict[str, QPushButton] = {}
        self._active_key = ""
        self._variant = ""

        for key, caption, role in segments:
            button = _Segment(caption)
            button.setObjectName("segment")
            button.setProperty("segment", key)
            button.setProperty("role", role)
            button.setProperty("variant", "")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, k=key: self.activated.emit(k))
            layout.addWidget(button)
            self._buttons[key] = button

        if segments:
            self.set_active(segments[0][0])

    # -- state ----------------------------------------------------------------

    def set_active(self, key: str, *, variant: str = "") -> None:
        """Light `key`, disable the rest, and qualify it with `variant`.

        `variant` is a free string the stylesheet may match on -- `armed` on
        the recording strip's Stop segment, for instance. It is cleared on
        every call, so a caller that stops passing it goes back to the plain
        colours rather than keeping the last one it set.
        """
        self._active_key = key
        self._variant = variant

        # The live segment is enabled *first*, and the focus carried onto it if
        # it is sitting on a segment that is about to go dark. Qt does not leave
        # the focus on a widget it has just disabled -- it hands it to the next
        # one in the tab order, and next to these toggles is a `QLineEdit`: the
        # OBS port, the in-game overlay's hotkey. A `QLineEdit` selects its
        # contents when it gains focus, so pressing Start put a caret in a field
        # nobody had asked to edit, and the hotkey field read as armed for a new
        # binding.
        #
        # Order matters twice over: `setFocus` on a disabled widget is a no-op,
        # so the incoming segment cannot take the focus until it is enabled, and
        # the outgoing one must not be disabled until it has given it up.
        live_button = self._buttons.get(key)
        if live_button is not None and self._disable_inactive:
            live_button.setEnabled(True)
            if any(
                button.hasFocus()
                for button_key, button in self._buttons.items()
                if button_key != key
            ):
                live_button.setFocus(Qt.OtherFocusReason)

        for button_key, button in self._buttons.items():
            live = button_key == key
            button.setEnabled(live or not self._disable_inactive)
            _set_properties(
                button,
                active="true" if live else "false",
                variant=variant if live else "",
            )

    def active_key(self) -> str:
        return self._active_key

    def variant(self) -> str:
        return self._variant

    def segment(self, key: str) -> QPushButton:
        """The segment widget for `key`. For tests and for tooltips."""
        return self._buttons[key]


def _set_properties(widget, **properties) -> None:
    """Assign properties and make Qt re-match the stylesheet against them.

    Property-driven selectors are not re-evaluated on assignment, so without
    the repolish a segment keeps whichever colours it was built with. Skipped
    entirely when nothing changed, because a repolish is not free and this runs
    on every refresh tick of the recording strip.
    """
    changed = False
    for name, value in properties.items():
        if widget.property(name) != value:
            widget.setProperty(name, value)
            changed = True
    if not changed:
        return
    style = widget.style()
    if style is None:
        return
    style.unpolish(widget)
    style.polish(widget)
    widget.update()
