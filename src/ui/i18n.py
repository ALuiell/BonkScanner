"""Explicit display-text adapters. Stored values and user content are never translated.

UiText carries a complete message and its parameters up to the Qt boundary.
Bindings belong to their widgets and refresh without emitting editing signals.
"""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QObject, QSignalBlocker, Qt, Slot, Signal
from PySide6.QtWidgets import QApplication, QLabel, QGroupBox, QTabWidget, QComboBox

from ui.localization import localization
from core.localization_context import DisplayText, GameDisplayText, message_key as source_key


class StoredMessage:
    """Keep Python provenance opaque to QVariant's automatic str conversion."""
    def __init__(self, value):
        self.value = value


_ITEM_MESSAGES_ROLE = int(Qt.UserRole) + 149


@lru_cache(maxsize=1)
def _standalone_translator():
    from app.localization import create_localization_translator
    return create_localization_translator()


def active_translator():
    return localization().translator if QApplication.instance() else _standalone_translator()


class UiText(str):
    def __new__(cls, source, values=None):
        values = values or {}
        instance = super().__new__(cls, cls._render(source, values))
        instance.source = source
        instance.values = values
        return instance

    @staticmethod
    def _render(source, values):
        translator = active_translator()
        return translator.text(source_key(source), **values)

    def render(self):
        return self._render(self.source, self.values)

    def canonical(self):
        return self.source.format(**self.values)

    def __str__(self):
        return self.render()

    def __format__(self, spec):
        return format(self.render(), spec)


def tr(source, **values):
    return UiText(source, values)


def preserve(value):
    return value if isinstance(value, (UiText, DisplayText, GameDisplayText)) else str(value)


class PrefixedText(UiText):
    def __new__(cls, prefix, message):
        instance = str.__new__(cls, prefix + message.render())
        instance.prefix, instance.message = prefix, message
        return instance

    def render(self):
        return self.prefix + self.message.render()

    def canonical(self):
        return self.prefix + self.message.canonical()


def prefixed(prefix, message):
    return PrefixedText(prefix, message) if isinstance(message, UiText) else prefix + message


class TransformedText(UiText):
    def __new__(cls, message, operation):
        instance = str.__new__(cls, operation(str(message)))
        instance.message, instance.operation = message, operation
        return instance

    def render(self):
        return self.operation(self.message.render())

    def canonical(self):
        return self.operation(self.message.canonical())


def transform(message, operation):
    if isinstance(message, DisplayText):
        message = UiText(message.source, message.values)
    return TransformedText(message, operation) if isinstance(message, UiText) else operation(str(message))


class JoinedText(UiText):
    def __new__(cls, separator, messages):
        instance = str.__new__(cls, separator.join(map(str, messages)))
        instance.separator, instance.messages = separator, tuple(messages)
        return instance

    def render(self):
        return self.separator.join(map(str, self.messages))

    def canonical(self):
        return self.separator.join(m.canonical() if isinstance(m, UiText) else str(m)
                                   for m in self.messages)


def join(separator, messages):
    return JoinedText(separator, [term(message) for message in messages])


class GameText(UiText):
    def __new__(cls, category, source, english=None):
        instance = str.__new__(cls, source)
        instance.category, instance.name = category, source
        instance.english = english
        return instance

    def render(self):
        translator = active_translator()
        return self.english if translator.game_language == "en" and self.english is not None else translator.game_name(self.category, self.name)

    def canonical(self):
        return self.name


def game(category, source, *, english=None):
    return GameText(category, str(source), english)


def game_term(source, categories):
    translator = active_translator()
    for category in categories:
        if translator.has_game_name(category, source):
            return game(category, source)
    return term(source)


def stat(source):
    if isinstance(source, UiText):
        return source
    if isinstance(source, DisplayText):
        return UiText(source.source, source.values)
    if isinstance(source, GameDisplayText):
        return transform(game(source.category, source.name), lambda name, suffix=source.suffix: name + suffix)
    from core.stat_labels import STAT_LABEL_ABBREVIATIONS
    canonical = next((key for key, value in STAT_LABEL_ABBREVIATIONS.items() if value == source), source)
    return game("stats", canonical, english=source) if active_translator().has_game_name("stats", canonical) else term(source)


class TermText(UiText):
    def __new__(cls, source, category=None):
        instance = str.__new__(cls, source)
        instance.name, instance.category = source, category
        return instance

    def render(self):
        translator = active_translator()
        if self.category is not None:
            return self.name if translator.game_language == "en" else translator.game_name(self.category, self.name)
        try:
            return translator.text(source_key(self.name.replace("{", "{{").replace("}", "}}")))
        except KeyError:
            return self.name

    def canonical(self):
        return self.name


def term(source, category=None):
    if isinstance(source, UiText):
        return source
    if isinstance(source, DisplayText):
        return UiText(source.source, source.values)
    if isinstance(source, GameDisplayText):
        return transform(game(source.category, source.name), lambda name, suffix=source.suffix: name + suffix)
    return TermText(str(source), category)


