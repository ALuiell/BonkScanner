"""Selection persistence and future access policy for built-in appearance packages."""
import src  # noqa: F401
import json
from pathlib import Path
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
