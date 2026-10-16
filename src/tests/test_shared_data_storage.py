from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from tempfile import TemporaryDirectory
from unittest.mock import patch

from infra import data_storage as storage, edition, shared_storage as shared


class SharedDataStorageTests(unittest.TestCase):
    def setUp(self):
        storage._reset_for_tests()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(storage._reset_for_tests)
        self.root = Path(temporary.name)
        self.install = self.root / "source-regular"
        self.install.mkdir()
        self.anchor = self.root / "local" / "BonkScanner"
        self.folder = self.root / "profile"
        self.folder.mkdir()
        (self.folder / "config.json").write_text('{"HOTKEY":"f6"}', encoding="utf-8")
        (self.install / "config.json").write_text('{"HOTKEY":"f8"}', encoding="utf-8")
        self.frozen = False
        self.enterContext(patch.dict(os.environ, {shared.IGNORE_SHARED_ENV: "0"}))
        self.enterContext(patch.multiple(
            storage,
            installation_directory=lambda: self.install,
            is_frozen_build=lambda: self.frozen,
            recommended_data_directory=lambda: self.anchor,
            _running_process_from_installation=lambda _path: False,
        ))
        self.enterContext(patch.multiple(edition, EDITION="regular", CONFIG_FILE_NAME="config.json"))

    def connect(self):
        result = shared.request_shared_folder(self.folder)
        self.assertTrue(result.success, result.message)
        return result

    def restart(self):
        storage._reset_for_tests()
        return storage.initialize_storage()

    def test_source_is_private_until_explicitly_connected(self):
        self.anchor.mkdir(parents=True)
        (self.anchor / storage.STATE_FILE_NAME).write_text("corrupt", encoding="utf-8")
        with patch.object(storage, "recommended_data_directory", side_effect=AssertionError("must stay private")):
            context = storage.initialize_storage(acquire_active_lock=False)
        self.assertEqual(context.data_dir, self.install)
        self.assertEqual(context.mode, "source")

    def test_connect_uses_existing_library_without_overwriting_either_config(self):
        old = (self.install / "config.json").read_bytes()
        existing = (self.folder / "config.json").read_bytes()
        (self.install / "merchant_history.jsonl").write_text('{"v":1}\n', encoding="utf-8")
        self.connect()
        self.assertEqual(storage.storage_context().data_dir, self.install)
        context = self.restart()
        self.assertEqual(context.mode, "shared")
        self.assertEqual(context.data_dir, self.folder)
        self.assertTrue(context.can_migrate)
        self.assertEqual((self.folder / "config.json").read_bytes(), existing)
        self.assertEqual((self.install / "config.json").read_bytes(), old)
        self.assertFalse((self.folder / "merchant_history.jsonl").exists())
        self.assertTrue((self.install / "merchant_history.jsonl").exists())

    def test_advanced_copies_its_legacy_config_under_a_different_name(self):
        with patch.multiple(edition, EDITION="advanced", CONFIG_FILE_NAME="config_advanced.json"):
            old = (self.install / "config.json").read_bytes()
            existing = (self.folder / "config.json").read_bytes()
            self.connect()
            self.restart()
            self.assertEqual((self.folder / "config_advanced.json").read_bytes(), old)
            self.assertEqual((self.folder / "config.json").read_bytes(), existing)
            (self.folder / "config_advanced.json").write_text('{"HOTKEY":"f11"}', encoding="utf-8")
            self.restart()
            self.assertEqual(json.loads((self.folder / "config_advanced.json").read_text())["HOTKEY"], "f11")

    def test_existing_advanced_config_is_never_replaced(self):
        (self.folder / "config_advanced.json").write_text('{"HOTKEY":"f12"}', encoding="utf-8")
        with patch.multiple(edition, EDITION="advanced", CONFIG_FILE_NAME="config_advanced.json"):
            self.connect()
            self.restart()
        self.assertEqual(json.loads((self.folder / "config_advanced.json").read_text())["HOTKEY"], "f12")

    def test_advanced_source_upgrade_keeps_the_original_file(self):
        with patch.multiple(edition, EDITION="advanced", CONFIG_FILE_NAME="config_advanced.json"):
            storage.initialize_storage()
        self.assertEqual((self.install / "config_advanced.json").read_bytes(), (self.install / "config.json").read_bytes())

    def test_live_shared_folder_rejects_another_writer(self):
        self.connect()
        self.restart()
        other = storage._ProcessFileLock(self.folder / storage.DATA_LOCK_NAME)
        try:
            self.assertFalse(other.acquire())
        finally:
            other.release()

    def test_connect_rejects_a_locked_target_without_creating_config(self):
        lock = storage._ProcessFileLock(self.folder / storage.DATA_LOCK_NAME)
        self.assertTrue(lock.acquire())
        try:
            with patch.multiple(edition, EDITION="advanced", CONFIG_FILE_NAME="config_advanced.json"):
                result = shared.request_shared_folder(self.folder)
            self.assertFalse(result.success)
            self.assertIn("in use", result.message)
            self.assertFalse((self.folder / "config_advanced.json").exists())
            self.assertFalse((self.install / shared.SOURCE_MARKER).exists())
        finally:
            lock.release()

    def test_empty_or_nested_target_is_not_a_shared_profile(self):
        empty = self.root / "empty"
        empty.mkdir()
        self.assertFalse(shared.request_shared_folder(empty).success)
        nested = self.install / "nested"
        nested.mkdir()
        (nested / "config.json").write_text("{}", encoding="utf-8")
        self.assertFalse(shared.request_shared_folder(nested).success)

    def test_missing_shared_folder_fails_closed_instead_of_starting_empty(self):
        self.connect()
        self.folder.rename(self.root / "saved-profile")
        with self.assertRaises(storage.StorageError):
            self.restart()
        self.assertFalse(self.folder.exists())

    def test_invalid_source_marker_fails_closed(self):
        (self.install / shared.SOURCE_MARKER).write_text("broken", encoding="utf-8")
        with self.assertRaises(storage.StorageError):
            storage.initialize_storage()

    def test_test_runner_can_ignore_a_real_source_selection(self):
        self.connect()
        with patch.dict(os.environ, {shared.IGNORE_SHARED_ENV: "1"}):
            self.assertEqual(self.restart().data_dir, self.install)

    def test_another_profile_cannot_silently_replace_the_shared_selection(self):
        self.connect()
        other = self.root / "other-profile"
        other.mkdir()
        (other / "config.json").write_text("{}", encoding="utf-8")
        result = shared.request_shared_folder(other)
        self.assertFalse(result.success)
        self.assertEqual(self.restart().data_dir, self.folder)

    def test_source_marker_failure_rolls_back_the_registration(self):
        with patch.object(storage, "_write_journal", side_effect=OSError("marker denied")):
            result = shared.request_shared_folder(self.folder)
        self.assertFalse(result.success)
        state = storage._load_state(self.anchor)
        self.assertNotIn(shared.SHARED_KEY, state["installations"])
        self.assertFalse((self.install / shared.SOURCE_MARKER).exists())

    def test_current_folder_can_become_shared_without_copying_over_itself(self):
        self.folder = self.install
        self.connect()
        self.assertEqual(self.restart().data_dir, self.install)
        self.assertEqual(storage.storage_context().mode, "shared")

    def test_shared_move_copies_both_configs_and_all_members_follow(self):
        self.connect()
        regular_install = self.install
        self.install = self.root / "source-advanced"
        self.install.mkdir()
        (self.install / "config.json").write_text('{"NATIVE_HOOK_ENABLED":true}', encoding="utf-8")
        storage._reset_for_tests()
        with patch.multiple(edition, EDITION="advanced", CONFIG_FILE_NAME="config_advanced.json"):
            self.connect()
            self.restart()
            (self.folder / "stats_recordings").mkdir()
            (self.folder / "stats_recordings" / "run.jsonl").write_text('{"type":"metadata"}\n', encoding="utf-8")
            (self.folder / "vod_metadata_index.json").write_text('{"stale":true}', encoding="utf-8")
            destination = self.root / "moved"
            result = storage.request_migration(destination)
            self.assertTrue(result.success, result.message)
            status = storage.migration_status()
            self.assertEqual(status.mode, "shared")
            self.assertEqual(status.pending_target, destination)
        advanced_install = self.install
        self.install = regular_install
        moved = self.restart()
        self.assertEqual(moved.data_dir, destination)
        self.assertEqual(moved.migration_status, "success", moved.migration_message)
        self.assertTrue((destination / "config.json").is_file())
        self.assertTrue((destination / "config_advanced.json").is_file())
        self.assertTrue((destination / "stats_recordings" / "run.jsonl").is_file())
        self.assertFalse((destination / "vod_metadata_index.json").exists())
        self.assertTrue((self.folder / "stats_recordings" / "run.jsonl").is_file())
        self.install = advanced_install
        with patch.multiple(edition, EDITION="advanced", CONFIG_FILE_NAME="config_advanced.json"):
            self.assertEqual(self.restart().data_dir, destination)

    def test_cancel_shared_migration_keeps_both_editions_on_original_folder(self):
        self.connect()
        self.restart()
        self.assertTrue(storage.request_migration(self.root / "moved").success)
        self.assertTrue(storage.cancel_migration().success)
        self.assertEqual(storage.migration_status().migration_status, "cancelled")
        self.assertEqual(self.restart().data_dir, self.folder)

    def test_failed_shared_move_keeps_selected_folder_and_originals(self):
        self.connect()
        self.restart()
        destination = self.root / "moved"
        self.assertTrue(storage.request_migration(destination).success)
        with patch.object(storage.shutil, "copy2", side_effect=OSError("copy interrupted")):
            context = self.restart()
        self.assertEqual(context.data_dir, self.folder)
        self.assertEqual(context.migration_status, "failed")
        self.assertTrue((self.folder / "config.json").exists())
        self.assertFalse((destination / "config.json").exists())

    def test_default_installed_copy_follows_shared_but_legacy_copy_does_not(self):
        self.connect()
        self.install = self.root / "fresh-exe"
        self.install.mkdir()
        self.frozen = True
        self.assertEqual(self.restart().data_dir, self.folder)
        self.install = self.root / "legacy-exe"
        self.install.mkdir()
        (self.install / "config.json").write_text("{}", encoding="utf-8")
        self.assertEqual(self.restart().data_dir, self.install)

    def test_corrupt_config_is_not_copied_or_replaced(self):
        (self.install / "config.json").write_text("broken", encoding="utf-8")
        with patch.multiple(edition, EDITION="advanced", CONFIG_FILE_NAME="config_advanced.json"):
            result = shared.request_shared_folder(self.folder)
        self.assertFalse(result.success)
        self.assertFalse((self.folder / "config_advanced.json").exists())

    def test_shared_profile_cannot_use_legacy_cleanup(self):
        self.connect()
        self.restart()
        result = storage.remove_legacy_data()
        self.assertFalse(result.success)


if __name__ == "__main__":
    unittest.main()
