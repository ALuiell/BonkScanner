"""The window's bottom strip: version, update status, and the links.

The main window had no footer at all -- ``build_layout`` put a header and a
splitter into the root layout and stopped -- so two things had nowhere to live.
The version was readable only in the title bar and in the log's welcome line,
which scrolls away; and the four support links existed only inside the settings
dialog, which nobody reopens after setting their hotkeys once.

Both go here, on one 28px line. The three links stay compact and backgroundless,
but no longer read like disabled metadata: GitHub and Discord carry quiet cool
colours, while Support carries the Patreon red. Hover draws one short line out
from the caption's centre. Support also owns the only ambient motion in the
strip -- a small double heartbeat after a long pause -- and replaces it with one
clear beat while the pointer is over the button.

The strip spans the whole window rather than sitting inside the 16px content
margins, which is why ``build_layout`` now nests its content in an inner widget:
a footer inset from the edges reads as a floating bar, not as the window's base.
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QLineF,
    QPoint,
    QRectF,
    QPropertyAnimation,
    QSequentialAnimationGroup,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QIcon, QPainter, QPen
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

FOOTER_HOVER_IN_MS = 180
FOOTER_HOVER_OUT_MS = 140
HEART_FONT_SCALE = 13.5 / 11.5
HEART_PASSIVE_PAUSE_MS = 3000
HEART_PASSIVE_FIRST_SCALE = 1.08
HEART_PASSIVE_SECOND_SCALE = 1.04
HEART_HOVER_SCALE = 1.09


def _mix_color(start: QColor, end: QColor, progress: float) -> QColor:
    """Interpolate two stylesheet-provided colours without changing geometry."""
    progress = max(0.0, min(1.0, float(progress)))
    return QColor.fromRgbF(
        start.redF() + (end.redF() - start.redF()) * progress,
        start.greenF() + (end.greenF() - start.greenF()) * progress,
        start.blueF() + (end.blueF() - start.blueF()) * progress,
        start.alphaF() + (end.alphaF() - start.alphaF()) * progress,
    )


class _AnimatedFooterLink(QPushButton):
    """A backgroundless footer link with a centre-out light trace on hover.

    QSS pseudo-states can switch colour and add a border, but they cannot
    interpolate either. Painting the two small pieces here keeps the visible
    contract in the stylesheet -- the three colours are qproperties -- while a
    single 0..1 property drives the colour lift, glow and underline together.
    """

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._rest_color = QColor("#B9C2CE")
        self._hover_color = QColor("#EDF1F5")
        self._line_color = QColor("#EDF1F5")
        self._hover_progress = 0.0

        self._hover_animation = QPropertyAnimation(self, b"hoverProgress", self)
        self._hover_animation.setEasingCurve(QEasingCurve.OutCubic)

    # -- stylesheet colours -------------------------------------------------

    def _get_rest_color(self) -> QColor:
        return QColor(self._rest_color)

    def _set_rest_color(self, color: QColor) -> None:
        self._rest_color = QColor(color)
        self.update()

    restColor = Property(QColor, _get_rest_color, _set_rest_color)

    def _get_hover_color(self) -> QColor:
        return QColor(self._hover_color)

    def _set_hover_color(self, color: QColor) -> None:
        self._hover_color = QColor(color)
        self.update()

    hoverColor = Property(QColor, _get_hover_color, _set_hover_color)

    def _get_line_color(self) -> QColor:
        return QColor(self._line_color)

    def _set_line_color(self, color: QColor) -> None:
        self._line_color = QColor(color)
        self.update()

    lineColor = Property(QColor, _get_line_color, _set_line_color)

    # -- hover progress ------------------------------------------------------

    def _get_hover_progress(self) -> float:
        return self._hover_progress

    def _set_hover_progress(self, value: float) -> None:
        self._hover_progress = max(0.0, min(1.0, float(value)))
        self.update()

    hoverProgress = Property(float, _get_hover_progress, _set_hover_progress)

    def _animate_hover(self, target: float) -> None:
        start = self._hover_progress
        target = max(0.0, min(1.0, float(target)))
        self._hover_animation.stop()
        if abs(target - start) < 0.001:
            self._hover_animation.setStartValue(start)
            self._hover_animation.setEndValue(target)
            self._set_hover_progress(target)
            return
        full_duration = FOOTER_HOVER_IN_MS if target > start else FOOTER_HOVER_OUT_MS
        self._hover_animation.setDuration(max(1, round(full_duration * abs(target - start))))
        self._hover_animation.setStartValue(start)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def enterEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._animate_hover(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._animate_hover(0.0)
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._hover_animation.stop()
        self._set_hover_progress(0.0)
        super().hideEvent(event)

    # -- painting ------------------------------------------------------------

    @staticmethod
    def _draw_text(
        painter: QPainter,
        rect: QRectF,
        font: QFont,
        text: str,
        color: QColor,
        *,
        glow_alpha: int = 0,
    ) -> None:
        painter.setFont(font)
        flags = Qt.AlignCenter | Qt.TextSingleLine
        if glow_alpha > 0:
            glow = QColor(color)
            glow.setAlpha(max(0, min(255, glow_alpha)))
            painter.setPen(glow)
            for dx, dy in ((-1.0, 0.0), (1.0, 0.0), (0.0, -1.0), (0.0, 1.0)):
                painter.drawText(rect.translated(dx, dy), flags, text)
        painter.setPen(color)
        painter.drawText(rect, flags, text)

    def _content_width(self) -> float:
        return QFontMetricsF(self.font()).horizontalAdvance(self.text())

    def _paint_content(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        self._draw_text(
            painter,
            rect,
            self.font(),
            self.text(),
            color,
            glow_alpha=round(36 * self._hover_progress),
        )

    def paintEvent(self, _event) -> None:  # noqa: N802 -- Qt's name
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)

        color = _mix_color(
            self._rest_color, self._hover_color, self._hover_progress
        )
        if self.isDown():
            color = color.darker(118)

        content = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -2.0)
        self._paint_content(painter, content, color)

        if self._hover_progress <= 0.001:
            return
        half_width = self._content_width() * self._hover_progress / 2.0
        centre_x = content.center().x()
        y = content.bottom() + 1.0
        line = QColor(self._line_color)

        halo = QColor(line)
        halo.setAlpha(round(42 * self._hover_progress))
        painter.setPen(QPen(halo, 3.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QLineF(centre_x - half_width, y, centre_x + half_width, y))

        line.setAlpha(round(220 * self._hover_progress))
        painter.setPen(QPen(line, 1.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QLineF(centre_x - half_width, y, centre_x + half_width, y))


class _SupportFooterLink(_AnimatedFooterLink):
    """The support link, with a separately painted and animated heart."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        self._caption = ""
        self._heart_scale = 1.0
        self._hovered = False
        super().__init__("", parent)
        self.setText(text)

        self._ambient_heartbeat = QSequentialAnimationGroup(self)
        self._ambient_heartbeat.addPause(HEART_PASSIVE_PAUSE_MS)
        self._ambient_heartbeat.addAnimation(
            self._heart_step(1.0, HEART_PASSIVE_FIRST_SCALE, 80, QEasingCurve.OutCubic)
        )
        self._ambient_heartbeat.addAnimation(
            self._heart_step(HEART_PASSIVE_FIRST_SCALE, 1.0, 100, QEasingCurve.InCubic)
        )
        self._ambient_heartbeat.addPause(40)
        self._ambient_heartbeat.addAnimation(
            self._heart_step(1.0, HEART_PASSIVE_SECOND_SCALE, 70, QEasingCurve.OutCubic)
        )
        self._ambient_heartbeat.addAnimation(
            self._heart_step(HEART_PASSIVE_SECOND_SCALE, 1.0, 90, QEasingCurve.InCubic)
        )
        self._ambient_heartbeat.setLoopCount(-1)

        self._hover_heartbeat = QSequentialAnimationGroup(self)
        self._hover_heartbeat.addAnimation(
            self._heart_step(1.0, HEART_HOVER_SCALE, 90, QEasingCurve.OutCubic)
        )
        self._hover_heartbeat.addAnimation(
            self._heart_step(HEART_HOVER_SCALE, 1.0, 170, QEasingCurve.InCubic)
        )

    def _heart_step(
        self,
        start: float,
        end: float,
        duration: int,
        easing: QEasingCurve.Type,
    ) -> QPropertyAnimation:
        animation = QPropertyAnimation(self, b"heartScale")
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.setDuration(duration)
        animation.setEasingCurve(easing)
        return animation

    def _get_heart_scale(self) -> float:
        return self._heart_scale

    def _set_heart_scale(self, value: float) -> None:
        self._heart_scale = max(1.0, float(value))
        self.update()

    heartScale = Property(float, _get_heart_scale, _set_heart_scale)

    def setText(self, text: str) -> None:  # noqa: N802 -- Qt's name
        visible_text = str(text)
        self._caption = visible_text.replace("♥", "", 1).strip()
        super().setText(visible_text)
        self.updateGeometry()

    def caption(self) -> str:
        return self._caption

    def _heart_font(self) -> QFont:
        font = QFont(self.font())
        if font.pointSizeF() > 0:
            font.setPointSizeF(font.pointSizeF() * HEART_FONT_SCALE)
        elif font.pixelSize() > 0:
            font.setPixelSize(max(1, round(font.pixelSize() * HEART_FONT_SCALE)))
        return font

    def _content_metrics(self) -> tuple[QFont, float, float, float]:
        heart_font = self._heart_font()
        heart_width = QFontMetricsF(heart_font).horizontalAdvance("♥")
        caption_width = QFontMetricsF(self.font()).horizontalAdvance(self._caption)
        gap = 4.0
        return heart_font, heart_width, caption_width, gap

    def _content_width(self) -> float:
        _heart_font, heart_width, caption_width, gap = self._content_metrics()
        return heart_width + gap + caption_width

    def _paint_content(self, painter: QPainter, rect: QRectF, color: QColor) -> None:
        heart_font, heart_width, caption_width, gap = self._content_metrics()
        total_width = heart_width + gap + caption_width
        start_x = rect.center().x() - total_width / 2.0
        heart_rect = QRectF(start_x, rect.top(), heart_width, rect.height())
        caption_rect = QRectF(
            start_x + heart_width + gap,
            rect.top(),
            caption_width,
            rect.height(),
        )

        self._draw_text(
            painter,
            caption_rect,
            self.font(),
            self._caption,
            color,
            glow_alpha=round(36 * self._hover_progress),
        )

        pulse = max(
            0.0,
            min(1.0, (self._heart_scale - 1.0) / (HEART_HOVER_SCALE - 1.0)),
        )
        painter.save()
        centre = heart_rect.center()
        painter.translate(centre)
        painter.scale(self._heart_scale, self._heart_scale)
        painter.translate(-centre)
        self._draw_text(
            painter,
            heart_rect,
            heart_font,
            "♥",
            color,
            glow_alpha=round(max(48 * self._hover_progress, 86 * pulse)),
        )
        painter.restore()

    def sizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        hint = super().sizeHint()
        return QSize(hint.width() + 3, max(24, hint.height()))

    def minimumSizeHint(self) -> QSize:  # noqa: N802 -- Qt's name
        return self.sizeHint()

    def _restart_ambient_heartbeat(self) -> None:
        self._ambient_heartbeat.stop()
        self._set_heart_scale(1.0)
        if self.isVisible() and not self._hovered:
            # The pause is the first animation, so every restart waits before
            # drawing the next passive beat instead of answering a hover twice.
            self._ambient_heartbeat.start()

    def enterEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._hovered = True
        self._ambient_heartbeat.stop()
        self._hover_heartbeat.stop()
        self._set_heart_scale(1.0)
        self._hover_heartbeat.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._hovered = False
        self._hover_heartbeat.stop()
        self._set_heart_scale(1.0)
        super().leaveEvent(event)
        self._restart_ambient_heartbeat()

    def showEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        super().showEvent(event)
        self._restart_ambient_heartbeat()

    def hideEvent(self, event) -> None:  # noqa: N802 -- Qt's name
        self._hovered = False
        self._ambient_heartbeat.stop()
        self._hover_heartbeat.stop()
        self._set_heart_scale(1.0)
        super().hideEvent(event)


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


