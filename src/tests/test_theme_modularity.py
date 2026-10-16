"""A non-Halloween provider proves the extension boundary using real Qt objects."""
import src  # noqa: F401
import ast
from dataclasses import fields
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, QTimer, Qt
from PySide6.QtWidgets import QLabel, QWidget
import shiboken6

from app import config
from ui.themes import THEME_CONFIG_KEY
from ui.themes.contracts import AppearanceProvider, SupportContext, ThemeHost
from ui.themes.host import build_theme_host
from ui.themes.lifecycle import ThemeResources
from ui.themes.package import ThemePackage, original_package, read_package
from ui.themes.providers import ProviderDefinition, register_provider, registered_providers
from ui.themes.registry import ThemeCatalog, ThemeEntry
from ui.themes.runtime import AppearanceRuntime
from src.tests.test_theme_runtime import AppearanceRuntimeTests, flush, qt


def grain_options(preset):
    params = preset.get("parameters", {})
    grain = params.get("grain", 3)
    if set(params) - {"grain"} or type(grain) is not int or not 1 <= grain <= 99:
        raise ValueError("Invalid grain")
    return {"grain": grain}


class StaticIcon:
    """Deliberately has no clock, phases, signals, timers or animation dependency."""
    slot_width = 32
    height = 40

    def __init__(self):
        self.surface = None
        self.update_callback = None
        self.pulses = 0
        self.disposed = False

    def attach(self, surface, request_update):
        self.surface = surface
        self.update_callback = request_update

    def detach(self):
        self.surface = None
        self.update_callback = None

    def refresh(self):
        if self.update_callback:
            self.update_callback()

    def pulse(self):
        self.pulses += 1
        self.refresh()

    def paint(self, painter, start, center_y, density):
        painter.drawText(int(start), int(center_y), "*")

    def dispose(self):
        self.disposed = True
        self.detach()


class PlainPresentation:
    def __init__(self, context):
        self.context = context
        self.resources = ThemeResources()
        self.card = self.resources.own(QLabel("Independent presentation", context.host))
        self.card.hide()
        self.disposed = False
        self.thank_you = False

    def start(self, *, thank_you=False):
        self.thank_you = thank_you
        self.card.show()

    def stop(self):
        self.card.hide()

    def dispose(self):
        self.disposed = True
        self.resources.close()


class GrainProvider(AppearanceProvider):
    """Needs only the window and its own options; no Halloween scene anchors."""
    def prepare(self):
        with self.resources:
            self.label = self.resources.own(QLabel(str(self.package.parameter("grain")), self.host.window))
            self.label.hide()
            self.timer = self.resources.own(QTimer(self.host.window))
            self.timer.start(60000)
            if self.package.parameter("grain") == 13:
                raise RuntimeError("Injected partial preparation failure")
            self.footer_icon = self.resources.own(StaticIcon())
            self.footer_height = 44

    def activate(self):
        self.label.show()

    def create_support(self, context):
        return self.resources.own(PlainPresentation(context))


