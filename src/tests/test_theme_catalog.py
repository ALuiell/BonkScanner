"""Selection persistence and future access policy for built-in appearance packages."""
import src  # noqa: F401
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QWidget
from app import config
from ui.themes import (
    THEME_CONFIG_KEY, LEGACY_THEME_CONFIG_KEY, _ThemeAccessBinding,
    _bind_theme_access, premium_access_for_themes, resolved_theme, selected_theme,
)
from ui.themes.registry import ThemeCatalog, ThemeEntry, theme_catalog
from ui.themes.selector import ThemeSelector

qt = QApplication.instance() or QApplication([])
PUBLIC = ThemeCatalog("halloween", (ThemeEntry("original", "Default"), ThemeEntry("halloween", "Halloween")))
PAID = ThemeCatalog("original", (ThemeEntry("original", "Default"), ThemeEntry("halloween", "Halloween", "premium")))


class ThemeCatalogTests(unittest.TestCase):
    def test_saved_id_wins_and_legacy_choice_is_read_without_writing(self):
        for data, expected in (
            ({}, "halloween"), ({LEGACY_THEME_CONFIG_KEY: True}, "original"),
            ({LEGACY_THEME_CONFIG_KEY: False}, "halloween"),
            ({THEME_CONFIG_KEY: "original", LEGACY_THEME_CONFIG_KEY: False}, "original"),
            ({THEME_CONFIG_KEY: "halloween", LEGACY_THEME_CONFIG_KEY: True}, "halloween"),
            ({THEME_CONFIG_KEY: "future-theme"}, "future-theme"),
            ({THEME_CONFIG_KEY: "../../outside"}, "halloween"),
        ):
            with self.subTest(data=data), patch.object(config, "user_config", data), patch("ui.themes.theme_catalog", return_value=PUBLIC):
                before = dict(data)
                self.assertEqual(selected_theme(), expected)
                self.assertEqual(data, before)

    def test_release_default_does_not_override_saved_choice(self):
        with patch("ui.themes.theme_catalog", return_value=PAID):
            with patch.object(config, "user_config", {}):
                self.assertEqual(selected_theme(), "original")
            with patch.object(config, "user_config", {THEME_CONFIG_KEY: "halloween"}):
                self.assertEqual(selected_theme(), "halloween")

    def test_catalog_is_cached_and_invalid_policy_falls_back_to_public_default(self):
        valid = {"schema_version": 1, "default_theme": "halloween", "themes": [
            {"id": "original", "name": "Default", "access": "public"},
            {"id": "halloween", "name": "Halloween", "access": "public"}]}
        variants = [valid, [], {**valid, "schema_version": 2},
                    {**valid, "default_theme": "missing"},
                    {**valid, "themes": [valid["themes"][1]]},
                    {**valid, "themes": [*valid["themes"], valid["themes"][0]]},
                    {**valid, "themes": [{"id": "original", "name": "Default", "access": "premium"}]},
                    {**valid, "themes": [{"id": "../outside", "name": "Invalid"}]}]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "catalog.json"
            for index, data in enumerate(variants):
                with self.subTest(index=index), patch("ui.themes.registry.resource_path", return_value=str(path)):
                    path.write_text(json.dumps(data), encoding="utf-8")
                    theme_catalog.cache_clear()
                    catalog = theme_catalog()
                    self.assertIs(theme_catalog(), catalog)
                    self.assertEqual(catalog.default_theme, "halloween" if index == 0 else "original")
        theme_catalog.cache_clear()
        self.addCleanup(theme_catalog.cache_clear)

    def test_missing_catalog_is_safe_without_optional_assets(self):
        theme_catalog.cache_clear()
        self.addCleanup(theme_catalog.cache_clear)
        with patch("ui.themes.registry.resource_path", return_value="Z:/missing/catalog.json"):
            self.assertEqual(theme_catalog().themes, (ThemeEntry("original", "Default"),))

    def test_current_public_catalog_does_not_query_or_subscribe_to_premium(self):
        owner = SimpleNamespace(has_premium_access=Mock(), supporter_access=Mock())
        with patch("ui.themes.theme_catalog", return_value=PUBLIC):
            self.assertFalse(premium_access_for_themes(owner))
            _bind_theme_access(owner)
        owner.has_premium_access.assert_not_called()
        owner.supporter_access.add_listener.assert_not_called()

    def test_future_premium_release_falls_back_without_losing_desired_id(self):
        data = {THEME_CONFIG_KEY: "halloween"}
        owner = SimpleNamespace(has_premium_access=lambda: False)
        with patch.object(config, "user_config", data), patch("ui.themes.theme_catalog", return_value=PAID):
            self.assertEqual(resolved_theme(owner), "original")
            self.assertEqual(data[THEME_CONFIG_KEY], "halloween")
            owner.has_premium_access = lambda: True
            self.assertEqual(resolved_theme(owner), "halloween")

    def test_future_paid_default_is_not_applied_to_non_premium(self):
        catalog = ThemeCatalog("halloween", PAID.themes)
        self.assertEqual(catalog.resolve("missing", premium=False), "original")

    def test_selector_has_two_public_choices_and_preserves_missing_choice_on_refresh(self):
        with patch.object(config, "user_config", {THEME_CONFIG_KEY: "halloween"}), patch("ui.themes.selector.theme_catalog", return_value=PUBLIC):
            combo = ThemeSelector(SimpleNamespace())
            self.addCleanup(combo.deleteLater)
            self.assertEqual([combo.itemText(i) for i in range(combo.count())], ["Default", "Halloween"])
            self.assertEqual(combo.currentData(), "halloween")
            self.assertTrue(all(combo.model().item(i).isEnabled() for i in range(combo.count())))
            changes = Mock()
            combo.currentIndexChanged.connect(changes)
            combo.reload()
            changes.assert_not_called()
            with patch.object(config, "user_config", {THEME_CONFIG_KEY: "missing"}):
                combo.reload()
                self.assertEqual(combo.currentData(), "missing")
                self.assertFalse(combo.model().item(combo.currentIndex()).isEnabled())

    def test_future_premium_choice_is_labeled_and_disabled_without_access(self):
        with patch.object(config, "user_config", {THEME_CONFIG_KEY: "halloween"}), \
                patch("ui.themes.theme_catalog", return_value=PAID), \
                patch("ui.themes.selector.theme_catalog", return_value=PAID):
            owner = SimpleNamespace(has_premium_access=lambda: False)
            combo = ThemeSelector(owner)
            self.addCleanup(combo.deleteLater)
            index = combo.findData("halloween")
            self.assertIn("Premium", combo.itemText(index))
            self.assertFalse(combo.model().item(index).isEnabled())
            owner.has_premium_access = lambda: True
            combo.reload()
            self.assertTrue(combo.model().item(index).isEnabled())

    def _access_fixture(self, *, online=True, remaining=30):
        from datetime import datetime, timedelta, timezone
        from app.supporter_access import OFFLINE_GRACE, SupporterAccessController, SupporterAccessState
        from ui.themes.runtime import AppearanceRuntime

        clock = {"now": datetime(2026, 10, 13, tzinfo=timezone.utc)}
        access = SupporterAccessController(client=Mock(), schedule=lambda *_args: None,
            is_shutting_down=lambda: False, get_key=lambda: "", now=lambda: clock["now"])
        access._state = SupporterAccessState(status="active_subscription", active=True,
            online=online, checked_at=clock["now"] if online else clock["now"] - OFFLINE_GRACE + timedelta(seconds=remaining),
            expires_at=clock["now"] + timedelta(seconds=remaining) if online else clock["now"] + timedelta(days=10))
        window = QWidget()
        self.addCleanup(window.deleteLater)
        owner = SimpleNamespace(window=window, supporter_access=access,
            has_premium_access=access.has_premium_access, _visual_theme="halloween")
        from ui.themes.contracts import ThemeHost
        owner._appearance_runtime = AppearanceRuntime(ThemeHost(owner.window))
        self.addCleanup(owner._appearance_runtime.dispose)
        for item in (patch.object(config, "user_config", {THEME_CONFIG_KEY: "halloween"}),
                     patch("ui.themes.theme_catalog", return_value=PAID)):
            item.start()
            self.addCleanup(item.stop)
        _bind_theme_access(owner)
        binding = owner._theme_access_binding
        self.addCleanup(binding.close)
        return clock, access, owner, binding

    def test_expiry_and_offline_grace_refresh_without_access_publication(self):
        if os.environ.get("BONKSCANNER_THEME_EXPIRY_CHILD") != "1":
            # QSignalSpy.wait() runs a nested Qt event loop. Other UI tests retain
            # widgets until process shutdown, so their queued events must not be
            # delivered while this timer's access policy is patched.
            env = dict(os.environ, QT_QPA_PLATFORM="offscreen",
                       BONKSCANNER_IGNORE_SHARED_STORAGE="1",
                       BONKSCANNER_THEME_EXPIRY_CHILD="1")
            result = subprocess.run(
                [sys.executable, "-m", "unittest",
                 "src.tests.test_theme_catalog.ThemeCatalogTests."
                 "test_expiry_and_offline_grace_refresh_without_access_publication"],
                cwd=Path(__file__).resolve().parents[2], env=env,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return

        from datetime import timedelta
        from PySide6.QtTest import QSignalSpy

        for online in (True, False):
            with self.subTest(online=online):
                clock, access, owner, binding = self._access_fixture(online=online)
                self.assertTrue(binding.expiry_timer.isActive())
                self.assertEqual(binding.expiry_timer.interval(), 30000)
                clock["now"] += timedelta(seconds=31)
                self.assertFalse(access.has_premium_access())
                with patch("ui.themes.apply_theme", side_effect=lambda app: setattr(app, "_visual_theme", resolved_theme(app))) as apply:
                    observed = QSignalSpy(binding.expiry_timer.timeout)
                    binding.expiry_timer.start(1)
                    self.assertTrue(observed.wait(1000), "Expiry timer did not fire")
                    apply.assert_called_once_with(owner)
                self.assertEqual(owner._visual_theme, "original")
                self.assertEqual(config.user_config[THEME_CONFIG_KEY], "halloween")
                self.assertFalse(binding.expiry_timer.isActive())
                binding.close()

    def test_access_extension_rearms_one_timer_and_reactivation_restores_desired_theme(self):
        from dataclasses import replace
        from datetime import timedelta
        from PySide6.QtCore import QTimer

        clock, access, owner, binding = self._access_fixture()
        timer = binding.expiry_timer
        clock["now"] += timedelta(seconds=20)
        access._publish(replace(access.state, expires_at=clock["now"] + timedelta(seconds=1800)))
        self.assertIs(binding.expiry_timer, timer)
        self.assertEqual(timer.interval(), 1800000)
        self.assertEqual(len(binding.findChildren(QTimer)), 1)
        with patch("ui.themes.apply_theme", side_effect=lambda app: setattr(app, "_visual_theme", resolved_theme(app))) as apply:
            clock["now"] += timedelta(seconds=1800)
            binding.refresh()
            self.assertEqual(owner._visual_theme, "original")
            self.assertFalse(timer.isActive())
            access._publish(replace(access.state, expires_at=clock["now"] + timedelta(seconds=60)))
            self.assertEqual(owner._visual_theme, "halloween")
            self.assertEqual(apply.call_count, 2)
        self.assertTrue(timer.isActive())
        self.assertEqual(timer.interval(), 60000)

    def test_unbounded_or_inactive_access_does_not_poll(self):
        from dataclasses import replace

        _, access, _, binding = self._access_fixture()
        access._publish(replace(access.state, expires_at=None, online=True))
        self.assertFalse(binding.expiry_timer.isActive())
        with patch("ui.themes.apply_theme"):
            access._publish(replace(access.state, active=False))
        self.assertFalse(binding.expiry_timer.isActive())

    def test_runtime_disposal_cancels_expiry_and_unsubscribes(self):
        _, access, owner, binding = self._access_fixture()
        self.assertIn(binding.listener, access._listeners)
        owner._appearance_runtime.dispose()
        self.assertTrue(binding.closed)
        self.assertFalse(binding.expiry_timer.isActive())
        self.assertNotIn(binding.listener, access._listeners)
        with patch("ui.themes.apply_theme") as apply:
            binding.refresh()
            apply.assert_not_called()
        binding.close()

    def test_access_events_refresh_once_and_disconnect_on_destruction(self):
        listeners = []
        access = SimpleNamespace(add_listener=listeners.append, remove_listener=listeners.remove)
        window = QWidget()
        owner = SimpleNamespace(window=window, supporter_access=access, _visual_theme="halloween")
        binding = _ThemeAccessBinding(owner, access)
        with patch("ui.themes.resolved_theme", return_value="original"), patch("ui.themes.apply_theme") as apply:
            binding.refresh()
            apply.assert_called_once_with(owner)
            owner._visual_theme = "original"
            binding.refresh()
            apply.assert_called_once_with(owner)
        window.destroy()
        window.deleteLater()
        # Also exercise deterministic removal independently of DeferredDelete.
        binding.close()
        self.assertEqual(listeners, [])


if __name__ == "__main__":
    unittest.main()
