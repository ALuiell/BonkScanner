from __future__ import annotations

import json
import src
from infra import vod_storage as vod_storage

from types import SimpleNamespace
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.character_passives import (
    CharacterPassiveEffectKind,
    CharacterPassiveEffectSnapshot,
    CharacterPassiveSnapshot,
    CharacterPassiveStatus,
)
from core.stats.formats import PlayerStatFormat, WeaponStatFormat
from core.stats.types import ChaosTomeSnapshot, ChaosTomeStatSnapshot, DamageSourceSnapshot, TomeSnapshot, WeaponSnapshot, WeaponStatValue
from core.vod_capture import VodCapturePayload
from infra.vod_storage import LEGACY_VODS_DIR, RECORDINGS_DIR, UnsupportedVodVersionError, VodFormatError, VodRecorder, delete_vod, delete_vods_below_snapshot_count, list_vods, load_cached_vods, load_vod, load_vod_metadata, rename_vod, refresh_vod_metadata_index
from projections import formatting


class FakeRecordingSettings:
    """A RecordingSettings that keeps the index in memory."""

    def __init__(self) -> None:
        self.index: dict = {}

    def read_metadata_index(self) -> dict:
        return self.index

    def write_metadata_index(self, payload: dict) -> None:
        self.index = payload


def capture(recorder, stats, *values, **fields):
    for name, value in zip(
        ("items", "weapons", "tomes", "banishes", "damage_sources"),
        values,
    ):
        fields[name] = value
    return recorder.capture(VodCapturePayload(stats=stats, **fields))


