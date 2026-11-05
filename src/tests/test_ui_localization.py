from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import src  # noqa: F401
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QWidget

from app import config
from core.localization import LANGUAGE_CONFIG_KEY, SUPPORTED_LANGUAGES
from ui.dialogs import SettingsDialog
from ui.layout import _build_header_controls
from ui.localization import bind_text, localization
from ui.scanner_toggle import ScannerToggle


class UiLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.config_patch = patch.object(config, "user_config", deepcopy(config.user_config))
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        config.user_config[LANGUAGE_CONFIG_KEY] = "en"
        self.service = localization()
        previous_language = self.service.translator.language
        self.addCleanup(self.service.translator.set_language, previous_language)
        self.service.apply_saved_language()
        game_value = config.reset_hold_duration_to_game_value(config.RESET_HOLD_DURATION,
                                                            safety_margin=config.RESET_HOLD_SAFETY_MARGIN)
        game_read = patch.object(config, "read_game_quick_reset_time",
                                 return_value=config.GameConfigReadResult(True, value=game_value))
        game_read.start()
        self.addCleanup(game_read.stop)
        self.parent = QWidget()
        self.addCleanup(self.parent.deleteLater)
        self.dialog = SettingsDialog(self.parent, master=SimpleNamespace())

    def test_all_seven_languages_apply_after_save_and_preserve_scanner_state(self):
        self.dialog.show()
        toggle = ScannerToggle(self.parent)
        toggle.setText(ScannerToggle.STOP_TEXT)
        original_hotkey = config.HOTKEY
        with patch.object(config, "save_settings_with_game_reset", return_value=config.SettingsSaveResult(True)) as save:
            for code in SUPPORTED_LANGUAGES:
                self.dialog.language_selector.setCurrentIndex(self.dialog.language_selector.findData(code))
                self.assertTrue(self.dialog.save(close_dialog=False))
                self.assertEqual(save.call_args.args[0][LANGUAGE_CONFIG_KEY], code)
                self.assertEqual(config.user_config[LANGUAGE_CONFIG_KEY], code)
                self.assertEqual(self.service.translator.language, code)
                self.assertEqual(self.dialog.windowTitle(), self.service.text("common.settings"))
                self.assertEqual(self.dialog.settings_header_tabs.tabText(0), self.service.text("settings.general"))
                self.assertEqual(self.dialog.save_btn.text(), self.service.text("common.save"))
                QApplication.processEvents()
                tabs = self.dialog.settings_header_tabs
                self.assertLessEqual(tabs.tabRect(tabs.count() - 1).right(), tabs.width())
                self.assertEqual(toggle.segment("start").text(), "▶  " + self.service.text("scanner.start"))
                self.assertTrue(toggle.is_running())
                self.assertEqual(toggle.text(), "Stop Scanner")
                self.assertEqual(config.HOTKEY, original_hotkey)
                self.dialog.reload_from_config()
                self.assertEqual(self.dialog.language_selector.currentData(), code)

    def test_cancel_and_failed_save_keep_active_language_and_unsaved_selection(self):
        selector = self.dialog.language_selector
        selector.setCurrentIndex(selector.findData("uk"))
        self.assertTrue(self.dialog._general_settings_dirty)
        self.assertEqual(self.service.translator.language, "en")
        self.dialog.reject()
        self.assertEqual(config.user_config[LANGUAGE_CONFIG_KEY], "en")
        self.dialog.reload_from_config()
        self.assertEqual(selector.currentData(), "en")
        selector.setCurrentIndex(selector.findData("ru"))
        with patch.object(config, "save_settings_with_game_reset", return_value=config.SettingsSaveResult(False, "read only")), \
                patch.object(SettingsDialog, "_show_game_reset_notice"):
            self.assertFalse(self.dialog.save(close_dialog=False))
        self.assertEqual(self.service.translator.language, "en")
        self.assertEqual(config.user_config[LANGUAGE_CONFIG_KEY], "en")
        self.assertEqual(selector.currentData(), "ru")

    def test_header_tooltips_follow_language_and_bindings_disconnect_on_deletion(self):
        owner = SimpleNamespace(_scanner=SimpleNamespace(toggle_main_loop=lambda: None),
                                open_settings_dialog=lambda: None, open_help_dialog=lambda: None)
        header = QWidget(self.parent)
        _build_header_controls(owner, QHBoxLayout(header))
        transient = QLabel(self.parent)
        bind_text(transient, "common.help")
        transient.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        config.user_config[LANGUAGE_CONFIG_KEY] = "fr"
        self.service.apply_saved_language()
        self.assertEqual(owner.settings_btn.toolTip(), "Paramètres")
        self.assertEqual(owner.help_btn.toolTip(), "Aide")
        later = QLabel(self.parent)
        bind_text(later, "common.help")
        self.assertEqual(later.text(), "Aide")

    def test_translated_tabs_route_by_page_and_native_language_codes_remain_stable(self):
        config.user_config[LANGUAGE_CONFIG_KEY] = "de"
        self.service.apply_saved_language()
        self.assertEqual([self.dialog.language_selector.itemData(i) for i in range(7)], list(SUPPORTED_LANGUAGES))
        self.dialog.show_page("support")
        self.assertIs(self.dialog.settings_tabs.currentWidget(), self.dialog.supporter_access_page)
        self.assertEqual(self.dialog.save_btn.text(), "Fertig")
        self.dialog.language_selector.setCurrentIndex(self.dialog.language_selector.findData("fr"))
        self.assertEqual(self.dialog.save_btn.text(), "Änderungen speichern")
