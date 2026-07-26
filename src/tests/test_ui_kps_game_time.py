"""Instant KPS is published on ``run_timer`` second-crossings, over a fixed
~1 game-second window.

Every case here fails against the pre-change 0.9/1.2 s gate, which is why it
is a new file: the two existing tests over this path in
``test_live_run_tracker.py`` pass both before and after the change and prove
nothing about it.  Coverage sits at the ``combat.py`` level, where the second
cursor and the sample history are directly inspectable -- ``track_ui_kps`` had
no unit coverage there at all.

Design: docs/updates/functional_updates.md, "Game-Time Synchronized KPS
Calculation".
"""
from __future__ import annotations

import src  # noqa: F401  -- puts `src/` on sys.path regardless of collection order

import unittest

from core.tracker import combat


def _feed(samples: list[tuple[float, int]]) -> combat._CombatState:
    state = combat._CombatState()
    for game_time_seconds, kills in samples:
        combat.track_kills(state, game_time_seconds, kills)
    return state


class UiKpsGameTimeTest(unittest.TestCase):
    def test_skipped_second_still_publishes_a_rate(self) -> None:
        """The current code loses this tick outright and rebases its baseline."""
        state = _feed([(100.0, 1_000), (100.5, 1_100), (102.4, 1_400)])

        # Baseline is the newest sample at or before 102.4 - 1.0 + 0.05 = 101.45,
        # i.e. (100.5, 1_100): 300 kills over 1.9 s.
        self.assertEqual(state.ui_kps_value, 158)
        self.assertEqual(state.ui_kps_second, 102)

    def test_late_crossing_does_not_shrink_the_window(self) -> None:
        """The case that rejects a baseline re-anchored to the publishing sample.

        101.98 publishes and 102.48 publishes again 0.5 s later.  Measuring the
        second one over that 0.5 s doubles the noise of every kill -- measured
        live at 567 KPS against 352 over the same fight.
        """
        state = combat._CombatState()
        combat.track_kills(state, 100.0, 1_000)
        combat.track_kills(state, 100.5, 1_100)
        combat.track_kills(state, 101.98, 1_400)
        first_published = state.ui_kps_value

        combat.track_kills(state, 102.48, 1_500)

        # 100 kills over the 0.5 s between the two publishing samples would read
        # 200; the window must instead reach back past the 1.0 s mark.
        self.assertNotEqual(state.ui_kps_value, 200)
        self.assertEqual(state.ui_kps_value, round(400 / 1.98))
        self.assertEqual(first_published, round(300 / 1.48))

    def test_tolerance_admits_a_near_miss(self) -> None:
        """A sample 2 ms short of the mark beats one 1.498 s back."""
        state = _feed([(100.0, 1_000), (100.502, 1_100), (101.5, 1_400)])

        # Cutoff 100.55; (100.502, 1_100) qualifies: 300 kills over 0.998 s.
        self.assertEqual(state.ui_kps_value, round(300 / 0.998))

    def test_tolerance_does_not_shrink_the_window_at_fine_spacing(self) -> None:
        """At 100 ms polling the baseline must sit at ~t-1.0, not at ~t-0.9.

        This is the case that failed at ``TOLERANCE = 0.1``.
        """
        samples = [(100.0 + 0.1 * i, 1_000 + 10 * i) for i in range(11)]
        state = _feed(samples)

        # Newest sample published at 101.0; baseline must be 100.0, giving a
        # 1.0 s window and 100 kills, not 100.1 with 90 kills over 0.9 s.
        self.assertEqual(state.ui_kps_value, 100)

    def test_window_not_yet_filled_publishes_nothing(self) -> None:
        state = _feed([(100.9, 1_000), (101.4, 1_100)])

        self.assertIsNone(state.ui_kps_value)
        self.assertEqual(state.ui_kps_second, 101)

    def test_pause_neither_publishes_nor_advances_the_cursor(self) -> None:
        state = _feed([(100.0, 1_000), (100.5, 1_100), (101.0, 1_300)])
        self.assertEqual(state.ui_kps_value, 300)

        combat.track_kills(state, 101.0, 1_310)
        combat.track_kills(state, 101.0, 1_320)

        self.assertEqual(state.ui_kps_value, 300)
        self.assertEqual(state.ui_kps_second, 101)

    def test_rollback_clears_the_cursor_and_the_value(self) -> None:
        state = _feed([(100.0, 1_000), (100.5, 1_100), (101.0, 1_300)])
        self.assertEqual(state.ui_kps_value, 300)

        combat.track_kills(state, 3.0, 5)

        self.assertIsNone(state.ui_kps_value)
        self.assertEqual(state.ui_kps_second, 3)
        self.assertEqual(list(state.recent_kills_history), [(3.0, 5)])

    def test_kill_count_decrease_clears_the_cursor_and_the_value(self) -> None:
        state = _feed([(100.0, 1_000), (100.5, 1_100), (101.0, 1_300)])
        self.assertEqual(state.ui_kps_value, 300)

        combat.track_kills(state, 101.5, 0)

        self.assertIsNone(state.ui_kps_value)
        self.assertEqual(state.ui_kps_second, 101)
        self.assertEqual(list(state.recent_kills_history), [(101.5, 0)])

    def test_next_run_starts_from_an_empty_window(self) -> None:
        state = _feed([(100.0, 1_000), (100.5, 1_100), (101.0, 1_300)])

        combat.reset(state)
        combat.track_kills(state, 0.5, 10)
        combat.track_kills(state, 1.0, 40)

        # One sample inside the window is not a window: nothing published.
        self.assertIsNone(state.ui_kps_value)

    def test_rate_is_floored_at_zero(self) -> None:
        state = _feed([(100.0, 1_000), (100.5, 1_000), (101.0, 1_000)])

        self.assertEqual(state.ui_kps_value, 0)
