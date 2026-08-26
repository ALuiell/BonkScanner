from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401
from PySide6.QtWidgets import QApplication, QAbstractSpinBox

from app import config
from ui import dialogs as dialogs_module
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

    def test_support_routes_include_the_crypto_page_button(self) -> None:
        dialog = SettingsDialog(None, master=MagicMock())
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.crypto_btn.text(), "Crypto")
        self.assertEqual(dialog.crypto_btn.objectName(), "CryptoButton")
        self.assertFalse(dialog.crypto_btn.icon().isNull())
        self.assertEqual(
            dialog.crypto_btn.isEnabled(),
            bool(dialogs_module.CRYPTO_SUPPORT_URL),
        )

    def test_a_value_below_the_minimum_clamps_instead_of_restoring_the_old_value(
        self,
    ) -> None:
        with patch.object(config, "RESET_HOLD_SAFETY_MARGIN", 0.02):
            with patch.object(config, "RESET_HOLD_DURATION", 0.50):
                dialog = SettingsDialog(None, master=MagicMock())
        self.addCleanup(dialog.close)
        entry = dialog.reset_hold_duration_entry

        self.assertEqual(
            entry.correctionMode(),
            QAbstractSpinBox.CorrectionMode.CorrectToNearestValue,
        )
        entry.lineEdit().setText("0.01")
        entry.interpretText()

        self.assertEqual(entry.value(), 0.03)
        self.assertEqual(entry.text(), "0.03 s")

    def test_zero_margin_allows_the_game_minimum_hold_duration(self) -> None:
        with patch.object(config, "RESET_HOLD_SAFETY_MARGIN", 0.0):
            with patch.object(config, "RESET_HOLD_DURATION", 0.03):
                dialog = SettingsDialog(None, master=MagicMock())
        self.addCleanup(dialog.close)

        entry = dialog.reset_hold_duration_entry
        self.assertEqual(entry.minimum(), 0.01)
        self.assertEqual(entry.value(), 0.03)
        self.assertEqual(entry.text(), "0.03 s")

    def test_margin_updates_the_dynamic_minimum_and_derived_game_value(self) -> None:
        with patch.object(config, "RESET_HOLD_SAFETY_MARGIN", 0.02):
            with patch.object(config, "RESET_HOLD_DURATION", 0.07):
                dialog = SettingsDialog(None, master=MagicMock())
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.reset_hold_duration_entry.singleStep(), 0.01)
        self.assertEqual(dialog.reset_hold_safety_margin_entry.singleStep(), 0.01)
        self.assertEqual(dialog.reset_hold_duration_entry.minimum(), 0.03)
        self.assertEqual(dialog.reset_game_value_label.text(), "0.05 s")

        dialog.reset_hold_safety_margin_entry.setValue(0.03)

        self.assertEqual(dialog.reset_hold_duration_entry.minimum(), 0.04)
        self.assertEqual(dialog.reset_game_value_label.text(), "0.04 s")


if __name__ == "__main__":
    unittest.main()
