from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QScrollArea, QWidget

import gui_app
from app import config
from gui_app import MegabonkApp


class _SettingsOwner:
    open_settings_dialog = MegabonkApp.open_settings_dialog
    _settings_dialog_destroyed = MegabonkApp._settings_dialog_destroyed
    open_help_dialog = MegabonkApp.open_help_dialog
    _log_dialog_failure = MegabonkApp._log_dialog_failure

    def __init__(self) -> None:
        self.window = QWidget()
        self._settings_dialog = None
        self.logs: list[tuple[str, str | None]] = []

    def log(self, message: str, tag: str | None = None) -> None:
        self.logs.append((message, tag))


class _SettingsDialogProbe(QDialog):
    instances: list["_SettingsDialogProbe"] = []

    def __init__(self, parent, *, master) -> None:
        super().__init__(parent)
        self.master = master
        self.open_calls = 0
        self.raise_calls = 0
        self.activate_calls = 0
        self.reload_calls = 0
        self.page_calls = []
        self.instances.append(self)

    def exec(self) -> int:
        raise AssertionError("Settings must not use a nested QDialog.exec() loop")

    def open(self) -> None:
        self.open_calls += 1
        super().open()

    def raise_(self) -> None:
        self.raise_calls += 1
        super().raise_()

    def activateWindow(self) -> None:
        self.activate_calls += 1
        super().activateWindow()

    def reload_from_config(self) -> None:
        self.reload_calls += 1

    def show_page(self, page: str) -> None:
        self.page_calls.append(page)


