"""Non-modal Shady Guy lifetime analytics window."""
from __future__ import annotations

from ui import i18n as l10n

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
        l10n.display(self, 'setWindowTitle', l10n.tr('Shady Guy Analytics'))
        self.setModal(False)

        self._status = QLabel()
        self._status.setObjectName("dialogSubtitle")
        layout = dialog_body(self, title=l10n.tr('Shady Guy Analytics'), subtitle=l10n.tr('Lifetime item availability from the merchants you have viewed.'), title_trailing=self._status, width=DIALOG_WIDE, height=DIALOG_TALL)

        filters = QHBoxLayout()
        self._family = QComboBox()
        l10n.combo_item(self._family, l10n.tr('All map families'), None)
        l10n.combo_item(self._family, l10n.tr('Forest / Desert'), 'forest_desert')
        l10n.combo_item(self._family, l10n.tr('Graveyard'), 'graveyard')
        self._stage = QComboBox()
        l10n.combo_item(self._stage, l10n.tr('All stages'), None)
        for stage in range(1, 5):
            l10n.combo_item(self._stage, l10n.tr('Stage {p0}', p0=stage), stage)
        self._item_sort = CompactItemsSortComboBox()
        l10n.combo_item(self._item_sort, l10n.tr('Most offered'), 'default')
        l10n.combo_item(self._item_sort, l10n.tr('Rarity: high to low'), 'rarity_desc')
        l10n.combo_item(self._item_sort, l10n.tr('Rarity: low to high'), 'rarity_asc')
        self._item_sort.setCurrentIndex(self._item_sort.findData("rarity_desc"))
        self._search = QLineEdit()
        l10n.display(self._search, 'setPlaceholderText', l10n.tr('Search item name or ID'))
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
        self._merchants = l10n.localized(QLabel, '0')
        self._offers = l10n.localized(QLabel, '0')
        for column, caption in enumerate(("MERCHANTS VIEWED", "OFFERS RECORDED", "MERCHANT RARITIES")):
            label = l10n.localized(QLabel, caption)
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
            l10n.display(badge, 'setToolTip', l10n.tr('Filter by {p0} merchants. Click again to show all rarities.', p0=name))
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
        l10n.table_headers(self._table, (l10n.tr('Item'), l10n.tr('Offers'), l10n.tr('% of viewed merchants')))
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

        data = l10n.localized(QPushButton, l10n.tr('Data'))
        menu = QMenu(data)
        l10n.menu_action(menu, l10n.tr('Export JSON…'), self._export)
        l10n.menu_action(menu, l10n.tr('Open data folder'), self._open_folder)
        menu.addSeparator()
        l10n.menu_action(menu, l10n.tr('Clear history…'), self._clear)
        data.setMenu(menu)
        close = l10n.localized(QPushButton, l10n.tr('Close'))
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
            status_text = l10n.tr('Collection paused · Storage error')
        elif enabled and premium:
            status_text = l10n.tr('Collection active · {p0} recorded this session', p0=status.session_recorded)
        elif enabled:
            status_text = l10n.tr('Collection paused · Premium required')
        else:
            status_text = l10n.tr('Collection off')
        l10n.display(self._status, 'setText', status_text)
        l10n.display(self._status, 'setToolTip', status.error or l10n.tr('Manage collection in Session Stats. Saved history remains available.'))

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
        l10n.display(self._merchants, 'setText', f'{snapshot.merchants:,}')
        l10n.display(self._offers, 'setText', f'{snapshot.offers:,}')
        rarity_values = dict(snapshot.rarity_counts)
        for name, badge in self._rarities.items():
            l10n.display(badge, 'setText', f'{name.title()} {rarity_values.get(name, 0):,}')
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
                l10n.display(item, 'setToolTip', l10n.tr('{p0} · ID {p1}', p0=row.display_name, p1=row.item_id))
                if column == 2:
                    l10n.display(item, 'setToolTip', l10n.tr('Available at {p0:,} of {p1:,} viewed merchants matching the current filters.', p0=row.merchant_count, p1=snapshot.merchants))
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
            show_app_notice(self, title=l10n.tr('Could not open folder'), subtitle=l10n.tr('Shady Guy analytics'), message=l10n.tr('BonkScanner could not open this folder.\n\n{p0}\n\n{p1}', p0=folder, p1=reason), danger=True)

    def _export(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(self, l10n.tr('Export Shady Guy analytics'), str(Path(self._service.store.path.parent) / 'shady_guy_analytics.json'), 'JSON files (*.json)')
        if not filename:
            return
        try:
            self._service.export_json(filename)
        except Exception as exc:
            QMessageBox.warning(self, l10n.tr('Export failed'), str(exc))

    def _clear(self) -> None:
        status = self._service.status()
        answer = QMessageBox.question(self, l10n.tr('Clear Shady Guy history'), l10n.tr('Delete {p0:,} saved merchant observations?\n\nCollection will be turned off.', p0=status.total_recorded), QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self._toggle_collection(False)
        if bool(getattr(config, "MERCHANT_ANALYTICS_ENABLED", False)):
            return
        try:
            self._service.clear()
        except Exception as exc:
            QMessageBox.warning(self, l10n.tr('Clear failed'), str(exc))
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
        QMessageBox.warning(parent, l10n.tr('Shady Guy Analytics'), result.reason)
        return current
    config.MERCHANT_ANALYTICS_ENABLED = enabled
    config.user_config["MERCHANT_ANALYTICS_ENABLED"] = enabled
    app._in_game_overlay._sync_map_marker_runtime()
    return enabled
