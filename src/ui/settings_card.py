"""A numbered card with a title, a sub-line and an optional header action.

The streaming tabs are a numbered sequence -- setup, then what is visible, then
how it behaves -- and the number is the point: it says the cards are steps in an
order, not three unrelated boxes. `QGroupBox` cannot carry that. Its title is a
single string drawn into the frame's border, so the sub-line, the step number
and the right-aligned action button would each have to be smuggled in as extra
widgets inside the body, below a border the title has already cut through.

So this is a plain frame with a header row of its own. What it buys over the
group boxes it replaces is exactly the three things the mock's card head has and
a group box title has nowhere to put.

`body` is the layout callers fill. Everything else is header furniture.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

#: How wide the working area of a streaming tab is allowed to get, and how wide
#: its right-hand rail is.
#:
#: Both are ceilings rather than decoration. Measured on the shipped build at
#: 1920: a card stretched to the full width put a tile's switch about 450px from
#: its name, and a URL field 1450px wide held a 30-character URL. Past roughly
#: this width a row stops being a row and becomes two things at opposite ends of
#: the screen.
WORKSPACE_MAX_WIDTH = 1560
RAIL_WIDTH = 348

#: The OBS rail is wider than the others, and it has to be. Its preview is
#: locked to the canvas aspect, so the rail's width *is* the preview's height:
#: at 348 a 16:9 canvas is 196px tall, which is the small picture it was already
#: getting. 520 buys ~292px without pushing the preview into a full-width strip
#: under the cards, where the tip beside it ends up stretched across a quarter
#: of the screen to hold two lines.
OBS_RAIL_WIDTH = 520


def build_workspace(parent_layout: QVBoxLayout, *, rail_width: int | None = RAIL_WIDTH):
    """A capped, centred main column with an optional fixed rail beside it.

    Returns `(main_layout, rail_layout)`; `rail_layout` is `None` when
    `rail_width` is None. The rail is a fixed width on purpose -- letting it
    size to its contents is what collapsed the In-Game rail to 180px the moment
    its preview was removed, leaving a paragraph wrapping every three words.
    """
    holder = QWidget()
    holder.setMaximumWidth(WORKSPACE_MAX_WIDTH)

    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(12)

    main_layout = QVBoxLayout()
    main_layout.setSpacing(12)
    row.addLayout(main_layout, 1)

    rail_layout = None
    if rail_width:
        rail_holder = QWidget()
        rail_holder.setFixedWidth(int(rail_width))
        rail_layout = QVBoxLayout(rail_holder)
        rail_layout.setContentsMargins(0, 0, 0, 0)
        rail_layout.setSpacing(12)
        row.addWidget(rail_holder, 0, Qt.AlignTop)

    # Centred with a spacer either side and the cap doing the limiting, *not*
    # with `Qt.AlignHCenter`. Alignment makes a widget take its size hint rather
    # than the space offered, which collapsed the whole working area to about a
    # third of the window: cards came out 520px wide and the Copy button was cut
    # in half. Here the holder takes what it is given up to `maximumWidth` and
    # the two spacers split whatever is left, which is the same thing a max-width
    # and auto margins do on the web.
    centring = QHBoxLayout()
    centring.setContentsMargins(0, 0, 0, 0)
    centring.addStretch(1)
    centring.addWidget(holder, 8)
    centring.addStretch(1)
    parent_layout.addLayout(centring)

    return main_layout, rail_layout


class SettingsCard(QFrame):
    """Header (number, title, sub-line, optional action) over a body layout."""

    def __init__(
        self,
        *,
        number: int | None,
        title: str,
        subtitle: str = "",
        action: QPushButton | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settingsCard")
        self.setProperty("settingsCard", "true")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("settingsCardHead")
        header.setProperty("settingsCardHead", "true")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(12, 9, 12, 9)
        header_row.setSpacing(10)

        if number is not None:
            badge = QLabel(str(number))
            badge.setObjectName("settingsCardNumber")
            badge.setAlignment(Qt.AlignCenter)
            badge.setFixedSize(22, 22)
            header_row.addWidget(badge)

        copy_column = QVBoxLayout()
        copy_column.setContentsMargins(0, 0, 0, 0)
        copy_column.setSpacing(1)
        self._title = QLabel(str(title))
        self._title.setObjectName("settingsCardTitle")
        copy_column.addWidget(self._title)
        # Parented to `header` at construction, which is not cosmetic: a
        # parentless widget told to show becomes a top-level window and flashes
        # on screen. Adding it to `copy_column` first is not enough either --
        # that layout is not installed on a widget yet, so it has no parent to
        # hand down. `test_startup_window_order` caught eight of these, one per
        # card, and it caught them the second time too.
        self._subtitle = QLabel(str(subtitle), header)
        self._subtitle.setObjectName("settingsCardSubtitle")
        self._subtitle.setWordWrap(True)
        copy_column.addWidget(self._subtitle)
        # Hidden rather than skipped: a card that gains a sub-line later should
        # not have to grow a layout for it.
        self._subtitle.setVisible(bool(subtitle))
        header_row.addLayout(copy_column, 1)

        self._action = action
        if action is not None:
            header_row.addWidget(action, 0, Qt.AlignVCenter)

        outer.addWidget(header)

        body_holder = QWidget()
        body_holder.setObjectName("settingsCardBody")
        self._body = QVBoxLayout(body_holder)
        self._body.setContentsMargins(12, 12, 12, 12)
        self._body.setSpacing(10)
        outer.addWidget(body_holder)

    @property
    def body(self) -> QVBoxLayout:
        """The layout callers put their controls into."""
        return self._body

    @property
    def action(self) -> QPushButton | None:
        return self._action

    def set_subtitle(self, subtitle: str) -> None:
        self._subtitle.setText(str(subtitle))
        self._subtitle.setVisible(bool(subtitle))
