"""Native Settings selector using the catalog and the application's access gate."""

from ui import i18n as l10n
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QComboBox

from ui.themes import premium_access_for_themes, selected_theme
from ui.themes.registry import theme_catalog


class ThemeSelector(QComboBox):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setObjectName("appearanceThemeSelector")
        l10n.display(self, 'setAccessibleName', l10n.tr('Application design'))
        l10n.display(self, 'setToolTip', l10n.tr('Choose the application design. Applied when you save Settings.'))
        self.reload()

    def _populate(self, requested):
        with QSignalBlocker(self):
            self.clear()
            premium = premium_access_for_themes(self.owner)
            for entry in theme_catalog().themes:
                caption = l10n.tr("Original") if entry.id == "original" else entry.name
                suffix = " · Premium" if entry.access == "premium" else ""
                label = l10n.transform(caption, lambda value, ending=suffix: value + ending)
                l10n.combo_item(self, label, entry.id)
                index = self.count() - 1
                self.model().item(index).setEnabled(entry.available(premium))
                if not entry.available(premium):
                    l10n.combo_tooltip(self, index, l10n.tr("Requires active Premium"))
            index = self.findData(requested)
            if index < 0:
                l10n.combo_item(self, l10n.tr('{p0} (Unavailable)', p0=requested), requested)
                index = self.count() - 1
                self.model().item(index).setEnabled(False)
            self.setCurrentIndex(index)

    def reload(self):
        self._populate(selected_theme())

    def showPopup(self):  # noqa: N802
        # Access can change while the reusable Settings dialog is open.
        self._populate(self.currentData())
        super().showPopup()
