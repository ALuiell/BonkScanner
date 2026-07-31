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
