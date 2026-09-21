from __future__ import annotations

import json
import os
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from infra import data_storage


class DataStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        data_storage._reset_for_tests()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(data_storage._reset_for_tests)
        self.root = Path(self.temp.name)
        self.install = self.root / "installed"
        self.local = self.root / "local" / "BonkScanner"
        self.install.mkdir(parents=True)

    def frozen(self):
        return patch.multiple(
            data_storage,
            is_frozen_build=lambda: True,
            installation_directory=lambda: self.install,
            recommended_data_directory=lambda: self.local,
            _running_process_from_installation=lambda _path: False,
        )

    def initialize(self):
        with self.frozen():
            return data_storage.initialize_storage(acquire_active_lock=False)

    def write_legacy_profile(self) -> dict[str, bytes]:
        (self.install / "config.json").write_text(
            json.dumps({"HOTKEY": "f7"}), encoding="utf-8"
        )
        history = {
            "v": 1,
            "map_id": "a" * 32,
            "merchant_id": "b" * 32,
            "map_family": "forest",
            "stage": 1,
            "merchant_rarity": "white",
            "item_ids": [1, 2, 3],
        }
        (self.install / "merchant_history.jsonl").write_text(
            json.dumps(history) + "\n", encoding="utf-8"
        )
        recordings = self.install / "stats_recordings"
        recordings.mkdir()
        (recordings / "run.jsonl").write_text('{"type":"metadata"}\n', encoding="utf-8")
        legacy_vods = self.install / "vods"
        legacy_vods.mkdir()
        (legacy_vods / "old-run.json").write_text('{"legacy":true}\n', encoding="utf-8")
        (self.install / "vod_metadata_index.json").write_text(
            json.dumps({"version": 1, "records": []}), encoding="utf-8"
        )
        return {
            path.relative_to(self.install).as_posix(): path.read_bytes()
            for path in self.install.rglob("*")
            if path.is_file()
        }

    def test_source_run_uses_repository_root_and_ignores_appdata_state(self) -> None:
        fake_source = self.root / "source"
        fake_source.mkdir()
        unrelated_cwd = self.root / "terminal-cwd"
        unrelated_cwd.mkdir()
        self.local.mkdir(parents=True)
        (self.local / data_storage.STATE_FILE_NAME).write_text("broken", encoding="utf-8")
        previous_cwd = Path.cwd()
        try:
            os.chdir(unrelated_cwd)
            with patch.multiple(
                data_storage,
                is_frozen_build=lambda: False,
                _source_root=lambda: fake_source,
            ), patch.object(
                data_storage,
                "recommended_data_directory",
                side_effect=AssertionError("source runs must not inspect AppData"),
            ):
                context = data_storage.initialize_storage(acquire_active_lock=False)
        finally:
            os.chdir(previous_cwd)
        self.assertEqual(context.mode, "source")
        self.assertEqual(context.data_dir, fake_source)
        self.assertIsNone(context.recommended_dir)

    def test_new_frozen_install_uses_shared_local_appdata(self) -> None:
        context = self.initialize()
        self.assertEqual(context.mode, "local")
        self.assertEqual(context.data_dir, self.local)

    def test_explicit_bootstrap_acquires_lock_after_lazy_path_resolution(self) -> None:
        with self.frozen():
            lazy = data_storage.storage_context()
            locked = data_storage.initialize_storage(acquire_active_lock=True)
        self.assertIs(lazy, locked)
        self.assertIsNotNone(data_storage._active_lock)

    def test_executable_inside_recommended_folder_is_local_even_with_config(self) -> None:
        self.local.mkdir(parents=True)
        (self.local / "config.json").write_text("{}", encoding="utf-8")
        with patch.multiple(
            data_storage,
            is_frozen_build=lambda: True,
            installation_directory=lambda: self.local,
            recommended_data_directory=lambda: self.local,
        ):
            context = data_storage.initialize_storage(acquire_active_lock=False)
        self.assertEqual(context.mode, "local")
        self.assertFalse(context.can_migrate)

    def test_existing_profile_stays_beside_executable(self) -> None:
        self.write_legacy_profile()
        context = self.initialize()
        self.assertEqual(context.mode, "legacy")
        self.assertEqual(context.data_dir, self.install)
        self.assertTrue(context.can_migrate)

    def test_logs_and_lock_alone_do_not_define_a_legacy_profile(self) -> None:
        (self.install / "logs").mkdir()
        (self.install / "logs" / "crash.log").write_text("x", encoding="utf-8")
        (self.install / "merchant_history.jsonl.lock").write_text("0", encoding="utf-8")
        context = self.initialize()
        self.assertEqual(context.mode, "local")

    def test_request_can_be_cancelled_before_restart(self) -> None:
        self.write_legacy_profile()
        context = self.initialize()
        self.assertEqual(context.mode, "legacy")
        with self.frozen():
            requested = data_storage.request_migration()
            pending = data_storage.migration_status()
            cancelled = data_storage.cancel_migration()
            final = data_storage.migration_status()
        self.assertTrue(requested.success)
        self.assertEqual(pending.migration_status, "pending")
        self.assertTrue(cancelled.success)
        self.assertEqual(final.migration_status, "cancelled")

    def test_migration_copies_verifies_and_keeps_originals(self) -> None:
        originals = self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()

        migrated = self.initialize()

        self.assertEqual(migrated.mode, "local")
        self.assertEqual(migrated.migration_status, "success")
        self.assertEqual((self.local / "config.json").read_bytes(), originals["config.json"])
        self.assertEqual(
            (self.local / "merchant_history.jsonl").read_bytes(),
            originals["merchant_history.jsonl"],
        )
        self.assertEqual(
            (self.local / "stats_recordings" / "run.jsonl").read_bytes(),
            originals["stats_recordings/run.jsonl"],
        )
        self.assertEqual(
            (self.local / "vods" / "old-run.json").read_bytes(),
            originals["vods/old-run.json"],
        )
        self.assertFalse((self.local / "vod_metadata_index.json").exists())
        for relative, payload in originals.items():
            self.assertEqual((self.install / relative).read_bytes(), payload)

    def test_remove_legacy_data_deletes_only_known_migrated_data(self) -> None:
        originals = self.write_legacy_profile()
        (self.install / "supporter_access_cache.json").write_text(
            '{"active":true}', encoding="utf-8"
        )
        (self.install / "merchant_history.jsonl.broken-1").write_text(
            "broken", encoding="utf-8"
        )
        logs = self.install / "logs"
        logs.mkdir()
        (logs / "crash.log").write_text("synthetic", encoding="utf-8")
        executable = self.install / "BonkScanner.exe"
        executable.write_bytes(b"synthetic-exe")
        unknown = self.install / "keep-me.txt"
        unknown.write_text("unknown", encoding="utf-8")
        unfinished = self.install / "recording.tmp"
        unfinished.write_text("partial", encoding="utf-8")

        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        migrated = self.initialize()
        self.assertEqual(migrated.mode, "local")

        with self.frozen():
            result = data_storage.remove_legacy_data()
            refreshed = data_storage.migration_status()

        self.assertTrue(result.success)
        self.assertEqual(result.status, "success")
        self.assertEqual(refreshed.legacy_cleanup_status, "success")
        for name in data_storage.LEGACY_CLEANUP_FILES:
            self.assertFalse((self.install / name).exists(), name)
        self.assertFalse((self.install / "merchant_history.jsonl.broken-1").exists())
        for name in data_storage.MIGRATION_DIRECTORIES:
            self.assertFalse((self.install / name).exists(), name)
        self.assertTrue(executable.exists())
        self.assertTrue(unknown.exists())
        self.assertTrue(unfinished.exists())
        self.assertFalse((self.install / data_storage.DATA_LOCK_NAME).exists())
        self.assertEqual(
            (self.local / "config.json").read_bytes(), originals["config.json"]
        )

    def test_remove_legacy_data_stops_when_old_instance_is_running(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        self.initialize()

        with self.frozen(), patch.object(
            data_storage, "_running_process_from_installation", return_value=True
        ):
            result = data_storage.remove_legacy_data()

        self.assertFalse(result.success)
        self.assertIn("still running", result.message)
        self.assertTrue((self.install / "config.json").exists())

    def test_remove_legacy_data_does_not_recreate_a_missing_old_folder(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        self.initialize()
        shutil.rmtree(self.install)

        with self.frozen():
            result = data_storage.remove_legacy_data()
            refreshed = data_storage.migration_status()

        self.assertTrue(result.success)
        self.assertEqual(refreshed.legacy_cleanup_status, "success")
        self.assertFalse(self.install.exists())

    def test_remove_legacy_data_does_not_unlink_a_lock_it_did_not_acquire(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        self.initialize()
        lock_path = self.install / data_storage.DATA_LOCK_NAME
        lock_path.write_text("owned-by-another-process", encoding="utf-8")

        with self.frozen(), patch.object(
            data_storage._ProcessFileLock,
            "acquire",
            side_effect=[True, False],
        ):
            result = data_storage.remove_legacy_data()

        self.assertFalse(result.success)
        self.assertIn("in use", result.message)
        self.assertEqual(lock_path.read_text(encoding="utf-8"), "owned-by-another-process")

    def test_remove_legacy_data_preflights_links_before_deleting_anything(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        self.initialize()
        linked = self.install / "stats_recordings"
        original_reparse_check = data_storage._is_reparse_point

        with self.frozen(), patch.object(
            data_storage,
            "_is_reparse_point",
            side_effect=lambda path: path == linked or original_reparse_check(path),
        ):
            result = data_storage.remove_legacy_data()

        self.assertFalse(result.success)
        self.assertIn("linked path", result.message)
        self.assertTrue((self.install / "config.json").exists())
        self.assertTrue(linked.exists())

    def test_remove_legacy_data_reports_a_target_inspection_error(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        self.initialize()

        with self.frozen(), patch.object(
            data_storage,
            "_legacy_cleanup_targets",
            side_effect=PermissionError("synthetic access denied"),
        ):
            result = data_storage.remove_legacy_data()
            refreshed = data_storage.migration_status()

        self.assertFalse(result.success)
        self.assertIn("access denied", result.message)
        self.assertEqual(refreshed.legacy_cleanup_status, "failed")
        self.assertTrue((self.install / "config.json").exists())

    def test_existing_target_profile_blocks_migration_without_overwrite(self) -> None:
        self.write_legacy_profile()
        self.local.mkdir(parents=True)
        target_config = self.local / "config.json"
        target_config.write_text('{"HOTKEY":"f9"}', encoding="utf-8")
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()

        context = self.initialize()

        self.assertEqual(context.mode, "legacy")
        self.assertEqual(context.migration_status, "failed")
        self.assertIn("another BonkScanner profile", context.migration_message)
        self.assertEqual(target_config.read_text(encoding="utf-8"), '{"HOTKEY":"f9"}')

    def test_copy_failure_leaves_source_active_and_target_unpublished(self) -> None:
        originals = self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()

        with self.frozen(), patch.object(
            data_storage.shutil, "copy2", side_effect=OSError("disk full")
        ):
            context = data_storage.initialize_storage(acquire_active_lock=False)

        self.assertEqual(context.mode, "legacy")
        self.assertEqual(context.migration_status, "failed")
        self.assertIn("disk full", context.migration_message)
        self.assertFalse((self.local / "config.json").exists())
        for relative, payload in originals.items():
            self.assertEqual((self.install / relative).read_bytes(), payload)

    def test_invalid_config_stops_migration_without_publishing(self) -> None:
        self.write_legacy_profile()
        (self.install / "config.json").write_text("{broken", encoding="utf-8")
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()

        context = self.initialize()

        self.assertEqual(context.mode, "legacy")
        self.assertEqual(context.migration_status, "failed")
        self.assertIn("config.json", context.migration_message)
        self.assertFalse((self.local / "config.json").exists())

    def test_invalid_history_stops_migration_without_repairing_source(self) -> None:
        self.write_legacy_profile()
        history = self.install / "merchant_history.jsonl"
        history.write_text("not-json\n", encoding="utf-8")
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()

        context = self.initialize()

        self.assertEqual(context.mode, "legacy")
        self.assertEqual(context.migration_status, "failed")
        self.assertIn("merchant history", context.migration_message)
        self.assertEqual(history.read_text(encoding="utf-8"), "not-json\n")

    def test_source_change_during_copy_stops_before_publication(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        original_copy = data_storage.shutil.copy2
        changed = False

        def copy_then_change_source(source, destination):
            nonlocal changed
            result = original_copy(source, destination)
            source_path = Path(source)
            if source_path.name == "config.json" and not changed:
                source_path.write_text(
                    source_path.read_text(encoding="utf-8") + " ", encoding="utf-8"
                )
                changed = True
            return result

        with self.frozen(), patch.object(
            data_storage.shutil, "copy2", side_effect=copy_then_change_source
        ):
            context = data_storage.initialize_storage(acquire_active_lock=False)

        self.assertEqual(context.mode, "legacy")
        self.assertEqual(context.migration_status, "failed")
        self.assertIn("changed during migration", context.migration_message)
        self.assertFalse((self.local / "config.json").exists())

    def test_top_level_link_is_refused_before_copy(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()

        linked = self.install / "config.json"
        original_reparse_check = data_storage._is_reparse_point
        with self.frozen(), patch.object(
            data_storage,
            "_is_reparse_point",
            side_effect=lambda path: path == linked or original_reparse_check(path),
        ):
            context = data_storage.initialize_storage(acquire_active_lock=False)

        self.assertEqual(context.mode, "legacy")
        self.assertEqual(context.migration_status, "failed")
        self.assertIn("linked file", context.migration_message)
        self.assertFalse((self.local / "config.json").exists())

    def test_mid_publish_failure_rolls_back_files_already_moved(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        original_replace = data_storage.os.replace

        def replace_with_one_publish_failure(source, destination):
            destination_path = Path(destination)
            if destination_path == self.local / "merchant_history.jsonl":
                raise OSError("simulated publish failure")
            return original_replace(source, destination)

        with self.frozen(), patch.object(
            data_storage.os, "replace", side_effect=replace_with_one_publish_failure
        ):
            context = data_storage.initialize_storage(acquire_active_lock=False)

        self.assertEqual(context.mode, "legacy")
        self.assertEqual(context.migration_status, "failed")
        self.assertIn("simulated publish failure", context.migration_message)
        self.assertFalse((self.local / "config.json").exists())
        self.assertFalse(any(self.local.glob(".migration-*.journal.json")))

    def test_unavailable_process_check_refuses_pending_migration(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()

        with self.frozen(), patch.object(
            data_storage, "_running_process_from_installation", return_value=None
        ):
            context = data_storage.initialize_storage(acquire_active_lock=False)

        self.assertEqual(context.mode, "legacy")
        self.assertEqual(context.migration_status, "failed")
        self.assertIn("could not verify", context.migration_message)

    def test_current_pyinstaller_launcher_is_not_a_competing_process(self) -> None:
        with patch.object(data_storage.os, "getpid", return_value=42), patch.object(
            data_storage.os, "getppid", return_value=41
        ):
            self.assertEqual({42, 41}, data_storage._current_instance_process_ids())

    def test_process_starting_during_copy_prevents_publication(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()

        with patch.multiple(
            data_storage,
            is_frozen_build=lambda: True,
            installation_directory=lambda: self.install,
            recommended_data_directory=lambda: self.local,
        ), patch.object(
            data_storage,
            "_running_process_from_installation",
            side_effect=(False, True),
        ):
            context = data_storage.initialize_storage(acquire_active_lock=False)

        self.assertEqual(context.mode, "legacy")
        self.assertEqual(context.migration_status, "failed")
        self.assertIn("started during migration", context.migration_message)
        self.assertFalse((self.local / "config.json").exists())

    def test_interrupted_publication_is_recovered_before_retry(self) -> None:
        originals = self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()

        with self.frozen(), patch.object(
            data_storage,
            "_write_state",
            side_effect=KeyboardInterrupt("simulated process termination"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                data_storage.initialize_storage(acquire_active_lock=False)

        self.assertTrue((self.local / "config.json").exists())
        self.assertTrue(any(self.local.glob(".migration-*.journal.json")))
        data_storage._reset_for_tests()

        recovered = self.initialize()

        self.assertEqual(recovered.mode, "local")
        self.assertEqual(recovered.migration_status, "success")
        self.assertFalse(any(self.local.glob(".migration-*.journal.json")))
        self.assertEqual((self.local / "config.json").read_bytes(), originals["config.json"])

    def test_other_installation_cannot_open_interrupted_published_profile(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        with self.frozen(), patch.object(
            data_storage,
            "_write_state",
            side_effect=KeyboardInterrupt("simulated process termination"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                data_storage.initialize_storage(acquire_active_lock=False)
        data_storage._reset_for_tests()

        other_install = self.root / "other-new-copy"
        other_install.mkdir()
        with patch.multiple(
            data_storage,
            is_frozen_build=lambda: True,
            installation_directory=lambda: other_install,
            recommended_data_directory=lambda: self.local,
        ), self.assertRaisesRegex(data_storage.StorageError, "interrupted data migration"):
            data_storage.initialize_storage(acquire_active_lock=False)

    def test_orphan_journal_blocks_other_installation_even_without_state_entry(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        with self.frozen(), patch.object(
            data_storage,
            "_write_state",
            side_effect=KeyboardInterrupt("simulated process termination"),
        ):
            with self.assertRaises(KeyboardInterrupt):
                data_storage.initialize_storage(acquire_active_lock=False)
        state_path = self.local / data_storage.STATE_FILE_NAME
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["installations"] = {}
        state_path.write_text(json.dumps(state), encoding="utf-8")
        data_storage._reset_for_tests()

        other_install = self.root / "other-new-copy"
        other_install.mkdir()
        with patch.multiple(
            data_storage,
            is_frozen_build=lambda: True,
            installation_directory=lambda: other_install,
            recommended_data_directory=lambda: self.local,
        ), self.assertRaisesRegex(data_storage.StorageError, "interrupted data migration"):
            data_storage.initialize_storage(acquire_active_lock=False)

    def test_success_marker_is_scoped_to_one_legacy_installation(self) -> None:
        self.write_legacy_profile()
        self.initialize()
        with self.frozen():
            self.assertTrue(data_storage.request_migration().success)
        data_storage._reset_for_tests()
        first = self.initialize()
        self.assertEqual(first.mode, "local")

        other_install = self.root / "other-installed"
        other_install.mkdir()
        (other_install / "config.json").write_text("{}", encoding="utf-8")
        data_storage._reset_for_tests()
        with patch.multiple(
            data_storage,
            is_frozen_build=lambda: True,
            installation_directory=lambda: other_install,
            recommended_data_directory=lambda: self.local,
            _running_process_from_installation=lambda _path: False,
        ):
            second = data_storage.initialize_storage(acquire_active_lock=False)
        self.assertEqual(second.mode, "legacy")
        self.assertEqual(second.data_dir, other_install)

    def test_corrupt_storage_state_stops_bootstrap(self) -> None:
        self.local.mkdir(parents=True)
        (self.local / data_storage.STATE_FILE_NAME).write_text("{broken", encoding="utf-8")
        with self.frozen(), self.assertRaises(data_storage.StorageError):
            data_storage.initialize_storage(acquire_active_lock=False)


if __name__ == "__main__":
    unittest.main()
