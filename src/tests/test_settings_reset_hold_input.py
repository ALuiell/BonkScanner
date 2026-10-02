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

        self.assertEqual(dialog.supporter_access_page.crypto_btn.text(), "Open Crypto")
        self.assertEqual(dialog.supporter_access_page.crypto_btn.objectName(), "SupportCryptoPrimary")
        self.assertFalse(dialog.supporter_access_page.crypto_btn.icon().isNull())
        self.assertEqual(
            dialog.supporter_access_page.crypto_btn.isEnabled(),
            bool(dialogs_module.CRYPTO_SUPPORT_URL),
        )

    def test_a_value_below_the_minimum_stays_visible_and_blocks_save(
        self,
    ) -> None:
        with patch.object(config, "RESET_HOLD_SAFETY_MARGIN", 0.02):
            with patch.object(config, "RESET_HOLD_DURATION", 0.50):
                dialog = SettingsDialog(None, master=MagicMock())
        self.addCleanup(dialog.close)
        entry = dialog.reset_hold_duration_entry

        entry.lineEdit().setText("0.01")
        entry.interpretText()

        self.assertEqual(entry.value(), 0.01)
        self.assertEqual(entry.text(), "0.01")
        self.assertFalse(dialog.save_btn.isEnabled())

    def test_zero_margin_allows_the_game_minimum_hold_duration(self) -> None:
        with patch.object(config, "RESET_HOLD_SAFETY_MARGIN", 0.0):
            with patch.object(config, "RESET_HOLD_DURATION", 0.03):
                dialog = SettingsDialog(None, master=MagicMock())
        self.addCleanup(dialog.close)

        entry = dialog.reset_hold_duration_entry
        self.assertEqual(entry.minimum(), 0.01)
        self.assertEqual(entry.value(), 0.03)
        self.assertEqual(entry.text(), "0.03 s")

    def test_margin_updates_the_dynamic_minimum_and_shows_current_game_value(self) -> None:
        with patch.object(config, "RESET_HOLD_SAFETY_MARGIN", 0.02):
            with patch.object(config, "RESET_HOLD_DURATION", 0.07):
                with patch.object(
                    config,
                    "read_game_quick_reset_time",
                    return_value=config.GameConfigReadResult(True, value=0.01),
                ):
                    dialog = SettingsDialog(None, master=MagicMock())
        self.addCleanup(dialog.close)

        self.assertEqual(dialog.reset_hold_duration_entry.singleStep(), 0.01)
        self.assertEqual(dialog.reset_hold_safety_margin_entry.singleStep(), 0.01)
        self.assertEqual(dialog.reset_hold_duration_entry.minimum(), 0.03)
        self.assertEqual(dialog.reset_game_value_label.text(), "0.01 s")

        with patch.object(
            config,
            "read_game_quick_reset_time",
            return_value=config.GameConfigReadResult(True, value=0.01),
        ):
            dialog.reset_hold_safety_margin_entry.setValue(0.03)

        self.assertEqual(dialog.reset_hold_duration_entry.minimum(), 0.04)
        self.assertEqual(dialog.reset_game_value_label.text(), "0.01 s")


if __name__ == "__main__":
    unittest.main()
