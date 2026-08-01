"""The chrome every dialog in the app shares: a head, a body and a footer.

There are fourteen dialogs and, before this, no two agreed on anything. Their
widths were 223, 258, 274, 298, 305, 348, 355, 420, 560, 589, 640 and 760 --
not a scale, just whatever each one's content happened to add up to on the day.
Half had no title inside the window, so the only thing naming them was the OS
title bar. Their buttons sat flush against the frame in some and inset in
others, and the destructive one was sometimes beside the dismiss button and
sometimes across the window from it.

None of that is visible in any single dialog. It is visible in the *set*: open
two in a row and the second one looks like it came from a different program.

So this module is the set. A dialog says what it is called and how much room its
content needs; everything else -- margins, the rule under the title, where the
buttons go, which of them is dangerous -- is decided here, once.

Sizes are a scale of three, not a free number:

* ``DIALOG_COMPACT`` -- one question and its answer. A confirmation.
* ``DIALOG_REGULAR`` -- a form, or a paragraph with a choice under it.
* ``DIALOG_WIDE`` -- content that needs room of its own: a picker, a table, a
  page of help.

Height is deliberately not on the scale. A confirmation is as tall as its
sentence and a form as tall as its rows; fixing that too would only add empty
space to the short ones. ``DIALOG_TALL`` exists for the wide dialogs, whose
content scrolls and therefore has no natural height to be.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

#: The three widths. A dialog picks the one that fits what it holds; a number
#: that is not one of these is what the set looked like before.
DIALOG_COMPACT = 420
DIALOG_REGULAR = 560
DIALOG_WIDE = 900

#: For the wide dialogs only -- their content scrolls, so it has no height of
#: its own to adopt.
DIALOG_TALL = 720

#: One set of margins, so the gap between a button and the frame is the same
#: gap in every window.
MARGIN = 16
SPACING = 12


def dialog_body(
    dialog: QDialog,
    *,
    title: str,
    subtitle: str = "",
    width: int = DIALOG_REGULAR,
    height: int | None = None,
) -> QVBoxLayout:
    """Install the shared chrome on `dialog`; return the layout for its content.

    The title is repeated inside the window rather than left to the title bar.
    Half of these dialogs are opened from a button whose caption the user has
    already forgotten by the time the window is up, and the bar is a thin strip
    of OS chrome above a dark window -- the first thing read is what is inside.

    `width` is a minimum, not a cap: a form with a long field is allowed to be
    wider than its class, and holding it to the scale would clip the field
    instead. What the scale fixes is the floor, which is what made a
    confirmation 223px wide and the one after it 348.
    """
    dialog.setMinimumWidth(int(width))
    if height is not None:
        dialog.resize(int(width), int(height))

    outer = QVBoxLayout(dialog)
    outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
    outer.setSpacing(SPACING)

    head = QWidget()
    head.setObjectName("dialogHead")
    head_layout = QVBoxLayout(head)
    head_layout.setContentsMargins(0, 0, 0, 0)
    head_layout.setSpacing(2)

    title_label = QLabel(str(title), head)
    title_label.setObjectName("dialogTitle")
    head_layout.addWidget(title_label)

    if subtitle:
        subtitle_label = QLabel(str(subtitle), head)
        subtitle_label.setObjectName("dialogSubtitle")
        subtitle_label.setWordWrap(True)
        head_layout.addWidget(subtitle_label)

    outer.addWidget(head)

    rule = QFrame()
    rule.setObjectName("dialogHeadRule")
    rule.setFrameShape(QFrame.NoFrame)
    outer.addWidget(rule)

    body = QVBoxLayout()
    body.setContentsMargins(0, 0, 0, 0)
    body.setSpacing(SPACING)
    outer.addLayout(body, 1)

    # Held on the dialog so `dialog_footer` can find where to put itself
    # without every caller having to pass the layout back in.
    dialog._shell_outer = outer  # noqa: SLF001 -- the shell's own bookkeeping
    return body


def dialog_footer(
    dialog: QDialog,
    *,
    primary: QPushButton | None = None,
    secondary: QPushButton | None = None,
    destructive: QPushButton | None = None,
    leading: QWidget | None = None,
) -> QWidget:
    """The button row: destructive on the left, the rest on the right.

    The gap between them is the point. `Delete Selected` used to sit shoulder to
    shoulder with `Cancel`, and a delete that is one slip away from the button
    you press to back out is a delete that happens by accident. Putting it at
    the other end costs nothing and is the only protection a modal offers.

    Right-hand order is secondary then primary, so the affirmative one is always
    the last thing before the corner -- the same place in every window.
    """
    footer = QWidget()
    footer.setObjectName("dialogFooter")
    row = QHBoxLayout(footer)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)

    if destructive is not None:
        destructive.setObjectName("danger")
        row.addWidget(destructive)
    if leading is not None:
        # `Don't show this again` and its kind: a control about the dialog
        # rather than an answer to it, so it sits away from the answers.
        row.addWidget(leading)
    row.addStretch(1)
    if secondary is not None:
        row.addWidget(secondary)
    if primary is not None:
        primary.setObjectName("primary")
        primary.setDefault(True)
        row.addWidget(primary)

    outer = getattr(dialog, "_shell_outer", None)
    if outer is None:
        # A dialog that never called `dialog_body`. Returning the row unplaced
        # would leave it a top-level window -- see `SettingsCard`'s sub-line.
        raise RuntimeError("dialog_footer needs dialog_body to have run first")
    outer.addWidget(footer)
    return footer


def dialog_card(text: str) -> QFrame:
    """The tinted "read this" paragraph -- Auto-Reroll, the OBS reminder.

    Object name unchanged from when these were the only styled dialogs in the
    app, so the rule in the redesign sheet still finds them. What changed is
    that the card no longer carries a title of its own: it sits under the shared
    head, and two titles in one small window read as two separate things.
    """
    card = QFrame()
    card.setObjectName("WarningCard")
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 12, 14, 12)
    layout.setSpacing(0)
    body = QLabel(str(text), card)
    body.setObjectName("dialogCardText")
    body.setWordWrap(True)
    body.setTextFormat(Qt.RichText)
    layout.addWidget(body)
    return card


def dialog_note(text: str, *, parent: QWidget | None = None) -> QLabel:
    """A muted line under the content -- the "you can turn this off" sentence."""
    note = QLabel(str(text), parent)
    note.setObjectName("dialogNote")
    note.setWordWrap(True)
    note.setTextFormat(Qt.RichText)
    return note
