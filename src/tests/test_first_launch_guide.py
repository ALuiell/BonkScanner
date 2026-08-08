from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401
from PySide6.QtWidgets import QApplication, QLabel, QWidget

import gui_app
from app import config
from gui_app import MegabonkApp
from ui.dialogs import AutoRerollSetupGuideDialog
from ui.dialogs.shell import DIALOG_WIDE


class FirstLaunchGuideConfigTests(unittest.TestCase):
    def test_a_missing_config_is_a_new_install(self) -> None:
        self.assertFalse(
            config.resolve_auto_reroll_setup_guide_acknowledged(
                None, config_existed=False
            )
        )

    def test_an_existing_config_predating_the_guide_is_not_interrupted(self) -> None:
        self.assertTrue(
            config.resolve_auto_reroll_setup_guide_acknowledged(
                None, config_existed=True
            )
        )

    def test_an_explicit_pending_or_acknowledged_state_wins(self) -> None:
        self.assertFalse(
            config.resolve_auto_reroll_setup_guide_acknowledged(
                False, config_existed=True
            )
        )
        self.assertTrue(
            config.resolve_auto_reroll_setup_guide_acknowledged(
                True, config_existed=False
            )
        )


class FirstLaunchGuideDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        original_user_config = dict(config.user_config)
        self.addCleanup(config.user_config.update, original_user_config)
        self.addCleanup(config.user_config.clear)

    def test_the_guide_contains_the_required_setup_and_acknowledges_only_got_it(self) -> None:
        dialog = AutoRerollSetupGuideDialog(None)
        self.addCleanup(dialog.close)
        text = " ".join(label.text() for label in dialog.findChildren(QLabel))

        self.assertIn("Quick Reset", text)
        self.assertIn("Skip Portal Animation", text)
        self.assertIn("Super Quick Resets", text)
        self.assertIn("0.10 s", text)
        self.assertIn("0.05-second safety margin", text)
        self.assertIn("RESET_HOLD_SAFETY_MARGIN", text)
        self.assertIn("0.07", text)
        self.assertIn("automatic adjustment", text)
        self.assertIn("Megabonk's game config", text)
        self.assertIn("%USERPROFILE%", text)
        self.assertEqual(dialog.minimumWidth(), DIALOG_WIDE)
        self.assertEqual(
            sum(
                frame.objectName() == "WarningCard"
                for frame in dialog.findChildren(QWidget)
            ),
            2,
        )
        self.assertFalse(dialog.acknowledged)

        dialog.reject()
        self.assertFalse(dialog.acknowledged)
        dialog.confirm()
        self.assertTrue(dialog.acknowledged)

    def test_got_it_persists_the_acknowledgement(self) -> None:
        app = object.__new__(MegabonkApp)
        app.window = QWidget()
        app._auto_reroll_setup_guide = None
        self.addCleanup(app.window.close)
        fake_dialog = SimpleNamespace(
            acknowledged=True,
            finished=MagicMock(),
            open=MagicMock(),
            deleteLater=MagicMock(),
        )

        with patch.object(config, "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED", False):
            with patch.object(config, "save_config") as save_config:
                with patch.object(
                    gui_app,
                    "AutoRerollSetupGuideDialog",
                    return_value=fake_dialog,
                ) as dialog_class:
                    app._show_auto_reroll_setup_guide()
                    app._show_auto_reroll_setup_guide()
                    fake_dialog.finished.connect.call_args.args[0](1)

                dialog_class.assert_called_once_with(app.window)
                fake_dialog.open.assert_called_once_with()
                fake_dialog.deleteLater.assert_called_once_with()
                self.assertIsNone(app._auto_reroll_setup_guide)
                self.assertTrue(config.AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED)
                self.assertTrue(
                    config.user_config["AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED"]
                )
                save_config.assert_called_once_with(config.user_config)

    def test_dismissing_the_guide_does_not_acknowledge_it(self) -> None:
        app = object.__new__(MegabonkApp)
        app.window = QWidget()
        app.window.show()
        app._auto_reroll_setup_guide = None
        self.addCleanup(app.window.close)
        fake_dialog = SimpleNamespace(
            acknowledged=False,
            finished=MagicMock(),
            open=MagicMock(),
            deleteLater=MagicMock(),
        )

        with patch.object(config, "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED", False):
            with patch.object(config, "save_config") as save_config:
                with patch.object(
                    gui_app,
                    "AutoRerollSetupGuideDialog",
                    return_value=fake_dialog,
                ):
                    app._show_auto_reroll_setup_guide()
                    fake_dialog.finished.connect.call_args.args[0](0)

                fake_dialog.open.assert_called_once_with()
                fake_dialog.deleteLater.assert_called_once_with()
                self.assertIsNone(app._auto_reroll_setup_guide)
                self.assertTrue(app.window.isVisible())
                self.assertFalse(config.AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED)
                save_config.assert_not_called()

    def test_closing_the_real_guide_leaves_the_main_window_running(self) -> None:
        app = object.__new__(MegabonkApp)
        app.window = QWidget()
        app.window.show()
        app._auto_reroll_setup_guide = None
        self.addCleanup(app.window.close)

        with patch.object(config, "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED", False):
            with patch.object(config, "save_config") as save_config:
                app._show_auto_reroll_setup_guide()
                dialog = app._auto_reroll_setup_guide
                self.assertIsNotNone(dialog)
                self.assertTrue(dialog.isVisible())

                dialog.close()
                QApplication.processEvents()

                self.assertTrue(app.window.isVisible())
                self.assertIsNone(app._auto_reroll_setup_guide)
                self.assertFalse(config.AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED)
                save_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
