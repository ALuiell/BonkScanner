from __future__ import annotations

from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path

from vod_storage import LEGACY_VODS_DIR, RECORDINGS_DIR, VodRecorder, delete_vod, list_vods, load_vod, load_vod_metadata, rename_vod


class VodStorageTests(unittest.TestCase):
    def test_recorder_defaults_to_stats_recordings_directory(self) -> None:
        recorder = VodRecorder()

        self.assertEqual(recorder.vods_dir, RECORDINGS_DIR)
        self.assertNotEqual(recorder.vods_dir, LEGACY_VODS_DIR)

    def test_recorder_writes_loads_and_renames_vod(self) -> None:
        now = 1000.0
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(
                vods_dir=Path(temp_dir),
                interval_seconds=60,
                clock=lambda: now,
            )

            path = recorder.start(name="Test run", seed=12345)
            recorder.capture(
                {
                    "Damage": SimpleNamespace(value=1.25, display_value="1.25x"),
                    "Armor": SimpleNamespace(value=0.15, display_value="15%"),
                },
                ("Wrench x1",),
                chests_per_minute=1.23,
            )
            now += 60
            recorder.capture(
                {
                    "Damage": SimpleNamespace(value=1.5, display_value="1.5x"),
                    "Armor": SimpleNamespace(value=0.2, display_value="20%"),
                },
                ("Wrench x2", "Dice x1"),
                chests_per_minute=2.34,
            )
            recorder.stop()

            loaded = load_vod(path)

            self.assertEqual(loaded.metadata.name, "Test run")
            self.assertEqual(loaded.metadata.run_seed, 12345)
            self.assertEqual(loaded.metadata.snapshot_count, 2)
            self.assertEqual(loaded.snapshots[0].stats["Damage"].display_value, "1.25x")
            self.assertEqual(loaded.snapshots[0].items, ("Wrench x1",))
            self.assertEqual(loaded.snapshots[0].chests_per_minute, 1.23)
            self.assertEqual(loaded.snapshots[1].items, ("Wrench x2", "Dice x1"))
            self.assertEqual(loaded.snapshots[1].chests_per_minute, 2.34)
            self.assertEqual(loaded.snapshots[1].time_label, "01:00")

            vods = list_vods(Path(temp_dir))
            self.assertEqual([vod.name for vod in vods], ["Test run"])

            renamed = rename_vod(path, "Renamed run")
            self.assertEqual(renamed.name, "Renamed run")
            self.assertEqual(load_vod(path).metadata.name, "Renamed run")

            delete_vod(path)
            self.assertFalse(path.exists())

    def test_load_vod_metadata_skips_snapshot_payload_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "metadata-only-fast-path.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":1,"name":"Fast metadata","created_at":"2026-05-10T16:00:00","snapshot_interval_seconds":60}',
                        '{"type":"snapshot","elapsed_seconds":0,"stats":"not-a-dict"}',
                        '{"type":"snapshot","elapsed_seconds":60,"stats":{"Damage":{"value":1.25,"display":"1.25x"}}}',
                        '{"type":"summary","duration_seconds":60,"snapshot_count":2}',
                    ],
                )
                + "\n",
                encoding="utf-8",
            )

            metadata = load_vod_metadata(path)

            self.assertEqual(metadata.name, "Fast metadata")
            self.assertEqual(metadata.snapshot_count, 2)
            self.assertEqual(metadata.duration_seconds, 60)

    def test_list_vods_reads_legacy_directory_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            legacy_dir = Path(temp_dir) / "vods"
            legacy_dir.mkdir(parents=True, exist_ok=True)
            path = legacy_dir / "legacy-run.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":1,"name":"Legacy run","created_at":"2026-05-10T16:00:00","snapshot_interval_seconds":60}',
                        '{"type":"summary","duration_seconds":0,"snapshot_count":0}',
                    ],
                )
                + "\n",
                encoding="utf-8",
            )

            original_recordings_dir = RECORDINGS_DIR
            original_legacy_dir = LEGACY_VODS_DIR
            try:
                import vod_storage

                vod_storage.RECORDINGS_DIR = Path(temp_dir) / "stats_recordings"
                vod_storage.LEGACY_VODS_DIR = legacy_dir
                vods = list_vods()
            finally:
                vod_storage.RECORDINGS_DIR = original_recordings_dir
                vod_storage.LEGACY_VODS_DIR = original_legacy_dir

            self.assertEqual([vod.name for vod in vods], ["Legacy run"])


if __name__ == "__main__":
    unittest.main()
