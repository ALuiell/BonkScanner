from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import src  # noqa: F401
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from app import config
from gui_app import MegabonkApp


class FirstLaunchGuideConfigTests(unittest.TestCase):
    def test_a_missing_config_is_a_new_install(self) -> None:
        self.assertFalse(
            config.resolve_auto_reroll_setup_guide_acknowledged(
                None, config_existed=False
            )
        )

    def test_an_existing_config_predating_the_current_guide_sees_it_again(self) -> None:
        self.assertFalse(
            config.resolve_auto_reroll_setup_guide_acknowledged(
                None, config_existed=True
            )
        )

    def test_only_an_acknowledgement_for_the_current_version_wins(self) -> None:
        self.assertFalse(
            config.resolve_auto_reroll_setup_guide_acknowledged(
                False, config_existed=True
            )
        )
        self.assertFalse(
            config.resolve_auto_reroll_setup_guide_acknowledged(
                True,
                config_existed=True,
                saved_version=config.AUTO_REROLL_SETUP_GUIDE_VERSION - 1,
            )
        )
        self.assertTrue(
            config.resolve_auto_reroll_setup_guide_acknowledged(
                True,
                config_existed=False,
                saved_version=config.AUTO_REROLL_SETUP_GUIDE_VERSION,
            )
        )


class FirstLaunchGuideDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        read_only = patch.object(config, "profile_read_only_reason", return_value=None)
        read_only.start()
        self.addCleanup(read_only.stop)
        original_user_config = dict(config.user_config)
        self.addCleanup(config.user_config.update, original_user_config)
        self.addCleanup(config.user_config.clear)
        config.user_config["RESET_TIMING_SETUP_PENDING"] = False

    def test_pending_new_install_attempts_recommendations_even_after_guide_acknowledgement(self):
        owner = self._guide_owner()
        owner.is_game_running = lambda: True
        owner.log = MagicMock()
        config.user_config["RESET_TIMING_SETUP_PENDING"] = True
        with patch.object(config, "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED", True), patch.object(
            config, "apply_recommended_reset_timing",
            return_value=config.SettingsSaveResult(False, "Close Megabonk"),
        ) as apply:
            MegabonkApp._show_auto_reroll_setup_guide(owner)
        apply.assert_called_once()
        self.assertEqual(apply.call_args.args[0](), (True, ""))
        owner.log.assert_called_once()
        self.assertTrue(config.user_config["RESET_TIMING_SETUP_PENDING"])

    def test_existing_install_does_not_apply_recommendations_automatically(self):
        owner = self._guide_owner()
        with patch.object(config, "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED", True), patch.object(
            config, "apply_recommended_reset_timing"
        ) as apply:
            MegabonkApp._show_auto_reroll_setup_guide(owner)
        apply.assert_not_called()

    def _guide_owner(self, *, visible: bool = False):
        window = QWidget()
        if visible:
            window.show()
        self.addCleanup(window.close)
        owner = SimpleNamespace(
            window=window,
            _auto_reroll_setup_guide=None,
        )
        owner._finish_auto_reroll_setup_guide = lambda result: (
            MegabonkApp._finish_auto_reroll_setup_guide(owner, result)
        )
        return owner

    def test_accepting_the_quick_guide_persists_acknowledgement(self) -> None:
        owner = self._guide_owner()
        guide = SimpleNamespace(finished=MagicMock())
        owner.open_quick_guide = MagicMock(return_value=guide)
        with patch.object(config, "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED", False), patch.object(
            config, "save_config"
        ) as save:
            MegabonkApp._show_auto_reroll_setup_guide(owner)
            MegabonkApp._show_auto_reroll_setup_guide(owner)
            owner.open_quick_guide.assert_called_once_with("welcome")
            self.assertIs(owner._auto_reroll_setup_guide, guide)
            guide.finished.connect.call_args.args[0](QDialog.Accepted)
            self.assertIsNone(owner._auto_reroll_setup_guide)
            self.assertTrue(config.AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED)
            self.assertTrue(config.user_config["AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED"])
            self.assertEqual(config.user_config["AUTO_REROLL_SETUP_GUIDE_VERSION"],
                             config.AUTO_REROLL_SETUP_GUIDE_VERSION)
            save.assert_called_once_with(config.user_config)

    def test_rejecting_the_quick_guide_does_not_acknowledge_it(self) -> None:
        owner = self._guide_owner(visible=True)
        guide = SimpleNamespace(finished=MagicMock())
        owner.open_quick_guide = MagicMock(return_value=guide)
        with patch.object(config, "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED", False), patch.object(
            config, "save_config"
        ) as save:
            MegabonkApp._show_auto_reroll_setup_guide(owner)
            guide.finished.connect.call_args.args[0](QDialog.Rejected)
            self.assertIsNone(owner._auto_reroll_setup_guide)
            self.assertTrue(owner.window.isVisible())
            self.assertFalse(config.AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED)
            save.assert_not_called()

    def test_failed_open_does_not_acknowledge_and_can_retry(self) -> None:
        owner = self._guide_owner()
        owner.open_quick_guide = MagicMock(return_value=None)
        with patch.object(config, "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED", False), patch.object(
            config, "save_config"
        ) as save:
            MegabonkApp._show_auto_reroll_setup_guide(owner)
            MegabonkApp._show_auto_reroll_setup_guide(owner)
            self.assertEqual(owner.open_quick_guide.call_count, 2)
            self.assertIsNone(owner._auto_reroll_setup_guide)
            self.assertFalse(config.AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED)
            save.assert_not_called()

    def test_read_only_profile_does_not_apply_timing_or_open_guide(self) -> None:
        owner = self._guide_owner()
        owner.open_quick_guide = MagicMock()
        config.user_config["RESET_TIMING_SETUP_PENDING"] = True
        with patch.object(config, "profile_read_only_reason", return_value="profile in use"), patch.object(
            config, "AUTO_REROLL_SETUP_GUIDE_ACKNOWLEDGED", False
        ), patch.object(config, "apply_recommended_reset_timing") as apply, patch.object(
            config, "save_config"
        ) as save:
            MegabonkApp._show_auto_reroll_setup_guide(owner)
            apply.assert_not_called()
            owner.open_quick_guide.assert_not_called()
            save.assert_not_called()
            self.assertTrue(config.user_config["RESET_TIMING_SETUP_PENDING"])


if __name__ == "__main__":
    unittest.main()
