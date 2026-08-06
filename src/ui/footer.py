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

from PySide6.QtCore import QPoint, Qt, QTimer
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

        #: The widget this was last opened against, so the card can re-anchor
        #: itself if its contents change while it is on screen.
        self._anchor: QWidget | None = None

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

    #: How a `tier` value is drawn: `(object name, prefix, sort rank)`.
    #:
    #: Three states and no more, each earning its distinction. A diamond and the
    #: Patreon red for a subscription, which is the only one that is *ongoing*;
    #: the same red without the diamond for someone who bought a pack, since the
    #: money is the same and the recurrence is not; the Ko-fi blue for a Ko-fi
    #: tip, which reads as "a different place" rather than "a different amount".
    #: Anything past this is a price list, which is not what a thank-you card is.
    #:
    #: Keys are normalised by `_tier_key`, so `"Ko-Fi"` and `"ko_fi"` both land.
    TIER_STYLES = {
        "patreon": ("supporterNamePatreon", "♦  ", 0),
        "pack": ("supporterNamePack", "", 1),
        "kofi": ("supporterNameKofi", "", 2),
    }
    #: An unrecognised but non-empty tier. It is marked rather than dropped to
    #: grey: `supporters.json` is edited by hand in a browser, and a typo in the
    #: tier of someone who is *known to have paid* should cost them a diamond,
    #: not their place among the people being thanked.
    UNKNOWN_TIER_STYLE = ("supporterNamePack", "", 1)
    #: No tier at all -- a bare `"Name"` string. Deliberately unmarked.
    PLAIN_STYLE = ("supporterName", "", 3)

    @staticmethod
    def _tier_key(tier) -> str:
        """`"Ko-fi"`, `"ko_fi"` and `" KOFI "` are all `kofi`."""
        return "".join(
            character
            for character in str(tier or "").lower()
            if character.isalnum()
        )

    def set_supporters(self, supporters=()) -> None:
        """Show these people, or go back to being the plain two-button card.

        **The empty case is the shipping case and must stay unremarkable.**
        The list is fetched, so every copy of the application starts here and a
        good number of them stay: no network, no names published yet, an older
        build. What the card looks like with no list is what those people see --
        a title, one line, two buttons. No heading over a blank space, no
        "0 supporters", no rule with nothing above it. An empty card reads as a
        broken feature; a card that never mentions the list reads as nothing at
        all, which is correct.

        Accepts plain names or mappings, so `supporters.json` needs no shape
        negotiation: `"Nyxaria"` and `{"name": "Nyxaria", "tier": "patreon"}`
        both work. See `TIER_STYLES` for what each tier looks like.
        """
        people = []
        for entry in supporters or ():
            if isinstance(entry, dict):
                name = str(entry.get("name") or "").strip()
                key = self._tier_key(entry.get("tier"))
                style = (
                    self.PLAIN_STYLE
                    if not key
                    else self.TIER_STYLES.get(key, self.UNKNOWN_TIER_STYLE)
                )
            else:
                name = str(entry or "").strip()
                style = self.PLAIN_STYLE
            if name:
                people.append((name, style))

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
            self._reanchor()
            return

        self._title.setText(f"{len(people)} people support BonkScanner")
        # Grouped by tier, and inside a group the order they arrived in. Not
        # alphabetical: a list someone maintains by hand has an order, and
        # re-sorting it throws away whatever they meant by it. `sort` is stable,
        # so the file's order survives within each group.
        people.sort(key=lambda person: person[1][2])
        listed = people[: self.MAX_LISTED]
        hidden = len(people) - len(listed)
        self._note.setText(
            "Thank you." if not hidden else f"Thank you, and {hidden} more."
        )

        rows = (len(listed) + 1) // 2
        for index, (name, (object_name, prefix, _rank)) in enumerate(listed):
            label = QLabel(prefix + name, self._names_host)
            label.setObjectName(object_name)
            # Elided rather than wrapped, and the grid column carries the width:
            # a display name is whatever its owner typed, and one long one must
            # not be allowed to widen the popup or reflow the column beside it.
            label.setTextFormat(Qt.PlainText)
            label.setToolTip(name)
            self._names_grid.addWidget(label, index % rows, index // rows)
        self._names_grid.setColumnStretch(0, 1)
        self._names_grid.setColumnStretch(1, 1)
        self._reanchor()

    def _reanchor(self) -> None:
        """Re-place the card if it is on screen and just changed size.

        The list arrives about a second after launch, so a click in that window
        lands on the narrow card and widens it while it is open. Every early
        return here is a case where there is nothing to correct: not visible, or
        never opened against anything.

        **Placed twice, and the second time is the one that gets the height
        right.** Rows added to the grid are not measurable yet at this point:
        the labels they replaced are only unparented on the next pass through
        the event loop, and the new ones have not been polished, so `sizeHint`
        still answers for the previous contents -- measured, 8 names reported
        the height of 2. Placing from that puts the bottom edge of the card
        below the button it is supposed to sit above. The immediate placement
        keeps the width honest without waiting a frame; `_settle` fixes the
        height once there is something true to measure.
        """
        if self.isVisible() and self._anchor is not None:
            self._place_above(self._anchor)
            QTimer.singleShot(0, self._settle)

    def _settle(self) -> None:
        """Second half of `_reanchor`, once the layout has caught up."""
        if self.isVisible() and self._anchor is not None:
            self._place_above(self._anchor)

    def _open_patreon(self) -> None:
        webbrowser.open(config.PATREON_SUPPORT_URL)
        self.close()

    def _open_kofi(self) -> None:
        webbrowser.open(config.KOFI_SUPPORT_URL)
        self.close()

    def show_above(self, anchor: QWidget) -> None:
        """Open with the popup's bottom-right corner over `anchor`'s top-right."""
        self._anchor = anchor
        self._place_above(anchor)
        self.show()
        # The same one-pass lag applies to a popup built and filled in the click
        # that opens it: nothing has been polished yet. Idempotent when the
        # first placement was already right.
        QTimer.singleShot(0, self._settle)

    def _place_above(self, anchor: QWidget) -> None:
        """Put the bottom-right corner of the card over `anchor`'s top-right.

        **Re-run whenever the card changes size, not only when it opens.** The
        popup is anchored by a corner that moves when it grows: `move` fixes the
        top-left, so a card that goes from 268 to 400 wide grows *rightwards*,
        straight off the display. That is what the first open looked like -- not
        a mis-measurement, but a click that landed in the second or so between
        the window appearing and the supporters arriving. The card opened narrow
        and was widened underneath itself while it sat there.

        The clamp is the backstop for everything this arithmetic cannot know:
        the anchor lives at the right edge of the window and the window is
        usually at the right edge of the screen, so there is nothing to spare. A
        card nudged a few pixels out of line with its button is much better than
        one rendered half off the edge.
        """
        self.ensurePolished()
        # Invalidated innermost first, and this is not belt-and-braces. A layout
        # caches the size hint it computed for its parent, so activating only
        # the outer one answers from the *previous* contents: adding rows to the
        # grid re-placed the card at its height from one call ago, which put its
        # bottom edge below the button it is supposed to sit above. The width
        # never showed it -- the card's width is set outright.
        self._names_grid.invalidate()
        self._card.layout().invalidate()
        self.layout().invalidate()
        self.layout().activate()
        self.adjustSize()
        size = self.sizeHint()

        top_right = anchor.mapToGlobal(QPoint(anchor.width(), 0))
        x = top_right.x() - size.width()
        y = top_right.y() - size.height() - 8

        screen = self.screen() or anchor.screen()
        if screen is not None:
            available = screen.availableGeometry()
            x = min(max(x, available.left()), available.right() - size.width() + 1)
            y = min(max(y, available.top()), available.bottom() - size.height() + 1)

        self.setGeometry(x, y, size.width(), size.height())


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

        Called from `ui.dialogs.update_prompt.start_supporters_load`, on the GUI
        thread, once a launch, and only when there is something to show --
        `app.supporters.load_supporters` stays silent on every failure and on
        the empty list, so this is not the path that decides what an absent list
        looks like. `SupportPopup.set_supporters` is.

        Deliberately the whole surface: one call sets the caption and the card
        together, so the two cannot disagree, and passing nothing puts the strip
        back exactly as it ships.
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
