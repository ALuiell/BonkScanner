"""Appearance isolation, safe fallback and bounded lifecycle through real Qt UI."""
import src  # noqa: F401
import copy
import json
from pathlib import Path
import tempfile
import os
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtGui import QImage, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton, QTabWidget, QTextEdit, QVBoxLayout, QWidget
import shiboken6

from app import config
from ui.footer import build_footer
from ui.themes import apply_theme, THEME_CONFIG_KEY
from ui.themes.package import read_package
from ui.themes.registry import ThemeCatalog, ThemeEntry
from ui.themes.runtime import AppearanceProvider, load_package

qt = QApplication.instance() or QApplication([])


def flush(window):
    qt.processEvents()
    # Other Qt tests deliberately retain dialogs until process shutdown.
    # Never deliver their queued deletions while verifying this fixture's objects.
    owned = [window, *window.findChildren(QObject)] if shiboken6.isValid(window) else []
    for item in owned:
        if shiboken6.isValid(item):
            QCoreApplication.sendPostedEvents(item, QEvent.DeferredDelete)
    qt.processEvents()


class ThemePackageTests(unittest.TestCase):
    def test_packaged_descriptors_are_complete_and_baseline_has_no_effects(self):
        original = read_package("original")
        halloween = read_package("halloween")
        self.assertEqual(original.provider, "none")
        self.assertEqual(halloween.provider, "halloween")
        self.assertTrue(all(halloween.asset(name) for name in halloween.preset["assets"]))

    def test_left_forest_branch_tips_fit_inside_its_svg_canvas(self):
        package = read_package("halloween")
        renderer = QSvgRenderer(package.asset("forest-left"))
        size = renderer.defaultSize()
        self.assertEqual(size.width(), round(package.parameter("forest_left_width")))
        image = QImage(size, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        rightmost_ink = max(x for x in range(size.width())
                            if any(image.pixelColor(x, y).alpha() > 10 for y in range(size.height())))
        self.assertGreater(rightmost_ink, size.width() - 20)
        self.assertLess(rightmost_ink, size.width() - 2)

    def test_invalid_version_provider_resource_path_and_parameters_fall_back(self):
        base = copy.deepcopy(read_package("halloween").preset)
        variants = [ {**base, "schema_version": 2}, {**base, "runtime_provider": "import:os"},
                     {**base, "assets": {}}, {**base, "parameters": {"pulse_frame_ms": 0}},
                     {**base, "parameters": {"pulse_frame_ms": 16.5}} ]
        for path in ("../outside.svg", "C:/outside.svg", "assets/missing.svg", "assets\\bad.svg"):
            item = copy.deepcopy(base)
            item["assets"]["hat"]["path"] = path
            variants.append(item)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # Preserve valid resources so each case isolates its own validation error.
            import shutil
            shutil.copytree(read_package("halloween").root / "assets", root / "assets")
            for data in variants:
                (root / "preset.json").write_text(json.dumps(data), encoding="utf-8")
                with self.subTest(data=data), patch("ui.themes.package.resource_path", return_value=str(root)):
                    self.assertEqual(load_package("halloween").id, "original")

    def test_optional_missing_art_has_empty_path_and_keeps_package(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            data = {"schema_version": 1, "version": "1", "id": "simple", "runtime_provider": "none",
                    "assets": {"unused": {"path": "assets/missing.svg", "required": False}}}
            (root / "preset.json").write_text(json.dumps(data), encoding="utf-8")
            with patch("ui.themes.package.resource_path", return_value=str(root)):
                self.assertEqual(read_package("simple").asset("unused"), "")

    def test_effect_color_map_keeps_animated_alpha(self):
        from ui.themes.package import ThemePackage
        package = ThemePackage(Path(), {"id": "simple", "effect_color_map": {"#8768B1": "#123456"}})
        from PySide6.QtGui import QColor
        source = QColor("#8768B1")
        source.setAlpha(91)
        self.assertEqual(package.color(source).name(), "#123456")
        self.assertEqual(package.color(source).alpha(), 91)


class AppearanceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.old_controller = getattr(qt, "_desktop_theme_controller", None)
        self.old_sheet = qt.styleSheet()
        self.old_palette = QPalette(qt.palette())
        for item in (patch('ui.footer._read_support_reminder_state', return_value=0),
                     patch('ui.footer._update_support_reminder_state', return_value=SimpleNamespace(success=True)),
                     patch('ui.footer._SupportReminder.start', lambda self: None),
                     patch.object(QApplication, 'applicationState', return_value=Qt.ApplicationActive)):
            item.start()
            self.addCleanup(item.stop)
        self.config = patch.object(config, "user_config", {THEME_CONFIG_KEY: "original"})
        self.config.start()
        self.addCleanup(self.config.stop)
        self.window = QWidget()
        layout = QVBoxLayout(self.window)
        header = QFrame(self.window)
        header.setObjectName("headerBar")
        header.setFixedHeight(90)
        layout.addWidget(header)
        status = QWidget(header)
        status.setObjectName("headerStatusCluster")
        status.setGeometry(0, 0, 180, 50)
        rec = QLabel("REC", header)
        rec.setGeometry(900, 0, 70, 50)
        logo = QLabel(header)
        pixmap = QPixmap(34, 24)
        pixmap.fill(Qt.blue)
        logo.setPixmap(pixmap)
        premium = QPushButton("Premium", header)
        left = QTabWidget(self.window)
        left.addTab(QWidget(), "Templates")
        add = QPushButton("Add", left.currentWidget())
        right = QTabWidget(self.window)
        right.addTab(QWidget(), "Logs")
        logs = QWidget(right.currentWidget())
        editor = QTextEdit(logs)
        editor.resize(700, 350)
        layout.addWidget(left)
        layout.addWidget(right)
        self.owner = SimpleNamespace(window=self.window, rec_flag=rec, logo_label=logo,
            premium_access_badge=premium, left_tabview=left, tabview=right, log_box=logs,
            _templates_panel=SimpleNamespace(add_btn=add), has_premium_access=lambda: False)
        layout.addWidget(build_footer(self.owner))
        self.original_logo = QPixmap(logo.pixmap())
        self.original_icon = premium.icon().cacheKey()
        self.window.resize(1100, 750)
        self.window.show()
        flush(self.window)
        self.addCleanup(self.cleanup)

    def cleanup(self):
        runtime = getattr(self.owner, "_appearance_runtime", None)
        if runtime:
            self.choose("original")
            runtime.dispose()
        self.window.close()
        self.window.deleteLater()
        flush(self.window)
        if self.old_controller is None:
            controller = getattr(qt, "_desktop_theme_controller", None)
            if controller is not None:
                qt.removeEventFilter(controller)
                controller.deleteLater()
                QCoreApplication.sendPostedEvents(controller, QEvent.DeferredDelete)
                del qt._desktop_theme_controller
        qt.setStyleSheet(self.old_sheet)
        qt.setPalette(self.old_palette)
        qt.processEvents()

    def choose(self, theme):
        config.user_config[THEME_CONFIG_KEY] = theme
        result = apply_theme(self.owner)
        flush(self.window)
        return result

    def test_original_start_never_constructs_seasonal_provider(self):
        with patch("ui.themes.providers.halloween.HalloweenProvider", side_effect=AssertionError("seasonal allocation")):
            self.assertEqual(self.choose("original"), "original")
        self.assertIsNone(self.owner._theme_decorations)
        self.assertIsNone(self.owner.footer._support_btn._theme_icon)
        self.assertIsInstance(self.owner._appearance_runtime.active, AppearanceProvider)

    def test_repeated_switches_delete_old_effects_and_restore_logo_corner_and_support(self):
        self.choose("original")
        baseline = len(self.window.findChildren(QWidget))
        for _ in range(4):
            self.assertEqual(self.choose("halloween"), "halloween")
            decor = self.owner._theme_decorations
            clock = decor.animation
            badge = decor.badge
            self.assertTrue(self.owner.footer._reminder.play(force=True))
            spider = self.owner.footer._reminder._presentation
            self.assertEqual(self.choose("original"), "original")
            for item in (decor, clock, badge, spider, spider.art, spider.plaque):
                self.assertFalse(shiboken6.isValid(item))
            self.assertEqual(self.owner.logo_label.pixmap().toImage(), self.original_logo.toImage())
            self.assertEqual(self.owner.premium_access_badge.icon().cacheKey(), self.original_icon)
            self.assertIsNone(self.owner.tabview.cornerWidget(Qt.TopRightCorner))
            self.assertIsNone(self.owner.footer._reminder._presentation)
            self.assertEqual(len(self.window.findChildren(QWidget)), baseline)
        self.assertTrue(self.owner.footer._reminder.play(force=True))
        self.assertTrue(self.owner.footer._reminder.isVisible())

    def test_same_selection_keeps_active_instance_and_frame_cache(self):
        self.choose("halloween")
        decor = self.owner._theme_decorations
        self.choose("halloween")
        self.assertIs(self.owner._theme_decorations, decor)

    def test_narrow_header_keeps_full_forest_behind_badge_during_flare(self):
        self.choose("halloween")
        self.window.resize(900, 750)
        self.owner.rec_flag.move(650, 0)
        flush(self.window)
        decor = self.owner._theme_decorations
        decor._refresh()
        flush(self.window)

        header = decor.header
        status = header.findChild(QWidget, "headerStatusCluster")
        tree_x = header.mapFrom(decor.tree.parentWidget(), decor.tree.pos()).x()
        badge_x = header.mapFrom(decor.badge.parentWidget(), decor.badge.pos()).x()
        self.assertTrue(decor.tree.isVisible())
        self.assertEqual(decor.tree.width(), round(decor.package.parameter("forest_left_width")))
        self.assertEqual(tree_x, status.geometry().right() + 16)
        self.assertGreater(tree_x + decor.tree.width(), badge_x + 40)

        parent = decor.tree.parentWidget()
        self.assertIs(decor.badge.parentWidget(), parent)
        self.assertLess(parent.children().index(decor.tree), parent.children().index(decor.badge))
        decor.animation.timer.stop()
        decor.animation.show_phase(.25)
        flush(self.window)
        self.assertTrue(decor.badge.light.isVisible())
        self.assertLess(parent.children().index(decor.badge.light), parent.children().index(decor.badge))

    def test_package_parameters_drive_clocks_layout_and_presentation(self):
        from ui.themes.package import ThemePackage
        preset = copy.deepcopy(read_package("halloween").preset)
        preset["parameters"].update(pulse_frame_ms=50, pulse_pause_ms=6000,
                                    footer_icon_slot=44, support_read_seconds=12)
        package = ThemePackage(read_package("halloween").root, preset)
        with patch("ui.themes.runtime.load_package", side_effect=lambda theme: package if theme == "halloween" else read_package(theme)):
            self.choose("halloween")
        clock = self.owner._theme_decorations.animation
        self.assertEqual(clock.timer.interval(), 50)
        self.assertEqual(clock.pause_ms, 6000)
        self.assertEqual(self.owner.footer._support_btn._theme_icon.slot_width, 44)
        self.assertTrue(self.owner.footer._reminder.play(force=True))
        self.assertEqual(self.owner.footer._reminder._presentation.read_seconds, 12)

    def test_palette_only_package_gets_no_halloween_and_restores_exact_local_style(self):
        from ui.themes.package import ThemePackage
        package = ThemePackage(Path(), {"schema_version": 1, "version": "1", "id": "simple",
            "color_map": {"#0E1217": "#101010"}, "neutral_color_map": {"#8A94A3": "#123456"}})
        catalog = ThemeCatalog("simple", (ThemeEntry("original", "Default"), ThemeEntry("simple", "Simple")))
        label = QLabel("Late", self.window)
        label.setStyleSheet("color:#8A94A3")
        with patch("ui.themes.theme_catalog", return_value=catalog), patch("ui.themes.runtime.load_package", return_value=package):
            self.assertEqual(self.choose("simple"), "simple")
            label.ensurePolished()
            self.assertEqual(label.styleSheet(), "color:#123456")
            self.assertIsNone(self.owner._theme_decorations)
        self.choose("original")
        self.assertEqual(label.styleSheet(), "color:#8A94A3")

    def _assert_failed_construction_restores_baseline(self, target, failure):
        from ui.themes.providers.halloween_effects.animation import HalloweenAnimation

        self.choose("original")
        corner = QPushButton("Existing control", self.owner.tabview)
        self.owner.tabview.setCornerWidget(corner, Qt.TopRightCorner)
        corner.show()
        flush(self.window)
        baseline = len(self.window.findChildren(QObject))
        self.assertTrue(corner.isVisible())
        for attempt in range(3):
            with self.subTest(attempt=attempt), patch(target, side_effect=failure):
                with self.assertLogs("ui.themes.runtime", level="ERROR"):
                    self.assertEqual(self.choose("halloween"), "original")
                self.assertEqual(config.user_config[THEME_CONFIG_KEY], "halloween")
                self.assertIsNone(self.owner._theme_decorations)
                self.assertEqual(self.window.findChildren(HalloweenAnimation), [])
                self.assertEqual(len(self.window.findChildren(QObject)), baseline)
                self.assertIs(self.owner.tabview.cornerWidget(Qt.TopRightCorner), corner)
                self.assertTrue(corner.isVisible())
        self.assertEqual(self.choose("halloween"), "halloween")
        self.assertEqual(self.choose("original"), "original")
        self.assertEqual(len(self.window.findChildren(QObject)), baseline)
        self.assertIs(self.owner.tabview.cornerWidget(Qt.TopRightCorner), corner)
        self.assertTrue(corner.isVisible())

    def test_provider_constructor_failure_rolls_back_allocated_decorations(self):
        self._assert_failed_construction_restores_baseline(
            "ui.themes.providers.halloween.WebFooterIcon", RuntimeError("footer allocation"))

    def test_decoration_constructor_failure_rolls_back_clock_and_corner(self):
        self._assert_failed_construction_restores_baseline(
            "ui.themes.providers.halloween_effects.header.FireHeader", RuntimeError("header allocation"))

    def test_header_constructor_failure_rolls_back_its_partial_widget(self):
        self._assert_failed_construction_restores_baseline(
            "ui.themes.providers.halloween_effects.header.PumpkinArt", RuntimeError("pumpkin allocation"))

    def test_light_constructor_failure_rolls_back_its_partial_widget(self):
        self._assert_failed_construction_restores_baseline(
            "ui.themes.providers.halloween_effects.header._AmbientLight", RuntimeError("ambient allocation"))

    def test_svg_constructor_failure_rolls_back_its_partial_widget(self):
        from PySide6.QtSvg import QSvgRenderer

        def renderer(path, *args):
            if "forest-right" in str(path):
                raise RuntimeError("renderer allocation")
            return QSvgRenderer(path, *args)

        self._assert_failed_construction_restores_baseline(
            "ui.themes.providers.halloween_effects.decorations.QSvgRenderer", renderer)

    def test_activation_failure_cleans_new_provider_and_restores_baseline(self):
        from ui.themes.providers.halloween import HalloweenProvider
        with patch.object(HalloweenProvider, "activate", side_effect=RuntimeError("test failure")):
            self.assertEqual(self.choose("halloween"), "original")
        self.assertIsNone(self.owner._theme_decorations)
        self.assertEqual(config.user_config[THEME_CONFIG_KEY], "halloween")
        self.assertEqual(self.window.findChildren(QWidget, "seasonalDecoration"), [])
        self.assertEqual(self.owner.footer.frame.height(), 28)


class IsolatedAppearanceTests(unittest.TestCase):
    def test_runtime_in_a_fresh_qt_process(self):
        # Global QSS repolishes every widget, including other tests' retained
        # Settings dialogs. Exercise the complete lifecycle in its own process.
        env = dict(os.environ, QT_QPA_PLATFORM="offscreen", BONKSCANNER_IGNORE_SHARED_STORAGE="1")
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "src.tests.test_theme_runtime.AppearanceRuntimeTests"],
            cwd=Path(__file__).resolve().parents[2], env=env,
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def load_tests(loader, _tests, _pattern):
    return unittest.TestSuite((loader.loadTestsFromTestCase(ThemePackageTests),
                               loader.loadTestsFromTestCase(IsolatedAppearanceTests)))


if __name__ == "__main__":
    unittest.main()
