"""Qt bindings for explicitly opted-in text; models and user text stay intact."""
from __future__ import annotations

from PySide6.QtCore import QObject, QSignalBlocker, Signal, Slot
from PySide6.QtWidgets import QApplication, QComboBox

from app.localization import create_localization_translator, selected_language
from core.localization import SUPPORTED_LANGUAGES


class UiLocalization(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.translator = create_localization_translator()

    def text(self, key: str, **values) -> str:
        return self.translator.text(key, **values)

    def apply_saved_language(self) -> None:
        if self.translator.set_language(selected_language()):
            self.changed.emit()


def localization() -> UiLocalization:
    application = QApplication.instance()
    if application is None:
        raise RuntimeError("Create QApplication before binding localized widgets")
    service = getattr(application, "_bonkscanner_localization", None)
    if service is None:
        service = UiLocalization(application)
        application._bonkscanner_localization = service
    return service


class TextBinding(QObject):
    """The widget owns its binding; Qt disconnects it when the widget dies."""

    def __init__(self, widget, key: str, *, method="setText", prefix="", values=None):
        super().__init__(widget)
        self._widget = widget
        self._key = key
        self._method = method
        self._prefix = prefix
        self._values = values or {}
        self._localization = localization()
        self._localization.changed.connect(self.refresh)
        self.refresh()

    @Slot()
    def refresh(self):
        values = self._values() if callable(self._values) else self._values
        getattr(self._widget, self._method)(self._prefix + self._localization.text(self._key, **values))


def bind_text(widget, key: str, **kwargs) -> TextBinding:
    return TextBinding(widget, key, **kwargs)


class LanguageSelector(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("interfaceLanguageSelector")
        for code, name in SUPPORTED_LANGUAGES.items():
            self.addItem(name, code)
        self.reload()
        bind_text(self, "settings.language", method="setAccessibleName")
        bind_text(self, "settings.language_hint", method="setToolTip")

    def reload(self):
        with QSignalBlocker(self):
            self.setCurrentIndex(self.findData(selected_language()))
