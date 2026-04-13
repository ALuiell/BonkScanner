from __future__ import annotations

import unittest

from game_data import MapStat, StatValue
from runtime_stats import adapt_map_stats, empty_runtime_stats


class RuntimeStatsTests(unittest.TestCase):
    def test_empty_runtime_stats_contains_all_known_labels(self) -> None:
        stats = empty_runtime_stats()

        self.assertEqual(stats["Boss Curses"], 0)
        self.assertEqual(stats["Shady Guy"], 0)
        self.assertEqual(len(stats), 10)

    def test_adapt_map_stats_uses_max_values_and_defaults_missing_to_zero(self) -> None:
        stats = adapt_map_stats(
            {
                MapStat.BOSS_CURSES: StatValue(current=3, max=5),
                MapStat.MICROWAVES: StatValue(current=2, max=2),
                MapStat.SHADY_GUY: StatValue(current=4, max=6),
            }
        )

        self.assertEqual(
            stats,
            {
                "Boss Curses": 5,
                "Challenges": 0,
                "Charge Shrines": 0,
                "Chests": 0,
                "Greed Shrines": 0,
                "Magnet Shrines": 0,
                "Microwaves": 2,
                "Moais": 0,
                "Pots": 0,
                "Shady Guy": 6,
            },
        )


if __name__ == "__main__":
    unittest.main()
