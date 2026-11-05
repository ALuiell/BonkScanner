"""Explicit native-overlay bindings; never translate arbitrary widget trees."""
from PySide6.QtCore import QObject, QSignalBlocker, Slot
from PySide6.QtWidgets import QLabel, QCheckBox, QComboBox

from core.overlay_localization import OVERLAY_MESSAGE_KEYS
from ui.dialogs.shell import dialog_body
from ui.localization import bind_text, localization
from ui.settings_card import SettingsCard
from ui.tab_hero import TabHero


def text(source: str, **values) -> str:
    return localization().text(OVERLAY_MESSAGE_KEYS[source], **values)


def bind(widget, source: str, *, method="setText", values=None):
    return bind_text(widget, OVERLAY_MESSAGE_KEYS[source], method=method, values=values)


def widget(control, source=None):
    source = control.text() if source is None else source
    control.setProperty("overlay_source", source)
    bind(control, source)
    return control


class RefreshBinding(QObject):
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.callback = callback
        localization().changed.connect(self.refresh)

    @Slot()
    def refresh(self):
        self.callback()


def combo_item(combo, caption, value):
    # Re-measure after a language change rather than retaining the width of
    # the English caption measured on the first show.
    combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
    index = combo.count()
    combo.addItem(text(caption), value)
    def refresh():
        with QSignalBlocker(combo):
            combo.setItemText(index, text(caption))
    RefreshBinding(combo, refresh)


def game_widget(control, category, source):
    def refresh():
        name = localization().translator.game_name(category, source)
        control.setText(name)
        control.setToolTip(name)
        if isinstance(control, QCheckBox):
            control.setMinimumWidth(control.sizeHint().width())
    RefreshBinding(control, refresh)
    refresh()
    return control


def action_name(action):
    translator = localization().translator
    if translator.cache_key == ("en", "en"):
        return action.display_name
    label = translator.game_name("activities", action.label)
    if label == action.label and label in OVERLAY_MESSAGE_KEYS:
        label = text(label)
    return f"{label} · {text(action.variant)}" if action.variant else label


def bind_overlay_tab(tabview, page):
    page.setProperty("translation_tab_id", "In-Game Overlay")
    def refresh():
        index = tabview.indexOf(page)
        if index >= 0:
            tabview.setTabText(index, text("In-Game Overlay"))
    RefreshBinding(page, refresh)
    refresh()


def localized_dialog_body(dialog, *, title, subtitle="", **kwargs):
    layout = dialog_body(dialog, title=title, subtitle=subtitle, **kwargs)
    bind(dialog.findChild(QLabel, "dialogTitle"), title)
    if subtitle:
        bind(dialog.findChild(QLabel, "dialogSubtitle"), subtitle)
    return layout


class OverlaySettingsCard(SettingsCard):
    def __init__(self, *, title, subtitle="", **kwargs):
        super().__init__(title=title, subtitle=subtitle, **kwargs)
        bind(self._title, title)
        if subtitle:
            bind(self._subtitle, subtitle)


class OverlayTabHero(TabHero):
    def __init__(self, *, title, subtitle, auto_text, **kwargs):
        super().__init__(title=title, subtitle=subtitle, auto_text=auto_text, **kwargs)
        bind(self._title, title)
        bind(self, subtitle, method="set_subtitle")
        bind(self.auto_switch, auto_text)
