"""Non-modal lifetime analytics. Viewing saved data never requires Premium."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, QSize
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFileDialog, QFrame, QHeaderView, QHBoxLayout,
    QLabel, QMenu, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
)

from app import config
from ui.shared import resource_path
from ui.dialogs.shell import DIALOG_REGULAR, DIALOG_TALL, dialog_body, dialog_footer, show_app_notice


class RollAnalyticsWindow(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._service = app.coordinator.roll_analytics
        self._source = "dice"
        self._last_key = None
        self.setWindowTitle("Roll Analytics")
        self.setModal(False)
        self._status = QLabel()
        self._status.setObjectName("dialogSubtitle")
        self._status.setWordWrap(True)
        layout = dialog_body(self, title="Roll Analytics",
                             subtitle="Lifetime stat rolls from Dice passive and Chaos Tome.",
                             width=DIALOG_REGULAR, height=DIALOG_TALL)
        layout.addWidget(self._status)
        tabs = QFrame()
        tabs.setProperty("segmentedToggle", True)
        tab_layout = QHBoxLayout(tabs)
        tab_layout.setContentsMargins(4, 4, 4, 4)
        tab_layout.setSpacing(4)
        self._tabs = QButtonGroup(self)
        self._tabs.setExclusive(True)
        self._source_buttons = {}
        for source, caption, icon in (("dice", "Dice passive", "roll_dice.svg"),
                                      ("chaos", "Chaos Tome", "roll_chaos.svg")):
            button = QPushButton(QIcon(resource_path("media/" + icon)), caption)
            button.setObjectName("RollAnalyticsSource")
            button.setIconSize(QSize(18, 18))
            button.setCheckable(True)
            button.setChecked(source == self._source)
            button.setAccessibleName(caption)
            button.clicked.connect(lambda _checked, name=source: self._select_source(name))
            self._tabs.addButton(button)
            self._source_buttons[source] = button
            tab_layout.addWidget(button, 1)
        layout.addWidget(tabs)
        summary = QFrame()
        summary.setObjectName("card")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        caption = QLabel("CONFIRMED ROLLS")
        caption.setObjectName("kpiLabel")
        summary_layout.addWidget(caption)
        self._total = QLabel("0")
        self._total.setObjectName("kpiValue")
        summary_layout.addWidget(self._total)
        summary_layout.addStretch(1)
        layout.addWidget(summary)
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(("Stat", "Roll count", "% of confirmed rolls"))
        self._table.setShowGrid(False)
        self._table.setStyleSheet("QTableWidget::item { border-bottom: 1px solid #1D2730; padding: 6px 12px; }")
        self._table.verticalHeader().hide()
        self._table.verticalHeader().setDefaultSectionSize(38)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 100), (2, 178)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self._table.setColumnWidth(column, width)
        layout.addWidget(self._table, 1)
        self._note = QLabel("Manage collection in Session Stats. Saved history remains available without Premium.")
        self._note.setObjectName("dialogSubtitle")
        self._note.setWordWrap(True)
        layout.addWidget(self._note)
        data = QPushButton("Data")
        menu = QMenu(data)
        menu.addAction("Export JSON…", self._export)
        menu.addAction("Open data folder", self._open_folder)
        menu.addSeparator()
        menu.addAction("Clear history…", self._clear)
        data.setMenu(menu)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        dialog_footer(self, secondary=close, leading=data)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()
        self.refresh()

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _select_source(self, source):
        self._source = source
        self.refresh()

    def refresh(self):
        status = self._service.status()
        enabled = bool(getattr(config, "ROLL_ANALYTICS_ENABLED", False))
        premium = bool(self._app.has_premium_access())
        self._service.set_collection_active(enabled and premium)
        self._status.setText("Collection paused" if status.error else
                             "Collection active" if enabled and premium else
                             "Collection paused · Premium required" if enabled else "Collection off")
        self._note.setText(status.error or
                           "Manage collection in Session Stats. Saved history remains available without Premium.")
        snapshot = self._service.snapshot(self._source)
        key = (self._source, status.revision)
        if key == self._last_key:
            return
        self._last_key = key
        self._total.setText(f"{snapshot.total:,}")
        scroll = self._table.verticalScrollBar().value()
        self._table.setUpdatesEnabled(False)
        try:
            self._table.setRowCount(len(snapshot.rows))
            for index, row in enumerate(snapshot.rows):
                for column, text in enumerate((row.label, f"{row.count:,}",
                                               "—" if row.percent is None else f"{row.percent:.1f}%")):
                    item = self._table.item(index, column)
                    if item is None:
                        item = QTableWidgetItem()
                        self._table.setItem(index, column, item)
                    item.setText(text)
                    item.setTextAlignment((Qt.AlignLeft if column == 0 else Qt.AlignRight) | Qt.AlignVCenter)
            self._table.verticalScrollBar().setValue(scroll)
        finally:
            self._table.setUpdatesEnabled(True)

    def _open_folder(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._service.store.path.parent)))

    def _export(self):
        path, _selected = QFileDialog.getSaveFileName(self, "Export roll analytics", "roll_analytics.json", "JSON (*.json)")
        if path:
            try:
                self._service.export_json(path)
            except Exception as exc:
                show_app_notice(self, title="Roll Analytics", message=str(exc), danger=True)

    def _clear(self):
        answer = QMessageBox.question(
            self, "Clear roll history",
            "Delete all saved Dice and Chaos Tome roll counts?\n\nCollection will be turned off.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        if set_roll_analytics_collection(self._app, False, parent=self):
            return
        try:
            self._service.clear()
        except Exception as exc:
            show_app_notice(self, title="Roll Analytics", message=str(exc), danger=True)
        self.refresh()


def show_roll_analytics(app):
    dialog = getattr(app, "_roll_analytics_window", None)
    if dialog is None:
        dialog = RollAnalyticsWindow(app, app.window)
        app._roll_analytics_window = dialog
    dialog.refresh()
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


def set_roll_analytics_collection(app, enabled, *, parent=None):
    enabled = bool(enabled)
    current = bool(getattr(config, "ROLL_ANALYTICS_ENABLED", False))
    if enabled and not app.has_premium_access():
        return current
    result = config.update_config(lambda candidate: candidate.__setitem__("ROLL_ANALYTICS_ENABLED", enabled))
    if not result.success:
        QMessageBox.warning(parent, "Roll Analytics", result.reason)
        return current
    config.ROLL_ANALYTICS_ENABLED = enabled
    config.user_config["ROLL_ANALYTICS_ENABLED"] = enabled
    app.roll_analytics_collection_active()
    scanner = getattr(app, "_scanner", None)
    if scanner is not None:
        scanner.on_supporter_access_changed()
    return enabled