def _link(
    text: str,
    object_name: str = "footerLink",
    *,
    link_role: str = "",
) -> QPushButton:
    if object_name == "footerSupportLink":
        button = _SupportFooterLink(text)
    elif object_name == "footerLink":
        button = _AnimatedFooterLink(text)
    else:
        button = QPushButton(text)
    button.setObjectName(object_name)
    if link_role:
        button.setProperty("linkRole", link_role)
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
    make. It provides the brief context a bare link lacks, and the same shape
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
        # The wider card gives the support message room to breathe instead of
        # leaving it as a dense caption above the two platform buttons.
        card.setFixedWidth(self.NARROW_WIDTH)
        outer.addWidget(card)

        body = QVBoxLayout(card)
        body.setContentsMargins(12, 11, 12, 12)
        body.setSpacing(3)

        title = QLabel("Support BonkScanner", card)
        title.setObjectName("supportPopupTitle")
        body.addWidget(title)

        note = QLabel(self.DEFAULT_NOTE, card)
        note.setObjectName("supportPopupNote")
        note.setWordWrap(True)
        body.addWidget(note)
        self._title = title
        self._note = note

        # A compact legend for the two independent signals used by the list:
        # colour says where someone supported, while the symbols say what they
        # have done. Kept on one quiet line so the popup remains a thank-you
        # card, not a second settings panel.
        self._legend = QWidget(card)
        self._legend.setObjectName("supporterLegend")
        legend_row = QHBoxLayout(self._legend)
        legend_row.setContentsMargins(0, 2, 0, 2)
        legend_row.setSpacing(7)
        for object_name, caption in (
            ("supporterLegendPatreon", "●  Patreon"),
            ("supporterLegendKofi", "●  Ko-fi"),
        ):
            label = QLabel(caption, self._legend)
            label.setObjectName(object_name)
            label.setTextFormat(Qt.PlainText)
            legend_row.addWidget(label, 0, Qt.AlignVCenter)

        legend_separator = QFrame(self._legend)
        legend_separator.setObjectName("supporterLegendSeparator")
        legend_separator.setFixedSize(1, 15)
        legend_row.addWidget(legend_separator, 0, Qt.AlignVCenter)

        for object_name, caption in (
            ("supporterLegendFounder", "★  Founder"),
            ("supporterLegendPack", "■  Supporter Pack"),
            ("supporterLegendSub", "♦  Active sub"),
        ):
            label = QLabel(caption, self._legend)
            label.setObjectName(object_name)
            label.setTextFormat(Qt.PlainText)
            legend_row.addWidget(label, 0, Qt.AlignVCenter)
        legend_row.addStretch(1)
        self._legend.setVisible(False)
        body.addWidget(self._legend)

        # The names, when there are any. Built empty and hidden, so the popup
        # is exactly what it was until something calls `set_supporters` -- see
        # that method for why the empty case must look like this and not like a
        # heading over a blank space.
        self._names_host = QWidget(card)
        self._names_host.setObjectName("supporterList")
        self._names_grid = QGridLayout(self._names_host)
        # `body` already contributes 3px between its children. These small
        # internal margins make the changing names section read as a group:
        # 6px after the thank-you line and 7px before the divider, while the
        # empty card remains exactly as compact as before because the host is
        # hidden with the list.
        self._names_grid.setContentsMargins(0, 3, 0, 4)
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

    #: Card widths. The narrow one gives the support message a relaxed wrap; the
    #: wide one by two columns of display name, which are user-supplied text and
    #: can be any length -- they ellipsise rather than widen the card further.
    NARROW_WIDTH = 320
    WIDE_WIDTH = 440
    DEFAULT_NOTE = "If it helps your runs, you can throw a little fuel its way."
    #: Names past this are not listed; the count in the caption still includes
    #: them. A popup is not a page, and a scroll bar inside one is a worse
    #: answer than "and 40 others".
    MAX_LISTED = 24

    #: How a `tier` value is drawn: `(object name, marker, sort rank)`.
    #:
    #: A diamond and Patreon red identify the only ongoing state; a square and
    #: the same red identify a one-time pack; Ko-fi blue reads as "a different
    #: place" rather than "a different amount". Permanent badges are composed
    #: separately, so a founder who owns a pack and has an active subscription
    #: can carry all three markers without becoming three people in the count.
    #:
    #: Keys are normalised by `_tier_key`, so `"Ko-Fi"` and `"ko_fi"` both land.
    TIER_STYLES = {
        "patreon": ("supporterNamePatreon", "♦  ", 0),
        "pack": ("supporterNamePack", "■  ", 1),
        "kofi": ("supporterNameKofi", "", 2),
    }
    #: Permanent, stackable acknowledgements. Tuple order is display order;
    #: input order in a hand-edited JSON file cannot make the markers jump.
    BADGE_MARKERS = (
        ("founder", "★"),
        ("pack", "■"),
    )
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

    @classmethod
    def _supporter_prefix(cls, badges, tier_marker: str) -> str:
        """Compose known permanent badges and the current tier marker once."""
        badge_keys = (
            {cls._tier_key(badge) for badge in badges}
            if isinstance(badges, (list, tuple))
            else set()
        )
        markers = [
            marker for key, marker in cls.BADGE_MARKERS if key in badge_keys
        ]
        current_marker = tier_marker.strip()
        if current_marker and current_marker not in markers:
            markers.append(current_marker)
        return "".join(f"{marker}  " for marker in markers)

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
                badges = entry.get("badges")
            else:
                name = str(entry or "").strip()
                style = self.PLAIN_STYLE
                badges = ()
            if name:
                people.append((name, style, self._supporter_prefix(badges, style[1])))

        _clear_layout(self._names_grid)
        self._legend.setVisible(bool(people))
        self._names_host.setVisible(bool(people))
        self._rule.setVisible(bool(people))
        self._card.setFixedWidth(self.WIDE_WIDTH if people else self.NARROW_WIDTH)

        if not people:
            self._title.setText("Support BonkScanner")
            self._note.setText(self.DEFAULT_NOTE)
            self._reanchor()
            return

        count = len(people)
        self._title.setText(
            "1 person supports BonkScanner"
            if count == 1
            else f"{count} people support BonkScanner"
        )
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
        for index, (name, (object_name, _tier_marker, _rank), prefix) in enumerate(
            listed
        ):
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

    github_btn = _link("GitHub", link_role="github")
    github_btn.clicked.connect(lambda: webbrowser.open(config.GITHUB_REPOSITORY_URL))
    row.addWidget(github_btn, 0, Qt.AlignVCenter)
    row.addWidget(_separator(), 0, Qt.AlignVCenter)

    discord_btn = _link("Discord", link_role="discord")
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
