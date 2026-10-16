"""Non-modal Shady Guy lifetime analytics window."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
)

from app import config
from core.item_metadata import ITEMS, ITEM_RARITY_COLOR_MAP
from projections.item_sort import ITEM_RARITY_SORT_ORDER
from ui.tabs.player_stats.items_section import CompactItemsSortComboBox
from ui.dialogs.shell import (
    DIALOG_TALL,
    DIALOG_WIDE,
    dialog_body,
    dialog_footer,
    show_app_notice,
)


class MerchantAnalyticsWindow(QDialog):
    def __init__(self, app, parent=None) -> None:
        super().__init__(parent)
        self._app = app
        self._service = app.coordinator.merchant_analytics
        self._last_snapshot_key = None
        self._selected_rarity = None
        self._item_colors = {
            item.item_id: QColor(ITEM_RARITY_COLOR_MAP[item.rarity])
            for item in ITEMS if item.rarity in ITEM_RARITY_COLOR_MAP
        }
        self.setWindowTitle("Shady Guy Analytics")
        self.setModal(False)

        self._status = QLabel()
        self._status.setObjectName("dialogSubtitle")
        layout = dialog_body(
            self,
            title="Shady Guy Analytics",
            subtitle="Lifetime item availability from the merchants you have viewed.",
            title_trailing=self._status,
            width=DIALOG_WIDE,
            height=DIALOG_TALL,
        )

        filters = QHBoxLayout()
        self._family = QComboBox()
        self._family.addItem("All map families", None)
        self._family.addItem("Forest / Desert", "forest_desert")
        self._family.addItem("Graveyard", "graveyard")
        self._stage = QComboBox()
        self._stage.addItem("All stages", None)
        for stage in range(1, 5):
            self._stage.addItem(f"Stage {stage}", stage)
        self._item_sort = CompactItemsSortComboBox()
        self._item_sort.addItem("Most offered", "default")
        self._item_sort.addItem("Rarity: high to low", "rarity_desc")
        self._item_sort.addItem("Rarity: low to high", "rarity_asc")
        self._item_sort.setCurrentIndex(self._item_sort.findData("rarity_desc"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search item name or ID")
        for widget in (self._family, self._stage, self._item_sort):
            widget.currentIndexChanged.connect(self.refresh)
            filters.addWidget(widget)
        self._search.textChanged.connect(self.refresh)
        filters.addWidget(self._search, 1)
        layout.addLayout(filters)

        summary = QFrame()
        summary.setObjectName("card")
        totals = QGridLayout(summary)
        totals.setContentsMargins(16, 12, 16, 12)
        totals.setHorizontalSpacing(24)
        self._merchants = QLabel("0")
        self._offers = QLabel("0")
        for column, caption in enumerate(("MERCHANTS VIEWED", "OFFERS RECORDED", "MERCHANT RARITIES")):
            label = QLabel(caption)
            label.setObjectName("kpiLabel")
            totals.addWidget(label, 0, column)
        for value in (self._merchants, self._offers):
            value.setObjectName("kpiValueHero")
        totals.addWidget(self._merchants, 1, 0)
        totals.addWidget(self._offers, 1, 1)
        rarities = QHBoxLayout()
        rarities.setSpacing(8)
        self._rarities = {}
        for name, color in (("white", "#EDF1F5"), ("blue", "#79B8FF"), ("purple", "#C49BFF"), ("gold", "#EBC56A")):
            badge = QPushButton()
            badge.setCheckable(True)
            badge.setAutoDefault(False)
            badge.setCursor(Qt.PointingHandCursor)
            badge.setToolTip(f"Filter by {name} merchants. Click again to show all rarities.")
            badge.setStyleSheet(
                f"QPushButton {{ color: {color}; background: #161D25; border: 1px solid transparent;"
                " border-radius: 6px; padding: 6px 9px; min-width: 0; }"
                f"QPushButton:hover {{ border-color: {color}; }}"
                f"QPushButton:checked {{ border-color: {color}; background: #263342; }}"
            )
            badge.clicked.connect(lambda checked, rarity=name: self._select_rarity(rarity, checked))
            self._rarities[name] = badge
            rarities.addWidget(badge)
        rarities.addStretch(1)
        totals.addLayout(rarities, 1, 2)
        totals.setColumnStretch(2, 1)
        layout.addWidget(summary)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(
            ("Item", "Offers", "% of viewed merchants")
        )
        self._table.setShowGrid(False)
        self._table.setStyleSheet("QTableWidget::item { border-bottom: 1px solid #1D2730; padding: 6px 12px; }")
        self._table.verticalHeader().setDefaultSectionSize(38)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self._table.verticalHeader().setFixedWidth(52)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 110), (2, 220)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            self._table.setColumnWidth(column, width)
        layout.addWidget(self._table, 1)

        data = QPushButton("Data")
        menu = QMenu(data)
        menu.addAction("Export JSON…", self._export)
        menu.addAction("Open data folder", self._open_folder)
        menu.addSeparator()
        menu.addAction("Clear history…", self._clear)
        data.setMenu(menu)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        dialog_footer(
            self,
            secondary=close,
            leading=data,
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
        status = self._service.status()
        if status.error:
            status_text = "Collection paused · Storage error"
        elif enabled and premium:
            status_text = f"Collection active · {status.session_recorded} recorded this session"
        elif enabled:
            status_text = "Collection paused · Premium required"
        else:
            status_text = "Collection off"
        self._status.setText(status_text)
        self._status.setToolTip(status.error or "Manage collection in Session Stats. Saved history remains available.")

        map_family = self._family.currentData()
        stage = self._stage.currentData()
        merchant_rarity = self._selected_rarity
        item_sort = self._item_sort.currentData()
        search = self._search.text()
        snapshot_key = (
            status.revision,
            map_family,
            stage,
            merchant_rarity,
            item_sort,
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
        for name, badge in self._rarities.items():
            badge.setText(f"{name.title()} {rarity_values.get(name, 0):,}")
        rows = snapshot.rows
        if item_sort in ("rarity_desc", "rarity_asc"):
            ranks = {item.item_id: ITEM_RARITY_SORT_ORDER.get(item.rarity) for item in ITEMS}
            direction = -1 if item_sort == "rarity_desc" else 1
            rows = sorted(rows, key=lambda row: (
                ranks.get(row.item_id) is None,
                direction * (ranks.get(row.item_id) or 0),
                -row.offer_count, row.display_name.casefold(), row.item_id,
            ))
        self._table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.display_name,
                f"{row.offer_count:,}",
                f"{row.merchant_percent:.1f}% · {row.merchant_count:,}/{snapshot.merchants:,}",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(f"{row.display_name} · ID {row.item_id}")
                if column == 2:
                    item.setToolTip(
                        f"Available at {row.merchant_count:,} of {snapshot.merchants:,} viewed merchants"
                        " matching the current filters."
                    )
                if column:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                elif row.item_id in self._item_colors:
                    item.setForeground(self._item_colors[row.item_id])
                self._table.setItem(row_index, column, item)

    def _select_rarity(self, rarity: str, checked: bool) -> None:
        self._selected_rarity = rarity if checked else None
        for name, button in self._rarities.items():
            button.setChecked(name == self._selected_rarity)
        self.refresh()

    def _toggle_collection(self, enabled: bool) -> None:
        set_merchant_analytics_collection(self._app, enabled, parent=self)
        self.refresh()

    def _open_folder(self) -> None:
        folder = self._service.store.path.parent
        try:
            folder.mkdir(parents=True, exist_ok=True)
            opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        except Exception as exc:
            opened = False
            reason = str(exc)
        else:
            reason = "Windows did not accept the folder request."
        if not opened:
            show_app_notice(
                self,
                title="Could not open folder",
                subtitle="Shady Guy analytics",
                message=f"BonkScanner could not open this folder.\n\n{folder}\n\n{reason}",
                danger=True,
            )

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
    """Persist collection changes from Session Stats or clearing history."""

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
