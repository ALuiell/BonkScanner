from __future__ import annotations

import src  # noqa: F401
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QApplication

from app import config
from app.roll_analytics import RollAnalyticsService
from app.roll_analytics_view import RollRecordingCache, save_view_preferences, view_preferences
from core.roll_analytics import ROLL_STATS, aggregate_roll_counts
from infra.roll_history_store import RollHistoryStore
from infra.roll_recording import read_recorded_rolls
from src.tests.test_roll_analysis_view import frame, write_recording
from ui.dialogs.roll_analytics import RollAnalyticsWindow


class RollAnalyticsViewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.service = RollAnalyticsService(RollHistoryStore(self.root / "history.json"))
        self.addCleanup(self.service.close)
        self.app = NS(coordinator=NS(roll_analytics=self.service), has_premium_access=lambda: False)
        self.preferences = patch.dict(config.user_config, {"ROLL_ANALYTICS_VIEW": {}})
        self.preferences.start()
        self.addCleanup(self.preferences.stop)
        self.window = RollAnalyticsWindow(self.app)
        self.addCleanup(self.window.close)

    def wait(self, predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            self.qt.processEvents()
            time.sleep(0.005)
        self.qt.processEvents()
        self.assertTrue(predicate(), "Qt worker did not settle")

    def item_for(self, stat_id):
        table = self.window._table
        return next(table.item(i, column) for column in (0, 6)
                    for i in range(table.rowCount())
                    if table.item(i, column).data(Qt.UserRole) == stat_id)

    def test_game_order_fills_left_then_right_without_selection_controls(self):
        table = self.window._table
        self.assertEqual(table.rowCount(), 14)
        labels = [table.item(i, column).text() for column in (0, 6)
                  for i in range(table.rowCount()) if table.item(i, column).text()]
        self.assertEqual(labels, [label for _stat_id, label in ROLL_STATS])
        self.assertEqual(table.item(13, 6).text(), "")
        self.assertTrue(all(table.item(i, column).data(Qt.CheckStateRole) is None
                            for column in (0, 6) for i in range(table.rowCount())))
        self.assertFalse(hasattr(self.window, "_selected_summary"))

    def test_sort_by_reorders_all_stats_before_splitting_columns(self):
        counts = {ROLL_STATS[0][0]: 3, ROLL_STATS[16][0]: 9, ROLL_STATS[-1][0]: 12}
        with patch.object(self.service, "snapshot", return_value=aggregate_roll_counts("dice", counts)):
            self.window._sort_by.setCurrentIndex(1)  # Most rolls
            table = self.window._table
            self.assertEqual(table.item(0, 0).text(), ROLL_STATS[-1][1])
            self.assertEqual(table.item(1, 0).text(), ROLL_STATS[16][1])
            ranked = sorted(aggregate_roll_counts("dice", counts).rows,
                            key=lambda row: row.count, reverse=True)
            self.assertEqual(table.item(0, 6).text(), ranked[14].label)
            self.window._sort_by.setCurrentIndex(2)  # Fewest rolls
            self.assertEqual(table.item(0, 0).text(), ROLL_STATS[1][1])
            self.window._sort_by.setCurrentIndex(0)
            self.assertEqual(table.item(0, 0).text(), ROLL_STATS[0][1])

    def test_failed_preference_write_rolls_back_expected(self):
        with patch("ui.dialogs.roll_analytics.save_view_preferences", return_value=NS(success=False, reason="read only")), \
             patch("ui.dialogs.roll_analytics.show_app_notice") as notice:
            self.window._expected_switch.setChecked(True)
            self.assertFalse(self.window._show_expected)
            self.assertFalse(self.window._expected_switch.isChecked())
            notice.assert_called_once()

    def test_recording_mode_uses_cached_two_source_result_without_history_write(self):
        path = write_recording(self.root / "run.jsonl", [frame({12: 27}, {30: 54})])
        read = Mock(wraps=read_recorded_rolls)
        picker = self.window._recording_picker
        picker._cache = RollRecordingCache(reader=read)
        self.window._data_mode.setCurrentIndex(1)
        picker.select_path(path)
        self.wait(lambda: picker.recorded is not None)
        self.assertEqual(self.window._total.text(), "27")
        self.window._source_buttons["chaos"].click()
        self.assertEqual(self.window._total.text(), "54")
        with patch("ui.dialogs.roll_analytics.save_view_preferences", return_value=NS(success=True)):
            self.window._expected_switch.setChecked(True)
        table = self.window._table
        stat = self.item_for(30)
        self.assertFalse(table.isColumnHidden(3))
        self.assertEqual(table.item(stat.row(), stat.column() + 3).text(), "2.0")
        self.assertEqual(read.call_count, 1)
        self.assertFalse(self.window._clear_action.isEnabled())
        self.assertEqual(self.service.snapshot("dice").total, 0)
        self.assertEqual(self.service.snapshot("chaos").total, 0)
        self.window._data_mode.setCurrentIndex(0)
        self.assertEqual(self.window._total.text(), "0")
        self.assertTrue(self.window._clear_action.isEnabled())

    def test_absent_recording_source_displays_unavailable_not_zero(self):
        path = write_recording(self.root / "run.jsonl", [frame(chaos={30: 5})])
        self.window._data_mode.setCurrentIndex(1)
        picker = self.window._recording_picker
        picker.select_path(path)
        self.wait(lambda: picker.recorded is not None)
        self.assertEqual(self.window._total.text(), "—")
        self.assertIn("No confirmed", self.window._recording_context.text())
        self.window._source_buttons["chaos"].click()
        self.assertEqual(self.window._total.text(), "5")

    def test_incomplete_recording_warning_survives_unchanged_timer_refresh(self):
        path = write_recording(self.root / "unfinished.jsonl", [frame({12: 27}, {30: 54})], summary=False)
        self.window._data_mode.setCurrentIndex(1)
        picker = self.window._recording_picker
        picker.select_path(path)
        self.wait(lambda: picker.recorded is not None)
        self.assertIn("Incomplete recording", self.window._note.text())
        self.window.refresh()
        self.assertIn("Incomplete recording", self.window._note.text())

    def test_latest_saved_excludes_active_and_uses_created_date(self):
        old = write_recording(self.root / "old.jsonl", [frame({12: 1}, {30: 1})])
        latest = write_recording(self.root / "saved.jsonl", [frame({12: 2}, {30: 2})])
        active = self.root / "active.jsonl"
        entries = [NS(path=p, name=p.stem, created_at=str(i), created_label=str(i), snapshot_count=1)
                   for i, p in enumerate((old, latest, active))]
        picker = self.window._recording_picker
        picker._library = NS(index=entries, ensure_refresh=Mock(), is_active_path=lambda p: Path(p) == active)
        self.window._data_mode.setCurrentIndex(1)
        self.wait(lambda: picker.recorded is not None)
        self.assertEqual(picker.path, latest)
        self.assertEqual(picker.combo.count(), 2)
        picker.select_path(active)
        self.assertIsNone(picker.recorded)
        self.assertIn("Finish saving", picker.error)

    def test_slow_previous_load_cannot_replace_new_selection(self):
        a = write_recording(self.root / "a.jsonl", [frame({12: 1}, {30: 1})])
        b = write_recording(self.root / "b.jsonl", [frame({12: 2}, {30: 2})])
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def read(path, *, cancelled=None):
            if path == a:
                started.set()
                release.wait(2)
            return read_recorded_rolls(path, cancelled=cancelled)
        picker = self.window._recording_picker
        picker._cache = RollRecordingCache(reader=read)
        self.window._data_mode.setCurrentIndex(1)
        picker.select_path(a)
        self.wait(started.is_set)
        picker.select_path(b)
        release.set()
        self.wait(lambda: picker.recorded is not None)
        self.assertEqual(picker.recorded.path, b)
        self.assertEqual(self.window._total.text(), "2")

    def test_close_cancels_pending_delivery(self):
        path = write_recording(self.root / "a.jsonl", [frame({12: 1}, {30: 1})])
        started, release, finished = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def read(path, *, cancelled=None):
            started.set()
            release.wait(2)
            try:
                return read_recorded_rolls(path, cancelled=cancelled)
            finally:
                finished.set()
        picker = self.window._recording_picker
        picker._cache = RollRecordingCache(reader=read)
        self.window._data_mode.setCurrentIndex(1)
        picker.select_path(path)
        self.wait(started.is_set)
        self.window.close()
        release.set()
        self.wait(finished.is_set)
        self.assertIsNone(picker.recorded)
        self.assertIsNone(picker._lane)

    def test_compact_layout_shows_all_rows_in_one_table(self):
        self.window.resize(900, 720)
        self.window.show()
        self.qt.processEvents()
        table = self.window._table
        self.assertEqual(table.rowCount(), 14)
        self.assertGreater(table.viewport().width(), 700)
        self.assertEqual(table.verticalScrollBar().maximum(), 0)
        with patch("ui.dialogs.roll_analytics.save_view_preferences", return_value=NS(success=True)):
            self.window._expected_switch.setChecked(True)
        self.qt.processEvents()
        self.assertEqual(table.horizontalHeaderItem(10).text(), "Δ")
        self.assertGreater(table.columnWidth(0), 100)
        self.assertEqual(table.verticalScrollBar().maximum(), 0)
        self.window._data_mode.setCurrentIndex(1)
        self.qt.processEvents()
        self.assertEqual(table.verticalScrollBar().maximum(), 0)

    def test_preferences_use_existing_transaction_and_round_trip(self):
        def commit(mutate):
            candidate = dict(config.user_config)
            mutate(candidate)
            config.user_config.update(candidate)
            return NS(success=True)
        with patch.object(config, "update_config", side_effect=commit):
            save_view_preferences([30, 12, 12, True], True)
        self.assertEqual(view_preferences(), ((12, 30), True))

    def test_real_styles_keep_share_and_expected_visible(self):
        from ui.styles import build_qt_app_stylesheet
        from ui.shared import resource_path
        old_style = self.qt.styleSheet()
        try:
            self.qt.setStyleSheet(build_qt_app_stylesheet(Path(resource_path("media/checkmark.svg")).as_posix()))
            self.window.show()
            with patch("ui.dialogs.roll_analytics.save_view_preferences", return_value=NS(success=True)):
                self.window._expected_switch.setChecked(True)
            for width in (900, 1100):
                self.window.resize(width, 720)
                self.qt.processEvents()
                table = self.window._table
                self.assertFalse(table.isColumnHidden(2))
                self.assertFalse(table.isColumnHidden(3))
                self.assertFalse(table.isColumnHidden(8))
                self.assertFalse(table.isColumnHidden(9))
                self.assertGreater(table.columnWidth(0), 100)
                self.assertEqual(table.verticalScrollBar().maximum(), 0)
        finally:
            self.qt.setStyleSheet(old_style)

    def test_large_numeric_values_fit_in_both_halves(self):
        from ui.styles import build_qt_app_stylesheet
        from ui.shared import resource_path
        old_style = self.qt.styleSheet()
        try:
            self.qt.setStyleSheet(build_qt_app_stylesheet(Path(resource_path("media/checkmark.svg")).as_posix()))
            path = write_recording(self.root / "large.jsonl", [frame(chaos={12: 1000000, 30: 26000000})])
            self.window.show()
            self.window._data_mode.setCurrentIndex(1)
            picker = self.window._recording_picker
            picker.select_path(path)
            self.wait(lambda: picker.recorded is not None)
            self.window._source_buttons["chaos"].click()
            with patch("ui.dialogs.roll_analytics.save_view_preferences", return_value=NS(success=True)):
                self.window._expected_switch.setChecked(True)
            for width in (900, 1100):
                self.window.resize(width, 720)
                self.qt.processEvents()
                table = self.window._table
                for row in range(table.rowCount()):
                    for column in (1, 2, 3, 4, 7, 8, 9, 10):
                        item = table.item(row, column)
                        if item is not None and item.text():
                            required = QFontMetrics(item.font()).horizontalAdvance(item.text()) + 12
                            self.assertGreaterEqual(table.columnWidth(column), required, item.text())
        finally:
            self.qt.setStyleSheet(old_style)
