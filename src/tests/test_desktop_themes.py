from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import src  # noqa: F401
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QLabel, QTabWidget, QVBoxLayout, QWidget

from app import config
from app.config_repository import ConfigRepository
from ui.styles import build_qt_app_stylesheet
from ui.themes import (
    THEME_CONFIG_KEY, LEGACY_THEME_CONFIG_KEY, _ThemeController, load_preset, remap_colors,
    selected_theme, theme_stylesheet,
)


class DesktopThemeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_missing_selection_defaults_to_halloween_and_saved_original_survives_reload(self):
        with patch.object(config, "user_config", {}):
            self.assertEqual(selected_theme(), "halloween")
            with tempfile.TemporaryDirectory() as folder:
                repository = ConfigRepository(Path(folder) / "config.json")
                self.assertTrue(repository.commit({THEME_CONFIG_KEY: "original"}).success)
                config.user_config.update(repository.load().snapshot)
                self.assertEqual(selected_theme(), "original")
                config.user_config[THEME_CONFIG_KEY] = "halloween"
                self.assertEqual(selected_theme(), "halloween")

    def test_only_boolean_legacy_original_selection_is_accepted(self):
        for value in (None, "false", "true", 1, [], {}):
            with self.subTest(value=value), patch.object(config, "user_config", {LEGACY_THEME_CONFIG_KEY: value}):
                self.assertEqual(selected_theme(), "halloween")

    def test_original_sheet_is_unchanged_and_halloween_preserves_behavior_colors(self):
        original = build_qt_app_stylesheet("check.svg")
        self.assertEqual(theme_stylesheet(original, "original"), original)
        halloween = build_qt_app_stylesheet("check.svg", theme="halloween")
        self.assertIn("#8058BA", halloween)
        self.assertIn("#15111C", halloween)
        for color in ("#22C55E", "#FACC15", "#60A5FA", "#E879F9", "#C084FC"):
            self.assertIn(color, original)
            self.assertIn(color, halloween)
            self.assertNotIn(color, load_preset("halloween")["color_map"])

    def test_color_replacements_do_not_cascade_and_preserve_alpha(self):
        mapping = {"#010203": "#040506", "#040506": "#070809"}
        self.assertEqual(remap_colors("#010203 rgba(1, 2, 3, 0.2) #040506", mapping),
                         "#040506 rgba(4,5,6,0.2) #070809")

    def test_logs_footer_reveals_the_rounded_pane_instead_of_a_rectangular_host(self):
        from ui.log_view import LogView

        before = self.app.styleSheet()
        self.addCleanup(self.app.setStyleSheet, before)
        self.app.setStyleSheet(build_qt_app_stylesheet("check.svg", theme="halloween"))
        tabs = QTabWidget()
        self.addCleanup(tabs.close)
        tabs.setObjectName("mainTabs")
        page = QWidget()
        page.setObjectName("mainTabPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        logs = LogView()
        layout.addWidget(logs)
        tabs.addTab(page, "Logs")
        tabs.resize(900, 500)
        tabs.show()
        self.app.processEvents()
        shot = tabs.grab().toImage()
        density = shot.devicePixelRatio()
        point = logs._footer.mapTo(tabs, QPoint(logs._footer.width() - 5, 2))
        self.assertEqual(shot.pixelColor(round(point.x() * density), round(point.y() * density)).name(), "#1b1623")
        # The empty margin above the document must be the very same surface.
        point = logs._document.mapTo(tabs, QPoint(5, -3))
        self.assertEqual(shot.pixelColor(round(point.x() * density), round(point.y() * density)).name(), "#1b1623")

    def test_painted_controls_receive_halloween_colors_and_restore_original(self):
        from ui.shared import LabeledSwitch
        from ui.tabs.player_stats.items_section import CompactItemsSortComboBox

        before = self.app.styleSheet()
        self.addCleanup(self.app.setStyleSheet, before)
        switch = LabeledSwitch("Expanded")
        combo = CompactItemsSortComboBox()
        self.addCleanup(switch.close)
        self.addCleanup(combo.close)
        for theme, expected in (("halloween", "#8058ba"), ("original", "#2f6fb0")):
            self.app.setStyleSheet(build_qt_app_stylesheet("check.svg", theme=theme))
            for widget in (switch, combo):
                widget.ensurePolished()
                widget.style().unpolish(widget)
                widget.style().polish(widget)
            self.assertEqual(switch.property("trackOnColor").name(), expected)
            self.assertEqual(combo.property("glyphActiveColor").name(), "#facc15")

    def test_missing_and_malformed_optional_preset_fall_back_to_original(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "preset.json"
            with patch("ui.themes.package.resource_path", return_value=str(path.parent)):
                self.assertEqual(theme_stylesheet("unchanged", "halloween"), "unchanged")
                path.write_text("[]", encoding="utf-8")
                self.assertEqual(load_preset("halloween")["id"], "original")
                path.write_text('{"id":"halloween","color_map":null}', encoding="utf-8")
                self.assertEqual(load_preset("halloween")["id"], "original")

    def test_dynamic_local_styles_and_late_widgets_restore_without_changing_template_identity(self):
        controller = _ThemeController(self.app)
        controller.preset = load_preset("halloween")
        window = QWidget()
        self.addCleanup(window.close)
        try:
            label = QLabel("Late dialog", window)
            original = "color:#8A94A3;background:#141A22;"
            label.setStyleSheet(original)
            label.ensurePolished()
            self.assertIn("#A79AB8", label.styleSheet())
            label.setStyleSheet("color:#22C55E;background:#0B0F14;")
            self.assertIn("#22C55E", label.styleSheet())
            self.assertIn("#120F19", label.styleSheet())
            template = QLabel("User color", window)
            template.setObjectName("TemplateName")
            template.setStyleSheet("color:#8A94A3;")
            template.ensurePolished()
            self.assertEqual(template.styleSheet(), "color:#8A94A3;")
            controller.preset = load_preset("original")
            controller._adapt_widget(label)
            self.assertEqual(label.styleSheet(), "color:#22C55E;background:#0B0F14;")
        finally:
            self.app.removeEventFilter(controller)
            controller.deleteLater()


if __name__ == "__main__":
    unittest.main()
