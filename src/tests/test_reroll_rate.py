"""The peak is a count in completed 60-second windows, not a startup estimate."""

from __future__ import annotations

import unittest

import src  # noqa: F401  -- path bootstrap

from app.reroll_rate import RollingRerollPeak


class RollingRerollPeakTests(unittest.TestCase):
    def test_first_complete_window_is_kept_when_the_ui_tick_is_late(self) -> None:
        peak = RollingRerollPeak()
        peak.start(0.0)
        peak.record(0.25)
        peak.record(1.0)
        self.assertIsNone(peak.sample(59.9))
        self.assertEqual(peak.sample(61.0), 2)
        self.assertEqual(peak.sample(120.0), 2)

    def test_new_sixty_second_peak_survives_idle_time_and_reset_clears_it(self) -> None:
        peak = RollingRerollPeak()
        peak.start(0.0)
        for moment in (1.0, 2.0, 3.0):
            peak.record(moment)
        self.assertEqual(peak.sample(60.0), 3)
        self.assertEqual(peak.sample(180.0), 3)
        for moment in (181.0, 182.0, 183.0, 184.0):
            peak.record(moment)
        self.assertEqual(peak.maximum, 4)
        self.assertEqual(peak.sample(300.0), 4)
        peak.start(300.0)
        self.assertIsNone(peak.maximum)
        self.assertEqual(peak.sample(360.0), 0)

    def test_exactly_expired_reroll_is_not_counted_twice(self) -> None:
        peak = RollingRerollPeak()
        peak.start(0.0)
        peak.record(1.0)
        peak.record(61.0)
        self.assertEqual(peak.maximum, 1)