def status_message(source, summary):
    """Localize owned status copy; retain opaque diagnostic details verbatim."""
    if isinstance(source, (UiText, DisplayText, GameDisplayText)):
        return term(source)
    source = str(source or "")
    escaped = source.replace("{", "{{").replace("}", "}}")
    if localization().translator.has_text(source_key(escaped)):
        return tr(escaped)
    if not source:
        return summary
    return tr("{summary}\n\n{details}", summary=summary, details=source)


def preset_name(source, *, uppercase=False):
    captions = {
        "light": tr("Light"), "good": tr("Good"),
        "perfect": tr("Perfect"), "perfect+": tr("Perfect+"),
        "merchant": tr("Merchant"), "boss rush": tr("Boss Rush"),
        "boss rush+": tr("Boss Rush+"),
    }
    message = captions.get(source.casefold(), source)
    return transform(message, str.upper) if uppercase else message


def template_name(template):
    from app import config
    name = str(template.get("name", ""))
    default = next((row for row in config.DEFAULT_TEMPLATES
                    if row.get("id") == template.get("id")), None)
    # Renamed built-ins are user content too, even though their ID is retained.
    if default is not None and name == default.get("name"):
        return preset_name(name, uppercase=name.isupper())
    return name


class DisplayBinding(QObject):
    def __init__(self, widget, method):
        super().__init__(widget)
        self.widget = widget
        self.method = method
        self.message = None
        localization().changed.connect(self.refresh)

    @Slot()
    def refresh(self):
        if self.message is not None:
            with QSignalBlocker(self.widget):
                getattr(self.widget, self.method)(self.message.render())


class RefreshBinding(QObject):
    def __init__(self, parent, callback):
        super().__init__(parent)
        self.callback = callback
        localization().changed.connect(self.refresh)
        self.refresh()

    @Slot()
    def refresh(self):
        self.callback()


def display(widget, method, message):
    if isinstance(message, DisplayText):
        message = UiText(message.source, message.values)
    elif isinstance(message, GameDisplayText):
        message = transform(game(message.category, message.name), lambda name, suffix=message.suffix: name + suffix)
    if isinstance(widget, super):
        return getattr(widget, method)(str(message))
    if not isinstance(widget, QObject):
        # Table items are owned by a model, not QObjects. One table-level
        # binding refreshes its current items; removed rows have no listeners.
        stored = widget.data(_ITEM_MESSAGES_ROLE) if hasattr(widget, "data") else None
        messages = stored.value if isinstance(stored, StoredMessage) else {}
        messages[method] = message if isinstance(message, UiText) else None
        if hasattr(widget, "setData"):
            widget.setData(_ITEM_MESSAGES_ROLE, StoredMessage(messages))
        getattr(widget, method)(str(message))
        owner = widget.tableWidget() if hasattr(widget, "tableWidget") else None
        if owner is not None:
            _table_binding(owner)
        return
    bindings = getattr(widget, "_display_bindings", None)
    if bindings is None:
        bindings = widget._display_bindings = {}
    binding = bindings.get(method)
    if isinstance(message, UiText):
        if binding is None:
            binding = bindings[method] = DisplayBinding(widget, method)
        binding.message = message
        binding.refresh()
    else:
        # A new unbound value supersedes the previous message (for example a
        # newly selected recording's user-defined name).
        if binding is not None:
            binding.message = None
        getattr(widget, method)(message)


def localized(factory, *args, **kwargs):
    args = tuple(UiText(x.source, x.values) if isinstance(x, DisplayText) else x for x in args)
    args = tuple(transform(game(x.category, x.name), lambda name, suffix=x.suffix: name + suffix)
                 if isinstance(x, GameDisplayText) else x for x in args)
    widget = factory(*(str(x) if isinstance(x, UiText) else x for x in args), **kwargs)
    for message in args:
        if isinstance(message, UiText):
            display(widget, "setTitle" if isinstance(widget, QGroupBox) else "setText", message)
            break
    return widget


class TableBinding(QObject):
    def __init__(self, table):
        super().__init__(table)
        self.table = table
        localization().changed.connect(self.refresh)

    @Slot()
    def refresh(self):
        items = [self.table.horizontalHeaderItem(c) for c in range(self.table.columnCount())]
        items += [self.table.item(r, c) for r in range(self.table.rowCount()) for c in range(self.table.columnCount())]
        with QSignalBlocker(self.table):
            for item in items:
                stored = item.data(_ITEM_MESSAGES_ROLE) if item is not None else None
                messages = stored.value if isinstance(stored, StoredMessage) else {}
                for method, message in messages.items():
                    if message is not None:
                        getattr(item, method)(message.render())


def _table_binding(table):
    if not hasattr(table, "_table_translation"):
        table._table_translation = TableBinding(table)


