"""A Start/Stop pair of segments driven by the caption its owner writes.

`ScannerToggle` was the first of these, and the three streaming tabs wanted the
same control: OBS's server, the Twitch bot and the in-game overlay each had a
single button that swapped its own caption between `Start X` and `Stop X` and
its QSS role between `primary` and `stopScanner`. That is the shape
`SegmentedToggle` exists to replace -- captions that never change, so the
control is one width in every state, and the dim segment left on screen to say
what the other half of the state is.

What makes it a drop-in is the *channel*, not the look. None of the three owners
says "running" out loud; each writes a caption:

* `refresh_overlay_ui` -> `"Stop Server"` / `"Start Server"`
* `update_in_game_overlay_status_ui` -> `"Stop Overlay"` / `"Start Overlay"`
* `show_bot_running` / `show_bot_stopped` -> `"Stop Bot"` / `"Start Bot"`

So `setText` reads the caption back into a state rather than painting it, and
the callers keep working untouched. The pair of literals is a constructor
argument because it is the only thing that differs between the four instances.

`_set_widget_style_role` is also called on all four, and it assigns
`objectName` -- so this frame's name flips between `primary` and `stopScanner`
at runtime and cannot be used to style it. `SegmentedToggle` already handles
that by selecting the container on the `segmentedToggle` *property*, which the
role swap leaves alone.

**A caption channel fails silently.** A typo on either side -- here or in the
owner -- leaves the toggle stuck on Start with nothing raising and every test
green. `test_run_toggle` drives each owner's literal pair through `setText` and
asserts which segment came out live; that is the only thing standing between a
renamed caption and a control that quietly stops working.
"""

from __future__ import annotations

from PySide6.QtCore import Signal

from ui.segmented_toggle import ROLE_GO, ROLE_HALT, SegmentedToggle

# The caption pairs, as `(start, stop)`, named here rather than written inline
# on both sides of the channel. That is not tidiness: the failure this control
# invites is the *two* literals drifting apart -- the owner renaming its caption
# while the toggle keeps comparing against the old one, which leaves the segment
# stuck with nothing raising. One name each means there is only one literal to
# rename, so the two sides cannot disagree.
OVERLAY_SERVER_CAPTIONS = ("Start Server", "Stop Server")
TWITCH_BOT_CAPTIONS = ("Start Bot", "Stop Bot")
IN_GAME_OVERLAY_CAPTIONS = ("Start Overlay", "Stop Overlay")


class RunToggle(SegmentedToggle):
    """Two segments -- Start and Stop -- of which exactly one is live."""

    #: Emitted when the user presses the live segment. Owners connect it to
    #: whatever their old button's `clicked` drove.
    toggle_requested = Signal()

    def __init__(self, start_text: str, stop_text: str, parent=None) -> None:
        super().__init__(
            (
                ("start", "▶  Start", ROLE_GO),
                ("stop", "■  Stop", ROLE_HALT),
            ),
            parent,
        )
        self._start_text = str(start_text)
        self._stop_text = str(stop_text)
        self.activated.connect(lambda _key: self.toggle_requested.emit())
        self._text = self._start_text
        self.set_active("start")

    # -- the owner's port -----------------------------------------------------

    def setText(self, text) -> None:
        """Adopt the state `text` names. The port's only state channel."""
        self._text = str(text)
        running = self._text.strip() == self._stop_text
        self.set_active("stop" if running else "start")

    def text(self) -> str:
        return self._text

    def is_running(self) -> bool:
        """Which segment is live. For tests and for callers that need to ask."""
        return self.active_key() == "stop"
