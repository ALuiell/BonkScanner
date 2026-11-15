"""Native Quick Guides for the BonkScanner desktop UI."""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QStyle,
    QStyleOptionButton,
    QVBoxLayout,
    QWidget,
)

from ui import i18n as l10n
from ui.dialogs.shell import DIALOG_REGULAR, dialog_body
from ui.shared import resource_path
from .guide_locale import bind, message, ui
from .live_preview import LiveStatsGuidePreview
from .merchant_previews import build_merchant_preview
from .overlay_previews import build_overlay_previews
from .recording_preview import RecordingsGuidePreview
from .roll_analytics_preview import build_roll_analytics_preview
from .widget_previews import build_preview


@dataclass(frozen=True)
class Topic:
    key: str
    path: tuple[str, ...]
    action: str
    secondary: str | None = None

    def text(self, field: str, **values) -> str:
        return message(f"topic.{self.key}.{field}", **values)

    def breadcrumb(self) -> str:
        return " → ".join(ui(part) for part in self.path)

    def summary(self) -> str:
        labels = {
            "restart": {"templates": "Templates", "scores": "Scores", "start": "Start"},
            "obs": {"editor": "Open layout editor"},
            "game_overlay": {"luck": "Luck"},
        }
        return self.text("summary", **{key: ui(label) for key, label in labels.get(self.key, {}).items()})

    def menu(self) -> str:
        return ui(self.path[0]) if self.key in ("live", "recordings", "game_overlay") else self.text("menu")

    def action_caption(self, *, secondary: bool = False) -> str:
        route = self.secondary if secondary else self.action
        if route == "obs:editor":
            return ui("Open layout editor")
        if route and route.startswith(("tab:", "settings:")):
            category, destination = route.split(":", 1)
            caption = destination.title() if category == "settings" else destination
            return message("guide.open_target", target=ui(caption))
        return self.text("secondary" if secondary else "action")


TOUR = (
    Topic("welcome", ("BonkScanner",), "restart"),
    Topic("restart", ("Settings", "Restart"), "settings:restart"),
    Topic("live", ("Live Stats",), "tab:Live"),
    Topic("recordings", ("Recordings",), "tab:Recordings"),
    Topic("obs", ("OBS",), "obs:editor"),
    Topic("game_overlay", ("Game Overlay",), "tab:Game Overlay"),
)

PREMIUM_FEATURES = (
    Topic("minimap", ("Game Overlay", "Map markers"), "access"),
    Topic("stock", ("Game Overlay", "Map markers"), "access"),
    Topic("shady", ("Session", "Shady Analytics"), "access", "history:shady"),
    Topic("roll", ("Session", "Roll Analytics"), "access", "history:roll"),
)

PREMIUM = (
    Topic("premium", ("Premium",), "access"),
    *PREMIUM_FEATURES,
    Topic("access", ("Settings", "Support"), "settings:support"),
)


_STYLE = """
QDialog#QuickGuidePreview { background: #10151c; }
QFrame#GuideSection { background:#0d131b; border:1px solid #2c4055; border-radius:10px; }
QFrame#GuideSection[section="premium"] { background:#171522; border-color:#3d334f; }
QFrame#GuideCard { background:#141d29; border:1px solid #34445a; border-radius:12px; }
QWidget#GuideChoiceArea { background:#141d29; }
QLabel#GuideChoiceTitle, QLabel#GuideChoiceDetail, QLabel#GuideChoiceArrow, QLabel#GuideChoiceIcon {
    background:transparent; border:0;
}
QLabel#GuideChoiceTitle { color:#eaf4ff; font-size:15px; font-weight:700; }
QLabel#GuideChoiceDetail { color:#a8bed2; font-size:12px; }
QWidget#GuideChoiceArea[context="welcome"] QLabel#GuideChoiceTitle { font-size:17px; }
QWidget#GuideChoiceArea[context="welcome"] QLabel#GuideChoiceDetail { font-size:13px; }
QLabel#GuideChoiceArrow { color:#85b9e5; font-size:21px; }
QPushButton#GuideChoiceButton {
    background:#172638; border:1px solid #304963; border-radius:10px; padding:0;
}
QPushButton#GuideChoiceButton:hover, QPushButton#GuideChoiceButton:focus:!hover {
    background:#213b55; border-color:#5587b3;
}
QPushButton#GuideChoiceButton:pressed { background:#284764; border-color:#78a9d4; }
QScrollArea#GuideScroll, QScrollArea#GuideRail { background:transparent; border:0; }
QWidget#GuideScrollContent { background:transparent; }
QLabel#GuideGroup { background:transparent; color:#9cbfe0; font-size:12px; font-weight:700; }
QFrame#GuideSection[section="premium"] QLabel#GuideGroup { color:#c4aee7; }
QLabel#GuidePath { color:#8ccaff; font-size:12px; font-weight:600; }
QLabel#GuideTitle { color:#f0f5fa; font-size:27px; font-weight:700; }
QLabel#GuideSummary { color:#becbda; font-size:14px; }
QLabel#GuideFootnote { color:#a5b7ca; font-size:12px; }
QLabel#GuideCount { color:#a5b7ca; font-size:12px; }
QPushButton#GuideTopic {
    background:transparent; border:1px solid transparent; border-radius:6px;
    color:#becbd9; font-size:13px; font-weight:600; padding:8px 10px; text-align:left;
}
QPushButton#GuideTopic:hover { background:#192638; color:#f0f5fa; }
QPushButton#GuideTopic:checked {
    background:#1b324a; border-color:#385c7e; color:#e0f1ff;
}
QPushButton#GuideTopic:focus { border-color:#63abeb; }
QFrame#GuideSection[section="premium"] QPushButton#GuideTopic:hover { background:#241d35; }
QFrame#GuideSection[section="premium"] QPushButton#GuideTopic:checked {
    background:#302442; border-color:#624984; color:#f2e9ff;
}
QFrame#GuideSection[section="premium"] QPushButton#GuideTopic:focus { border-color:#a188ce; }
QPushButton#GuidePage {
    background:#172230; border:1px solid #304256; border-radius:6px;
    font-size:15px; color:#d5e7f8; padding:5px 10px;
}
QPushButton#GuidePage:hover { background:#213751; border-color:#598cbb; }
QPushButton#GuidePage:disabled { color:#607284; border-color:#253141; }
"""


