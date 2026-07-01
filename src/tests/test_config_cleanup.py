from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import src

import config


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


if __name__ == "__main__":
    unittest.main()
