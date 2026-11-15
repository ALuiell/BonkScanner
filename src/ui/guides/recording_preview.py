"""Native UI excerpts for the Recordings guide page."""
from PySide6.QtCore import QLocale, QRectF, QSize, QTimer, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel, QSizePolicy, QTabBar, QVBoxLayout, QWidget

from ui import i18n as l10n
from ui.timeline_controls import TIMELINE_CAP_LABELS

from .guide_locale import localization, message, ui
from .native_recording_screens import capture_recording_screens
from .run_sample import load_run_example


_STYLE = """
QWidget#GuideRunPreview { background:#141d29; }
QTabBar#GuideRunExamples { background:transparent; border:0; }
QTabBar#GuideRunExamples::tab {
    background:#172333; border:1px solid #2d4258; border-radius:6px;
    color:#bed3e6; margin-right:6px; padding:7px 11px;
}
QTabBar#GuideRunExamples::tab:selected {
    background:#214365; color:#edf7ff; border-color:#5b91bc;
}
QTabBar#GuideRunExamples::tab:focus { border-color:#89c8ff; }
QLabel#GuideRunDescription { background:transparent; color:#d7e3f1; font-size:13px; }
QLabel#GuideRunKeys { background:transparent; color:#9fc4ea; font-size:12px; }
QLabel#GuideRunSource { background:transparent; color:#a9bdd0; font-size:12px; }
"""

_RECORDING_EXAMPLES = (
    ("Timeline", "run.screen.timeline", "run.keys.timeline"),
    ("Compare Details", "run.screen.compare", "run.keys.compare"),
    ("Damage Sources", "run.screen.damage", ""),
)


def _label(role):
    label = QLabel()
    label.setTextFormat(Qt.PlainText)
    label.setWordWrap(True)
    label.setObjectName(role)
    return label


def _capture_context(app):
    translator = localization().translator
    return translator.language, translator.game_language, app.window.styleSheet()


class _RunScreen(QWidget):
    """Display a static production UI excerpt."""

    def __init__(self, max_height=380):
        super().__init__()
        self.setObjectName("GuideRunScreen")
        self._shot = QPixmap()
        self._max_height = max_height
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(0)

    def set_screenshot(self, shot):
        self._shot = shot
        self._fit()
        self.update()

    def _fit(self):
        if self._shot.isNull():
            self.setFixedHeight(0)
            return
        size = self._shot.size().scaled(QSize(max(1, self.width()), self._max_height), Qt.KeepAspectRatio)
        self.setFixedHeight(size.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def paintEvent(self, _event):
        if self._shot.isNull():
            return
        size = self._shot.size().scaled(self.size(), Qt.KeepAspectRatio)
        target = QRectF((self.width() - size.width()) / 2, 0, size.width(), size.height())
        clip = QPainterPath()
        clip.addRoundedRect(target, 6, 6)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setClipPath(clip)
        painter.drawPixmap(target, self._shot, QRectF(self._shot.rect()))
        painter.end()


class RecordingsGuidePreview(QWidget):
    def __init__(self, app):
        super().__init__()
        self._app = app
        self._context = None
        self._screens = ()
        self._capture = QTimer(self)
        self._capture.setSingleShot(True)
        self._capture.timeout.connect(self._show_screen)

        self.setObjectName("GuideRunPreview")
        self.setAttribute(Qt.WA_StyledBackground)
        self.setStyleSheet(_STYLE)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        self._tabs = QTabBar()
        self._tabs.setObjectName("GuideRunExamples")
        self._tabs.setDocumentMode(True)
        self._tabs.setDrawBase(False)
        self._tabs.setExpanding(False)
        self._tabs.setElideMode(Qt.ElideRight)
        self._tabs.setUsesScrollButtons(False)
        self._tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        for _ in _RECORDING_EXAMPLES:
            self._tabs.addTab("")
        layout.addWidget(self._tabs)
        self._description = _label("GuideRunDescription")
        layout.addWidget(self._description)
        self._keys = _label("GuideRunKeys")
        layout.addWidget(self._keys)
        self._screen = _RunScreen()
        layout.addWidget(self._screen)
        self._source = _label("GuideRunSource")
        self._source.setAlignment(Qt.AlignRight)
        layout.addWidget(self._source)
        layout.addStretch(1)

        self._tabs.currentChanged.connect(self._select_example)
        l10n.RefreshBinding(self, self._refresh_language)

    def showEvent(self, event):
        super().showEvent(event)
        self._select_example(self._tabs.currentIndex())

    def _refresh_language(self):
        for index, (label, _, _) in enumerate(_RECORDING_EXAMPLES):
            caption = ui(label)
            self._tabs.setTabText(index, caption)
            self._tabs.setTabToolTip(index, caption)
        self._select_example(self._tabs.currentIndex())

    def _select_example(self, index):
        label, description, keys = _RECORDING_EXAMPLES[index]
        self._description.setText(message(
            description, powerups=l10n.tr("Powerups"), diff_cap=TIMELINE_CAP_LABELS["Difficulty"],
        ))
        self._keys.setText(message(keys) if keys else "")
        self._keys.setVisible(bool(keys))
        self._screen.setAccessibleName(ui(label))
        if self.isVisible():
            if self._context == _capture_context(self._app):
                self._screen.set_screenshot(self._screens[index])
            else:
                self._capture.start(0)

    def _show_screen(self):
        self._context = _capture_context(self._app)
        self._screens = capture_recording_screens(self._app)
        sample = load_run_example()
        kills = QLocale(localization().translator.language).toString(sample.kill_count)
        character = str(l10n.game("characters", sample.character))
        self._source.setText(message("run.real_recording", character=character, kills=kills))
        self._screen.set_screenshot(self._screens[self._tabs.currentIndex()])
