from __future__ import annotations

import src  # noqa: F401
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from app.roll_analytics_view import RollRecordingCache
from core.roll_analysis_view import (
    expected_rolls, normalize_selected_stats, summarize_selected, valid_recorded_counter_block,
)
from core.roll_analytics import aggregate_roll_counts
from infra import roll_recording as reader
from infra.vod_storage import UnsupportedVodVersionError, VOD_FORMAT_VERSION, VodFormatError


def frame(dice=None, chaos=None, time=100):
    return {
        "type": "snapshot", "game_time_seconds": time, "elapsed_seconds": time,
        "character_passive": None if dice is None else {
            "character_id": 18, "character_name": "Dice", "passive_id": 18,
            "runtime_class": "PassiveAbilityGamba", "level": sum(dice.values()),
            "status": "supported", "coverage": "complete", "ambiguous": 0,
            "pending": 103,  # Unrelated candidate queue must not invalidate Dice.
            "effects": [{"kind": "permanent_roll", "stat_id": i, "count": n,
                         "value": 1, "value_format": "flat"} for i, n in dice.items()],
        },
        "chaos_tome": None if chaos is None else {
            "level": sum(chaos.values()), "ambiguous_rolls": 0,
            "stats": [{"stat_id": i, "rolls": n, "value": 1,
                       "value_format": "flat"} for i, n in chaos.items()],
        },
    }


def write_recording(path, snapshots, *, version=VOD_FORMAT_VERSION, summary=True):
    records = [{"type": "metadata", "version": version, "name": "Test recording",
                "created_at": "2026-10-08T12:00:00"}, *snapshots]
    if summary:
        records.append({"type": "summary", "name": "Final name"})
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    return path


class RollSelectionTests(unittest.TestCase):
    def test_selected_group_keeps_full_denominator_and_deduplicates(self):
        snapshot = aggregate_roll_counts("dice", {12: 20, 18: 10, 30: 70})
        result = summarize_selected(snapshot, [12, 18, 12, 999])
        self.assertEqual((result.count, result.total, result.percent, result.selected_stats), (30, 100, 30, 2))
        self.assertAlmostEqual(result.expected, 200 / 27)
        self.assertAlmostEqual(result.difference, 30 - 200 / 27)

    def test_empty_sample_and_empty_selection_are_not_zero_percent(self):
        self.assertIsNone(summarize_selected(aggregate_roll_counts("chaos", {}), [12]).percent)
        self.assertIsNone(summarize_selected(aggregate_roll_counts("chaos", {12: 1}), []).percent)
        self.assertIsNone(expected_rolls("dice", 0, [12]))

    def test_uniform_model_and_unknown_pool_fail_closed(self):
        self.assertEqual(expected_rolls("chaos", 270, [12]), 10)
        self.assertEqual(expected_rolls("dice", 270, [12, 18, 17]), 30)
        self.assertIsNone(expected_rolls("shrine", 270, [12]))
        with patch("core.roll_analysis_view.ROLL_STAT_IDS", frozenset({12})):
            self.assertIsNone(expected_rolls("dice", 270, [12]))

    def test_normalize_preferences_does_not_accept_bool_string_or_unknown(self):
        self.assertEqual(normalize_selected_stats([True, "12", 12, 12, 999, 17]), (12, 17))
        self.assertEqual(normalize_selected_stats({"12": True}), ())

    def test_missing_counts_and_duplicate_rows_are_not_confirmed(self):
        raw = frame(dice={12: 2})["character_passive"]
        self.assertTrue(valid_recorded_counter_block(raw, "dice"))
        raw["effects"][0].pop("count")
        self.assertFalse(valid_recorded_counter_block(raw, "dice"))
        raw = frame(chaos={12: 2})["chaos_tome"]
        raw["stats"].append(deepcopy(raw["stats"][0]))
        raw["level"] = 4
        self.assertFalse(valid_recorded_counter_block(raw, "chaos"))

    def test_invalid_ambiguity_counters_are_not_coerced_to_confirmation(self):
        for source, key, raw in (
            ("dice", "ambiguous", frame(dice={12: 2})["character_passive"]),
            ("chaos", "ambiguous_rolls", frame(chaos={12: 2})["chaos_tome"]),
        ):
            for value in (-1, False, "0", None, 0.5):
                with self.subTest(source=source, value=value):
                    invalid = deepcopy(raw)
                    invalid[key] = value
                    self.assertFalse(valid_recorded_counter_block(invalid, source))


