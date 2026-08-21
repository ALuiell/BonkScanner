from __future__ import annotations

import unittest

import src  # noqa: F401 -- test path bootstrap
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

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

    def test_marker_settings_clamp_scale_and_default_to_disabled(self) -> None:
        self.assertEqual(
            normalize_map_marker_settings({"scale": 99, "hotkeys": "bad"}),
            {
                "enabled": False,
                "automatic_discovery": False,
                "scale": 3.0,
                "hotkeys": [],
            },
        )
        self.assertTrue(
            normalize_map_marker_settings({"automatic_discovery": True})[
                "automatic_discovery"
            ]
        )

    def test_plain_game_controls_are_reserved_but_modified_keys_work(self) -> None:
        self.assertIsNone(normalize_input_binding("tab"))
        self.assertIsNone(normalize_input_binding("w"))
        self.assertEqual(normalize_input_binding("Ctrl+W"), "ctrl+w")
        self.assertEqual(display_input_binding("mouse_middle"), "Middle Mouse")


class MapMarkerSettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

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
            self.assertEqual(len(action_ids), 14)
            self.assertIn("egg", action_ids)
            self.assertIn("sus_bush", action_ids)
            for action_id in ("moai", "egg", "sus_bush"):
                index = dialog.action_combo.findData(action_id)
                self.assertGreaterEqual(index, 0)
                self.assertFalse(dialog.action_combo.itemIcon(index).isNull())
        finally:
            dialog.close()


if __name__ == "__main__":
    unittest.main()