def table_headers(table, captions):
    table.setHorizontalHeaderLabels([str(x) for x in captions])
    for index, caption in enumerate(captions):
        if isinstance(caption, UiText):
            display(table.horizontalHeaderItem(index), "setText", caption)


def menu_action(menu, caption, *args):
    action = menu.addAction(str(caption), *args)
    if isinstance(caption, UiText):
        display(action, "setText", caption)
    return action


def form_row(layout, caption, *fields):
    if isinstance(caption, UiText):
        caption = localized(QLabel, caption)
    return layout.addRow(caption, *fields)


_COMBO_MESSAGE_ROLE = int(Qt.UserRole) + 147
_COMBO_SOURCE_ROLE = int(Qt.UserRole) + 148
_COMBO_TOOLTIP_ROLE = int(Qt.UserRole) + 150


class ComboBinding(QObject):
    def __init__(self, combo):
        super().__init__(combo)
        self.combo = combo
        localization().changed.connect(self.refresh)

    @Slot()
    def refresh(self):
        with QSignalBlocker(self.combo):
            for index in range(self.combo.count()):
                message = self.combo.itemData(index, _COMBO_MESSAGE_ROLE)
                if isinstance(message, StoredMessage):
                    self.combo.setItemText(index, message.value.render())
                tooltip = self.combo.itemData(index, _COMBO_TOOLTIP_ROLE)
                if isinstance(tooltip, StoredMessage):
                    self.combo.setItemData(index, tooltip.value.render(), Qt.ToolTipRole)
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)


def combo_item(combo, caption, *args):
    index = combo.count()
    combo.addItem(str(caption), *args)
    if isinstance(caption, UiText):
        combo.setItemData(index, StoredMessage(caption), _COMBO_MESSAGE_ROLE)
        combo.setItemData(index, caption.canonical(), _COMBO_SOURCE_ROLE)
        if not hasattr(combo, "_combo_translation"):
            combo._combo_translation = ComboBinding(combo)
        combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)


def combo_items(combo, captions):
    for caption in captions:
        combo_item(combo, caption)


def combo_tooltip(combo, index, message):
    combo.setItemData(index, str(message), Qt.ToolTipRole)
    if isinstance(message, UiText):
        combo.setItemData(index, StoredMessage(message), _COMBO_TOOLTIP_ROLE)
        if not hasattr(combo, "_combo_translation"):
            combo._combo_translation = ComboBinding(combo)


def combo_value(combo):
    value = combo.currentData(_COMBO_SOURCE_ROLE)
    return combo.currentText() if value is None else value


def find_combo_value(combo, value):
    for index in range(combo.count()):
        canonical = combo.itemData(index, _COMBO_SOURCE_ROLE)
        if (combo.itemText(index) if canonical is None else canonical) == value:
            return index
    return -1


def set_combo_value(combo, value):
    index = find_combo_value(combo, value)
    if index >= 0:
        combo.setCurrentIndex(index)
    else:
        combo.setCurrentText(value)


class ComboValueRelay(QObject):
    changed = Signal(str)

    def __init__(self, combo):
        super().__init__(combo)
        self.combo = combo
        combo.currentTextChanged.connect(self.emit_value)

    @Slot(str)
    def emit_value(self, _caption):
        self.changed.emit(combo_value(self.combo))


def connect_combo_value(combo, callback):
    if not hasattr(combo, "_canonical_text_signal"):
        combo._canonical_text_signal = ComboValueRelay(combo)
    return combo._canonical_text_signal.changed.connect(callback)


class TabBinding(QObject):
    def __init__(self, tabs):
        super().__init__(tabs)
        self.tabs = tabs
        self.messages = {}
        localization().changed.connect(self.refresh)

    @Slot()
    def refresh(self):
        with QSignalBlocker(self.tabs):
            for index in range(self.tabs.count()):
                message = self.messages.get(tab_identity(self.tabs, index))
                if message is not None:
                    self.tabs.setTabText(index, message.render())


def tab_identity(tabs, index):
    if isinstance(tabs, QTabWidget):
        page = tabs.widget(index)
        identity = page.property("translation_tab_id") if page is not None else None
        if identity is not None:
            return identity
    binding = getattr(tabs, "_tabs_translation", None)
    if binding is not None:
        return binding.indices.get(index, tabs.tabText(index))
    return tabs.tabText(index)


def tab(tabs, *args):
    caption = args[-1]
    index = tabs.addTab(*(str(x) if isinstance(x, UiText) else x for x in args))
    if isinstance(caption, UiText):
        if not hasattr(tabs, "_tabs_translation"):
            tabs._tabs_translation = TabBinding(tabs)
            tabs._tabs_translation.indices = {}
        identity = caption.canonical()
        tabs._tabs_translation.messages[identity] = caption
        tabs._tabs_translation.indices[index] = identity
        if isinstance(tabs, QTabWidget):
            tabs.widget(index).setProperty("translation_tab_id", identity)
    return index
