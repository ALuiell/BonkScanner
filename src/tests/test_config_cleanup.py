from __future__ import annotations

import os
import json
import tempfile
import unittest
from unittest.mock import patch

import src

from app import config


class GameResetTimeConfigTests(unittest.TestCase):
    def _write_game_config(self, path: str, quick_reset_time: float = 0.05) -> None:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(
                {"cfGameSettings": {"quick_reset_time": quick_reset_time}},
                handle,
            )

    def test_update_game_reset_time_writes_and_verifies_requested_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            self._write_game_config(game_config_path)

            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                result = config.update_game_reset_time(0.2)

            self.assertTrue(result.success)
            with open(game_config_path, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            self.assertEqual(saved["cfGameSettings"]["quick_reset_time"], 0.2)

    def test_update_game_reset_time_reports_missing_game_config(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = os.path.join(temp_dir, "missing.json")

            with patch.object(config, "get_game_config_path", return_value=missing_path):
                result = config.update_game_reset_time(0.2)

            self.assertFalse(result.success)
            self.assertIn("not found", result.reason)

    def test_update_game_reset_time_reports_write_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            self._write_game_config(game_config_path)

            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                with patch.object(config, "save_game_config", return_value=False):
                    result = config.update_game_reset_time(0.2)

            self.assertFalse(result.success)
            self.assertIn("write", result.reason)

    def test_update_game_reset_time_rejects_unverified_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game_config_path = os.path.join(temp_dir, "config.json")
            self._write_game_config(game_config_path, quick_reset_time=0.05)

            with patch.object(config, "get_game_config_path", return_value=game_config_path):
                with patch.object(config, "save_game_config", return_value=True):
                    result = config.update_game_reset_time(0.2)

            self.assertFalse(result.success)
            self.assertIn("expected 0.20", result.reason)
            self.assertIn("found 0.05", result.reason)


class LegacyNativeHookCleanupTests(unittest.TestCase):
    def test_cleanup_removes_legacy_hook_directories_and_empty_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_appdata = os.path.join(temp_dir, "AppData", "Local")
            root_dir = os.path.join(local_appdata, "BonkScanner")
            native_hook_dir = os.path.join(root_dir, "native-hook")
            extracted_dir = os.path.join(root_dir, "native-hook-extracted")

            os.makedirs(native_hook_dir)
            os.makedirs(extracted_dir)
            with open(os.path.join(native_hook_dir, "BonkHook.dll"), "w", encoding="utf-8") as handle:
                handle.write("x")
            with open(os.path.join(extracted_dir, "BonkHook.dll"), "w", encoding="utf-8") as handle:
                handle.write("x")

            with patch.dict(os.environ, {"LOCALAPPDATA": local_appdata}, clear=False):
                config.cleanup_legacy_native_hook_cache(
                    os.path.join(extracted_dir, "BonkHook.dll")
                )

            self.assertFalse(os.path.exists(native_hook_dir))
            self.assertFalse(os.path.exists(extracted_dir))
            self.assertFalse(os.path.exists(root_dir))

    def test_cleanup_ignores_saved_dll_path_outside_expected_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            local_appdata = os.path.join(temp_dir, "AppData", "Local")
            root_dir = os.path.join(local_appdata, "BonkScanner")
            os.makedirs(root_dir)

            external_dir = os.path.join(temp_dir, "Elsewhere")
            os.makedirs(external_dir)
            external_dll_path = os.path.join(external_dir, "BonkHook.dll")
            with open(external_dll_path, "w", encoding="utf-8") as handle:
                handle.write("x")

            with patch.dict(os.environ, {"LOCALAPPDATA": local_appdata}, clear=False):
                config.cleanup_legacy_native_hook_cache(external_dll_path)

            self.assertTrue(os.path.exists(external_dir))
            self.assertTrue(os.path.exists(external_dll_path))
            self.assertFalse(os.path.exists(root_dir))


class InGameOverlayConfigTests(unittest.TestCase):
    def test_invalid_scale_falls_back_to_widget_default(self) -> None:
        normalized = config.normalize_in_game_overlay_config(
            {
                "widgets": {
                    "scanner": {"scale": "not-a-number"},
                    "recording": {"scale": "inf"},
                    "kps": {"scale": ""},
                    "powerups": {"scale": None},
                    "luck_rarity": {"scale": object(), "show_bar": False},
                }
            }
        )

        defaults = config.DEFAULT_IN_GAME_OVERLAY["widgets"]
        self.assertEqual(normalized["widgets"]["scanner"]["scale"], defaults["scanner"]["scale"])
        self.assertEqual(normalized["widgets"]["recording"]["scale"], defaults["recording"]["scale"])
        self.assertEqual(normalized["widgets"]["kps"]["scale"], defaults["kps"]["scale"])
        self.assertEqual(normalized["widgets"]["powerups"]["scale"], defaults["powerups"]["scale"])
        self.assertEqual(normalized["widgets"]["luck_rarity"]["scale"], defaults["luck_rarity"]["scale"])
        self.assertEqual(normalized["widgets"]["luck_rarity"]["show_bar"], False)


class FastTrackerIntervalConfigTests(unittest.TestCase):
    def test_legacy_chaos_tome_key_is_migrated_to_fast_tracker_interval(self) -> None:
        self.assertEqual(
            config.resolve_fast_tracker_interval_ms(
                {"CHAOS_TOME_TRACKER_INTERVAL_MS": 250}
            ),
            250,
        )

    def test_new_fast_tracker_key_takes_precedence_over_legacy_key(self) -> None:
        self.assertEqual(
            config.resolve_fast_tracker_interval_ms(
                {
                    "FAST_TRACKER_INTERVAL_MS": 300,
                    "CHAOS_TOME_TRACKER_INTERVAL_MS": 250,
                }
            ),
            300,
        )

    def test_fast_tracker_interval_preserves_minimum_bound(self) -> None:
        self.assertEqual(
            config.resolve_fast_tracker_interval_ms({"FAST_TRACKER_INTERVAL_MS": 1}),
            100,
        )


if __name__ == "__main__":
    unittest.main()
