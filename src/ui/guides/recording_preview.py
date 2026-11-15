"""A native guide to Live Stats and Recordings using static UI excerpts."""
from PySide6.QtCore import QLocale, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QTabBar, QVBoxLayout, QWidget

from .guide_locale import localization, message, ui
from .native_live_screens import capture_live_screens
from .native_recording_screens import capture_recording_screens
from .run_sample import game_clock, load_run_example
from ui import i18n as l10n


_STYLE = """
QWidget#GuideRunPreview {background:transparent;}
QTabBar#GuideRunMode, QTabBar#GuideRunExamples {background:transparent; border:0;}
QTabBar#GuideRunMode::tab, QTabBar#GuideRunExamples::tab {
    background:#172333; border:1px solid #2d4258; border-radius:6px;
    color:#bed3e6; margin-right:6px; padding:7px 11px;
}
QTabBar#GuideRunMode::tab:selected, QTabBar#GuideRunExamples::tab:selected {
    background:#214365; color:#edf7ff; border-color:#5b91bc;
}
QTabBar#GuideRunMode::tab:focus, QTabBar#GuideRunExamples::tab:focus {border-color:#89c8ff;}
QLabel#GuideRunDescription {background:transparent; color:#d7e3f1; font-size:13px;}
QLabel#GuideRunKeys {background:transparent; color:#9fc4ea; font-size:12px;}
QLabel#GuideRunSource {background:transparent; color:#a9bdd0; font-size:12px;}
"""

_EXAMPLES = (
    (("Stats", "run.screen.live_stats"), ("Loot", "run.live_note")),
    (("Timeline", "run.screen.timeline"), ("Compare Details", "run.screen.compare"),
     ("Damage Sources", "run.screen.damage")),
)


class _RunScreen(QWidget):
    """Display a real UI excerpt without an image-opening action."""

    def __init__(self):
        super().__init__()
        self.setObjectName("GuideRunScreen")
        self._shot = QPixmap()
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(160)

    def set_screenshot(self, shot):
        self._shot = shot
        self._fit()
        self.update()

    def _fit(self):
        if self._shot.isNull():
            self.setFixedHeight(160)
        else:
            size = self._shot.size().scaled(QSize(max(1, self.width() - 2), 380), Qt.KeepAspectRatio)
            self.setFixedHeight(size.height() + 2)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def paintEvent(self, _event):
        painter = QPainter(self)
        if not self._shot.isNull():
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            size = self._shot.size().scaled(self.size() - QSize(2, 2), Qt.KeepAspectRatio)
            target = QRectF((self.width() - size.width()) / 2, 1, size.width(), size.height())
            painter.drawPixmap(target, self._shot, QRectF(self._shot.rect()))
        painter.end()


def _tabs(name):
    tabs = QTabBar()
    tabs.setObjectName(name)
    tabs.setDocumentMode(True)
    tabs.setDrawBase(False)
    tabs.setExpanding(False)
    tabs.setElideMode(Qt.ElideRight)
    tabs.setUsesScrollButtons(False)
    return tabs


class RunGuidePreview(QWidget):
    mode_changed = Signal()

    def __init__(self, app):
        super().__init__()
        self._app = app
        self._sample = load_run_example()
        self.setObjectName("GuideRunPreview")
        self.setStyleSheet(_STYLE)
        self._screens = {}
        self._last_example = [0, 0]
        self._examples_mode = None
        self._capture = QTimer(self)
        self._capture.setSingleShot(True)
        self._capture.timeout.connect(self._show_screen)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)
        mode_row = QHBoxLayout()
        self.mode_tabs = _tabs("GuideRunMode")
        for _ in _EXAMPLES:
            self.mode_tabs.addTab("")
        mode_row.addWidget(self.mode_tabs)
        self._source = QLabel()
        self._source.setObjectName("GuideRunSource")
        self._source.setWordWrap(True)
        self._source.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        mode_row.addWidget(self._source, 1)
        layout.addLayout(mode_row)
        self._example_tabs = _tabs("GuideRunExamples")
        self._example_tabs.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self._example_tabs)

        self._description = QLabel()
        self._description.setObjectName("GuideRunDescription")
        self._description.setWordWrap(True)
        layout.addWidget(self._description)
        self._keys = QLabel()
        self._keys.setObjectName("GuideRunKeys")
        self._keys.setWordWrap(True)
        layout.addWidget(self._keys)
        self._screen = _RunScreen()
        layout.addWidget(self._screen)
        layout.addStretch(1)

        self.mode_tabs.currentChanged.connect(self._mode_selected)
        self._example_tabs.currentChanged.connect(self._example_selected)
        l10n.RefreshBinding(self, self._refresh_language)

    @property
    def recordings_selected(self):
        return self.mode_tabs.currentIndex() == 1

    def _refresh_language(self):
        for index, label in enumerate(("Live Stats", "Recordings")):
            self.mode_tabs.setTabText(index, ui(label))
        self._refresh_examples()

    def _mode_selected(self, _index):
        self._refresh_examples()
        self.mode_changed.emit()

    def _refresh_examples(self):
        mode = self.mode_tabs.currentIndex()
        tabs = self._example_tabs
        character = str(l10n.game("characters", self._sample.character))
        if self.recordings_selected:
            kills = QLocale(localization().translator.language).toString(self._sample.kill_count)
            caption = message("run.real_recording", character=character, kills=kills)
        else:
            snap = self._sample.live_snapshot
            time = game_clock(snap.game_time_seconds or snap.elapsed_seconds)
            caption = message("run.live_snapshot", character=character, time=time)
        self._source.setText(caption)
        tabs.blockSignals(True)
        if mode != self._examples_mode:
            while tabs.count():
                tabs.removeTab(0)
            for _ in _EXAMPLES[mode]:
                tabs.addTab("")
            self._examples_mode = mode
        for index, (label, _) in enumerate(_EXAMPLES[mode]):
            caption = ui(label)
            tabs.setTabText(index, caption)
            tabs.setTabToolTip(index, caption)
        tabs.setCurrentIndex(self._last_example[mode])
        tabs.blockSignals(False)
        self._example_selected(tabs.currentIndex())

    def _example_selected(self, index):
        mode = self.mode_tabs.currentIndex()
        if index < 0:
            return
        self._last_example[mode] = index
        label, description = _EXAMPLES[mode][index]
        self._description.setText(message(description, loot=ui("Loot")))
        self._keys.setText(message("run.timeline_hint"))
        self._keys.setVisible(mode == 1 and index == 1)
        self._screen.setAccessibleName(ui(label))
        self._capture.start(0)

    def _show_screen(self):
        mode = self.mode_tabs.currentIndex()
        index = self._last_example[mode]
        translator = localization().translator
        key = (mode, translator.language, translator.game_language, self._app.window.styleSheet())
        shots = self._screens.get(key)
        if shots is None:
            capture = (capture_live_screens, capture_recording_screens)[mode]
            shots = self._screens[key] = capture(self._app)
        if mode == self.mode_tabs.currentIndex():
            self._screen.set_screenshot(shots[self._last_example[mode]])
