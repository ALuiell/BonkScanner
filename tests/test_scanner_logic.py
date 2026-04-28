from __future__ import annotations

import types
import unittest

from game_data import EItem, MapStat
import logic
import scanner_logic


class ScannerLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scores_config = {
            "weights": {
                "moais": 3.0,
                "shady": 2.0,
                "boss": 1.0,
                "magnet": 0.5,
            },
            "multipliers": {
                "microwave": {
                    "1": 1.0,
                    "2": 1.25,
                },
            },
            "thresholds": {
                "Perfect": 25.0,
            },
            "active_tiers": ["Perfect"],
        }

    def test_item_name_prefers_item_name_attribute(self) -> None:
        item = types.SimpleNamespace(name="SoulHarvester")

        self.assertEqual(scanner_logic.item_name(item), "SoulHarvester")

    def test_item_name_falls_back_to_string_conversion(self) -> None:
        item = 123

        self.assertEqual(scanner_logic.item_name(item), "123")

    def test_has_required_shady_guy_item_matches_known_required_item(self) -> None:
        items = [types.SimpleNamespace(name=EItem.SoulHarvester.name)]

        self.assertTrue(scanner_logic.has_required_shady_guy_item(items))

    def test_has_required_shady_guy_item_rejects_unrelated_items(self) -> None:
        items = [types.SimpleNamespace(name="Beacon"), types.SimpleNamespace(name="GymSauce")]

        self.assertFalse(scanner_logic.has_required_shady_guy_item(items))

    def test_shady_guy_count_reads_map_stat_max(self) -> None:
        raw_stats = {
            MapStat.SHADY_GUY: types.SimpleNamespace(max=4),
        }

        self.assertEqual(scanner_logic.shady_guy_count(raw_stats, {}), 4)

    def test_shady_guy_count_falls_back_to_adapted_stats(self) -> None:
        self.assertEqual(scanner_logic.shady_guy_count({}, {"Shady Guy": 3}), 3)

    def test_shady_guy_count_clamps_negative_and_invalid_values_to_zero(self) -> None:
        negative_raw_stats = {
            MapStat.SHADY_GUY: types.SimpleNamespace(max=-2),
        }
        invalid_raw_stats = {
            MapStat.SHADY_GUY: "abc",
        }

        self.assertEqual(scanner_logic.shady_guy_count(negative_raw_stats, {}), 0)
        self.assertEqual(scanner_logic.shady_guy_count(invalid_raw_stats, {}), 0)
        self.assertEqual(scanner_logic.shady_guy_count({}, {"Shady Guy": "bad"}), 0)

    def test_format_stats_preserves_gui_text_shape_and_normalized_microwave_score(self) -> None:
        stats = {
            "Shady Guy": 2,
            "Moais": 3,
            "Microwaves": 0,
            "Boss Curses": 4,
            "Magnet Shrines": 1,
        }

        formatted = scanner_logic.format_stats(stats, self.scores_config)

        self.assertEqual(
            formatted,
            "Shady: 2, Moai: 3, Microwaves: 1, Boss: 4, Magnet: 1, Score: 17.5",
        )

    def test_calculate_map_score_delegates_to_logic_calculate_score(self) -> None:
        stats = {
            "Shady Guy": 2,
            "Moais": 3,
            "Microwaves": 2,
            "Boss Curses": 4,
            "Magnet Shrines": 1,
        }

        self.assertEqual(
            scanner_logic.calculate_map_score(stats, self.scores_config),
            logic.calculate_score(stats, self.scores_config),
        )

    def test_evaluate_candidate_uses_template_matching_in_templates_mode(self) -> None:
        stats = {
            "Shady Guy": 8,
            "Moais": 2,
            "Microwaves": 1,
            "Boss Curses": 2,
        }
        templates = [
            {
                "id": 5,
                "name": "Perfect",
                "sm_total": 10,
                "micro": 1,
                "boss": 2,
                "color": "YELLOW",
            }
        ]

        result = scanner_logic.evaluate_candidate(
            stats,
            "templates",
            ["Perfect"],
            templates,
            self.scores_config,
        )

        self.assertEqual(result, templates[0])

    def test_evaluate_candidate_uses_score_evaluation_in_scores_mode(self) -> None:
        stats = {
            "Shady Guy": 8,
            "Moais": 2,
            "Microwaves": 1,
            "Boss Curses": 3,
            "Magnet Shrines": 0,
        }

        result = scanner_logic.evaluate_candidate(
            stats,
            "scores",
            ["unused"],
            [],
            self.scores_config,
        )

        self.assertEqual(result, logic.evaluate_map_by_scores(stats, self.scores_config))


if __name__ == "__main__":
    unittest.main()
