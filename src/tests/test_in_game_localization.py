from __future__ import annotations

from copy import deepcopy
from html import escape
from types import SimpleNamespace as NS
import unittest
from unittest.mock import MagicMock, patch

import src  # noqa: F401
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from app import config
from core.localization import LANGUAGE_CONFIG_KEY, GAME_LANGUAGE_CONFIG_KEY, FOLLOW_INTERFACE_LANGUAGE, SUPPORTED_LANGUAGES
from core.map_markers import MAP_MARKER_ACTIONS, MerchantOffer, MerchantStockCapture
from core.overlay_localization import overlay_text
from core.stats.weapon_tracker import WeaponTrackerMetric, WeaponTrackerRow
from gui_in_game_overlay_settings import (
    InGameWidgetSettingsDialog, WeaponTrackerSettingsDialog, build_in_game_overlay_tab,
)
from gui_in_game_overlay_window import LuckRarityOverlayWidget, _display_stock
from infra.localization_catalogs import create_translator
from projections.in_game_html import (
    build_build_progression_overlay_html, build_event_timer_overlay_html,
    build_item_cooldowns_overlay_html, build_kps_overlay_html_from_values,
    build_powerups_overlay_html, build_stats_overlay_html, build_status_indicator_html,
    build_weapon_tracker_overlay_html,
)
from ui.dialogs.map_markers import MapMarkerBindingDialog, MapMarkerSettingsDialog
from ui.layout import _is_tab_active
from ui.localization import localization
from ui.overlay_localization import action_name, bind_overlay_tab


class NativeOverlayLocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        preference = patch.object(config, "user_config", deepcopy(config.user_config))
        preference.start()
        self.addCleanup(preference.stop)
        config.user_config[LANGUAGE_CONFIG_KEY] = "en"
        config.user_config[GAME_LANGUAGE_CONFIG_KEY] = FOLLOW_INTERFACE_LANGUAGE
        self.service = localization()
        self.service.apply_saved_language()
        def restore_english():
            config.user_config[LANGUAGE_CONFIG_KEY] = "en"
            self.service.apply_saved_language()
        self.addCleanup(restore_english)
        overlay = patch.object(config, "IN_GAME_OVERLAY", config.normalize_in_game_overlay_config({}))
        overlay.start()
        self.addCleanup(overlay.stop)

    def switch(self, code):
        config.user_config[LANGUAGE_CONFIG_KEY] = code
        self.service.apply_saved_language()

    def test_all_text_widgets_use_selected_locale_and_exact_game_names(self):
        snapshot = NS(stats={"Damage": NS(value=1.5, display_value="150%")})
        powerups = NS(active=(NS(name="Rage", remaining_seconds=9),), powerup_multiplier_display="2x")
        cooldowns = NS(item_cooldowns=NS(my_time_seconds=100,
                                       readings=(NS(name="Holy Book", next_trigger_time=120),)))
        weapons = (WeaponTrackerRow(1, "Fire Staff", 3, (WeaponTrackerMetric("damage", 12, "DMG", 15),)),)
        payload = {"configured": True, "available": True, "name": "My <Build>", "progress": "0/1",
                   "show_section_headings": True,
                   "rows": [{"kind": "item", "target": "Holy Book", "label": "Holy Book",
                             "value": "0/1", "time": "NO DEADLINE"}]}
        before = deepcopy(payload)
        for code in SUPPORTED_LANGUAGES:
            with self.subTest(locale=code):
                translator = create_translator(language=code)
                message = lambda source, **values: overlay_text(translator, source, **values)
                self.assertIn(message("REC"), build_status_indicator_html("REC", True, translator=translator))
                self.assertIn(message("Run"), build_kps_overlay_html_from_values({"run_avg": 12}, ["run"], translator=translator))
                self.assertIn(escape(message("Event Timer (preview)")), build_event_timer_overlay_html(0, 0, 600, False, edit_mode=True, translator=translator))
                self.assertIn(escape(message("Powerups (preview)")), build_powerups_overlay_html(NS(), edit_mode=True, translator=translator))
                power = build_powerups_overlay_html(powerups, translator=translator)
                expected_rage = "Rage" if code == "en" else translator.game_name("powerups", "Rage")
                self.assertIn(escape(expected_rage), power)
                cooldown = build_item_cooldowns_overlay_html(cooldowns, translator=translator)
                expected_item = "Holy Book" if code == "en" else translator.game_name("items", "Holy Book")
                self.assertIn(escape(expected_item), cooldown)
                self.assertIn("20", cooldown)
                stats = build_stats_overlay_html(snapshot, ["Damage"], 0, 0, 600, False, translator=translator)
                expected_stat = "DMG" if code == "en" else translator.game_name("stats", "Damage")
                self.assertIn(escape(expected_stat), stats)
                weapon = build_weapon_tracker_overlay_html(weapons, layout="detailed", translator=translator)
                expected_weapon = "Fire Staff" if code == "en" else translator.game_name("weapons", "Fire Staff")
                self.assertIn(escape(expected_weapon), weapon)
                self.assertIn(escape(message("Lv.{level}", level=3)), weapon)
                self.assertIn(escape(message("Waiting for Weapon Data")), build_weapon_tracker_overlay_html((), edit_mode=True, status_message="Waiting for Weapon Data", translator=translator))
                build = build_build_progression_overlay_html(payload, translator=translator)
                self.assertIn("My &lt;Build&gt;", build)
                self.assertIn(escape(expected_item), build)
                self.assertIn(escape(message("NO DEADLINE")), build)
        self.assertEqual(payload, before)
        self.assertEqual(weapons[0].name, "Fire Staff")
        self.assertEqual(powerups.active[0].name, "Rage")

    def test_settings_retranslate_in_place_without_saving_or_changing_options(self):
        handler = MagicMock()
        owner = NS(**{name: handler for name in (
            "_on_igo_settings_changed", "_toggle_in_game_overlay", "_open_igo_widget_settings_dialog",
            "_open_weapon_tracker_settings_dialog", "_open_build_progression_dialog",
            "_queue_igo_weapon_tracker_layout_change", "_apply_igo_weapon_tracker_layout_change",
            "apply_in_game_overlay_settings", "rebind_hotkeys")})
        owner._has_premium_access = lambda: True
        owner._in_game_overlay_target_geometry = lambda: None
        owner.is_in_game_overlay_tab_active = lambda: True
        owner.in_game_overlay_window = None
        build_in_game_overlay_tab(owner)
        self.addCleanup(owner.tab_in_game_overlay.deleteLater)
        stats = InGameWidgetSettingsDialog(owner)
        weapons = WeaponTrackerSettingsDialog(owner)
        self.addCleanup(stats.deleteLater)
        self.addCleanup(weapons.deleteLater)
        pages = QTabWidget()
        pages.addTab(owner.tab_in_game_overlay, "In-Game Overlay")
        bind_overlay_tab(pages, owner.tab_in_game_overlay)
        self.addCleanup(pages.deleteLater)
        before = deepcopy(config.IN_GAME_OVERLAY)
        handler.reset_mock()
        with patch.object(config, "save_config") as save:
            for code in SUPPORTED_LANGUAGES:
                with self.subTest(locale=code):
                    self.switch(code)
                    self.assertTrue(_is_tab_active(pages, "In-Game Overlay"))
                    self.assertEqual(stats.windowTitle(), overlay_text(self.service.translator, "Stats shown by the Stats widget"))
                    self.assertEqual(stats.stats_checkboxes["Damage"].text(), self.service.translator.game_name("stats", "Damage"))
                    self.assertEqual(weapons.metric_checkboxes["damage"].text(), self.service.translator.game_name("stats", "Damage"))
                    self.assertEqual(owner.igo_weapon_tracker_layout_combo.currentData(), "compact")
                    self.assertEqual(owner.igo_luck_layout_combo.currentData(), "column")
            save.assert_not_called()
        handler.assert_not_called()
        self.assertEqual(config.IN_GAME_OVERLAY, before)

    def test_marker_dialog_and_stock_use_localized_display_copies(self):
        bindings = [{"input": "mouse4", "action": "shady_guy_blue"}]
        dialog = MapMarkerSettingsDialog(bindings, has_premium_access=True)
        binding_dialog = MapMarkerBindingDialog(bindings[0])
        self.addCleanup(dialog.deleteLater)
        self.addCleanup(binding_dialog.deleteLater)
        binding_dialog.input_recorder._set_message("Reserved or unsupported — try another input")
        stock = MerchantStockCapture(1, 2, "merchant", 1, 0, 0,
                                     (MerchantOffer(1, "Holy Book", "Holy Book", "LEGENDARY", 100),))
        before = deepcopy(stock)
        for code in SUPPORTED_LANGUAGES:
            self.switch(code)
            self.assertEqual(dialog.bindings, bindings)
            self.assertEqual(binding_dialog.action_combo.currentData(), "shady_guy_blue")
            self.assertEqual(binding_dialog.input_recorder.binding, "mouse4")
            self.assertEqual(binding_dialog.input_recorder.text(), overlay_text(
                self.service.translator, "Reserved or unsupported — try another input"))
            self.assertEqual(binding_dialog.action_combo.itemText(0), action_name(MAP_MARKER_ACTIONS[0]))
            translated = _display_stock(stock, code)
            expected = "Holy Book" if code == "en" else self.service.translator.game_name("items", "Holy Book")
            self.assertEqual(translated.items[0].display_name, expected)
            self.assertEqual(translated.items[0].canonical_name, "Holy Book")
            self.assertEqual(translated.items[0].price, 100)
        self.assertEqual(stock, before)

    def test_luck_status_uses_message_translation_and_keeps_counts(self):
        widget = LuckRarityOverlayWidget("luck_rarity")
        self.addCleanup(widget.deleteLater)
        for code in SUPPORTED_LANGUAGES:
            self.switch(code)
            widget.set_expected({}, {}, show_expected=False, status_message="Missed run start")
            self.assertIn(escape(overlay_text(self.service.translator, "Missed run start")), widget.expected_label.text())
