from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import src
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)
from app import config
from app.config_repository import ConfigRepository
from core.overlay_config import widget_config_by_id
from core.stats.types import WeaponStatFormat
from gui_in_game_overlay_settings import WeaponTrackerSettingsDialog, _igo_widget_options
from projections.obs import build_overlay_state_from_snapshot
from twitch_bot import TwitchBotWorker
from ui.dialogs import TwitchCommandSettingsDialog
from ui.tabs.player_stats.stat_cards import StatCardsView
from test_gui_run_control import build_overlay_test_component, build_in_game_overlay_test_component
from test_weapon_tracker_projection import _weapon, _globals


class WeaponIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = ConfigRepository(Path(self.temp.name) / "config.json")
        for key, value in (
            ("OVERLAY", config.normalize_overlay_config({})),
            ("IN_GAME_OVERLAY", config.normalize_in_game_overlay_config({})),
            ("TWITCH_BOT", config.normalize_twitch_bot_config({})),
            ("user_config", {}), ("_repository", self.repo),
            ("config_path", str(self.repo.path)),
        ):
            patcher = patch.object(config, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        config.user_config.update(
            OVERLAY=config.OVERLAY, IN_GAME_OVERLAY=config.IN_GAME_OVERLAY,
            TWITCH_BOT=config.TWITCH_BOT,
        )

    def test_old_and_invalid_settings_default_off_without_losing_empty_selection(self):
        self.assertFalse(config.TWITCH_BOT["weapons_include_globals"])
        self.assertFalse(config.IN_GAME_OVERLAY["widgets"]["weapon_tracker"]["show_caps"])
        self.assertFalse(widget_config_by_id(config.OVERLAY)["weapon_tracker"]["show_caps"])
        for value in ("false", "true", None, [], {}):
            obs = config.normalize_overlay_config({"widgets": [{"id": "weapon_tracker", "show_caps": value, "selected_stats": []}]})
            widget = widget_config_by_id(obs)["weapon_tracker"]
            self.assertFalse(widget["show_caps"])
            self.assertEqual(widget["selected_stats"], [])
            self.assertFalse(config.normalize_twitch_bot_config({"weapons_include_globals": value})["weapons_include_globals"])

    def test_native_inline_caps_save_apply_and_disk_roundtrip(self):
        overlay = build_in_game_overlay_test_component(find_game_window=lambda _name: None)
        overlay.build()
        self.addCleanup(overlay.tab_in_game_overlay.deleteLater)
        self.addCleanup(overlay.igo_target_window_timer.stop)
        overlay.apply_in_game_overlay_settings = MagicMock()
        checkbox = overlay.igo_weapon_tracker_caps_cb
        self.assertTrue(overlay.tab_in_game_overlay.isAncestorOf(checkbox))
        self.assertFalse(checkbox.isChecked())
        original_selection = list(config.IN_GAME_OVERLAY["widgets"]["weapon_tracker"]["selected_stats"])
        for enabled in (True, False, True):
            checkbox.setChecked(enabled)
            saved = self.repo.load().snapshot
            restored = config.normalize_in_game_overlay_config(saved["IN_GAME_OVERLAY"])
            self.assertEqual(restored["widgets"]["weapon_tracker"]["show_caps"], enabled)
            self.assertEqual(restored["widgets"]["weapon_tracker"]["selected_stats"], original_selection)
            self.assertFalse(widget_config_by_id(saved["OVERLAY"])["weapon_tracker"]["show_caps"])
        self.assertEqual(overlay.apply_in_game_overlay_settings.call_count, 3)

        # The metric picker must neither duplicate nor overwrite the inline flag.
        dialog = WeaponTrackerSettingsDialog(overlay, overlay.tab_in_game_overlay)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(len(dialog.findChildren(QCheckBox)), 6)
        dialog.metric_checkboxes["duration"].setChecked(True)
        dialog._save_settings()
        self.assertTrue(self.repo.load().snapshot["IN_GAME_OVERLAY"]["widgets"]["weapon_tracker"]["show_caps"])

        # Reconstruct the control from the persisted setting, as on restart.
        with patch.object(config, "IN_GAME_OVERLAY", restored):
            parent = SimpleNamespace(
                _on_igo_settings_changed=MagicMock(),
                _open_weapon_tracker_settings_dialog=MagicMock(),
                _queue_igo_weapon_tracker_layout_change=MagicMock(),
                _apply_igo_weapon_tracker_layout_change=MagicMock(),
            )
            holder = _igo_widget_options(parent, "weapon_tracker")
            self.addCleanup(holder.deleteLater)
            self.assertTrue(parent.igo_weapon_tracker_caps_cb.isChecked())
            parent._on_igo_settings_changed.assert_not_called()

    def test_obs_dialog_toggle_saves_and_publishes_independent_settings(self):
        overlay = build_overlay_test_component()
        overlay.build()
        self.addCleanup(overlay.tab_overlay.deleteLater)
        self.addCleanup(overlay.overlay_preview_timer.stop)

        def edit(_dialog):
            weapon_group = next(
                group
                for group in _dialog.findChildren(QGroupBox)
                if group.title() == "Weapon Tracker"
            )
            section_titles = [
                label.text()
                for label in weapon_group.findChildren(QLabel, "settingsSubsectionTitle")
            ]
            self.assertEqual(section_titles, ["APPEARANCE", "CAP DISPLAY", "DISPLAYED STATS"])
            self.assertEqual(
                len(weapon_group.findChildren(QFrame, "settingsSubsectionDivider")), 2
            )
            self.assertFalse(overlay.overlay_weapon_options["show_caps"].isChecked())
            overlay.overlay_widget_checkboxes["weapon_tracker"].setChecked(True)
            overlay.overlay_weapon_options["show_caps"].setChecked(True)
            overlay.overlay_weapon_layout_combo.setCurrentIndex(1)
            overlay.overlay_weapon_checkboxes["crit_damage"].setChecked(True)
            return QDialog.Accepted

        with patch.object(QDialog, "exec", edit):
            overlay.open_overlay_widget_settings_dialog()
        saved = self.repo.load().snapshot
        obs = config.normalize_overlay_config(saved["OVERLAY"])
        widget = widget_config_by_id(obs)["weapon_tracker"]
        self.assertTrue(widget["enabled"])
        self.assertTrue(widget["show_caps"])
        self.assertEqual(widget["layout"], "detailed")
        self.assertIn("crit_damage", widget["selected_stats"])
        self.assertFalse(saved["IN_GAME_OVERLAY"]["widgets"]["weapon_tracker"]["show_caps"])
        published = overlay.overlay_state_store.set_state.call_args.args[0]
        self.assertTrue(published["widgets"]["weapon_tracker"]["show_caps"])
        self.assertIsNone(overlay.overlay_weapon_options)
        # Closing the settings window must not leave deleted Qt wrappers in save.
        overlay.save_overlay_settings_from_ui()

    def test_twitch_dialog_persistence_and_original_message_order(self):
        parent = QWidget()
        self.addCleanup(parent.deleteLater)
        dialog = TwitchCommandSettingsDialog(parent)
        self.assertFalse(dialog.weapons_include_globals_cb.isChecked())
        dialog.weapons_include_globals_cb.setChecked(True)
        dialog.save()
        saved = self.repo.load().snapshot
        config.TWITCH_BOT = config.normalize_twitch_bot_config(saved["TWITCH_BOT"])
        self.assertTrue(config.TWITCH_BOT["weapons_include_globals"])
        dialog.deleteLater()

        snapshot = SimpleNamespace(weapons=(_weapon(),), stats=_globals())
        bot = SimpleNamespace(
            _runtime_snapshot=MagicMock(return_value=SimpleNamespace(latest_snapshot=snapshot)),
            _format_template=lambda _key, template, **values: template.format(**values),
            _send_chat=MagicMock(),
        )
        config.TWITCH_BOT["weapons_include_globals"] = False
        TwitchBotWorker._handle_weapons(bot, "channel")
        original = bot._send_chat.call_args.args[1]
        self.assertIn("Stat 12: 50", original)
        self.assertEqual(bot._send_chat.call_count, 1)
        bot._send_chat.reset_mock()
        config.TWITCH_BOT["weapons_include_globals"] = True
        TwitchBotWorker._handle_weapons(bot, "channel")
        messages = [call.args[1] for call in bot._send_chat.call_args_list]
        self.assertEqual(messages[0], original)
        self.assertEqual(len(messages), 2)
        self.assertIn("Weapons with global stats:", messages[1])
        self.assertIn("DMG: 100", messages[1])
        self.assertNotIn("cap", messages[1])
        self.assertLessEqual(len(messages[1]), 450)
        snapshot.stats = {}
        bot._send_chat.reset_mock()
        TwitchBotWorker._handle_weapons(bot, "channel")
        self.assertIn("Unavailable", bot._send_chat.call_args.args[1])
        snapshot.weapons = ()
        bot._send_chat.reset_mock()
        TwitchBotWorker._handle_weapons(bot, "channel")
        bot._send_chat.assert_called_once_with("channel", "No weapons found.")

    def test_live_card_preserves_original_fields_and_refreshes_on_global_only_change(self):
        root = QWidget()
        self.addCleanup(root.deleteLater)
        view = StatCardsView(weapons_layout=QVBoxLayout(root), weapons_status_label=QLabel(root),
                            tomes_layout=None, tomes_status_label=None, chaos_layout=None,
                            chaos_status_label=None, damage_sources_layout=None, damage_sources_status_label=None)
        weapon = _weapon(values={12: 50, 11: 8, 19: 0}, upgrade_stat_ids=(12, 11, 19))
        raw_before = deepcopy(weapon)
        view.display_weapons((weapon,), general_stats=_globals())
        card = view._weapon_cards[0]
        self.assertEqual([row._weapon_value_label.text() for row in card._row_widgets], ["50", "8", "0"])
        self.assertEqual([row._value_label.text() for row in card._row_widgets], ["100", "—", "×2"])
        self.assertEqual([row._name_label.text() for row in card._row_widgets], ["Stat 12", "Stat 11", "Stat 19"])
        self.assertEqual(card._weapon_heading._weapon_value_label.text(), "Weapon")
        self.assertEqual(card._weapon_heading._value_label.text(), "With globals")
        self.assertFalse(card._weapon_heading.isHidden())
        original_rows = tuple(card._row_widgets)
        view.display_weapons((weapon,), general_stats=_globals(Damage=3))
        self.assertIs(view._weapon_cards[0], card)
        self.assertEqual(card._row_widgets[0]._value_label.text(), "150")
        self.assertEqual(tuple(card._row_widgets), original_rows)
        self.assertEqual(weapon, raw_before)
        self.assertFalse(any("cap" in label.text() for label in card.findChildren(QLabel)))
        view.display_weapons((weapon,), general_stats={})
        self.assertEqual([row._weapon_value_label.text() for row in card._row_widgets], ["50", "8", "0"])
        self.assertEqual([row._value_label.text() for row in card._row_widgets], ["—", "—", "—"])
        self.assertIn("unavailable", card._row_widgets[0].toolTip())
        # Existing Recordings callers omit globals and keep the original view.
        view.display_weapons((weapon,))
        self.assertEqual([row._value_label.text() for row in card._row_widgets], ["50", "8", "0"])
        self.assertEqual(card._row_widgets[0].toolTip(), "")
        self.assertTrue(all(row._weapon_value_label.isHidden() for row in card._row_widgets))
        self.assertTrue(card._weapon_heading.isHidden())
        view.display_weapons((weapon,), general_stats=_globals())
        self.assertEqual(card._row_widgets[0]._value_label.text(), "100")
        self.assertFalse(card._weapon_heading.isHidden())

    def test_live_weapon_units_keep_raw_numbers_and_historical_format(self):
        root = QWidget()
        self.addCleanup(root.deleteLater)
        view = StatCardsView(weapons_layout=QVBoxLayout(root), weapons_status_label=QLabel(root),
                            tomes_layout=None, tomes_status_label=None, chaos_layout=None,
                            chaos_status_label=None, damage_sources_layout=None, damage_sources_status_label=None)
        weapon = _weapon(values={9: 4.3, 16: 28.8, 10: 2.57}, upgrade_stat_ids=(9, 16, 10))
        for stat_id in (9, 10):
            stat = replace(weapon.full_stats[stat_id], value_format=WeaponStatFormat.MULTIPLIER)
            weapon.full_stats[stat_id] = stat
            weapon.upgraded_stats[stat_id] = stat
        before = deepcopy(weapon)
        view.display_weapons((weapon,), general_stats=_globals())
        rows = view._weapon_cards[0]._row_widgets
        self.assertEqual([row._weapon_value_label.text() for row in rows], ["×4.3", "28.8", "2.57s"])
        self.assertEqual([row._value_label.text() for row in rows], ["×6.45", "29", "5.14s"])
        self.assertEqual(weapon, before)
        view.display_weapons((weapon,))
        self.assertEqual([row._value_label.text() for row in rows], ["4.3x", "28.8", "2.57x"])
