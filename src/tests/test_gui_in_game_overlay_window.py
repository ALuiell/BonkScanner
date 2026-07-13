from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import src
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication

import config
from gui_in_game_overlay_window import InGameOverlayWindow


def _test_overlay_config() -> dict:
    return {
        "widgets": {
            "scanner": {"enabled": True, "x": 0, "y": 0, "scale": 1.0},
            "recording": {"enabled": True, "x": 0, "y": 0, "scale": 1.0},
            "kps": {"enabled": True, "x": 0, "y": 0, "scale": 1.0},
            "powerups": {"enabled": True, "x": 0, "y": 0, "scale": 1.0},
            "luck_rarity": {"enabled": True, "x": 0, "y": 0, "scale": 1.0, "show_bar": True},
            "stats": {"enabled": True, "x": 0, "y": 0, "scale": 1.0, "selected_stats": ["Damage", "Difficulty", "XP Gain", "Luck"]},
            "event_timer": {"enabled": True, "x": 0, "y": 0, "scale": 1.0, "warning_seconds": 15},
        }
    }


class InGameOverlayWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def test_sync_geometry_repositions_save_button_in_edit_mode(self) -> None:
        screen_rect = QApplication.primaryScreen().availableGeometry()
        target_rect = QRect(
            screen_rect.left() + 20,
            screen_rect.top() + 20,
            max(320, min(800, screen_rect.width() - 40)),
            max(240, min(600, screen_rect.height() - 40)),
        )

        def current_geometry() -> QRect:
            return target_rect

        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=current_geometry,
            _toggle_igo_edit_mode=lambda: None,
        )

        with patch.object(config, "IN_GAME_OVERLAY", _test_overlay_config()):
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.toggle_edit_mode(True)
                self.assertIsNotNone(window.save_btn)

                window.sync_geometry_to_target()

                self.assertEqual(window.geometry(), target_rect)
                visible_rect = window._visible_local_rect()
                self.assertEqual(window.save_btn.width(), 280)
                self.assertEqual(window.save_btn.height(), 40)
                self.assertEqual(
                    window.save_btn.x(),
                    visible_rect.left() + (visible_rect.width() - window.save_btn.width()) // 2,
                )
                self.assertEqual(
                    window.save_btn.y(),
                    visible_rect.bottom() + 1 - window.save_btn.height() - 60,
                )
            finally:
                window.close()

    def test_save_button_stays_inside_visible_screen_area_when_overlay_bottom_is_offscreen(self) -> None:
        screen_rect = QApplication.primaryScreen().availableGeometry()
        target_rect = QRect(
            screen_rect.left() + 20,
            screen_rect.bottom() - 80,
            max(320, min(800, screen_rect.width() - 40)),
            600,
        )

        def current_geometry() -> QRect:
            return target_rect

        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=current_geometry,
            _toggle_igo_edit_mode=lambda: None,
        )

        with patch.object(config, "IN_GAME_OVERLAY", _test_overlay_config()):
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.toggle_edit_mode(True)
                self.assertIsNotNone(window.save_btn)
                window.sync_geometry_to_target()

                visible_rect = window._visible_local_rect()
                self.assertLessEqual(window.save_btn.y() + window.save_btn.height(), visible_rect.bottom() + 1)
                self.assertGreaterEqual(window.save_btn.y(), visible_rect.top())
            finally:
                window.close()

    def test_sync_geometry_keeps_widgets_inside_smaller_game_window(self) -> None:
        target_rect = QRect(0, 0, 320, 240)
        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=lambda: target_rect,
            _toggle_igo_edit_mode=lambda: None,
        )
        overlay_config = _test_overlay_config()
        overlay_config["widgets"]["stats"]["x"] = 1500
        overlay_config["widgets"]["stats"]["y"] = 900

        with patch.object(config, "IN_GAME_OVERLAY", overlay_config), patch.object(
            config, "save_config"
        ) as save_config:
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.sync_geometry_to_target()
                stats = window.widgets["stats"]

                self.assertGreaterEqual(stats.x(), 0)
                self.assertGreaterEqual(stats.y(), 0)
                self.assertLessEqual(stats.x() + stats.width(), window.width())
                self.assertLessEqual(stats.y() + stats.height(), window.height())
                self.assertEqual(overlay_config["widgets"]["stats"]["x"], stats.x())
                self.assertEqual(overlay_config["widgets"]["stats"]["y"], stats.y())
                save_config.assert_called()
            finally:
                window.close()

    def test_drag_position_is_limited_to_overlay_bounds(self) -> None:
        parent_mixin = SimpleNamespace(
            _in_game_overlay_target_geometry=lambda: QRect(0, 0, 320, 240),
            _toggle_igo_edit_mode=lambda: None,
        )

        with patch.object(config, "IN_GAME_OVERLAY", _test_overlay_config()):
            window = InGameOverlayWindow(parent_mixin)
            try:
                window.sync_geometry_to_target()
                widget = window.widgets["stats"]

                self.assertEqual(widget._clamp_to_parent(QPoint(-50, -20)), QPoint(0, 0))
                self.assertEqual(
                    widget._clamp_to_parent(QPoint(1000, 900)),
                    QPoint(
                        max(0, window.width() - widget.width()),
                        max(0, window.height() - widget.height()),
                    ),
                )
            finally:
                window.close()


if __name__ == "__main__":
    unittest.main()
