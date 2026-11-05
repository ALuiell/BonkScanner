"""Qt bindings for explicitly opted-in text; models and user text stay intact."""
from __future__ import annotations

from PySide6.QtCore import QObject, QSignalBlocker, Signal, Slot, QTranslator, QLibraryInfo
from PySide6.QtWidgets import QApplication, QComboBox

from app.localization import (create_localization_translator, selected_language,
                              selected_game_language, selected_languages)
from core.localization import SUPPORTED_LANGUAGES, FOLLOW_INTERFACE_LANGUAGE


class UiLocalization(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.translator = create_localization_translator()
        self._qt_translator = QTranslator(self)
        self._load_standard_messages()

    def _load_standard_messages(self):
        application = QApplication.instance()
        application.removeTranslator(self._qt_translator)
        code = "pt_BR" if self.translator.language == "pt" else self.translator.language
        if code != "en" and self._qt_translator.load(
            "qtbase_" + code, QLibraryInfo.path(QLibraryInfo.TranslationsPath)
        ):
            application.installTranslator(self._qt_translator)

    def text(self, key: str, **values) -> str:
        return self.translator.text(key, **values)

    def apply_saved_language(self) -> None:
        previous_language = self.translator.language
        if self.translator.set_languages(*selected_languages()):
            if self.translator.language != previous_language:
                self._load_standard_messages()
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


class GameLanguageSelector(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("gameLanguageSelector")
        self.addItem("", FOLLOW_INTERFACE_LANGUAGE)
        for code, name in SUPPORTED_LANGUAGES.items():
            self.addItem(name, code)
        self.reload()
        bind_text(self, "settings.game_language", method="setAccessibleName")
        bind_text(self, "settings.game_language_hint", method="setToolTip")
        localization().changed.connect(self._retranslate)
        self._retranslate()

    @Slot()
    def _retranslate(self):
        with QSignalBlocker(self):
            self.setItemText(0, localization().text("settings.game_language_follow"))

    def reload(self):
        with QSignalBlocker(self):
            self.setCurrentIndex(self.findData(selected_game_language()))
