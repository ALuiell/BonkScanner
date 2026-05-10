from __future__ import annotations

from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path

from vod_storage import VodRecorder, delete_vod, list_vods, load_vod, load_vod_metadata, rename_vod


class VodStorageTests(unittest.TestCase):
    def test_recorder_writes_loads_and_renames_vod(self) -> None:
        now = 1000.0
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(
                vods_dir=Path(temp_dir),
                interval_seconds=60,
                clock=lambda: now,
            )

            path = recorder.start(name="Test run")
            recorder.capture(
                {
                    "Damage": SimpleNamespace(value=1.25, display_value="1.25x"),
                    "Armor": SimpleNamespace(value=0.15, display_value="15%"),
                },
            )
            now += 60
            recorder.capture(
                {
                    "Damage": SimpleNamespace(value=1.5, display_value="1.5x"),
                    "Armor": SimpleNamespace(value=0.2, display_value="20%"),
                },
            )
            recorder.stop()

            loaded = load_vod(path)

            self.assertEqual(loaded.metadata.name, "Test run")
            self.assertEqual(loaded.metadata.snapshot_count, 2)
            self.assertEqual(loaded.snapshots[0].stats["Damage"].display_value, "1.25x")
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


if __name__ == "__main__":
    unittest.main()