def _label(text, role: str) -> QLabel:
    label = QLabel()
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setObjectName(role)
    if callable(text):
        return bind(label, text)
    label.setText(text)
    return label


def _scroll(content: QWidget) -> QScrollArea:
    scroll = QScrollArea()
    scroll.setObjectName("GuideScroll")
    content.setObjectName("GuideScrollContent")
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    scroll.setWidget(content)
    return scroll


class _TopicButton(QPushButton):
    def __init__(self):
        super().__init__()
        self._caption = ""
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)

    def set_caption(self, caption: str) -> None:
        self._caption = caption
        self.setAccessibleName(caption)
        self._fit_caption()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._fit_caption()

    def _fit_caption(self) -> None:
        option = QStyleOptionButton()
        self.initStyleOption(option)
        contents = self.style().subElementRect(QStyle.SE_PushButtonContents, option, self)
        text = self.fontMetrics().elidedText(self._caption, Qt.ElideRight, max(0, contents.width()))
        self.setText(text)
        self.setToolTip(self._caption if text != self._caption else "")


class QuickGuide(QDialog):
    action_requested = Signal(str)

    def __init__(self, parent: QWidget, *, app, overlay_widgets):
        super().__init__(parent)
        self._app = app
        self._overlay_widgets = overlay_widgets
        self.setObjectName("QuickGuidePreview")
        bind(self, lambda: message("guide.window"), method="setWindowTitle")
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint | Qt.WindowCloseButtonHint)
        self.setStyleSheet(_STYLE)
        self._topic = TOUR[0]
        self._buttons = {}
        self._pages = {}
        self._nav = QButtonGroup(self)
        self._slide = None
        self._welcome_grid = None
        self._welcome_tiles = []
        self._welcome_columns = 0
        body = dialog_body(self, title=message("guide.title"), width=DIALOG_REGULAR, height=718)
        bind(self.findChild(QLabel, "dialogTitle"), lambda: message("guide.title"))
        self.setMinimumHeight(460)
        content = QHBoxLayout()
        content.setSpacing(14)
        body.addLayout(content, 1)
        self._rail = self._build_rail()
        content.addWidget(self._rail)
        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        content.addWidget(self._stack, 1)
        self._build_footer()

        for key, offset in (("Alt+Left", -1), ("Alt+Right", 1)):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda step=offset: self._step(step))
        self.select("welcome")
        l10n.RefreshBinding(self, self._update_footer)

    @property
    def topic(self) -> str:
        return self._topic.key

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if hasattr(self, "_rail"):
            self._rail.setFixedWidth(162 if event.size().width() < 820 else 220)
        self._reflow_welcome()

    def _build_rail(self) -> QScrollArea:
        navigation = QWidget()
        items = QVBoxLayout(navigation)
        items.setSpacing(10)
        items.setContentsMargins(0, 0, 0, 0)
        sections = (
            ("tour", lambda: message("guide.tour"), TOUR),
            ("premium", "Premium", PREMIUM),
        )
        for section, heading, topics in sections:
            card = QFrame()
            card.setObjectName("GuideSection")
            card.setProperty("section", section)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(9, 9, 9, 9)
            card_layout.setSpacing(2)
            label = _label(heading, "GuideGroup")
            label.setContentsMargins(10, 2, 0, 5)
            card_layout.addWidget(label)
            for topic in topics:
                button = _TopicButton()
                button.setObjectName("GuideTopic")
                bind(button, topic.menu, method="set_caption")
                button.setProperty("guideTopic", topic.key)
                button.setCheckable(True)
                button.setAutoDefault(False)
                button.setCursor(Qt.PointingHandCursor)
                self._nav.addButton(button)
                self._buttons[topic.key] = button
                button.clicked.connect(lambda _checked=False, key=topic.key: self.select(key, animate=True))
                card_layout.addWidget(button)
            items.addWidget(card)
        items.addStretch(1)
        rail = _scroll(navigation)
        rail.setObjectName("GuideRail")
        rail.viewport().setAutoFillBackground(False)
        rail.setFixedWidth(220)
        return rail

    def _build_footer(self) -> None:
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.previous = self._page_button("‹", "guide.previous", -1)
        self.next = self._page_button("›", "guide.next", 1)
        self.counter = _label("", "GuideCount")
        self.counter.setAlignment(Qt.AlignCenter)
        footer.addWidget(self.previous)
        footer.addWidget(self.counter)
        footer.addWidget(self.next)
        footer.addStretch(1)
        self.close_button = bind(QPushButton(), lambda: message("guide.close"))
        self.close_button.setAutoDefault(False)
        self.close_button.clicked.connect(self.accept)
        footer.addWidget(self.close_button)
        self.secondary = QPushButton()
        self.secondary.setAutoDefault(False)
        self.secondary.clicked.connect(self._activate_secondary)
        footer.addWidget(self.secondary)
        self.primary = QPushButton()
        self.primary.setObjectName("primary")
        self.primary.setAutoDefault(False)
        self.primary.clicked.connect(lambda: self._activate(self._topic.action))
        footer.addWidget(self.primary)
        self._shell_outer.addLayout(footer)

    def _page_button(self, text: str, key: str, step: int) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("GuidePage")
        button.setAutoDefault(False)
        bind(button, lambda: message(key), method="setAccessibleName")
        bind(button, lambda: message(key), method="setToolTip")
        button.clicked.connect(lambda: self._step(step))
        return button

    def _make_card(self, topic: Topic) -> QScrollArea:
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("GuideCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 17, 20, 15)
        layout.setSpacing(10)
        layout.addWidget(_label(topic.breadcrumb, "GuidePath"))
        layout.addWidget(_label(lambda: topic.text("title"), "GuideTitle"))
        layout.addWidget(_label(topic.summary, "GuideSummary"))
        layout.addSpacing(4)
        if topic.key == "welcome":
            preview = self._welcome_choices()
        elif topic.key == "premium":
            preview = self._premium_overview()
        elif topic.key == "live":
            preview = LiveStatsGuidePreview()
        elif topic.key == "recordings":
            preview = RecordingsGuidePreview(self._app)
        elif topic.key in ("obs", "game_overlay"):
            preview = build_overlay_previews(topic.key, self._overlay_widgets)
        elif topic.key in ("stock", "shady"):
            preview = build_merchant_preview(topic.key, self._overlay_widgets)
        elif topic.key == "roll":
            preview = build_roll_analytics_preview()
        else:
            preview = build_preview(topic.key)
        preview.setObjectName(preview.objectName() or "GuideExample")
        if topic.key == "welcome":
            preview.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
            layout.addWidget(preview, 1)
        elif topic.key == "premium":
            layout.addWidget(preview)
        else:
            preview.setMinimumHeight(max(214, preview.minimumHeight()))
            preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            layout.addWidget(preview, 1)
        if topic.key not in ("obs", "game_overlay") and topic.text("footnote"):
            layout.addWidget(_label(lambda: topic.text("footnote"), "GuideFootnote"))
        inner_layout.addWidget(card, alignment=Qt.AlignTop if topic.key == "premium" else Qt.Alignment())
        return _scroll(inner)

    def _welcome_choices(self) -> QWidget:
        area = QWidget()
        area.setObjectName("GuideChoiceArea")
        area.setProperty("context", "welcome")
        self._welcome_grid = QGridLayout(area)
        self._welcome_grid.setContentsMargins(0, 0, 0, 4)
        self._welcome_grid.setSpacing(12)
        choices = (
            ("restart", "help_icon.svg"), ("live", "roll_dice.svg"),
            ("game_overlay", "in_game_icon.svg"), ("premium", "premium_access_icon.svg"),
        )
        for destination, icon in choices:
            self._welcome_tiles.append(self._choice_tile(
                destination,
                lambda key=destination: ui("Game Overlay") if key == "game_overlay" else message(f"welcome.{key}.title"),
                lambda key=destination: message(f"welcome.{key}.note"),
                icon=icon,
            ))
        self._reflow_welcome()
        return area

    def _premium_overview(self) -> QWidget:
        area = QWidget()
        area.setObjectName("GuideChoiceArea")
        layout = QVBoxLayout(area)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        for feature in PREMIUM_FEATURES:
            tile = self._choice_tile(
                feature.key,
                feature.menu,
                lambda key=feature.key: message(f"premium.feature.{key}"),
            )
            layout.addWidget(tile, 1)
        return area

    def _choice_tile(self, destination, title, copy, *, icon: str | None = None) -> QPushButton:
        button = QPushButton()
        button.setProperty("guideDestination", destination)
        button.setObjectName("GuideChoiceButton")
        button.setAutoDefault(False)
        button.setCursor(Qt.PointingHandCursor)
        button.setMinimumHeight(100 if icon else 72)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding if icon else QSizePolicy.Preferred)
        bind(button, title, method="setAccessibleName")
        bind(button, copy, method="setAccessibleDescription")
        button.clicked.connect(lambda: self.select(destination, animate=True))
        row = QHBoxLayout(button)
        row.setContentsMargins(14, 11, 14, 11)
        row.setSpacing(11)
        if icon:
            badge = _label("", "GuideChoiceIcon")
            badge.setPixmap(QIcon(resource_path(f"media/{icon}")).pixmap(30, 30))
            row.addWidget(badge, alignment=Qt.AlignVCenter)
        text = QVBoxLayout()
        text.setSpacing(4)
        text.addStretch(1)
        text.addWidget(_label(title, "GuideChoiceTitle"))
        text.addWidget(_label(copy, "GuideChoiceDetail"))
        text.addStretch(1)
        row.addLayout(text, 1)
        row.addWidget(_label("›", "GuideChoiceArrow"), alignment=Qt.AlignVCenter)
        for label in button.findChildren(QLabel):
            label.setAttribute(Qt.WA_TransparentForMouseEvents)
        return button

    def _reflow_welcome(self) -> None:
        if not self._welcome_grid:
            return
        columns = 1 if self.width() < 740 else 2
        if columns == self._welcome_columns:
            return
        self._welcome_grid.setColumnStretch(0, 1)
        self._welcome_grid.setColumnStretch(1, int(columns == 2))
        for index, tile in enumerate(self._welcome_tiles):
            self._welcome_grid.removeWidget(tile)
            tile.setMinimumHeight(94 if columns == 1 else 136)
            self._welcome_grid.addWidget(tile, index // columns, index % columns)
        self._welcome_columns = columns

    def select(self, key: str, *, animate: bool = False) -> None:
        topics = TOUR + PREMIUM
        index = next(i for i, topic in enumerate(topics) if topic.key == key)
        old_index = topics.index(self._topic)
        self._topic = topic = topics[index]
        self._buttons[key].setChecked(True)
        page = self._pages.get(key)
        if page is None:
            self._pages[key] = page = self._make_card(topic)
            self._stack.addWidget(page)
        if self._slide is not None:
            self._slide.stop()
            self._slide.targetObject().move(0, 0)
            self._slide.deleteLater()
            self._slide = None
        self._stack.setCurrentWidget(page)
        self.previous.setEnabled(index > 0)
        self.next.setEnabled(index < len(topics) - 1)
        group = TOUR if topic in TOUR else PREMIUM
        self.counter.setText(f"{group.index(topic) + 1} / {len(group)}")
        self._update_footer()
        if animate and self.isVisible() and old_index != index:
            self._animate(page, 1 if index > old_index else -1)

    def _animate(self, page: QWidget, direction: int) -> None:
        position = page.pos()
        animation = QPropertyAnimation(page, b"pos", self)
        animation.setDuration(170)
        animation.setStartValue(position + QPoint(21 * direction, 0))
        animation.setEndValue(position)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._slide = animation
        animation.start()

    def _step(self, delta: int) -> None:
        topics = TOUR + PREMIUM
        next_index = topics.index(self._topic) + delta
        if 0 <= next_index < len(topics):
            self.select(topics[next_index].key, animate=True)

    def _activate_secondary(self) -> None:
        if self._topic.secondary:
            self._activate(self._topic.secondary)

    def _update_footer(self) -> None:
        topic = self._topic
        self.primary.setText(topic.action_caption())
        self.secondary.setVisible(topic.secondary is not None)
        if topic.secondary is not None:
            self.secondary.setText(topic.action_caption(secondary=True))

    def _activate(self, action: str) -> None:
        if any(topic.key == action for topic in TOUR + PREMIUM):
            self.select(action, animate=True)
        else:
            self.action_requested.emit(action)
