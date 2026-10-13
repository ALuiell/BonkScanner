"""Native Settings selector using the catalog and the application's access gate."""
from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QComboBox

from ui.themes import premium_access_for_themes, selected_theme
from ui.themes.registry import theme_catalog


class ThemeSelector(QComboBox):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setObjectName("appearanceThemeSelector")
        self.setAccessibleName("Application design")
        self.setToolTip("Choose the application design. Applied when you save Settings.")
        self.reload()

    def _populate(self, requested):
        with QSignalBlocker(self):
            self.clear()
            premium = premium_access_for_themes(self.owner)
            for entry in theme_catalog().themes:
                label = entry.name + (" · Premium" if entry.access == "premium" else "")
                self.addItem(label, entry.id)
                index = self.count() - 1
                self.model().item(index).setEnabled(entry.available(premium))
                if not entry.available(premium):
                    self.setItemData(index, "Requires active Premium", Qt.ToolTipRole)
            index = self.findData(requested)
            if index < 0:
                self.addItem(f"{requested} (Unavailable)", requested)
                index = self.count() - 1
                self.model().item(index).setEnabled(False)
            self.setCurrentIndex(index)

    def reload(self):
        self._populate(selected_theme())

    def showPopup(self):  # noqa: N802
        # Access can change while the reusable Settings dialog is open.
        self._populate(self.currentData())
        super().showPopup()