class VodStorageTests(unittest.TestCase):
    def test_vod_versions_one_through_ten_and_missing_version_are_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for version in (None, *range(1, 11)):
                suffix = "" if version is None else f',"version":{version}'
                path = Path(temp_dir) / f"v{version or 'missing'}.jsonl"
                path.write_text(
                    f'{{"type":"metadata"{suffix},"name":"Run","created_at":"2026-01-01T00:00:00","snapshot_interval_seconds":30}}\n',
                    encoding="utf-8",
                )
                self.assertEqual(load_vod(path).metadata.name, "Run")

    def test_future_and_malformed_vod_versions_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            future = Path(temp_dir) / "future.jsonl"
            future.write_text('{"type":"metadata","version":11,"name":"Run"}\n', encoding="utf-8")
            with self.assertRaises(UnsupportedVodVersionError):
                load_vod(future)

            for index, value in enumerate(('"10"', "0", "-1", "1.5", "true")):
                malformed = Path(temp_dir) / f"malformed-{index}.jsonl"
                malformed.write_text(
                    f'{{"type":"metadata","version":{value},"name":"Run"}}\n',
                    encoding="utf-8",
                )
                with self.assertRaises(VodFormatError):
                    load_vod(malformed)

    def test_recording_kill_count_uses_compact_suffixes(self) -> None:
        expected = {
            0: "0",
            970: "970",
            999: "999",
            1_000: "1K",
            10_000: "10K",
            970_000: "970K",
            16_000_000: "16M",
        }
        for value, display in expected.items():
            with self.subTest(value=value):
                self.assertEqual(
                    vod_storage.format_recording_kill_count(value),
                    display,
                )

    def test_character_default_name_metadata_and_passive_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(
                vods_dir=Path(temp_dir), interval_seconds=30, clock=lambda: 1000.0
            )
            passive = CharacterPassiveSnapshot(
                character_id=18,
                character_name="Dice",
                passive_id=15,
                passive_name="Gamba",
                runtime_class="PassiveAbilityGamba",
                level=145,
                status=CharacterPassiveStatus.SUPPORTED,
                effects=(
                    CharacterPassiveEffectSnapshot(
                        key="stat:5",
                        label="Evasion",
                        value=0.105954933912,
                        value_format=PlayerStatFormat.PERCENT,
                        kind=CharacterPassiveEffectKind.PERMANENT_ROLL,
                        stat_id=5,
                        count=4,
                    ),
                ),
                coverage="complete",
            )
            path = recorder.start(
                seed=123,
                character_id=18,
                character_name="Dice",
            )
            capture(recorder,
                {},
                character_passive=passive,
                mob_kills=970_000,
            )
            # A disappearing process can expose a reset counter during the
            # best-effort final capture. The completed name keeps the run max.
            capture(recorder, {}, mob_kills=12)
            recorder.stop()

            loaded = load_vod(path)
            self.assertRegex(
                loaded.metadata.name,
                r"^Dice 970K \d{4}-\d{2}-\d{2} ",
            )
            self.assertEqual(load_vod_metadata(path).name, loaded.metadata.name)
            self.assertEqual(loaded.metadata.character_id, 18)
            self.assertEqual(loaded.metadata.character_name, "Dice")
            self.assertEqual(loaded.snapshots[0].character_passive, passive)

    def test_custom_name_wins_over_character_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(vods_dir=Path(temp_dir), clock=lambda: 1000.0)
            path = recorder.start(
                name="My challenge",
                character_id=0,
                character_name="Fox",
            )
            for _ in range(3):
                capture(recorder, {}, mob_kills=16_000_000)
            recorder.stop()
            self.assertEqual(load_vod_metadata(path).name, "My challenge")

    def test_older_recording_has_no_character_metadata_or_passive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "old.jsonl"
            path.write_text(
                '{"type":"metadata","version":8,"name":"Run old","created_at":"2026-08-22T10:00:00","snapshot_interval_seconds":30}\n'
                '{"type":"snapshot","elapsed_seconds":0,"captured_at":1,"stats":{}}\n'
                '{"type":"summary","duration_seconds":0,"snapshot_count":1}\n',
                encoding="utf-8",
            )
            loaded = load_vod(path)
            self.assertIsNone(loaded.metadata.character_id)
            self.assertIsNone(loaded.metadata.character_name)
            self.assertIsNone(loaded.snapshots[0].character_passive)

    def test_vod_metadata_index_persists_and_drops_deleted_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            from infra import vod_storage as vod_storage

            root = Path(temp_dir) / "recordings"
            root.mkdir()
            path = root / "indexed-run.jsonl"
            path.write_text(
                '{"type":"metadata","version":6,"name":"Indexed run","created_at":"2026-05-10T16:00:00","snapshot_interval_seconds":30}\n'
                '{"type":"summary","duration_seconds":90,"snapshot_count":3}\n',
                encoding="utf-8",
            )
            # Injected rather than reached for: this used to patch the real
            # config.user_config, so the test mutated the developer's own config.
            settings = FakeRecordingSettings()
            old_recordings, old_legacy = (
                vod_storage.RECORDINGS_DIR,
                vod_storage.LEGACY_VODS_DIR,
            )
            try:
                vod_storage.RECORDINGS_DIR = root
                vod_storage.LEGACY_VODS_DIR = Path(temp_dir) / "missing-legacy"
                refreshed = refresh_vod_metadata_index(settings)
                self.assertEqual([vod.name for vod in refreshed], ["Indexed run"])
                self.assertEqual([vod.name for vod in load_cached_vods(settings)], ["Indexed run"])
                self.assertEqual(settings.index.get("version"), 1)
                self.assertEqual(len(settings.index.get("records", [])), 1)

                path.unlink()
                refreshed = refresh_vod_metadata_index(settings)
                self.assertEqual(refreshed, [])
                self.assertEqual(load_cached_vods(settings), [])
                self.assertEqual(settings.index.get("records"), [])
            finally:
                vod_storage.RECORDINGS_DIR = old_recordings
                vod_storage.LEGACY_VODS_DIR = old_legacy

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

    def test_recorder_enforces_minimum_snapshot_interval(self) -> None:
        recorder = VodRecorder(interval_seconds=1)

        self.assertEqual(
            recorder.interval_seconds,
            vod_storage.MIN_RECORDING_SNAPSHOT_INTERVAL_SECONDS,
        )

        recorder.interval_seconds = 5
        self.assertEqual(
            recorder.interval_seconds,
            vod_storage.MIN_RECORDING_SNAPSHOT_INTERVAL_SECONDS,
        )

        recorder.interval_seconds = 60
        self.assertEqual(recorder.interval_seconds, 60)

    def test_failed_start_does_not_leave_a_phantom_active_recorder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(vods_dir=Path(temp_dir), clock=lambda: 1000.0)
            with patch.object(Path, "open", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(OSError, "disk full"):
                    recorder.start()

            self.assertFalse(recorder.is_recording)
            self.assertIsNone(recorder._file)
            self.assertIsNone(recorder.path)
            self.assertEqual("", recorder.name)

    def test_failed_metadata_write_closes_and_removes_partial_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(vods_dir=Path(temp_dir), clock=lambda: 1000.0)
            with patch.object(
                recorder, "_write_record", side_effect=OSError("flush failed")
            ):
                with self.assertRaisesRegex(OSError, "flush failed"):
                    recorder.start()

            self.assertFalse(recorder.is_recording)
            self.assertIsNone(recorder._file)
            self.assertIsNone(recorder.path)
            self.assertEqual([], list(Path(temp_dir).glob("*.jsonl")))

    def test_failed_summary_write_still_closes_the_recording_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(vods_dir=Path(temp_dir), clock=lambda: 1000.0)
            path = recorder.start()
            with patch.object(
                recorder, "_write_record", side_effect=OSError("disk removed")
            ):
                with self.assertRaisesRegex(OSError, "disk removed"):
                    recorder.stop()

            self.assertFalse(recorder.is_recording)
            self.assertIsNone(recorder._file)
            # Keep the recoverable partial recording; a failed summary must not
            # turn into an implicit delete.
            self.assertTrue(path.exists())

    def test_start_refuses_to_replace_an_open_recording(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(vods_dir=Path(temp_dir), clock=lambda: 1000.0)
            first_path = recorder.start()

            with self.assertRaisesRegex(RuntimeError, "already active"):
                recorder.start()

            self.assertEqual(first_path, recorder.path)
            self.assertTrue(recorder.is_recording)
            recorder.stop()

    def test_recorder_writes_loads_and_renames_vod(self) -> None:
        now = 1000.0
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(
                vods_dir=Path(temp_dir),
                interval_seconds=60,
                clock=lambda: now,
            )

            path = recorder.start(name="Test run", seed=12345)
            capture(recorder,
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
                (
                    DamageSourceSnapshot(
                        source_key="FireStaff",
                        source_name="FireStaff",
                        damage=10662.599609375,
                        added_at_time=114.64570617675781,
                    ),
                    DamageSourceSnapshot(
                        source_key="CursedDoll",
                        source_name="CursedDoll",
                        damage=3198.958984375,
                        added_at_time=166.73388671875,
                    ),
                ),
                chaos_tome=ChaosTomeSnapshot(
                    level=7,
                    stats=(
                        ChaosTomeStatSnapshot(
                            stat_id=12,
                            label="Damage",
                            value=0.168,
                            value_format=PlayerStatFormat.MULTIPLIER,
                            rolls=1,
                        ),
                        ChaosTomeStatSnapshot(
                            stat_id=30,
                            label="Luck",
                            value=0.07,
                            value_format=PlayerStatFormat.PERCENT,
                            rolls=1,
                        ),
                    ),
                ),
                chests_per_minute=1.23,
                game_time_seconds=21.52338219,
                mob_kills=37,
                kps_at_capture=150,
                minute_avg_kps_at_capture=243,
                five_minute_avg_kps_at_capture=221,
                run_avg_kps_at_capture=138,
                player_level=2,
                map_seed=12345,
                stage_ptr=0x3000,
                stage_index=2,
                chests_opened=37,
                chests_total=46,
                pots_total=55,
                paid_chests=16,
                key_procs=19,
                free_chests=2,
                keys_count=13,
                expected_key_procs=18.4,
                chests_opened_by_stage={1: 37},
                chests_total_by_stage={1: 46},
            )
            now += 60
            capture(recorder,
                {
                    "Damage": SimpleNamespace(value=1.5, display_value="1.5x"),
                    "Armor": SimpleNamespace(value=0.2, display_value="20%"),
                },
                ("Wrench x2", "Dice x1"),
                (),
                (),
                (),
                (),
                chests_per_minute=2.34,
                game_time_seconds=81.75,
                mob_kills=12,
                kps_at_capture=160,
                minute_avg_kps_at_capture=250,
                five_minute_avg_kps_at_capture=225,
                run_avg_kps_at_capture=140,
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
            self.assertIsNotNone(loaded.snapshots[0].chaos_tome)
            self.assertEqual(loaded.snapshots[0].chaos_tome.level, 7)
            self.assertEqual(
                [(stat.stat_id, stat.label, stat.display_delta) for stat in loaded.snapshots[0].chaos_tome.stats],
                [(12, "Damage", "+16.8%"), (30, "Luck", "+7%")],
            )
            self.assertEqual(loaded.snapshots[0].banishes, ("Clover", "Golden Tome"))
            self.assertEqual(loaded.snapshots[0].damage_sources[0].source_key, "FireStaff")
            self.assertEqual(loaded.snapshots[0].damage_sources[0].source_name, "FireStaff")
            self.assertAlmostEqual(loaded.snapshots[0].damage_sources[0].damage, 10662.599609375)
            self.assertEqual(loaded.snapshots[0].chests_per_minute, 1.23)
            self.assertAlmostEqual(loaded.snapshots[0].game_time_seconds, 21.52338219)
            self.assertEqual(loaded.snapshots[0].mob_kills, 37)
            self.assertEqual(loaded.snapshots[0].kps_at_capture, 150)
            self.assertEqual(loaded.snapshots[0].minute_avg_kps_at_capture, 243)
            self.assertEqual(loaded.snapshots[0].five_minute_avg_kps_at_capture, 221)
            self.assertEqual(loaded.snapshots[0].run_avg_kps_at_capture, 138)
            self.assertEqual(loaded.snapshots[0].player_level, 2)
            self.assertEqual(loaded.snapshots[0].map_seed, 12345)
            self.assertEqual(loaded.snapshots[0].stage_ptr, 0x3000)
            self.assertEqual(loaded.snapshots[0].stage_index, 2)
            self.assertEqual(loaded.snapshots[0].chests_opened, 37)
            self.assertEqual(loaded.snapshots[0].chests_total, 46)
            self.assertEqual(loaded.snapshots[0].pots_total, 55)
            self.assertEqual(loaded.snapshots[0].paid_chests, 16)
            self.assertEqual(loaded.snapshots[0].key_procs, 19)
            self.assertEqual(loaded.snapshots[0].free_chests, 2)
            self.assertEqual(loaded.snapshots[0].keys_count, 13)
            self.assertEqual(loaded.snapshots[0].expected_key_procs, 18.4)
            self.assertEqual(loaded.snapshots[0].chests_opened_by_stage, {1: 37})
            self.assertEqual(loaded.snapshots[0].chests_total_by_stage, {1: 46})
            self.assertEqual(loaded.snapshots[1].items, ("Wrench x2", "Dice x1"))
            self.assertEqual(loaded.snapshots[1].weapons, ())
            self.assertEqual(loaded.snapshots[1].tomes, ())
            self.assertEqual(loaded.snapshots[1].banishes, ())
            self.assertEqual(loaded.snapshots[1].damage_sources, ())
            self.assertEqual(loaded.snapshots[1].chests_per_minute, 2.34)
            self.assertAlmostEqual(loaded.snapshots[1].game_time_seconds, 81.75)
            self.assertEqual(loaded.snapshots[1].mob_kills, 12)
            self.assertEqual(loaded.snapshots[1].kps_at_capture, 160)
            self.assertEqual(loaded.snapshots[1].minute_avg_kps_at_capture, 250)
            self.assertEqual(loaded.snapshots[1].five_minute_avg_kps_at_capture, 225)
            self.assertEqual(loaded.snapshots[1].run_avg_kps_at_capture, 140)
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

    def test_recorder_writes_non_finite_measurements_as_json_null(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(
                vods_dir=Path(temp_dir), interval_seconds=60, clock=lambda: 1000.0
            )
            path = recorder.start(name="Overflow run")
            capture(recorder,
                {
                    "Damage": SimpleNamespace(
                        value=float("nan"), display_value="--"
                    )
                },
                damage_sources=(
                    DamageSourceSnapshot(
                        source_key="Dragonfire",
                        source_name="Dragonfire",
                        damage=float("inf"),
                    ),
                ),
                chests_per_minute=float("-inf"),
                loot_expected={"LEGENDARY": float("inf")},
            )
            recorder.stop()

            for line in path.read_text(encoding="utf-8").splitlines():
                json.loads(
                    line,
                    parse_constant=lambda constant: self.fail(
                        f"writer emitted non-standard JSON constant {constant}"
                    ),
                )

            snapshot = load_vod(path).snapshots[0]
            self.assertIsNone(snapshot.stats["Damage"].value)
            self.assertIsNone(snapshot.damage_sources[0].damage)
            self.assertIsNone(snapshot.chests_per_minute)
            self.assertEqual(snapshot.loot_expected, {})

    def test_legacy_non_finite_measurements_load_as_unknown_and_rename_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy-overflow.jsonl"
            path.write_text(
                '\n'.join(
                    [
                        '{"type":"metadata","version":7,"name":"Legacy overflow","created_at":"2026-08-21T11:17:10","snapshot_interval_seconds":60}',
                        '{"type":"snapshot","elapsed_seconds":60,"captured_at":1000.0,"stats":{"Damage":{"value":NaN,"display":"--"}},"damage_sources":[{"source_key":"Dragonfire","source_name":"Dragonfire","damage":Infinity}],"chests_per_minute":-Infinity,"game_time_seconds":1e400}',
                        '{"type":"summary","duration_seconds":60,"snapshot_count":1}',
                    ]
                )
                + '\n',
                encoding="utf-8",
            )

            snapshot = load_vod(path).snapshots[0]

            self.assertIsNone(snapshot.stats["Damage"].value)
            self.assertIsNone(snapshot.damage_sources[0].damage)
            self.assertIsNone(snapshot.chests_per_minute)
            self.assertIsNone(snapshot.game_time_seconds)

            renamed = rename_vod(path, "Clean overflow")
            cleaned_text = renamed.path.read_text(encoding="utf-8")
            self.assertNotIn("NaN", cleaned_text)
            self.assertNotIn("Infinity", cleaned_text)
            for line in cleaned_text.splitlines():
                json.loads(
                    line,
                    parse_constant=lambda constant: self.fail(
                        f"rename emitted non-standard JSON constant {constant}"
                    ),
                )

    def test_load_vod_recovers_an_incomplete_final_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "interrupted.jsonl"
            path.write_bytes(
                b'{"type":"metadata","version":7,"name":"Interrupted","created_at":"2026-08-21T11:17:10","snapshot_interval_seconds":60}\n'
                b'{"type":"snapshot","elapsed_seconds":60,"captured_at":1000.0,"stats":{}}\n'
                b'{"type":"summary","duration_seconds"'
            )

            metadata = load_vod_metadata(path)
            loaded = load_vod(path)

            self.assertEqual(metadata.name, "Interrupted")
            self.assertEqual(metadata.snapshot_count, 1)
            self.assertEqual(metadata.duration_seconds, 60)
            self.assertEqual(len(loaded.snapshots), 1)

    def test_load_vod_rejects_a_malformed_complete_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "corrupt.jsonl"
            path.write_bytes(
                b'{"type":"metadata","version":7,"name":"Corrupt","created_at":"2026-08-21T11:17:10","snapshot_interval_seconds":60}\n'
                b'{"type":"snapshot","elapsed_seconds"\n'
                b'{"type":"summary","duration_seconds":60,"snapshot_count":1}\n'
            )

            with self.assertRaises(json.JSONDecodeError):
                load_vod(path)
            # Listing deliberately trusts the first/last-record fast path; the
            # payload is validated when the user actually opens the run.
            self.assertEqual(load_vod_metadata(path).name, "Corrupt")

    def test_load_vod_does_not_hide_a_malformed_completed_tail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "corrupt-tail.jsonl"
            path.write_bytes(
                b'{"type":"metadata","version":7,"name":"Corrupt tail","created_at":"2026-08-21T11:17:10","snapshot_interval_seconds":60}\n'
                b'{"type":"snapshot","elapsed_seconds":60,"captured_at":1000.0,"stats":{}}\n'
                b'{"type":"summary","duration_seconds"\n'
            )

            with self.assertRaises(json.JSONDecodeError):
                load_vod(path)
            with self.assertRaises(json.JSONDecodeError):
                load_vod_metadata(path)

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
                from infra import vod_storage as vod_storage

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

    def test_explicit_unknown_chest_rate_survives_recording_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(
                vods_dir=Path(temp_dir), interval_seconds=60, clock=lambda: 1000.0
            )
            path = recorder.start(name="Unknown chest rate")
            capture(recorder,
                {
                    "Elite Spawn Increase": SimpleNamespace(
                        value=15.0,
                        display_value="15",
                    ),
                    "Powerup Drop Chance": SimpleNamespace(
                        value=2.0,
                        display_value="2",
                    ),
                },
                chests_per_minute=None,
            )
            recorder.stop()

            snapshot = load_vod(path).snapshots[0]

            self.assertTrue(snapshot.chests_per_minute_recorded)
            self.assertIsNone(snapshot.chests_per_minute)
            self.assertIsNone(formatting.resolve_snapshot_chests_per_minute(snapshot))

    def test_legacy_missing_chest_rate_field_keeps_historical_estimate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "legacy-chest-rate.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":2,"name":"Old run","created_at":"2026-05-10T16:00:00","snapshot_interval_seconds":60}',
                        '{"type":"snapshot","elapsed_seconds":0,"captured_at":1000.0,"stats":{"Elite Spawn Increase":{"value":15.0,"display":"15"},"Powerup Drop Chance":{"value":2.0,"display":"2"}},"items":[]}',
                        '{"type":"summary","duration_seconds":0,"snapshot_count":1}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            snapshot = load_vod(path).snapshots[0]

            self.assertFalse(snapshot.chests_per_minute_recorded)
            self.assertAlmostEqual(
                formatting.resolve_snapshot_chests_per_minute(snapshot),
                formatting.calculate_player_chests_per_minute(snapshot.stats),
            )

    def test_loot_totals_round_trip_through_a_recording(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(
                vods_dir=Path(temp_dir), interval_seconds=60, clock=lambda: 1000.0
            )
            path = recorder.start(name="Loot run")
            capture(recorder,
                {},
                loot_actual={"LEGENDARY": 116, "RARE": 78, "UNCOMMON": 38, "COMMON": 45},
                loot_expected={"LEGENDARY": 118.4, "RARE": 78.0, "UNCOMMON": 36.2, "COMMON": 45.0},
            )
            recorder.stop()

            snapshot = load_vod(path).snapshots[0]

            self.assertEqual(116, snapshot.loot_actual["LEGENDARY"])
            self.assertAlmostEqual(36.2, snapshot.loot_expected["UNCOMMON"])

    def test_a_recording_without_the_field_reads_as_not_recorded_not_zero(self) -> None:
        """The explicit missing-value path, and the whole reason for it.

        Older files have no such key, and so does any run the tracker could not
        measure. Both mean "not recorded". Reading that as zero would say the
        run gained no items of that tier, which is a different and false claim
        -- so the load must produce `None`, and nothing downstream may default
        it.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "no-loot-field.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":6,"name":"Older run","created_at":"2026-07-01T10:00:00","snapshot_interval_seconds":10}',
                        '{"type":"snapshot","elapsed_seconds":0,"captured_at":1000.0,"stats":{},"items":[],"key_procs":3}',
                        '{"type":"summary","duration_seconds":0,"snapshot_count":1}',
                    ],
                )
                + "\n",
                encoding="utf-8",
            )

            snapshot = load_vod(path).snapshots[0]

            self.assertIsNone(snapshot.loot_actual)
            self.assertIsNone(snapshot.loot_expected)
            self.assertEqual(3, snapshot.key_procs, "the rest of the record still loads")

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

            result = delete_vods_below_snapshot_count(2, root)

            self.assertEqual(result.removed, 1)
            self.assertEqual(result.skipped_active, 0)
            self.assertEqual(result.skipped_locked, 0)
            self.assertFalse(short_path.exists())
            self.assertTrue(keep_path.exists())

    def test_delete_vods_below_snapshot_count_skips_active_and_locked_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            active_path = root / "active.jsonl"
            locked_path = root / "locked.jsonl"
            removable_path = root / "removable.jsonl"
            for path, name in (
                (active_path, "Active"),
                (locked_path, "Locked"),
                (removable_path, "Removable"),
            ):
                path.write_text(
                    "\n".join(
                        [
                            f'{{"type":"metadata","version":3,"name":"{name}","created_at":"2026-05-10T16:00:00","snapshot_interval_seconds":30}}',
                            '{"type":"summary","duration_seconds":5,"snapshot_count":1}',
                        ]
                    )
                    + "\n",
                    encoding="utf-8",
                )

            original_delete_vod = vod_storage.delete_vod

            def delete_with_locked_file(path: Path) -> None:
                if path == locked_path:
                    raise PermissionError("file is in use")
                original_delete_vod(path)

            with patch.object(vod_storage, "delete_vod", side_effect=delete_with_locked_file):
                result = delete_vods_below_snapshot_count(
                    2,
                    root,
                    excluded_paths={active_path},
                )

            self.assertEqual(result.removed, 1)
            self.assertEqual(result.skipped_active, 1)
            self.assertEqual(result.skipped_locked, 1)
            self.assertTrue(active_path.exists())
            self.assertTrue(locked_path.exists())
            self.assertFalse(removable_path.exists())

    def test_recorder_stop_deletes_empty_recordings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            recorder = VodRecorder(vods_dir=Path(temp_dir), interval_seconds=30, clock=lambda: 1000.0)

            path = recorder.start(name="Empty run", seed=123)
            status = recorder.stop()

            self.assertEqual(status, "deleted_empty")
            self.assertFalse(path.exists())

    def test_repeated_strings_are_one_object_across_a_loaded_recording(self) -> None:
        """The load's string pool, asserted by identity because that is the point.

        A recording is one JSON object per line, so the decoder runs per line
        and drops its key memo in between: without the pool, a file of 713
        snapshots holds 713 copies of every stat name and of the few display
        strings the stats cycle through. Measured on the real library that was
        5 MB of the 19 a single recording cost.

        Equality would pass with or without the pool -- the copies are equal,
        that is the whole problem -- so this asserts `is`. It does not assert a
        byte count: the saving depends on the file, and a test that pinned one
        would be reporting on this fixture rather than on the sharing.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "repeats.jsonl"
            snapshot = (
                '{{"type":"snapshot","elapsed_seconds":{elapsed},"captured_at":{elapsed}.0,'
                '"stats":{{"Damage":{{"value":1.25,"display":"1.25x"}},'
                '"Crit Chance":{{"value":0.1,"display":"10%"}}}},'
                '"items":["Wrench x1"],"banishes":["Boots"],'
                '"weapons":[{{"id":1,"name":"Hammer","level":2}}],'
                '"tomes":[{{"id":2,"name":"Tome of Speed","stat_label":"Movement Speed"}}],'
                '"damage_sources":[{{"source_key":"hammer","source_name":"Hammer","damage":5.0}}]}}'
            )
            path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":7,"name":"Repeats","created_at":"2026-08-01T10:00:00","snapshot_interval_seconds":10}',
                    ]
                    + [snapshot.format(elapsed=elapsed) for elapsed in (0, 10, 20)]
                    + ['{"type":"summary","duration_seconds":20,"snapshot_count":3}']
                )
                + "\n",
                encoding="utf-8",
            )

            first, second, third = load_vod(path).snapshots

            def key_of(snapshot, name):
                return next(key for key in snapshot.stats if key == name)

            for name in ("Damage", "Crit Chance"):
                self.assertIs(key_of(first, name), key_of(second, name))
                self.assertIs(key_of(first, name), key_of(third, name))

            self.assertIs(
                first.stats["Damage"].display_value,
                third.stats["Damage"].display_value,
            )
            self.assertIs(first.items[0], third.items[0])
            self.assertIs(first.banishes[0], third.banishes[0])
            self.assertIs(first.weapons[0].name, third.weapons[0].name)
            self.assertIs(first.tomes[0].name, third.tomes[0].name)
            self.assertIs(first.tomes[0].stat_label, third.tomes[0].stat_label)
            self.assertIs(
                first.damage_sources[0].source_name,
                third.damage_sources[0].source_name,
            )

    def test_the_snapshot_types_carry_no_per_instance_dict(self) -> None:
        """`slots=True` on the two types that exist in five figures.

        One recording builds a `VodSnapshot` per capture and a `VodStatValue`
        per stat per capture -- 855 and 25,650 for a run in the real library.
        A dataclass without slots gives each one a `__dict__`, and putting that
        back would cost about 1.5 MB per open recording with nothing failing.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "slots.jsonl"
            path.write_text(
                "\n".join(
                    [
                        '{"type":"metadata","version":7,"name":"Slots","created_at":"2026-08-01T10:00:00","snapshot_interval_seconds":10}',
                        '{"type":"snapshot","elapsed_seconds":0,"captured_at":1000.0,"stats":{"Damage":{"value":1.0,"display":"1x"}}}',
                        '{"type":"summary","duration_seconds":0,"snapshot_count":1}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            snapshot = load_vod(path).snapshots[0]

            self.assertFalse(hasattr(snapshot, "__dict__"))
            self.assertFalse(hasattr(snapshot.stats["Damage"], "__dict__"))


if __name__ == "__main__":
    unittest.main()
