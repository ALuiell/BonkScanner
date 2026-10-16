from __future__ import annotations

import src

import math
import struct
import unittest

from core.stats.types import PlayerStatModifierSnapshot
from core.tracker.chaos import CHAOS_FINGERPRINTS, looks_like_chaos_value
from core.tracker.live_run import LiveRunTracker
from core.tracker.shrines import SHRINE_STAT_RULES


def modifier(ptr: int, value: float, stat_id: int = 12):
    rule = SHRINE_STAT_RULES[stat_id]
    return PlayerStatModifierSnapshot(
        stat_id=stat_id, label=rule.label, value=value,
        value_format=rule.value_format, object_ptr=ptr, modify_type=rule.modify_type,
    )


def counts(tracker):
    snapshot = tracker.chaos_tome_snapshot()
    return {stat.stat_id: stat.rolls for stat in snapshot.stats} if snapshot else {}


class ChaosTrackingEdgeTests(unittest.TestCase):
    def test_negative_new_modifier_preserves_budget_for_real_grant(self):
        tracker = LiveRunTracker()
        bad = modifier(100, -0.168)
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (bad,)})
        self.assertEqual(counts(tracker), {})
        tracker.update_chaos_tome(
            chaos_level=1, permanent_modifiers={12: (bad, modifier(200, 0.168))})
        self.assertEqual(counts(tracker), {12: 1})
        self.assertAlmostEqual(tracker.chaos_tome_snapshot().stats[0].value, 0.168)

    def test_decreasing_modifier_does_not_consume_new_level_budget(self):
        tracker = LiveRunTracker()
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (modifier(100, 0.168),)})
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={12: (modifier(100, 0.0),)})
        self.assertEqual(counts(tracker), {12: 1})
        tracker.update_chaos_tome(
            chaos_level=2, permanent_modifiers={12: (modifier(100, 0.0), modifier(200, 0.168))})
        self.assertEqual(counts(tracker), {12: 2})
        self.assertAlmostEqual(tracker.chaos_tome_snapshot().stats[0].value, 0.336)

    def test_negative_then_positive_same_pointer_is_one_grant(self):
        tracker = LiveRunTracker()
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={12: (modifier(100, -0.168),)})
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={12: (modifier(100, 0.168),)})
        self.assertEqual(counts(tracker), {12: 1})

    def test_settled_object_moving_after_source_filter_is_not_a_new_roll(self):
        tracker = LiveRunTracker()
        first, second = modifier(100, 0.168), modifier(200, 0.336)
        for _ in range(5):
            tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (first, second)})
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={12: (second,)})
        self.assertEqual(counts(tracker), {12: 1})
        tracker.update_chaos_tome(
            chaos_level=2, permanent_modifiers={12: (second, modifier(300, 0.168))})
        self.assertEqual(counts(tracker), {12: 2})

    def test_reordered_and_returning_objects_are_not_counted_twice(self):
        tracker = LiveRunTracker()
        first, second = modifier(100, 0.168), modifier(200, 0.336)
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={12: (first, second)})
        for entries in ((second, first), (), (second,), (first, second)):
            tracker.update_chaos_tome(chaos_level=3, permanent_modifiers={12: entries})
            self.assertEqual(counts(tracker), {12: 2})
        tracker.update_chaos_tome(
            chaos_level=3, permanent_modifiers={12: (modifier(300, 0.168), second, first)})
        self.assertEqual(counts(tracker), {12: 3})

    def test_new_pointer_at_same_position_is_a_new_roll(self):
        tracker = LiveRunTracker()
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (modifier(100, 0.168),)})
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={12: (modifier(200, 0.168),)})
        self.assertEqual(counts(tracker), {12: 2})

    def test_waiting_for_budget_follows_object_when_it_moves(self):
        tracker = LiveRunTracker()
        first, pending = modifier(100, 0.168), modifier(200, 0.336)
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (first, pending)})
        tracker.update_chaos_tome(chaos_level=2, permanent_modifiers={12: (pending, first)})
        self.assertEqual(counts(tracker), {12: 2})
        self.assertAlmostEqual(tracker.chaos_tome_snapshot().stats[0].value, 0.504)

    def test_nearby_values_are_rejected_with_a_large_roll_budget(self):
        for value in (0.167, 0.169, 0.1679, 0.335, 0.337):
            with self.subTest(value=value):
                tracker = LiveRunTracker()
                tracker.update_chaos_tome(chaos_level=100, permanent_modifiers={12: (modifier(100, value),)})
                self.assertEqual(counts(tracker), {})

    def test_legal_fingerprints_survive_float32_rounding(self):
        for stat_id, fingerprints in CHAOS_FINGERPRINTS.items():
            for value in fingerprints:
                with self.subTest(stat_id=stat_id, value=value):
                    rounded = struct.unpack("<f", struct.pack("<f", value))[0]
                    self.assertEqual(looks_like_chaos_value(stat_id, rounded), 1)

    def test_two_float32_ulps_are_allowed_but_not_a_thousandth(self):
        bits = struct.unpack("<I", struct.pack("<f", 0.168))[0]
        for offset in (-2, -1, 0, 1, 2):
            value = struct.unpack("<f", struct.pack("<I", bits + offset))[0]
            self.assertEqual(looks_like_chaos_value(12, value), 1)
        self.assertEqual(looks_like_chaos_value(12, 0.167), 0)

    def test_nonfinite_values_do_not_block_a_later_valid_read(self):
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                self.assertEqual(looks_like_chaos_value(12, value), 0)
                tracker = LiveRunTracker()
                tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (modifier(100, value),)})
                tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (modifier(100, 0.168),)})
                self.assertEqual(counts(tracker), {12: 1})

    def test_new_run_does_not_keep_pointer_baselines(self):
        from core.tracker.snapshots import LiveRunSnapshot
        tracker = LiveRunTracker()
        tracker.update(LiveRunSnapshot(captured_at=1, stats={}, game_time_seconds=100))
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (modifier(100, 0.168),)})
        tracker.update(LiveRunSnapshot(captured_at=2, stats={}, game_time_seconds=1))
        tracker.update_chaos_tome(chaos_level=1, permanent_modifiers={12: (modifier(100, 0.168),)})
        self.assertEqual(counts(tracker), {12: 1})


if __name__ == "__main__":
    unittest.main()
