from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import src
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from app import config
from gui_in_game_overlay_settings import (
    IGO_SCALE_SPIN_ATTRIBUTES,
    IN_GAME_WIDGET_ROWS,
    WEAPON_TRACKER_LAYOUT_DEBOUNCE_MS,
    WeaponTrackerSettingsDialog,
    _build_igo_widgets_card,
    _igo_widget_options,
    _open_map_marker_settings_dialog,
    refresh_map_marker_settings_summary,
    refresh_weapon_tracker_settings_summary,
)
from gui_in_game_overlay import InGameOverlay


class WeaponTrackerSettingsDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.overlay = config.normalize_in_game_overlay_config(
            {
                "widgets": {
                    "weapon_tracker": {
                        "enabled": True,
                        "selected_stats": ["damage", "size"],
                        "layout": "compact",
                    }
                }
            }
        )
        self.parent = SimpleNamespace(
            apply_in_game_overlay_settings_calls=0,
            apply_in_game_overlay_settings=lambda: setattr(
                self.parent,
                "apply_in_game_overlay_settings_calls",
                self.parent.apply_in_game_overlay_settings_calls + 1,
            ),
            igo_weapon_tracker_summary_label=QLabel(),
            _open_weapon_tracker_settings_dialog=MagicMock(),
            _on_igo_settings_changed=MagicMock(),
            _queue_igo_weapon_tracker_layout_change=MagicMock(),
            _apply_igo_weapon_tracker_layout_change=MagicMock(),
        )

    def test_weapon_tracker_is_registered_as_one_settings_row(self) -> None:
        rows = [row for row in IN_GAME_WIDGET_ROWS if row[0] == "weapon_tracker"]

        self.assertEqual(
            rows,
            [("weapon_tracker", "Weapon Tracker", "igo_weapon_tracker_cb")],
        )

    def test_dialog_loads_only_six_independent_metrics(self) -> None:
        with patch.object(config, "IN_GAME_OVERLAY", self.overlay):
            dialog = WeaponTrackerSettingsDialog(self.parent)
            try:
                self.assertEqual(len(dialog.metric_checkboxes), 6)
                self.assertTrue(dialog.metric_checkboxes["damage"].isChecked())
                self.assertTrue(dialog.metric_checkboxes["size"].isChecked())
                self.assertFalse(dialog.metric_checkboxes["crit_chance"].isChecked())
                self.assertFalse(dialog.metric_checkboxes["crit_damage"].isChecked())
                self.assertFalse(hasattr(dialog, "layout_combo"))
            finally:
                dialog.close()

    def test_save_preserves_explicit_empty_selection_and_current_layout(self) -> None:
        with patch.object(config, "IN_GAME_OVERLAY", self.overlay), patch.object(
            config, "save_config"
        ) as save_config:
            dialog = WeaponTrackerSettingsDialog(self.parent)
            try:
                for checkbox in dialog.metric_checkboxes.values():
                    checkbox.setChecked(False)

                dialog._save_settings()

                settings = self.overlay["widgets"]["weapon_tracker"]
                self.assertEqual(settings["selected_stats"], [])
                self.assertEqual(settings["layout"], "compact")
                self.assertEqual(dialog.result(), QDialog.Accepted)
                self.assertEqual(
                    self.parent.apply_in_game_overlay_settings_calls, 1
                )
                self.assertEqual(
                    self.parent.igo_weapon_tracker_summary_label.text(),
                    "0 stats",
                )
                save_config.assert_called_once_with(config.user_config)
            finally:
                dialog.close()

    def test_cancel_does_not_mutate_or_persist_settings(self) -> None:
        with patch.object(config, "IN_GAME_OVERLAY", self.overlay), patch.object(
            config, "save_config"
        ) as save_config:
            dialog = WeaponTrackerSettingsDialog(self.parent)
            try:
                dialog.metric_checkboxes["damage"].setChecked(False)
                dialog.reject()

                self.assertEqual(
                    self.overlay["widgets"]["weapon_tracker"]["selected_stats"],
                    ["damage", "size"],
                )
                self.assertEqual(
                    self.overlay["widgets"]["weapon_tracker"]["layout"],
                    "compact",
                )
                save_config.assert_not_called()
            finally:
                dialog.close()

    def test_summary_uses_approved_shape(self) -> None:
        with patch.object(config, "IN_GAME_OVERLAY", self.overlay):
            refresh_weapon_tracker_settings_summary(self.parent)

        self.assertEqual(
            self.parent.igo_weapon_tracker_summary_label.text(),
            "2 stats",
        )

    def test_options_row_debounces_rapid_layout_switching(self) -> None:
        self.parent._queue_igo_weapon_tracker_layout_change = (
            lambda *_args: InGameOverlay._queue_igo_weapon_tracker_layout_change(
                self.parent
            )
        )
        with patch.object(config, "IN_GAME_OVERLAY", self.overlay):
            holder = _igo_widget_options(self.parent, "weapon_tracker")
            try:
                combo = self.parent.igo_weapon_tracker_layout_combo
                self.assertEqual(combo.currentData(), "compact")
                self.assertEqual(
                    self.parent.igo_weapon_tracker_summary_label.text(),
                    "2 stats",
                )

                compact_index = combo.findData("compact")
                detailed_index = combo.findData("detailed")
                for _ in range(50):
                    combo.setCurrentIndex(detailed_index)
                    combo.setCurrentIndex(compact_index)
                combo.setCurrentIndex(detailed_index)

                self.assertEqual(combo.currentData(), "detailed")
                self.assertEqual(
                    self.overlay["widgets"]["weapon_tracker"]["layout"],
                    "detailed",
                )
                self.parent._apply_igo_weapon_tracker_layout_change.assert_not_called()
                timer = self.parent.igo_weapon_tracker_layout_apply_timer
                self.assertTrue(timer.isSingleShot())
                self.assertEqual(timer.interval(), WEAPON_TRACKER_LAYOUT_DEBOUNCE_MS)
                self.assertTrue(timer.isActive())

                timer.stop()
                timer.timeout.emit()

                self.parent._apply_igo_weapon_tracker_layout_change.assert_called_once()
            finally:
                if holder is not None:
                    holder.deleteLater()

    def test_composite_option_rows_follow_action_mode_checkbox_order(self) -> None:
        self.parent._open_igo_widget_settings_dialog = MagicMock()
        self.parent._open_build_progression_dialog = MagicMock()
        overlay = config.normalize_in_game_overlay_config({})

        def direct_controls(holder):
            layout = holder.layout()
            return [
                layout.itemAt(index).widget()
                for index in range(layout.count())
                if layout.itemAt(index).widget() is not None
            ]

        with patch.object(config, "IN_GAME_OVERLAY", overlay):
            luck = _igo_widget_options(self.parent, "luck_rarity")
            build = _igo_widget_options(self.parent, "build_progression")
            weapon = _igo_widget_options(self.parent, "weapon_tracker")
        try:
            self.assertEqual(
                [type(control) for control in direct_controls(luck)],
                [QComboBox, QCheckBox, QCheckBox],
            )
            self.assertEqual(
                [type(control) for control in direct_controls(build)],
                [QPushButton, QSpinBox, QCheckBox],
            )
            self.assertEqual(
                [type(control) for control in direct_controls(weapon)],
                [QPushButton, QLabel, QComboBox, QCheckBox],
            )
        finally:
            for holder in (luck, build, weapon):
                holder.deleteLater()

    def test_every_inline_options_row_keeps_checkboxes_as_final_group(self) -> None:
        self.parent._open_igo_widget_settings_dialog = MagicMock()
        self.parent._open_build_progression_dialog = MagicMock()
        overlay = config.normalize_in_game_overlay_config({})
        holders = []
        try:
            with patch.object(config, "IN_GAME_OVERLAY", overlay):
                for widget_id, _label, _attribute in IN_GAME_WIDGET_ROWS:
                    holder = _igo_widget_options(self.parent, widget_id)
                    if holder is None:
                        continue
                    holders.append(holder)
                    layout = holder.layout()
                    controls = [
                        layout.itemAt(index).widget()
                        for index in range(layout.count())
                        if layout.itemAt(index).widget() is not None
                    ]
                    first_checkbox = next(
                        (
                            index
                            for index, control in enumerate(controls)
                            if isinstance(control, QCheckBox)
                        ),
                        len(controls),
                    )
                    self.assertTrue(
                        all(
                            isinstance(control, QCheckBox)
                            for control in controls[first_checkbox:]
                        ),
                        f"{widget_id} has a non-checkbox after its checkbox group",
                    )
        finally:
            for holder in holders:
                holder.deleteLater()

    def test_debounced_layout_apply_only_repaints_tracker_and_saves(self) -> None:
        parent = SimpleNamespace(_overlay_fast_tick=MagicMock())
        with patch.object(config, "save_config") as save_config:
            InGameOverlay._apply_igo_weapon_tracker_layout_change(parent)

        parent._overlay_fast_tick.assert_called_once_with()
        save_config.assert_called_once_with(config.user_config)

    def test_table_saver_persists_inline_layout_and_applies_immediately(self) -> None:
        class _Toggle:
            def __init__(self, checked: bool) -> None:
                self._checked = checked

            def isChecked(self) -> bool:
                return self._checked

        class _Value:
            def __init__(self, value) -> None:
                self._value = value

            def value(self):
                return self._value

        parent = SimpleNamespace(
            igo_auto_start_cb=_Toggle(False),
            igo_map_markers_cb=None,
            igo_map_markers_scale_spin=None,
            igo_weapon_tracker_layout_combo=SimpleNamespace(
                currentData=lambda: "detailed"
            ),
            igo_weapon_tracker_layout_apply_timer=MagicMock(),
            apply_in_game_overlay_settings=MagicMock(),
        )
        for widget_id, _label, attribute in IN_GAME_WIDGET_ROWS:
            setattr(
                parent,
                attribute,
                _Toggle(self.overlay["widgets"][widget_id]["enabled"]),
            )
            setattr(parent, IGO_SCALE_SPIN_ATTRIBUTES[widget_id], _Value(1.0))

        with patch.object(config, "IN_GAME_OVERLAY", self.overlay), patch.object(
            config, "save_config"
        ) as save_config:
            InGameOverlay._on_igo_settings_changed(parent)

        self.assertEqual(
            self.overlay["widgets"]["weapon_tracker"]["layout"], "detailed"
        )
        parent.igo_weapon_tracker_layout_apply_timer.stop.assert_called_once_with()
        parent.apply_in_game_overlay_settings.assert_called_once_with()
        save_config.assert_called_once_with(config.user_config)

    def test_map_marker_dialog_saves_classic_style_and_updates_summary(self) -> None:
        marker_config = {
            "enabled": True,
            "automatic_discovery": False,
            "style": "modern",
            "scale": 1.0,
            "hotkeys": [],
        }
        overlay = {"map_markers": marker_config}
        dialog = SimpleNamespace(
            exec=MagicMock(return_value=QDialog.Accepted),
            bindings=[{"input": "f10", "action": "moai"}],
            automatic_discovery=True,
            marker_style="classic",
            minimap_enabled=True,
            minimap_scale=1.2,
            merchant_memory_enabled=True,
            merchant_stock_display="cursor",
            deleteLater=MagicMock(),
        )
        parent = SimpleNamespace(
            tab_in_game_overlay=None,
            igo_map_markers_summary=QLabel(),
            _rebind_hotkeys=MagicMock(),
            _has_premium_access=MagicMock(return_value=True),
            _open_support_settings=MagicMock(),
        )
        with patch.object(config, "IN_GAME_OVERLAY", overlay), patch(
            "gui_in_game_overlay_settings.MapMarkerSettingsDialog",
            return_value=dialog,
        ) as dialog_factory, patch.object(config, "save_config") as save_config:
            _open_map_marker_settings_dialog(parent)

        dialog_factory.assert_called_once_with(
            [],
            None,
            automatic_discovery=False,
            style="modern",
            minimap_enabled=True,
            minimap_scale=1.0,
            merchant_memory_enabled=True,
            merchant_stock_display="smart",
            has_premium_access=True,
            open_support_settings=parent._open_support_settings,
        )
        self.assertTrue(marker_config["automatic_discovery"])
        self.assertEqual(marker_config["style"], "classic")
        self.assertEqual(marker_config["hotkeys"], dialog.bindings)
        self.assertTrue(marker_config["minimap_enabled"])
        self.assertEqual(marker_config["minimap_scale"], 1.2)
        self.assertTrue(marker_config["merchant_memory_enabled"])
        self.assertNotIn("merchant_prices_enabled", marker_config)
        self.assertEqual(marker_config["merchant_stock_display"], "cursor")
        self.assertIn("Classic", parent.igo_map_markers_summary.text())
        parent._rebind_hotkeys.assert_called_once_with()
        save_config.assert_called_once_with(config.user_config)
        dialog.deleteLater.assert_called_once_with()

    def test_map_marker_summary_sits_immediately_after_settings_button(self) -> None:
        parent = SimpleNamespace(
            _on_igo_settings_changed=MagicMock(),
            _open_igo_widget_settings_dialog=MagicMock(),
            _open_build_progression_dialog=MagicMock(),
            _open_weapon_tracker_settings_dialog=MagicMock(),
            _apply_igo_weapon_tracker_layout_change=MagicMock(),
            _queue_igo_weapon_tracker_layout_change=MagicMock(),
            _has_premium_access=MagicMock(return_value=True),
        )
        host = QWidget()
        column = QVBoxLayout(host)
        try:
            with patch.object(config, "IN_GAME_OVERLAY", self.overlay):
                _build_igo_widgets_card(parent, column)

            button = parent.igo_map_markers_settings_btn
            premium_icon = parent.igo_map_markers_premium_icon
            summary = parent.igo_map_markers_summary
            self.assertIs(button.parentWidget(), premium_icon.parentWidget())
            self.assertIs(button.parentWidget(), summary.parentWidget())
            options_layout = button.parentWidget().layout()
            self.assertEqual(options_layout.indexOf(button), 0)
            self.assertEqual(options_layout.indexOf(premium_icon), 1)
            self.assertEqual(options_layout.indexOf(summary), 2)
            self.assertIsNotNone(options_layout.itemAt(3).spacerItem())
            self.assertFalse(premium_icon.pixmap().isNull())
        finally:
            host.close()

    def test_runtime_forwards_map_marker_style_to_painter(self) -> None:
        setter = MagicMock()
        parent = SimpleNamespace(
            _has_premium_access=lambda: True,
            in_game_overlay_window=SimpleNamespace(
                map_marker_layer=SimpleNamespace(set_snapshot=setter)
            )
        )
        snapshot = object()
        overlay = {
            "map_markers": {
                "scale": 1.3,
                "style": "classic",
            }
        }
        with patch.object(config, "IN_GAME_OVERLAY", overlay):
            InGameOverlay._set_map_marker_snapshot(parent, snapshot)

        setter.assert_called_once_with(
            snapshot,
            scale=1.3,
            style="classic",
            minimap_scale=1.0,
            merchant_stock_display="smart",
            cursor_position=None,
        )

    def test_map_marker_summary_names_new_style_by_default(self) -> None:
        parent = SimpleNamespace(igo_map_markers_summary=QLabel())
        with patch.object(
            config,
            "IN_GAME_OVERLAY",
            {"map_markers": {"hotkeys": [], "style": "modern"}},
        ):
            refresh_map_marker_settings_summary(parent)

        self.assertEqual(
            parent.igo_map_markers_summary.text(),
            "Manual only · New style · 0 hotkeys · 2 Premium options",
        )

    def test_map_marker_summary_lists_enabled_premium_features(self) -> None:
        parent = SimpleNamespace(
            igo_map_markers_summary=QLabel(),
            _has_premium_access=lambda: True,
        )
        with patch.object(
            config,
            "IN_GAME_OVERLAY",
            {
                "map_markers": {
                    "hotkeys": [],
                    "style": "modern",
                    "minimap_enabled": True,
                    "merchant_memory_enabled": True,
                }
            },
        ):
            refresh_map_marker_settings_summary(parent)

        self.assertEqual(
            parent.igo_map_markers_summary.text(),
            "Manual only · New style · 0 hotkeys · "
            "Minimap + Shady memory",
        )


if __name__ == "__main__":
    unittest.main()
