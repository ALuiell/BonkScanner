from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

import src  # noqa: F401 -- test path bootstrap
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QPushButton

from core.map_markers import (
    display_input_binding,
    normalize_input_binding,
    normalize_map_marker_hotkeys,
    normalize_map_marker_settings,
)
from ui.dialogs.map_markers import (
    InputBindingRecorder,
    MapMarkerBindingDialog,
    MapMarkerSettingsDialog,
)


class MapMarkerConfigTests(unittest.TestCase):
    def test_normalization_keeps_valid_unique_bindings(self) -> None:
        self.assertEqual(
            normalize_map_marker_hotkeys(
                [
                    {"input": "Mouse 4", "action": "microwave_white"},
                    {"input": "mouse4", "action": "boss_curse"},
                    {"input": "F10", "action": "challenge_shrine"},
                    {"input": "Tab", "action": "moai"},
                    {"input": "F11", "action": "removed_action"},
                ]
            ),
            [
                {"input": "mouse4", "action": "microwave_white"},
                {"input": "f10", "action": "challenge_shrine"},
            ],
        )

    def test_marker_settings_clamp_scale_and_default_premium_options_on(self) -> None:
        self.assertEqual(
            normalize_map_marker_settings({"scale": 99, "hotkeys": "bad"}),
            {
                "enabled": False,
                "automatic_discovery": False,
                "style": "modern",
                "scale": 3.0,
                "minimap_enabled": True,
                "minimap_scale": 1.0,
                "merchant_memory_enabled": True,
                "merchant_stock_display": "smart",
                "hotkeys": [],
            },
        )
        self.assertTrue(
            normalize_map_marker_settings({"automatic_discovery": True})[
                "automatic_discovery"
            ]
        )
        self.assertEqual(
            normalize_map_marker_settings({"style": "classic"})["style"],
            "classic",
        )
        self.assertEqual(
            normalize_map_marker_settings({"style": "unknown"})["style"],
            "modern",
        )
        premium = normalize_map_marker_settings(
            {
                "minimap_enabled": True,
                "minimap_scale": 99,
                "merchant_memory_enabled": True,
                "merchant_stock_display": "cursor",
            }
        )
        self.assertTrue(premium["minimap_enabled"])
        self.assertEqual(premium["minimap_scale"], 2.0)
        self.assertTrue(premium["merchant_memory_enabled"])
        self.assertEqual(premium["merchant_stock_display"], "cursor")

    def test_plain_game_controls_are_reserved_but_modified_keys_work(self) -> None:
        self.assertIsNone(normalize_input_binding("tab"))
        self.assertIsNone(normalize_input_binding("w"))
        self.assertEqual(normalize_input_binding("Ctrl+W"), "ctrl+w")
        self.assertEqual(display_input_binding("mouse_middle"), "Middle Mouse")


class MapMarkerSettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_stock_memory_includes_prices_without_separate_setting(self) -> None:
        dialog = MapMarkerSettingsDialog([], has_premium_access=True)
        try:
            self.assertTrue(dialog.minimap_enabled)
            self.assertTrue(dialog.merchant_memory_enabled)
            self.assertFalse(hasattr(dialog, "merchant_prices_switch"))
            copy = " ".join(
                label.text() for label in dialog.merchant_row.findChildren(QLabel)
            )
            self.assertIn("names and prices", copy)
            self.assertIn("Reopen the shop to refresh them", copy)
        finally:
            dialog.deleteLater()

    def test_microwave_counter_is_part_of_free_automatic_discovery(self) -> None:
        for premium in (False, True):
            with self.subTest(premium=premium):
                dialog = MapMarkerSettingsDialog([], has_premium_access=premium)
                try:
                    dialog.show()
                    QApplication.processEvents()
                    self.assertEqual(len(dialog.premium_card.findChildren(QCheckBox)), 2)
                    copy = " ".join(
                        label.text()
                        for label in dialog.behavior_card.findChildren(QLabel)
                    )
                    self.assertIn("remaining uses", copy)
                    self.assertNotIn("Requires Premium", copy)
                finally:
                    dialog.close()

    def test_dialog_exposes_dynamic_saved_rows(self) -> None:
        dialog = MapMarkerSettingsDialog(
            [
                {"input": "mouse4", "action": "microwave_white"},
                {"input": "f10", "action": "challenge_shrine"},
            ]
        )
        try:
            self.assertEqual(len(dialog.bindings), 2)
            dialog._remove(0)
            self.assertEqual(
                dialog.bindings,
                [{"input": "f10", "action": "challenge_shrine"}],
            )
        finally:
            dialog.close()

    def test_automatic_discovery_is_a_separate_opt_in(self) -> None:
        dialog = MapMarkerSettingsDialog([])
        try:
            self.assertFalse(dialog.automatic_discovery)
            dialog.automatic_discovery_cb.setChecked(True)
            self.assertTrue(dialog.automatic_discovery)
        finally:
            dialog.close()

    def test_classic_marker_style_is_an_optional_checkbox(self) -> None:
        modern = MapMarkerSettingsDialog([])
        classic = MapMarkerSettingsDialog([], style="classic")
        try:
            self.assertEqual(modern.marker_style, "modern")
            self.assertFalse(modern.classic_style_cb.isChecked())
            self.assertEqual(classic.marker_style, "classic")
            classic.classic_style_cb.setChecked(False)
            self.assertEqual(classic.marker_style, "modern")
        finally:
            modern.close()
            classic.close()

    def test_behavior_switches_share_one_compact_row_before_premium(self) -> None:
        dialog = MapMarkerSettingsDialog([], has_premium_access=True)
        try:
            dialog.show()
            QApplication.processEvents()

            automatic_position = dialog.automatic_discovery_cb.mapTo(
                dialog, QPoint(0, 0)
            )
            classic_position = dialog.classic_style_cb.mapTo(
                dialog, QPoint(0, 0)
            )
            premium_position = dialog.premium_card.mapTo(dialog, QPoint(0, 0))

            self.assertLess(automatic_position.x(), classic_position.x())
            self.assertLessEqual(
                abs(automatic_position.y() - classic_position.y()), 2
            )
            self.assertLess(classic_position.y(), premium_position.y())
            # The two Premium features stay compact in one paired row.
            self.assertLessEqual(dialog.premium_card.height(), 225)
            self.assertEqual(dialog.premium_card.objectName(), "mapMarkerPremiumGroup")
            self.assertEqual(dialog.premium_card.styleSheet(), "")
        finally:
            dialog.close()

    def test_locked_placeholders_preserve_saved_premium_settings(self) -> None:
        open_support = MagicMock()
        locked = MapMarkerSettingsDialog(
            [],
            minimap_enabled=True,
            merchant_memory_enabled=True,
            open_support_settings=open_support,
        )
        active = MapMarkerSettingsDialog(
            [],
            minimap_enabled=True,
            minimap_scale=1.4,
            merchant_memory_enabled=True,
            merchant_stock_display="cursor",
            has_premium_access=True,
        )
        try:
            locked.show()
            QApplication.processEvents()

            self.assertIsInstance(locked.minimap_enabled_switch, QCheckBox)
            self.assertIsInstance(locked.merchant_memory_switch, QCheckBox)
            self.assertFalse(locked.minimap_enabled_switch.isEnabled())
            self.assertFalse(locked.merchant_memory_switch.isEnabled())
            self.assertFalse(locked.minimap_enabled_switch.isVisible())
            self.assertFalse(locked.merchant_memory_switch.isVisible())
            self.assertFalse(locked.minimap_scale_spin.isVisible())
            self.assertFalse(locked.merchant_stock_display_combo.isVisible())
            self.assertTrue(locked.minimap_enabled)
            self.assertTrue(locked.merchant_memory_enabled)
            for row in (locked.minimap_row, locked.merchant_row):
                self.assertIsNotNone(row.findChild(QLabel, "PremiumFeatureLockedStatus"))
            self.assertEqual(
                locked.minimap_enabled_switch.objectName(),
                "PremiumFeatureCheck",
            )
            self.assertEqual(locked.premium_group_badge.text(), "Premium")
            self.assertFalse(locked.premium_group_badge.icon().isNull())
            self.assertEqual(
                locked.premium_group_badge.property("premiumState"),
                "locked",
            )
            self.assertIs(
                locked.premium_group_badge.parentWidget(),
                locked.premium_card,
            )
            title_geometry = locked.premium_group_badge.geometry()
            self.assertGreaterEqual(title_geometry.left(), 0)
            self.assertGreaterEqual(title_geometry.top(), 0)
            self.assertLessEqual(title_geometry.right(), locked.premium_card.width())
            self.assertEqual(title_geometry.height(), 26)
            self.assertEqual(locked.premium_group_badge.iconSize(), QSize(15, 15))
            self.assertLess(
                locked.minimap_row.geometry().right(),
                locked.merchant_row.geometry().left(),
            )
            locked.premium_group_badge.click()
            open_support.assert_called_once_with()

            self.assertTrue(active.minimap_enabled_switch.isEnabled())
            self.assertTrue(active.merchant_memory_switch.isEnabled())
            self.assertEqual(
                active.premium_group_badge.property("premiumState"),
                "active",
            )
            self.assertTrue(active.minimap_enabled)
            self.assertAlmostEqual(active.minimap_scale, 1.4)
            self.assertTrue(active.merchant_memory_enabled)
            self.assertEqual(active.merchant_stock_display, "cursor")
            active.show()
            QApplication.processEvents()
            self.assertTrue(active.minimap_enabled_switch.isVisible())
            self.assertTrue(active.merchant_memory_switch.isVisible())
            for dialog in (locked, active):
                notes = [row.findChild(QLabel, "PremiumFeatureNote")
                         for row in (dialog.minimap_row, dialog.merchant_row)]
                positions = [note.mapTo(dialog, QPoint(0, 0)).y() for note in notes]
                self.assertLessEqual(abs(positions[0] - positions[1]), 2)
        finally:
            locked.close()
            active.close()

    def test_empty_state_text_and_add_button_use_the_available_space(self) -> None:
        dialog = MapMarkerSettingsDialog([])
        try:
            dialog.show()
            QApplication.processEvents()

            note = next(
                label
                for label in dialog.findChildren(QLabel)
                if label.text().startswith("Add one exact marker")
            )
            self.assertGreater(note.width(), 500)
            self.assertGreaterEqual(note.height(), note.heightForWidth(note.width()))

            save_btn = dialog.findChild(QPushButton, "primary")
            self.assertIsNotNone(save_btn)
            self.assertIs(dialog.add_btn.parentWidget(), save_btn.parentWidget())
            self.assertLessEqual(
                abs(dialog.add_btn.geometry().center().y() - save_btn.geometry().center().y()),
                1,
            )
        finally:
            dialog.close()

    def test_recorder_captures_a_keyboard_chord(self) -> None:
        recorder = InputBindingRecorder()
        recorder.start_recording()
        event = QKeyEvent(
            QKeyEvent.KeyPress,
            Qt.Key_F10,
            Qt.ControlModifier,
        )
        recorder.keyPressEvent(event)
        self.assertEqual(recorder.binding, "ctrl+f10")

    def test_recorder_captures_mouse_4(self) -> None:
        recorder = InputBindingRecorder()
        recorder.start_recording()
        event = QMouseEvent(
            QEvent.MouseButtonPress,
            QPointF(1, 1),
            QPointF(1, 1),
            Qt.BackButton,
            Qt.BackButton,
            Qt.NoModifier,
        )
        recorder.mousePressEvent(event)
        self.assertEqual(recorder.binding, "mouse4")

    def test_binding_dialog_lists_every_exact_marker_action(self) -> None:
        dialog = MapMarkerBindingDialog()
        try:
            # Two visual separators are not actions and carry no item data.
            action_ids = {
                dialog.action_combo.itemData(index)
                for index in range(dialog.action_combo.count())
                if dialog.action_combo.itemData(index)
            }
            self.assertEqual(len(action_ids), 15)
            self.assertIn("balance_shrine", action_ids)
            self.assertIn("egg", action_ids)
            self.assertIn("sus_bush", action_ids)
            for action_id in (
                "microwave_white",
                "shady_guy_white",
                "moai",
                "balance_shrine",
                "egg",
                "sus_bush",
            ):
                index = dialog.action_combo.findData(action_id)
                self.assertGreaterEqual(index, 0)
                self.assertFalse(dialog.action_combo.itemIcon(index).isNull())
        finally:
            dialog.close()

    def test_nested_binding_dialog_is_deleted_after_exec(self) -> None:
        editor = SimpleNamespace(
            exec=MagicMock(return_value=MapMarkerBindingDialog.Accepted),
            binding={"input": "f10", "action": "moai"},
            deleteLater=MagicMock(),
        )
        dialog = MapMarkerSettingsDialog(
            [], binding_dialog_factory=lambda _binding, _parent: editor
        )
        try:
            dialog._open_editor(None)
            self.assertEqual(dialog.bindings, [{"input": "f10", "action": "moai"}])
            editor.deleteLater.assert_called_once_with()
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
