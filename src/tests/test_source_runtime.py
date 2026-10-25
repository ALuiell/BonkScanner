from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from infra import data_storage as storage, shared_storage as shared
from infra import source_runtime as runtime


class SourceRuntimeTests(unittest.TestCase):
    def setUp(self):
        storage._reset_for_tests()
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(storage._reset_for_tests)
        self.root = Path(temporary.name)
        self.install = self.root / "arbitrary checkout name"
        self.install.mkdir()
        self.runtime = self.install / "runtime"
        self.enterContext(patch.dict(os.environ, {shared.IGNORE_SHARED_ENV: "1"}))
        self.enterContext(patch.multiple(
            storage, installation_directory=lambda: self.install,
            is_frozen_build=lambda: False,
        ))

    def initialize(self):
        return storage.initialize_storage()

    def write(self, relative: str, data: bytes = b"original bytes\r\n") -> Path:
        path = self.install / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_moves_only_runtime_entries_and_preserves_every_byte(self):
        names = ["config.json", "config_advanced.json", "merchant_history.jsonl",
                 "roll_history.json", "supporter_access_cache.json", "vod_metadata_index.json",
                 "stats_recordings/run.jsonl", "vods/old.json", "logs/crash.log",
                 "merchant_history.jsonl.broken-123", "merchant_history.jsonl.lock",
                 "roll_history.json.lock", "restart-diagnostics.log", "config.json.bak",
                 "config_advanced.json.bak", "config.json.interrupted.tmp"]
        for name in names:
            self.write(name)
        for name in ("supporters.json", "THIRD_PARTY_NOTICES.md", "README.md", "src/main.py", "dist/config.json"):
            self.write(name)
        self.write("config.json", b'{"HOTKEY":"f8"}\r\n')
        expected = {name: (self.install / name).read_bytes() for name in names}
        context = self.initialize()
        self.assertEqual(context.data_dir, self.runtime)
        self.assertEqual(context.installation_dir, self.install)
        for name, data in expected.items():
            self.assertEqual((self.runtime / name).read_bytes(), data)
            self.assertFalse((self.install / name).exists())
        for name in ("supporters.json", "THIRD_PARTY_NOTICES.md", "README.md", "src/main.py", "dist/config.json"):
            self.assertEqual((self.install / name).read_bytes(), b"original bytes\r\n")
        self.assertFalse((self.install / storage.DATA_LOCK_NAME).exists())
        self.assertIsNotNone(storage._active_lock)

    def test_existing_profile_is_not_merged_with_root_leftovers(self):
        self.write("config.json", b'{"old":1}')
        self.write("merchant_history.jsonl", b"old history")
        self.write("runtime/config.json", b'{"new":2}')
        self.initialize()
        self.assertEqual((self.runtime / "config.json").read_bytes(), b'{"new":2}')
        self.assertFalse((self.runtime / "merchant_history.jsonl").exists())
        backups = list((self.runtime / "legacy-backup").iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "config.json").read_bytes(), b'{"old":1}')
        self.assertEqual((backups[0] / "merchant_history.jsonl").read_bytes(), b"old history")

    def test_existing_cache_does_not_hide_the_legacy_config(self):
        self.write("config.json", b'{"original":true}')
        self.write("supporter_access_cache.json", b"old cache")
        self.write("runtime/supporter_access_cache.json", b"new cache")
        self.initialize()
        self.assertEqual((self.runtime / "config.json").read_bytes(), b'{"original":true}')
        self.assertEqual((self.runtime / "supporter_access_cache.json").read_bytes(), b"new cache")
        backup = next((self.runtime / "legacy-backup").iterdir())
        self.assertEqual((backup / "supporter_access_cache.json").read_bytes(), b"old cache")

    def test_interrupted_move_resumes_before_opening_any_profile(self):
        self.write("config.json", b"{}")
        self.write("merchant_history.jsonl", b"old history")
        original = Path.rename

        def fail_second(path, destination):
            if path.name == "merchant_history.jsonl":
                raise OSError("interrupted")
            return original(path, destination)

        with patch.object(Path, "rename", fail_second):
            with self.assertRaisesRegex(OSError, "interrupted"):
                self.initialize()
        self.assertIsNone(storage._context)
        self.assertIsNone(storage._active_lock)
        self.assertTrue((self.runtime / runtime.PLAN_NAME).exists())
        self.initialize()
        self.assertEqual((self.runtime / "config.json").read_bytes(), b"{}")
        self.assertEqual((self.runtime / "merchant_history.jsonl").read_bytes(), b"old history")
        self.assertFalse((self.runtime / runtime.PLAN_NAME).exists())
        self.assertFalse((self.runtime / "legacy-backup").exists())

    def test_root_lock_blocks_migration_without_moving_data(self):
        source = self.write("config.json", b"{}")
        lock = storage._ProcessFileLock(self.install / storage.DATA_LOCK_NAME)
        self.assertTrue(lock.acquire())
        try:
            with self.assertRaisesRegex(storage.StorageError, "in use"):
                self.initialize()
            self.assertEqual(source.read_bytes(), b"{}")
        finally:
            lock.release()
        self.initialize()

    def test_active_runtime_lock_rejects_another_lock_handle(self):
        self.initialize()
        lock = storage._ProcessFileLock(self.runtime / storage.DATA_LOCK_NAME)
        try:
            self.assertFalse(lock.acquire())
        finally:
            lock.release()

    def test_repeated_launch_does_not_create_root_files_or_another_backup(self):
        self.write("config.json", b"{}")
        self.initialize()
        storage._reset_for_tests()
        self.initialize()
        self.assertEqual([p.name for p in self.install.iterdir()], ["runtime"])
        self.assertFalse((self.runtime / "legacy-backup").exists())

    def test_invalid_plan_cannot_move_project_files(self):
        project = self.write("README.md")
        self.write("runtime/" + runtime.PLAN_NAME, b'{"README.md":"README.md"}')
        with self.assertRaises(storage.StorageError):
            self.initialize()
        self.assertTrue(project.exists())

    def test_plan_cannot_escape_runtime(self):
        self.write("config.json", b"{}")
        self.write("runtime/" + runtime.PLAN_NAME, b'{"config.json":"../config.json"}')
        with self.assertRaises(storage.StorageError):
            self.initialize()
        self.assertTrue((self.install / "config.json").exists())

    def test_frozen_startup_never_prepares_source_runtime(self):
        self.write("config.json", b"{}")
        with patch.object(storage, "is_frozen_build", return_value=True), patch.object(
            runtime, "prepare_source_runtime", side_effect=AssertionError("EXE must stay unchanged")
        ), patch.object(storage, "recommended_data_directory", return_value=self.root / "appdata"):
            context = self.initialize()
        self.assertEqual(context.data_dir, self.install)
        self.assertFalse(self.runtime.exists())

    def test_legacy_shared_marker_moves_but_selected_profile_does_not(self):
        profile = self.root / "shared"
        profile.mkdir()
        (profile / "config.json").write_bytes(b'{"active":true}')
        self.write("config.json", b'{"stale":true}')
        self.write(shared.SOURCE_MARKER, b'{"shared_profile":1}')
        selected = storage.StorageContext("shared", self.install, profile, profile, "shared")
        with patch.object(shared, "selected_shared_context", return_value=selected):
            self.assertEqual(self.initialize().data_dir, profile)
        self.assertEqual((profile / "config.json").read_bytes(), b'{"active":true}')
        self.assertEqual((self.runtime / "config.json").read_bytes(), b'{"stale":true}')
        self.assertTrue((self.runtime / shared.SOURCE_MARKER).exists())
        self.assertFalse((self.install / shared.SOURCE_MARKER).exists())

    def test_linked_runtime_is_rejected_without_touching_target(self):
        outside = self.root / "outside"
        outside.mkdir()
        try:
            self.runtime.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Creating symlinks is unavailable")
        with self.assertRaises(storage.StorageError):
            self.initialize()
        self.assertEqual(list(outside.iterdir()), [])

    def test_root_used_as_shared_profile_is_never_relocated_implicitly(self):
        source = self.write("config.json", b'{"shared":true}')
        with self.assertRaisesRegex(storage.StorageError, "shared data folder"):
            runtime.prepare_source_runtime(self.install, shared_data=self.install)
        self.assertEqual(source.read_bytes(), b'{"shared":true}')
        self.assertFalse((self.runtime / "config.json").exists())
