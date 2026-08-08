from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401
from PySide6.QtWidgets import QApplication, QAbstractSpinBox

from app import config
from ui.dialogs import SettingsDialog


class SettingsResetHoldInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_player_movement_guard_checkbox_reflects_config(self) -> None:
        with patch.object(config, "STOP_SCANNING_ON_PLAYER_MOVEMENT", False):
            dialog = SettingsDialog(None, master=MagicMock())
        self.addCleanup(dialog.close)

        checkbox = dialog.stop_scanning_on_player_movement_var
        self.assertEqual(checkbox.text(), "Stop scanning when player moves")
        self.assertFalse(checkbox.isChecked())

    def test_a_value_below_the_minimum_clamps_instead_of_restoring_the_old_value(
        self,
    ) -> None:
        with patch.object(config, "RESET_HOLD_DURATION", 0.50):
            dialog = SettingsDialog(None, master=MagicMock())
        self.addCleanup(dialog.close)
        entry = dialog.reset_hold_duration_entry

        self.assertEqual(
            entry.correctionMode(),
            QAbstractSpinBox.CorrectionMode.CorrectToNearestValue,
        )
        entry.lineEdit().setText("0.05")
        entry.interpretText()

        self.assertEqual(entry.value(), config.MIN_RESET_HOLD_DURATION)
        self.assertEqual(entry.text(), "0.10 s")


if __name__ == "__main__":
    unittest.main()
