from __future__ import annotations

import src

import unittest
from types import SimpleNamespace

from core.tracker.chaos import CHAOS_FINGERPRINTS, CHAOS_TOME_GAME_STAT_ORDER
from ui.tabs.player_stats.stat_cards import (
    chaos_average_roll_quality,
    chaos_roll_quality_color,
    chaos_stats_by_roll_count,
)


class ChaosStatCardsTests(unittest.TestCase):
    def test_stats_are_sorted_by_roll_count_then_game_order(self) -> None:
        low_game_position = min(CHAOS_TOME_GAME_STAT_ORDER, key=CHAOS_TOME_GAME_STAT_ORDER.get)
        high_game_position = max(CHAOS_TOME_GAME_STAT_ORDER, key=CHAOS_TOME_GAME_STAT_ORDER.get)
        stats = (
            SimpleNamespace(stat_id=high_game_position, label="Later", rolls=2),
            SimpleNamespace(stat_id=low_game_position, label="Earlier", rolls=2),
            SimpleNamespace(stat_id=30, label="Most", rolls=4),
        )

        ordered = chaos_stats_by_roll_count(SimpleNamespace(stats=stats))

        self.assertEqual([stat.label for stat in ordered], ["Most", "Earlier", "Later"])

    def test_average_quality_uses_the_stat_specific_roll_range(self) -> None:
        stat_id = 30
        minimum = min(CHAOS_FINGERPRINTS[stat_id])
        maximum = max(CHAOS_FINGERPRINTS[stat_id])

        low = SimpleNamespace(stat_id=stat_id, value=minimum * 2, rolls=2)
        high = SimpleNamespace(stat_id=stat_id, value=maximum * 3, rolls=3)

        self.assertAlmostEqual(chaos_average_roll_quality(low), 0.0)
        self.assertAlmostEqual(chaos_average_roll_quality(high), 1.0)
        self.assertEqual(chaos_roll_quality_color(chaos_average_roll_quality(low)), "#98A7BA")
        self.assertEqual(chaos_roll_quality_color(chaos_average_roll_quality(high)), "#FACC15")

    def test_quality_is_unavailable_without_rolls_or_known_fingerprints(self) -> None:
        self.assertIsNone(
            chaos_average_roll_quality(SimpleNamespace(stat_id=30, value=1.0, rolls=0))
        )
        self.assertIsNone(
            chaos_average_roll_quality(SimpleNamespace(stat_id=999, value=1.0, rolls=1))
        )


if __name__ == "__main__":
    unittest.main()
