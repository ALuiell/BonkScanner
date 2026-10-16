"""Peak RPM measures consecutive complete cycles, even in a short search."""

from __future__ import annotations

import unittest

import src  # noqa: F401  -- path bootstrap

from app.reroll_rate import RerollCyclePeak


class RerollCyclePeakTests(unittest.TestCase):
    def test_first_peak_needs_ten_loaded_cycles_and_no_minute_wait(self) -> None:
        peak = RerollCyclePeak()
        peak.start()
        peak.map_ready(100.0)  # Initial map and armed time are not rerolls.
        for index in range(1, 10):
            peak.restarted()
            peak.map_ready(100.0 + index * 0.5)
        self.assertIsNone(peak.maximum)
        peak.restarted()
        self.assertIsNone(peak.maximum)  # Reset accepted, loading not finished.
        peak.map_ready(105.0)
        self.assertEqual(peak.maximum, 120.0)

    def test_slow_cycle_is_included_in_the_average(self) -> None:
        peak = RerollCyclePeak()
        peak.map_ready(0.0)
        for index in range(1, 10):
            peak.restarted()
            peak.map_ready(index * 0.5)
        peak.restarted()
        peak.map_ready(5.3)
        self.assertAlmostEqual(peak.maximum, 600.0 / 5.3)

    def test_window_slides_and_slower_cycles_do_not_reduce_the_peak(self) -> None:
        peak = RerollCyclePeak()
        now = 0.0
        peak.map_ready(now)
        for duration in [1.0] * 10 + [0.5] * 10 + [2.0] * 10:
            now += duration
            peak.restarted()
            peak.map_ready(now)
        self.assertEqual(peak.maximum, 120.0)

    def test_pause_preserves_peak_and_requires_a_new_complete_sequence(self) -> None:
        peak = RerollCyclePeak()
        peak.map_ready(0.0)
        for index in range(1, 11):
            peak.restarted()
            peak.map_ready(float(index))
        self.assertEqual(peak.maximum, 60.0)
        peak.restarted()
        peak.break_sequence()
        peak.map_ready(300.0)
        for index in range(1, 10):
            peak.restarted()
            peak.map_ready(300.0 + index * 0.25)
        self.assertEqual(peak.maximum, 60.0)
        peak.restarted()
        peak.map_ready(302.5)
        self.assertEqual(peak.maximum, 240.0)
        peak.start()
        self.assertIsNone(peak.maximum)

    def test_repeated_map_reads_without_restarts_cannot_create_a_peak(self) -> None:
        peak = RerollCyclePeak()
        for index in range(20):
            peak.map_ready(index * 0.01)
        self.assertIsNone(peak.maximum)

    def test_multiple_resets_without_loaded_maps_break_the_sequence(self) -> None:
        peak = RerollCyclePeak()
        peak.map_ready(0.0)
        for index in range(1, 10):
            peak.restarted()
            peak.map_ready(index * 0.5)
        peak.restarted()
        peak.restarted()
        peak.map_ready(5.0)
        self.assertIsNone(peak.maximum)

    def test_equal_or_backwards_timestamps_cannot_create_a_peak(self) -> None:
        for last_time in (4.5, 4.0):
            with self.subTest(last_time=last_time):
                peak = RerollCyclePeak()
                peak.map_ready(0.0)
                for index in range(1, 10):
                    peak.restarted()
                    peak.map_ready(index * 0.5)
                peak.restarted()
                peak.map_ready(last_time)
                self.assertIsNone(peak.maximum)
