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

    def make_scores_config(self, *, thresholds: dict[str, float], active_tiers: list[str]) -> dict:
        return {
            "weights": self.scores_config["weights"],
            "multipliers": self.scores_config["multipliers"],
            "thresholds": thresholds,
            "active_tiers": active_tiers,
        }

    def test_normalize_microwaves_clamps_to_supported_range(self) -> None:
        cases = {
            None: 1,
            0: 1,
            1: 1,
            2: 2,
            3: 2,
        }

        for raw_value, expected in cases.items():
            with self.subTest(raw_value=raw_value):
                self.assertEqual(logic.normalize_microwaves(raw_value), expected)

    def test_score_uses_default_weights_and_multipliers_when_config_is_empty(self) -> None:
        stats = {
            "Shady Guy": 2,
            "Moais": 3,
            "Microwaves": 2,
            "Boss Curses": 4,
            "Magnet Shrines": 1,
        }

        score = logic.calculate_score(stats, {})

        self.assertEqual(score, 21.875)

    def test_score_caps_magnet_shrines_at_two(self) -> None:
        stats = {
            "Shady Guy": 0,
            "Moais": 0,
            "Microwaves": 1,
            "Boss Curses": 0,
            "Magnet Shrines": 5,
        }

        score = logic.calculate_score(stats, self.scores_config)

        self.assertEqual(score, 1.0)

    def test_score_uses_one_microwave_multiplier_when_microwaves_are_missing_or_zero(self) -> None:
        stats = {
            "Shady Guy": 2,
            "Moais": 1,
            "Boss Curses": 1,
            "Magnet Shrines": 2,
        }
        zero_microwave_stats = {
            **stats,
            "Microwaves": 0,
        }

        missing_score = logic.calculate_score(stats, self.scores_config)
        zero_score = logic.calculate_score(zero_microwave_stats, self.scores_config)

        self.assertEqual(missing_score, 9.0)
        self.assertEqual(zero_score, 9.0)

    def test_score_uses_custom_weights_and_multipliers(self) -> None:
        stats = {
            "Shady Guy": 2,
            "Moais": 1,
            "Microwaves": 2,
            "Boss Curses": 3,
            "Magnet Shrines": 4,
        }
        config = {
            "weights": {
                "moais": 10.0,
                "shady": 1.5,
                "boss": 2.0,
                "magnet": 4.0,
            },
            "multipliers": {
                "microwave": {
                    "1": 0.75,
                    "2": 2.0,
                },
            },
        }

        score = logic.calculate_score(stats, config)

        self.assertEqual(score, 54.0)

    def test_template_with_one_microwave_requirement_matches_zero_or_missing_microwaves(self) -> None:
        stats = {
            "Shady Guy": 10,
            "Moais": 0,
            "Microwaves": 0,
            "Boss Curses": 2,
        }
        missing_microwave_stats = {
            "Shady Guy": 10,
            "Moais": 0,
            "Boss Curses": 2,
        }

        zero_result = logic.find_matching_template(stats, ["MICRO"], [self.template])
        missing_result = logic.find_matching_template(missing_microwave_stats, ["MICRO"], [self.template])

        self.assertEqual(zero_result, self.template)
        self.assertEqual(missing_result, self.template)

    def test_template_with_one_microwave_requirement_matches_one_microwave(self) -> None:
        stats = {
            "Shady Guy": 10,
            "Moais": 0,
            "Microwaves": 1,
            "Boss Curses": 2,
        }

        result = logic.find_matching_template(stats, ["MICRO"], [self.template])

        self.assertEqual(result, self.template)

    def test_scores_perfect_treats_zero_microwaves_as_one_with_required_stats(self) -> None:
        stats = {
            "Shady Guy": 8,
            "Moais": 2,
            "Microwaves": 0,
            "Boss Curses": 3,
            "Magnet Shrines": 0,
        }

        result = logic.evaluate_map_by_scores(stats, self.scores_config)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Perfect")

    def test_scores_perfect_zero_microwaves_still_needs_one_microwave_special_stats(self) -> None:
        stats = {
            "Shady Guy": 10,
            "Moais": 10,
            "Microwaves": 0,
            "Boss Curses": 1,
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

    def test_scores_returns_highest_active_tier(self) -> None:
        stats = {
            "Shady Guy": 10,
            "Moais": 10,
            "Microwaves": 2,
            "Boss Curses": 10,
            "Magnet Shrines": 2,
        }
        config = self.make_scores_config(
            thresholds={
                "Light": 1.0,
                "Good": 2.0,
                "Perfect": 3.0,
                "Perfect+": 4.0,
            },
            active_tiers=["Light", "Good", "Perfect", "Perfect+"],
        )

        result = logic.evaluate_map_by_scores(stats, config)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Perfect+")
        self.assertEqual(result["color"], "LIGHTRED_EX")

    def test_scores_skips_inactive_higher_tier(self) -> None:
        stats = {
            "Shady Guy": 10,
            "Moais": 10,
            "Microwaves": 2,
            "Boss Curses": 10,
            "Magnet Shrines": 2,
        }
        config = self.make_scores_config(
            thresholds={
                "Light": 1.0,
                "Good": 2.0,
                "Perfect": 3.0,
                "Perfect+": 4.0,
            },
            active_tiers=["Good"],
        )

        result = logic.evaluate_map_by_scores(stats, config)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Good")

    def test_scores_returns_none_when_score_is_below_threshold(self) -> None:
        stats = {
            "Shady Guy": 1,
            "Moais": 1,
            "Microwaves": 2,
            "Boss Curses": 1,
            "Magnet Shrines": 0,
        }
        config = self.make_scores_config(
            thresholds={"Light": 100.0},
            active_tiers=["Light"],
        )

        result = logic.evaluate_map_by_scores(stats, config)

        self.assertIsNone(result)

    def test_scores_perfect_plus_requires_two_microwaves(self) -> None:
        stats = {
            "Shady Guy": 10,
            "Moais": 10,
            "Microwaves": 1,
            "Boss Curses": 10,
            "Magnet Shrines": 2,
        }
        config = self.make_scores_config(
            thresholds={"Perfect+": 1.0},
            active_tiers=["Perfect+"],
        )

        result = logic.evaluate_map_by_scores(stats, config)

        self.assertIsNone(result)

    def test_scores_perfect_plus_treats_more_than_two_microwaves_as_two(self) -> None:
        stats = {
            "Shady Guy": 10,
            "Moais": 10,
            "Microwaves": 3,
            "Boss Curses": 10,
            "Magnet Shrines": 2,
        }
        config = self.make_scores_config(
            thresholds={"Perfect+": 1.0},
            active_tiers=["Perfect+"],
        )

        result = logic.evaluate_map_by_scores(stats, config)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Perfect+")

    def test_scores_perfect_with_two_microwaves_does_not_require_extra_stats(self) -> None:
        stats = {
            "Shady Guy": 1,
            "Moais": 1,
            "Microwaves": 2,
            "Boss Curses": 0,
            "Magnet Shrines": 0,
        }
        config = self.make_scores_config(
            thresholds={"Perfect": 1.0},
            active_tiers=["Perfect"],
        )

        result = logic.evaluate_map_by_scores(stats, config)

        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "Perfect")

    def test_scores_good_and_light_use_score_without_special_rules(self) -> None:
        good_stats = {
            "Shady Guy": 0,
            "Moais": 0,
            "Boss Curses": 2,
            "Magnet Shrines": 0,
        }
        light_stats = {
            "Shady Guy": 0,
            "Moais": 0,
            "Boss Curses": 1,
            "Magnet Shrines": 0,
        }

        good_result = logic.evaluate_map_by_scores(
            good_stats,
            self.make_scores_config(thresholds={"Good": 2.0}, active_tiers=["Good"]),
        )
        light_result = logic.evaluate_map_by_scores(
            light_stats,
            self.make_scores_config(thresholds={"Light": 1.0}, active_tiers=["Light"]),
        )

        self.assertIsNotNone(good_result)
        self.assertEqual(good_result["name"], "Good")
        self.assertIsNotNone(light_result)
        self.assertEqual(light_result["name"], "Light")

    def test_score_clamps_more_than_two_microwaves_to_two(self) -> None:
        stats = {
            "Shady Guy": 1,
            "Moais": 1,
            "Microwaves": 3,
            "Boss Curses": 1,
            "Magnet Shrines": 2,
        }
        two_microwave_stats = {
            **stats,
            "Microwaves": 2,
        }

        score = logic.calculate_score(stats, self.scores_config)
        two_microwave_score = logic.calculate_score(two_microwave_stats, self.scores_config)

        self.assertEqual(score, 8.75)
        self.assertEqual(score, two_microwave_score)

    def test_template_with_two_microwave_requirement_matches_more_than_two_microwaves(self) -> None:
        template = {
            "id": 1,
            "name": "TWO_MICRO",
            "micro": 2,
        }
        stats = {
            "Microwaves": 3,
        }

        result = logic.find_matching_template(stats, ["TWO_MICRO"], [template])

        self.assertEqual(result, template)

    def test_templates_are_checked_by_descending_id(self) -> None:
        low = {"id": 1, "name": "LOW", "sm_total": 1}
        high = {"id": 10, "name": "HIGH", "sm_total": 1}
        stats = {
            "Shady Guy": 1,
            "Moais": 0,
        }

        result = logic.find_matching_template(stats, ["LOW", "HIGH"], [low, high])

        self.assertEqual(result, high)

    def test_inactive_template_is_ignored(self) -> None:
        stats = {
            "Shady Guy": 10,
            "Moais": 0,
            "Microwaves": 1,
            "Boss Curses": 2,
        }

        result = logic.find_matching_template(stats, [], [self.template])

        self.assertIsNone(result)

    def test_each_template_requirement_can_block_match(self) -> None:
        base_stats = {
            "Shady Guy": 3,
            "Moais": 4,
            "Microwaves": 1,
            "Boss Curses": 2,
        }
        blocking_templates = [
            {"id": 1, "name": "SM", "sm_total": 8},
            {"id": 1, "name": "SHADY", "shady": 4},
            {"id": 1, "name": "MOAI", "moai": 5},
            {"id": 1, "name": "MICRO", "micro": 2},
            {"id": 1, "name": "BOSS", "boss": 3},
        ]

        for template in blocking_templates:
            with self.subTest(template=template["name"]):
                result = logic.find_matching_template(base_stats, [template["name"]], [template])
                self.assertIsNone(result)

    def test_template_without_requirements_matches_any_active_template(self) -> None:
        template = {"id": 1, "name": "ANY"}

        result = logic.find_matching_template({}, ["ANY"], [template])

        self.assertEqual(result, template)

    def test_conditions_met_reflects_matching_template_result(self) -> None:
        matching_stats = {
            "Shady Guy": 10,
            "Moais": 0,
            "Microwaves": 1,
            "Boss Curses": 2,
        }
        failing_stats = {
            **matching_stats,
            "Microwaves": 0,
            "Boss Curses": 1,
        }

        self.assertTrue(logic.conditions_met(matching_stats, ["MICRO"], [self.template]))
        self.assertFalse(logic.conditions_met(failing_stats, ["MICRO"], [self.template]))


if __name__ == "__main__":
    unittest.main()
