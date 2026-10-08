"""Compact lifetime and recording roll analytics; saved data remains accessible."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, QUrl, QSize
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QHeaderView,
    QHBoxLayout, QLabel, QMenu, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
)

from app import config
from app.roll_analytics_view import save_view_preferences, view_preferences
from core.roll_analysis_view import REFERENCE_MODEL_NOTE, expected_rolls, summarize_selected
from core.roll_analytics import aggregate_roll_counts
from ui.shared import resource_path
from ui.dialogs.roll_recording_picker import RollRecordingPicker
from ui.dialogs.shell import DIALOG_WIDE, DIALOG_TALL, dialog_body, dialog_footer, show_app_notice


def _clock(seconds):
    if seconds is None:
        return "unknown time"
    minutes, seconds = divmod(int(seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"


def _signed(value):
    return "0.0" if abs(value) < 0.05 else f"{value:+,.1f}"


class RollAnalyticsWindow(QDialog):
    def __init__(self, app, parent=None):
        super().__init__(parent)
        self._app = app
        self._service = app.coordinator.roll_analytics
        self._source = "dice"
        selected, expected = view_preferences()
        self._selected = frozenset(selected)
        self._show_expected = expected
        self._last_key = None
        self.setWindowTitle("Roll Analytics")
        self.setModal(False)
        self._status = QLabel(self)
        self._status.setObjectName("dialogSubtitle")
        layout = dialog_body(
            self, title="Roll Analytics", subtitle="Dice passive and Chaos Tome · lifetime or a saved recording",
            title_trailing=self._status, width=DIALOG_WIDE, height=DIALOG_TALL,
        )
        tabs = QFrame(self)
        tabs.setProperty("segmentedToggle", True)
        tab_layout = QHBoxLayout(tabs)
        tab_layout.setContentsMargins(4, 4, 4, 4)
        self._tabs = QButtonGroup(self)
        self._tabs.setExclusive(True)
        self._source_buttons = {}
        for source, caption, icon in (("dice", "Dice passive", "roll_dice.svg"),
                                      ("chaos", "Chaos Tome", "roll_chaos.svg")):
            button = QPushButton(QIcon(resource_path("media/" + icon)), caption, tabs)
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

        data_row = QHBoxLayout()
        self._data_mode = QComboBox(self)
        self._data_mode.addItem("Lifetime history", "lifetime")
        self._data_mode.addItem("From recording", "recording")
        self._data_mode.setToolTip("Viewing a recording never adds its rolls to lifetime history.")
        data_row.addWidget(self._data_mode)
        self._recording_picker = RollRecordingPicker(getattr(app, "vod_library", None), self)
        self._recording_picker.hide()
        data_row.addWidget(self._recording_picker, 1)
        self._expected_switch = QCheckBox("Expected (27-stat model)", self)
        self._expected_switch.setChecked(expected)
        self._expected_switch.setToolTip(REFERENCE_MODEL_NOTE + " At narrow widths, Share is available in row tooltips.")
        data_row.addWidget(self._expected_switch)
        layout.addLayout(data_row)
        self._recording_context = QLabel(self)
        self._recording_context.setTextFormat(Qt.PlainText)
        self._recording_context.setObjectName("dialogSubtitle")
        self._recording_context.setWordWrap(True)
        self._recording_context.hide()
        layout.addWidget(self._recording_context)

        summary = QFrame(self)
        summary.setObjectName("card")
        summary_layout = QHBoxLayout(summary)
        summary_layout.setContentsMargins(14, 12, 14, 12)
        caption = QLabel("CONFIRMED ROLLS", summary)
        caption.setObjectName("kpiLabel")
        summary_layout.addWidget(caption)
        self._total = QLabel("0", summary)
        self._total.setObjectName("kpiValue")
        summary_layout.addWidget(self._total)
        summary_layout.addStretch(1)
        self._selected_summary = QLabel(summary)
        self._selected_summary.setObjectName("dialogSubtitle")
        self._selected_summary.setWordWrap(True)
        self._selected_summary.setTextFormat(Qt.PlainText)
        summary_layout.addWidget(self._selected_summary, 1)
        self._clear_selected = QPushButton("Clear selection", summary)
        self._clear_selected.clicked.connect(lambda: self._save_preferences((), self._show_expected))
        summary_layout.addWidget(self._clear_selected)
        layout.addWidget(summary)
        tables_layout = QHBoxLayout()
        tables_layout.setContentsMargins(0, 0, 0, 0)
        tables_layout.setSpacing(12)
        self._tables = tuple(self._build_stat_table() for _ in range(2))
        for table in self._tables:
            tables_layout.addWidget(table, 1)
            table.itemChanged.connect(self._stat_checked)
        for index, table in enumerate(self._tables):
            table.verticalScrollBar().valueChanged.connect(
                lambda value, peer=self._tables[1 - index]: self._sync_stat_scroll(peer, value))
        layout.addLayout(tables_layout, 1)
        self._note = QLabel(self)
        self._note.setObjectName("dialogSubtitle")
        self._note.setTextFormat(Qt.PlainText)
        self._note.setWordWrap(True)
        layout.addWidget(self._note)
        data = QPushButton("Data", self)
        menu = QMenu(data)
        self._export_action = menu.addAction("Export lifetime JSON…", self._export)
        menu.addAction("Open data folder", self._open_folder)
        menu.addSeparator()
        self._clear_action = menu.addAction("Clear lifetime history…", self._clear)
        data.setMenu(menu)
        close = QPushButton("Close", self)
        close.clicked.connect(self.close)
        dialog_footer(self, secondary=close, leading=data)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self._data_mode.currentIndexChanged.connect(self._mode_changed)
        self._expected_switch.toggled.connect(self._expected_changed)
        self._recording_picker.changed.connect(self.refresh)
        self.refresh()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for table in getattr(self, "_tables", ()):
            table.setColumnHidden(2, self._show_expected and self.width() < 1050)

    def _build_stat_table(self):
        table = QTableWidget(0, 5, self)
        table.setHorizontalHeaderLabels(("Stat", "Rolls", "Share", "Expected", "Δ"))
        table.horizontalHeaderItem(0).setToolTip("Check a stat to pin it and include it in the selected-stats summary.")
        table.horizontalHeaderItem(2).setToolTip("Share of all confirmed rolls for this source; selection never changes the denominator.")
        for column in (3, 4):
            table.horizontalHeaderItem(column).setToolTip(REFERENCE_MODEL_NOTE + " Δ = actual minus expected.")
        table.setShowGrid(False)
        table.setStyleSheet("QTableWidget::item { border-bottom: 1px solid #1D2730; padding: 4px 6px; }")
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(28)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setTextElideMode(Qt.ElideRight)
        header = table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 65), (2, 72), (3, 78), (4, 65)):
            header.setSectionResizeMode(column, QHeaderView.Fixed)
            table.setColumnWidth(column, width)
        return table

    @staticmethod
    def _sync_stat_scroll(peer, value):
        scrollbar = peer.verticalScrollBar()
        blocked = scrollbar.blockSignals(True)
        try:
            scrollbar.setValue(value)
        finally:
            scrollbar.blockSignals(blocked)

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()
        if self._data_mode.currentData() == "recording":
            self._recording_picker.set_active(True)
        self.refresh()

    def hideEvent(self, event):
        self._timer.stop()
        self._recording_picker.set_active(False)
        super().hideEvent(event)

    def closeEvent(self, event):
        self._recording_picker.set_active(False)
        super().closeEvent(event)

    def _select_source(self, source):
        self._source = source
        self._source_buttons[source].setChecked(True)
        self.refresh()

    def _mode_changed(self, *_args):
        recording = self._data_mode.currentData() == "recording"
        self._recording_picker.setVisible(recording)
        self._recording_context.setVisible(recording)
        self._recording_picker.set_active(recording)
        self.refresh()

    def _expected_changed(self, enabled):
        self._save_preferences(self._selected, enabled)

    def _save_preferences(self, selected, expected):
        result = save_view_preferences(selected, expected)
        if result.success:
            self._selected = frozenset(selected)
            self._show_expected = bool(expected)
        else:
            show_app_notice(self, title="Roll Analytics", message=result.reason, danger=True)
        self._expected_switch.blockSignals(True)
        self._expected_switch.setChecked(self._show_expected)
        self._expected_switch.blockSignals(False)
        self._last_key = None
        self.refresh()

    def _stat_checked(self, item):
        if item.column() != 0 or item.data(Qt.UserRole) is None:
            return
        selected = set(self._selected)
        stat_id = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            selected.add(stat_id)
        else:
            selected.discard(stat_id)
        if selected != set(self._selected):
            self._save_preferences(selected, self._show_expected)

    def refresh(self):
        status = self._service.status()
        enabled = bool(getattr(config, "ROLL_ANALYTICS_ENABLED", False))
        premium = bool(self._app.has_premium_access())
        self._service.set_collection_active(enabled and premium)
        recording = self._data_mode.currentData() == "recording"
        picker = self._recording_picker
        if recording:
            picker.refresh_library()
        key = (self._source, recording, status.revision if not recording else id(picker.recorded),
               picker.loading, picker.error, self._selected, self._show_expected, self.width() < 1050)
        self._export_action.setEnabled(not recording)
        self._clear_action.setEnabled(not recording)
        if recording:
            self._status.setText("Reading recording…" if picker.loading else "Recorded data · read only")
        else:
            self._status.setText("Collection paused" if status.error else
                                 "Collection active" if enabled and premium else
                                 "Collection paused · Premium required" if enabled else "Collection off")
            self._note.setText(status.error or "Manage collection in Session Stats. Saved history remains available without Premium.")
        if key == self._last_key:
            return
        self._last_key = key
        available = True
        if recording:
            self._note.setText("Recording data is never added to lifetime history. Check stats to pin them.")
            snapshot = aggregate_roll_counts(self._source, {})
            result = picker.recorded.for_source(self._source) if picker.recorded is not None else None
            available = bool(result is not None and result.analytics is not None)
            if available:
                snapshot = result.analytics
                stamp = result.game_time_seconds if result.game_time_seconds is not None else result.elapsed_seconds
                suffix = " · earlier confirmed snapshot" if result.older_snapshot else " · last saved snapshot"
                date = picker.recorded.created_at.replace("T", " ")
                self._recording_context.setText(f"{picker.recorded.name} · {date} · at {_clock(stamp)}{suffix}")
                self._recording_context.setToolTip(str(picker.recorded.path))
                if not picker.recorded.finalized or picker.recorded.incomplete_tail:
                    self._note.setText("Incomplete recording: showing the last confirmed saved state. Lifetime history is unchanged.")
            else:
                self._recording_context.setText(picker.error or
                    ("Reading the recording header and tail…" if picker.loading else
                     result.reason if result is not None else "Choose a saved recording or open a .jsonl file."))
                self._recording_context.setToolTip(str(picker.path or ""))
        else:
            snapshot = self._service.snapshot(self._source)
        self._total.setText(f"{snapshot.total:,}" if available else "—")
        self._clear_selected.setEnabled(bool(self._selected))
        if not self._selected:
            self._selected_summary.setText("Check the stats you want to follow.")
        elif not available:
            self._selected_summary.setText(f"Selected stats: {len(self._selected)} · data unavailable")
        else:
            selected = summarize_selected(snapshot, self._selected)
            share = f"{selected.percent:.1f}%" if selected.percent is not None else "—"
            message = f"Selected stats ({selected.selected_stats}): {selected.count:,}/{selected.total:,} · {share}"
            if self._show_expected and selected.expected is not None:
                message += f"\nExpected {selected.expected:,.1f} · Δ {_signed(selected.difference)}"
            self._selected_summary.setText(message)
        self._selected_summary.setToolTip(REFERENCE_MODEL_NOTE if self._show_expected else
            "The denominator is all confirmed rolls for the selected source and dataset.")
        rows = sorted(snapshot.rows, key=lambda row: row.stat_id not in self._selected)
        half = (len(rows) + 1) // 2
        for table, panel in zip(self._tables, (rows[:half], rows[half:])):
            scroll = table.verticalScrollBar().value()
            table.blockSignals(True)
            table.setUpdatesEnabled(False)
            try:
                table.setColumnHidden(2, self._show_expected and self.width() < 1050)
                table.setColumnHidden(3, not self._show_expected)
                table.setColumnHidden(4, not self._show_expected)
                table.setRowCount(half)
                for index in range(half):
                    row = panel[index] if index < len(panel) else None
                    expected = expected_rolls(snapshot.source, snapshot.total, (row.stat_id,)) if row and available else None
                    values = (row.label, f"{row.count:,}" if available else "—",
                              f"{row.percent:.1f}%" if available and row.percent is not None else "—",
                              f"{expected:,.1f}" if expected is not None else "—",
                              _signed(row.count - expected) if expected is not None else "—") if row else ("",) * 5
                    for column, text in enumerate(values):
                        item = table.item(index, column)
                        if item is None:
                            item = QTableWidgetItem()
                            table.setItem(index, column, item)
                        item.setText(text)
                        item.setData(Qt.UserRole, row.stat_id if row else None)
                        item.setFlags((Qt.ItemIsEnabled | Qt.ItemIsSelectable |
                                       (Qt.ItemIsUserCheckable if column == 0 else Qt.NoItemFlags)) if row else Qt.NoItemFlags)
                        if column == 0:
                            item.setData(Qt.CheckStateRole, (Qt.Checked if row.stat_id in self._selected else Qt.Unchecked) if row else None)
                        font = table.font()
                        font.setBold(bool(row and row.stat_id in self._selected))
                        item.setFont(font)
                        tooltip = (row.label + " · check to pin and include in selected stats" if column == 0 else
                                   REFERENCE_MODEL_NOTE if column in (3, 4) else
                                   f"{row.label}: {row.count:,} of {snapshot.total:,} confirmed rolls" + (f" ({row.percent:.1f}%)" if row.percent is not None else "") if available else
                                   "No confirmed recorded counters.") if row else ""
                        item.setToolTip(tooltip)
                        item.setTextAlignment((Qt.AlignLeft if column == 0 else Qt.AlignRight) | Qt.AlignVCenter)
                self._sync_stat_scroll(table, scroll)
                # Lifetime totals can grow beyond the compact default widths.
                # Measure the actual items, including the bold pinned rows.
                for column, minimum in ((1, 65), (2, 72), (3, 78), (4, 65)):
                    header = table.horizontalHeader()
                    heading = header.fontMetrics().horizontalAdvance(table.horizontalHeaderItem(column).text()) + 16
                    table.setColumnWidth(column, max(minimum, heading, table.sizeHintForColumn(column) + 12))
            finally:
                table.blockSignals(False)
                table.setUpdatesEnabled(True)

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