class ModularityContractTests(unittest.TestCase):
    def test_resources_close_in_reverse_order_even_if_one_cleanup_raises(self):
        order = []
        scope = ThemeResources()
        scope.callback(order.append, "first")
        scope.callback(Mock(side_effect=RuntimeError("cleanup failure")))
        scope.callback(order.append, "last")
        with self.assertLogs("ui.themes.lifecycle", level="ERROR"):
            scope.close()
        scope.close()
        self.assertEqual(order, ["last", "first"])
        with self.assertRaises(RuntimeError):
            scope.callback(lambda: None)

    def test_resources_keep_successful_preparation_and_rollback_failure(self):
        order = []
        with ThemeResources() as scope:
            scope.callback(order.append, "closed")
        self.assertEqual(order, [])
        scope.close()
        self.assertEqual(order, ["closed"])
        with self.assertRaisesRegex(ValueError, "prepare"):
            with ThemeResources() as failed:
                failed.callback(order.append, "failed")
                raise ValueError("prepare")
        self.assertEqual(order, ["closed", "failed"])

    def test_closed_scope_does_not_install_signals_or_event_filters(self):
        scope = ThemeResources()
        scope.close()
        timer = QTimer()
        slot = Mock()
        with self.assertRaises(RuntimeError):
            scope.connect(timer.timeout, slot)
        timer.timeout.emit()
        slot.assert_not_called()
        watched = Mock()
        with self.assertRaises(RuntimeError):
            scope.event_filter(watched, QObject())
        watched.installEventFilter.assert_not_called()

    def test_new_provider_validates_its_own_parameters_and_defaults(self):
        import ui.themes.providers as registry
        with patch.dict(registry._PROVIDERS), tempfile.TemporaryDirectory() as folder:
            register_provider("grain", ProviderDefinition(GrainProvider, grain_options))
            root = Path(folder)
            data = {"schema_version": 1, "version": "1", "id": "grain-skin",
                    "runtime_provider": "grain", "parameters": {"grain": 7}}
            (root / "preset.json").write_text(json.dumps(data), encoding="utf-8")
            with patch("ui.themes.package.resource_path", return_value=str(root)):
                self.assertEqual(read_package("grain-skin").parameter("grain"), 7)
                data["parameters"] = {}
                (root / "preset.json").write_text(json.dumps(data), encoding="utf-8")
                self.assertEqual(read_package("grain-skin").parameter("grain"), 3)
                data["parameters"] = {"grain": True}
                (root / "preset.json").write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ValueError):
                    read_package("grain-skin")
            with self.assertRaises(ValueError):
                register_provider("grain", ProviderDefinition(GrainProvider, grain_options))
            with self.assertRaises(TypeError):
                registered_providers()["other"] = ProviderDefinition(GrainProvider, grain_options)
        self.assertNotIn("grain", registered_providers())

    def test_default_start_does_not_import_effect_implementation(self):
        code = '''import src, sys
from PySide6.QtWidgets import QApplication, QWidget
from ui.themes.contracts import ThemeHost
from ui.themes.runtime import AppearanceRuntime, load_package
qt = QApplication([])
window = QWidget()
runtime = AppearanceRuntime(ThemeHost(window))
assert runtime.switch(load_package("original"), lambda _: None) == "original"
assert not any("halloween_effects" in name for name in sys.modules)
runtime.dispose()
'''
        result = subprocess.run([sys.executable, "-B", "-c", code],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen", BONKSCANNER_IGNORE_SHARED_STORAGE="1"),
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_dependency_boundary_is_enforced_by_source(self):
        root = Path(__file__).resolve().parents[1]
        self.assertNotIn("owner", {field.name for field in fields(ThemeHost)})
        forbidden = {"rec_flag", "_templates_panel", "log_box", "logo_label", "tabview", "left_tabview"}
        for path in (root / "ui/themes/providers").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            self.assertFalse(attributes & forbidden, str(path))
            imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            self.assertFalse(any(name == "gui_app" or name.startswith(("app.", "infra.")) for name in imports), str(path))
        for name in ("runtime.py", "package.py", "contracts.py"):
            tree = ast.parse((root / "ui/themes" / name).read_text(encoding="utf-8"))
            imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
            self.assertFalse(any("halloween" in name for name in imports))
        footer = ast.parse((root / "ui/footer.py").read_text(encoding="utf-8"))
        self.assertFalse(any(isinstance(node, ast.Attribute) and node.attr == "clock" for node in ast.walk(footer)))


class ModularRuntimeTests(unittest.TestCase):
    setUp = AppearanceRuntimeTests.setUp
    cleanup = AppearanceRuntimeTests.cleanup
    choose = AppearanceRuntimeTests.choose

    def install_grain(self, value=7):
        import ui.themes.providers as registry
        registry_patch = patch.dict(registry._PROVIDERS)
        registry_patch.start()
        self.addCleanup(registry_patch.stop)
        register_provider("grain", ProviderDefinition(GrainProvider, grain_options))
        package = ThemePackage(Path(), {"schema_version": 1, "version": "1", "id": "grain-skin",
            "runtime_provider": "grain", "color_map": {}, "parameters": {"grain": value}})
        catalog = ThemeCatalog("original", (ThemeEntry("original", "Default"), ThemeEntry("grain-skin", "Grain")))
        for item in (patch("ui.themes.theme_catalog", return_value=catalog),
                     patch("ui.themes.runtime.load_package", side_effect=lambda theme: package if theme == "grain-skin" else original_package())):
            item.start()
            self.addCleanup(item.stop)
        return package

    def test_static_icon_and_custom_message_work_without_a_clock(self):
        self.install_grain()
        self.choose("original")
        baseline = len(self.window.findChildren(QObject))
        self.assertEqual(self.choose("grain-skin"), "grain-skin")
        provider = self.owner._appearance_runtime.active
        self.assertIsInstance(provider.host, ThemeHost)
        self.assertFalse(hasattr(provider, "owner"))
        self.assertEqual(provider.label.text(), "7")
        link = self.owner.footer._support_btn
        self.assertFalse(hasattr(link._theme_icon, "clock"))
        link.pulse_theme_icon(force=True)
        self.assertEqual(provider.footer_icon.pulses, 1)
        self.assertFalse(link.grab().isNull())
        card = self.owner.footer._reminder
        self.assertTrue(card.play(force=True))
        presentation = card._presentation
        self.assertIsInstance(presentation.context, SupportContext)
        self.assertTrue(presentation.card.isVisible())
        presentation.context.dismiss()
        self.assertFalse(card._playing)
        self.choose("original")
        self.assertTrue(provider.disposed)
        self.assertTrue(provider.footer_icon.disposed)
        self.assertTrue(presentation.disposed)
        self.assertFalse(shiboken6.isValid(provider.label))
        self.assertFalse(shiboken6.isValid(provider.timer))
        self.assertEqual(len(self.window.findChildren(QObject)), baseline)

    def test_partial_preparation_failure_rolls_back_before_default(self):
        self.install_grain(value=13)
        self.choose("original")
        baseline = len(self.window.findChildren(QObject))
        for _ in range(5):
            with self.assertLogs("ui.themes.runtime", level="ERROR"):
                self.assertEqual(self.choose("grain-skin"), "original")
            self.assertEqual(config.user_config[THEME_CONFIG_KEY], "grain-skin")
            self.assertEqual(len(self.window.findChildren(QObject)), baseline)
            self.assertIsNone(self.owner.footer._support_btn._theme_icon)

    def test_minimal_host_runs_palette_and_independent_provider_without_scene_anchors(self):
        package = self.install_grain()
        window = QWidget()
        self.addCleanup(window.deleteLater)
        runtime = AppearanceRuntime(ThemeHost(window))
        self.addCleanup(runtime.dispose)
        self.assertEqual(runtime.switch(original_package(), lambda _: None), "original")
        self.assertEqual(window.findChildren(QTimer), [])
        self.assertEqual(runtime.switch(package, lambda _: None), "grain-skin")
        provider = runtime.active
        runtime.dispose()
        self.assertFalse(provider.timer.isActive())
        runtime.dispose()
        flush(window)
        self.assertFalse(shiboken6.isValid(provider.timer))
        with self.assertRaises(RuntimeError):
            runtime.switch(package, lambda _: None)

    def test_message_creation_failure_uses_standard_card_without_repeated_attempts(self):
        self.install_grain()
        self.choose("grain-skin")
        card = self.owner.footer._reminder
        with patch.object(GrainProvider, "create_support", side_effect=RuntimeError("message allocation")) as create:
            with self.assertLogs("ui.footer", level="ERROR"):
                self.assertTrue(card.play(force=True))
            self.assertTrue(card.isVisible())
            self.assertTrue(card._playing)
            self.assertIsNone(card._presentation)
            card.dismiss()
            self.assertTrue(card.play(force=True))
            create.assert_called_once()
            card.dismiss()
        self.choose("original")
        self.choose("grain-skin")
        self.assertFalse(card._presentation_failed)
        self.assertTrue(card.play(force=True))
        self.assertIsInstance(card._presentation, PlainPresentation)

    def test_message_start_failure_disposes_the_custom_card_before_fallback(self):
        self.install_grain()
        self.choose("grain-skin")
        provider = self.owner._appearance_runtime.active
        original_create = provider.create_support
        created = []

        def create(context):
            presentation = original_create(context)
            created.append(presentation)
            return presentation

        card = self.owner.footer._reminder
        with patch.object(provider, "create_support", side_effect=create), \
                patch.object(PlainPresentation, "start", side_effect=RuntimeError("message start")), \
                self.assertLogs("ui.footer", level="ERROR"):
            self.assertTrue(card.play(force=True))
        self.assertTrue(created[0].disposed)
        flush(self.window)
        self.assertFalse(shiboken6.isValid(created[0].card))
        self.assertTrue(card.isVisible())
        self.assertTrue(card._presentation_failed)

    def test_footer_bind_failure_disposes_prepared_provider_before_default(self):
        self.install_grain()
        self.choose("original")
        baseline = len(self.window.findChildren(QObject))
        runtime = self.owner._appearance_runtime
        original_bind = runtime._bind_footer
        created = []

        def bind(provider):
            original_bind(provider)
            if isinstance(provider, GrainProvider):
                created.append(provider)
                raise RuntimeError("footer bind")

        with patch.object(runtime, "_bind_footer", side_effect=bind), self.assertLogs("ui.themes.runtime", level="ERROR"):
            self.assertEqual(self.choose("grain-skin"), "original")
        self.assertTrue(created[0].disposed)
        self.assertTrue(created[0].footer_icon.disposed)
        self.assertIsNone(self.owner.footer._support_btn._theme_icon)
        self.assertEqual(len(self.window.findChildren(QObject)), baseline)

    def test_failure_inside_clock_constructor_releases_both_partial_qt_objects(self):
        from ui.themes.providers.halloween_effects.animation import HalloweenAnimation
        from PySide6.QtCore import QTimer as NativeTimer
        self.choose("original")
        baseline = len(self.window.findChildren(QObject))
        calls = []

        def timer(parent):
            if calls:
                raise RuntimeError("wake allocation")
            calls.append(NativeTimer(parent))
            return calls[-1]

        with patch("ui.themes.providers.halloween_effects.animation.QTimer", side_effect=timer), \
                self.assertLogs("ui.themes.runtime", level="ERROR"):
            self.assertEqual(self.choose("halloween"), "original")
        self.assertFalse(shiboken6.isValid(calls[0]))
        self.assertEqual(self.window.findChildren(HalloweenAnimation), [])
        self.assertEqual(len(self.window.findChildren(QObject)), baseline)

    def test_spider_partial_constructor_failure_uses_standard_card_without_leaks(self):
        self.choose("halloween")
        baseline = len(self.window.findChildren(QObject))
        card = self.owner.footer._reminder
        with patch("ui.themes.providers.halloween_effects.support._SpiderPlaque", side_effect=RuntimeError("plaque allocation")), \
                self.assertLogs("ui.footer", level="ERROR"):
            self.assertTrue(card.play(force=True))
        flush(self.window)
        self.assertTrue(card.isVisible())
        self.assertEqual(len(self.window.findChildren(QObject)), baseline)

    def test_adapter_geometry_changes_without_exposing_application_objects(self):
        host = build_theme_host(self.owner)
        left, right = host.header.content_span()
        self.owner.rec_flag.move(self.owner.rec_flag.x() - 37, self.owner.rec_flag.y())
        self.assertEqual(host.header.content_span(), (left, right - 37))
        self.assertFalse(hasattr(host, "supporter_access"))
        self.assertFalse(hasattr(host, "_templates_panel"))
        self.owner.left_tabview.addTab(QWidget(), "Other")
        self.owner.left_tabview.setCurrentIndex(1)
        self.assertIsNone(host.templates.available_rect())

    def test_repeated_new_provider_switches_keep_timer_and_object_counts_bounded(self):
        self.install_grain()
        self.choose("original")
        baseline = len(self.window.findChildren(QObject))
        for _ in range(12):
            self.choose("grain-skin")
            provider = self.owner._appearance_runtime.active
            self.choose("grain-skin")
            self.assertIs(self.owner._appearance_runtime.active, provider)
            self.choose("original")
            self.assertEqual(len(self.window.findChildren(QObject)), baseline)


class IsolatedModularRuntimeTests(unittest.TestCase):
    def test_new_provider_in_isolated_qt_process(self):
        result = subprocess.run([sys.executable, "-B", "-m", "unittest",
            "src.tests.test_theme_modularity.ModularRuntimeTests"],
            env=dict(os.environ, QT_QPA_PLATFORM="offscreen", BONKSCANNER_IGNORE_SHARED_STORAGE="1"),
            cwd=Path(__file__).resolve().parents[2], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def load_tests(loader, _tests, _pattern):
    return unittest.TestSuite((loader.loadTestsFromTestCase(ModularityContractTests),
                              loader.loadTestsFromTestCase(IsolatedModularRuntimeTests)))
