from __future__ import annotations

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401
from PySide6.QtWidgets import QApplication, QDialog, QWidget

import gui_app
from app import config
from gui_app import MegabonkApp


class _SettingsOwner:
    open_settings_dialog = MegabonkApp.open_settings_dialog
    _settings_dialog_destroyed = MegabonkApp._settings_dialog_destroyed

    def __init__(self) -> None:
        self.window = QWidget()
        self._settings_dialog = None


class _SettingsDialogProbe(QDialog):
    instances: list["_SettingsDialogProbe"] = []

    def __init__(self, parent, *, master) -> None:
        super().__init__(parent)
        self.master = master
        self.open_calls = 0
        self.raise_calls = 0
        self.activate_calls = 0
        self.reload_calls = 0
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

    def test_real_widgets_survive_repeated_save_and_cancel_cycles(self) -> None:
        with patch.object(config, "save_config"):
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


if __name__ == "__main__":
    unittest.main()