class RecordingTailTests(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "test.jsonl"

    def test_only_final_snapshot_is_used_and_history_is_never_summed(self):
        write_recording(self.path, [frame({12: 10}, {30: 2}, 10), frame({12: 15}, {30: 3}, 20)])
        original = self.path.read_bytes()
        result = reader.read_recorded_rolls(self.path)
        self.assertEqual(result.for_source("dice").analytics.total, 15)
        self.assertEqual(result.for_source("chaos").analytics.total, 3)
        self.assertEqual(result.snapshots_examined, 1)
        self.assertTrue(result.finalized)
        self.assertEqual(result.name, "Final name")
        self.assertEqual(self.path.read_bytes(), original)

    def test_bounded_fallback_is_independent_and_timestamped(self):
        last = frame({12: 3}, {30: 5}, 20)
        last["chaos_tome"]["ambiguous_rolls"] = 1
        write_recording(self.path, [frame({12: 2}, {30: 4}, 10), last])
        result = reader.read_recorded_rolls(self.path)
        self.assertEqual(result.for_source("dice").analytics.total, 3)
        self.assertFalse(result.for_source("dice").older_snapshot)
        chaos = result.for_source("chaos")
        self.assertEqual((chaos.analytics.total, chaos.game_time_seconds, chaos.older_snapshot), (4, 10, True))

    def test_does_not_search_past_four_snapshots(self):
        write_recording(self.path, [frame({12: 1}, {30: 2}, 1)] + [frame(time=t) for t in range(2, 6)])
        result = reader.read_recorded_rolls(self.path)
        self.assertEqual(result.snapshots_examined, 4)
        self.assertTrue(all(s.analytics is None for s in result.sources))

    def test_confirmed_zero_and_absent_source_are_different(self):
        write_recording(self.path, [frame(dice={}, chaos=None)])
        result = reader.read_recorded_rolls(self.path)
        self.assertEqual(result.for_source("dice").analytics.total, 0)
        self.assertIsNone(result.for_source("chaos").analytics)

    def test_legacy_missing_dice_counter_is_unavailable_not_zero(self):
        row = frame(dice={12: 2}, chaos={30: 4})
        row["character_passive"]["effects"][0].pop("count")
        write_recording(self.path, [row], version=9)
        result = reader.read_recorded_rolls(self.path)
        self.assertIsNone(result.for_source("dice").analytics)
        self.assertEqual(result.for_source("chaos").analytics.total, 4)

    def test_malformed_ambiguity_does_not_become_a_confirmed_recorded_source(self):
        last = frame({12: 2}, {30: 4})
        last["character_passive"]["ambiguous"] = -1
        write_recording(self.path, [last])
        result = reader.read_recorded_rolls(self.path)
        self.assertIsNone(result.for_source("dice").analytics)
        self.assertEqual(result.for_source("chaos").analytics.total, 4)
        last = frame({12: 2}, {30: 4})
        last["chaos_tome"]["ambiguous_rolls"] = 0.5
        write_recording(self.path, [last])
        result = reader.read_recorded_rolls(self.path)
        self.assertEqual(result.for_source("dice").analytics.total, 2)
        self.assertIsNone(result.for_source("chaos").analytics)

    def test_newer_version_is_rejected_before_using_tail(self):
        write_recording(self.path, [frame({12: 1}, {30: 2})], version=VOD_FORMAT_VERSION + 1)
        with self.assertRaises(UnsupportedVodVersionError):
            reader.read_recorded_rolls(self.path)

    def test_truncated_last_line_and_valid_line_without_newline(self):
        write_recording(self.path, [frame({12: 1}, {30: 2})], summary=False)
        self.path.write_bytes(self.path.read_bytes() + b'{"type":')
        result = reader.read_recorded_rolls(self.path)
        self.assertTrue(result.incomplete_tail)
        self.assertEqual(result.for_source("dice").analytics.total, 1)
        write_recording(self.path, [frame({12: 1}, {30: 2})], summary=False)
        self.path.write_bytes(self.path.read_bytes().rstrip(b"\n"))
        result = reader.read_recorded_rolls(self.path)
        self.assertFalse(result.incomplete_tail)
        self.assertEqual(result.for_source("chaos").analytics.total, 2)

    def test_corrupt_terminated_record_is_not_silently_skipped(self):
        write_recording(self.path, [frame({12: 1}, {30: 2})])
        self.path.write_bytes(self.path.read_bytes() + b'not json\n')
        with self.assertRaises(VodFormatError):
            reader.read_recorded_rolls(self.path)

    def test_long_snapshot_across_blocks_and_interleaved_powerups(self):
        last = frame({12: 5}, {30: 2})
        last["unrelated"] = "x" * (reader.CHUNK_SIZE * 3)
        write_recording(self.path, [last, {"type": "powerup_sample", "anything": "ignored"}])
        result = reader.read_recorded_rolls(self.path)
        self.assertEqual(result.for_source("dice").analytics.total, 5)
        self.assertEqual(result.snapshots_examined, 1)

    def test_large_recording_reads_only_a_small_tail(self):
        write_recording(self.path, [
            {"type": "powerup_sample", "unrelated": "x" * (5 * 1024 * 1024)},
            frame({12: 5}, {30: 2}),
        ])
        with patch.object(reader, "_loads_record", wraps=reader._loads_record) as parse:
            result = reader.read_recorded_rolls(self.path)
        self.assertLess(result.bytes_read, 2 * reader.CHUNK_SIZE)
        self.assertEqual(parse.call_count, 3)  # Metadata, summary, final snapshot.

    def test_byte_budget_does_not_trigger_full_file_fallback(self):
        write_recording(self.path, [frame({12: 5}, {30: 2}), {"type": "powerup_sample", "data": "x" * 8192}])
        with patch.object(reader, "TAIL_LIMIT", 4096):
            result = reader.read_recorded_rolls(self.path)
        self.assertEqual(result.snapshots_examined, 0)
        self.assertTrue(all(s.analytics is None for s in result.sources))
        self.assertLess(result.bytes_read, 4096 + reader.HEADER_LIMIT)

    def test_reverse_reader_handles_blank_lines_and_utf8(self):
        write_recording(self.path, [frame({12: 5}, {30: 2})])
        data = self.path.read_text(encoding="utf-8").replace("Final name", "Запись · Dice")
        self.path.write_text(data + "\n\n", encoding="utf-8")
        with patch.object(reader, "CHUNK_SIZE", 17):
            result = reader.read_recorded_rolls(self.path)
        self.assertEqual(result.name, "Запись · Dice")
        self.assertEqual(result.for_source("chaos").analytics.total, 2)

    def test_fallback_does_not_cross_run_clock_reset(self):
        write_recording(self.path, [frame({12: 20}, {30: 5}, 600), frame(time=2)])
        result = reader.read_recorded_rolls(self.path)
        self.assertTrue(all(s.analytics is None for s in result.sources))

    def test_cancelled_load_and_changed_file_do_not_publish(self):
        write_recording(self.path, [frame({12: 1}, {30: 2})])
        with self.assertRaises(InterruptedError):
            reader.read_recorded_rolls(self.path, cancelled=lambda: True)
        with patch.object(reader, "file_signature", return_value=(-1, -1)):
            with self.assertRaises(OSError):
                reader.read_recorded_rolls(self.path)

    def test_cache_reuses_summary_and_invalidates_on_file_change(self):
        write_recording(self.path, [frame({12: 1}, {30: 2})])
        read = Mock(wraps=reader.read_recorded_rolls)
        cache = RollRecordingCache(reader=read)
        first = cache.load(self.path)
        self.assertIs(cache.load(self.path), first)
        self.assertEqual(read.call_count, 1)
        write_recording(self.path, [frame({12: 150}, {30: 2})])
        self.assertEqual(cache.load(self.path).for_source("dice").analytics.total, 150)
        self.assertEqual(read.call_count, 2)

    def test_cache_is_bounded(self):
        read = Mock(wraps=reader.read_recorded_rolls)
        cache = RollRecordingCache(capacity=2, reader=read)
        paths = [write_recording(self.path.with_name(f"{i}.jsonl"), [frame({12: 1}, {30: 2})]) for i in range(3)]
        for path in paths:
            cache.load(path)
        cache.load(paths[0])
        self.assertEqual(read.call_count, 4)
