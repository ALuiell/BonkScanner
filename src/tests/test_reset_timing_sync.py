from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QLabel

from app import config
from ui.dialogs import GameResetTimeNoticeDialog, SettingsDialog


class ResetTimingSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.game_path = Path(directory) / "game.json"
        self.scanner_path = Path(directory) / "scanner.json"
        self.running = False
        self.stack.enter_context(patch.object(config, "get_game_config_path", return_value=str(self.game_path)))
        self.stack.enter_context(patch.object(config, "config_path", str(self.scanner_path)))
        self.stack.enter_context(patch.object(config, "_repository", None))
        self.stack.enter_context(patch.object(config, "user_config", deepcopy(config.user_config)))
        for name in (
            "HOTKEY", "RESET_HOTKEY", "PLAYER_STATS_RECORD_HOTKEY", "IN_GAME_OVERLAY_EDIT_HOTKEY",
            "AUTO_START_RECORDING", "SHOW_OBS_REMINDER_ON_START_SCANNER",
            "STOP_SCANNING_ON_PLAYER_MOVEMENT", "PLAYER_STATS_RECORD_INTERVAL_SECONDS",
            "RESET_HOLD_DURATION", "RESET_HOLD_SAFETY_MARGIN", "GAME_RESET_HOLD_FLOOR",
            "RESET_HOLD_DURATION_RAISED_FROM", "RESET_HOLD_SYNC_WARNING",
        ):
            self.stack.enter_context(patch.object(config, name, getattr(config, name)))

    def write_game(self, value):
        self.game_path.write_text(json.dumps({
            "cfGameSettings": {"quick_reset_time": value, "other_setting": True},
            "unrelated": [1, 2, 3],
        }), encoding="utf-8")

    def make_dialog(self, game=0.20, hold=0.25, margin=0.05):
        self.write_game(game)
        config.RESET_HOLD_DURATION = hold
        config.RESET_HOLD_SAFETY_MARGIN = margin
        config.user_config.update(RESET_HOLD_DURATION=hold, RESET_HOLD_SAFETY_MARGIN=margin)
        self.scanner_path.write_text(json.dumps(config.user_config), encoding="utf-8")
        master = SimpleNamespace(is_game_running=lambda: self.running)
        dialog = SettingsDialog(None, master=master)
        self.notice = self.stack.enter_context(patch.object(SettingsDialog, "_show_game_reset_notice"))
        self.addCleanup(dialog.close)
        return dialog

    def test_margin_increase_extends_hold_without_writing_open_game(self):
        self.running = True
        dialog = self.make_dialog()
        original = self.game_path.read_bytes()
        dialog.reset_hold_safety_margin_entry.setValue(0.07)
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.27)
        self.assertIn("0.20 s (unchanged)", dialog.reset_game_after_label.text())
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertEqual(self.game_path.read_bytes(), original)
        self.assertEqual(json.loads(self.scanner_path.read_text())["RESET_HOLD_DURATION"], 0.27)
        self.notice.assert_not_called()
        self.assertEqual(dialog.reset_timing_status_label.text(), "✓  Saved.")

    def test_save_from_support_keeps_edits_from_general_and_restart(self):
        dialog = self.make_dialog()
        original_game = self.game_path.read_bytes()
        dialog.hotkey_entry.setText("f10")
        dialog.hotkey_entry.textEdited.emit("f10")
        dialog.show_page("restart")
        dialog.reset_hold_safety_margin_entry.setValue(0.07)
        dialog.show_page("support")
        self.assertEqual(dialog.save_btn.text(), "Save changes")
        dialog._on_primary_action()
        saved = json.loads(self.scanner_path.read_text())
        self.assertEqual(saved["HOTKEY"], "f10")
        self.assertEqual(saved["RESET_HOLD_DURATION"], 0.27)
        self.assertEqual(saved["RESET_HOLD_SAFETY_MARGIN"], 0.07)
        self.assertEqual(self.game_path.read_bytes(), original_game)

    def test_restart_primary_action_saves_even_without_edits(self):
        dialog = self.make_dialog()
        dialog.show_page("restart")
        self.assertIs(dialog.settings_tabs.currentWidget(), dialog.restart_settings_page)
        with patch.object(dialog, "save", wraps=dialog.save) as save:
            dialog._on_primary_action()
        save.assert_called_once_with()

    def test_tab_switches_preserve_reset_draft_and_refresh_game_status(self):
        self.running = True
        dialog = self.make_dialog()
        dialog.show_page("restart")
        dialog.reset_hold_duration_entry.setValue(0.15)
        original = self.scanner_path.read_bytes(), self.game_path.read_bytes()
        self.assertIn("Close Megabonk", dialog.reset_timing_status_label.text())
        dialog.show_page("general")
        self.running = False
        dialog._refresh_live_reset_timing()
        dialog.show_page("restart")
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.15)
        self.assertIn("0.20 s → 0.10 s", dialog.reset_game_after_label.text())
        self.assertNotIn("Close Megabonk", dialog.reset_timing_status_label.text())
        self.assertEqual((self.scanner_path.read_bytes(), self.game_path.read_bytes()), original)
        dialog._on_primary_action()
        self.assertEqual(json.loads(self.game_path.read_text())["cfGameSettings"]["quick_reset_time"], 0.10)

    def test_cancel_and_reload_discard_edits_from_both_editable_pages(self):
        dialog = self.make_dialog()
        original = self.scanner_path.read_bytes(), self.game_path.read_bytes()
        dialog.hotkey_entry.setText("f10")
        dialog.show_page("restart")
        dialog.reset_hold_safety_margin_entry.setValue(0.07)
        dialog.reject()
        dialog.reload_from_config()
        self.assertEqual(dialog.hotkey_entry.text(), config.HOTKEY)
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.25)
        self.assertEqual(dialog.reset_hold_safety_margin_entry.value(), 0.05)
        self.assertFalse(dialog._general_settings_dirty)
        self.assertEqual(dialog.save_btn.text(), "Save")
        self.assertEqual((self.scanner_path.read_bytes(), self.game_path.read_bytes()), original)

    def test_margin_preserves_a_planned_lower_game_threshold(self):
        dialog = self.make_dialog()
        dialog.reset_hold_duration_entry.setValue(0.15)
        dialog.reset_hold_safety_margin_entry.setValue(0.07)
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.17)
        self.assertIn("0.20 s → 0.10 s", dialog.reset_game_after_label.text())
        self.assertTrue(dialog.save(close_dialog=False))
        game = json.loads(self.game_path.read_text())
        self.assertEqual(game["cfGameSettings"]["quick_reset_time"], 0.10)
        self.assertTrue(game["cfGameSettings"]["other_setting"])
        self.assertEqual(game["unrelated"], [1, 2, 3])

    def test_lowering_margin_shortens_hold_and_preserves_deliberate_extra(self):
        dialog = self.make_dialog(hold=0.35)
        dialog.reset_hold_safety_margin_entry.setValue(0.03)
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.33)
        self.assertIn("0.13 s", dialog.reset_timing_limits_label.text())
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertEqual(json.loads(self.game_path.read_text())["cfGameSettings"]["quick_reset_time"], 0.20)

    def test_margin_uses_external_game_change_even_before_the_next_poll(self):
        dialog = self.make_dialog()
        self.write_game(0.30)
        dialog.reset_hold_safety_margin_entry.setValue(0.07)
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.37)
        self.assertIn("unchanged", dialog.reset_game_after_label.text())
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertEqual(json.loads(self.game_path.read_text())["cfGameSettings"]["quick_reset_time"], 0.30)

    def test_close_game_status_refresh_preserves_draft_and_does_not_write(self):
        self.running = True
        dialog = self.make_dialog()
        original = self.scanner_path.read_bytes(), self.game_path.read_bytes()
        dialog.reset_hold_duration_entry.setValue(0.15)
        self.assertIn("Close Megabonk", dialog.reset_timing_status_label.text())
        self.running = False
        dialog._refresh_live_reset_timing()
        self.assertNotIn("Close Megabonk", dialog.reset_timing_status_label.text())
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.15)
        self.assertEqual((self.scanner_path.read_bytes(), self.game_path.read_bytes()), original)

    def test_save_rechecks_game_running_and_keeps_all_edits_on_failure(self):
        dialog = self.make_dialog()
        original = self.scanner_path.read_bytes(), self.game_path.read_bytes()
        dialog.reset_hold_duration_entry.setValue(0.15)
        dialog.hotkey_entry.setText("f10")
        self.running = True
        self.assertFalse(dialog.save(close_dialog=False))
        self.assertEqual(dialog.hotkey_entry.text(), "f10")
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.15)
        self.assertEqual((self.scanner_path.read_bytes(), self.game_path.read_bytes()), original)
        self.assertEqual(dialog.reset_timing_status_label.property("tone"), "warning")

    def test_unreadable_game_blocks_timing_edits_but_allows_unrelated_settings(self):
        dialog = self.make_dialog()
        original = self.scanner_path.read_bytes()
        self.game_path.write_text("invalid JSON", encoding="utf-8")
        dialog.reset_hold_duration_entry.setValue(0.15)
        self.assertFalse(dialog.save(close_dialog=False))
        self.assertEqual(self.scanner_path.read_bytes(), original)
        dialog.reset_hold_duration_entry.setValue(0.25)
        dialog.hotkey_entry.setText("f10")
        self.notice.reset_mock()
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertEqual(json.loads(self.scanner_path.read_text())["HOTKEY"], "f10")
        self.assertEqual(self.game_path.read_text(), "invalid JSON")
        self.notice.assert_not_called()

    def test_poll_updates_runtime_correction_without_marking_an_edit(self):
        dialog = self.make_dialog()
        config.RESET_HOLD_DURATION = 0.35
        dialog._refresh_live_reset_timing()
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.35)
        self.assertEqual(dialog._initial_reset_hold_duration, 0.35)
        self.assertFalse(dialog._general_settings_dirty)
        self.assertFalse(dialog._reset_timing_is_edited())

    def test_poll_preserves_uncommitted_typed_number(self):
        dialog = self.make_dialog()
        edit = dialog.reset_hold_duration_entry.lineEdit()
        edit.setText("0.1")
        edit.setModified(True)
        draft_text = edit.text()  # Qt may insert the spinbox suffix immediately.
        config.RESET_HOLD_DURATION = 0.35
        dialog._refresh_live_reset_timing()
        self.assertEqual(edit.text(), draft_text)

    def test_preview_and_save_agree_on_live_timing_while_equivalent_input_is_typed(self):
        dialog = self.make_dialog()
        edit = dialog.reset_hold_duration_entry.lineEdit()
        edit.setText("0.25")
        edit.setModified(True)
        draft_text = edit.text()
        config.RESET_HOLD_DURATION = 0.35
        config.user_config["RESET_HOLD_DURATION"] = 0.35
        dialog._refresh_live_reset_timing()
        self.assertEqual(edit.text(), draft_text)
        self.assertEqual(dialog.reset_hold_after_label.text(), "0.35 s")
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertEqual(json.loads(self.scanner_path.read_text())["RESET_HOLD_DURATION"], 0.35)
        self.notice.assert_not_called()

    def test_reload_does_not_apply_the_margin_delta_to_saved_hold(self):
        dialog = self.make_dialog()
        dialog.reset_hold_safety_margin_entry.setValue(0.07)
        config.RESET_HOLD_DURATION = 0.40
        config.RESET_HOLD_SAFETY_MARGIN = 0.02
        dialog.reload_from_config()
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.40)
        self.assertEqual(dialog.reset_hold_safety_margin_entry.value(), 0.02)
        self.assertFalse(dialog._reset_timing_is_edited())

    def test_timer_runs_only_while_settings_is_visible_and_focus_refreshes(self):
        dialog = self.make_dialog()
        self.assertFalse(dialog.reset_timing_timer.isActive())
        dialog.show()
        self.assertTrue(dialog.reset_timing_timer.isActive())
        self.write_game(0.10)
        QApplication.sendEvent(dialog, QEvent(QEvent.WindowActivate))
        self.assertEqual(dialog.reset_game_value_label.text(), "0.10 s")
        dialog.hide()
        self.assertFalse(dialog.reset_timing_timer.isActive())

    def test_maximum_hold_rejects_margin_that_cannot_preserve_game_threshold(self):
        dialog = self.make_dialog(game=9.95, hold=10.0)
        dialog.reset_hold_safety_margin_entry.setValue(0.10)
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 10.0)
        self.assertEqual(dialog.reset_hold_safety_margin_entry.value(), 0.05)
        self.assertIn("not changed", dialog.reset_timing_status_label.text())

    def test_below_minimum_input_is_preserved_and_explained(self):
        dialog = self.make_dialog()
        entry = dialog.reset_hold_duration_entry
        entry.lineEdit().setText("0.01")
        entry.lineEdit().textEdited.emit("0.01")
        entry.interpretText()
        entry.editingFinished.emit()
        self.assertEqual(entry.value(), 0.01)
        self.assertIn("Minimum 0.06 s", dialog.reset_timing_status_label.text())
        self.assertFalse(dialog.save_btn.isEnabled())

    def test_safe_live_correction_survives_failed_persistence_rollback(self):
        self.make_dialog()
        self.write_game(0.40)

        def failed_save(_payload):
            config.RESET_HOLD_DURATION = 0.25  # Simulate repository runtime rollback.
            config.RESET_HOLD_SAFETY_MARGIN = 0.01
            config.GAME_RESET_HOLD_FLOOR = 0.41
            return config.ConfigSaveResult(False, "disk unavailable")

        with patch.object(config, "save_config", side_effect=failed_save):
            self.assertEqual(config.refresh_reset_hold_duration(), 0.25)
        self.assertEqual(config.RESET_HOLD_DURATION, 0.45)
        self.assertEqual(config.RESET_HOLD_SAFETY_MARGIN, 0.05)
        self.assertEqual(config.GAME_RESET_HOLD_FLOOR, 0.45)
        self.assertEqual(config.user_config["RESET_HOLD_DURATION"], 0.45)
        self.assertIn("could not be saved", config.RESET_HOLD_SYNC_WARNING)

    def test_verified_game_value_is_reported_even_when_file_changes_before_save(self):
        dialog = self.make_dialog(hold=0.35)
        dialog.reset_hold_duration_entry.setValue(0.30)
        original_save = config.save_settings_with_game_reset

        def save_after_game_change(*args, **kwargs):
            self.write_game(0.10)
            return original_save(*args, **kwargs)

        with patch.object(config, "save_settings_with_game_reset", side_effect=save_after_game_change):
            self.assertTrue(dialog.save(close_dialog=False))
        self.assertEqual(dialog.reset_game_value_label.text(), "0.10 s")

    def test_invalid_draft_survives_poll_and_tab_switch_and_cannot_save(self):
        dialog = self.make_dialog(game=0.01, hold=0.06)
        original = self.scanner_path.read_bytes(), self.game_path.read_bytes()
        entry = dialog.reset_hold_duration_entry
        entry.setText("0.04")
        entry.textEdited.emit("0.04")
        dialog._refresh_live_reset_timing()
        dialog.show_page("support")
        self.assertEqual(entry.text(), "0.04")
        self.assertFalse(dialog.save_btn.isEnabled())
        self.assertEqual(dialog.reset_timing_status_label.property("tone"), "error")
        self.assertFalse(dialog.save(close_dialog=False))
        self.assertEqual((self.scanner_path.read_bytes(), self.game_path.read_bytes()), original)

    def test_initial_hint_and_save_confirmation_survives_polling(self):
        dialog = self.make_dialog()
        dialog.show_page("restart")
        dialog.show()
        self.app.processEvents()
        status = dialog.reset_timing_status_label
        self.assertEqual(status.text(), "")
        self.assertFalse(status.isVisible())
        self.assertTrue(dialog.reset_timing_hint.isVisible())
        self.assertEqual(status.property("tone"), "neutral")
        dialog.reset_hold_duration_entry.setValue(0.30)
        self.assertTrue(dialog.save_btn.isEnabled())
        self.assertTrue(dialog.save(close_dialog=False))
        dialog._refresh_live_reset_timing()
        self.app.processEvents()
        self.assertEqual(status.text(), "✓  Saved.")
        self.assertEqual(status.property("tone"), "success")
        self.assertTrue(status.isVisible())
        dialog.reset_hold_duration_entry.setValue(0.35)
        self.assertIn("Ready to save", status.text())

    def test_status_transitions_and_game_close_enable_save(self):
        dialog = self.make_dialog()
        self.assertEqual(dialog.reset_timing_status_label.property("tone"), "neutral")
        dialog.reset_hold_duration_entry.setValue(0.35)
        self.assertEqual(dialog.reset_timing_status_label.property("tone"), "success")
        self.running = True
        dialog.reset_hold_duration_entry.setValue(0.15)
        self.assertEqual(dialog.reset_timing_status_label.property("tone"), "warning")
        self.assertFalse(dialog.save_btn.isEnabled())
        self.running = False
        dialog._refresh_live_reset_timing()
        self.assertTrue(dialog.save_btn.isEnabled())
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertEqual(dialog.reset_timing_status_label.text(), "✓  Saved.")

    def test_incomplete_input_waits_for_blur_and_is_never_saved(self):
        dialog = self.make_dialog()
        entry = dialog.reset_hold_duration_entry
        entry.setText("0.")
        entry.textEdited.emit("0.")
        self.assertEqual(dialog.reset_timing_status_label.property("tone"), "neutral")
        self.assertFalse(dialog.save_btn.isEnabled())
        entry.editingFinished.emit()
        self.assertEqual(dialog.reset_timing_status_label.property("tone"), "error")
        self.assertFalse(dialog.save(close_dialog=False))

    def test_margin_does_not_replace_invalid_hold_draft(self):
        dialog = self.make_dialog()
        dialog.reset_hold_duration_entry.setText("oops")
        dialog.reset_hold_safety_margin_entry.setValue(0.07)
        self.assertEqual(dialog.reset_hold_duration_entry.text(), "oops")
        self.assertFalse(dialog.save(close_dialog=False))

    def test_recommendations_preserve_general_draft_and_other_game_keys(self):
        dialog = self.make_dialog()
        old_hotkey = config.HOTKEY
        dialog.hotkey_entry.setText("f10")
        dialog.hotkey_entry.textEdited.emit("f10")
        with patch("ui.dialogs.ask_app_confirmation", return_value=True):
            dialog._apply_recommended_reset_timing()
        self.assertEqual(dialog.hotkey_entry.text(), "f10")
        self.assertEqual(config.HOTKEY, old_hotkey)
        saved = json.loads(self.scanner_path.read_text())
        self.assertEqual(saved["HOTKEY"], old_hotkey)
        self.assertEqual(saved["RESET_HOLD_DURATION"], 0.06)
        self.assertFalse(saved["RESET_TIMING_SETUP_PENDING"])
        game = json.loads(self.game_path.read_text())
        self.assertEqual(game["cfGameSettings"], {"quick_reset_time": 0.01, "other_setting": True})
        self.assertEqual(game["unrelated"], [1, 2, 3])
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertEqual(json.loads(self.scanner_path.read_text())["HOTKEY"], "f10")

    def test_recommendations_cancel_and_running_game_do_not_write(self):
        dialog = self.make_dialog()
        original = self.scanner_path.read_bytes(), self.game_path.read_bytes()
        with patch("ui.dialogs.ask_app_confirmation", return_value=False):
            dialog._apply_recommended_reset_timing()
        self.running = True
        with patch("ui.dialogs.ask_app_confirmation", return_value=True):
            dialog._apply_recommended_reset_timing()
        self.assertEqual((self.scanner_path.read_bytes(), self.game_path.read_bytes()), original)
        self.assertEqual(dialog.reset_timing_status_label.property("tone"), "warning")

    def test_recommendations_at_game_minimum_work_while_running(self):
        self.make_dialog(game=0.01, hold=0.25)
        original_game = self.game_path.read_bytes()
        result = config.apply_recommended_reset_timing(lambda: (True, ""))
        self.assertTrue(result.success)
        self.assertEqual(config.RESET_HOLD_DURATION, 0.06)
        self.assertEqual(self.game_path.read_bytes(), original_game)

    def test_recommendation_failure_preserves_runtime_and_scanner_config(self):
        self.make_dialog()
        original = self.scanner_path.read_bytes()
        with patch.object(config, "update_game_reset_time", return_value=config.GameConfigUpdateResult(False, "locked")):
            result = config.apply_recommended_reset_timing(lambda: (False, ""))
        self.assertFalse(result.success)
        self.assertEqual(config.RESET_HOLD_DURATION, 0.25)
        self.assertEqual(json.loads(self.scanner_path.read_text()), json.loads(original))

    def test_explicit_timing_save_cancels_pending_first_launch_recommendation(self):
        dialog = self.make_dialog()
        config.user_config["RESET_TIMING_SETUP_PENDING"] = True
        dialog.reset_hold_duration_entry.setValue(0.30)
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertFalse(config.user_config["RESET_TIMING_SETUP_PENDING"])

    def test_write_failure_remains_red_after_poll_and_keeps_draft(self):
        report = SettingsDialog._show_game_reset_notice
        dialog = self.make_dialog()
        dialog.reset_hold_duration_entry.setValue(0.35)
        with patch.object(SettingsDialog, "_show_game_reset_notice", side_effect=report), patch.object(
            config, "save_settings_with_game_reset",
            return_value=config.SettingsSaveResult(False, "Disk is read-only"),
        ):
            self.assertFalse(dialog.save(close_dialog=False))
        dialog._refresh_live_reset_timing()
        self.assertEqual(dialog.reset_timing_status_label.property("tone"), "error")
        self.assertIn("Disk is read-only", dialog.reset_timing_status_label.text())
        self.assertEqual(dialog.reset_hold_duration_entry.value(), 0.35)
        self.assertEqual(config.RESET_HOLD_DURATION, 0.25)

    def test_recommendations_do_not_write_if_process_detection_fails(self):
        self.make_dialog()
        original = self.scanner_path.read_bytes(), self.game_path.read_bytes()
        result = config.apply_recommended_reset_timing(lambda: (False, "Process list unavailable"))
        self.assertFalse(result.success)
        self.assertEqual((self.scanner_path.read_bytes(), self.game_path.read_bytes()), original)

    def test_hint_is_replaced_only_for_timing_edits(self):
        dialog = self.make_dialog(game=0.01, hold=0.06)
        dialog.show_page("restart")
        dialog.show()
        self.app.processEvents()
        self.assertTrue(dialog.reset_timing_hint.isVisible())
        self.assertFalse(dialog.reset_timing_status_label.isVisible())
        self.assertFalse(dialog.reset_hold_safety_margin_entry.isVisible())
        dialog.hotkey_entry.setText("f10")
        dialog.hotkey_entry.textEdited.emit("f10")
        self.assertTrue(dialog.reset_timing_hint.isVisible())
        self.assertFalse(dialog.reset_timing_status_label.isVisible())
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertTrue(dialog.reset_timing_hint.isVisible())
        dialog.reset_hold_duration_entry.setValue(0.10)
        self.assertFalse(dialog.reset_timing_hint.isVisible())
        self.assertTrue(dialog.reset_timing_status_label.isVisible())
        dialog.reset_hold_duration_entry.setText("oops")
        dialog.reset_hold_duration_entry.textEdited.emit("oops")
        self.assertEqual(dialog.reset_timing_status_label.property("tone"), "error")
        self.assertFalse(dialog.reset_timing_hint.isVisible())

    def test_movement_guard_saves_from_restart_without_changing_game_config(self):
        dialog = self.make_dialog()
        original_game = self.game_path.read_bytes()
        dialog.show_page("restart")
        checkbox = dialog.stop_scanning_on_player_movement_var
        expected = not checkbox.isChecked()
        checkbox.click()
        dialog.show_page("general")
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertEqual(config.STOP_SCANNING_ON_PLAYER_MOVEMENT, expected)
        self.assertEqual(json.loads(self.scanner_path.read_text())["STOP_SCANNING_ON_PLAYER_MOVEMENT"], expected)
        self.assertEqual(self.game_path.read_bytes(), original_game)

    def test_general_edit_after_save_restores_passive_hint(self):
        dialog = self.make_dialog()
        dialog.reset_hold_duration_entry.setValue(0.35)
        self.assertTrue(dialog.save(close_dialog=False))
        self.assertEqual(dialog.reset_timing_status_label.text(), "✓  Saved.")
        dialog.hotkey_entry.setText("f10")
        dialog.hotkey_entry.textEdited.emit("f10")
        self.assertEqual(dialog.reset_timing_status_label.text(), "")


class ResetTimingNoticeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_scanner_only_notice_is_nonmodal_and_releases_after_timeout(self):
        dialog = MagicMock()
        with patch("ui.dialogs.GameResetTimeNoticeDialog", return_value=dialog), patch(
            "ui.dialogs.QTimer.singleShot"
        ) as timer:
            SettingsDialog._show_game_reset_notice(None, saved=True, game_updated=False)
        dialog.setModal.assert_called_once_with(False)
        dialog.show.assert_called_once_with()
        dialog.exec.assert_not_called()
        timer.call_args.args[1]()
        dialog.deleteLater.assert_called_once_with()

    def test_notice_distinguishes_selected_minimum_and_actual_extra_hold(self):
        dialog = GameResetTimeNoticeDialog(
            None, saved=True, scanner_hold=0.35, game_value=0.20, margin=0.05,
            game_updated=False,
        )
        self.addCleanup(dialog.close)
        text = " ".join(label.text() for label in dialog.findChildren(QLabel))
        self.assertIn("0.15 s", text)
        self.assertIn("0.05 s", text)
        self.assertIn("next reset", text)


if __name__ == "__main__":
    unittest.main()
