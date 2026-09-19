"""Non-modal Shady Guy lifetime analytics window."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from app import config
from ui.dialogs.shell import DIALOG_TALL, DIALOG_WIDE, dialog_body, dialog_footer


class MerchantAnalyticsWindow(QDialog):
    def __init__(self, app, parent=None) -> None:
        super().__init__(parent)
        self._app = app
        self._service = app.coordinator.merchant_analytics
        self._last_snapshot_key = None
        self.setWindowTitle("Shady Guy Analytics")
        self.setModal(False)

        self._collect = QCheckBox("Collect Shady Guy analytics")
        self._collect.toggled.connect(self._toggle_collection)
        layout = dialog_body(
            self,
            title="Shady Guy Analytics",
            subtitle="Lifetime item availability from the merchants you have viewed.",
            title_trailing=self._collect,
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )

        self._status = QLabel()
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        filters = QHBoxLayout()
        self._family = QComboBox()
        self._family.addItem("All map families", None)
        self._family.addItem("Forest / Desert", "forest_desert")
        self._family.addItem("Graveyard", "graveyard")
        self._stage = QComboBox()
        self._stage.addItem("All stages", None)
        for stage in range(1, 5):
            self._stage.addItem(f"Stage {stage}", stage)
        self._rarity = QComboBox()
        self._rarity.addItem("All merchant rarities", None)
        for value, label in (
            ("white", "White"),
            ("blue", "Blue"),
            ("purple", "Purple"),
            ("gold", "Gold"),
        ):
            self._rarity.addItem(label, value)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search item name or ID")
        for widget in (self._family, self._stage, self._rarity):
            widget.currentIndexChanged.connect(self.refresh)
            filters.addWidget(widget)
        self._search.textChanged.connect(self.refresh)
        filters.addWidget(self._search, 1)
        layout.addLayout(filters)

        totals = QGridLayout()
        self._merchants = QLabel("0")
        self._offers = QLabel("0")
        self._rarities = QLabel("White 0 · Blue 0 · Purple 0 · Gold 0")
        totals.addWidget(QLabel("MERCHANTS VIEWED"), 0, 0)
        totals.addWidget(QLabel("OFFERS RECORDED"), 0, 1)
        totals.addWidget(QLabel("MERCHANT RARITIES"), 0, 2)
        totals.addWidget(self._merchants, 1, 0)
        totals.addWidget(self._offers, 1, 1)
        totals.addWidget(self._rarities, 1, 2)
        layout.addLayout(totals)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ("Item", "ID", "Offers", "% of viewed merchants")
        )
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._table.verticalHeader().setFixedWidth(52)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 80), (2, 100), (3, 220)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self._table.setColumnWidth(column, width)
        layout.addWidget(self._table, 1)

        open_folder = QPushButton("Open data folder")
        export = QPushButton("Export JSON")
        clear = QPushButton("Clear history")
        close = QPushButton("Close")
        open_folder.clicked.connect(self._open_folder)
        export.clicked.connect(self._export)
        clear.clicked.connect(self._clear)
        close.clicked.connect(self.close)
        leading = QWidget()
        leading_layout = QHBoxLayout(leading)
        leading_layout.setContentsMargins(0, 0, 0, 0)
        leading_layout.addWidget(open_folder)
        leading_layout.addWidget(export)
        dialog_footer(
            self,
            secondary=close,
            destructive=clear,
            leading=leading,
        )

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self.refresh()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start()
        self.refresh()

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def refresh(self, *_args) -> None:
        enabled = bool(getattr(config, "MERCHANT_ANALYTICS_ENABLED", False))
        premium = bool(self._app.has_premium_access())
        self._collect.blockSignals(True)
        self._collect.setChecked(enabled)
        self._collect.setEnabled(premium or enabled)
        self._collect.blockSignals(False)

        status = self._service.status()
        if status.error:
            status_text = status.error
        elif enabled and premium:
            status_text = f"Collection active · {status.session_recorded} recorded this session"
        elif enabled:
            status_text = "Collection paused: Premium access is required for new observations."
        else:
            status_text = "Collection off. Saved history remains available."
        self._status.setText(status_text)

        map_family = self._family.currentData()
        stage = self._stage.currentData()
        merchant_rarity = self._rarity.currentData()
        search = self._search.text()
        snapshot_key = (
            status.revision,
            map_family,
            stage,
            merchant_rarity,
            search,
        )
        if snapshot_key == self._last_snapshot_key:
            return
        self._last_snapshot_key = snapshot_key
        snapshot = self._service.snapshot(
            map_family=map_family,
            stage=stage,
            merchant_rarity=merchant_rarity,
            search=search,
        )
        self._merchants.setText(f"{snapshot.merchants:,}")
        self._offers.setText(f"{snapshot.offers:,}")
        rarity_values = dict(snapshot.rarity_counts)
        self._rarities.setText(
            " · ".join(
                f"{name.title()} {rarity_values.get(name, 0):,}"
                for name in ("white", "blue", "purple", "gold")
            )
        )
        self._table.setRowCount(len(snapshot.rows))
        for row_index, row in enumerate(snapshot.rows):
            values = (
                row.display_name,
                str(row.item_id),
                f"{row.offer_count:,}",
                f"{row.merchant_percent:.1f}%",
            )
            for column, value in enumerate(values):
                self._table.setItem(row_index, column, QTableWidgetItem(value))

    def _toggle_collection(self, enabled: bool) -> None:
        set_merchant_analytics_collection(self._app, enabled, parent=self)
        self.refresh()

    def _open_folder(self) -> None:
        folder = self._service.store.path.parent
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _export(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Export Shady Guy analytics",
            str(Path(self._service.store.path.parent) / "shady_guy_analytics.json"),
            "JSON files (*.json)",
        )
        if not filename:
            return
        try:
            self._service.export_json(filename)
        except Exception as exc:
            QMessageBox.warning(self, "Export failed", str(exc))

    def _clear(self) -> None:
        status = self._service.status()
        answer = QMessageBox.question(
            self,
            "Clear Shady Guy history",
            f"Delete {status.total_recorded:,} saved merchant observations?\n\n"
            "Collection will be turned off.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._toggle_collection(False)
        if bool(getattr(config, "MERCHANT_ANALYTICS_ENABLED", False)):
            return
        try:
            self._service.clear()
        except Exception as exc:
            QMessageBox.warning(self, "Clear failed", str(exc))
        self.refresh()


def show_merchant_analytics(app) -> MerchantAnalyticsWindow:
    dialog = getattr(app, "_merchant_analytics_window", None)
    if dialog is None:
        dialog = MerchantAnalyticsWindow(app, getattr(app, "window", None))
        app._merchant_analytics_window = dialog
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return dialog


def set_merchant_analytics_collection(app, enabled: bool, *, parent=None) -> bool:
    """Persist and apply the collection switch shared by both analytics views."""

    enabled = bool(enabled)
    current = bool(getattr(config, "MERCHANT_ANALYTICS_ENABLED", False))
    if enabled and not app.has_premium_access():
        return current
    result = config.update_config(
        lambda candidate: candidate.__setitem__(
            "MERCHANT_ANALYTICS_ENABLED", enabled
        )
    )
    if not result.success:
        QMessageBox.warning(parent, "Shady Guy Analytics", result.reason)
        return current
    config.MERCHANT_ANALYTICS_ENABLED = enabled
    config.user_config["MERCHANT_ANALYTICS_ENABLED"] = enabled
    app._in_game_overlay._sync_map_marker_runtime()
    return enabled
