from __future__ import annotations

import unittest

import src  # noqa: F401 -- path bootstrap

from app import config


class AutomaticScoreThresholdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.multipliers = {"microwave": {"1": 1.0, "2": 1.25}}
        self.default_weights = {
            "moais": 3.0,
            "shady": 2.0,
            "boss": 1.0,
            "magnet": 0.5,
            "challenges": 0.0,
        }

    def test_challenge_default_preserves_existing_thresholds(self) -> None:
        self.assertEqual(
            config.calculate_auto_thresholds(self.default_weights, self.multipliers),
            {"Light": 14.0, "Good": 20.0, "Perfect": 25.0, "Perfect+": 30.0},
        )

    def test_negative_points_do_not_lower_automatic_thresholds(self) -> None:
        zeroed = {**self.default_weights, "magnet": 0.0, "challenges": 0.0}
        penalties = {**self.default_weights, "magnet": -20.0, "challenges": -30.0}

        self.assertEqual(
            config.calculate_auto_thresholds(penalties, self.multipliers),
            config.calculate_auto_thresholds(zeroed, self.multipliers),
        )

    def test_positive_challenge_points_raise_automatic_thresholds(self) -> None:
        rewarded = {**self.default_weights, "challenges": 3.0}

        self.assertGreater(
            config.calculate_auto_thresholds(rewarded, self.multipliers)["Perfect+"],
            config.calculate_auto_thresholds(self.default_weights, self.multipliers)["Perfect+"],
        )

    def test_no_positive_points_collapse_to_zero_for_ui_validation(self) -> None:
        penalties = {key: -1.0 for key in self.default_weights}

        self.assertEqual(
            config.calculate_auto_thresholds(penalties, self.multipliers),
            {"Light": 0.0, "Good": 0.0, "Perfect": 0.0, "Perfect+": 0.0},
        )


if __name__ == "__main__":
    unittest.main()
