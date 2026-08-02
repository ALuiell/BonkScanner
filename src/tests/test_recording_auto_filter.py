"""The auto-filter: how short a run has to be before it is thrown away.

The rule used to be a literal in ``VodRecorder.stop`` -- ``snapshot_count == 0``
-- while ``CleanupRecordingsDialog`` proposed its own hard-coded ``2``. Two
numbers answering one question, guaranteed to disagree, and neither reachable
from the UI. These cases pin the single threshold that replaced them, including
the part that is easy to get wrong: a recorder with no settings store must keep
discarding, not silently keep everything.
"""

from __future__ import annotations

import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace

import src  # noqa: F401  -- path bootstrap, as in the rest of the suite

from core.settings import DEFAULT_MINIMUM_SNAPSHOT_COUNT
from infra import vod_storage


class FakeRecordingSettings:
    def __init__(self, minimum=None) -> None:
        self.minimum = minimum
        self.written: list[int] = []

    def read_metadata_index(self):
        return {}

    def write_metadata_index(self, payload) -> None:
        pass

    def read_minimum_snapshot_count(self) -> int:
        return self.minimum

    def write_minimum_snapshot_count(self, value: int) -> None:
        self.written.append(int(value))


class _SettingsFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.addCleanup(vod_storage.use_settings, None)

    def use(self, settings) -> None:
        vod_storage.use_settings(settings)


class MinimumSnapshotCountTests(_SettingsFixture):
    def test_the_default_is_the_old_hard_coded_rule(self) -> None:
        """`< 1` is exactly the `== 0` this replaced, so nothing changes."""
        self.use(None)
        self.assertEqual(vod_storage.minimum_snapshot_count(), 1)
        self.assertEqual(DEFAULT_MINIMUM_SNAPSHOT_COUNT, 1)

    def test_a_configured_threshold_is_used(self) -> None:
        self.use(FakeRecordingSettings(minimum=30))
        self.assertEqual(vod_storage.minimum_snapshot_count(), 30)

    def test_zero_is_honoured_as_keep_everything(self) -> None:
        """A deliberate choice, unlike a negative or a corrupt value."""
        self.use(FakeRecordingSettings(minimum=0))
        self.assertEqual(vod_storage.minimum_snapshot_count(), 0)

    def test_a_corrupt_value_falls_back_rather_than_crashing(self) -> None:
        self.use(FakeRecordingSettings(minimum="not a number"))
        self.assertEqual(vod_storage.minimum_snapshot_count(), DEFAULT_MINIMUM_SNAPSHOT_COUNT)

    def test_a_negative_value_cannot_disable_the_filter(self) -> None:
        self.use(FakeRecordingSettings(minimum=-5))
        self.assertEqual(vod_storage.minimum_snapshot_count(), 0)

    def test_a_settings_store_without_the_reader_falls_back(self) -> None:
        """An older settings object must not silently disable the filter."""
        self.use(object())
        self.assertEqual(vod_storage.minimum_snapshot_count(), DEFAULT_MINIMUM_SNAPSHOT_COUNT)


class RecorderDiscardTests(_SettingsFixture):
    def _recorder(self, directory: Path):
        return vod_storage.VodRecorder(vods_dir=directory, interval_seconds=1)

    def _run(self, directory: Path, snapshots: int):
        recorder = self._recorder(directory)
        recorder.start(name="Run")
        for _ in range(snapshots):
            recorder.capture(
                {"Damage": SimpleNamespace(value=1.0, display_value="1")},
            )
        path = recorder.path
        return path, recorder.stop()

    def test_an_empty_run_is_still_deleted_and_still_says_so(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.use(FakeRecordingSettings(minimum=10))
            path, status = self._run(Path(directory), 0)
            self.assertEqual(status, "deleted_empty")
            self.assertFalse(path.exists())

    def test_a_run_below_the_threshold_is_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.use(FakeRecordingSettings(minimum=10))
            path, status = self._run(Path(directory), 3)
            self.assertEqual(status, "deleted_short")
            self.assertFalse(path.exists())

    def test_a_run_at_the_threshold_is_kept(self) -> None:
        """`minimum` is the shortest run worth keeping, not the first discarded."""
        with tempfile.TemporaryDirectory() as directory:
            self.use(FakeRecordingSettings(minimum=3))
            path, status = self._run(Path(directory), 3)
            self.assertEqual(status, "kept")
            self.assertTrue(path.exists())

    def test_a_threshold_of_zero_keeps_even_an_empty_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.use(FakeRecordingSettings(minimum=0))
            path, status = self._run(Path(directory), 0)
            self.assertEqual(status, "kept")
            self.assertTrue(path.exists())

    def test_without_settings_the_old_rule_still_applies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.use(None)
            path, status = self._run(Path(directory), 0)
            self.assertEqual(status, "deleted_empty")
            self.assertFalse(path.exists())

            kept_path, kept_status = self._run(Path(directory), 1)
            self.assertEqual(kept_status, "kept")
            self.assertTrue(kept_path.exists())


if __name__ == "__main__":
    unittest.main()
