from __future__ import annotations

import unittest

import logic


class LogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self.template = {
            "id": 1,
            "name": "MICRO",
            "sm_total": 10,
            "micro": 1,
            "boss": 2,
        }
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

    def test_template_with_one_microwave_requirement_does_not_match_zero_microwaves(self) -> None:
        stats = {
            "Shady Guy": 10,
            "Moais": 0,
            "Microwaves": 0,
            "Boss Curses": 2,
        }

        result = logic.find_matching_template(stats, ["MICRO"], [self.template])

        self.assertIsNone(result)

    def test_template_with_one_microwave_requirement_matches_one_microwave(self) -> None:
        stats = {
            "Shady Guy": 10,
            "Moais": 0,
            "Microwaves": 1,
            "Boss Curses": 2,
        }

        result = logic.find_matching_template(stats, ["MICRO"], [self.template])

        self.assertEqual(result, self.template)

    def test_scores_perfect_does_not_treat_zero_microwaves_as_one(self) -> None:
        stats = {
            "Shady Guy": 8,
            "Moais": 2,
            "Microwaves": 0,
            "Boss Curses": 3,
            "Magnet Shrines": 0,
        }

        result = logic.evaluate_map_by_scores(stats, self.scores_config)

        self.assertIsNone(result)

    def test_scores_perfect_allows_one_microwave_with_required_stats(self) -> None:
        stats = {
            "Shady Guy": 8,
            "Moais": 2,
            "Microwaves": 1,
            "Boss Curses": 3,
            "Magnet Shrines": 0,
        }

        result = logic.evaluate_map_by_scores(stats, self.scores_config)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Perfect")

    def test_score_uses_two_microwave_multiplier_for_more_than_two_microwaves(self) -> None:
        stats = {
            "Shady Guy": 1,
            "Moais": 1,
            "Microwaves": 3,
            "Boss Curses": 1,
            "Magnet Shrines": 2,
        }

        score = logic.calculate_score(stats, self.scores_config)

        self.assertEqual(score, 8.75)


if __name__ == "__main__":
    unittest.main()
