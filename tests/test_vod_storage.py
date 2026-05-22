from __future__ import annotations

from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path

from player_stats import (
    PlayerStatFormat,
    TomeSnapshot,
    WeaponSnapshot,
    WeaponStatFormat,
    WeaponStatValue,
)
from vod_storage import (
    LEGACY_VODS_DIR,
    RECORDINGS_DIR,
    VodRecorder,
    delete_vod,
    delete_vods_below_snapshot_count,
    list_vods,
    load_vod,
    load_vod_metadata,
    rename_vod,
)


class VodStorageTests(unittest.TestCase):
    def test_recorder_batches_snapshot_flushes_but_flushes_metadata_and_summary(self) -> None:
        class FakeFile:
            def __init__(self) -> None:
                self.flush_calls = 0
                self.closed = False
                self.parts: list[str] = []

            def write(self, chunk: str) -> None:
                self.parts.append(chunk)

            def flush(self) -> None:
                self.flush_calls += 1

            def close(self) -> None:
                self.closed = True

        fake_file = FakeFile()
        recorder = VodRecorder(vods_dir=Path("."), interval_seconds=30, clock=lambda: 1000.0)
        recorder.path = Path("fake.jsonl")
        recorder.name = "Fake"
        recorder.start_time = 1000.0
        recorder.is_recording = True
        recorder._file = fake_file

        recorder._write_record({"type": "metadata"}, flush=True)
        for index in range(1, 4):
            recorder.snapshot_count = index
            recorder._write_record({"type": "snapshot", "index": index}, flush=(index % 3 == 0))
        recorder._write_record({"type": "summary"}, flush=True)

        self.assertEqual(fake_file.flush_calls, 3)

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
                (
                    WeaponSnapshot(
                        weapon_id=0,
                        name="Fire Staff",
                        level=3,
                        upgrade_stat_ids=(12, 16, 9, 11),
                        upgraded_stats={
                            12: WeaponStatValue(12, "Damage", 10.0, WeaponStatFormat.FLAT),
                            16: WeaponStatValue(16, "Projectiles", 2.0, WeaponStatFormat.FLAT),
                            9: WeaponStatValue(9, "Size", 1.16, WeaponStatFormat.MULTIPLIER),
                            11: WeaponStatValue(11, "Speed", 0.6, WeaponStatFormat.MULTIPLIER),
                        },
                        full_stats={
                            12: WeaponStatValue(12, "Damage", 10.0, WeaponStatFormat.FLAT),
                            16: WeaponStatValue(16, "Projectiles", 2.0, WeaponStatFormat.FLAT),
                            9: WeaponStatValue(9, "Size", 1.16, WeaponStatFormat.MULTIPLIER),
                            11: WeaponStatValue(11, "Speed", 0.6, WeaponStatFormat.MULTIPLIER),
                            24: WeaponStatValue(24, "Knockback", 1.0, WeaponStatFormat.MULTIPLIER),
                        },
                    ),
                ),
                (
                    TomeSnapshot(
                        tome_id=0,
                        name="Damage",
                        level=3,
                        stat_id=12,
                        stat_label="Damage",
                        value=1.25,
                        value_format=PlayerStatFormat.MULTIPLIER,
                    ),
                ),
                ("Clover", "Golden Tome"),
                chests_per_minute=1.23,
                game_time_seconds=21.52338219,
                mob_kills=37,
                player_level=2,
            )
            now += 60
            recorder.capture(
                {
                    "Damage": SimpleNamespace(value=1.5, display_value="1.5x"),
                    "Armor": SimpleNamespace(value=0.2, display_value="20%"),
                },
                ("Wrench x2", "Dice x1"),
                (),
                (),
                (),
                chests_per_minute=2.34,
                game_time_seconds=81.75,
                mob_kills=12,
                player_level=4,
            )
            recorder.stop()

            loaded = load_vod(path)

            self.assertEqual(loaded.metadata.name, "Test run")
            self.assertEqual(loaded.metadata.run_seed, 12345)
            self.assertEqual(loaded.metadata.snapshot_count, 2)
            self.assertEqual(loaded.snapshots[0].stats["Damage"].display_value, "1.25x")
            self.assertEqual(loaded.snapshots[0].items, ("Wrench x1",))
            self.assertEqual(loaded.snapshots[0].weapons[0].name, "Fire Staff")
            self.assertEqual(loaded.snapshots[0].weapons[0].upgraded_stats[12].display_value, "10")
            self.assertEqual(loaded.snapshots[0].weapons[0].upgraded_stats[11].display_value, "0.6x")
            self.assertEqual(loaded.snapshots[0].tomes[0].name, "Damage")
            self.assertEqual(loaded.snapshots[0].tomes[0].level, 3)
            self.assertEqual(loaded.snapshots[0].tomes[0].display_value, "1.25x")
            self.assertEqual(loaded.snapshots[0].banishes, ("Clover", "Golden Tome"))
            self.assertEqual(loaded.snapshots[0].chests_per_minute, 1.23)
            self.assertAlmostEqual(loaded.snapshots[0].game_time_seconds, 21.52338219)
            self.assertEqual(loaded.snapshots[0].mob_kills, 37)
            self.assertEqual(loaded.snapshots[0].player_level, 2)
            self.assertEqual(loaded.snapshots[1].items, ("Wrench x2", "Dice x1"))
            self.assertEqual(loaded.snapshots[1].weapons, ())
            self.assertEqual(loaded.snapshots[1].tomes, ())
            self.assertEqual(loaded.snapshots[1].banishes, ())
            self.assertEqual(loaded.snapshots[1].chests_per_minute, 2.34)
            self.assertAlmostEqual(loaded.snapshots[1].game_time_seconds, 81.75)
            self.assertEqual(loaded.snapshots[1].mob_kills, 12)
            self.assertEqual(loaded.snapshots[1].player_level, 4)
            self.assertEqual(loaded.snapshots[1].time_label, "01:00")

            vods = list_vods(Path(temp_dir))
            self.assertEqual([vod.name for vod in vods], ["Test run"])

            renamed = rename_vod(path, "Renamed run")
            self.assertEqual(renamed.name, "Renamed run")
            self.assertEqual(renamed.path.name, "Renamed run.jsonl")
            self.assertFalse(path.exists())
            self.assertEqual(load_vod(renamed.path).metadata.name, "Renamed run")

            delete_vod(renamed.path)
            self.assertFalse(renamed.path.exists())

    def test_rename_vod_sanitizes_filename_and_avoids_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first_path = root / "first.jsonl"
            first_path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":3,"name":"First","created_at":"2026-05-10T16:00:00","snapshot_interval_seconds":30}',
                        '{"type":"summary","duration_seconds":0,"snapshot_count":0}',
                    ],
                )
                + "\n",
                encoding="utf-8",
            )
            second_path = root / "Target_Name.jsonl"
            second_path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":3,"name":"Second","created_at":"2026-05-10T16:01:00","snapshot_interval_seconds":30}',
                        '{"type":"summary","duration_seconds":0,"snapshot_count":0}',
                    ],
                )
                + "\n",
                encoding="utf-8",
            )

            renamed = rename_vod(first_path, 'Target:Name')

            self.assertEqual(renamed.path.name, "Target_Name-1.jsonl")
            self.assertTrue(renamed.path.exists())
            self.assertEqual(load_vod(renamed.path).metadata.name, "Target:Name")

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

    def test_load_vod_keeps_backward_compatibility_when_in_game_time_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "old-format.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":2,"name":"Old run","created_at":"2026-05-10T16:00:00","snapshot_interval_seconds":60}',
                        '{"type":"snapshot","elapsed_seconds":0,"captured_at":1000.0,"stats":{"Damage":{"value":1.25,"display":"1.25x"}},"items":["Wrench x1"],"chests_per_minute":1.23}',
                        '{"type":"summary","duration_seconds":0,"snapshot_count":1}',
                    ],
                )
                + "\n",
                encoding="utf-8",
            )

            loaded = load_vod(path)

            self.assertIsNone(loaded.snapshots[0].game_time_seconds)
            self.assertIsNone(loaded.snapshots[0].mob_kills)
            self.assertEqual(loaded.snapshots[0].weapons, ())
            self.assertEqual(loaded.snapshots[0].tomes, ())
            self.assertEqual(loaded.snapshots[0].banishes, ())

    def test_delete_vods_below_snapshot_count_removes_only_short_recordings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            short_path = root / "short.jsonl"
            short_path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":3,"name":"Short","created_at":"2026-05-10T16:00:00","snapshot_interval_seconds":30}',
                        '{"type":"summary","duration_seconds":5,"snapshot_count":1}',
                    ],
                )
                + "\n",
                encoding="utf-8",
            )
            keep_path = root / "keep.jsonl"
            keep_path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":3,"name":"Keep","created_at":"2026-05-10T16:01:00","snapshot_interval_seconds":30}',
                        '{"type":"summary","duration_seconds":30,"snapshot_count":3}',
                    ],
                )
                + "\n",
                encoding="utf-8",
            )

            removed = delete_vods_below_snapshot_count(2, root)

            self.assertEqual(removed, 1)
            self.assertFalse(short_path.exists())
            self.assertTrue(keep_path.exists())

    def test_recorder_stop_deletes_empty_recordings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(vods_dir=Path(temp_dir), interval_seconds=30, clock=lambda: 1000.0)

            path = recorder.start(name="Empty run", seed=123)
            status = recorder.stop()

            self.assertEqual(status, "deleted_empty")
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