class SettingsDialogLifecycleTests(unittest.TestCase):
    _keepalive: list[_SettingsOwner] = []

    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        _SettingsDialogProbe.instances.clear()
        original_user_config = dict(config.user_config)
        original_values = {
            name: getattr(config, name)
            for name in (
                "HOTKEY",
                "RESET_HOTKEY",
                "PLAYER_STATS_RECORD_HOTKEY",
                "IN_GAME_OVERLAY_EDIT_HOTKEY",
                "AUTO_START_RECORDING",
                "SHOW_OBS_REMINDER_ON_START_SCANNER",
                "STOP_SCANNING_ON_PLAYER_MOVEMENT",
                "RESET_HOLD_DURATION",
                "PLAYER_STATS_RECORD_INTERVAL_SECONDS",
            )
        }
        self.addCleanup(config.user_config.update, original_user_config)
        self.addCleanup(config.user_config.clear)
        for name, value in original_values.items():
            self.addCleanup(setattr, config, name, value)
        self.owner = _SettingsOwner()

    def tearDown(self) -> None:
        dialog = self.owner._settings_dialog
        if dialog is not None:
            dialog.close()
        self.owner.window.close()
        # Match production ownership: the application and its one reusable
        # settings dialog live until process shutdown. A global DeferredDelete
        # flush here would also execute unrelated Qt deletions from other tests.
        self._keepalive.append(self.owner)

    def test_one_dialog_is_reused_until_qt_destroys_it(self) -> None:
        with patch.object(gui_app, "SettingsDialog", _SettingsDialogProbe):
            self.owner.open_settings_dialog()
            dialog = self.owner._settings_dialog

            self.assertIsInstance(dialog, _SettingsDialogProbe)
            self.assertIs(dialog.master, self.owner)
            self.assertEqual(dialog.open_calls, 1)

            self.owner.open_settings_dialog()
            self.assertEqual(len(_SettingsDialogProbe.instances), 1)
            self.assertEqual(dialog.raise_calls, 1)
            self.assertEqual(dialog.activate_calls, 1)

            dialog.reject()
            self.assertIs(self.owner._settings_dialog, dialog)

            self.owner.open_settings_dialog()
            self.assertIs(self.owner._settings_dialog, dialog)
            self.assertEqual(len(_SettingsDialogProbe.instances), 1)
            self.assertEqual(dialog.reload_calls, 1)
            self.assertEqual(dialog.open_calls, 2)

    def test_failed_reuse_is_replaced_without_old_destroyed_clearing_new(self) -> None:
        with patch.object(gui_app, "SettingsDialog", _SettingsDialogProbe):
            self.owner.open_settings_dialog()
            first = self.owner._settings_dialog
            first.reject()
            first.reload_from_config = MagicMock(
                side_effect=RuntimeError("native handle was deleted")
            )
            first.deleteLater = MagicMock()

            self.owner.open_settings_dialog()
            replacement = self.owner._settings_dialog
            self.owner._settings_dialog_destroyed(first)

        self.assertIsNot(replacement, first)
        self.assertIs(self.owner._settings_dialog, replacement)
        first.deleteLater.assert_called_once_with()
        self.assertTrue(any("native handle was deleted" in text for text, _ in self.owner.logs))

    def test_page_request_reaches_new_and_visible_settings_dialog(self) -> None:
        with patch.object(gui_app, "SettingsDialog", _SettingsDialogProbe):
            self.owner.open_settings_dialog(page="support")
            dialog = self.owner._settings_dialog
            self.assertEqual(dialog.page_calls, ["support"])

            self.owner.open_settings_dialog(page="support")
            self.assertEqual(dialog.page_calls, ["support", "support"])
            self.assertEqual(dialog.raise_calls, 1)

    def test_help_dialog_is_deleted_after_its_modal_session(self) -> None:
        dialog = MagicMock()
        with patch.object(gui_app, "HelpDialog", return_value=dialog):
            self.owner.open_help_dialog()

        dialog.exec.assert_called_once_with()
        dialog.deleteLater.assert_called_once_with()

    def test_real_widgets_survive_repeated_save_and_cancel_cycles(self) -> None:
        game_value = config.reset_hold_duration_to_game_value(
            config.RESET_HOLD_DURATION,
            safety_margin=config.RESET_HOLD_SAFETY_MARGIN,
        )
        # This is a widget-lifecycle test, so keep it independent of the real
        # Megabonk config on the machine running the suite. A mismatched or
        # missing game file opens the intentional modal result notice and makes
        # this offscreen loop wait for user input; the real persistence path has
        # dedicated transaction tests.
        with patch.object(
            config,
            "read_game_quick_reset_time",
            return_value=config.GameConfigReadResult(True, value=game_value),
        ), patch.object(
            config,
            "save_settings_with_game_reset",
            return_value=config.SettingsSaveResult(True),
        ):
            for cycle in range(100):
                self.owner.open_settings_dialog()
                dialog = self.owner._settings_dialog
                self.assertIsNotNone(dialog)

                if cycle % 2:
                    dialog.auto_start_recording_var.setChecked(False)
                    dialog.save()
                else:
                    dialog.hotkey_entry.setText("discard me")
                    dialog.reject()

                QApplication.processEvents()
                self.assertIs(self.owner._settings_dialog, dialog, cycle)

                self.owner.open_settings_dialog()
                self.assertIs(self.owner._settings_dialog, dialog, cycle)
                self.assertEqual(dialog.hotkey_entry.text(), str(config.HOTKEY))
                dialog.reject()

    def test_snapshot_interval_control_accepts_then_clamps_subminimum_input(self) -> None:
        self.owner.open_settings_dialog()
        dialog = self.owner._settings_dialog

        self.assertIsNotNone(dialog)
        dialog.record_interval_entry.setFocus()
        dialog.record_interval_entry.lineEdit().selectAll()
        QTest.keyClicks(dialog.record_interval_entry, "5")

        # Keeping the editor's technical range at 10 rejects the single-digit
        # intermediate text and can merge it with the old value (for example,
        # 5 + 0 -> 50). Let the user finish typing, then apply the real minimum.
        self.assertEqual(dialog.record_interval_entry.lineEdit().text(), "5 s")
        self.assertEqual(dialog.record_interval_entry.value(), 5)
        dialog.record_interval_entry.editingFinished.emit()

        self.assertEqual(
            dialog.record_interval_entry.value(),
            config.MIN_RECORDING_SNAPSHOT_INTERVAL_SECONDS,
        )

    def test_support_page_and_general_both_expose_support_routes(self) -> None:
        self.owner.open_settings_dialog()
        dialog = self.owner._settings_dialog
        self.assertIsNotNone(dialog)
        dialog.show()
        QApplication.processEvents()

        self.assertEqual(
            [
                dialog.settings_tabs.tabText(index)
                for index in range(dialog.settings_tabs.count())
            ],
            ["General", "Support"],
        )
        self.assertIsNone(
            dialog.general_settings_page.findChild(QWidget, "SupporterAccessCard")
        )
        self.assertIsNotNone(
            dialog.supporter_access_page.findChild(QWidget, "SupporterAccessCard")
        )
        self.assertTrue(dialog.general_settings_page.isAncestorOf(dialog.patreon_btn))
        for button in (
            dialog.patreon_btn,
            dialog.crypto_btn,
            dialog.github_btn,
            dialog.discord_btn,
        ):
            self.assertEqual(button.property("settingsSupportAction"), "true")
            self.assertGreater(button.width(), 104)
            self.assertEqual(button.height(), 32)
            self.assertEqual(
                (button.iconSize().width(), button.iconSize().height()),
                (16, 16),
            )
        self.assertTrue(
            dialog.supporter_access_page.isAncestorOf(
                dialog.supporter_access_page.patreon_btn
            )
        )
        self.assertNotEqual(
            dialog.patreon_btn,
            dialog.supporter_access_page.patreon_btn,
        )
        self.assertEqual(
            dialog.supporter_access_page.patreon_btn.objectName(),
            "SupportPatreonPrimary",
        )
        self.assertEqual(
            dialog.supporter_access_page.github_btn.objectName(),
            "SupportSecondaryLink",
        )

        dialog.settings_tabs.setCurrentWidget(dialog.supporter_access_page)
        QApplication.processEvents()
        self.assertEqual(dialog.save_btn.text(), "Done")
        self.assertFalse(dialog.cancel_btn.isVisible())

        dialog.settings_tabs.setCurrentWidget(dialog.general_settings_page)
        QApplication.processEvents()
        self.assertEqual(dialog.save_btn.text(), "Save")
        self.assertTrue(dialog.cancel_btn.isVisible())

    def test_settings_navigation_replaces_title_and_frees_general_page_height(self) -> None:
        self.owner.open_settings_dialog()
        dialog = self.owner._settings_dialog
        dialog.setStyleSheet(
            (Path(__file__).resolve().parents[1] / "media" / "bonkscanner_theme.qss").read_text(
                encoding="utf-8"
            )
        )
        dialog.resize(560, 720)
        dialog.show()
        QApplication.processEvents()

        self.assertIsNone(dialog.findChild(QLabel, "dialogTitle"))
        self.assertFalse(dialog.settings_header_tabs.isHidden())
        self.assertTrue(dialog.settings_tabs.tabBar().isHidden())
        self.assertEqual(
            [
                dialog.settings_header_tabs.tabText(index)
                for index in range(dialog.settings_header_tabs.count())
            ],
            ["General", "Support"],
        )
        dialog.settings_header_tabs.setCurrentIndex(1)
        QApplication.processEvents()
        self.assertIs(
            dialog.settings_tabs.currentWidget(),
            dialog.supporter_access_page,
        )
        dialog.settings_header_tabs.setCurrentIndex(0)
        QApplication.processEvents()
        self.assertIs(
            dialog.settings_tabs.currentWidget(),
            dialog.general_settings_page,
        )
        settings_scroll = dialog.findChild(QScrollArea, "SettingsScroll")
        self.assertFalse(settings_scroll.verticalScrollBar().isVisible())

    def test_support_does_not_silently_discard_general_edits(self) -> None:
        self.owner.open_settings_dialog()
        dialog = self.owner._settings_dialog
        dialog.show()
        QApplication.processEvents()

        dialog.hotkey_entry.textEdited.emit("f7")
        dialog.settings_tabs.setCurrentWidget(dialog.supporter_access_page)
        QApplication.processEvents()

        self.assertEqual(dialog.save_btn.text(), "Save changes")
        self.assertTrue(dialog.cancel_btn.isVisible())

        dialog.reload_from_config()
        self.assertEqual(dialog.save_btn.text(), "Done")
        self.assertFalse(dialog.cancel_btn.isVisible())


if __name__ == "__main__":
    unittest.main()
