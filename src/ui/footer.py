"""The window's bottom strip: version, update status, and the links.

The main window had no footer at all -- ``build_layout`` put a header and a
splitter into the root layout and stopped -- so two things had nowhere to live.
The version was readable only in the title bar and in the log's welcome line,
which scrolls away; and the four support links existed only inside the settings
dialog, which nobody reopens after setting their hotkeys once.

Both go here, on one 28px line, in the register the rest of the secondary text
uses. The Support link is *not* an accent: the header's status dot is what
speaks in colour, and a second coloured element competing with it -- especially
one asking for money -- is the thing that actually annoys people. It warms to
the Patreon red on hover and not before.

The strip spans the whole window rather than sitting inside the 16px content
margins, which is why ``build_layout`` now nests its content in an inner widget:
a footer inset from the edges reads as a floating bar, not as the window's base.
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import config
from app.version import CURRENT_VERSION
from ui.dialogs.update_prompt import start_update_check
from ui.shared import _clear_layout, resource_path

FOOTER_HEIGHT = 28

PATREON_ICON_PATH = "media/patreon_logo.svg"
KOFI_ICON_PATH = "media/kofi_logo.svg"


def _separator() -> QFrame:
    """The hairline between two footer items.

    A `QFrame` with `VLine` draws Qt's own etched line, which is two colours and
    ignores the stylesheet. One pixel of background does what the design asks
    and stays reachable from the QSS -- the same trick `#dialogHeadRule` uses.
    """
    line = QFrame()
    line.setObjectName("footerSeparator")
    line.setFixedWidth(1)
    line.setFixedHeight(11)
    return line


def _link(text: str, object_name: str = "footerLink") -> QPushButton:
    button = QPushButton(text)
    button.setObjectName(object_name)
    button.setFlat(True)
    button.setCursor(Qt.PointingHandCursor)
    # Without this a footer link steals the focus ring on click and keeps it,
    # which on a strip this thin reads as a stuck highlight.
    button.setFocusPolicy(Qt.NoFocus)
    return button


class SupportPopup(QFrame):
    """The two donation platforms, with one line of context.

    A popup rather than a link straight to Patreon, because there are two
    platforms and picking one for the user is a decision nobody asked us to
    make. It is also the only shape that can carry the "free, and stays free"
    sentence -- a bare link carries no context at all -- and the same shape
    grows into the supporters list later without moving.

    `Qt.Popup` gives the dismiss-on-outside-click behaviour for free. The
    translucent top level wrapping an inner card is what lets the card have
    rounded corners: a `Qt.Popup` frame paints its own square background
    underneath them otherwise.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setObjectName("supportPopup")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame(self)
        card.setObjectName("supportPopupCard")
        # Left to `adjustSize` the card came out 238px wide and broke the note
        # after "useful to" -- three words on the second line under twelve on
        # the first. The width is what sets the wrap, so it is stated.
        card.setFixedWidth(268)
        outer.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(12, 11, 12, 12)
        body.setSpacing(3)

        title = QLabel("Support BonkScanner", card)
        title.setObjectName("supportPopupTitle")
        body.addWidget(title)

        note = QLabel(
            "BonkScanner is free to download and stays that way. "
            "If it is useful to you:",
            card,
        )
        note.setObjectName("supportPopupNote")
        note.setWordWrap(True)
        body.addWidget(note)
        self._title = title
        self._note = note

        # The names, when there are any. Built empty and hidden, so the popup
        # is exactly what it was until something calls `set_supporters` -- see
        # that method for why the empty case must look like this and not like a
        # heading over a blank space.
        self._names_host = QWidget(card)
        self._names_host.setObjectName("supporterList")
        self._names_grid = QGridLayout(self._names_host)
        self._names_grid.setContentsMargins(0, 0, 0, 0)
        self._names_grid.setHorizontalSpacing(16)
        self._names_grid.setVerticalSpacing(1)
        self._names_host.setVisible(False)
        body.addWidget(self._names_host)

        self._rule = QFrame(card)
        self._rule.setObjectName("supportPopupRule")
        self._rule.setFixedHeight(1)
        self._rule.setVisible(False)
        body.addWidget(self._rule)

        body.addSpacing(7)

        buttons = QHBoxLayout()
        buttons.setSpacing(7)
        # Same object names as the settings card's buttons, so both places take
        # their brand colours from the one set of rules in the QSS rather than
        # drifting apart. `KOFI_SUPPORT_URL` currently points at a Ko-fi *shop*
        # item rather than the donation page -- the caption says only "Ko-fi"
        # for that reason, and changing the URL is a separate decision.
        self.patreon_btn = QPushButton("Patreon", card)
        self.patreon_btn.setObjectName("PatreonButton")
        self.patreon_btn.setIcon(QIcon(resource_path(PATREON_ICON_PATH)))
        self.patreon_btn.clicked.connect(self._open_patreon)
        self.kofi_btn = QPushButton("Ko-fi", card)
        self.kofi_btn.setObjectName("KofiButton")
        self.kofi_btn.setIcon(QIcon(resource_path(KOFI_ICON_PATH)))
        self.kofi_btn.clicked.connect(self._open_kofi)
        for button in (self.patreon_btn, self.kofi_btn):
            button.setCursor(Qt.PointingHandCursor)
            buttons.addWidget(button, 1)
        body.addLayout(buttons)
        self._card = card

    #: Card widths. The narrow one is set by the note's wrap (see above); the
    #: wide one by two columns of display name, which are user-supplied text and
    #: can be any length -- they ellipsise rather than widen the card further.
    NARROW_WIDTH = 268
    WIDE_WIDTH = 400
    #: Names past this are not listed; the count in the caption still includes
    #: them. A popup is not a page, and a scroll bar inside one is a worse
    #: answer than "and 40 others".
    MAX_LISTED = 24

    def set_supporters(self, supporters=()) -> None:
        """Show these people, or go back to being the plain two-button card.

        **The empty case is the shipping case and must stay unremarkable.**
        Nothing calls this in production yet -- see `FooterView.set_supporters`
        for the seam the data will arrive through -- so what the card looks like
        with no list is what everyone sees today: a title, one line, two
        buttons. No heading over a blank space, no "0 supporters", no rule with
        nothing above it. An empty card reads as a broken feature; a card that
        never mentions the list reads as nothing at all, which is correct.

        Accepts plain names or mappings, so a future `supporters.json` can be
        handed over with no shape negotiation: `"Nyxaria"` and
        `{"name": "Nyxaria", "tier": "gold"}` both work, and anything with a
        truthy `tier` is marked.
        """
        people = []
        for entry in supporters or ():
            if isinstance(entry, dict):
                name = str(entry.get("name") or "").strip()
                tier = bool(entry.get("tier"))
            else:
                name = str(entry or "").strip()
                tier = False
            if name:
                people.append((name, tier))

        _clear_layout(self._names_grid)
        self._names_host.setVisible(bool(people))
        self._rule.setVisible(bool(people))
        self._card.setFixedWidth(self.WIDE_WIDTH if people else self.NARROW_WIDTH)

        if not people:
            self._title.setText("Support BonkScanner")
            self._note.setText(
                "BonkScanner is free to download and stays that way. "
                "If it is useful to you:"
            )
            return

        self._title.setText(f"{len(people)} people support BonkScanner")
        # Tiers first, then the order they arrived in. Not alphabetical: a list
        # someone maintains by hand has an order, and re-sorting it throws away
        # whatever they meant by it.
        people.sort(key=lambda person: not person[1])
        listed = people[: self.MAX_LISTED]
        hidden = len(people) - len(listed)
        self._note.setText(
            "Thank you." if not hidden else f"Thank you, and {hidden} more."
        )

        rows = (len(listed) + 1) // 2
        for index, (name, tier) in enumerate(listed):
            label = QLabel(("♦  " if tier else "") + name, self._names_host)
            label.setObjectName("supporterNameTier" if tier else "supporterName")
            # Elided rather than wrapped, and the grid column carries the width:
            # a display name is whatever its owner typed, and one long one must
            # not be allowed to widen the popup or reflow the column beside it.
            label.setTextFormat(Qt.PlainText)
            label.setToolTip(name)
            self._names_grid.addWidget(label, index % rows, index // rows)
        self._names_grid.setColumnStretch(0, 1)
        self._names_grid.setColumnStretch(1, 1)

    def _open_patreon(self) -> None:
        webbrowser.open(config.PATREON_SUPPORT_URL)
        self.close()

    def _open_kofi(self) -> None:
        webbrowser.open(config.KOFI_SUPPORT_URL)
        self.close()

    def show_above(self, anchor: QWidget) -> None:
        """Open with the popup's bottom-right corner over `anchor`'s top-right."""
        self.adjustSize()
        top_right = anchor.mapToGlobal(QPoint(anchor.width(), 0))
        self.move(top_right.x() - self.width(), top_right.y() - self.height() - 8)
        self.show()


class FooterView:
    """The strip, and the one thing anything outside here can tell it."""

    def __init__(
        self,
        *,
        app,
        frame: QFrame,
        update_btn: QPushButton,
        update_separator: QFrame,
        support_btn: QPushButton,
    ) -> None:
        self._app = app
        self.frame = frame
        self._update_btn = update_btn
        # Hidden and shown with the control it divides. A separator is a claim
        # that there is something on both sides of it; left standing over an
        # empty slot it is a stray tick in the corner.
        self._update_separator = update_separator
        self._support_btn = support_btn
        self._popup: SupportPopup | None = None
        self._supporters: tuple = ()

    def set_update_status(self, state: str, version: str = "") -> None:
        """Say what the update check found, and stay pressable.

        A control rather than a caption, because "Up to date" as dead text is
        the least useful thing this slot could hold: it is a fact from whenever
        the app last launched, with no way to ask again. Re-checking lived only
        behind the settings dialog's *Check for Updates* button, which is two
        clicks and a modal away from the line that reports the answer.

        `"unavailable"` hides the slot outright. It is what a source run gets --
        `check_and_update` returns before it reaches the network there -- and a
        button that cannot do anything is worse than no button. `"unknown"`,
        by contrast, is a real invitation: nothing has been checked *yet*.
        """
        captions = {
            "checking": "Checking…",
            "current": "Up to date",
            "available": f"v{version} available  →",
            "unknown": "Check for updates",
        }
        visible = state != "unavailable"
        self._update_btn.setVisible(visible)
        self._update_separator.setVisible(visible)
        if not visible:
            return
        self._update_btn.setText(captions.get(state, captions["unknown"]))
        # Only while a request is in flight. Every other state is pressable --
        # including "Up to date", which is the whole point of it being a button.
        self._update_btn.setEnabled(state != "checking")
        self._update_btn.setProperty("state", state)
        # A property a stylesheet selects on does not repaint on its own.
        self._update_btn.style().unpolish(self._update_btn)
        self._update_btn.style().polish(self._update_btn)

    def check_for_updates(self) -> None:
        self.set_update_status("checking")
        # `force_check=True`, unlike the launch check: this one was asked for,
        # so a version the user once skipped should still be reported back.
        start_update_check(self._app, force_check=True)

    def set_supporters(self, supporters=()) -> None:
        """Hand the strip a list of supporters, or take it away again.

        **This is the seam, and nothing calls it yet.** The popup and the
        caption are built and styled; what is missing is where the names come
        from, which is a product decision rather than a UI one -- bundled in
        the build, fetched beside the update check, or both. The options and
        their costs are written up in `docs/updates/functional_updates.md`.

        Deliberately the whole surface: one call sets the caption and the card
        together, so the two cannot disagree, and passing nothing puts the strip
        back exactly as it ships. Whoever wires the data in has to add a reader
        and one call, and nothing else.
        """
        self._supporters = tuple(supporters or ())
        count = len(self._supporters)
        self._support_btn.setText(
            "♥  Support" if not count else f"♥  {count} supporters"
        )
        if self._popup is not None:
            self._popup.set_supporters(self._supporters)

    def open_support_popup(self) -> None:
        # Built on the first click, not at launch: it is a dozen widgets nobody
        # has asked for yet, and the same discipline `LazyPage` applies to the
        # tabs. Kept afterwards, so clicking twice does not leak a second one.
        if self._popup is None:
            self._popup = SupportPopup(self.frame.window())
            # Built late, so it has to be told what the view already knows.
            self._popup.set_supporters(self._supporters)
        self._popup.show_above(self._support_btn)


def build_footer(app) -> QFrame:
    """The strip itself. Returns the frame; the view lands on `app.footer`."""
    frame = QFrame()
    frame.setObjectName("appFooter")
    frame.setFixedHeight(FOOTER_HEIGHT)

    row = QHBoxLayout(frame)
    row.setContentsMargins(15, 0, 15, 0)
    row.setSpacing(10)

    # The version, and not the name beside it. "BonkScanner" is already on the
    # title bar and again in the header two lines up; a third copy down here
    # said nothing the other two had not, and pushed the one new fact -- which
    # build this is -- into second place on its own line.
    number = QLabel(f"v{CURRENT_VERSION}")
    number.setObjectName("footerVersionNumber")
    row.addWidget(number, 0, Qt.AlignVCenter)

    update_separator = _separator()
    row.addWidget(update_separator, 0, Qt.AlignVCenter)

    update_btn = _link("Check for updates", "footerUpdate")
    update_btn.setProperty("state", "unknown")
    row.addWidget(update_btn, 0, Qt.AlignVCenter)

    row.addStretch(1)

    github_btn = _link("GitHub")
    github_btn.clicked.connect(lambda: webbrowser.open(config.GITHUB_REPOSITORY_URL))
    row.addWidget(github_btn, 0, Qt.AlignVCenter)
    row.addWidget(_separator(), 0, Qt.AlignVCenter)

    discord_btn = _link("Discord")
    discord_btn.clicked.connect(lambda: webbrowser.open(config.DISCORD_SUPPORT_URL))
    row.addWidget(discord_btn, 0, Qt.AlignVCenter)
    row.addWidget(_separator(), 0, Qt.AlignVCenter)

    # GitHub and Discord open the browser on the click; only Support opens the
    # chooser. Two destinations behind one word is the whole reason it differs.
    support_btn = _link("♥  Support", "footerSupportLink")
    row.addWidget(support_btn, 0, Qt.AlignVCenter)

    app.footer = FooterView(
        app=app,
        frame=frame,
        update_btn=update_btn,
        update_separator=update_separator,
        support_btn=support_btn,
    )
    support_btn.clicked.connect(app.footer.open_support_popup)
    update_btn.clicked.connect(app.footer.check_for_updates)
    return frame
